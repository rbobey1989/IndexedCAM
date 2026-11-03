"""FreeCAD integration check for the CAM bridge (#12).

Run headless with the AppImage:
    INDEXEDCAM_ROOT=<repo> INDEXEDCAM_LOG=<log> FreeCAD.AppImage tests/freecad/check_cam_bridge.py
The last line of the log is PASS on success.
"""

import os
import sys
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui

ROOT = os.environ.get("INDEXEDCAM_ROOT", os.getcwd())
LOG = os.environ.get("INDEXEDCAM_LOG", os.path.join(tempfile.gettempdir(), "check_cam_bridge.log"))
sys.path.insert(0, ROOT)
out = open(LOG, "w")


def log(*args):
    out.write(" ".join(str(a) for a in args) + "\n")
    out.flush()


def check(condition, message):
    log(("ok   " if condition else "FAIL ") + message)
    if not condition:
        raise AssertionError(message)


def local_z(op):
    return sorted({round(c.Parameters["Z"], 2) for c in op.Path.Commands if "Z" in c.Parameters})


try:
    import Path.Op.MillFace as MillFace
    import Path.Op.Pocket as Pocket
    from IndexedCAM.Core.cam_bridge import CamBridge, CamBridgeError
    from IndexedCAM.Core.indexed_setup import IndexedSetup
    from IndexedCAM.Core import local_model
    from IndexedCAM.Machine.bc_head import normal_to_bc

    def setup(name, normal, origin=(0, 0, 0)):
        a = normal_to_bc(normal)
        return IndexedSetup(name=name, normal=normal, b=a.b, c=a.c, origin=origin)

    doc = App.newDocument("Bridge")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 60, 40, 30
    doc.recompute()

    from Path.Main import Job as CamJob

    job = CamJob.Create("Job", [box])
    bridge = CamBridge(job)
    sa, sb = setup("TopFace", (0, 0, 1)), setup("SideX", (1, 0, 0))
    ma = bridge.attach_setup(box, sa)
    mb = bridge.attach_setup(box, sb)
    check(local_model.find(job, "SideX") is mb, "local model found by Setup name")
    check(abs(mb.Shape.BoundBox.ZMax - 60) < 1e-6, "SideX model: +X face brought to Z=60")
    check(abs(ma.Shape.BoundBox.ZMax - 30) < 1e-6, "TopFace model: Z=30")

    def top_face(model):
        z = [(i, f.CenterOfMass.z) for i, f in enumerate(model.Shape.Faces)]
        return "Face%d" % (max(z, key=lambda t: t[1])[0] + 1)

    ops = {}
    for name, cls, model in (("OpA", MillFace, ma), ("OpB", Pocket, mb)):
        op = cls.Create(name, parentJob=job)
        op.Base = [(model, [top_face(model)])]
        bridge.bind_operation(op, model.SetupName)
        ops[name] = op
    check(len(job.Operations.Group) == 2, "both operations live in the same Job")
    check(max(local_z(ops["OpA"])) == 40, "OpA clearance Z=40 (30+10)")
    check(max(local_z(ops["OpB"])) == 70, "OpB clearance Z=70 (60+10)")
    check(len(ops["OpA"].Path.Commands) < 100, "OpA is a short face path, not stock-wide")
    check([o.Name for o in bridge.operations_of("SideX")] == ["OpB"], "operations_of")

    box.Length = 80
    doc.recompute()
    check(abs(mb.Shape.BoundBox.ZMax - 80) < 1e-6, "local model follows source edit")
    bridge.refresh_all()
    check(max(local_z(ops["OpB"])) == 90, "refresh_all updates heights after edit")

    try:
        bridge.detach_setup("SideX")
        check(False, "detach with bound ops must fail")
    except CamBridgeError:
        check(True, "detach refuses a Setup with operations")

    path = os.path.join(tempfile.gettempdir(), "bridge_check.FCStd")
    doc.saveAs(path)
    check(os.path.getsize(path) < 120000, "file size small: %d bytes" % os.path.getsize(path))
    App.closeDocument(doc.Name)
    doc2 = App.openDocument(path)
    doc2.recompute()
    job2 = [o for o in doc2.Objects if hasattr(o, "Operations") and hasattr(o, "Tools")][0]
    mb2 = local_model.find(job2, "SideX")
    check(mb2 is not None and not mb2.Shape.isNull(), "local model rebuilt after reload")
    check(len(CamBridge(job2).operations_of("SideX")) == 1, "bound operation found after reload")
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
Gui.getMainWindow().close()
