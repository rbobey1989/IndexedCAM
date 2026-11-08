"""Tree view of an orientation Job.

A Job created by CAM's own command gets CAM's Job view provider, whose
``claimChildren`` nests Operations, Model, Stock, SetupSheet and Tools under it.
A Job created from Python has no view provider at all, so those groups appear as
loose objects at the root of the tree. This module gives an orientation Job the
same provider, plus the Setup's local model, which is the only object IndexedCAM
adds to the document.
"""

from __future__ import annotations

from typing import Any

from Path.Main.Gui.Job import ViewProvider as CamJobViewProvider

PROXY = "Gui::ViewProviderGroupExtensionPython"


class OrientationJobViewProvider(CamJobViewProvider):
    """CAM's Job provider that also shows the local model inside the Job."""

    def claimChildren(self) -> Any:
        children = super().claimChildren()
        model = _local_model(getattr(self, "obj", None))
        if model is not None and all(child is not model for child in children):
            children.append(model)
        return children


def _local_model(job: Any) -> Any:
    from IndexedCAM.Core import local_model

    if job is None or not hasattr(job, "IndexedCAMSetup"):
        return None
    from IndexedCAM.Core.orientation_jobs import OrientationJobs

    return local_model.find(job.Document, OrientationJobs.name_of(job))


def attach(job: Any) -> None:
    """Give ``job`` the Job view provider (idempotent, GUI only)."""
    view = getattr(job, "ViewObject", None)
    if view is None:
        return
    if not isinstance(view.Proxy, OrientationJobViewProvider):
        view.Proxy = OrientationJobViewProvider(view)
    proxy = view.Proxy
    # a fresh object gets ``attach`` from FreeCAD when the proxy is assigned; a
    # document being adopted does not, and without it ``claimChildren`` has no
    # object to work with
    if getattr(proxy, "obj", None) is not job:
        proxy.attach(view)
    try:
        view.addExtension(PROXY)
    except Exception:  # already added: nothing to do
        pass


def attach_all(document: Any) -> int:
    """Attach the provider to every orientation Job of ``document``."""
    from IndexedCAM.Core.orientation_jobs import OrientationJobs

    count = 0
    for job in OrientationJobs(document).jobs():
        attach(job)
        count += 1
    return count
