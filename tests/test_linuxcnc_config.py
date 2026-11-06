"""Static checks of the LinuxCNC simulation config (no LinuxCNC needed).

Verifies that ``configs/linuxcnc`` is self-consistent: joint/axis mapping of
``5axiskins``, the pivot and tool-length wiring, and that every tilted work
plane of the demo program matches the ``LocalFrame`` that IndexedCAM computes
for those B/C angles.
"""

import configparser
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Machine.bc_head import normal_to_bc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "configs", "linuxcnc")
INI = os.path.join(CONFIG, "indexedcam.ini")
PROGRAM = os.path.join(CONFIG, "validate_bc.ngc")
COORDINATES = "XYZBCW"
PIVOT = 250.0


def ini():
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), strict=False)
    parser.read(INI)
    return parser


def config_text(name):
    with open(os.path.join(CONFIG, name), encoding="utf-8") as handle:
        return handle.read()


def program_lines():
    with open(PROGRAM, encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in handle]


def without_comments(line):
    return re.sub(r"\([^)]*\)", " ", line)


def words(line):
    """Axis/parameter words of a block, as a dict of floats."""
    result = {}
    for item in without_comments(line).split():
        if item[0].isalpha() and item[0] not in "GMNOST" and item[1:]:
            result[item[0]] = float(item[1:])
    return result


def codes(line):
    return [item for item in without_comments(line).split() if item[0].isalpha()]


# --- INI ------------------------------------------------------------------


def test_kinematics_is_the_bc_head_module():
    parser = ini()
    assert parser["KINS"]["JOINTS"] == "6"
    kinematics = parser["KINS"]["KINEMATICS"]
    assert kinematics.split()[0] == "5axiskins"
    assert "coordinates=xyzbcw" in kinematics


def test_coordinates_and_joints_agree():
    parser = ini()
    assert parser["TRAJ"]["COORDINATES"] == COORDINATES
    joints = int(parser["KINS"]["JOINTS"])
    assert len(COORDINATES) == joints
    for letter in COORDINATES:
        assert ("AXIS_" + letter) in parser
    for number in range(joints):
        assert ("JOINT_%d" % number) in parser


def test_b_and_c_are_rotary_joints_3_and_4():
    parser = ini()
    assert COORDINATES.index("B") == 3 and COORDINATES.index("C") == 4
    for number in (3, 4):
        assert parser["JOINT_%d" % number]["TYPE"] == "ANGULAR"
    for number in (0, 1, 2):
        assert parser["JOINT_%d" % number]["TYPE"] == "LINEAR"


def test_angles_are_programmed_in_degrees():
    assert ini()["TRAJ"]["ANGULAR_UNITS"] == "degree"


def test_motion_module_is_named_so_the_launcher_can_find_it():
    # sin esto el arranque falla con "can't read ::EMCMOT(EMCMOT)"
    assert ini()["EMCMOT"]["EMCMOT"].split()[0] == "motmod"


def test_the_w_axis_has_travel_for_the_pivot():
    parser = ini()
    for section in ("AXIS_Z", "JOINT_2"):
        assert float(parser[section]["MIN_LIMIT"]) <= -PIVOT


def test_tool_table_lists_the_tools_of_the_demo():
    parser = ini()
    table = os.path.join(CONFIG, parser["EMCIO"]["TOOL_TABLE"])
    assert os.path.exists(table)
    with open(table, encoding="utf-8") as handle:
        tools = {
            int(match.group(1))
            for match in (re.match(r"T(\d+)", line) for line in handle if line.strip())
            if match
        }
    used = {
        int(match.group(1))
        for line in program_lines()
        for match in [re.search(r"\bT(\d+)\b", without_comments(line))]
        if match
    }
    assert used and used <= tools, "herramientas del programa: %s" % sorted(used)


# --- HAL ------------------------------------------------------------------


def hal_lines(name):
    return [line.strip() for line in config_text(name).splitlines() if line.strip() and not line.strip().startswith("#")]


def test_hal_sets_the_pivot_and_feeds_the_tool_length():
    lines = hal_lines("indexedcam.hal")
    assert "setp 5axiskins.pivot-length %g" % PIVOT in lines
    tool = [line for line in lines if "5axiskins.tool-length" in line]
    assert tool and "motion.tooloffset.z" in tool[0]


def test_tool_length_is_one_signal_across_hal_files():
    # dos "net" distintos sobre motion.tooloffset.z abortan el arranque
    lines = hal_lines("indexedcam.hal") + hal_lines("indexedcam_vismach.hal")
    sources = [line for line in lines if line.startswith("net") and "motion.tooloffset.z" in line]
    assert len(sources) == 1, sources
    signal = sources[0].split()[1]
    for line in lines:
        if "5axiskins.tool-length" in line or "5axisgui.tool_length" in line:
            assert line.split()[1] == signal


def test_vismach_pivot_matches_the_kinematics():
    text = config_text("indexedcam_vismach.hal")
    assert "pivot_len=%g" % PIVOT in text


def test_every_joint_referenced_by_hal_exists():
    joints = int(ini()["KINS"]["JOINTS"])
    for name in ("indexedcam.hal", "indexedcam_vismach.hal"):
        for line in hal_lines(name):
            for number in re.findall(r"joint\.(\d+)", line):
                assert int(number) < joints


# --- programa de validacion ----------------------------------------------


def test_comments_have_no_nested_parentheses():
    for line in program_lines():
        assert line.count("(") == line.count(")"), line
        comment = line[line.index("(") :] if "(" in line else ""
        assert "(" not in comment[1:-1] if comment else True, line


def plane_frames():
    """(b, c, origin, x_axis, normal) of every G68.2 P3 plane of the program."""
    frames = []
    angles = {}
    pending = None
    for line in program_lines():
        codes_here = codes(line)
        if "G68.2" in codes_here and words(line).get("Q") == 1:
            pending = words(line)
        elif "G68.2" in codes_here and words(line).get("Q") == 2:
            normal = words(line)
            frames.append(
                (angles["B"], angles["C"], pending, (pending["I"], pending["J"], pending["K"]),
                 (normal["I"], normal["J"], normal["K"]))
            )
            pending = None
        elif "G0" in codes_here and "B" in words(line):
            angles = {"B": words(line)["B"], "C": words(line)["C"]}
    return frames


def test_the_program_defines_four_planes():
    assert len(plane_frames()) == 4


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_every_plane_is_the_frame_of_its_bc_angles(index):
    b, c, origin_words, x_axis, normal = plane_frames()[index]
    setup = IndexedSetup(
        name="probe",
        normal=normal,
        b=b,
        c=c,
        origin=(origin_words["X"], origin_words["Y"], origin_words["Z"]),
    )
    frame = setup.local_frame()
    assert b == pytest.approx(setup.b) and c == pytest.approx(setup.c)
    for actual, expected in zip(x_axis, frame.x_axis):
        assert actual == pytest.approx(expected, abs=1e-3)
    for actual, expected in zip(normal, frame.z_axis):
        assert actual == pytest.approx(expected, abs=1e-3)


def test_the_normals_are_the_bc_angles_of_the_solver():
    for b, c, _, _, normal in plane_frames():
        assert normal_to_bc(normal).b == pytest.approx(b, abs=1e-3)
        assert normal_to_bc(normal).c == pytest.approx(c, abs=1e-3)


def test_head_is_indexed_only_with_no_plane_active():
    """Cada indexado va precedido de un G69: girar con un plano activo es un error."""
    active = False
    for line in program_lines():
        line_codes = codes(line)
        if "G69" in line_codes:
            active = False
        elif "G68.2" in line_codes:
            active = True
        elif "G0" in line_codes and "B" in words(line):
            assert not active, "indexado con plano activo: " + line


@pytest.mark.skipif(shutil.which("rs274") is None, reason="rs274 no disponible")
def test_the_interpreter_accepts_the_program(tmp_path):
    output = tmp_path / "canon.txt"
    result = subprocess.run(
        ["rs274", "-g", "-i", INI, "-t", os.path.join(CONFIG, ini()["EMCIO"]["TOOL_TABLE"]), PROGRAM, str(output)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    text = result.stdout + result.stderr
    assert "error" not in text.lower(), text
    assert "nested" not in text.lower(), text
    canon = output.read_text()
    assert canon.count("SET_G68_FRAME") >= 9, "un plano por orientacion y su cancelacion"
    assert "SET_G68_FRAME(60.0000, 20.0000, 15.0000" in canon
