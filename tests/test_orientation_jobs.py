import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Machine.bc_head import bc_to_normal  # noqa: E402
from IndexedCAM.Core.orientation_jobs import (  # noqa: E402
    SETUP_PROPERTY,
    OrientationJobs,
    is_orientation_job,
)


def setup(name, b=0.0, c=0.0):
    return IndexedSetup(name=name, normal=bc_to_normal(b, c), b=b, c=c)


def fake_job(name, setup_name, operations=(), b=0.0, c=0.0):
    return SimpleNamespace(
        Name=name,
        Label=name,
        TypeId="Path::FeaturePython",
        Operations=SimpleNamespace(Group=list(operations)),
        Model=SimpleNamespace(Group=[SimpleNamespace(Name=name + "_model")]),
        Stock=SimpleNamespace(Name=name + "_stock"),
        **{SETUP_PROPERTY: json.dumps(setup(setup_name, b, c).to_dict())},
    )


def fake_container(*children):
    document = SimpleNamespace(Name="Doc")
    return SimpleNamespace(Document=document, Group=list(children))


def jobs_over(*children):
    """OrientationJobs over a container that already exists."""
    container = fake_container(*children)
    return OrientationJobs(container.Document, container)


def test_nothing_is_created_until_a_setup_needs_it():
    created = []
    document = SimpleNamespace(
        Name="Doc", getObject=lambda name: None, addObject=lambda kind, name: created.append(name)
    )
    jobs = OrientationJobs(document)
    assert jobs.jobs() == [] and jobs.operations() == [] and jobs.bound_steps() == []
    assert created == []


def test_is_orientation_job_only_matches_jobs_with_a_setup():
    assert is_orientation_job(fake_job("J", "Superior"))
    assert not is_orientation_job(SimpleNamespace(TypeId="Path::FeaturePython"))
    assert not is_orientation_job(SimpleNamespace(TypeId="Part::Box", IndexedCAMSetup="{}"))


def test_jobs_find_and_names_keep_container_order():
    second = fake_job("J2", "Lateral")
    first = fake_job("J1", "Superior")
    foreign = SimpleNamespace(TypeId="Part::Box", Name="Box")
    jobs = jobs_over(first, foreign, second)
    assert jobs.jobs() == [first, second]
    assert jobs.find("lateral") is second
    assert jobs.find("Inexistente") is None
    assert [s.name for s in jobs.setups()] == ["Superior", "Lateral"]


def test_label_shows_the_angles():
    assert OrientationJobs.label(setup("Lateral", 45.0, 90.0)) == "Lateral B45.0 C90.0"


def test_operations_and_steps_follow_container_and_job_order():
    a1, a2, b1 = (SimpleNamespace(Name=n) for n in ("A1", "A2", "B1"))
    jobs = jobs_over(fake_job("JA", "Superior", [a1, a2]), fake_job("JB", "Lateral", [b1]))
    assert jobs.operations() == [a1, a2, b1]
    assert jobs.operations_of("lateral") == [b1]
    assert [(s.setup, s.operation) for s in jobs.bound_steps()] == [
        ("Superior", "A1"),
        ("Superior", "A2"),
        ("Lateral", "B1"),
    ]


def test_setup_of_operation_finds_the_owning_job():
    op = SimpleNamespace(Name="Pocket")
    jobs = jobs_over(fake_job("JA", "Superior", [op]))
    assert jobs.setup_of_operation(op) == "Superior"
    assert jobs.setup_of_operation(SimpleNamespace(Name="Otro")) is None


def test_model_and_stock_of_a_setup():
    job = fake_job("JA", "Superior")
    jobs = jobs_over(job)
    assert jobs.model("Superior") is job.Model.Group[0]
    assert jobs.stock_of("Superior") is job.Stock


def test_missing_setup_raises_on_model():
    from IndexedCAM.Core.cam_bridge import CamBridgeError

    jobs = jobs_over()
    with pytest.raises(CamBridgeError, match="no CAM Job"):
        jobs.model("Superior")


def test_operations_of_a_missing_setup_is_empty():
    jobs = jobs_over()
    assert jobs.operations_of("Nada") == []


def test_setup_of_reads_the_stored_json():
    job = fake_job("JA", "Lateral", b=45.0, c=90.0)
    stored = OrientationJobs.setup_of(job)
    assert (stored.name, stored.b, stored.c) == ("Lateral", 45.0, 90.0)
