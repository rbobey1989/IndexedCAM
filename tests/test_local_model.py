import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.local_model import find, is_local_model  # noqa: E402


def model(name):
    return SimpleNamespace(Name=name, SetupName=name, LocalPlacement=1)


def part(name):
    return SimpleNamespace(Name=name)


def test_is_local_model_needs_both_properties():
    assert is_local_model(model("Sup"))
    assert not is_local_model(part("Clone"))
    assert not is_local_model(SimpleNamespace(SetupName="Sup"))


def test_find_searches_the_job_model_first():
    job = SimpleNamespace(Model=SimpleNamespace(Group=[part("Clone"), model("Sup"), model("Side")]))
    assert find(job, "sup") is job.Model.Group[1]
    assert find(job, "Lado") is None


def test_find_accepts_a_document_or_a_group():
    document = SimpleNamespace(Objects=[part("Box"), model("Sup")])
    assert find(document, "Sup") is document.Objects[1]
    group = SimpleNamespace(Group=[model("Side")])
    assert find(group, "Side") is group.Group[0]
