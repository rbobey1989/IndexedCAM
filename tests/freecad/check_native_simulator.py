"""FreeCAD check: the native (legacy) CAM simulator tilts its CutTool for indexed operations.

    INDEXEDCAM_ROOT=<repo> INDEXEDCAM_LOG=<log> FreeCAD.AppImage tests/freecad/check_native_simulator.py
The last line of the log is PASS on success.
"""

import math
import os
import sys
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui

ROOT = os.environ.get("INDEXEDCAM_ROOT", os.getcwd())
LOG = os.environ.get("INDEXEDCAM_LOG", os.path.join(tempfile.gettempdir(), "check_sim.log"))
sys.path.insert(0, ROOT)
out = open(LOG, "w", buffering=1)


def log(*args):
    out.write(" ".join(str(a) for a in args) + "\n")


def check(condition, message):
    log(("ok   " if condition else "FAIL ") + message)
    if not condition:
        raise AssertionError(message)


try:
    from Path.Main.Gui import Job as Gui_Job
    from Path.Main.Gui import Simulator
    import Path.Op.Profile as Profile
    from IndexedCAM.Commands import face_orientation
    from IndexedCAM.Commands.context import build_context
    from IndexedCAM.Commands.transaction import DocumentTransaction
    from IndexedCAM.Core.face_orientation import FaceOrientationService
    from IndexedCAM.Gui import native_simulator

    doc = App.newDocument("Sim")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 60, 40, 30
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)
    job = Gui_Job.Create([box], openTaskPanel=False)
    clone = job.Model.Group[0]
    op = Profile.Create("Contour", parentJob=job)
    op.Base = [(clone, ["Face6"])]
    doc.recompute()
    ctx = build_context(doc, job)

    for face, name, ops in (("Face6", "Superior", []), ("Face2", "Lateral X", [op])):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, clone.Name, face)
        Gui.Selection.addSelection(doc.Name, job.Name)
        face_orientation.FaceOrientationWorkflow(
            FaceOrientationService(), ctx.manager, face_orientation._shared_triad(),
            lambda orientation, default, n=name: n,
            lambda: DocumentTransaction(doc, "setup"),
            lambda setup, o=ops: ctx.assigner.assign(setup.name, o),
        ).run(Gui.Selection.getSelectionEx())
    doc.recompute()

    plan = native_simulator.build_plan(job)
    check(plan is not None and plan.orientation(op.Name) == (90.0, 0.0), "plan has the operation's B/C: %s" % (plan and plan.orientations))

    check(native_simulator.install(), "simulator patched")
    check(native_simulator.install(), "patch is idempotent")

    class Fake:
        isVoxel = False

        def PerformCutBoolean(self):
            pass

    sim = Fake()
    sim.job, sim.operation, sim.busy, sim.resetSimulation = job, op, False, False
    sim.cutTool = doc.addObject("Part::FeaturePython", "CutTool")
    sim.cutTool.Placement = App.Placement(App.Vector(1, 2, 3), App.Rotation())
    Simulator.PathSimulation.PerformCut(sim)
    axis = sim.cutTool.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    check(abs(axis.x - 1) < 1e-6 and abs(axis.z) < 1e-6, "tool axis follows B/C of the operation: %s" % axis)
    out.write("ok   native tool tilted in place\n")
    Gui.getMainWindow().close()
    out.write("PASS\n")
except Exception:
    out.write(traceback.format_exc())
    out.write("FAIL\n")
    Gui.getMainWindow().close()
