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
    import Path.Op.MillFace as MillFace
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
    op = MillFace.Create("Facing", parentJob=job)
    op.Base = [(clone, ["Face2"])]
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

    op.setExpression("FinalDepth", None)
    op.FinalDepth = -5
    doc.recompute()
    ZS = sorted({round(c.Parameters["Z"], 1) for c in op.Path.Commands if "Z" in c.Parameters})
    log("props", op.StartDepth, op.FinalDepth, op.OpFinalDepth, op.SafeHeight, len(op.Path.Commands), op.StepDown, op.Base)
    check(min(ZS) < 0, "operation cuts below the face: %s" % ZS)
    sim = Simulator.PathSimulation()
    sim.Activate()
    check(type(sim.voxSim).__name__ == "IndexedVoxSim", "indexed job uses the indexed voxel engine")
    sim.disableAnim = True
    tilted = False
    for _ in range(sim.numCommands + 5):
        if sim.ioperation >= len(sim.activeOps) or sim.icmd >= len(sim.opCommands):
            break
        sim.PerformCut()
        axis = sim.cutTool.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        tilted = tilted or abs(axis.x - 1) < 1e-6
    check(tilted, "CAM's own CutTool is tilted along the lateral operation")
    sim.voxSim.flush()
    stock = sim.voxSim.stock
    removed = 1.0 - stock.volume() / (stock.cells.size * stock.resolution ** 3)
    check(removed > 0.001, "material was removed: %.4f" % removed)
    # the lateral operation works on the +X face: material must go near x = XMax, not on top
    x_idx = int(stock.cells.shape[0] * 0.97)
    top_idx = int(stock.cells.shape[2] * 0.95)
    check(not stock.cells[x_idx].all(), "material removed on the +X face")
    half = stock.cells.shape[0] // 2
    check(stock.cells[:half, :, top_idx].all(), "far side of the top face untouched by the lateral operation")
    import time

    started = time.time()
    mesh, inner = sim.voxSim.GetResultMesh(force=True)
    log("mesh facets %d in %.2fs" % (mesh.CountFacets, time.time() - started))
    check(mesh.CountFacets > 12 and abs(mesh.Volume - stock.volume()) / stock.volume() < 0.01, "display mesh matches the voxel volume")
    sim.accept()
    Gui.getMainWindow().close()
    out.write("PASS\n")
except Exception:
    out.write(traceback.format_exc())
    out.write("FAIL\n")
    Gui.getMainWindow().close()
