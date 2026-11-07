#!/usr/bin/env python3
"""End-to-end check of the LinuxCNC simulation config (headless).

Starts the config in ``configs/linuxcnc`` on a virtual X display, homes the
machine, sends MDI blocks that tilt the head into each indexed orientation and
compares the resulting joint positions with the pivot kinematics
(``tip = pivot + (pivot-length + tool-length) * tool axis``).

Run it after changing the config or the post processor:

    python3 tests/linuxcnc/check_sim.py                      # solo las poses
    python3 tests/linuxcnc/check_sim.py uno.ngc dos.ngc       # y ejecuta esos programas
    cat /tmp/indexedcam_sim.log

The last line of the log is PASS on success. It needs ``linuxcnc``, ``Xvfb``,
``halcmd`` and ``axis-remote`` (all from a LinuxCNC install) and does not touch
the real machine: it runs the simulator on a virtual display.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(ROOT, "configs", "linuxcnc")
INI = os.path.join(CONFIG, "indexedcam.ini")
LOG_PATH = os.environ.get("INDEXEDCAM_LOG", os.path.join(tempfile.gettempdir(), "indexedcam_sim.log"))
LINUXCNC_LOG = os.path.join(tempfile.gettempdir(), "indexedcam_sim_linuxcnc.log")
TOLERANCE = 0.01
ERROR_WORDS = ("would exceed", "USRMOT: ERROR", "invalid params", "G68", "error:")

out = open(LOG_PATH, "w", buffering=1)
procs: List[subprocess.Popen] = []


def log(*args: object) -> None:
    out.write(" ".join(str(a) for a in args) + "\n")


def check(condition: bool, message: str) -> None:
    log(("ok   " if condition else "FAIL ") + message)
    if not condition:
        raise AssertionError(message)


# --- casos: plano G68.2, angulos B/C y joints esperados ----------------------
# El pivote del config es 250 mm y la tabla de herramientas tiene Z=0, asi que
# con B=90 el carro queda 250 mm por detras de la punta y a la misma altura.
CASES: Sequence[Tuple[str, str, float, float, Tuple[float, ...]]] = (
    (
        "cara superior",
        "G68.2 P3 Q1 X30 Y20 Z30 I1 J0 K0\nG68.2 P3 Q2 I0 J0 K1",
        0.0,
        0.0,
        (30.0, 20.0, 30.0, 0.0, 0.0),
    ),
    (
        "cara +X (B90 C0)",
        "G68.2 P3 Q1 X60 Y20 Z15 I0 J0 K-1\nG68.2 P3 Q2 I1 J0 K0",
        90.0,
        0.0,
        (-190.0, 20.0, -235.0, 90.0, 0.0),
    ),
    (
        "cara +Y (B90 C90)",
        "G68.2 P3 Q1 X30 Y40 Z15 I0 J0 K-1\nG68.2 P3 Q2 I0 J1 K0",
        90.0,
        90.0,
        (30.0, -210.0, -235.0, 90.0, 90.0),
    ),
    (
        "compuesta (B45 C45)",
        "G68.2 P3 Q1 X60 Y40 Z30 I0.5 J0.5 K-0.7071068\nG68.2 P3 Q2 I0.5 J0.5 K0.7071068",
        45.0,
        45.0,
        (-65.0, -85.0, -43.223, 45.0, 45.0),
    ),
)


def realtime_busy() -> bool:
    """True if another LinuxCNC instance holds the real-time session.

    Only one instance can run per machine: ``loadrt`` fails with
    "Realtime already running" while the user's own LinuxCNC is open.
    """
    path = os.path.join(tempfile.gettempdir(), "indexedcam_probe.hal")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("show pin\n")
    try:
        result = subprocess.run(
            ["halrun", "-f", path], capture_output=True, text=True, timeout=60
        )
    finally:
        os.unlink(path)
    return "already running" in (result.stdout + result.stderr).lower()


def env_with(display: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["DISPLAY"] = display
    env["LC_ALL"] = "C"
    return env


def free_display() -> str:
    for number in range(91, 100):
        if not os.path.exists("/tmp/.X11-unix/X{}".format(number)):
            return ":{}".format(number)
    raise RuntimeError("no free X display")


def wait(condition: Callable[[], bool], timeout: float, what: str, step: float = 0.5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if condition():
                return
        except (subprocess.SubprocessError, OSError, ValueError):
            pass
        time.sleep(step)
    raise RuntimeError("timeout esperando " + what)


def run(args: Sequence[str], env: Dict[str, str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), env=env, capture_output=True, text=True, timeout=timeout)


def hal_get(env: Dict[str, str], pin: str) -> float:
    result = run(["halcmd", "getp", pin], env)
    return float(result.stdout.strip().split()[-1].replace(",", "."))


def hal_bit(env: Dict[str, str], pin: str) -> bool:
    result = run(["halcmd", "getp", pin], env)
    return result.stdout.strip().split()[-1] in ("TRUE", "1", "1.0")


def hal_set(env: Dict[str, str], pin: str, value: int) -> None:
    run(["halcmd", "setp", pin, str(value)], env)


def switch_on(
    env: Dict[str, str], pin: str, read: str, what: str, expect: bool = True, attempts: int = 4
) -> None:
    """Toggle an IN bit: halui only reacts to the rising edge."""
    for _ in range(attempts):
        hal_set(env, pin, 0)
        time.sleep(0.5)
        hal_set(env, pin, 1)
        time.sleep(1.5)
        if hal_bit(env, read) is expect:
            return
    raise RuntimeError("no se pudo activar " + what)


def gui_ping(env: Dict[str, str]) -> bool:
    return run(["axis-remote", "--ping"], env).returncode == 0


def mdi(env: Dict[str, str], command: str, attempts: int = 40) -> None:
    """Send an MDI block, retrying while the interpreter is busy."""
    for _ in range(attempts):
        result = run(["axis-remote", "-m", command], env)
        if result.returncode == 0 and not result.stdout.strip() and not result.stderr.strip():
            time.sleep(0.35)
            return
        time.sleep(0.35)
    raise RuntimeError("MDI rechazado: " + command)


def joints(env: Dict[str, str]) -> Tuple[float, ...]:
    return tuple(hal_get(env, "joint.{}.pos-fb".format(n)) for n in range(5))


def ini_with(program: str) -> str:
    """Copy of the INI that opens ``program`` at startup (it lives in the same dir)."""
    if not program:
        return INI
    with open(INI, encoding="utf-8") as handle:
        text = handle.read()
    text = re.sub(r"(?m)^OPEN_FILE\s*=.*$", "OPEN_FILE = " + program, text)
    path = os.path.join(CONFIG, "indexedcam_run.ini")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def start_machine(ini_path: Optional[str] = None) -> Dict[str, str]:
    display = free_display()
    procs.append(
        subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1024x768x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )
    env = env_with(display)
    wait(lambda: os.path.exists("/tmp/.X11-unix/X{}".format(display[1:])), 15, "Xvfb")
    logfile = open(LINUXCNC_LOG, "w")
    procs.append(
        subprocess.Popen(
            ["linuxcnc", "-r", ini_path or INI],
            cwd=CONFIG,
            env=env,
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
    )
    wait(lambda: gui_ping(env), 90, "la GUI de LinuxCNC (mira " + LINUXCNC_LOG + ")")
    check(True, "el config arranca (INI + HAL + 5axiskins)")
    switch_on(env, "halui.estop.reset", "halui.estop.is-activated", "el reset de emergencia", expect=False)
    hal_set(env, "halui.estop.reset", 0)
    switch_on(env, "halui.machine.on", "halui.machine.is-on", "la maquina")
    check(True, "maquina ON tras reset de emergencia")
    hal_set(env, "halui.home-all", 1)
    wait(lambda: all(hal_bit(env, "joint.{}.homed".format(n)) for n in range(6)), 60, "homing")
    check(True, "6 joints referenciados (B = joint 3, C = joint 4)")
    hal_set(env, "halui.mode.mdi", 1)
    return env


def verify(env: Dict[str, str]) -> None:
    for name, planes, b, c, expected in CASES:
        mdi(env, "G69")
        for block in planes.splitlines():
            mdi(env, block)
        mdi(env, "G0 B{} C{}".format(b, c))
        mdi(env, "G0 X0 Y0 Z0")
        wait(
            lambda: all(abs(a - e) <= TOLERANCE for a, e in zip(joints(env), expected)),
            20,
            "la pose de " + name,
        )
        actual = joints(env)
        log("     {}: joints = {}".format(name, ["{:.3f}".format(v) for v in actual]))
        check(
            all(abs(a - e) <= TOLERANCE for a, e in zip(actual, expected)),
            "{}: la punta queda en el origen del plano {}".format(name, ["{:.3f}".format(v) for v in expected]),
        )


def stop_machine(env: Optional[Dict[str, str]]) -> None:
    if env is not None:
        run(["axis-remote", "--quit"], env, timeout=15)
        time.sleep(2.0)
    for process in reversed(procs):
        if process.poll() is None:
            process.terminate()
    for process in reversed(procs):
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def controller_errors() -> List[str]:
    """Error lines the controller wrote while running the program."""
    if not os.path.exists(LINUXCNC_LOG):
        return []
    with open(LINUXCNC_LOG, encoding="utf-8", errors="replace") as handle:
        return [
            line.strip()
            for line in handle
            if any(word.lower() in line.lower() for word in ERROR_WORDS)
        ]


def run_program(env: Dict[str, str], path: str) -> None:
    """Run the program opened at startup (typ. posted by IndexedCAM)."""
    check(os.path.exists(path), "existe el programa " + path)
    hal_set(env, "halui.mode.auto", 1)
    switch_off_on(env, "halui.program.run")
    wait(lambda: hal_bit(env, "halui.program.is-idle"), 300, "el programa", step=1.0)
    errors = controller_errors()
    for line in errors:
        log("     " + line)
    check(not errors, "sin errores del controlador: " + os.path.basename(path))
    check(hal_bit(env, "halui.program.is-idle"), "el programa termina: " + os.path.basename(path))


def switch_off_on(env: Dict[str, str], pin: str) -> None:
    hal_set(env, pin, 0)
    time.sleep(0.3)
    hal_set(env, pin, 1)


def main() -> int:
    for tool in ("linuxcnc", "Xvfb", "halcmd", "axis-remote"):
        if shutil.which(tool) is None:
            log("SKIP falta " + tool)
            return 0
    env: Optional[Dict[str, str]] = None
    programs = [os.path.abspath(item) for item in sys.argv[1:]]
    if realtime_busy():
        log("SKIP hay otra instancia de LinuxCNC usando el realtime.")
        log("     Cierra LinuxCNC (o el simulador) y vuelve a ejecutar este script:")
        log("     python3 tests/linuxcnc/check_sim.py " + " ".join(sys.argv[1:]))
        out.close()
        return 2
    try:
        check(os.path.exists(INI), "existe " + INI)
        env = start_machine(ini_with(programs[0]) if programs else None)
        verify(env)
        for index, program in enumerate(programs):
            if index:
                # un programa por instancia: AXIS no cambia de fichero con el
                # interprete cargado y el estado modal se arrastraria
                stop_machine(env)
                procs.clear()
                env = start_machine(ini_with(program))
            run_program(env, program)
        log("PASS")
        return 0
    except Exception:
        log(traceback.format_exc())
        log("FAIL")
        return 1
    finally:
        stop_machine(env)
        out.close()


if __name__ == "__main__":
    sys.exit(main())
