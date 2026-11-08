"""Store IndexedCAM data inside the CAM Jobs of the orientations.

Every orientation is a native CAM Job (see ``orientation_jobs``), so the data
IndexedCAM needs travels in hidden properties of that Job: the Setup
(``IndexedCAMSetup``, written by ``OrientationJobs``), the program order and the
controller settings. A document-wide value is written to every orientation Job
and read from the first one that has it, so deleting one Job never loses the
configuration. No extra object is added to the document: the tree shows only CAM
Jobs and their own groups.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Sequence

PROGRAM_PROPERTY_NAME = "IndexedCAMProgram"
GROUP_TITLE = "IndexedCAM"


def orientation_jobs(document: Any) -> Any:
    from IndexedCAM.Core.orientation_jobs import OrientationJobs

    return OrientationJobs(document)


def string_property(owner: Any, name: str, tooltip: str) -> None:
    """Add a hidden string property to ``owner`` if it does not have it yet."""
    if not hasattr(owner, name):
        owner.addProperty("App::PropertyString", name, GROUP_TITLE, tooltip)
        owner.setEditorMode(name, 2)


class JobSetupsStorage:
    """Setup storage whose content *is* the set of orientation Jobs.

    ``save`` reconciles the Jobs with the given Setups: a new Setup creates its
    Job (from the part stored in its metadata), a renamed one relabels it and a
    deleted one takes the Job and its operations away.
    """

    def __init__(self, document: Any) -> None:
        self._document = getattr(document, "Document", document)

    def load(self) -> List[Dict[str, Any]]:
        jobs = orientation_jobs(self._document)
        return [setup.to_dict() for setup in jobs.setups()]

    def save(self, setups: Sequence[Mapping[str, Any]]) -> None:
        orientation_jobs(self._document).ensure(setups)


class JobProgramStorage:
    """Program order stored on the orientation Jobs (read from the first one)."""

    def __init__(self, document: Any) -> None:
        self._document = getattr(document, "Document", document)

    def load(self) -> List[Dict[str, Any]]:
        for job in orientation_jobs(self._document).jobs():
            raw = getattr(job, PROGRAM_PROPERTY_NAME, "")
            if raw:
                return json.loads(raw)
        return []

    def save(self, steps: Sequence[Mapping[str, Any]]) -> None:
        data = json.dumps(list(steps))
        for job in orientation_jobs(self._document).jobs():
            string_property(job, PROGRAM_PROPERTY_NAME, "Program steps")
            setattr(job, PROGRAM_PROPERTY_NAME, data)


class JobSettingStorage:
    """Document-wide setting (safety distance, post options) stored on the Jobs.

    Subclasses provide ``property_name``, ``tooltip`` and a ``load``/``save``
    pair for the value; the JSON stays in a hidden property of every orientation
    Job so it travels inside the ``.FCStd``.
    """

    property_name = ""
    tooltip = ""

    def __init__(self, document: Any) -> None:
        self._document = getattr(document, "Document", document)

    def _jobs(self) -> List[Any]:
        return orientation_jobs(self._document).jobs()

    def _raw(self) -> str:
        for job in self._jobs():
            raw = getattr(job, self.property_name, "")
            if raw:
                return raw
        return ""

    def _store(self, value: Mapping[str, Any]) -> None:
        data = json.dumps(dict(value))
        for job in self._jobs():
            string_property(job, self.property_name, self.tooltip)
            setattr(job, self.property_name, data)
