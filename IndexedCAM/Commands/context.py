"""Everything a command needs for the document's IndexedCAM data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from IndexedCAM.Core.cam_bridge import CamBridge
from IndexedCAM.Core.document_storage import JobProgramStorage, JobSetupsStorage
from IndexedCAM.Core.operation_assignment import OperationAssigner
from IndexedCAM.Core.program import Program
from IndexedCAM.Core.setup_manager import SetupManager


@dataclass(frozen=True)
class IndexedContext:
    """Setups, program and CAM Jobs of one document."""

    document: Any
    manager: SetupManager
    program: Program
    bridge: CamBridge
    assigner: OperationAssigner


def build_context(document: Any) -> IndexedContext:
    """Context of ``document`` (nothing is created until something is saved)."""
    document = getattr(document, "Document", document)
    bridge = CamBridge(document)
    bridge.jobs.adopt_legacy()
    manager = SetupManager(JobSetupsStorage(document))
    program = Program(JobProgramStorage(document))
    return IndexedContext(
        document,
        manager,
        program,
        bridge,
        OperationAssigner(manager, bridge, document.getObject, program),
    )
