"""One native CAM Job per indexed orientation.

CAM's area operations (Adaptive, 3D Surface, Waterline...) always read
``Job.Model`` and ``Job.Stock`` and ignore the operation's own geometry for both
the stock and the depth bounds (``Path.Op.Area.areaOpShapeForDepths``,
``Path.Op.SurfaceSupport``): a single Job whose model is the part in part
coordinates cannot machine a tilted face, because the tool would still work
along the part's +Z.

So every Setup owns a Job whose model is the part already placed in the Setup's
local frame (Z = tool axis) and whose stock is derived from that model. Indexed
jobs live in the ``IndexedCAM`` container of the document, next to the hidden
local model they follow.
"""

from __future__ import annotations

import json
from typing import Any, Iterator, List, Optional

from IndexedCAM.Core import local_model
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.program import Step

CONTAINER_NAME = "IndexedCAM"
CONTAINER_MARKER = "IndexedCAMContainer"
SETUP_PROPERTY = "IndexedCAMSetup"
GROUP_TITLE = "IndexedCAM"


def container(document: Any) -> Any:
    """The IndexedCAM container of ``document``, created on first use."""
    existing = document.getObject(CONTAINER_NAME)
    if existing is not None and hasattr(existing, CONTAINER_MARKER):
        return existing
    group = document.addObject("App::DocumentObjectGroup", CONTAINER_NAME)
    group.Label = CONTAINER_NAME
    group.addProperty("App::PropertyBool", CONTAINER_MARKER, GROUP_TITLE, "IndexedCAM data")
    group.setEditorMode(CONTAINER_MARKER, 2)
    hide(group)
    return group


def find_container(document: Any) -> Optional[Any]:
    """The IndexedCAM container of ``document`` if it exists (never creates)."""
    existing = document.getObject(CONTAINER_NAME)
    if existing is not None and hasattr(existing, CONTAINER_MARKER):
        return existing
    return None


def is_orientation_job(obj: Any) -> bool:
    return getattr(obj, "TypeId", "").startswith("Path::FeaturePython") and hasattr(obj, SETUP_PROPERTY)


def hide(obj: Any) -> None:
    obj.Visibility = False
    view = getattr(obj, "ViewObject", None)
    if view is not None:
        view.Visibility = False


class OrientationJobs:
    """The CAM Jobs of a document, one per Setup, and the operations inside them."""

    def __init__(self, document: Any, container_object: Any = None) -> None:
        self._document = document
        self._container = container_object

    @property
    def container(self) -> Any:
        """The IndexedCAM container, created the first time it is needed."""
        if self._container is None:
            self._container = container(self._document)
        return self._container

    # -- jobs -----------------------------------------------------------------
    def jobs(self) -> List[Any]:
        """The orientation Jobs in container order (empty if there is none)."""
        if self._container is None:
            return []
        return [child for child in self._container.Group if is_orientation_job(child)]

    def __iter__(self) -> Iterator[Any]:
        return iter(self.jobs())

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
            from IndexedCAM.Core.cam_bridge import CamBridgeError

            raise CamBridgeError("Setup '{}' has no CAM Job".format(setup_name))
        group = getattr(job, "Model", None)
        models = getattr(group, "Group", ())
        if not models:
            from IndexedCAM.Core.cam_bridge import CamBridgeError

            raise CamBridgeError("Job of Setup '{}' has no model".format(setup_name))
        return models[0]

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
            self._reuse_job(job, model, setup)
        self._document.recompute()
        return job

    def _local_model(self, source: Any, setup: IndexedSetup) -> Any:
        model = self._find_local_model(setup.name)
        if model is None:
            model = local_model.create(self._document, source, setup)
            self.container.addObject(model)
        else:
            local_model.update(model, setup)
        return model

    def _find_local_model(self, setup_name: str) -> Any:
        key = setup_name.casefold()
        for child in getattr(self._container, "Group", ()):
            if getattr(child, "SetupName", "").casefold() == key and hasattr(child, "LocalPlacement"):
                return child
        return None

    def _new_job(self, model: Any, setup: IndexedSetup) -> Any:
        import Path.Main.Job as PathJob
        import Path.Main.Stock as PathStock

        job = PathJob.Create("IndexedCAM_Job_{}".format(_object_safe(setup.name)), [model])
        job.addProperty("App::PropertyString", SETUP_PROPERTY, GROUP_TITLE, "Orientation")
        job.setEditorMode(SETUP_PROPERTY, 2)
        setattr(job, SETUP_PROPERTY, json.dumps(setup.to_dict()))
        job.Label = self.label(setup)
        job.Stock = PathStock.CreateFromBase(job)
        self.container.addObject(job)
        return job

    def _reuse_job(self, job: Any, model: Any, setup: IndexedSetup) -> None:
        if not hasattr(job, SETUP_PROPERTY):
            job.addProperty("App::PropertyString", SETUP_PROPERTY, GROUP_TITLE, "Orientation")
            job.setEditorMode(SETUP_PROPERTY, 2)
        setattr(job, SETUP_PROPERTY, json.dumps(setup.to_dict()))
        job.Label = self.label(setup)
        if getattr(job, "Model", None) is not None and not job.Model.Group:
            job.Model.addObject(model)
        if getattr(job, "Stock", None) is not None:
            job.Stock.touch()

    @staticmethod
    def label(setup: IndexedSetup) -> str:
        return "{} B{:.1f} C{:.1f}".format(setup.name, setup.b, setup.c)

    def rename(self, old: str, new: str) -> None:
        job = self.find(old)
        if job is None:
            return
        model = self._find_local_model(old)
        if model is not None:
            local_model.rename(model, new)
        setup = IndexedSetup.from_dict(json.loads(getattr(job, SETUP_PROPERTY)))
        setup.name = new
        setattr(job, SETUP_PROPERTY, json.dumps(setup.to_dict()))
        job.Label = self.label(setup)

    def remove(self, setup_name: str) -> None:
        job = self.find(setup_name)
        if job is not None:
            self._document.removeObject(job.Name)
        model = self._find_local_model(setup_name)
        if model is not None:
            self._document.removeObject(model.Name)

    # -- operations -----------------------------------------------------------
    def operations_of(self, setup_name: str) -> List[Any]:
        job = self.find(setup_name)
        if job is None or getattr(job, "Operations", None) is None:
            return []
        return list(job.Operations.Group)

    def operations(self) -> List[Any]:
        """Every operation of every orientation, in container and Job order."""
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
        return [Step(self.name_of(job), op.Name) for job in self.jobs() for op in self.operations_of(self.name_of(job))]

    def stock_of(self, setup_name: str) -> Any:
        job = self.find(setup_name)
        return getattr(job, "Stock", None)


def _object_safe(name: str) -> str:
    """FreeCAD object names keep alphanumerics and underscores only."""
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in name.strip())
    return cleaned or "Setup"
