"""Bridge between IndexedCAM Setups and the CAM Job the user created.

Everything stays in that one Job: every Setup contributes a lightweight
``LocalModel`` (a rotated clone of the part, ``Shape`` transient) placed inside
``Job.Model``, and each CAM operation uses a face of its Setup's local model as
``Base``, so the operation keeps living in ``Job.Operations`` with nothing moved
or duplicated.

The local model must be a member of ``Job.Model`` and not a loose object: CAM's
area operations (Adaptive, 3D Surface, Waterline) look up the ``Base`` faces in
``Job.Model.Group`` (``Path.Op.SurfaceSupport._identifyFacesAndVoids``) and
compute their stock and depths from ``Job.Stock``, so a Base outside the Job is
simply not found. The price is that the Job's stock (a box around
``Job.Model``) grows to cover the rotated copies; the heights of every operation
are tied to its own local model by expression, so the cut is unaffected. Public
CAM APIs only; CAM is not modified.
"""

from __future__ import annotations

from typing import Any, List, Optional

from IndexedCAM.Core import local_model
from IndexedCAM.Core.job_stock import keep_part_stock
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import OperationHeights, heights_above
from IndexedCAM.Core.program import Step
from IndexedCAM.Machine.envelope import Envelope

OPERATION_SETUP_PROPERTY = "IndexedSetup"
#: property a Job created by the previous (one Job per orientation) version has
LEGACY_JOB_PROPERTY = "IndexedCAMSetup"


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
        return local_model.find(self.job, setup_name)

    def attach_setup(self, source: Any, setup: IndexedSetup) -> Any:
        """Create (or update) the local model of ``setup`` inside ``Job.Model``.

        CAM's area operations only find the faces of objects that belong to the
        Job's model, so the clone has to be a member of ``Job.Model`` (not a
        loose helper object).
        """
        model = self._model(setup.name)
        if model is None:
            model = local_model.create(self._document, source, setup)
        else:
            local_model.update(model, setup)
        self._document.recompute()
        # the clone joins Job.Model so CAM finds its faces; the stock has to
        # ignore it, or it would grow to cover every rotated copy of the part
        keep_part_stock(self.job)
        if model not in getattr(self.job.Model, "Group", ()):
            self.job.Model.addObject(model)
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
        self._rebase_depths(operation, float(model.Shape.BoundBox.ZMax))
        self.refresh_operation(operation)

    def _rebase_depths(self, operation: Any, top: float) -> None:
        """Keep the cut depth of an operation that changes to another frame.

        ``FinalDepth`` is a local Z, so a value computed against the part frame
        would cut through everything in a rotated one. The distance below the
        previous top (the depth of cut the user asked for) is kept.
        """
        old_top = _number(operation, "StartDepth")
        final = _number(operation, "FinalDepth")
        if old_top is None or final is None:
            return
        operation.FinalDepth = final - (old_top - top)

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

    def ensure_paths(self) -> List[str]:
        """Rebuild the ``Path`` of every bound operation and return their names.

        CAM only rebuilds an operation when one of its inputs is flagged as
        changed, and IndexedCAM changes two of them behind its back (the
        transient Shape of a local model on load, a repaired stock). An
        operation restored from such a document keeps the old Path while
        reporting itself as up to date, so it has to be touched explicitly.
        """
        names = []
        for operation in self.operations():
            if getattr(operation, OPERATION_SETUP_PROPERTY, None):
                operation.touch()
                names.append(operation.Name)
        if names:
            self._document.recompute()
        return names

    # -- documents of the previous version -----------------------------------
    def legacy_jobs(self) -> List[Any]:
        """Jobs invented by the previous version (one per orientation)."""
        return [
            obj
            for obj in self._document.Objects
            if obj is not self.job and hasattr(obj, LEGACY_JOB_PROPERTY)
        ]

    def adopt_legacy_jobs(self) -> List[IndexedSetup]:
        """Fold the operations of those Jobs back into this one.

        The previous version gave every orientation its own Job; this brings
        its operations (and their tools) into the user's Job, re-bases them on a
        local model of the same Setup and deletes the leftover Job.
        """
        adopted: List[IndexedSetup] = []
        for job in self.legacy_jobs():
            try:
                adopted.append(self._adopt(job))
            except (ValueError, TypeError, KeyError, AttributeError):
                # a document in an unexpected state must never block the command
                continue
        if adopted:
            self._document.recompute()
        return adopted

    def _adopt(self, job: Any) -> IndexedSetup:
        import json

        setup = IndexedSetup.from_dict(json.loads(getattr(job, LEGACY_JOB_PROPERTY)))
        source = self._source_object(str(setup.metadata.get("source", "")))
        operations = list(getattr(job.Operations, "Group", ()))
        controllers = [
            getattr(op, "ToolController", None)
            for op in operations
            if getattr(op, "ToolController", None) is not None
        ]
        for op in operations:
            job.Operations.removeObject(op)
        for controller in controllers:
            if controller in getattr(job.Tools, "Group", ()):
                job.Tools.removeObject(controller)
        self._document.removeObject(job.Name)
        self._document.recompute()
        if source is not None:
            self.attach_setup(source, setup)
        for controller in controllers:
            self.job.Proxy.addToolController(controller)
        for op in operations:
            self.job.Proxy.addOperation(op)
            self.bind_operation(op, setup.name)
        return setup

    def _source_object(self, name: str) -> Any:
        """The document object a Setup metadata refers to, following clones."""
        obj = self._document.getObject(name.rpartition(".")[0])
        for _ in range(5):
            source = getattr(obj, "Source", None)
            if source is None or source is obj:
                break
            obj = source
        return obj


def _number(operation: Any, prop: str) -> Optional[float]:
    """Numeric value of a CAM property (``Value`` for quantities), if any."""
    value = getattr(operation, prop, None)
    if value is None:
        return None
    try:
        return float(getattr(value, "Value", value))
    except (TypeError, ValueError):
        return None
