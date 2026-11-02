import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.document_storage import (  # noqa: E402
    CONTAINER_NAME,
    PROPERTY_NAME,
    DocumentStorage,
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


class FakeObject:
    def __init__(self):
        self.modes = {}

    def addProperty(self, kind, name, group, doc):
        assert kind == "App::PropertyString"
        setattr(self, name, "")

    def setEditorMode(self, name, mode):
        self.modes[name] = mode


class FakeDocument:
    def __init__(self):
        self.objects = {}

    def getObject(self, name):
        return self.objects.get(name)

    def addObject(self, kind, name):
        assert kind == "App::FeaturePython"
        self.objects[name] = FakeObject()
        return self.objects[name]


def test_document_storage_lazy_creation_and_roundtrip():
    doc = FakeDocument()
    storage = DocumentStorage(doc)
    assert storage.load() == []
    assert doc.objects == {}
    m = SetupManager(storage)
    assert doc.objects == {}
    m.add(setup("A"))
    assert json.loads(getattr(doc.objects[CONTAINER_NAME], PROPERTY_NAME))[0]["name"] == "A"
    assert SetupManager(DocumentStorage(doc)).names() == ["A"]


def test_document_storage_rejects_non_list():
    doc = FakeDocument()
    storage = DocumentStorage(doc)
    storage.save([])
    setattr(doc.objects[CONTAINER_NAME], PROPERTY_NAME, "{}")
    with pytest.raises(ValueError, match="list"):
        storage.load()


def test_name_error_rules(manager):
    assert manager.name_error("Nuevo") == ""
    assert "vacío" in manager.name_error("   ")
    assert "Ya existe" in manager.name_error("a")
    assert manager.name_error("B", renaming="B") == "El nombre es el mismo."
    assert manager.name_error("b", renaming="B") == ""
    assert "Ya existe" in manager.name_error("A", renaming="B")
