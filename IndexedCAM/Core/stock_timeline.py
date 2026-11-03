"""Stock removal along the preview clips.

Operation clips carve a ``VoxelStock`` with the tool of their operation at the
B/C of their Setup; transition clips remove nothing. Snapshots at the start of
each clip let the preview jump to any clip and frame, forward or backward.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from IndexedCAM.Core.preview import OPERATION, Clip
from IndexedCAM.Core.voxel_stock import ToolProfile, VoxelStock
from IndexedCAM.Machine.bc_head import bc_to_normal


class StockTimeline:
    def __init__(self, stock: VoxelStock, clips: Sequence[Clip]) -> None:
        self._stock = stock
        self._clips = list(clips)
        self._initial = stock.snapshot()
        self._starts: List[Optional[np.ndarray]] = [self._initial] + [None] * len(self._clips)
        self._at: Optional[tuple] = None  # (clip, frame) the stock currently shows

    @property
    def stock(self) -> VoxelStock:
        return self._stock

    def _profile(self, clip: Clip) -> ToolProfile:
        cutter = clip.envelope.cutter
        return ToolProfile.cylinder(cutter.radius, cutter.length)

    def _carve(self, clip: Clip, first: int, last: int) -> None:
        """Carve frames ``first``..``last`` (inclusive) of an operation clip."""
        if clip.kind != OPERATION or not clip.frames:
            return
        profile = self._profile(clip)
        for index in range(max(first, 0), min(last, len(clip.frames) - 1) + 1):
            frame = clip.frames[index]
            axis = bc_to_normal(frame.b, frame.c)
            if index == 0:
                self._stock.carve(frame.tip, axis, profile)
            else:
                self._stock.carve_segment(clip.frames[index - 1].tip, frame.tip, axis, profile)

    def _start_of(self, index: int) -> np.ndarray:
        """Snapshot before clip ``index``, simulating the clips before it once."""
        known = max(i for i in range(index + 1) if self._starts[i] is not None)
        for k in range(known, index):
            self._stock.restore(self._starts[k])
            self._carve(self._clips[k], 0, len(self._clips[k].frames))
            self._starts[k + 1] = self._stock.snapshot()
            self._at = None
        return self._starts[index]

    def show(self, clip_index: int, frame_index: int) -> VoxelStock:
        """Stock after ``frame_index`` of clip ``clip_index`` (the frame is included)."""
        if self._at is not None and self._at[0] == clip_index and self._at[1] <= frame_index:
            self._carve(self._clips[clip_index], self._at[1] + 1, frame_index)
        else:
            self._stock.restore(self._start_of(clip_index))
            self._carve(self._clips[clip_index], 0, frame_index)
        self._at = (clip_index, frame_index)
        return self._stock

    def final(self) -> VoxelStock:
        """Stock after the whole program."""
        last = len(self._clips) - 1
        return self.show(last, max(len(self._clips[last].frames) - 1, 0))
