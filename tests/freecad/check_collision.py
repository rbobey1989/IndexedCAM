"""FreeCAD check for #17: Part-based collision checker and planner integration.

Run: INDEXEDCAM_ROOT=<repo> INDEXEDCAM_LOG=<log> FreeCAD.AppImage tests/freecad/check_collision.py
The last line of the log is PASS on success.
"""

import os
import sys
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui
import Part

ROOT = os.environ.get("INDEXEDCAM_ROOT", os.getcwd())
LOG = os.environ.get("INDEXEDCAM_LOG", os.path.join(tempfile.gettempdir(), "check_collision.log"))
sys.path.insert(0, ROOT)
out = open(LOG, "w")


def log(*args):
    out.write(" ".join(str(a) for a in args) + "\n")
    out.flush()


def check(condition, message):
    log(("ok   " if condition else "FAIL ") + message)
    if not condition:
        raise AssertionError(message)


try:
    from IndexedCAM.Core.collision_checker import Obstacle, PartCollisionChecker
    from IndexedCAM.Core.program import Pose
    from IndexedCAM.Core.transition_planner import (
        SafetySphere,
        TransitionError,
        TransitionPlanner,
    )
    from IndexedCAM.Machine.bc_machine import BCMachine
    from IndexedCAM.Machine.envelope import Envelope

    box = Part.makeBox(60, 40, 30)
    envelope = Envelope()
    part = Obstacle("pieza", box, cuttable=True)
    checker = PartCollisionChecker(envelope, [part], margin=2.0)

    check(checker.collision((30, 20, 100), 0, 0) is None, "tool far above the part is free")
    hit = checker.collision((30, 20, 20), 0, 0)
    check(hit is not None and "tool contra pieza" in hit, "tool inside the part collides: %s" % hit)
    check(checker.cutting_collision((30, 20, 28), 0, 0) is None, "cutting tool may touch the part")
    hit = checker.cutting_collision((30, -10, 15), 90, 90)
    check(hit is not None and "holder" in hit,
          "holder still collides while cutting: %s" % hit)
    check(checker.collision((30, 20, 31), 0, 0) is not None, "margin: 1 mm above the face collides")
    check(checker.collision((30, 20, 33), 0, 0) is None, "3 mm above the face is free")
    # head tilted horizontally over the top face: head cylinder hits the part
    check(checker.collision((30, 20, 32), 90, 0) is not None,
          "horizontal tool grazing the top: holder/head collide")

    sphere = SafetySphere.around((30, 20, 15), 40.0, envelope)
    planner = TransitionPlanner(BCMachine(), checker, sphere)
    top = Pose(0.0, 0.0, (30, 20, 60))
    side = Pose(90.0, 0.0, (100, 20, 15))
    transition = planner.plan(top, side)
    check(len(transition.samples) > 30, "real transition validated: %d samples" % len(transition.samples))

    wall = Obstacle("utillaje", Part.makeBox(10, 300, 300, App.Vector(80, -150, -150)))
    blocked = PartCollisionChecker(envelope, [part, wall], margin=2.0)
    blocking = TransitionPlanner(BCMachine(), blocked, sphere)
    try:
        blocking.plan(top, side)
        check(False, "fixture in the way must be detected")
    except TransitionError as error:
        check("utillaje" in str(error), "blocked transition reports the fixture: %s" % error)
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
Gui.getMainWindow().close()
