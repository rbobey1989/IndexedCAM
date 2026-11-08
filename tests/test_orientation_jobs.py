import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.orientation_jobs import (  # noqa: E402
    LEGACY_CONTAINER,
    SETUP_PROPERTY,
    OrientationJobs,
    is_orientation_job,
)
from IndexedCAM.Machine.bc_head import bc_to_normal  # noqa: E402


def setup(name, b=0.0, c=0.0):
    return IndexedSetup(name=name, normal=bc_to_normal(b, c), b=b, c=c)


def fake_job(document, name, setup_name, operations=(), b=0.0, c=0.0):
    return SimpleNamespace(
        Name=name,
        Label=name,
        TypeId="Path::FeaturePython",
        Document=document,
        Operations=SimpleNamespace(Group=list(operations)),
        Model=SimpleNamespace(Group=[SimpleNamespace(Name=name + "_model")]),
        Stock=SimpleNamespace(Name=name + "_stock"),
        **{SETUP_PROPERTY: json.dumps(setup(setup_name, b, c).to_dict())},
    )


def fake_document(*objects):
    document = SimpleNamespace(Name="Doc", Objects=list(objects), removed=[], recomputed=0)

    def remove(name):
        document.removed.append(name)
        document.Objects = [o for o in document.Objects if o.Name != name]

    def recompute():
        document.recomputed += 1

    document.removeObject = remove
    document.recompute = recompute
    document.getObject = lambda name: next((o for o in document.Objects if o.Name == name), None)
    return document


def jobs_over(*objects):
    return OrientationJobs(fake_document(*objects))


def test_is_orientation_job_only_matches_jobs_with_a_setup():
    document = fake_document()
    assert is_orientation_job(fake_job(document, "J", "Superior"))
    assert not is_orientation_job(SimpleNamespace(TypeId="Path::FeaturePython"))
    assert not is_orientation_job(SimpleNamespace(TypeId="Part::Box", IndexedCAMSetup="{}"))


def test_jobs_find_and_names_keep_document_order():
    document = fake_document()
    second = fake_job(document, "J2", "Lateral")
    first = fake_job(document, "J1", "Superior")
    foreign = SimpleNamespace(TypeId="Part::Box", Name="Box")
    jobs = OrientationJobs(fake_document(first, foreign, second))
    assert jobs.jobs() == [first, second]
    assert jobs.find("lateral") is second
    assert jobs.find("Inexistente") is None
    assert [s.name for s in jobs.setups()] == ["Superior", "Lateral"]
    assert len(jobs) == 2


def test_nothing_is_created_for_a_new_document():
    created = []
    document = SimpleNamespace(
        Name="Doc",
        Objects=[],
        getObject=lambda name: None,
        addObject=lambda kind, name: created.append(name),
        removeObject=lambda name: None,
        recompute=lambda: None,
    )
    jobs = OrientationJobs(document)
    assert jobs.jobs() == [] and jobs.operations() == [] and jobs.bound_steps() == []
    jobs.adopt_legacy()
    assert created == []


def test_label_shows_the_angles():
    assert OrientationJobs.label(setup("Lateral", 45.0, 90.0)) == "Lateral B45.0 C90.0"


def test_operations_and_steps_follow_document_and_job_order():
    document = fake_document()
    a1, a2, b1 = (SimpleNamespace(Name=n) for n in ("A1", "A2", "B1"))
    jobs = OrientationJobs(
        fake_document(
            fake_job(document, "JA", "Superior", [a1, a2]), fake_job(document, "JB", "Lateral", [b1])
        )
    )
    assert jobs.operations() == [a1, a2, b1]
    assert jobs.operations_of("lateral") == [b1]
    assert [(s.setup, s.operation) for s in jobs.bound_steps()] == [
        ("Superior", "A1"),
        ("Superior", "A2"),
        ("Lateral", "B1"),
    ]


def test_setup_of_operation_finds_the_owning_job():
    document = fake_document()
    op = SimpleNamespace(Name="Pocket")
    jobs = OrientationJobs(fake_document(fake_job(document, "JA", "Superior", [op])))
    assert jobs.setup_of_operation(op) == "Superior"
    assert jobs.setup_of_operation(SimpleNamespace(Name="Otro")) is None


def test_model_and_stock_of_a_setup():
    document = fake_document()
    job = fake_job(document, "JA", "Superior")
    jobs = OrientationJobs(fake_document(job))
    assert jobs.model("Superior") is job.Model.Group[0]
    assert jobs.stock_of("Superior") is job.Stock


def test_missing_setup_raises_on_model():
    from IndexedCAM.Core.orientation_jobs import CamBridgeError

    jobs = OrientationJobs(fake_document())
    with pytest.raises(CamBridgeError, match="no CAM Job"):
        jobs.model("Superior")


def test_operations_of_a_missing_setup_is_empty():
    jobs = OrientationJobs(fake_document())
    assert jobs.operations_of("Nada") == []


def test_setup_of_reads_the_stored_json():
    document = fake_document()
    job = fake_job(document, "JA", "Lateral", b=45.0, c=90.0)
    stored = OrientationJobs.setup_of(job)
    assert (stored.name, stored.b, stored.c) == ("Lateral", 45.0, 90.0)


def test_remove_takes_the_job_and_its_model_away():
    document = fake_document()
    job = fake_job(document, "JA", "Superior")
    model = SimpleNamespace(Name="IndexedCAM_Local_Superior", SetupName="Superior", LocalPlacement=1)
    document.Objects = [job, model]
    OrientationJobs(document).remove("Superior")
    assert document.removed == ["JA", "IndexedCAM_Local_Superior"]
    assert document.Objects == []


def test_legacy_container_is_emptied_and_removed():
    document = fake_document()
    job = fake_job(document, "JA", "Superior")
    model = SimpleNamespace(Name="IndexedCAM_Local_Superior", SetupName="Superior", LocalPlacement=1)
    container = SimpleNamespace(
        Name=LEGACY_CONTAINER,
        Group=[model, job],
        IndexedCAMContainer=True,
        removeObject=lambda obj: container.Group.remove(obj),
    )
    document.Objects = [container, model, job]
    assert OrientationJobs(document).adopt_legacy() is True
    assert container.Group == []
    assert LEGACY_CONTAINER in document.removed
    assert job in document.Objects and model in document.Objects


def test_documents_without_a_legacy_container_are_left_alone():
    document = fake_document(fake_job(fake_document(), "JA", "Superior"))
    assert OrientationJobs(document).adopt_legacy() is False
    assert document.removed == []
