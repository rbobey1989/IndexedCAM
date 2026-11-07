"""Locate the native CAM Jobs of a document.

IndexedCAM never requires a Job: the user creates operations in CAM (in any
Job) and assigns them to an orientation, which moves them into that
orientation's own Job. This module only finds the Jobs whose operations can be
assigned.
"""

from __future__ import annotations

from typing import Any, List

JOB_PROPERTIES = ("Operations", "Model", "Tools")


def is_job(obj: Any) -> bool:
    return all(hasattr(obj, name) for name in JOB_PROPERTIES)


def find_jobs(document: Any) -> List[Any]:
    """Every CAM Job of the document, in document order."""
    return [obj for obj in document.Objects if is_job(obj)]
