import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.job_context import (  # noqa: E402
    JobCancelled,
    JobError,
    find_jobs,
    is_job,
    jobs_of,
    resolve_job,
)


def job(name):
    return SimpleNamespace(Name=name, Operations=1, Model=1, Tools=1, InList=[])


def obj(name, *users):
    return SimpleNamespace(Name=name, InList=list(users))


def document(*objects):
    return SimpleNamespace(Objects=list(objects))


def test_is_job_and_find_jobs():
    j = job("Job")
    assert is_job(j) and not is_job(obj("Box"))
    assert find_jobs(document(obj("Box"), j)) == [j]


def test_jobs_of_follows_users_up_to_the_job():
    j = job("Job")
    clone = obj("Clone", j)
    box = obj("Box", clone)
    assert jobs_of(box) == [j]
    assert jobs_of(j) == [j]
    assert jobs_of(obj("Lonely")) == []


def test_jobs_of_survives_cycles():
    a, b = obj("A"), obj("B")
    a.InList, b.InList = [b], [a]
    assert jobs_of(a) == []


def test_no_job_asks_to_create_one_in_cam():
    with pytest.raises(JobError, match="banco CAM"):
        resolve_job(document(obj("Box")), [], lambda jobs: None)


def test_single_job_needs_no_question():
    j = job("Job")
    assert resolve_job(document(j), [], lambda jobs: pytest.fail("asked")) is j


def test_selection_picks_its_job_among_several():
    j1, j2 = job("Job1"), job("Job2")
    box = obj("Box", obj("Clone", j2))
    assert resolve_job(document(j1, j2), [box], lambda jobs: pytest.fail("asked")) is j2


def test_ambiguous_selection_asks_with_candidates_only():
    j1, j2, j3 = job("Job1"), job("Job2"), job("Job3")
    box = obj("Box", j1, j2)
    asked = []

    def choose(jobs):
        asked.append(jobs)
        return jobs[1]

    assert resolve_job(document(j1, j2, j3), [box], choose) is j2
    assert asked == [[j1, j2]]


def test_unrelated_selection_falls_back_to_all_jobs():
    j1, j2 = job("Job1"), job("Job2")
    assert resolve_job(document(j1, j2), [obj("Other")], lambda jobs: jobs[0]) is j1


def test_cancelled_choice_is_silent_type():
    with pytest.raises(JobCancelled):
        resolve_job(document(job("A"), job("B")), [], lambda jobs: None)
