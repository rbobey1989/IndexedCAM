"""Bridge between IndexedCAM Setups and a single FreeCAD CAM Job.

One Job holds every Setup: each Setup contributes a lightweight
``LocalModel`` to ``Job.Model``, and each CAM operation of that Setup uses a
face of its local model as ``Base``. Public CAM APIs only; CAM is not modified.
"""

from __future__ import annotations

from typing import Any, List, Optional

from IndexedCAM.Core import local_model
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import OperationHeights, heights_above

JOB_MARKER = "IndexedCAMJob"
OPERATION_SETUP_PROPERTY = "IndexedSetup"
JOB_NAME = "IndexedCAM_Job"


class CamBridgeError(RuntimeError):
    """Raised when the CAM Job cannot be built or an operation cannot be bound."""


class CamBridge:
    """Creates and keeps in sync the Job, local models and operations."""

    def __init__(
        self, document: Any, safe_offset: float = 5.0, clearance_offset: float = 10.0
    ) -> None:
        self._document = document
        self._safe_offset = safe_offset
        self._clearance_offset = clearance_offset

    def find_job(self) -> Optional[Any]:
        for obj in self._document.Objects:
            if hasattr(obj, JOB_MARKER):
                return obj
        return None

    def ensure_job(self, source: Any) -> Any:
        """Return the IndexedCAM Job, creating it from ``source`` if missing."""
        job = self.find_job()
        if job is not None:
            return job
        from Path.Main import Job

        job = Job.Create(JOB_NAME, [source])
        job.addProperty("App::PropertyBool", JOB_MARKER, "IndexedCAM", "IndexedCAM Job")
        setattr(job, JOB_MARKER, True)
        self._document.recompute()
        return job

    def attach_setup(self, job: Any, source: Any, setup: IndexedSetup) -> Any:
        """Create (or update) the local model of ``setup`` and add it to the Job."""
        model = local_model.find(self._document, setup.name)
        if model is None:
            model = local_model.create(self._document, source, setup)
        else:
            local_model.update(model, setup)
        if model not in job.Model.Group:
            job.Model.addObject(model)
        self._document.recompute()
        return model

    def detach_setup(self, job: Any, setup_name: str) -> None:
        """Remove the local model of a Setup that has no operations bound."""
        model = local_model.find(self._document, setup_name)
        if model is None:
            return
        bound = self.operations_of(job, setup_name)
        if bound:
            raise CamBridgeError(
                "Setup '{}' still has operations: {}".format(
                    setup_name, ", ".join(op.Label for op in bound)
                )
            )
        if model in job.Model.Group:
            job.Model.removeObject(model)
        self._document.removeObject(model.Name)

    def operations_of(self, job: Any, setup_name: str) -> List[Any]:
        return [
            op
            for op in job.Operations.Group
            if getattr(op, OPERATION_SETUP_PROPERTY, None) == setup_name
        ]

    def bind_operation(self, operation: Any, setup_name: str, face: str) -> None:
        """Bind ``operation`` to ``face`` ("FaceN") of the Setup's local model."""
        model = local_model.find(self._document, setup_name)
        if model is None:
            raise CamBridgeError("Setup '{}' has no local model".format(setup_name))
        if not hasattr(operation, OPERATION_SETUP_PROPERTY):
            operation.addProperty(
                "App::PropertyString", OPERATION_SETUP_PROPERTY, "IndexedCAM", "Owning Setup"
            )
        setattr(operation, OPERATION_SETUP_PROPERTY, setup_name)
        operation.Base = [(model, [face])]
        self.refresh_operation(operation)

    def refresh_operation(self, operation: Any) -> OperationHeights:
        """Bind the operation heights to its Setup's local model (and return them)."""
        name = getattr(operation, OPERATION_SETUP_PROPERTY, None)
        model = local_model.find(self._document, name) if name else None
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
        operation.touch()
        self._document.recompute()
        return heights

    def refresh_all(self, job: Any) -> None:
        """Refresh every bound operation (after the source model changed)."""
        for op in job.Operations.Group:
            if getattr(op, OPERATION_SETUP_PROPERTY, None):
                self.refresh_operation(op)
