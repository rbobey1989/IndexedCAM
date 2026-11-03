import math

import pytest

np = pytest.importorskip("numpy")

from IndexedCAM.Core.voxel_stock import ToolProfile, VoxelStock


def _stock(res=0.5):
    return VoxelStock((0, 0, 0), (20, 20, 10), res)


def test_untouched_stock_keeps_its_volume():
    assert _stock().volume() == pytest.approx(20 * 20 * 10)


def test_vertical_plunge_removes_a_cylinder():
    stock = _stock(0.25)
    stock.carve((10, 10, 4), (0, 0, 1), ToolProfile.cylinder(2, 20))
    assert 20 * 20 * 10 - stock.volume() == pytest.approx(math.pi * 4 * 6, rel=0.05)


def test_horizontal_tool_cuts_from_the_side():
    stock = _stock(0.25)
    # tip travels from x=20 to x=10 with the tool body toward +X
    stock.carve_segment((20, 10, 5), (10, 10, 5), (1, 0, 0), ToolProfile.cylinder(2, 30))
    assert stock.cells[int(15 / 0.25), int(10 / 0.25), int(5 / 0.25)] == False  # noqa: E712
    assert stock.cells[int(5 / 0.25), int(10 / 0.25), int(5 / 0.25)]


def test_tilt_changes_what_is_removed():
    vertical, tilted = _stock(0.25), _stock(0.25)
    profile = ToolProfile.cylinder(1.5, 20)
    vertical.carve((10, 10, 5), (0, 0, 1), profile)
    tilted.carve((10, 10, 5), (1, 0, 1), profile)
    assert not (vertical.cells == tilted.cells).all()


def test_tool_outside_the_stock_removes_nothing():
    stock = _stock()
    stock.carve((100, 100, 100), (0, 0, 1), ToolProfile.cylinder(2, 5))
    assert stock.version == 0


def test_ball_profile_is_round_at_the_tip():
    profile = ToolProfile.ball(2, 6)
    assert profile.radii[0] == 0 and profile.radii[-1] == 2


def test_truncated_profile_shortens_the_tool():
    assert ToolProfile.cylinder(1, 10).truncated(4).length == pytest.approx(4)


def test_zero_axis_is_rejected():
    with pytest.raises(ValueError):
        _stock().carve((0, 0, 0), (0, 0, 0), ToolProfile.cylinder(1, 1))


def test_surface_of_a_box_is_closed_and_outward():
    stock = VoxelStock((0, 0, 0), (4, 3, 2), 1.0)
    tris = stock.triangles()
    area = 0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1).sum()
    assert area == pytest.approx(2 * (12 + 8 + 6))
    # divergence theorem: volume = 1/3 * sum(centroid . normal * area) is positive for outward normals
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    volume = np.einsum("ij,ij->i", tris[:, 0], cross).sum() / 6
    assert volume == pytest.approx(24)


def test_surface_follows_the_cut():
    stock = _stock(1.0)
    before = len(stock.triangles())
    stock.carve((10, 10, 5), (0, 0, 1), ToolProfile.cylinder(3, 10))
    assert len(stock.triangles()) > before
