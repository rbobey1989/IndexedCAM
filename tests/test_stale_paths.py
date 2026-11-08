"""Marks of documents whose saved toolpaths may not match the part."""

import pytest

from IndexedCAM.Core import stale_paths


class FakeDocument:
    def __init__(self, name):
        self.Name = name


@pytest.fixture(autouse=True)
def clear_marks():
    stale_paths.forget()
    yield
    stale_paths.forget()


def test_take_reports_a_mark_once():
    document = FakeDocument("Part")
    assert not stale_paths.take(document)
    stale_paths.mark(document)
    assert stale_paths.take(document)
    assert not stale_paths.take(document)


def test_mark_is_per_document():
    first, second = FakeDocument("First"), FakeDocument("Second")
    stale_paths.mark(first)
    assert stale_paths.marked(first)
    assert not stale_paths.marked(second)
    assert stale_paths.take(second) is False


def test_mark_twice_still_one_refresh():
    document = FakeDocument("Part")
    stale_paths.mark(document)
    stale_paths.mark(document)
    assert stale_paths.take(document)
    assert not stale_paths.take(document)


def test_forget_drops_the_mark():
    document = FakeDocument("Part")
    stale_paths.mark(document)
    stale_paths.forget(document)
    assert not stale_paths.marked(document)


def test_forget_all():
    first, second = FakeDocument("First"), FakeDocument("Second")
    stale_paths.mark(first)
    stale_paths.mark(second)
    stale_paths.forget()
    assert not stale_paths.marked(first)
    assert not stale_paths.marked(second)


def test_objects_without_a_document_name_are_ignored():
    stale_paths.mark(object())
    assert not stale_paths.take(object())
