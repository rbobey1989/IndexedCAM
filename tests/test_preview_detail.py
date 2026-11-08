import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Commands import preview  # noqa: E402


def test_every_detail_has_a_resolution_and_they_get_finer():
    resolutions = [resolution for _, resolution in preview.STOCK_DETAILS]
    assert resolutions == sorted(resolutions, reverse=True)
    assert preview.stock_resolution("Fino") < preview.stock_resolution("Normal")
    assert preview.stock_resolution("Normal") < preview.stock_resolution("Grueso")


def test_unknown_detail_falls_back_to_the_default():
    assert preview.stock_resolution("lo que sea") == preview.stock_resolution(preview.DEFAULT_DETAIL)
    assert preview.stock_resolution() == preview.stock_resolution(preview.DEFAULT_DETAIL)


def test_default_is_fine_enough_to_see_the_machined_surface():
    assert preview.stock_resolution() <= 0.25
    assert preview.stock_resolution("Fino") <= 0.15


def test_cell_budget_grows_with_the_detail():
    assert preview.STOCK_MAX_CELLS >= 5_000_000
    assert preview.NON_BOX_MAX_CELLS < preview.STOCK_MAX_CELLS


@pytest.mark.parametrize("detail", [name for name, _ in preview.STOCK_DETAILS])
def test_detail_names_are_shown_with_their_resolution(detail):
    label = next(name for name, _ in preview.STOCK_DETAILS if name == detail)
    assert label == detail
