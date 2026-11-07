import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.operation_assignment import (  # noqa: E402
    AssignmentError,
    AssignOperationWorkflow,
    OperationAssigner,
    parse_source,
)
from IndexedCAM.Core.program import MemoryProgramStorage, Program  # noqa: E402
from IndexedCAM.Core.setup_manager import MemoryStorage, SetupManager  # noqa: E402


def make_setup(name="Cara X", source="Box.Face2"):
    return IndexedSetup(
        name=name, normal=(1.0, 0.0, 0.0), b=90.0, c=0.0, metadata={"source": source}
    )


def make_op(name):
    return SimpleNamespace(Name=name, Label=name)


class FakeBridge:
    """Simulates the orientation Jobs: one operation list per Setup."""

    def __init__(self, ops):
        self.ops = ops
        self.by_setup = {}
        self.calls = []

    def candidates(self):
        return list(self.ops)

    def attach_setup(self, source, setup):
        self.calls.append(("attach", setup.name))
        self.by_setup.setdefault(setup.name, [])

    def bind_operation(self, operation, setup_name, face=None):
        self.calls.append(("bind", operation.Name, setup_name))
        for bound in self.by_setup.values():
            if operation in bound:
                bound.remove(operation)
        self.by_setup.setdefault(setup_name, []).append(operation)

    def operations(self):
        return [op for bound in self.by_setup.values() for op in bound]

    def operations_of(self, setup_name):
        return list(self.by_setup.get(setup_name, []))

    def bound_steps(self):
        from IndexedCAM.Core.program import Step

        return [
            Step(name, op.Name) for name, bound in self.by_setup.items() for op in bound
        ]


class Transaction:
    log = []

    def __enter__(self):
        Transaction.log.append("open")

    def __exit__(self, *exc):
        Transaction.log.append("close" if exc[0] is None else "abort")


def build(setups=(), ops=("Op1", "Op2"), chooser=None, source=object()):
    manager = SetupManager(MemoryStorage())
    for setup in setups:
        manager.add(setup)
    bridge = FakeBridge([make_op(n) for n in ops])
    program = Program(MemoryProgramStorage())
    assigner = OperationAssigner(
        manager, bridge, lambda name: source if name == "Box" else None, program
    )
    workflow = AssignOperationWorkflow(
        manager,
        bridge,
        assigner,
        chooser or (lambda s, o: (s[-1].name, [o[0]])),
        Transaction,
    )
    return workflow, manager, bridge, program, assigner


def test_parse_source():
    ref = parse_source("Box.Face12")
    assert (ref.object_name, ref.face) == ("Box", "Face12")
    assert parse_source("Body.Pad.Face3").object_name == "Body.Pad"


@pytest.mark.parametrize("bad", ["", "Box", "Box.Edge1", "Box.Face", ".Face1", "Face1"])
def test_parse_source_rejects_invalid(bad):
    with pytest.raises(AssignmentError):
        parse_source(bad)


def test_without_setups_asks_to_create_one():
    workflow, *_ = build()
    with pytest.raises(AssignmentError, match="Face Orientation"):
        workflow.run()


def test_without_operations_asks_to_create_them_in_cam():
    workflow, *_ = build([make_setup()], ops=())
    with pytest.raises(AssignmentError, match="banco CAM"):
        workflow.run()


def test_cancel_changes_nothing():
    workflow, _, bridge, *_ = build([make_setup()], chooser=lambda s, o: None)
    assert workflow.run() is None
    assert bridge.calls == []


def test_assign_attaches_setup_and_binds_chosen_operations():
    Transaction.log.clear()
    workflow, manager, bridge, *_ = build([make_setup("A"), make_setup("B")])
    result = workflow.run()
    assert result.setup.name == "B"
    assert bridge.calls == [("attach", "B"), ("bind", "Op1", "B")]
    assert Transaction.log == ["open", "close"]


def test_setup_operations_and_program_follow_the_job():
    workflow, manager, _, program, _ = build([make_setup()])
    workflow.run()
    assert manager.get("Cara X").operations == ["Op1"]
    assert [s.operation for s in program.steps()] == ["Op1"]


def test_assign_with_no_operations_only_attaches_the_setup():
    _, manager, bridge, _, assigner = build([make_setup()])
    assigner.assign("Cara X", [])
    assert bridge.calls == [("attach", "Cara X")]
    assert manager.get("Cara X").operations == []


def test_stale_operations_are_pruned_on_sync():
    setup = make_setup()
    setup.operations = ["Gone"]
    _, manager, _, _, assigner = build([setup])
    assigner.sync_operations()
    assert manager.get("Cara X").operations == []


def test_missing_source_object_is_reported_before_changes():
    workflow, _, bridge, *_ = build([make_setup(source="Gone.Face1")])
    with pytest.raises(AssignmentError, match="Gone"):
        workflow.run()
    assert bridge.calls == []
