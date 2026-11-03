"""Coin3D view of the tool, holder and head at a pose, plus the path polyline.

``cylinder_orientation`` is pure math; Coin3D (pivy) is imported only when a
node is built. Nodes are temporary scene-graph children, never stored in the
document.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple

from IndexedCAM.Machine.bc_head import Vector
from IndexedCAM.Machine.envelope import HEAD, HOLDER, SHANK, TOOL, CylinderPose

COLORS: Dict[str, Tuple[float, float, float]] = {
    TOOL: (1.0, 0.65, 0.1),
    SHANK: (0.85, 0.8, 0.3),
    HOLDER: (0.6, 0.6, 0.65),
    HEAD: (0.35, 0.45, 0.6),
}
COLLISION_COLOR = (1.0, 0.1, 0.1)
PATH_COLOR = (0.1, 0.6, 1.0)
TRANSPARENCY = 0.35


def cylinder_orientation(start: Vector, end: Vector) -> Tuple[Vector, float, Vector]:
    """(midpoint, length, unit direction) of the cylinder axis ``start`` → ``end``."""
    delta = tuple(e - s for s, e in zip(start, end))
    length = math.sqrt(sum(d * d for d in delta))
    if length <= 0.0:
        raise ValueError("cylinder must have positive length")
    midpoint = tuple((s + e) / 2.0 for s, e in zip(start, end))
    return midpoint, length, tuple(d / length for d in delta)  # type: ignore[return-value]


TOOL_NAMES = ("tool", "shank")


def build_mesh_node(mesh: Any, tip: Vector, direction: Vector, collides: bool = False) -> Any:
    """The real tool shape placed with its tip at ``tip`` and axis along ``direction``."""
    import numpy as np
    from pivy import coin

    vertices, triangles = mesh
    part = coin.SoSeparator()
    transform = coin.SoTransform()
    transform.translation.setValue(*tip)
    transform.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 0, 1), coin.SbVec3f(*direction)))
    part.addChild(transform)
    material = coin.SoMaterial()
    material.diffuseColor.setValue(*(COLLISION_COLOR if collides else COLORS.get("tool", (0.7, 0.7, 0.7))))
    part.addChild(material)
    points = coin.SoCoordinate3()
    points.point.setValues(0, len(vertices), np.asarray(vertices, dtype=np.float32))
    part.addChild(points)
    faces = coin.SoIndexedFaceSet()
    indices = np.full((len(triangles), 4), -1, dtype=np.int32)
    indices[:, :3] = np.asarray(triangles, dtype=np.int32)
    faces.coordIndex.setValues(0, indices.size, indices.reshape(-1))
    part.addChild(faces)
    return part


def build_tool_node(poses: Sequence[CylinderPose], collides: bool = False, mesh: Any = None) -> Any:
    """SoSeparator with one translucent cylinder per pose (red when ``collides``).

    With ``mesh`` the cutting tool and its shank are drawn with the real tool
    shape instead of cylinders (holder and head stay cylinders).
    """
    from pivy import coin

    root = coin.SoSeparator()
    root.setName("IndexedCAM_Tool")
    if mesh is not None and poses and poses[0].name == "tool":
        tool = poses[0]
        _, length, direction = cylinder_orientation(tool.start, tool.end)
        root.addChild(build_mesh_node(mesh, tool.start, direction, collides))
        poses = [p for p in poses if p.name not in TOOL_NAMES]
    for pose in poses:
        middle, length, direction = cylinder_orientation(pose.start, pose.end)
        part = coin.SoSeparator()
        transform = coin.SoTransform()
        transform.translation.setValue(*middle)
        # SoCylinder's axis is +Y
        transform.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(*direction)))
        part.addChild(transform)
        material = coin.SoMaterial()
        material.diffuseColor.setValue(*(COLLISION_COLOR if collides else COLORS.get(pose.name, (0.7, 0.7, 0.7))))
        material.transparency.setValue(TRANSPARENCY)
        part.addChild(material)
        cylinder = coin.SoCylinder()
        cylinder.radius = pose.radius
        cylinder.height = length
        part.addChild(cylinder)
        root.addChild(part)
    return root


def build_path_node(points: Sequence[Vector], color: Tuple[float, float, float] = PATH_COLOR) -> Any:
    """SoSeparator with the path as a polyline."""
    from pivy import coin

    root = coin.SoSeparator()
    root.setName("IndexedCAM_Path")
    style = coin.SoDrawStyle()
    style.lineWidth = 2
    root.addChild(style)
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    root.addChild(light)
    paint = coin.SoBaseColor()
    paint.rgb.setValue(*color)
    root.addChild(paint)
    coordinates = coin.SoCoordinate3()
    coordinates.point.setValues(0, len(points), list(points))
    root.addChild(coordinates)
    line = coin.SoLineSet()
    line.numVertices.setValue(len(points))
    root.addChild(line)
    return root


STOCK_COLOR = (0.85, 0.6, 0.25)
STOCK_TRANSPARENCY = 0.35


def build_stock_node(triangles: Any) -> Any:
    """SoSeparator with the stock surface (an (N, 3, 3) array of triangles), flat shaded."""
    import numpy as np
    from pivy import coin

    root = coin.SoSeparator()
    root.setName("IndexedCAM_Stock")
    material = coin.SoMaterial()
    material.diffuseColor.setValue(*STOCK_COLOR)
    material.transparency.setValue(STOCK_TRANSPARENCY)
    root.addChild(material)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.shapeType = coin.SoShapeHints.SOLID
    root.addChild(hints)
    count = len(triangles)
    if count:
        points = coin.SoCoordinate3()
        points.point.setValues(0, count * 3, np.ascontiguousarray(triangles.reshape(-1, 3), dtype=np.float32))
        root.addChild(points)
        faces = coin.SoIndexedFaceSet()
        indices = np.empty((count, 4), dtype=np.int32)
        indices[:, :3] = np.arange(count * 3, dtype=np.int32).reshape(count, 3)
        indices[:, 3] = -1
        faces.coordIndex.setValues(0, count * 4, indices.reshape(-1))
        root.addChild(faces)
    return root


class ToolView:
    """Shows one path and one tool pose in a 3D view, replacing the previous ones."""

    def __init__(self, view: Any = None) -> None:
        self._view = view
        self._scene: Optional[Any] = None
        self._path: Optional[Any] = None
        self._tool: Optional[Any] = None
        self._stock: Optional[Any] = None

    def _graph(self) -> Any:
        if self._scene is None:
            view = self._view
            if view is None:
                import FreeCADGui

                view = FreeCADGui.ActiveDocument.ActiveView
            self._scene = view.getSceneGraph()
        return self._scene

    def show_path(self, points: Sequence[Vector]) -> None:
        self._replace("_path", build_path_node(points) if len(points) > 1 else None)

    def show_tool(self, poses: Sequence[CylinderPose], collides: bool = False, mesh: Any = None) -> None:
        self._replace("_tool", build_tool_node(poses, collides, mesh))

    def show_stock(self, triangles: Any) -> None:
        self._replace("_stock", build_stock_node(triangles))

    def hide_stock(self) -> None:
        self._replace("_stock", None)

    def _replace(self, attribute: str, node: Optional[Any]) -> None:
        scene = self._graph()
        old = getattr(self, attribute)
        if old is not None:
            scene.removeChild(old)
        if node is not None:
            scene.addChild(node)
        setattr(self, attribute, node)

    def clear(self) -> None:
        if self._scene is None:
            return
        for attribute in ("_path", "_tool", "_stock"):
            self._replace(attribute, None)
        self._scene = None

    @property
    def visible(self) -> bool:
        return self._tool is not None or self._path is not None
