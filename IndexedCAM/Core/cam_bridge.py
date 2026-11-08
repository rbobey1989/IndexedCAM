"""Bridge between IndexedCAM Setups and native CAM Jobs.

Every Setup owns a CAM Job (see ``orientation_jobs``) whose model is the part
already placed in the Setup's local frame, so CAM computes both 2.5D and area
operations (Adaptive, 3D Surface...) with the tool along the Setup's axis and a
stock that matches the geometry it sees.

This bridge only moves operations and keeps their geometry, heights and tools
in sync; CAM itself is never modified.
"""

from __future__ import annotations

from typing import Any, List, Optional

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import OperationHeights, heights_above
from IndexedCAM.Core.orientation_jobs import CamBridgeError, OrientationJobs
from IndexedCAM.Core.program import Step
from IndexedCAM.Machine.envelope import Envelope


class CamBridge:
    """Keeps the orientation Jobs, their local models and their operations in sync."""

    def __init__(self, document: Any, safe_offset: float = 5.0, clearance_offset: float = 10.0) -> None:
        # nothing is created until a Setup (or a setting) has to be stored
        self._document = getattr(document, "Document", document)
        self.jobs = OrientationJobs(self._document)
        self._safe_offset = safe_offset
        self._clearance_offset = clearance_offset

    # -- setups ---------------------------------------------------------------
    def attach_setup(self, source: Any, setup: IndexedSetup) -> Any:
        """Create (or update) the CAM Job of ``setup`` and return it."""
        job = self.jobs.create(source, setup)
        self._document.recompute()
        return job

    def detach_setup(self, setup_name: str) -> None:
        """Remove the Job and local model of a Setup that has no operations."""
        bound = self.jobs.operations_of(setup_name)
        if bound:
            raise CamBridgeError(
                "Setup '{}' still has operations: {}".format(
                    setup_name, ", ".join(op.Label for op in bound)
                )
            )
        self.jobs.remove(setup_name)
        self._document.recompute()

    def rename_setup(self, old: str, new: str) -> None:
        """Follow a Setup rename: the Job keeps its object name, only labels change."""
        self.jobs.rename(old, new)
        self._document.recompute()

    def refresh_all(self) -> None:
        """Re-bind the geometry of every operation to its Job's model."""
        for job in self.jobs.jobs():
            name = self.jobs.name_of(job)
            for operation in self.jobs.operations_of(name):
                self.refresh_operation(operation, name)

    # -- operations -----------------------------------------------------------
    def operations(self) -> List[Any]:
        return self.jobs.operations()

    def operations_of(self, setup_name: str) -> List[Any]:
        return self.jobs.operations_of(setup_name)

    def bound_steps(self) -> List[Step]:
        return self.jobs.bound_steps()

    def setup_of(self, operation: Any) -> Optional[str]:
        return self.jobs.setup_of_operation(operation)

    def candidates(self) -> List[Any]:
        """Every operation of the document's CAM Jobs, indexed or not."""
        from IndexedCAM.Core.job_context import find_jobs

        found: List[Any] = []
        for job in find_jobs(self._document):
            for operation in getattr(getattr(job, "Operations", None), "Group", ()):
                if operation not in found:
                    found.append(operation)
        return found

    def stocks(self) -> List[Any]:
        """Stock object of every orientation Job (hidden while previewing)."""
        return [self.jobs.stock_of(self.jobs.name_of(job)) for job in self.jobs.jobs()]

    def envelope_for(self, operation: Any, base: Envelope) -> Envelope:
        """``base`` with the cutting tool of the operation's CAM tool controller."""
        tool = operation.ToolController.Tool
        shank = getattr(tool, "ShankDiameter", None)
        return base.with_tool(
            float(tool.Diameter.Value) / 2.0,
            float(tool.Length.Value),
            float(tool.CuttingEdgeHeight.Value),
            float(shank.Value) / 2.0 if shank is not None and shank.Value > 0 else None,
        )

    def bind_operation(self, operation: Any, setup_name: str, face: Optional[str] = None) -> None:
        """Move ``operation`` into the Setup's Job and orient it to that model.

        Its Base faces are moved to the same faces of the Job's model (face
        names are shared with the source). An operation without Base would
        machine the whole model, so it gets ``face`` (the Setup's own face).
        """
        job = self.jobs.find(setup_name)
        if job is None:
            raise CamBridgeError("Setup '{}' has no CAM Job".format(setup_name))
        self._move_to(operation, job)
        self._rebuild_base(operation, setup_name, face)
        self._rebase_depths(operation, float(self.jobs.model(setup_name).Shape.BoundBox.ZMax))
        self.refresh_operation(operation, setup_name)

    def _move_to(self, operation: Any, job: Any) -> None:
        owner = self._owner_job(operation)
        if owner is not None and owner is not job:
            # the old Job keeps its tool table: its user still creates
            # operations there, and CAM needs a controller for that
            owner.Operations.removeObject(operation)
        if not any(op.Name == operation.Name for op in getattr(job.Operations, "Group", ())):
            job.Proxy.addOperation(operation)
        controller = getattr(operation, "ToolController", None)
        if controller is not None:
            operation.ToolController = self._controller_in(job, controller)

    def _controller_in(self, job: Any, controller: Any) -> Any:
        """The Job's own controller for the same tool.

        A CAM tool table cannot be shared: adding a controller to a Job's Tools
        group removes it from the Job it was in, which would leave that Job
        without any tool. The moved operation gets a copy instead (same tool,
        same number, same feeds), and repeats of the same tool share it.
        """
        for existing in getattr(job.Tools, "Group", ()):
            if existing.Name == controller.Name:
                return existing
            if (
                getattr(existing, "Tool", None) is getattr(controller, "Tool", None)
                and existing.ToolNumber == controller.ToolNumber
            ):
                return existing
        copy = _copy_controller(controller)
        job.Proxy.addToolController(copy)
        return copy

    def _owner_job(self, operation: Any) -> Any:
        from PathScripts import PathUtils

        return PathUtils.findParentJob(operation)

    def _rebuild_base(self, operation: Any, setup_name: str, face: Optional[str]) -> None:
        base = getattr(operation, "Base", None)
        subs: List[str] = []
        for _, names in base or ():
            subs.extend(name for name in names if name not in subs)
        if not subs and not face:
            return
        model = self.jobs.model(setup_name)
        operation.Base = [(model, subs or [face])]

    def _rebase_depths(self, operation: Any, top: float) -> None:
        """Keep the cut depth of an operation that moves to another frame.

        ``FinalDepth`` is a local Z, so a value computed against the part frame
        would cut through everything in a rotated one. The distance below the
        previous top (which is the depth of cut the user asked for) is kept.
        """
        old_top = _number(operation, "StartDepth")
        final = _number(operation, "FinalDepth")
        if old_top is None or final is None:
            return
        # StartDepth is re-driven by an expression right after this call
        operation.FinalDepth = final - (old_top - top)

    def refresh_operation(self, operation: Any, setup_name: Optional[str] = None) -> OperationHeights:
        """Bind the operation heights to its Setup's model (and return them)."""
        name = setup_name or self.setup_of(operation)
        if name is None:
            raise CamBridgeError("Operation '{}' is not in an indexed Job".format(operation.Label))
        model = self.jobs.model(name)
        heights = heights_above(
            float(model.Shape.BoundBox.ZMax), self._safe_offset, self._clearance_offset
        )
        # Expressions keep the heights tied to the model, so a change of the
        # source part never leaves the operation with stale depths.
        top = "{}.Shape.BoundBox.ZMax * 1 mm".format(model.Name)
        for prop, offset in (
            ("StartDepth", 0.0),
            ("SafeHeight", self._safe_offset),
            ("ClearanceHeight", self._clearance_offset),
        ):
            if not hasattr(operation, prop):
                continue
            operation.setExpression(prop, "{} + {} mm".format(top, offset))
        # CAM draws every path in the Job frame (tool along +Z). The operation's
        # Placement moves it back onto the part, so the path is seen on the face
        # it machines with the tool along the Setup's axis. The Path itself stays
        # in the local frame, which is what the post and the preview expect.
        placement = self._local_placement(name)
        if placement is not None and hasattr(operation, "Placement"):
            operation.Placement = placement.inverse()
        operation.touch()
        self._document.recompute()
        return heights

    def _local_placement(self, setup_name: str) -> Any:
        model = self.jobs.local_model(setup_name)
        return model.LocalPlacement if model is not None else None


def _number(operation: Any, prop: str) -> Optional[float]:
    """Numeric value of a CAM property (``Value`` for quantities), if any."""
    value = getattr(operation, prop, None)
    if value is None:
        return None
    try:
        return float(getattr(value, "Value", value))
    except (TypeError, ValueError):
        return None


CONTROLLER_PROPERTIES = (
    "ToolNumber",
    "SpindleSpeed",
    "SpindleDir",
    "VertFeed",
    "HorizFeed",
    "VertRapid",
    "HorizRapid",
    "CoolantMode",
    "Tool",
)


def _copy_controller(controller: Any) -> Any:
    """A new tool controller with the same tool, number and speeds."""
    import Path.Tool.Controller as PathToolController

    copy = PathToolController.Create(
        str(getattr(controller, "Label", "") or "TC"),
        tool=getattr(controller, "Tool", None),
        toolNumber=int(getattr(controller, "ToolNumber", 1) or 1),
    )
    for prop in CONTROLLER_PROPERTIES:
        if prop == "Tool" or not hasattr(controller, prop) or not hasattr(copy, prop):
            continue
        try:
            setattr(copy, prop, getattr(controller, prop))
        except (AttributeError, TypeError):
            pass
    copy.Label = str(getattr(controller, "Label", "") or copy.Label)
    return copy
