import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.operation_assignment import (  # noqa: E402
    OPERATION_TYPES,
    AssignmentError,
    AssignOperationWorkflow,
    Choice,
    OperationLauncher,
    parse_source,
)
from IndexedCAM.Core.setup_manager import MemoryStorage, SetupManager  # noqa: E402


def make_setup(name="Cara X", source="Box.Face2"):
    return IndexedSetup(
        name=name, normal=(1.0, 0.0, 0.0), b=90.0, c=0.0, metadata={"source": source}
    )


class FakeBridge:
    def __init__(self):
        self.job = None
        self.calls = []
        self.bound = []

    def find_job(self):
        return self.job

    def ensure_job(self, source):
        self.calls.append(("ensure_job", source))
        self.job = self.job or SimpleNamespace(name="Job")
        return self.job

    def attach_setup(self, job, source, setup):
        self.calls.append(("attach", setup.name))

    def bind_operation(self, operation, setup_name, face):
        self.bound.append((operation, setup_name, face))
        operation.IndexedSetup = setup_name

    def operations_of(self, job, setup_name):
        return [
            op for op in getattr(job, "ops", []) if getattr(op, "IndexedSetup", None) == setup_name
        ]


class FakeLauncher(OperationLauncher):
    def __init__(self, result="op"):
        self.result = result
        self.launched = []

    def launch(self, job, operation, bind):
        self.launched.append(operation.key)
        if self.result is None:
            return None
        created = SimpleNamespace(Name="Op1", Label="Op1")
        bind(created)
        job.ops = getattr(job, "ops", []) + [created]
        return created


class Transaction:
    log = []

    def __enter__(self):
        Transaction.log.append("open")

    def __exit__(self, *exc):
        Transaction.log.append("close" if exc[0] is None else "abort")


def build(setups=(), chooser=None, source=object(), launcher=None):
    manager = SetupManager(MemoryStorage())
    for setup in setups:
        manager.add(setup)
    bridge = FakeBridge()
    launcher = launcher or FakeLauncher()
    workflow = AssignOperationWorkflow(
        manager,
        bridge,
        launcher,
        chooser or (lambda s, t: Choice(s[-1].name, t[0])),
        lambda name: source if name == "Box" else None,
        Transaction,
    )
    return workflow, manager, bridge, launcher


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


def test_cancel_changes_nothing():
    workflow, _, bridge, launcher = build([make_setup()], chooser=lambda s, t: None)
    assert workflow.run() is None
    assert bridge.calls == [] and launcher.launched == []


def test_assign_prepares_job_binds_face_and_launches():
    Transaction.log.clear()
    workflow, manager, bridge, launcher = build([make_setup("A"), make_setup("B")])
    result = workflow.run()
    assert result.setup.name == "B"
    assert launcher.launched == [OPERATION_TYPES[0].key]
    assert [c[0] for c in bridge.calls] == ["ensure_job", "attach"]
    assert bridge.bound[0][1:] == ("B", "Face2")
    assert Transaction.log == ["open", "close"]


def test_setup_operations_follow_the_job():
    workflow, manager, *_ = build([make_setup()])
    workflow.run()
    assert manager.get("Cara X").operations == ["Op1"]


def test_cancelled_operation_is_not_recorded():
    workflow, manager, *_ = build([make_setup()], launcher=FakeLauncher(result=None))
    assert workflow.run() is None
    assert manager.get("Cara X").operations == []


def test_stale_operations_are_pruned_on_next_run():
    setup = make_setup()
    setup.operations = ["Gone"]
    workflow, manager, bridge, _ = build([setup], chooser=lambda s, t: None)
    bridge.job = SimpleNamespace(ops=[])
    workflow.run()
    assert manager.get("Cara X").operations == []


def test_missing_source_object_is_reported_before_changes():
    workflow, _, bridge, launcher = build([make_setup(source="Gone.Face1")])
    with pytest.raises(AssignmentError, match="Gone"):
        workflow.run()
    assert bridge.calls == [] and launcher.launched == []


def test_operation_catalog_is_unique_and_native():
    keys = [t.key for t in OPERATION_TYPES]
    assert len(keys) == len(set(keys))
    assert all(t.gui_module.startswith("Path.Op.Gui.") for t in OPERATION_TYPES)
