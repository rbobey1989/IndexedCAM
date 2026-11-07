import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.job_context import find_jobs, is_job  # noqa: E402


def job(name):
    return SimpleNamespace(Name=name, Operations=1, Model=1, Tools=1)


def obj(name):
    return SimpleNamespace(Name=name)


def document(*objects):
    return SimpleNamespace(Objects=list(objects))


def test_is_job_requires_the_cam_groups():
    assert is_job(job("Job"))
    assert not is_job(obj("Box"))
    assert not is_job(SimpleNamespace(Operations=1, Model=1))


def test_find_jobs_keeps_document_order():
    first, second = job("Job"), job("IndexedCAM_Job_Side")
    assert find_jobs(document(first, obj("Box"), second)) == [first, second]


def test_find_jobs_without_cam_jobs():
    assert find_jobs(document(obj("Box"), obj("Sketch"))) == []
