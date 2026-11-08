"""FreeCAD integration check for the CAM bridge (one Job per orientation).

Run headless with the AppImage:
    INDEXEDCAM_ROOT=<repo> INDEXEDCAM_LOG=<log> FreeCAD.AppImage tests/freecad/check_cam_bridge.py
The last line of the log is PASS on success.

Covers the reason the architecture changed: CAM's area operations (Adaptive,
3D Surface...) read ``Job.Model`` and ``Job.Stock``, so an operation only
machines a tilted face when it lives in a Job whose model is already in that
face's frame.
"""

import math
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


def points(op):
    return [
        c.Parameters
        for c in op.Path.Commands
        if all(letter in c.Parameters for letter in "XYZ")
    ]


def height(op, prop):
    """Numeric value of a CAM height property."""
    return float(getattr(getattr(op, prop), "Value", getattr(op, prop)))


def local_z(op):
    return sorted({round(p["Z"], 2) for p in points(op)})


SIN45 = math.sin(math.radians(45))


def face_at_origin(model):
    """Name of the planar face that lies on the local Z=0 plane.

    The tool axis of an orientation is +Z, so the face it machines is the one
    whose plane goes through the local origin. Geometry (``CenterOfMass``) is
    used instead of ``normalAt`` because FreeCAD reports normals in a frame
    that ignores the placement of the shape.
    """
    for index, face in enumerate(model.Shape.Faces, start=1):
        if face.Surface.__class__.__name__ == "Plane" and abs(face.CenterOfMass.z) < 1e-6:
            return "Face%d" % index
    raise AssertionError("no face on the local Z=0 plane")


def make_part(document):
    """60x40x30 block with a 45 degree chamfer on one top edge (x + z = 70)."""
    box = document.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 60, 40, 30
    cutter = document.addObject("Part::Box", "Cutter")
    cutter.Length, cutter.Width, cutter.Height = 100, 100, 100
    cutter.Placement = App.Placement(
        App.Vector(40, -30, 30), App.Rotation(App.Vector(0, 1, 0), 45)
    )
    cut = document.addObject("Part::Cut", "Part")
    cut.Base, cut.Tool = box, cutter
    document.recompute()
    return cut


def inclined_face(model):
    """Name and face of the 45 degree plane (normal (sin45, 0, sin45)).

    The part itself has no placement, so ``normalAt`` is usable here.
    """
    for index, face in enumerate(model.Shape.Faces, start=1):
        normal = face.normalAt(0, 0)
        if face.Surface.__class__.__name__ == "Plane" and (
            abs(normal.x - SIN45) < 1e-6
            and abs(normal.z - SIN45) < 1e-6
            and abs(normal.y) < 1e-6
        ):
            return "Face%d" % index, face
    raise AssertionError("no inclined face in the part")


try:
    import Path.Op.MillFace as MillFace
    import Path.Op.Surface as Surface
    from IndexedCAM.Core.cam_bridge import CamBridge, CamBridgeError
    from IndexedCAM.Core.indexed_setup import IndexedSetup
    from IndexedCAM.Core.local_model import find as find_local_model
    from IndexedCAM.Machine.bc_head import normal_to_bc

    def setup(name, normal, origin=(0, 0, 0)):
        angles = normal_to_bc(normal)
        return IndexedSetup(name=name, normal=normal, b=angles.b, c=angles.c, origin=origin)

    doc = App.newDocument("Bridge")
    part = make_part(doc)
    face_name, face = inclined_face(part)
    normal = (face.normalAt(0, 0).x, face.normalAt(0, 0).y, face.normalAt(0, 0).z)
    center = face.CenterOfMass

    top = setup("Superior", (0, 0, 1), (20.0, 20.0, 30.0))
    incl = setup("Inclinada", normal, (center.x, center.y, center.z))

    bridge = CamBridge(doc)
    top_job = bridge.attach_setup(part, top)
    incl_job = bridge.attach_setup(part, incl)
    check(top_job is not incl_job, "one CAM Job per orientation")
    check(bridge.jobs.jobs() == [top_job, incl_job], "both Jobs are the orientation Jobs")
    check(
        all(job not in getattr(other, "Group", ()) for job in (top_job, incl_job) for other in doc.Objects),
        "the Jobs are root objects: no container groups them",
    )
    check(doc.getObject("IndexedCAM") is None, "no IndexedCAM container object in the document")
    from IndexedCAM.Core.job_context import find_jobs

    check([j.Name for j in find_jobs(doc)] == [top_job.Name, incl_job.Name], "two CAM Jobs only")

    top_model = bridge.jobs.model("Superior")
    incl_model = bridge.jobs.model("Inclinada")
    check(abs(top_model.Shape.BoundBox.ZMax) < 1e-6, "top face brought to local Z=0")
    check(
        face_at_origin(top_model) == "Face3",
        "top model: Face3 is the machined one on the local Z=0 plane",
    )
    check(
        face_at_origin(incl_model) == face_name,
        "the inclined face lies on the local Z=0 plane",
    )
    check(
        abs(top_model.Shape.BoundBox.XLength - 60) < 1e-6
        and abs(top_model.Shape.BoundBox.ZLength - 30) < 1e-6,
        "top model keeps the part size",
    )
    check(
        abs(top_job.Stock.Shape.BoundBox.ZMax - 1.0) < 1e-6
        and abs(top_job.Stock.Shape.BoundBox.ZMin - (top_model.Shape.BoundBox.ZMin - 1.0)) < 1e-6,
        "stock of the top Job follows its model (1 mm)",
    )
    check(
        abs(incl_job.Stock.Shape.BoundBox.ZMax - incl_model.Shape.BoundBox.ZMax - 1.0) < 1e-6,
        "stock of the inclined Job is in the local frame too",
    )

    # 2.5D operation in its own Job
    face_top = MillFace.Create("OpSuperior", parentJob=top_job)
    bridge.bind_operation(face_top, "Superior", face=face_at_origin(top_model))
    check(face_top.Base and face_top.Base[0][0] is top_model, "base re-pointed to the Job model")
    check(abs(height(face_top, "StartDepth")) < 1e-6, "start depth on the machined face")
    check(
        abs(height(face_top, "SafeHeight") - 5.0) < 1e-6
        and abs(height(face_top, "ClearanceHeight") - 10.0) < 1e-6,
        "safe and clearance heights above the local model",
    )
    check(len(face_top.Path.Commands) > 3, "2.5D operation computes")

    # OCL operation on the 45 degree face: the bug this architecture fixes
    ocl = Surface.Create("OpInclinada", parentJob=incl_job)
    bridge.bind_operation(ocl, "Inclinada", face=face_name)
    zs = local_z(ocl)
    cuts = [p for p in points(ocl) if p["Z"] <= 0.01]
    check(len(cuts) > 10, "3D Surface produces cutting moves: %d" % len(cuts))
    check(
        abs(height(ocl, "ClearanceHeight") - (incl_model.Shape.BoundBox.ZMax + 10.0)) < 1e-6,
        "surface clearance follows the local model: %s" % height(ocl, "ClearanceHeight"),
    )
    check(min(zs) >= -6.0, "surface does not cut far below the face: %s" % min(zs))
    limits = incl_model.Shape.BoundBox
    inside = all(
        limits.XMin - 1 <= p["X"] <= limits.XMax + 1
        and limits.YMin - 1 <= p["Y"] <= limits.YMax + 1
        for p in points(ocl)
    )
    check(inside, "surface path stays inside the orientation model")
    face_box = incl_model.Shape.getElement(face_name).BoundBox
    span_x = max(p["X"] for p in cuts) - min(p["X"] for p in cuts)
    span_y = max(p["Y"] for p in cuts) - min(p["Y"] for p in cuts)
    check(
        span_x > 0.5 * face_box.XLength and span_y > 0.5 * face_box.YLength,
        "surface covers the inclined face (%.1fx%.1f of %.1fx%.1f)"
        % (span_x, span_y, face_box.XLength, face_box.YLength),
    )

    check([o.Name for o in bridge.operations_of("Inclinada")] == ["OpInclinada"], "operations_of")
    check(bridge.setup_of(ocl) == "Inclinada", "setup_of finds the owning Job")
    check(
        [s.setup for s in bridge.bound_steps()] == ["Superior", "Inclinada"],
        "bound steps follow the document order",
    )
    check(ocl.ToolController in list(incl_job.Tools.Group), "tool moved with the operation")

    # the source part is edited: the model and the heights follow
    before = height(face_top, "StartDepth")
    part.Base.Height = 40
    doc.recompute()
    bridge.refresh_all()
    check(
        abs(height(face_top, "StartDepth") - 10.0) < 1e-6 and height(face_top, "StartDepth") > before,
        "refresh_all re-derives the heights after the part edit: %s" % height(face_top, "StartDepth"),
    )

    try:
        bridge.detach_setup("Inclinada")
        check(False, "detach with bound operations must fail")
    except CamBridgeError:
        check(True, "detach refuses a Setup with operations")

    path = os.path.join(tempfile.gettempdir(), "bridge_check.FCStd")
    doc.saveAs(path)
    check(os.path.getsize(path) < 400000, "file size: %d bytes" % os.path.getsize(path))
    App.closeDocument(doc.Name)

    doc2 = App.openDocument(path)
    doc2.recompute()
    reloaded = CamBridge(doc2)
    check([s.name for s in reloaded.jobs.setups()] == ["Superior", "Inclinada"], "jobs survive reload")
    model = find_local_model(doc2, "Inclinada")
    check(model is not None and not model.Shape.isNull(), "local model rebuilt after reload")
    check(len(reloaded.operations_of("Inclinada")) == 1, "operation still bound after reload")
    check(
        reloaded.jobs.model("Inclinada").Shape.BoundBox.ZMax > 0.0,
        "Job model cloned in the local frame after reload",
    )
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
Gui.getMainWindow().close()
