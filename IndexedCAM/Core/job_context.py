"""Find the native CAM Job an IndexedCAM action belongs to.

IndexedCAM never creates a Job: the user creates it in the CAM workbench and
the orientations live inside it. With several Jobs in the document, the one
related to the selection is used, and the user is asked only when ambiguous.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Optional, Sequence

JOB_PROPERTIES = ("Operations", "Model", "Tools")


class JobError(ValueError):
    """No usable Job (shown to the user as a warning)."""


class JobCancelled(JobError):
    """The user dismissed the Job choice (not an error to report)."""


Chooser = Callable[[Sequence[Any]], Optional[Any]]


def is_job(obj: Any) -> bool:
    return all(hasattr(obj, name) for name in JOB_PROPERTIES)


def find_jobs(document: Any) -> List[Any]:
    return [obj for obj in document.Objects if is_job(obj)]


def jobs_of(obj: Any) -> List[Any]:
    """Jobs that ``obj`` is, or is (transitively) used by, in document order."""
    found: List[Any] = []
    seen = set()
    queue = [obj]
    while queue:
        current = queue.pop(0)
        if current.Name in seen:
            continue
        seen.add(current.Name)
        if is_job(current):
            found.append(current)
            continue
        queue.extend(getattr(current, "InList", ()))
    return found


def resolve_job(
    document: Any, selected: Iterable[Any], choose: Chooser
) -> Any:
    """The Job for the selection, the only Job, or the one the user picks."""
    jobs = find_jobs(document)
    if not jobs:
        raise JobError(
            "No hay ningún Job. Crea uno en el banco CAM (Job) antes de usar IndexedCAM."
        )
    related: List[Any] = []
    for obj in selected:
        for job in jobs_of(obj):
            if job not in related:
                related.append(job)
    candidates = related or jobs
    if len(candidates) == 1:
        return candidates[0]
    chosen = choose(candidates)
    if chosen is None:
        raise JobCancelled("No se eligió un Job.")
    return chosen
