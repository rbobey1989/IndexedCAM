"""Voxel model of the stock, cut by a tool at any orientation.

The native CAM voxel simulator only removes material with a vertical tool.
``VoxelStock`` keeps one grid in part coordinates and carves it with the tool
axis of each indexed operation, so tilted cuts remove the right material.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

import numpy as np

Vector = Tuple[float, float, float]
MAX_CELLS = 2_000_000
PROFILE_STEP = 0.25


class ToolProfile:
    """Tool radius along its axis, measured from the tip (h = 0)."""

    def __init__(self, radii: Sequence[float], step: float = PROFILE_STEP) -> None:
        if len(radii) < 2 or step <= 0:
            raise ValueError("a tool profile needs at least two radii and a positive step")
        self.radii = np.asarray(radii, dtype=float)
        self.radii_sq = self.radii**2
        self.step = float(step)

    @classmethod
    def cylinder(cls, radius: float, length: float, step: float = PROFILE_STEP) -> "ToolProfile":
        count = max(2, int(math.ceil(length / step)) + 1)
        return cls([radius] * count, step)

    @classmethod
    def ball(cls, radius: float, length: float, step: float = PROFILE_STEP) -> "ToolProfile":
        count = max(2, int(math.ceil(length / step)) + 1)
        radii = []
        for i in range(count):
            h = i * step
            radii.append(math.sqrt(max(0.0, radius**2 - (radius - h) ** 2)) if h < radius else radius)
        return cls(radii, step)

    @property
    def length(self) -> float:
        return (len(self.radii) - 1) * self.step

    @property
    def max_radius(self) -> float:
        return float(self.radii.max())

    def truncated(self, length: float) -> "ToolProfile":
        count = max(2, min(len(self.radii), int(math.floor(length / self.step)) + 1))
        return ToolProfile(self.radii[:count], self.step)


class VoxelStock:
    """Boolean grid over a box; ``cells`` is True where material remains."""

    def __init__(self, low: Vector, high: Vector, resolution: float, max_cells: int = MAX_CELLS) -> None:
        size = [max(h - l, 1e-6) for l, h in zip(low, high)]
        wanted = max(resolution, 1e-6)
        self.resolution = max(wanted, (size[0] * size[1] * size[2] / max_cells) ** (1 / 3))
        shape = tuple(max(1, int(math.ceil(s / self.resolution - 1e-9))) for s in size)
        self.origin = np.asarray(low, dtype=float)
        self.cells = np.ones(shape, dtype=bool)
        self.version = 0

    def volume(self) -> float:
        return float(self.cells.sum()) * self.resolution**3

    def carve(self, tip: Vector, axis: Vector, profile: ToolProfile) -> None:
        """Remove the voxels whose centre lies inside the tool at ``tip`` pointing along ``axis``."""
        direction = np.asarray(axis, dtype=float)
        norm = np.linalg.norm(direction)
        if norm == 0:
            raise ValueError("the tool axis must not be zero")
        direction = direction / norm
        tip_v = np.asarray(tip, dtype=float)
        far = tip_v + direction * profile.length
        margin = profile.max_radius
        low = np.minimum(tip_v, far) - margin
        high = np.maximum(tip_v, far) + margin
        first = np.maximum(np.floor((low - self.origin) / self.resolution).astype(int), 0)
        last = np.minimum(np.ceil((high - self.origin) / self.resolution).astype(int) + 1, self.cells.shape)
        if np.any(last <= first):
            return
        window = tuple(slice(int(f), int(l)) for f, l in zip(first, last))
        centres = [
            self.origin[i] + (np.arange(first[i], last[i]) + 0.5) * self.resolution - tip_v[i]
            for i in range(3)
        ]
        dx, dy, dz = centres[0][:, None, None], centres[1][None, :, None], centres[2][None, None, :]
        h = dx * direction[0] + dy * direction[1] + dz * direction[2]
        rho_sq = dx * dx + dy * dy + dz * dz - h * h
        index = np.clip(np.rint(h / profile.step).astype(int), 0, len(profile.radii) - 1)
        inside = (h >= 0) & (h <= profile.length) & (rho_sq <= profile.radii_sq[index])
        if inside.any():
            self.cells[window][inside] = False
            self.version += 1

    def carve_segment(self, start: Vector, end: Vector, axis: Vector, profile: ToolProfile) -> None:
        """Sweep the tool from ``start`` to ``end`` in steps of one voxel."""
        a, b = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
        steps = max(1, int(math.ceil(np.linalg.norm(b - a) / self.resolution)))
        for k in range(steps + 1):
            self.carve(tuple(a + (b - a) * (k / steps)), axis, profile)

    def triangles(self) -> np.ndarray:
        """Boundary surface as an (N, 3, 3) array of outward-facing triangles."""
        padded = np.pad(self.cells, 1)
        chunks = []
        for axis in range(3):
            for sign in (1, -1):
                chunks.append(self._faces(padded, axis, sign))
        parts = [c for c in chunks if len(c)]
        return np.concatenate(parts) if parts else np.empty((0, 3, 3))

    def _faces(self, padded: np.ndarray, axis: int, sign: int) -> np.ndarray:
        window = [slice(1, -1)] * 3
        window[axis] = slice(2, None) if sign > 0 else slice(0, -2)
        exposed = self.cells & ~padded[tuple(window)]
        along = (axis + 1) % 3
        across = (axis + 2) % 3
        moved = np.moveaxis(exposed, along, -1)
        gap = np.zeros(moved.shape[:-1] + (1,), dtype=bool)
        starts = np.argwhere(moved & ~np.concatenate([gap, moved[..., :-1]], -1))
        ends = np.argwhere(moved & ~np.concatenate([moved[..., 1:], gap], -1))
        if len(starts) == 0:
            return np.empty((0, 3, 3))
        others = [d for d in range(3) if d != along]  # axes of moved[..., :-1], in order
        index = {others[0]: starts[:, 0], others[1]: starts[:, 1]}
        first, last = starts[:, 2], ends[:, 2] + 1
        plane = index[axis] + (1 if sign > 0 else 0)
        base = index[across]
        corners = np.empty((len(starts), 4, 3))
        for k, (m, t) in enumerate(((first, base), (last, base), (last, base + 1), (first, base + 1))):
            corners[:, k, axis] = plane
            corners[:, k, along] = m
            corners[:, k, across] = t
        world = self.origin + corners * self.resolution
        order = ([0, 1, 2], [0, 2, 3]) if sign > 0 else ([0, 2, 1], [0, 3, 2])
        return np.concatenate([world[:, order[0]], world[:, order[1]]])
