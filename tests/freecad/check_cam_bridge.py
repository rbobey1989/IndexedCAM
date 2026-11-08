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
import Part

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
    check(mb in list(job.Model.Group), "local model lives inside Job.Model (CAM finds the faces)")
    stock_box = job.Stock.Shape.BoundBox
    check(
        abs(stock_box.XLength - 62) < 1e-6
        and abs(stock_box.YLength - 42) < 1e-6
        and abs(stock_box.ZLength - 32) < 1e-6,
        "the Job stock still fits the part after two orientations: %s" % stock_box,
    )
    check(
        type(job.Stock.Proxy).__name__ == "OrientationStock",
        "the stock ignores the rotated copies: %s" % type(job.Stock.Proxy).__name__,
    )
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

    # --- regresion: 3D Surface en una cara inclinada con UN solo Job --------
    import math

    import Path.Op.Surface as Surface

    sin45 = math.sin(math.radians(45))
    block = doc.addObject("Part::Box", "Block")
    block.Length, block.Width, block.Height = 60, 40, 30
    corner = doc.addObject("Part::Box", "Corner")
    corner.Length, corner.Width, corner.Height = 100, 100, 100
    corner.Placement = App.Placement(
        App.Vector(40, -30, 30), App.Rotation(App.Vector(0, 1, 0), 45)
    )
    chamfered = doc.addObject("Part::Cut", "Chamfered")
    chamfered.Base, chamfered.Tool = block, corner
    doc.recompute()

    inclined_name, inclined = None, None
    for index, face in enumerate(chamfered.Shape.Faces, start=1):
        normal = face.normalAt(0, 0)
        if (
            face.Surface.__class__.__name__ == "Plane"
            and abs(normal.x - sin45) < 1e-6
            and abs(normal.z - sin45) < 1e-6
            and abs(normal.y) < 1e-6
        ):
            inclined_name, inclined = "Face%d" % index, face
    check(inclined is not None, "the chamfered part has a 45 degree face")

    incl_job = CamJob.Create("JobIncl", [chamfered])
    incl_bridge = CamBridge(incl_job)
    incl_setup = setup(
        "Inclinada",
        (inclined.normalAt(0, 0).x, inclined.normalAt(0, 0).y, inclined.normalAt(0, 0).z),
        tuple(inclined.CenterOfMass),
    )
    model = incl_bridge.attach_setup(chamfered, incl_setup)
    check(model in list(incl_job.Model.Group), "the inclined model is inside the Job model")

    surface = Surface.Create("SurfaceIncl", parentJob=incl_job)
    surface.StepOver = 1.0
    incl_bridge.bind_operation(surface, "Inclinada", face=inclined_name)
    doc.recompute()
    surface_points = [
        c.Parameters for c in surface.Path.Commands if all(k in c.Parameters for k in "XYZ")
    ]
    check(len(surface_points) > 100, "3D Surface computes in the same Job: %d points" % len(surface_points))
    zs = [q["Z"] for q in surface_points]
    check(min(zs) > -5.0, "surface does not cut through the part: Zmin %.2f" % min(zs))
    stock_top = float(model.StockTop)
    check(
        stock_top > model.Shape.BoundBox.ZMax + 1.0,
        "the stock of a chamfered block leans over the face: StockTop %.2f vs model %.2f"
        % (stock_top, model.Shape.BoundBox.ZMax),
    )
    check(
        abs(max(local_z(surface)) - (stock_top + 10.0)) < 0.01,  # local_z rounds to 0.01
        "the rapids clear the stock, not only the part: clearance %.2f (stock top %.2f)"
        % (max(local_z(surface)), stock_top),
    )
    check(
        max(zs) <= stock_top + 10.0 + 1e-6,
        "surface does not rapid above the clearance: Zmax %.2f" % max(zs),
    )
    limits = model.Shape.BoundBox
    inside = all(
        limits.XMin - 1.0 <= q["X"] <= limits.XMax + 1.0
        and limits.YMin - 1.0 <= q["Y"] <= limits.YMax + 1.0
        for q in surface_points
    )
    check(inside, "surface path stays inside the orientation model")
    cuts = [q for q in surface_points if q["Z"] <= 0.01]
    face_box = model.Shape.getElement(inclined_name).BoundBox
    span_x = max(q["X"] for q in cuts) - min(q["X"] for q in cuts)
    span_y = max(q["Y"] for q in cuts) - min(q["Y"] for q in cuts)
    check(
        span_x > 0.5 * face_box.XLength and span_y > 0.5 * face_box.YLength,
        "surface covers the inclined face (%.1fx%.1f of %.1fx%.1f)"
        % (span_x, span_y, face_box.XLength, face_box.YLength),
    )

    # --- 3D Pocket y Waterline con el mismo Job -----------------------------
    def positions(op):
        """Points the path visits, following the modal coordinates CAM emits."""
        current = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        found = []
        for command in op.Path.Commands:
            if command.Name not in ("G0", "G1", "G2", "G3"):
                continue
            for letter, value in command.Parameters.items():
                if letter in current:
                    current[letter] = value
            found.append(dict(current))
        return found

    face_box = model.Shape.getElement(inclined_name).BoundBox
    model_box = model.Shape.BoundBox

    import Path.Op.Pocket as Pocket3D
    import Path.Op.Waterline as Waterline

    pocket3d = Pocket3D.Create("Pocket3D", parentJob=incl_job)
    pocket3d.Base = [(model, [inclined_name])]
    pocket3d.StepDown = 0.5
    incl_bridge.bind_operation(pocket3d, "Inclinada", face=inclined_name)
    doc.recompute()
    visited = positions(pocket3d)
    cuts3d = [q for q in visited if q["Z"] <= 0.01]
    check(len(cuts3d) > 10, "3D Pocket cuts the inclined face: %d moves" % len(cuts3d))
    check(
        all(face_box.XMin - 1.0 <= q["X"] <= face_box.XMax + 1.0 for q in cuts3d)
        and all(face_box.YMin - 1.0 <= q["Y"] <= face_box.YMax + 1.0 for q in cuts3d),
        "3D Pocket stays on the face it machines",
    )

    # Waterline necesita una forma curva (en un bloque, los contornos coinciden
    # con el borde del modelo y CAM no emite nada): semiesfera aparte
    dome_feature = doc.addObject("Part::Feature", "Dome")
    dome_feature.Shape = Part.makeSphere(20.0).cut(
        Part.makeBox(60, 60, 20, App.Vector(-30, -30, -20))
    )
    doc.recompute()
    dome_job = CamJob.Create("JobDome", [dome_feature])
    dome_bridge = CamBridge(dome_job)
    sphere_index = next(
        index
        for index, candidate in enumerate(dome_feature.Shape.Faces, start=1)
        if candidate.Surface.__class__.__name__ == "Sphere"
    )
    sphere_face = dome_feature.Shape.Faces[sphere_index - 1]
    sphere_normal = sphere_face.normalAt(0.5, 0.5)
    sphere_centre = sphere_face.CenterOfMass
    dome_setup = setup(
        "Domo",
        (sphere_normal.x, sphere_normal.y, sphere_normal.z),
        (sphere_centre.x, sphere_centre.y, sphere_centre.z),
    )
    dome_model = dome_bridge.attach_setup(dome_feature, dome_setup)
    check(dome_model in list(dome_job.Model.Group), "the dome model is inside its Job model")

    waterline = Waterline.Create("Waterline", parentJob=dome_job)
    waterline.Base = []  # el modelo completo, ya orientado
    waterline.StepOver = 20.0
    waterline.StepDown = 1.0
    dome_bridge.bind_operation(waterline, "Domo")
    waterline.FinalDepth = dome_model.Shape.BoundBox.ZMin
    doc.recompute()
    visited = positions(waterline)
    below = [q for q in visited if q["Z"] < -0.5]
    check(len(below) > 20, "Waterline cuts below the surface plane: %d moves" % len(below))
    dome_box = dome_model.Shape.BoundBox
    lowest = min(q["Z"] for q in visited)
    log(
        "     waterline: Z %.2f..%.2f | modelo Z %.2f..%.2f"
        % (lowest, max(q["Z"] for q in visited), dome_box.ZMin, dome_box.ZMax)
    )
    check(
        abs(lowest - dome_box.ZMin) < 1.0,
        "Waterline reaches the bottom of the oriented model: %.2f vs %.2f" % (lowest, dome_box.ZMin),
    )

    # --- un documento de la version anterior vuelve a un solo Job -----------
    import json

    import Path.Op.Pocket as Pocket
    from IndexedCAM.Commands.context import build_context
    from IndexedCAM.Core.job_context import find_jobs

    leftover = CamJob.Create("IndexedCAM_Job_SideX", [mb])
    leftover.addProperty("App::PropertyString", "IndexedCAMSetup", "IndexedCAM", "Orientation")
    leftover.IndexedCAMSetup = json.dumps(
        setup("SideX", (1, 0, 0), (60.0, 20.0, 15.0)).to_dict()
        | {"metadata": {"source": "Box.Face1"}}
    )
    stray = Pocket.Create("StrayOp", parentJob=leftover)
    stray.Base = [(leftover.Model.Group[0], ["Face5"])]
    doc.recompute()
    check(len(find_jobs(doc)) == 4, "the leftover Job exists before adopting it: %d" % len(find_jobs(doc)))

    context = build_context(doc, job)
    check(
        "IndexedCAM_Job_SideX" not in [o.Name for o in find_jobs(doc)],
        "the leftover Job is folded back into the user's Job",
    )
    check(
        "StrayOp" in [o.Name for o in job.Operations.Group],
        "its operation moved into the user's Job",
    )
    check("SideX" in context.manager, "its Setup is registered in the Job")
    stray_model = local_model.find(job, "SideX")
    check(
        stray_model is not None and stray.Base[0][0] is stray_model,
        "its Base points at a local model of the Job",
    )
    check(
        len([o for o in doc.Objects if hasattr(o, "IndexedCAMSetup")]) == 0,
        "no orientation Jobs are left in the document",
    )

    path = os.path.join(tempfile.gettempdir(), "bridge_check.FCStd")
    doc.saveAs(path)
    # the check is that the local models do not save their Shape: what is stored
    # is the part plus the Path and removal shape of the operations
    check(os.path.getsize(path) < 200000, "file size small: %d bytes" % os.path.getsize(path))
    App.closeDocument(doc.Name)
    doc2 = App.openDocument(path)
    doc2.recompute()
    job2 = [o for o in doc2.Objects if hasattr(o, "Operations") and hasattr(o, "Tools")][0]
    mb2 = local_model.find(job2, "SideX")
    check(mb2 is not None and not mb2.Shape.isNull(), "local model rebuilt after reload")
    check(
        type(job2.Stock.Proxy).__name__ == "OrientationStock",
        "the stock proxy survives the reload: %s" % type(job2.Stock.Proxy).__name__,
    )
    check(
        abs(job2.Stock.Shape.BoundBox.XLength - 82) < 1e-6,
        "the stock follows the edited part (80+1+1) after the reload: %s"
        % job2.Stock.Shape.BoundBox,
    )
    reloaded_ops = [op.Name for op in CamBridge(job2).operations_of("SideX")]
    check(
        reloaded_ops == ["OpB", "StrayOp"],
        "bound operations found after reload: %s" % reloaded_ops,
    )
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
Gui.getMainWindow().close()
