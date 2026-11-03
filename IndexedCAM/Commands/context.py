"""Everything a command needs for one Job, built from the active document."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from IndexedCAM.Core.cam_bridge import CamBridge
from IndexedCAM.Core.document_storage import JobProgramStorage, JobStorage
from IndexedCAM.Core.job_context import resolve_job
from IndexedCAM.Core.operation_assignment import OperationAssigner
from IndexedCAM.Core.program import Program
from IndexedCAM.Core.setup_manager import SetupManager


@dataclass(frozen=True)
class JobContext:
    document: Any
    job: Any
    manager: SetupManager
    program: Program
    bridge: CamBridge
    assigner: OperationAssigner


def build_context(document: Any, job: Any) -> JobContext:
    manager = SetupManager(JobStorage(job))
    program = Program(JobProgramStorage(job))
    bridge = CamBridge(job)
    return JobContext(
        document,
        job,
        manager,
        program,
        bridge,
        OperationAssigner(manager, bridge, document.getObject, program),
    )


def open_context(document: Any, selected: Iterable[Any] = ()) -> JobContext:
    """Context of the Job related to ``selected`` (asks only when ambiguous)."""
    from IndexedCAM.Commands.dialogs import choose_job

    return build_context(document, resolve_job(document, selected, choose_job))


def selected_objects() -> list:
    import FreeCADGui as Gui

    return [item.Object for item in Gui.Selection.getSelectionEx()]
