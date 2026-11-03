"""Bridge between IndexedCAM Setups and an existing FreeCAD CAM Job.

The Job is created by the user in CAM. It holds every Setup: each Setup contributes a lightweight
``LocalModel`` kept in the Job's ``Orientations`` group (not in ``Job.Model``: the Job's stock
is the bounding box of ``Job.Model`` and would grow with every rotated copy), and each CAM operation of that Setup uses a
face of its local model as ``Base``. Public CAM APIs only; CAM is not modified.
"""

from __future__ import annotations

from typing import Any, List, Optional

from IndexedCAM.Core import local_model
from IndexedCAM.Core.document_storage import ensure_orientations_group, orientation_of, orientations_group
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import OperationHeights, heights_above
from IndexedCAM.Core.program import Step
from IndexedCAM.Machine.envelope import Envelope

OPERATION_SETUP_PROPERTY = "IndexedSetup"


class CamBridgeError(RuntimeError):
    """Raised when an operation cannot be bound to a Setup."""


class CamBridge:
    """Keeps local models and operations of one existing Job in sync."""

    def __init__(self, job: Any, safe_offset: float = 5.0, clearance_offset: float = 10.0) -> None:
        self.job = job
        self._document = job.Document
        self._safe_offset = safe_offset
        self._clearance_offset = clearance_offset

    def _model(self, setup_name: str) -> Any:
        return local_model.find(orientations_group(self.job), setup_name)

    def attach_setup(self, source: Any, setup: IndexedSetup) -> Any:
        """Create (or update) the local model of ``setup`` and add it to the Job."""
        model = self._model(setup.name)
        if model is None:
            model = local_model.create(self._document, source, setup)
        else:
            local_model.update(model, setup)
        group = ensure_orientations_group(self.job)
        owner = orientation_of(group, setup.name)
        # a model not yet inside an orientation (or a legacy orientation that is
        # not a group) stays directly in the Orientations group
        target = owner if owner is not None and hasattr(owner, "addObject") else group
        if model not in target.Group and not any(model in getattr(c, "Group", ()) for c in group.Group):
            target.addObject(model)
        self._document.recompute()
        return model

    def detach_setup(self, setup_name: str) -> None:
        """Remove the local model of a Setup that has no operations bound."""
        model = self._model(setup_name)
        if model is None:
            return
        bound = self.operations_of(setup_name)
        if bound:
            raise CamBridgeError(
                "Setup '{}' still has operations: {}".format(
                    setup_name, ", ".join(op.Label for op in bound)
                )
            )
        self._document.removeObject(model.Name)

    def rename_setup(self, old: str, new: str) -> None:
        """Follow a Setup rename: its local model and every operation bound to it.

        Object names stay (expressions and CAM refer to them); only the owning
        Setup name and the visible label change.
        """
        model = self._model(old)
        if model is not None:
            local_model.rename(model, new)
        for operation in self.operations_of(old):
            setattr(operation, OPERATION_SETUP_PROPERTY, new)
        self._document.recompute()

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

    def operations(self) -> List[Any]:
        """Every CAM operation of the Job, in Job order."""
        return list(self.job.Operations.Group)

    def bound_steps(self) -> List[Step]:
        """(Setup, operation) of every bound operation, in Job order."""
        return [
            Step(getattr(op, OPERATION_SETUP_PROPERTY), op.Name)
            for op in self.operations()
            if getattr(op, OPERATION_SETUP_PROPERTY, None)
        ]

    def operations_of(self, setup_name: str) -> List[Any]:
        return [
            op
            for op in self.operations()
            if getattr(op, OPERATION_SETUP_PROPERTY, None) == setup_name
        ]

    def bind_operation(self, operation: Any, setup_name: str, face: Optional[str] = None) -> None:
        """Orient an existing Job operation to a Setup.

        Its Base faces are moved to the same faces of the Setup's local model
        (face names are shared with the source). An operation without Base would
        machine the whole Job model, so it gets ``face`` (the Setup's own face).
        Its heights follow the local model.
        """
        model = self._model(setup_name)
        if model is None:
            raise CamBridgeError("Setup '{}' has no local model".format(setup_name))
        if not hasattr(operation, OPERATION_SETUP_PROPERTY):
            operation.addProperty(
                "App::PropertyString", OPERATION_SETUP_PROPERTY, "IndexedCAM", "Owning Setup"
            )
        setattr(operation, OPERATION_SETUP_PROPERTY, setup_name)
        base = getattr(operation, "Base", None)
        if base:
            subs: List[str] = []
            for _, names in base:
                subs.extend(n for n in names if n not in subs)
            operation.Base = [(model, subs)]
        elif face:
            operation.Base = [(model, [face])]
        self.refresh_operation(operation)

    def refresh_operation(self, operation: Any) -> OperationHeights:
        """Bind the operation heights to its Setup's local model (and return them)."""
        name = getattr(operation, OPERATION_SETUP_PROPERTY, None)
        model = self._model(name) if name else None
        if model is None:
            raise CamBridgeError("Operation '{}' is not bound to a Setup".format(operation.Label))
        heights = heights_above(
            model.Shape.BoundBox.ZMax, self._safe_offset, self._clearance_offset
        )
        # Expressions keep the heights tied to the local model, so a change of
        # the source model never leaves the operation with stale depths.
        top = "{}.Shape.BoundBox.ZMax * 1 mm".format(model.Name)
        for prop, offset in (
            ("StartDepth", 0.0),
            ("SafeHeight", self._safe_offset),
            ("ClearanceHeight", self._clearance_offset),
        ):
            operation.setExpression(prop, "{} + {} mm".format(top, offset))
        # CAM draws every path in the Job frame (tool along +Z). The operation's
        # Placement moves it back onto the part, so the path is seen on the face
        # it machines, with the tool pointing along the Setup's axis. The Path
        # itself stays in the local frame.
        operation.Placement = model.LocalPlacement.inverse()
        operation.touch()
        self._document.recompute()
        return heights

    def refresh_all(self) -> None:
        """Refresh every bound operation (after the source model changed)."""
        for op in self.operations():
            if getattr(op, OPERATION_SETUP_PROPERTY, None):
                self.refresh_operation(op)
