"""FreeCAD check: a toolpath saved in the file never reaches the Preview or the post.

CAM rebuilds an operation only when one of its inputs is flagged as changed, and
a ``LocalModel`` keeps its Shape transient, so a document can hold a Path
computed against another geometry with the operation reported as up to date. A
plain recompute does not fix it: the operation has to be touched. ``build_context``
(what the Preview and the post use) does it once for every document whose local
models were rebuilt from a file.

Run headless with the AppImage:
    INDEXEDCAM_ROOT=<repo> INDEXEDCAM_LOG=<log> FreeCAD.AppImage tests/freecad/check_stale_paths.py
The last line of the log is PASS on success.
"""

import os
import sys
import tempfile
import traceback

import FreeCAD as App

ROOT = os.environ.get("INDEXEDCAM_ROOT", os.getcwd())
LOG = os.environ.get("INDEXEDCAM_LOG", os.path.join(tempfile.gettempdir(), "check_stale_paths.log"))
sys.path.insert(0, ROOT)
out = open(LOG, "w")


def log(*args):
    out.write(" ".join(str(a) for a in args) + "\n")
    out.flush()


def check(condition, message):
    log(("ok   " if condition else "FAIL ") + message)
    if not condition:
        raise AssertionError(message)


def z_range(path):
    values = [c.Parameters["Z"] for c in path.Commands if "Z" in c.Parameters]
    return (round(min(values), 3), round(max(values), 3)) if values else (None, None)


try:
    import Path.Op.MillFace as MillFace
    from Path.Main import Job as CamJob

    from IndexedCAM.Commands.context import build_context
    from IndexedCAM.Core import local_model, stale_paths
    from IndexedCAM.Core.cam_bridge import CamBridge
    from IndexedCAM.Core.indexed_setup import IndexedSetup
    from IndexedCAM.Machine.bc_head import normal_to_bc

    def top_face(model):
        faces = [(index, face.CenterOfMass.z) for index, face in enumerate(model.Shape.Faces)]
        return "Face%d" % (max(faces, key=lambda item: item[1])[0] + 1)

    doc = App.newDocument("Stale")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 60, 40, 30
    doc.recompute()
    job = CamJob.Create("Job", [box])
    bridge = CamBridge(job)

    head = normal_to_bc((1, 0, 0))
    setup = IndexedSetup(name="SideX", normal=(1, 0, 0), b=head.b, c=head.c, origin=(60, 20, 15))
    model = bridge.attach_setup(box, setup)

    operation = MillFace.Create("OpFace", parentJob=job)
    operation.ToolController = job.Tools.Group[0]
    operation.Base = [(model, [top_face(model)])]
    bridge.bind_operation(operation, "SideX")
    doc.recompute()
    check(operation.Path.Commands, "the operation cuts before the file is saved")
    first_path = operation.Path
    first = z_range(first_path)
    check(first == (0.0, 10.0), "the path of the face sits at Z %s" % (first,))

    path = os.path.join(tempfile.gettempdir(), "stale_paths_check.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)

    # --- a document restored from a file --------------------------------
    doc = App.openDocument(path)
    job = doc.getObject("Job")
    operation = doc.getObject("OpFace")
    model = local_model.find(job, "SideX")
    check(model is not None, "the local model is restored")
    check(
        stale_paths.marked(doc),
        "rebuilding the local model from the file marks the document",
    )

    # the part grows in a later session: the Path of the file is the old one
    doc.getObject("Box").Length = 80
    doc.recompute()
    grown = z_range(operation.Path)
    check(grown == (20.0, 30.0), "the operation follows the edited part: Z %s" % (grown,))

    operation.Path = first_path
    check(z_range(operation.Path) == first, "the file can hold the path of the old part")
    stale_paths.mark(doc)
    build_context(doc, job)
    check(
        z_range(operation.Path) == grown,
        "build_context rebuilds the stale path: Z %s" % (z_range(operation.Path),),
    )

    operation.Path = first_path
    build_context(doc, job)
    check(
        z_range(operation.Path) == first,
        "the refresh happens once per load, not on every command: Z %s"
        % (z_range(operation.Path),),
    )
    stale_paths.forget()
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
    out.close()
    os._exit(1)
out.close()
os._exit(0)
