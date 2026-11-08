import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Commands.rename_setup import RenameError, RenameSetupWorkflow  # noqa: E402
from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.setup_manager import MemoryStorage, SetupManager  # noqa: E402


class Renamer:
    def __init__(self):
        self.calls = []

    def rename_setup(self, old, new):
        self.calls.append((old, new))


def make(request, names=("A", "B"), transaction=None):
    manager = SetupManager(MemoryStorage())
    for n in names:
        manager.add(IndexedSetup(name=n, normal=(0, 0, 1), b=0, c=0))
    renamer = Renamer()
    return RenameSetupWorkflow(manager, renamer, request, transaction), manager, renamer


def test_rename_updates_manager_and_dependents():
    workflow, manager, renamer = make(lambda s, e: ("A", " Cara "))
    assert workflow.run().name == "Cara"
    assert manager.names() == ["Cara", "B"]
    assert renamer.calls == [("A", "Cara")]


def test_cancel_changes_nothing():
    workflow, manager, renamer = make(lambda s, e: None)
    assert workflow.run() is None
    assert manager.names() == ["A", "B"] and renamer.calls == []


@pytest.mark.parametrize("new,message", [("", "vacío"), ("b", "Ya existe"), ("A", "mismo")])
def test_invalid_names_rejected(new, message):
    workflow, manager, renamer = make(lambda s, e: ("A", new))
    with pytest.raises(RenameError, match=message):
        workflow.run()
    assert manager.names() == ["A", "B"] and renamer.calls == []


def test_no_setups():
    workflow, _, _ = make(lambda s, e: None, names=())
    with pytest.raises(RenameError, match="No hay"):
        workflow.run()


def test_case_only_rename_allowed():
    workflow, manager, _ = make(lambda s, e: ("A", "a"))
    workflow.run()
    assert manager.names() == ["a", "B"]


def test_validator_given_to_dialog():
    seen = []
    workflow, _, _ = make(lambda s, e: seen.append(e("A", "B")) or None)
    workflow.run()
    assert "Ya existe" in seen[0]


def test_failure_inside_transaction_aborts():
    events = []

    class Tx:
        def __enter__(self):
            events.append("open")

        def __exit__(self, exc_type, exc, tb):
            events.append("abort" if exc_type else "commit")

    workflow, _, renamer = make(lambda s, e: ("A", "C"), transaction=Tx)
    renamer.rename_setup = lambda o, n: (_ for _ in ()).throw(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        workflow.run()
    assert events == ["open", "abort"]


def test_the_job_is_renamed_before_the_setup_is_persisted():
    """El listado guardado es el que crea/renombra/borra los Jobs de orientación.

    Si se guardara el nombre nuevo con el Job todavía con el viejo, el Job se
    vería como un Setup nuevo (y el viejo se borraría con sus operaciones).
    """
    events = []

    class Storage(MemoryStorage):
        def save(self, setups):
            events.append(("save", [s["name"] for s in setups]))
            super().save(setups)

    class OrderRenamer:
        def rename_setup(self, old, new):
            events.append(("rename", old, new))

    manager = SetupManager(Storage())
    manager.add(IndexedSetup(name="A", normal=(0, 0, 1), b=0, c=0))
    events.clear()
    RenameSetupWorkflow(manager, OrderRenamer(), lambda s, e: ("A", "Z")).run()
    assert events == [("rename", "A", "Z"), ("save", ["Z"])]


def test_rename_also_updates_program():
    from IndexedCAM.Core.program import MemoryProgramStorage, Program, Step

    program = Program(MemoryProgramStorage())
    program.add(Step("A", "op1"))
    manager = SetupManager(MemoryStorage())
    manager.add(IndexedSetup(name="A", normal=(0, 0, 1), b=0, c=0))
    RenameSetupWorkflow(manager, Renamer(), lambda s, e: ("A", "Z"), None, program).run()
    assert program.steps() == [Step("Z", "op1")]
