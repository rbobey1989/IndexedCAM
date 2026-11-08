"""One native CAM Job per indexed orientation.

CAM's area operations (Adaptive, 3D Surface, Waterline...) always read
``Job.Model`` and ``Job.Stock`` and ignore the operation's own geometry for both
the stock and the depth bounds (``Path.Op.Area.areaOpShapeForDepths``,
``Path.Op.SurfaceSupport``): a single Job whose model is the part in part
coordinates cannot machine a tilted face, because the tool would still work
along the part's +Z.

So every Setup owns a Job whose model is the part already placed in the Setup's
local frame (Z = tool axis) and whose stock is derived from that model. Those
Jobs are ordinary CAM Jobs at the root of the document (Operations, Model,
Stock, SetupSheet and Tools inside them, exactly like a Job created by CAM) and
they carry the Setup in a hidden property, so the document needs no extra
container object.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, List, Mapping, Optional

from IndexedCAM.Core import local_model
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.program import Step

SETUP_PROPERTY = "IndexedCAMSetup"
GROUP_TITLE = "IndexedCAM"
JOB_PREFIX = "IndexedCAM_Job_"
LEGACY_CONTAINER = "IndexedCAM"
LEGACY_CONTAINER_MARKER = "IndexedCAMContainer"


def is_orientation_job(obj: Any) -> bool:
    """A CAM Job created by IndexedCAM for one Setup."""
    return (
        getattr(obj, "TypeId", "").startswith("Path::FeaturePython")
        and hasattr(obj, SETUP_PROPERTY)
    )


def hide(obj: Any) -> None:
    obj.Visibility = False
    view = getattr(obj, "ViewObject", None)
    if view is not None:
        view.Visibility = False


class OrientationJobs:
    """The CAM Jobs of a document, one per Setup, and the operations inside them."""

    def __init__(self, document: Any) -> None:
        self._document = getattr(document, "Document", document)

    # -- jobs -----------------------------------------------------------------
    def jobs(self) -> List[Any]:
        """The orientation Jobs, in document order."""
        return [obj for obj in self._document.Objects if is_orientation_job(obj)]

    def __iter__(self) -> Any:
        return iter(self.jobs())

    def __len__(self) -> int:
        return len(self.jobs())

    def find(self, setup_name: str) -> Optional[Any]:
        key = setup_name.casefold()
        for job in self.jobs():
            if self.name_of(job).casefold() == key:
                return job
        return None

    @staticmethod
    def name_of(job: Any) -> str:
        try:
            return str(json.loads(getattr(job, SETUP_PROPERTY)).get("name", ""))
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def setup_of(job: Any) -> IndexedSetup:
        return IndexedSetup.from_dict(json.loads(getattr(job, SETUP_PROPERTY)))

    def setups(self) -> List[IndexedSetup]:
        return [self.setup_of(job) for job in self.jobs()]

    def model(self, setup_name: str) -> Any:
        """Geometry CAM works with for ``setup_name`` (the Job's model clone)."""
        job = self.find(setup_name)
        if job is None:
            raise CamBridgeError("Setup '{}' has no CAM Job".format(setup_name))
        models = getattr(getattr(job, "Model", None), "Group", ())
        if not models:
            raise CamBridgeError("Job of Setup '{}' has no model".format(setup_name))
        return models[0]

    def local_model(self, setup_name: str) -> Any:
        """The lightweight model the Job was built from (None if it is gone)."""
        return local_model.find(self._document, setup_name)

    # -- lifecycle ------------------------------------------------------------
    def create(self, source: Any, setup: IndexedSetup) -> Any:
        """Create (or update) the Job of ``setup`` and return it."""
        model = self._local_model(source, setup)
        # the Job clones the model, so its shape must be up to date first
        self._document.recompute()
        job = self.find(setup.name)
        if job is None:
            job = self._new_job(model, setup)
        else:
            self._reuse_job(job, setup)
        self._document.recompute()
        return job

    def ensure(self, setups: Iterable[Mapping[str, Any]]) -> None:
        """Make the Jobs match ``setups`` (create, update and remove).

        This is what keeps a Setup and its Job the same thing: the stored list
        is written by ``SetupManager`` on every change, so adding a Setup
        creates its Job, renaming it relabels the Job and deleting it removes
        the Job with its operations.
        """
        wanted = {}
        for data in setups:
            setup = IndexedSetup.from_dict(data)
            wanted[setup.name.casefold()] = setup
        for setup in wanted.values():
            job = self.find(setup.name)
            if job is None:
                source = self._source(setup)
                if source is not None:
                    self.create(source, setup)
                continue
            model = self.local_model(setup.name)
            if model is not None and _placement_differs(model, setup):
                local_model.update(model, setup)
                self._document.recompute()
            self._reuse_job(job, setup)
        for job in self.jobs():
            if self.name_of(job).casefold() not in wanted:
                self.remove(self.name_of(job))
        self._document.recompute()

    def _source(self, setup: IndexedSetup) -> Any:
        """The document object the Setup was created from (None if it is gone)."""
        source = str(setup.metadata.get("source", ""))
        object_name = source.rpartition(".")[0]
        return self._document.getObject(object_name) if object_name else None

    def _local_model(self, source: Any, setup: IndexedSetup) -> Any:
        model = local_model.find(self._document, setup.name)
        if model is None:
            model = local_model.create(self._document, source, setup)
        else:
            local_model.update(model, setup)
        return model

    def _new_job(self, model: Any, setup: IndexedSetup) -> Any:
        import FreeCAD as App
        import Path.Main.Job as PathJob
        import Path.Main.Stock as PathStock

        job = PathJob.Create(JOB_PREFIX + _object_safe(setup.name), [model])
        job.addProperty("App::PropertyString", SETUP_PROPERTY, GROUP_TITLE, "Orientation")
        job.setEditorMode(SETUP_PROPERTY, 2)
        setattr(job, SETUP_PROPERTY, json.dumps(setup.to_dict()))
        job.Label = self.label(setup)
        job.Stock = PathStock.CreateFromBase(job)
        if App.GuiUp:
            from IndexedCAM.Gui.job_view import attach

            attach(job)
        return job

    def _reuse_job(self, job: Any, setup: IndexedSetup) -> None:
        if not hasattr(job, SETUP_PROPERTY):
            job.addProperty("App::PropertyString", SETUP_PROPERTY, GROUP_TITLE, "Orientation")
            job.setEditorMode(SETUP_PROPERTY, 2)
        setattr(job, SETUP_PROPERTY, json.dumps(setup.to_dict()))
        job.Label = self.label(setup)
        if getattr(job, "Stock", None) is not None:
            job.Stock.touch()

    @staticmethod
    def label(setup: IndexedSetup) -> str:
        return "{} B{:.1f} C{:.1f}".format(setup.name, setup.b, setup.c)

    def rename(self, old: str, new: str) -> None:
        job = self.find(old)
        if job is None:
            return
        model = self.local_model(old)
        if model is not None:
            local_model.rename(model, new)
        setup = self.setup_of(job)
        setup.name = new
        self._reuse_job(job, setup)

    def remove(self, setup_name: str) -> None:
        job = self.find(setup_name)
        if job is not None:
            self._document.removeObject(job.Name)
        model = self.local_model(setup_name)
        if model is not None:
            self._document.removeObject(model.Name)

    # -- operations -----------------------------------------------------------
    def operations_of(self, setup_name: str) -> List[Any]:
        job = self.find(setup_name)
        if job is None or getattr(job, "Operations", None) is None:
            return []
        return list(job.Operations.Group)

    def operations(self) -> List[Any]:
        """Every operation of every orientation, in document and Job order."""
        found: List[Any] = []
        for job in self.jobs():
            found.extend(self.operations_of(self.name_of(job)))
        return found

    def setup_of_operation(self, operation: Any) -> Optional[str]:
        """Name of the Setup whose Job holds ``operation``."""
        for job in self.jobs():
            if operation in getattr(getattr(job, "Operations", None), "Group", ()):
                return self.name_of(job)
        return None

    def bound_steps(self) -> List[Step]:
        return [
            Step(self.name_of(job), op.Name)
            for job in self.jobs()
            for op in self.operations_of(self.name_of(job))
        ]

    def stock_of(self, setup_name: str) -> Any:
        return getattr(self.find(setup_name), "Stock", None)

    # -- legacy documents -----------------------------------------------------
    def adopt_legacy(self) -> bool:
        """Free the Jobs of documents written before the container was dropped.

        The previous version kept the Jobs and their local models inside a
        hidden ``IndexedCAM`` group. The Jobs are now ordinary root objects and
        the local model is shown inside its Job, so the group is removed once
        it is empty. Returns True if the document changed.
        """
        group = self._document.getObject(LEGACY_CONTAINER)
        if group is None or not hasattr(group, LEGACY_CONTAINER_MARKER):
            return False
        children = [child for child in getattr(group, "Group", ())]
        for child in children:
            if is_orientation_job(child) or hasattr(child, "LocalPlacement"):
                group.removeObject(child)
        if not getattr(group, "Group", ()):
            self._document.removeObject(group.Name)
        self._document.recompute()
        return True


class CamBridgeError(RuntimeError):
    """Raised when a Setup has no CAM Job (re-exported for the bridge)."""


def _placement_differs(model: Any, setup: IndexedSetup) -> bool:
    """True when the local model is not placed in the Setup's frame any more."""
    from IndexedCAM.Core.local_model import local_placement

    expected = local_placement(setup)
    current = model.LocalPlacement
    if expected.Base != current.Base:
        return True
    return (
        abs(expected.Rotation.Q[0] - current.Rotation.Q[0]) > 1e-9
        or abs(expected.Rotation.Q[1] - current.Rotation.Q[1]) > 1e-9
        or abs(expected.Rotation.Q[2] - current.Rotation.Q[2]) > 1e-9
        or abs(expected.Rotation.Q[3] - current.Rotation.Q[3]) > 1e-9
    )


def _object_safe(name: str) -> str:
    """FreeCAD object names keep alphanumerics and underscores only."""
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in name.strip())
    return cleaned or "Setup"
