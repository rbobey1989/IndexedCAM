"""Indexed machining Setup: one fixed B/C orientation and its operations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from IndexedCAM.Machine.bc_head import BCAngles, Vector, normalize, verify_solution
from IndexedCAM.Machine.bc_machine import BCMachine

DEFAULT_WCS = "G54"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LocalFrame:
    """Local XYZ frame of a Setup in part coordinates (Z = tool axis)."""

    origin: Vector
    x_axis: Vector
    y_axis: Vector
    z_axis: Vector


def _finite_vector(value: Sequence[float], what: str) -> Vector:
    if len(value) != 3 or not all(math.isfinite(float(v)) for v in value):
        raise ValueError("{} must be three finite numbers".format(what))
    return (float(value[0]), float(value[1]), float(value[2]))


@dataclass
class IndexedSetup:
    """Orientation setup for 3+2 machining on a B+C head.

    Stores only B and C (no A axis). ``normal`` is the unit tool-axis direction
    in part coordinates and must be consistent with ``b``/``c``. ``operations``
    holds the names of the CAM operations run in this orientation; they are
    interpreted in the local frame. ``metadata`` must be JSON-serializable.
    """

    name: str
    normal: Vector
    b: float
    c: float
    wcs: str = DEFAULT_WCS
    origin: Vector = (0.0, 0.0, 0.0)
    operations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("setup name must not be empty")
        if not self.wcs.strip():
            raise ValueError("wcs must not be empty")
        normal = _finite_vector(self.normal, "normal")
        if abs(math.sqrt(sum(v * v for v in normal)) - 1.0) > 1e-12:
            normal = normalize(normal)
        self.normal = normal
        self.origin = _finite_vector(self.origin, "origin")
        if not (math.isfinite(self.b) and math.isfinite(self.c)):
            raise ValueError("B and C must be finite")
        if not verify_solution(self.normal, BCAngles(self.b, self.c), tolerance=1e-6):
            raise ValueError("B/C do not align the tool axis with the normal")
        self.operations = list(self.operations)
        self.metadata = dict(self.metadata)

    @property
    def angles(self) -> BCAngles:
        return BCAngles(self.b, self.c)

    def local_frame(self) -> LocalFrame:
        """Local frame from Rz(C) @ Ry(B) (columns X, Y, Z), ignoring limits."""
        sb, cb = math.sin(math.radians(self.b)), math.cos(math.radians(self.b))
        sc, cc = math.sin(math.radians(self.c)), math.cos(math.radians(self.c))
        return LocalFrame(
            origin=self.origin,
            x_axis=(cc * cb, sc * cb, -sb),
            y_axis=(-sc, cc, 0.0),
            z_axis=(cc * sb, sc * sb, cb),
        )

    def validate_for(self, machine: BCMachine) -> None:
        """Raise ValueError if the machine cannot reach this setup's B/C."""
        machine.validate(self.b, self.c)

    def add_operation(self, operation: str) -> None:
        operation = operation.strip()
        if not operation:
            raise ValueError("operation name must not be empty")
        if operation in self.operations:
            raise ValueError("operation already in setup: {}".format(operation))
        self.operations.append(operation)

    def remove_operation(self, operation: str) -> None:
        try:
            self.operations.remove(operation)
        except ValueError:
            raise ValueError("operation not in setup: {}".format(operation)) from None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable representation."""
        return {
            "version": SCHEMA_VERSION,
            "name": self.name,
            "normal": list(self.normal),
            "b": self.b,
            "c": self.c,
            "wcs": self.wcs,
            "origin": list(self.origin),
            "operations": list(self.operations),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IndexedSetup":
        version = data.get("version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ValueError("unsupported setup schema version: {}".format(version))
        try:
            return cls(
                name=data["name"],
                normal=tuple(data["normal"]),  # type: ignore[arg-type]
                b=float(data["b"]),
                c=float(data["c"]),
                wcs=data.get("wcs", DEFAULT_WCS),
                origin=tuple(data.get("origin", (0.0, 0.0, 0.0))),  # type: ignore[arg-type]
                operations=list(data.get("operations", [])),
                metadata=dict(data.get("metadata", {})),
            )
        except KeyError as error:
            raise ValueError("missing setup field: {}".format(error.args[0])) from None
