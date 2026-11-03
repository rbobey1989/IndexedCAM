import pytest

np = pytest.importorskip("numpy")

from IndexedCAM.Core.preview import OPERATION, TRANSITION, Clip, PreviewFrame
from IndexedCAM.Core.stock_timeline import StockTimeline
from IndexedCAM.Core.voxel_stock import VoxelStock
from IndexedCAM.Machine.bc_machine import BCMachine


def _clip(kind, tips, b=0.0, c=0.0, radius=2.0, cutting=20.0):
    envelope = BCMachine().envelope.with_tool(radius, 30.0, cutting)
    frames = [PreviewFrame(t, b, c) for t in tips]
    return Clip(kind, "t", 0, frames, envelope, lambda tip, b, c: None)


def _timeline(clips):
    return StockTimeline(VoxelStock((0, 0, 0), (30, 30, 10), 0.5), clips)


def _line(y):
    return [(x, y, 5.0) for x in range(5, 26, 2)]


def test_operation_removes_material_and_transition_does_not():
    timeline = _timeline([_clip(TRANSITION, _line(15)), _clip(OPERATION, _line(15))])
    full = timeline.stock.volume()
    timeline.show(0, 5)
    assert timeline.stock.volume() == pytest.approx(full)
    timeline.show(1, 5)
    assert timeline.stock.volume() < full


def test_scrubbing_backwards_restores_material():
    timeline = _timeline([_clip(OPERATION, _line(15))])
    full = timeline.stock.volume()
    timeline.show(0, 10)
    cut = timeline.stock.volume()
    timeline.show(0, 2)
    assert full > timeline.stock.volume() > cut
    timeline.show(0, 0)
    assert timeline.stock.volume() > cut


def test_incremental_and_rebuilt_states_match():
    clips = [_clip(OPERATION, _line(10)), _clip(OPERATION, _line(20))]
    a, b = _timeline(clips), _timeline(clips)
    for i in range(0, 6):
        a.show(1, i)
    b.show(1, 5)
    assert (a.stock.cells == b.stock.cells).all()


def test_later_clip_starts_from_the_previous_cuts():
    clips = [_clip(OPERATION, _line(10)), _clip(OPERATION, _line(20))]
    timeline = _timeline(clips)
    timeline.show(1, 0)
    first_only = _timeline(clips[:1])
    first_only.final()
    assert timeline.stock.volume() <= first_only.stock.volume() + 1e-6


def test_tilted_clip_cuts_differently_from_vertical():
    vertical, tilted = _timeline([_clip(OPERATION, _line(15))]), _timeline([_clip(OPERATION, _line(15), b=90.0, c=0.0)])
    assert not (vertical.final().cells == tilted.final().cells).all()


def test_tool_radius_of_each_operation_is_used():
    thin, thick = _timeline([_clip(OPERATION, _line(15), radius=1.0)]), _timeline([_clip(OPERATION, _line(15), radius=4.0)])
    assert thick.final().volume() < thin.final().volume()


def test_inside_mask_limits_the_stock():
    stock = VoxelStock((0, 0, 0), (10, 10, 10), 1.0, inside=lambda c: c[:, 0] < 5)
    assert stock.volume() == pytest.approx(500)
