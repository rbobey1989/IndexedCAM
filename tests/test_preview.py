import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.preview import (  # noqa: E402
    OPERATION,
    TRANSITION,
    PreviewBuilder,
    decimate,
    sphere_for,
)
from IndexedCAM.Core.program import MemoryProgramStorage, Program, Step, chain  # noqa: E402
from IndexedCAM.Core.transition_planner import TransitionPlanner  # noqa: E402
from IndexedCAM.Gui.tool_view import cylinder_orientation  # noqa: E402
from IndexedCAM.Machine.bc_machine import BCMachine  # noqa: E402
from IndexedCAM.Machine.envelope import Envelope  # noqa: E402


class Checker:
    def __init__(self, hit_below_z=None):
        self.hit = hit_below_z
        self.calls = 0

    def _test(self, tip):
        self.calls += 1
        return "choque" if self.hit is not None and tip[2] < self.hit else None

    def collision(self, tip, b, c):
        return self._test(tip)

    cutting_collision = collision


class Resources:
    def __init__(self, checker):
        self._checker = checker

    def envelope(self, operation):
        return Envelope()

    def checker(self, operation):
        return self._checker

    def local_path(self, operation):
        return [(0, 0, 10), (0, 0, 0), (5, 0, 0)]


def setups():
    return {
        "Top": IndexedSetup(name="Top", normal=(0, 0, 1), b=0, c=0, origin=(0, 0, 30)),
        "Side": IndexedSetup(name="Side", normal=(1, 0, 0), b=90, c=0, origin=(60, 0, 0)),
    }


def build(checker=None):
    checker = checker or Checker()
    program = Program(MemoryProgramStorage())
    for step in (Step("Top", "a"), Step("Side", "b")):
        program.add(step)
    s = setups()
    ends = {"a": ((0, 0, 10), (5, 0, 0)), "b": ((0, 0, 10), (5, 0, 0))}
    items = chain(program, s, ends)
    sphere = sphere_for(((0, 0, 0), (60, 40, 30)))
    resources = Resources(checker)
    builder = PreviewBuilder(
        s, resources, lambda op: TransitionPlanner(BCMachine(), checker, sphere)
    )
    return builder.build(items), checker


def test_one_operation_clip_per_step_and_transition_between_setups():
    clips, _ = build()
    assert [c.kind for c in clips] == [OPERATION, TRANSITION, OPERATION]
    assert [c.step_index for c in clips] == [0, 1, 1]
    assert clips[1].error is None and len(clips[1]) > 10


def test_operation_frames_are_in_part_coordinates():
    clips, _ = build()
    top = clips[0].frames
    assert top[0].tip == pytest.approx((0, 0, 40)) and top[0].b == 0
    side = clips[2].frames
    assert side[0].tip == pytest.approx((70, 0, 0)) and side[0].b == 90


def test_collisions_are_lazy_and_cached():
    clips, checker = build(Checker(hit_below_z=-1e9))
    before = checker.calls
    clip = clips[0]
    assert clip.collision(0) is None
    assert clip.collision(0) is None
    assert checker.calls == before + 1


def test_first_collision_and_poses():
    clips, _ = build(Checker(hit_below_z=35))
    clip = clips[0]
    assert clip.first_collision() == 1  # second sample drops to z=30
    assert [p.name for p in clip.poses(0)] == ["tool"], "por defecto solo se modela la herramienta"


def test_failed_transition_is_still_shown_with_error():
    clips, _ = build(Checker(hit_below_z=1e9))
    transition = clips[1]
    assert transition.error and "No hay transición" in transition.error
    assert len(transition) > 10 and transition.collision(0)


def test_decimate_keeps_ends_and_limit():
    points = [(float(i), 0.0, 0.0) for i in range(1000)]
    result = decimate(points, 100)
    assert len(result) == 100 and result[0] == points[0] and result[-1] == points[-1]
    assert decimate(points[:5], 100) == points[:5]


def test_sphere_for_box():
    sphere = sphere_for(((0, 0, 0), (60, 40, 30)), margin=10.0)
    assert sphere.center == (30.0, 20.0, 15.0)
    assert sphere.radius == pytest.approx(math.sqrt(60**2 + 40**2 + 30**2) / 2 + 10)
    assert sphere_for(((0, 0, 0), (60, 40, 30))).radius == pytest.approx(
        math.sqrt(60**2 + 40**2 + 30**2) / 2
    )


def test_cylinder_orientation():
    middle, length, direction = cylinder_orientation((0, 0, 0), (0, 0, 10))
    assert (middle, length, direction) == ((0, 0, 5), 10.0, (0.0, 0.0, 1.0))
    with pytest.raises(ValueError):
        cylinder_orientation((1, 1, 1), (1, 1, 1))


def test_describe_tool_includes_diameter_and_flute():
    from IndexedCAM.Core.preview import describe_tool
    from IndexedCAM.Machine.bc_machine import BCMachine

    envelope = BCMachine().envelope.with_tool(3.0, 40.0, 12.0)
    assert describe_tool(envelope) == "Ø6 mm, largo 40 mm, corte 12 mm"
    assert describe_tool(BCMachine().envelope.with_tool(2.5, 30.0)) == "Ø5 mm, largo 30 mm"


def test_clips_carry_the_tool_mesh_of_their_operation():
    class MeshResources(Resources):
        def tool_mesh(self, operation):
            return ("mesh-" + operation, [])

    checker = Checker()
    program = Program(MemoryProgramStorage())
    for step in (Step("Top", "a"), Step("Side", "b")):
        program.add(step)
    s = setups()
    items = chain(program, s, {"a": ((0, 0, 10), (5, 0, 0)), "b": ((0, 0, 10), (5, 0, 0))})
    sphere = sphere_for(((0, 0, 0), (60, 40, 30)))
    clips = PreviewBuilder(
        s, MeshResources(checker), lambda op: TransitionPlanner(BCMachine(), checker, sphere)
    ).build(items)
    assert [c.tool_mesh[0] for c in clips] == ["mesh-a", "mesh-b", "mesh-b"]


def test_clips_without_tool_mesh_fall_back_to_cylinders():
    clips, _ = build()
    assert all(c.tool_mesh is None for c in clips)


def test_parking_clip_retracts_and_brings_the_head_back_to_vertical():
    """El post siempre termina con retirada y cabezal vertical."""
    from IndexedCAM.Core.preview import PARKING
    from IndexedCAM.Core.transition_planner import RETRACT, TURN

    checker = Checker()
    program = Program(MemoryProgramStorage())
    program.add(Step("Side", "b"))
    s = setups()
    items = chain(program, s, {"b": ((0, 0, 10), (5, 0, 0))})
    resources = Resources(checker)
    sphere = sphere_for(((0, 0, 0), (60, 40, 30)))
    clips = PreviewBuilder(
        s, resources, lambda op: TransitionPlanner(BCMachine(), checker, sphere), sphere
    ).build(items)
    parking = clips[-1]
    assert parking.kind == PARKING
    assert len(parking) > 5
    phases = [f.label for f in parking.frames]
    assert RETRACT in phases and TURN in phases
    last = parking.frames[-1]
    assert (last.b, last.c) == (0.0, 0.0), "termina con el cabezal vertical"
    first = parking.frames[0]
    assert (first.b, first.c) == (90.0, 0.0), "empieza en la orientacion de la cara"
    # la retirada lleva la punta a la altura segura del post: Z local = centro + radio
    from IndexedCAM.Core.post_builder import local_z

    local = s["Side"].local_frame()
    turn_start = phases.index(TURN)
    tip = parking.frames[turn_start].tip
    assert local_z(local, tip) == pytest.approx(
        local_z(local, sphere.center) + sphere.radius, abs=1e-6
    )


def test_no_parking_clip_when_the_program_ends_vertical():
    from IndexedCAM.Core.preview import PARKING

    checker = Checker()
    program = Program(MemoryProgramStorage())
    program.add(Step("Top", "a"))
    s = setups()
    items = chain(program, s, {"a": ((0, 0, 10), (5, 0, 0))})
    sphere = sphere_for(((0, 0, 0), (60, 40, 30)))
    clips = PreviewBuilder(
        s, Resources(checker), lambda op: TransitionPlanner(BCMachine(), checker, sphere), sphere
    ).build(items)
    assert PARKING not in [c.kind for c in clips]


def test_no_parking_clip_without_a_sphere():
    from IndexedCAM.Core.preview import PARKING

    clips, _ = build()
    assert PARKING not in [c.kind for c in clips]


def test_playlist_runs_the_selected_clips_in_order():
    from IndexedCAM.Core.preview import Playlist

    clips, _ = build()
    everything = Playlist.of(clips)
    assert len(everything) == sum(len(c) for c in clips)
    assert everything.clips() == [0, 1, 2]
    assert everything.at(0) == (0, 0)
    assert everything.at(len(clips[0])) == (1, 0)


def test_playlist_skips_the_clips_not_selected():
    from IndexedCAM.Core.preview import Playlist

    clips, _ = build()
    only_operations = Playlist.of(clips, [0, 2])
    assert only_operations.clips() == [0, 2]
    assert len(only_operations) == len(clips[0]) + len(clips[2])
    assert only_operations.first_in(1) is None
    assert only_operations.first_in(2) == len(clips[0])
    assert Playlist.of(clips, []).at(0) is None


def test_playlist_clamps_out_of_range_positions():
    from IndexedCAM.Core.preview import Playlist

    clips, _ = build()
    playlist = Playlist.of(clips)
    assert playlist.at(10_000) == playlist.at(len(playlist) - 1)
    assert playlist.at(-5) == (0, 0)
