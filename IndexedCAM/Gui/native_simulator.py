"""Makes the native CAM simulator tilt its tool for indexed operations.

``PathSimulation.PerformCut`` is wrapped (CAM sources stay untouched): before an
operation starts, the transition to it is played tick by tick, and afterwards
the ``CutTool`` object is rotated to the operation's B/C about its tip.
Only the legacy simulator draws a ``CutTool`` object; the stock removal of the
simulator itself still assumes a vertical tool.
"""

from __future__ import annotations

from typing import Any, Optional

from IndexedCAM.Core.simulation_plan import SimulationPlan, TiltScript, plan_from_clips
from IndexedCAM.Machine.bc_head import bc_to_normal

_MARK = "_indexedcam_patched"
_SCRIPT = "_indexedcam_script"


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


def _script(simulation: Any) -> Optional[TiltScript]:
    script = getattr(simulation, _SCRIPT, None)
    if script is None:
        try:
            plan = build_plan(simulation.job)
        except Exception as error:  # the native simulation must keep working
            import FreeCAD

            FreeCAD.Console.PrintWarning("IndexedCAM: tool tilt unavailable: {}\n".format(error))
            plan = None
        script = TiltScript(plan) if plan is not None else False
        setattr(simulation, _SCRIPT, script)
    return script or None


def _placement(tip: Any, b: float, c: float) -> Any:
    import FreeCAD

    axis = bc_to_normal(b, c)
    rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), FreeCAD.Vector(*axis))
    return FreeCAD.Placement(FreeCAD.Vector(tip[0], tip[1], tip[2]), rotation)


def _wrap(original: Any) -> Any:
    def perform_cut(self: Any) -> None:
        script = _script(self)
        if script is None or getattr(self, "cutTool", None) is None:
            return original(self)
        if getattr(self, "resetSimulation", False):
            script.reset()
        operation = self.operation.Name if getattr(self, "operation", None) is not None else None
        if operation is not None and not self.busy:
            script.enter(operation)
            frame = script.next_transition_frame()
            if frame is not None:
                self.cutTool.Placement = _placement(frame.tip, frame.b, frame.c)
                return None
        original(self)
        angles = script.orientation(operation) if operation is not None else None
        if angles is not None and getattr(self, "cutTool", None) is not None:
            tip = self.cutTool.Placement.Base
            self.cutTool.Placement = _placement(tip, angles[0], angles[1])
        return None

    return perform_cut


def install() -> bool:
    """Patch the legacy simulator once; False when it is not available."""
    try:
        from Path.Main.Gui import Simulator
    except Exception:
        return False
    cls = Simulator.PathSimulation
    if getattr(cls, _MARK, False):
        return True
    cls.PerformCut = _wrap(cls.PerformCut)
    setattr(cls, _MARK, True)
    return True
