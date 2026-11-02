"""Coin3D visualization of a Setup's local XYZ frame in the 3D view.

The math helpers are pure Python; pivy/Coin3D is imported only when a triad is
actually shown, so this module can be imported and tested without FreeCAD.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

from IndexedCAM.Core.indexed_setup import LocalFrame
from IndexedCAM.Core.local_placement import Quaternion, frame_to_quaternion

__all__ = ["frame_to_quaternion"]

AXIS_COLORS = ((1.0, 0.0, 0.0), (0.0, 0.8, 0.0), (0.0, 0.2, 1.0))
AXIS_LABELS = ("X", "Y", "Z")
DEFAULT_SIZE = 20.0


def suggested_size(face_area: float) -> float:
    """Triad axis length derived from a face area (fallback if unusable)."""
    if not math.isfinite(face_area) or face_area <= 0.0:
        return DEFAULT_SIZE
    return max(1.0, 0.5 * math.sqrt(face_area))


def build_triad_node(frame: LocalFrame, size: float = DEFAULT_SIZE) -> Any:
    """Build a Coin3D SoSeparator drawing the frame's X/Y/Z axes with labels."""
    from pivy import coin

    if not math.isfinite(size) or size <= 0.0:
        raise ValueError("triad size must be positive and finite")

    root = coin.SoSeparator()
    root.setName("IndexedCAM_Triad")

    transform = coin.SoTransform()
    transform.translation.setValue(*frame.origin)
    transform.rotation.setValue(*frame_to_quaternion(frame))
    root.addChild(transform)

    style = coin.SoDrawStyle()
    style.lineWidth = 3
    root.addChild(style)
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    root.addChild(light)

    tips = ((size, 0.0, 0.0), (0.0, size, 0.0), (0.0, 0.0, size))
    for color, label, tip in zip(AXIS_COLORS, AXIS_LABELS, tips):
        axis = coin.SoSeparator()
        material = coin.SoBaseColor()
        material.rgb.setValue(*color)
        axis.addChild(material)
        points = coin.SoCoordinate3()
        points.point.setValues(0, 2, [(0.0, 0.0, 0.0), tip])
        axis.addChild(points)
        axis.addChild(coin.SoLineSet())
        label_position = coin.SoTranslation()
        label_position.translation.setValue(*(1.08 * v for v in tip))
        axis.addChild(label_position)
        text = coin.SoText2()
        text.string = label
        axis.addChild(text)
        root.addChild(axis)
    return root


class TriadView:
    """Shows at most one triad in a 3D view, replacing the previous one."""

    def __init__(self, view: Any = None) -> None:
        self._view = view
        self._node: Optional[Any] = None

    def _scene(self) -> Any:
        view = self._view
        if view is None:
            import FreeCADGui

            view = FreeCADGui.ActiveDocument.ActiveView
        return view.getSceneGraph()

    def show(self, frame: LocalFrame, size: float = DEFAULT_SIZE) -> None:
        node = build_triad_node(frame, size)
        self.clear()
        scene = self._scene()
        scene.addChild(node)
        self._node = node
        self._scene_ref = scene

    def clear(self) -> None:
        if self._node is not None:
            self._scene_ref.removeChild(self._node)
            self._node = None

    @property
    def visible(self) -> bool:
        return self._node is not None
