"""Lightweight per-Setup copy of the part, placed in the Setup's local frame.

CAM needs the tool along +Z, so each Setup gets a ``LocalModel``: a
``Part::FeaturePython`` that shares the source geometry and only rotates it.
Its ``Shape`` is *transient* (not saved in the FCStd) and is rebuilt when the
document is restored, so Setups add almost nothing to the file size.
"""

from __future__ import annotations

from typing import Any

from IndexedCAM.Core import stale_paths
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import local_transform

OBJECT_PREFIX = "IndexedCAM_Local_"
GROUP = "IndexedCAM"


def local_placement(setup: IndexedSetup) -> Any:
    """FreeCAD Placement moving part coordinates into the Setup's frame."""
    import FreeCAD as App

    transform = local_transform(setup.local_frame())
    return App.Placement(App.Vector(*transform.translation), App.Rotation(*transform.rotation))


class LocalModel:
    """Proxy of the per-Setup model (Source link + persisted LocalPlacement)."""

    def __init__(self, obj: Any, source: Any, setup: IndexedSetup) -> None:
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Source", GROUP, "Part this model follows")
        obj.addProperty("App::PropertyString", "SetupName", GROUP, "Owning Setup")
        obj.addProperty(
            "App::PropertyPlacement", "LocalPlacement", GROUP, "Part to local frame"
        )
        obj.addProperty(
            "App::PropertyLength",
            "StockTop",
            GROUP,
            "Highest point of the rough stock along the Setup axis",
        )
        obj.setPropertyStatus("StockTop", "ReadOnly")
        obj.Source = source
        update(obj, setup)
        obj.setPropertyStatus("Shape", "Transient")

    def execute(self, obj: Any) -> None:
        import FreeCAD as App

        if obj.Source is None or obj.Source.Shape.isNull():
            return
        # The Setup frame is expressed in document coordinates, so the source's
        # own Placement (e.g. the Job's model clone is offset) must be kept.
        source_placement = obj.Source.Shape.Placement
        shape = obj.Source.Shape.copy(False)
        shape.Placement = App.Placement()
        obj.Shape = shape
        obj.Placement = obj.LocalPlacement.multiply(source_placement)
        obj.StockTop = _stock_envelope(obj)

    def onDocumentRestored(self, obj: Any) -> None:
        obj.Proxy = self
        obj.setPropertyStatus("Shape", "Transient")
        if not hasattr(obj, "StockTop"):
            # documents of the version that measured the heights on the part
            obj.addProperty(
                "App::PropertyLength",
                "StockTop",
                GROUP,
                "Highest point of the rough stock along the Setup axis",
            )
            obj.setPropertyStatus("StockTop", "ReadOnly")
        hide(obj)
        self.execute(obj)
        # the Shape is transient: it is rebuilt here, out of the recompute pass,
        # so an operation may still hold the Path saved with the previous one
        stale_paths.mark(obj.Document)

    def dumps(self) -> None:
        return None

    def loads(self, state: Any) -> None:
        return None


def stock_top(obj: Any) -> float:
    """Highest point of the rough stock along the Setup axis, in local Z.

    CAM's ``StockFromBase`` is the bounding box of the part, so the box of the
    source is (almost) the box of the stock; a bigger stock needs a bigger
    offset in the operation. The part itself is below its own box, never above.
    """
    stored = getattr(obj, "StockTop", None)
    if stored is not None:
        return float(stored)
    return _stock_envelope(obj)


def _stock_envelope(obj: Any) -> float:
    """``StockTop`` computed from the source (a document without the property)."""
    from IndexedCAM.Core.local_placement import LocalTransform, envelope_top

    box = obj.Source.Shape.BoundBox
    rotation = obj.LocalPlacement.Rotation.Q
    position = obj.LocalPlacement.Base
    transform = LocalTransform(tuple(rotation), (position.x, position.y, position.z))
    top = envelope_top(
        transform, (box.XMin, box.YMin, box.ZMin), (box.XMax, box.YMax, box.ZMax)
    )
    return max(top, float(obj.Shape.BoundBox.ZMax))


def update(obj: Any, setup: IndexedSetup) -> None:
    """Point an existing local model at (a possibly edited) Setup."""
    obj.SetupName = setup.name
    obj.LocalPlacement = local_placement(setup)
    obj.touch()


def rename(obj: Any, new_name: str) -> None:
    """Point the local model at the renamed Setup (the object Name is kept)."""
    obj.SetupName = new_name
    obj.Label = OBJECT_PREFIX + new_name


def create(document: Any, source: Any, setup: IndexedSetup) -> Any:
    """Create the local model of ``setup`` following ``source``."""
    obj = document.addObject("Part::FeaturePython", OBJECT_PREFIX + setup.name)
    obj.Label = OBJECT_PREFIX + setup.name
    LocalModel(obj, source, setup)
    hide(obj)
    return obj


def hide(obj: Any) -> None:
    """Local models are helpers for CAM: never shown in the 3D view by default."""
    obj.Visibility = False
    view = getattr(obj, "ViewObject", None)
    if view is not None:
        view.Visibility = False


def is_local_model(obj: Any) -> bool:
    """True for the lightweight model IndexedCAM adds for one orientation."""
    return hasattr(obj, "LocalPlacement") and hasattr(obj, "SetupName")


def find(owner: Any, setup_name: str) -> Any:
    """Local model of ``setup_name`` inside ``owner`` (a Job, group or document)."""
    key = setup_name.strip().casefold()
    for obj in _candidates(owner):
        if hasattr(obj, "LocalPlacement") and str(getattr(obj, "SetupName", "")).casefold() == key:
            return obj
    return None


def _candidates(owner: Any) -> Any:
    """Objects to search: the Job's model first, then its groups and the document."""
    model = getattr(owner, "Model", None)
    if model is not None:
        return list(getattr(model, "Group", ()))
    if hasattr(owner, "Objects"):
        return list(owner.Objects)
    return list(getattr(owner, "Group", ()))
