import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.post_program import (  # noqa: E402
    PostMove,
    PostOperation,
    PostOrientation,
    PostProgram,
    PostTool,
)
from IndexedCAM.Post.linuxcnc import AxisSigns, LinuxCNCConfig, LinuxCNCPost  # noqa: E402

T1 = PostTool(1, "Endmill", 12.0)
T2 = PostTool(2, "Ball", 6.0)

FACE = (
    PostMove("G0", (("X", 0.0), ("Y", 0.0), ("Z", 40.0))),
    PostMove("G1", (("Z", 0.0), ("F", 300.0))),
)
CONTOUR = (
    PostMove("G0", (("X", 0.0), ("Y", 0.0), ("Z", 20.0))),
    PostMove("G2", (("X", 10.0), ("Y", 0.0), ("I", 5.0), ("J", 0.0), ("F", 250.0))),
)

GOLDEN = """%
(IndexedCAM - Test000)
(Herramientas: T1 Endmill D12)
(Planos inclinados G68.2; pivot compensado por 5axiskins B gain 1.0 zero 0.0 / C gain 1.0 zero 0.0)
G21 G90 G17 G94 G40 G80
G69 (cancela cualquier plano previo)
G49
M6 T1 (cambio de herramienta T1 Endmill D12)
G43.4 H1 (longitud de herramienta)
G54 (sistema de coordenadas)
G0 B0.000 C0.000 (indexado)
G68.2 P3 Q1 X0.000 Y0.000 Z30.000 I1.000 J0.000 K0.000 (plano: origen y +X)
G68.2 P3 Q2 I0.000 J0.000 K1.000 (plano: normal +Z)
G0 Z40.000 (aproximacion en el plano)
(Operacion Face1 - T1 Endmill D12)
S10000 M3 (husillo horario)
M8 (refrigerante ON)
G0 X0.000 Y0.000 Z40.000
G1 Z0.000 F300.0
G0 Z100.000 (retirada libre para indexar)
G69 (anula el plano inclinado)
M5 (para el husillo)
M9 (refrigerante OFF)
G54 (sistema de coordenadas)
G0 B90.000 C0.000 (indexado)
G68.2 P3 Q1 X60.000 Y0.000 Z0.000 I0.000 J0.000 K-1.000 (plano: origen y +X)
G68.2 P3 Q2 I1.000 J0.000 K0.000 (plano: normal +Z)
G0 Z20.000 (aproximacion en el plano)
(Operacion Contour - T1 Endmill D12)
S10000 M3 (husillo horario)
G0 X0.000 Y0.000 Z20.000
G2 X10.000 Y0.000 I5.000 J0.000 F250.0
G0 Z100.000 (retirada libre para indexar)
M5 (para el husillo)
G69
G49
M30 (fin de programa)
%
"""


def operation(name, moves, tool=T1, spindle=10000, coolant=""):
    return PostOperation(name, name, tool, moves, spindle=spindle, coolant=coolant)


def top(setup_wcs="G54", operations=None):
    return PostOrientation(
        "Top", 0.0, 0.0, setup_wcs, (0, 0, 30), (1, 0, 0), (0, 1, 0), (0, 0, 1), 100.0, 40.0,
        (operations or (operation("Face1", FACE, coolant="flood"),)),
    )


def side(operations=None):
    return PostOrientation(
        "Side", 90.0, 0.0, "G54", (60, 0, 0), (0, 0, -1), (0, 1, 0), (1, 0, 0), 100.0, 20.0,
        (operations or (operation("Contour", CONTOUR),)),
    )


def render(*orientations, name="Test000", **config):
    return LinuxCNCPost().render(
        PostProgram(name, tuple(orientations)), LinuxCNCConfig(**config)
    )


def test_golden_program():
    assert render(top(), side()) == GOLDEN


def test_every_block_of_the_local_path_is_emitted_unchanged():
    text = render(top(), side())
    assert "G0 X0.000 Y0.000 Z40.000" in text
    assert "G2 X10.000 Y0.000 I5.000 J0.000 F250.0" in text


def test_arcs_stay_in_the_plane_because_every_face_has_its_own_plane():
    text = render(top(), side())
    assert text.count("G68.2 P3 Q1") == 2 and text.count("G68.2 P3 Q2") == 2


def test_retract_happens_before_cancelling_the_plane():
    lines = render(top(), side()).splitlines()
    retract = next(i for i, line in enumerate(lines) if line.startswith("G0 Z100.000"))
    cancel = next(i for i, line in enumerate(lines) if "anula el plano" in line)
    assert retract < cancel


def test_indexing_happens_after_the_plane_is_cancelled():
    lines = render(top(), side()).splitlines()
    cancel = next(i for i, line in enumerate(lines) if "anula el plano" in line)
    index = next(i for i, line in enumerate(lines) if "G0 B90.000 C0.000" in line)
    plane = next(i for i, line in enumerate(lines) if "Z0.000 I0.000 J0.000 K-1.000" in line)
    assert cancel < index < plane


def test_a_second_tool_in_the_same_orientation_redefines_the_plane():
    operations = (
        operation("Rough", FACE, tool=T1),
        operation("Finish", CONTOUR, tool=T2),
    )
    lines = render(top(operations=operations)).splitlines()
    tool_change = next(i for i, line in enumerate(lines) if line.startswith("M6 T2"))
    plane = max(i for i, line in enumerate(lines) if line.startswith("G68.2 P3 Q2"))
    assert tool_change < plane, "the plane must be re-established after a tool change"
    assert sum(1 for line in lines if line.startswith("G68.2 P3 Q1")) == 2
    assert any(line.startswith("G43.4 H2") for line in lines)


def test_same_tool_in_the_same_orientation_does_not_reindex():
    operations = (
        operation("Rough", FACE, tool=T1),
        operation("Finish", CONTOUR, tool=T1),
    )
    text = render(top(operations=operations))
    assert text.count("M6") == 1
    assert text.count("G68.2 P3 Q1") == 1
    assert text.count("(indexado)") == 1


def test_axis_signs_map_the_part_angles_to_controller_angles():
    signs = AxisSigns(b_sign=-1.0, c_sign=1.0, b_zero=0.0, c_zero=90.0)
    text = render(side(), signs=signs)
    assert "G0 B-90.000 C-90.000" in text


def test_axis_signs_are_reported_in_the_header():
    text = render(top(), signs=AxisSigns(b_sign=-1.0, c_zero=90.0))
    assert "B gain -1.0 zero 0.0" in text and "C gain 1.0 zero 90.0" in text


def test_default_signs_use_the_part_angles():
    assert "G0 B0.000 C0.000" in render(top())


def test_line_numbers_are_optional_and_increase():
    lines = render(top(), line_numbers=True, line_start=100, line_step=10).splitlines()
    numbered = [line for line in lines if line.startswith("N")]
    assert numbered[0].startswith("N100 ")
    assert numbered[1].startswith("N110 ")


def test_tool_length_offset_on_the_kinematics_is_the_default():
    text = render(top())
    assert "G43.4 H1" in text and "G49" in text


def test_plain_g43_when_the_machine_has_no_switchable_kinematics():
    text = render(top(), tool_length="G43")
    assert "G43 H1 (longitud de herramienta)" in text
    assert "G43.4" not in text


def test_tool_length_can_be_left_to_the_operator():
    text = render(top(), tool_length="none")
    assert "G43" not in text and "G49" not in text
    assert "M6 T1" in text


def test_coolant_can_be_disabled():
    text = render(top(), coolant=False)
    assert "M8" not in text


def test_coolant_is_not_repeated_for_consecutive_operations():
    operations = (operation("A", FACE, coolant="flood"), operation("B", CONTOUR, coolant="flood"))
    assert render(top(operations=operations)).count("M8") == 1


def test_vertical_head_before_a_tool_change():
    text = render(top(), vertical_before_tool_change=True)
    lines = text.splitlines()
    vertical = next(i for i, line in enumerate(lines) if "cabezal vertical" in line)
    assert lines[vertical].startswith("G0 B0.000 C0.000")


def test_spindle_is_not_stopped_between_orientations_when_disabled():
    text = render(top(), side(), stop_spindle_between=False)
    assert text.count("M5") == 1, "only the final stop"


def test_program_without_operations_only_has_the_frame():
    text = LinuxCNCPost().render(PostProgram("Vacio", ()))
    lines = text.splitlines()
    assert text.startswith("%\n") and text.rstrip().endswith("%")
    assert not [line for line in lines if line.startswith(("G68.2", "M6", "S10000"))]
    assert "M30" in text


def test_header_lines_become_comments():
    text = render(top(), header=("Job: Test000", "Fecha: 2026-11-06"))
    assert "(Job: Test000)" in text and "(Fecha: 2026-11-06)" in text


def test_comments_never_break_the_program():
    tool = PostTool(1, "Fresa (acabado) Ø12", 12.0)
    text = render(top(operations=(operation("A", FACE, tool=tool),)))
    assert "T1 Fresa [acabado] D12" in text
    for line in text.splitlines():
        assert line.count("(") == line.count(")")


def test_units_switch():
    assert "G20 G90" in render(top(), units="in")


def test_negative_zero_is_printed_as_zero():
    moves = (PostMove("G0", (("X", -0.0001),)),)
    text = render(top(operations=(operation("A", moves),)))
    assert "X0.000" in text and "X-0.000" not in text


def test_feed_decimals_are_configurable():
    text = render(top(), feed_decimals=0)
    assert "F300" in text and "F300.0" not in text


def test_bad_units_are_rejected():
    with pytest.raises(ValueError):
        LinuxCNCConfig(units="furlongs")


def test_bad_tool_length_mode_is_rejected():
    with pytest.raises(ValueError):
        LinuxCNCConfig(tool_length="G44")


def test_an_operation_without_feed_gets_one_before_cutting():
    """CAM writes ToolController.VertFeed into F, and a fresh controller is 0."""
    moves = (PostMove("G0", (("Z", 40.0),)), PostMove("G1", (("Z", 0.0),)),
             PostMove("G1", (("X", 10.0),)))
    text = render(top(operations=(operation("A", moves),)))
    assert "F300.0 (avance: CAM no lo trae en esta operacion)" in text
    assert "G1 Z0.000" in text


def test_the_tool_controller_feed_wins_over_the_default():
    op = PostOperation("A", "A", T1, (PostMove("G1", (("Z", 0.0),)),), feed=1200.0)
    text = render(top(operations=(op,)))
    assert "F1200.0" in text and "F300.0" not in text


def test_the_feed_of_the_moves_wins_over_everything():
    op = PostOperation("A", "A", T1, CONTOUR, feed=1200.0)
    text = render(top(operations=(op,)))
    assert "F300.0 (avance: CAM no lo trae" not in text
    assert "F250.0" in text


def test_a_cutting_move_after_a_g0_without_feed_gets_the_default():
    # CAM emits "G0 F0" followed by G1 moves: dropping the zero feed must not
    # leave the modal feed at zero.
    op = PostOperation(
        "A", "A", T1, (PostMove("G0", (("Z", 40.0),)), PostMove("G1", (("Z", 0.0),)))
    )
    text = render(top(operations=(op,)))
    assert text.count("F300.0") == 1
    assert "G1 Z0.000" in text
    for line in text.splitlines():
        if line.startswith("G1"):
            assert "F0" not in line


def test_zero_feed_rejected():
    op = PostOperation("A", "A", T1, (), feed=0.0)
    text = render(top(operations=(op,)), default_feed=500.0)
    assert "F500.0" in text, "un feed 0 en la operacion no puede llegar al G-code"


def test_default_feed_must_be_positive():
    with pytest.raises(ValueError):
        LinuxCNCConfig(default_feed=0.0)
