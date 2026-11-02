import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.path_endpoints import path_endpoints  # noqa: E402
from IndexedCAM.Core.program import (  # noqa: E402
    MemoryProgramStorage,
    Program,
    Step,
    chain,
    describe,
)


def cmd(name, **params):
    return SimpleNamespace(Name=name, Parameters=params)


def program(*pairs):
    p = Program(MemoryProgramStorage())
    for setup, op in pairs:
        p.add(Step(setup, op))
    return p


def test_add_remove_move_and_persistence():
    storage = MemoryProgramStorage()
    p = Program(storage)
    for i in "abc":
        p.add(Step("S", i))
    p.move("c", 0)
    p.remove("b")
    assert [s.operation for s in Program(storage).steps()] == ["c", "a"]
    p.move("c", 99)
    assert [s.operation for s in p.steps()] == ["a", "c"]


def test_duplicate_and_unknown_operation():
    p = program(("S", "a"))
    with pytest.raises(ValueError, match="already"):
        p.add(Step("S", "a"))
    with pytest.raises(KeyError):
        p.remove("zz")


def test_rename_setup():
    p = program(("A", "x"), ("B", "y"), ("A", "z"))
    p.rename_setup("A", "C")
    assert [s.setup for s in p.steps()] == ["C", "B", "C"]


def test_sync_keeps_order_drops_missing_appends_new():
    p = program(("A", "x"), ("B", "y"), ("A", "z"))
    p.move("z", 0)
    changed = p.sync([Step("A", "x"), Step("B", "y"), Step("B", "n")])
    assert changed
    assert [s.operation for s in p.steps()] == ["x", "y", "n"]
    assert not p.sync(p.steps())


def test_sync_refreshes_setup_of_kept_step():
    p = program(("A", "x"))
    p.sync([Step("B", "x")])
    assert p.steps() == [Step("B", "x")]


def test_path_endpoints_modal_and_ignores_non_motion():
    commands = [
        cmd("(comment)"),
        cmd("G0", Z=10.0),
        cmd("G0", X=1.0, Y=2.0),
        cmd("G1", Z=-1.0),
        cmd("M6"),
    ]
    assert path_endpoints(commands) == ((0.0, 0.0, 10.0), (1.0, 2.0, -1.0))
    assert path_endpoints([cmd("M6")]) is None


def test_chain_points_in_part_coordinates_and_transitions():
    top = IndexedSetup(name="Top", normal=(0, 0, 1), b=0, c=0, origin=(10, 20, 30))
    side = IndexedSetup(name="Side", normal=(1, 0, 0), b=90, c=0, origin=(60, 0, 0))
    p = program(("Top", "a"), ("Top", "b"), ("Side", "c"), ("Side", "empty"))
    ends = {
        "a": ((0, 0, 5), (1, 1, 0)),
        "b": ((1, 1, 5), (2, 2, 0)),
        "c": ((0, 0, 5), (0, 3, 0)),
        "empty": None,
    }
    items = chain(p, {"Top": top, "Side": side}, ends)
    assert items[0].previous is None and not items[0].needs_transition
    assert items[0].end.point == pytest.approx((11, 21, 30))
    assert items[1].previous is items[0].end and not items[1].needs_transition
    assert items[2].needs_transition and items[2].previous.b == 0
    # Side: local Z is the part X axis, so local (0,0,5) is part (65, 0, 0)
    assert items[2].start.point == pytest.approx((65, 0, 0))
    assert items[2].start.b == 90
    assert items[3].start is None and items[3].previous is items[2].end


def test_describe():
    top = IndexedSetup(name="Top", normal=(0, 0, 1), b=0, c=0)
    side = IndexedSetup(name="Side", normal=(1, 0, 0), b=90, c=0)
    p = program(("Top", "a"), ("Side", "c"), ("Side", "e"))
    ends = {"a": ((0, 0, 1), (0, 0, 0)), "c": ((0, 0, 1), (0, 0, 0)), "e": None}
    lines = [describe(i, n) for n, i in enumerate(chain(p, {"Top": top, "Side": side}, ends), 1)]
    assert "posición segura" in lines[0]
    assert "transición B0.0/C0.0 → B90.0/C0.0" in lines[1]
    assert "sin movimientos" in lines[2]


def test_path_points_subdivides_and_ignores_non_motion():
    from IndexedCAM.Core.path_endpoints import path_points

    commands = [cmd("G0", X=0.0, Y=0.0, Z=10.0), cmd("M6"), cmd("G1", Z=0.0)]
    points = path_points(commands, step=5.0)
    assert points == [(0.0, 0.0, 10.0), (0.0, 0.0, 5.0), (0.0, 0.0, 0.0)]
    assert path_points([cmd("M6")]) == []
    with pytest.raises(ValueError):
        path_points(commands, 0)


def test_check_operation_reports_first_hit_in_part_coordinates():
    from IndexedCAM.Core.collision_checker import check_operation

    frame = IndexedSetup(name="T", normal=(0, 0, 1), b=0, c=0, origin=(10, 0, 0)).local_frame()
    commands = [cmd("G0", X=0.0, Y=0.0, Z=10.0), cmd("G1", Z=0.0)]
    seen = []

    def check(tip, b, c):
        seen.append(tip)
        return "choque" if tip[2] == 0 else None

    message = check_operation(check, commands, frame, 0.0, 0.0)
    assert message.startswith("en (10.0, 0.0, 0.0)") and "choque" in message
    assert check_operation(lambda *a: None, commands, frame, 0.0, 0.0) is None
