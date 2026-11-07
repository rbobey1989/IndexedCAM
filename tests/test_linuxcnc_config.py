"""Static checks of the LinuxCNC simulation config (no LinuxCNC needed).

Verifies that ``configs/linuxcnc`` is self-consistent: joint/axis mapping of
``5axiskins``, the pivot and tool-length wiring, and that every tilted work
plane of the demo program matches the ``LocalFrame`` that IndexedCAM computes
for those B/C angles.
"""

import configparser
import math
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Machine.bc_head import bc_to_normal, normal_to_bc  # noqa: E402

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


def program_text(name="validate_bc.ngc"):
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
    """LinuxCNC aborts the program with "Nested comment found"."""
    for name in PROGRAMS + ("validate_tools.ngc",):
        for line in program_text(name).splitlines():
            assert line.count("(") == line.count(")"), line
            start = line.find("(")
            if start < 0:
                continue
            inner = line[start + 1 : line.rfind(")")]
            assert "(" not in inner and ")" not in inner, line


def plane_frames():
    """(b, c, origin, x_axis, normal) of every G68.2 P3 plane of the program."""
    frames = []
    angles = {"B": 0.0, "C": 0.0}
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

# --- cinematica de 5axiskins, para saber donde acaba cada movimiento ---------


def joint_position(tip, b, c, pivot=PIVOT):
    """Carro (joint 0/1/2) que 5axiskins necesita para poner la punta en ``tip``.

    Del fuente del modulo: ``pos = joints + r`` con
    ``r = s2r(pivot, c, 180 - b) = (pivot*sin b*cos c, pivot*sin b*sin c, -pivot*cos b)``,
    de donde ``joint = pos - r``: en horizontal el carro se retrasa ``pivot`` por
    cada eje del plano y en Z baja ``pivot*(1 - cos b)`` (con B=0 no se mueve).
    """
    nx, ny, nz = bc_to_normal(b, c)
    return (tip[0] - pivot * nx, tip[1] - pivot * ny, tip[2] - pivot * (1.0 - nz))


def frame_of(origin, x_axis, normal):
    """Marco del plano: X dado y Z = normal; Y se cierra con el producto vectorial."""
    x = unit(x_axis)
    z = unit(normal)
    y = (z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0])
    return origin, x, y, z


def unit(vector):
    length = sum(v * v for v in vector) ** 0.5
    return tuple(v / length for v in vector)


def to_part(plane, position):
    origin, x_axis, y_axis, z_axis = plane
    return tuple(
        origin[i] + position["X"] * x_axis[i] + position["Y"] * y_axis[i] + position["Z"] * z_axis[i]
        for i in range(3)
    )


def poses_of_program(path, pivot=PIVOT):
    """(linea, joints, b, c) de cada movimiento del programa, in machine terms."""
    identity = frame_of((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    plane = identity
    position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    b = c = 0.0
    pending = None
    poses = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line_codes = codes(line)
            block = words(line)
            for axis in ("X", "Y", "Z"):
                if axis in block:
                    position[axis] = block[axis]
            if "B" in block:
                b = block["B"]
            if "C" in block:
                c = block["C"]
            if "G69" in line_codes:
                plane = identity
            if "G68.2" in line_codes and block.get("Q") == 1:
                pending = block
            elif "G68.2" in line_codes and block.get("Q") == 2:
                plane = frame_of(
                    (pending["X"], pending["Y"], pending["Z"]),
                    (pending["I"], pending["J"], pending["K"]),
                    (block["I"], block["J"], block["K"]),
                )
                pending = None
            elif {"G0", "G1", "G2", "G3"} & set(line_codes):
                poses.append((number, joint_position(to_part(plane, position), b, c, pivot), b, c))
    return poses


def limit(parser, section, name, default):
    return float(parser[section].get(name, default))


PROGRAMS = ("validate_bc.ngc", "validate_tools.ngc", "posted_example.ngc")


@pytest.mark.parametrize("name", PROGRAMS)
def test_every_move_fits_the_machine_travel(name):
    parser = ini()
    worst = []
    for number, joints, b, c in poses_of_program(os.path.join(CONFIG, name)):
        for index, value in enumerate(joints):
            section = "JOINT_%d" % index
            low = limit(parser, section, "MIN_LIMIT", -1000.0)
            high = limit(parser, section, "MAX_LIMIT", 1000.0)
            worst.append((value - high, value - low, name, number, index, value, low, high))
        for index, value in ((3, b), (4, c)):
            section = "JOINT_%d" % index
            low = limit(parser, section, "MIN_LIMIT", -360.0)
            high = limit(parser, section, "MAX_LIMIT", 360.0)
            worst.append((value - high, value - low, name, number, index, value, low, high))
    above = [item for item in worst if item[0] > 1e-6]
    below = [item for item in worst if item[1] < -1e-6]
    message = "linea {} joint {} = {:.3f} fuera de [{}, {}]"
    assert not above, message.format(above[0][3], above[0][4], above[0][5], above[0][6], above[0][7])
    assert not below, message.format(below[0][3], below[0][4], below[0][5], below[0][6], below[0][7])


def test_z_travel_has_room_on_both_sides_of_the_pivot():
    """Con B=90 el carro baja ``pivot`` mm; con B=0 sube hasta la punta."""
    parser = ini()
    assert limit(parser, "JOINT_2", "MIN_LIMIT", -1000.0) <= -PIVOT
    highest = max(
        pose[1][2]
        for name in PROGRAMS
        for pose in poses_of_program(os.path.join(CONFIG, name))
    )
    assert highest > 0.0, "las retiradas deben subir por encima del cero de la pieza"
    assert highest <= limit(parser, "JOINT_2", "MAX_LIMIT", 1000.0)


def test_joint_position_matches_the_measured_machine():
    """Valores medidos en LinuxCNC 2.10 con esta config (pivote 250, herramienta 0)."""
    assert joint_position((60.0, 20.0, 15.0), 90.0, 0.0) == pytest.approx((-190.0, 20.0, -235.0))
    assert joint_position((30.0, 40.0, 15.0), 90.0, 90.0) == pytest.approx((30.0, -210.0, -235.0))
    assert joint_position((60.0, 40.0, 30.0), 45.0, 45.0) == pytest.approx((-65.0, -85.0, -43.223), abs=1e-3)
    assert joint_position((30.0, 20.0, 130.0), 0.0, 0.0) == pytest.approx((30.0, 20.0, 130.0))


# --- orden de las rotativas en el visor 3D de Axis --------------------------


def preview_axis(geometry, b, c):
    """Eje de la herramienta que dibuja el visor 3D de Axis.

    Replica ``ToolPart._apply_rotary`` de ``rs274/glcanon_scene.py``: recorre
    ``[DISPLAY]GEOMETRY`` y llama a ``glRotate`` en ese orden, que se
    post-multiplica (``M = R1·R2``), asi que sobre los vertices actua primero
    la ultima letra.
    """
    axis = [0.0, 0.0, 1.0]

    def about(vector, angle, axis_index):
        rad = math.radians(angle)
        cos, sin = math.cos(rad), math.sin(rad)
        x, y, z = vector
        if axis_index == 0:
            return [x, cos * y - sin * z, sin * y + cos * z]
        if axis_index == 1:
            return [cos * x + sin * z, y, -sin * x + cos * z]
        return [cos * x - sin * y, sin * x + cos * y, z]

    for letter in reversed(geometry):
        if letter == "B":
            axis = about(axis, b, 1)
        elif letter == "C":
            axis = about(axis, c, 2)
    return tuple(axis)


@pytest.mark.parametrize(
    "b, c, normal",
    (
        (0.0, 0.0, (0.0, 0.0, 1.0)),
        (90.0, 0.0, (1.0, 0.0, 0.0)),
        (90.0, 90.0, (0.0, 1.0, 0.0)),
        (90.0, -90.0, (0.0, -1.0, 0.0)),
    ),
)
def test_the_preview_geometry_order_draws_the_tool_normal(b, c, normal):
    """Con la cadena de GEOMETRY del INI, el visor 3D apunta a la normal."""
    geometry = ini()["DISPLAY"]["GEOMETRY"]
    rotaries = "".join(ch for ch in geometry if ch in "ABC")
    assert rotaries == "CB", (
        "GEOMETRY debe listar C antes que B para reproducir Rz(C)@Ry(B): "
        + geometry
    )
    for actual, expected in zip(preview_axis(rotaries, b, c), normal):
        assert actual == pytest.approx(expected, abs=1e-9)


def test_the_wrong_order_is_what_loses_the_c_rotation():
    """Con 'BC' la C no cambia la orientacion: era el sintoma reportado."""
    assert preview_axis("BC", 90.0, 90.0) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)
    assert preview_axis("BC", 90.0, -90.0) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)
    assert preview_axis("CB", 90.0, 90.0) == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)
    assert preview_axis("CB", 90.0, -90.0) == pytest.approx((0.0, -1.0, 0.0), abs=1e-9)
