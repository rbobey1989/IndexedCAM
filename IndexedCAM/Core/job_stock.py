"""The Job's stock: the part, not the rotated copies of the orientations.

CAM derives the stock of a Job from the bounding box of ``Job.Model``
(``Path.Main.Stock.StockFromBase``). The local models of the orientations have
to live inside ``Job.Model`` so that CAM's area operations find their faces, so
without this the stock would grow with every orientation until it covered every
rotated copy of the part (62x42x32 -> 102x62x62 with two orientations).

``OrientationStock`` is the same stock (box around the part, same allowances,
same placement) but leaving the local models out of the bounding box. It is
installed as the proxy of the existing stock object, so the document keeps its
``Stock``: only the computation changes.
"""

from __future__ import annotations

from typing import Any, List

import FreeCAD
import Part
from Path.Main.Stock import StockFromBase, shapeBoundBox

from IndexedCAM.Core import stale_paths
from IndexedCAM.Core.local_model import is_local_model


class OrientationStock(StockFromBase):
    """CAM's stock from the model, ignoring the clones of the orientations."""

    def __init__(self) -> None:
        # the object already has every property: this replaces CAM's proxy
        pass

    def execute(self, obj: Any) -> None:
        """Same box as CAM's, from the part models only (see module docstring)."""
        models = part_models(obj)
        if not models:
            return
        box = shapeBoundBox(models)
        origin = FreeCAD.Vector(-obj.ExtXneg.Value, -obj.ExtYneg.Value, -obj.ExtZneg.Value)
        length = box.XLength + obj.ExtXneg.Value + obj.ExtXpos.Value
        width = box.YLength + obj.ExtYneg.Value + obj.ExtYpos.Value
        height = box.ZLength + obj.ExtZneg.Value + obj.ExtZpos.Value
        if height <= 0.0:
            obj.ExtZneg.Value = self.MinExtent
            height = box.ZLength + obj.ExtZneg.Value + obj.ExtZpos.Value
        shape = Part.makeBox(length, width, height, origin)
        shape.Placement = obj.Placement
        obj.Shape = shape


def part_models(stock: Any) -> List[Any]:
    """Objects of the stock's base that are not orientation local models."""
    group = getattr(getattr(stock, "Base", None), "Group", None)
    if group is None:
        return []
    return [obj for obj in group if not is_local_model(obj)]


def keep_part_stock(job: Any, refresh: bool = False) -> Any:
    """Make the Job's stock ignore the local models of the orientations.

    ``refresh`` recomputes the box even when the proxy is already installed,
    which repairs a stock that grew with an earlier version of the addon.
    """
    stock = getattr(job, "Stock", None)
    if stock is None or not isinstance(getattr(stock, "Proxy", None), StockFromBase):
        # a box, a cylinder or a custom stock does not depend on Job.Model
        return stock
    if not isinstance(stock.Proxy, OrientationStock):
        stock.Proxy = OrientationStock()
        refresh = True
    if refresh:
        # CAM's own task panel recomputes the stock this way: cheaper than a
        # whole-document recompute and it repairs an already grown stock
        previous = stock.Shape.BoundBox if not stock.Shape.isNull() else None
        stock.Proxy.execute(stock)
        if previous is None or not _same_box(previous, stock.Shape.BoundBox):
            stale_paths.mark(job.Document)
    return stock


def _same_box(first: Any, second: Any, tolerance: float = 1e-6) -> bool:
    """True if two bound boxes are the same box (within ``tolerance``)."""
    return all(
        abs(a - b) <= tolerance
        for a, b in zip(
            (first.XMin, first.YMin, first.ZMin, first.XMax, first.YMax, first.ZMax),
            (second.XMin, second.YMin, second.ZMin, second.XMax, second.YMax, second.ZMax),
        )
    )
