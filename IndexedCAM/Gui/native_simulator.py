"""Makes the native CAM simulator work with tilted (indexed) operations.

``PathSimulation`` (CAM's legacy simulator) is wrapped, its sources stay untouched:

* its voxel engine (vertical tool only) is replaced by ``IndexedVoxSim``, which
  removes material with the real tool axis of each operation;
* indexed operations play their *local* path; the tool shown by CAM itself is
  placed with the operation's Placement, so it appears tilted;
* the B/C transition that leads to an operation is played before it starts.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from IndexedCAM.Core.path_endpoints import path_endpoints
from IndexedCAM.Core.simulation_plan import SimulationPlan, TiltScript, plan_from_clips
from IndexedCAM.Core.voxel_stock import PROFILE_STEP, ToolProfile, VoxelStock
from IndexedCAM.Machine.bc_head import bc_to_normal

_MARK = "_indexedcam_patched"
_SCRIPT = "_indexedcam_script"
_PROXY = "_indexedcam_proxy"
_NATIVE = "_indexedcam_native_vox"
_CUTTING = {"G1", "G01", "G2", "G02", "G3", "G03"}
MESH_PERIOD = 0.25


def build_plan(job: Any) -> Optional[SimulationPlan]:
    """Plan for ``job``, or None when it has no indexed operations."""
    from IndexedCAM.Commands.context import build_context
    from IndexedCAM.Commands.preview import build_clips
    from IndexedCAM.Commands.program import resolve_program

    ctx = build_context(job.Document, job)
    items = resolve_program(ctx.program, ctx.manager, ctx.bridge, ctx.document)
    if not items:
        return None
    clips = build_clips(ctx.document, ctx.manager, ctx.program, ctx.bridge, items=items)
    return plan_from_clips(items, clips)


def is_indexed(operation: Any) -> bool:
    return bool(getattr(operation, "IndexedSetup", ""))


def tool_profile(shape: Any) -> ToolProfile:
    """Radius of ``shape`` (tip at the origin, axis +Z) every ``PROFILE_STEP`` along Z."""
    import FreeCAD

    box = shape.BoundBox
    count = max(2, int(box.ZLength / PROFILE_STEP) + 1)
    radii = []
    for i in range(count):
        z = box.ZMin + max(i * PROFILE_STEP, 1e-3)
        try:
            wires = shape.slice(FreeCAD.Vector(0, 0, 1), z)
        except Exception:
            wires = []
        r = 0.0
        for wire in wires:
            b = wire.BoundBox
            r = max(r, abs(b.XMin), abs(b.XMax), abs(b.YMin), abs(b.YMax))
        radii.append(r)
    if max(radii) == 0:
        return ToolProfile.cylinder(max(box.XLength, box.YLength) / 2, box.ZLength)
    return ToolProfile(radii, PROFILE_STEP)


class IndexedVoxSim:
    """Stand-in for ``PathSimulator.PathSim`` that cuts with the operation's tool axis."""

    def __init__(self) -> None:
        import FreeCAD

        self._app = FreeCAD
        self.stock: Optional[VoxelStock] = None
        self.profile: Optional[ToolProfile] = None
        self.frame = FreeCAD.Placement()
        self.cut_height = 0.0
        self._mesh: Any = None
        self._built = -1
        self._stamp = 0.0

    def BeginSimulation(self, stock: Any, resolution: float) -> None:
        box = stock.BoundBox
        self.stock = VoxelStock((box.XMin, box.YMin, box.ZMin), (box.XMax, box.YMax, box.ZMax), resolution)
        self._mesh, self._built = None, -1

    def SetToolShape(self, shape: Any, resolution: float) -> None:
        self.profile = tool_profile(shape)

    def set_operation(self, frame: Any, cut_height: float) -> None:
        self.frame, self.cut_height = frame, cut_height

    def ApplyCommand(self, pos: Any, cmd: Any) -> Any:
        app = self._app
        start = pos.Base if hasattr(pos, "Base") else pos
        params = cmd.Parameters
        end = app.Vector(params.get("X", start.x), params.get("Y", start.y), params.get("Z", start.z))
        if cmd.Name in _CUTTING and self.stock is not None and self.profile is not None:
            profile = self.profile.truncated(self.cut_height) if self.cut_height > 0 else self.profile
            axis = self.frame.Rotation.multVec(app.Vector(0, 0, 1))
            self.stock.carve_segment(
                tuple(self.frame.multVec(start)), tuple(self.frame.multVec(end)), tuple(axis), profile
            )
        return app.Placement(end, app.Rotation())

    def GetResultMesh(self, force: bool = False) -> Any:
        import Mesh

        stock = self.stock
        if stock is not None and stock.version != self._built:
            if force or self._mesh is None or time.monotonic() - self._stamp >= MESH_PERIOD:
                self._mesh = Mesh.Mesh(stock.triangles().tolist())
                self._built, self._stamp = stock.version, time.monotonic()
        return (self._mesh if self._mesh is not None else Mesh.Mesh()), Mesh.Mesh()

    def flush(self) -> None:
        self.GetResultMesh(force=True)


def _placement(tip: Any, b: float, c: float) -> Any:
    import FreeCAD

    rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(*bc_to_normal(b, c)))
    return FreeCAD.Placement(FreeCAD.Vector(tip[0], tip[1], tip[2]), rotation)


def _script(simulation: Any) -> Optional[TiltScript]:
    script = getattr(simulation, _SCRIPT, None)
    if script is None:
        try:
            plan = build_plan(simulation.job)
        except Exception as error:  # the native simulation must keep working
            import FreeCAD

            FreeCAD.Console.PrintWarning("IndexedCAM: transitions unavailable: {}\n".format(error))
            plan = None
        script = TiltScript(plan) if plan is not None else False
        setattr(simulation, _SCRIPT, script)
    return script or None


def _show_tool(simulation: Any) -> None:
    """Place CAM's own tool at the current position, tilted by the operation's frame."""
    import FreeCAD

    proxy = getattr(simulation, _PROXY, None)
    script = getattr(simulation, _SCRIPT, None)
    if proxy is None or getattr(simulation, "cutTool", None) is None:
        return
    if script and script.pending():
        return
    position = simulation.curpos
    base = position.Base if hasattr(position, "Base") else position
    simulation.cutTool.Placement = proxy.frame.multiply(FreeCAD.Placement(base, FreeCAD.Rotation()))


def _wrap_setup_simulation(original: Any) -> Any:
    def setup_simulation(self: Any) -> None:
        import PathSimulator

        if not hasattr(self, _NATIVE):
            setattr(self, _NATIVE, self.voxSim)
        indexed = any(is_indexed(op) for op in self.job.Operations.OutList)
        proxy = IndexedVoxSim() if indexed else None
        setattr(self, _PROXY, proxy)
        self.voxSim = proxy if proxy is not None else getattr(self, _NATIVE, PathSimulator.PathSim())
        setattr(self, _SCRIPT, None)
        if proxy is not None:
            _script(self)
        original(self)

    return setup_simulation


def _wrap_setup_operation(original: Any) -> Any:
    def setup_operation(self: Any, itool: int) -> None:
        import FreeCAD

        original(self, itool)
        proxy = getattr(self, _PROXY, None)
        if proxy is None:
            return
        operation = self.operation
        frame = FreeCAD.Placement()
        if is_indexed(operation):
            frame = operation.Placement
            self.opCommands = list(operation.Path.Commands)
            ends = path_endpoints(self.opCommands)
            if ends is not None:
                self.curpos = FreeCAD.Placement(FreeCAD.Vector(*ends[0]), self.stdrot)
        height = 0.0
        if self.tool is not None:
            height = float(getattr(self.tool, "CuttingEdgeHeight", 0) or 0)
        proxy.set_operation(frame, height)
        script = getattr(self, _SCRIPT, None)
        if script:
            script.enter(operation.Name)
        _show_tool(self)

    return setup_operation


def _wrap_perform_cut(original: Any) -> Any:
    def perform_cut(self: Any) -> None:
        script = getattr(self, _SCRIPT, None)
        if script and getattr(self, _PROXY, None) is not None and not self.busy:
            if self.disableAnim:
                script.skip()
            else:
                frame = script.next_transition_frame()
                if frame is not None:
                    self.cutTool.Placement = _placement(frame.tip, frame.b, frame.c)
                    return
        original(self)
        _show_tool(self)

    return perform_cut


def _wrap_view_shape(original: Any) -> Any:
    def view_shape(self: Any) -> None:
        proxy = getattr(self, _PROXY, None)
        if proxy is not None:
            proxy.flush()
        original(self)

    return view_shape


def install() -> bool:
    """Patch the legacy simulator once; False when it is not available."""
    try:
        from Path.Main.Gui import Simulator
    except Exception:
        return False
    cls = Simulator.PathSimulation
    if getattr(cls, _MARK, False):
        return True
    cls.SetupSimulation = _wrap_setup_simulation(cls.SetupSimulation)
    cls.SetupOperation = _wrap_setup_operation(cls.SetupOperation)
    cls.PerformCut = _wrap_perform_cut(cls.PerformCut)
    cls.ViewShape = _wrap_view_shape(cls.ViewShape)
    setattr(cls, _MARK, True)
    return True
