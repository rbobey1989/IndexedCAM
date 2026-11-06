"""LinuxCNC post processor for a B+C head machine (pure Python, no FreeCAD).

Strategy: the program runs under a **tilted work plane** (``G68.2``), so the
moves of every operation are emitted verbatim in the local frame of its
orientation and the controller composes the plane on top of ``G54``. The head
is indexed with ``B``/``C`` words and the pivot compensation is done by the
``5axiskins`` kinematics module (``XYZBC``, "kinematics for XYZBC 5 axis bridge
mill"), which places the tool tip exactly where the program says.

Per orientation the post emits: retract along the tool axis, cancel the plane,
stop the spindle, (change tool), index B/C, define the plane from the frame
origin/+X and the normal, and approach in the new plane.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from IndexedCAM.Core.post_program import MM, PostOperation, PostOrientation, PostProgram, PostTool

G43, G434, NO_TOOL_LENGTH = "G43", "G43.4", "none"
FLOOD, MIST = "flood", "mist"

INTEGER_WORDS = "THSPQNO"


@dataclass(frozen=True)
class AxisSigns:
    """How part angles map to controller angles: ``word = sign * (angle - zero)``.

    The tilt sense of ``5axiskins`` is the opposite of the conventional
    right-hand rotation about +Y, and heads differ in zero position, so the
    mapping is data, not code.
    """

    b_sign: float = 1.0
    c_sign: float = 1.0
    b_zero: float = 0.0
    c_zero: float = 0.0

    def b_word(self, b: float) -> float:
        return self.b_sign * (b - self.b_zero)

    def c_word(self, c: float) -> float:
        return self.c_sign * (c - self.c_zero)

    def describe(self) -> str:
        return "B gain {} zero {} / C gain {} zero {}".format(
            self.b_sign, self.b_zero, self.c_sign, self.c_zero
        )


@dataclass(frozen=True)
class LinuxCNCConfig:
    """Everything the controller needs that is not part of the geometry."""

    units: str = MM
    decimals: int = 3
    feed_decimals: int = 1
    line_numbers: bool = False
    line_start: int = 10
    line_step: int = 10
    tool_length: str = G434
    coolant: bool = True
    stop_spindle_between: bool = True
    vertical_before_tool_change: bool = False
    header: Tuple[str, ...] = field(default_factory=tuple)
    signs: AxisSigns = AxisSigns()

    def __post_init__(self) -> None:
        if self.units not in (MM, "in"):
            raise ValueError("units must be 'mm' or 'in'")
        if not 0 <= self.decimals <= 6:
            raise ValueError("decimals must be between 0 and 6")
        if self.tool_length not in (G43, G434, NO_TOOL_LENGTH):
            raise ValueError("tool_length must be 'G43', 'G43.4' or 'none'")
        if self.line_step < 1:
            raise ValueError("line_step must be positive")
        object.__setattr__(self, "header", tuple(self.header))

    @property
    def units_code(self) -> str:
        return "G21" if self.units == MM else "G20"


class _Output:
    """Accumulates G-code lines with the configured formatting."""

    def __init__(self, config: LinuxCNCConfig) -> None:
        self._config = config
        self._lines: List[str] = []
        self._number = config.line_start

    def lines(self) -> List[str]:
        return list(self._lines)

    def comment(self, text: str) -> None:
        self._lines.append("({})".format(_clean(text)))

    def tag(self, text: str, comment: str = "") -> None:
        """A block given as literal text (no words to format)."""
        self._emit(text, comment)

    def block(self, code: str, words: Sequence[Tuple[str, float]] = (), comment: str = "") -> None:
        parts = [code]
        parts += [letter + self._value(letter, value) for letter, value in words]
        self._emit(" ".join(parts), comment)

    def _emit(self, body: str, comment: str) -> None:
        if self._config.line_numbers:
            body = "N{} {}".format(self._number, body)
            self._number += self._config.line_step
        if comment:
            body += " ({})".format(_clean(comment))
        self._lines.append(body)

    def _value(self, letter: str, value: float) -> str:
        if letter == "F":
            return _fixed(value, self._config.feed_decimals)
        if letter in INTEGER_WORDS and float(value).is_integer():
            return str(int(round(value)))
        return _fixed(value, self._config.decimals)


def _fixed(value: float, decimals: int) -> str:
    text = "{:.{}f}".format(float(value), decimals)
    return text[1:] if text.startswith("-") and float(text) == 0.0 else text


_ACCENTS = str.maketrans("áéíóúÁÉÍÓÚñÑ°Øø", "aeiouAEIOUnN Dd")


def _clean(text: str) -> str:
    """One comment line: no parentheses, plain ASCII (LinuxCNC reads bytes)."""
    text = str(text).translate(_ACCENTS).replace("(", "[").replace(")", "]")
    return " ".join(text.encode("ascii", "replace").decode("ascii").split())


class _Emitter:
    """Walks the program keeping the modal state the controller will have."""

    def __init__(self, out: _Output, config: LinuxCNCConfig) -> None:
        self._out = out
        self._config = config
        self._plane: Optional[PostOrientation] = None
        self._tool: Optional[int] = None
        self._spindle = False
        self._coolant = ""

    def program(self, program: PostProgram) -> None:
        self._preamble(program)
        for orientation in program.orientations:
            for operation in orientation.operations:
                self._enter(orientation, operation)
                self._operation(operation)
        self._postamble()

    def _preamble(self, program: PostProgram) -> None:
        self._out.tag("%")
        self._out.comment("IndexedCAM" + (" - " + program.name if program.name else ""))
        for line in self._config.header:
            self._out.comment(line)
        tools = program.tools()
        if tools:
            self._out.comment("Herramientas: " + ", ".join(t.describe() for t in tools))
        self._out.comment("Planos inclinados G68.2; pivot compensado por 5axiskins " + self._config.signs.describe())
        self._out.tag(" ".join([self._config.units_code, "G90", "G17", "G94", "G40", "G80"]))
        self._out.block("G69", comment="cancela cualquier plano previo")

    def _postamble(self) -> None:
        if self._plane is not None:
            self._retract()
        self._stop_spindle(force=True)
        self._stop_coolant()
        self._out.block("G69")
        if self._config.tool_length in (G43, G434):
            self._out.block("G49")
        self._out.tag("M30", "fin de programa")
        self._out.tag("%")

    def _retract(self) -> None:
        assert self._plane is not None
        self._out.block("G0", (("Z", self._plane.safe_z),), "retirada libre para indexar")

    def _enter(self, orientation: PostOrientation, operation: PostOperation) -> None:
        if self._plane is not None:
            self._retract()
        same_plane = self._plane is not None and self._plane.name == orientation.name
        new_tool = self._tool != operation.tool.number
        if not same_plane or new_tool:
            self._cancel_plane()
            self._stop_spindle(force=new_tool)
            self._stop_coolant()
        if new_tool:
            self._tool_change(operation.tool)
        if self._plane is None:
            self._index(orientation)

    def _cancel_plane(self) -> None:
        if self._plane is not None:
            self._out.block("G69", comment="anula el plano inclinado")
            self._plane = None

    def _stop_spindle(self, force: bool = False) -> None:
        if self._spindle and (force or self._config.stop_spindle_between):
            self._out.tag("M5", "para el husillo")
            self._spindle = False

    def _stop_coolant(self) -> None:
        if self._coolant:
            self._out.tag("M9", "refrigerante OFF")
            self._coolant = ""

    def _tool_change(self, tool: PostTool) -> None:
        if self._config.vertical_before_tool_change:
            self._out.block(
                "G0",
                (("B", self._config.signs.b_word(0.0)), ("C", self._config.signs.c_word(0.0))),
                "cabezal vertical para el cambio",
            )
        if self._config.tool_length in (G43, G434):
            self._out.block("G49")
        self._out.block("M6", (("T", tool.number),), "cambio de herramienta " + tool.describe())
        if self._config.tool_length in (G43, G434):
            self._out.block(self._config.tool_length, (("H", tool.number),), "longitud de herramienta")
        self._tool = tool.number

    def _index(self, orientation: PostOrientation) -> None:
        signs = self._config.signs
        self._out.block(orientation.wcs, comment="sistema de coordenadas")
        self._out.block(
            "G0",
            (("B", signs.b_word(orientation.b)), ("C", signs.c_word(orientation.c))),
            "indexado",
        )
        origin, x_axis, normal = orientation.origin, orientation.x_axis, orientation.z_axis
        self._out.block(
            "G68.2",
            (
                ("P", 3),
                ("Q", 1),
                ("X", origin[0]),
                ("Y", origin[1]),
                ("Z", origin[2]),
                ("I", x_axis[0]),
                ("J", x_axis[1]),
                ("K", x_axis[2]),
            ),
            "plano: origen y +X",
        )
        self._out.block(
            "G68.2",
            (("P", 3), ("Q", 2), ("I", normal[0]), ("J", normal[1]), ("K", normal[2])),
            "plano: normal +Z",
        )
        self._out.block("G0", (("Z", orientation.clearance_z),), "aproximación en el plano")
        self._plane = orientation

    def _operation(self, operation: PostOperation) -> None:
        self._out.comment("Operación {} - {}".format(operation.name, operation.tool.describe()))
        if operation.spindle is not None and not self._spindle:
            self._out.tag("S{} M3".format(operation.spindle), "husillo horario")
            self._spindle = True
        if self._config.coolant and operation.coolant and self._coolant != operation.coolant:
            self._out.tag("M8" if operation.coolant == FLOOD else "M7", "refrigerante ON")
            self._coolant = operation.coolant
        for move in operation.moves:
            self._out.block(move.code, move.words, move.comment)


class LinuxCNCPost:
    """Render a ``PostProgram`` as LinuxCNC G-code."""

    name = "LinuxCNC"

    def render(self, program: PostProgram, config: Optional[LinuxCNCConfig] = None) -> str:
        config = config or LinuxCNCConfig()
        out = _Output(config)
        _Emitter(out, config).program(program)
        return "\n".join(out.lines()) + "\n"
