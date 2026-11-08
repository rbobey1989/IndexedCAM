import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.document_storage import (  # noqa: E402
    JobProgramStorage,
    JobSetupsStorage,
    JobSettingStorage,
)
from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.setup_manager import MemoryStorage, SetupManager  # noqa: E402


def setup(name):
    return IndexedSetup(name=name, normal=(0, 0, 1), b=0, c=0)


@pytest.fixture
def manager():
    m = SetupManager(MemoryStorage())
    for n in ("A", "B", "C"):
        m.add(setup(n))
    return m


def test_add_get_list(manager):
    assert manager.names() == ["A", "B", "C"]
    assert len(manager) == 3
    assert manager.get("b").name == "B"
    assert "C" in manager and "Z" not in manager and 5 not in manager


def test_add_duplicate_rejected_case_insensitive(manager):
    with pytest.raises(ValueError, match="already exists"):
        manager.add(setup("a"))
    assert len(manager) == 3


def test_get_missing(manager):
    with pytest.raises(KeyError):
        manager.get("Z")


def test_rename(manager):
    manager.rename("A", "Top")
    assert manager.names() == ["Top", "B", "C"]
    manager.rename("Top", "TOP")
    assert manager.names()[0] == "TOP"


def test_rename_errors_leave_state(manager):
    with pytest.raises(ValueError, match="already exists"):
        manager.rename("A", "b")
    with pytest.raises(ValueError, match="empty"):
        manager.rename("A", "  ")
    with pytest.raises(KeyError):
        manager.rename("Z", "Y")
    assert manager.names() == ["A", "B", "C"]


def test_delete(manager):
    removed = manager.delete("B")
    assert removed.name == "B"
    assert manager.names() == ["A", "C"]
    with pytest.raises(KeyError):
        manager.delete("B")


def test_move_and_clamp(manager):
    manager.move("C", 0)
    assert manager.names() == ["C", "A", "B"]
    manager.move("C", 99)
    assert manager.names() == ["A", "B", "C"]
    manager.move("B", -5)
    assert manager.names() == ["B", "A", "C"]


def test_reorder(manager):
    manager.reorder(["C", "A", "B"])
    assert manager.names() == ["C", "A", "B"]
    with pytest.raises(ValueError, match="permutation"):
        manager.reorder(["A", "B"])
    with pytest.raises(ValueError, match="permutation"):
        manager.reorder(["A", "A", "B"])


def test_unique_name(manager):
    assert manager.unique_name("Setup") == "Setup"
    assert manager.unique_name("A") == "A 2"
    manager.add(setup("A 2"))
    assert manager.unique_name("A") == "A 3"


def test_persistence_and_update():
    storage = MemoryStorage()
    m = SetupManager(storage)
    s = m.add(setup("A"))
    s.add_operation("Pocket")
    m.update(s)
    reloaded = SetupManager(storage)
    assert reloaded.get("A").operations == ["Pocket"]
    with pytest.raises(KeyError):
        m.update(setup("A"))


def test_loading_duplicate_names_rejected():
    storage = MemoryStorage()
    data = setup("A").to_dict()
    storage.save([data, dict(data, name="a")])
    with pytest.raises(ValueError, match="duplicate"):
        SetupManager(storage)


class FakeJob:
    """Orientation Job stand-in: hidden string properties."""

    TypeId = "Path::FeaturePython"
    Label = "Job"
    Visibility = True

    def __init__(self, document, name):
        self.Document = document
        self.Name = name
        self.modes = {}
        self.IndexedCAMSetup = ""

    def addProperty(self, kind, name, group, doc):
        assert kind == "App::PropertyString"
        setattr(self, name, "")

    def setEditorMode(self, name, mode):
        self.modes[name] = mode


class FakeDocument:
    def __init__(self, jobs=()):
        self.Objects = list(jobs)
        self.removed = []

    def getObject(self, name):
        return next((o for o in self.Objects if o.Name == name), None)

    def recompute(self):
        pass

    def removeObject(self, name):
        self.removed.append(name)
        self.Objects = [o for o in self.Objects if o.Name != name]


def job_for(document, name, setup_name):
    job = FakeJob(document, name)
    job.IndexedCAMSetup = json.dumps(
        IndexedSetup(name=setup_name, normal=(0, 0, 1), b=0, c=0).to_dict()
    )
    return job


def test_job_setups_storage_reads_the_orientation_jobs():
    doc = FakeDocument()
    doc.Objects = [job_for(doc, "JobA", "A"), job_for(doc, "JobB", "B")]
    assert SetupManager(JobSetupsStorage(doc)).names() == ["A", "B"]


def test_job_setups_storage_follows_the_manager():
    doc = FakeDocument()
    manager = SetupManager(JobSetupsStorage(doc))
    assert manager.names() == []
    # sin pieza de origen en los metadatos no se puede crear el Job
    manager.add(setup("A"))
    assert manager.names() == ["A"] and doc.Objects == []


def test_program_and_settings_live_on_the_jobs():
    doc = FakeDocument()
    doc.Objects = [job_for(doc, "JobA", "A"), job_for(doc, "JobB", "B")]

    class Store(JobSettingStorage):
        property_name = "IndexedCAMPrueba"
        tooltip = "prueba"

    store = Store(doc)
    assert store._raw() == ""
    store._store({"margin": 3.0})
    assert json.loads(store._raw()) == {"margin": 3.0}
    assert all(json.loads(job.IndexedCAMPrueba)["margin"] == 3.0 for job in doc.Objects)

    program = JobProgramStorage(doc)
    assert program.load() == []
    program.save([{"setup": "A", "operation": "Pocket"}])
    assert program.load() == [{"setup": "A", "operation": "Pocket"}]


def test_name_error_rules(manager):
    assert manager.name_error("Nuevo") == ""
    assert "vacío" in manager.name_error("   ")
    assert "Ya existe" in manager.name_error("a")
    assert manager.name_error("B", renaming="B") == "El nombre es el mismo."
    assert manager.name_error("b", renaming="B") == ""
    assert "Ya existe" in manager.name_error("A", renaming="B")
