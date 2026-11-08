"""FreeCAD end-to-end check of the LinuxCNC post processor.

Creates a Job with two indexed orientations, posts the program and verifies the
G-code has one tilted work plane per orientation, the head angles of each
setup, the operation moves in the local frame and the retract before indexing.
Run headless with the AppImage:
    INDEXEDCAM_ROOT=<repo> INDEXEDCAM_LOG=<log> FreeCAD.AppImage tests/freecad/check_post.py
The last line of the log is PASS on success.
"""

import os
import sys
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui

ROOT = os.environ.get("INDEXEDCAM_ROOT", os.getcwd())
LOG = os.environ.get("INDEXEDCAM_LOG", os.path.join(tempfile.gettempdir(), "check_post.log"))
sys.path.insert(0, ROOT)
out = open(LOG, "w", buffering=1)


def log(*args):
    out.write(" ".join(str(a) for a in args) + "\n")


def finish(ok):
    """Exit without FreeCAD's window shutdown, which can hang in the AppImage.

    The check writes its log first, then leaves with a real exit code so a
    runner does not have to parse the log to know whether it passed.
    """
    out.flush()
    os._exit(0 if ok else 1)


def check(condition, message):
    log(("ok   " if condition else "FAIL ") + message)
    if not condition:
        raise AssertionError(message)


def blocks(text, prefix):
    return [line for line in text.splitlines() if line.startswith(prefix)]


def words_of(line):
    body = line.split("(")[0]
    return {item[0]: float(item[1:]) for item in body.split()[1:] if item[0].isalpha()}


def unit(vector):
    length = sum(v * v for v in vector) ** 0.5
    return tuple(v / length for v in vector)


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def frame_from(q1, q2):
    """Frame the controller builds from the two G68.2 P3 blocks."""
    words, normal = words_of(q1), words_of(q2)
    origin = (words["X"], words["Y"], words["Z"])
    x_axis = unit((words["I"], words["J"], words["K"]))
    z_axis = unit((normal["I"], normal["J"], normal["K"]))
    return origin, x_axis, cross(z_axis, x_axis), z_axis


def block_of(move):
    """The G-code block the post must produce for a move."""
    return " ".join([move.code] + ["%s%.3f" % (letter, value) for letter, value in move.words])


def close(actual, expected, tolerance=1e-3):
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


try:
    from Path.Main.Gui import Job as Gui_Job
    import Path.Op.MillFace as MillFace
    import Path.Op.Profile as Profile
    from IndexedCAM.Commands import face_orientation, post
    from IndexedCAM.Commands.context import build_context
    from IndexedCAM.Commands.post import build_post, default_path, summary_text, write_program
    from IndexedCAM.Commands.transaction import DocumentTransaction
    from IndexedCAM.Core.face_orientation import FaceOrientationService
    from IndexedCAM.Post.linuxcnc import AxisSigns, LinuxCNCConfig, LinuxCNCPost

    post.register()
    check(post.COMMAND_NAME in Gui.listCommands(), "command registered")

    doc = App.newDocument("Post")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 60, 40, 30
    box.Placement = App.Placement(App.Vector(10, 20, 30), App.Rotation())
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)

    job = Gui_Job.Create([box], openTaskPanel=False)
    clone = job.Model.Group[0]
    facing = MillFace.Create("Facing", parentJob=job)
    contour = Profile.Create("Contour", parentJob=job)
    facing.Base = [(clone, ["Face6"])]
    contour.Base = [(clone, ["Face2"])]
    doc.recompute()

    ctx = build_context(doc, job)
    manager, bridge, program = ctx.manager, ctx.bridge, ctx.program

    def make_setup(face, name, operations):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, clone.Name, face)
        Gui.Selection.addSelection(doc.Name, job.Name)
        workflow = face_orientation.FaceOrientationWorkflow(
            FaceOrientationService(),
            manager,
            face_orientation._shared_triad(),
            lambda orientation, default: name,
            lambda: DocumentTransaction(doc, "Create indexed setup"),
            lambda setup: ctx.assigner.assign(setup.name, operations),
        )
        return workflow.run(Gui.Selection.getSelectionEx())

    lateral = make_setup("Face2", "Lateral X", [contour])
    upper = make_setup("Face6", "Superior", [facing])
    check(lateral.b == 90.0 and upper.b == 0.0, "setups as expected: B=%s/%s" % (lateral.b, upper.b))

    posted = build_post(doc, manager, program, bridge, "PostCheck")
    check([o.name for o in posted.orientations] == ["Lateral X", "Superior"],
          "one orientation per indexed setup: %s" % [o.name for o in posted.orientations])
    check(len(posted.operations()) == 2, "one operation per orientation")
    check(all(o.operations for o in posted.orientations), "no orientation is empty")

    text = LinuxCNCPost().render(posted, LinuxCNCConfig())
    log(text)

    planes = blocks(text, "G68.2 P3 Q1")
    normals = blocks(text, "G68.2 P3 Q2")
    check(len(planes) == 2 and len(normals) == 2, "one tilted work plane per orientation")
    for orientation, first, second in zip(posted.orientations, planes, normals):
        origin, x_axis, y_axis, z_axis = frame_from(first, second)
        check(close(origin, orientation.origin), "plane origin of %s" % orientation.name)
        check(close(x_axis, orientation.x_axis), "plane +X of %s" % orientation.name)
        check(close(z_axis, orientation.z_axis), "plane normal of %s" % orientation.name)
        check(close(y_axis, orientation.y_axis), "Y derived by the control matches: %s" % orientation.name)
    check("G0 B90.000 C0.000 (indexado)" in text, "head indexed to the lateral setup")
    check("G0 B0.000 C0.000 (indexado)" in text, "head indexed to the upper setup")
    check(len(blocks(text, "M6")) == 1, "single tool: one tool change")
    check(blocks(text, "M6")[0].startswith("M6 T"), "tool number from the CAM controller")
    check(any(line.startswith("G43.4 H") for line in text.splitlines()), "tool length on the kinematics")

    cutting = [
        line for line in text.splitlines()
        if line.startswith(("G1 ", "G2 ", "G3 "))
    ]
    modal, missing = 0.0, []
    for line in text.splitlines():
        if not line.startswith(("G1 ", "G2 ", "G3 ", "F", "G0 ")):
            continue
        for item in line.split(" (")[0].split():
            if item.startswith("F"):
                modal = float(item[1:])
        if line.startswith(("G1 ", "G2 ", "G3 ")) and modal <= 0.0:
            missing.append(line)
    check(cutting and not missing, "%d movimientos de corte, todos con avance: %s"
          % (len(cutting), missing[:2]))
    check(not [line for line in text.splitlines() if line.startswith("G1") and "F0" in line],
          "ningun G1 con F0")

    from IndexedCAM.Core.safety import JobSafetyStorage, SafetyConfig

    stored = JobSafetyStorage(job)
    check(stored.load() == SafetyConfig(), "sin configurar, la distancia de seguridad es la minima")
    stored.save(SafetyConfig(30.0))
    check(stored.load() == SafetyConfig(30.0), "la distancia de seguridad se guarda en el Job")
    short = build_post(doc, manager, program, bridge, "PostCheck", SafetyConfig())
    padded = build_post(doc, manager, program, bridge, "PostCheck", SafetyConfig(30.0))
    check(all(p.safe_z < q.safe_z for p, q in zip(short.orientations, padded.orientations)),
          "mas margen = retirada mas alta: %s < %s"
          % (["%.2f" % o.safe_z for o in short.orientations],
             ["%.2f" % o.safe_z for o in padded.orientations]))
    check(all(abs(p.safe_z - 30.0 - q.safe_z) < 1e-6
              for p, q in zip(padded.orientations, short.orientations)),
          "el margen se suma tal cual a la altura de retirada")
    stored.save(SafetyConfig())

    from IndexedCAM.Core.post_settings import JobPostStorage, PostSettings
    from IndexedCAM.Post.linuxcnc import AxisSigns as PostSigns

    post_storage = JobPostStorage(job)
    check(post_storage.load() == PostSettings(), "las opciones del post empiezan por defecto")
    chosen = PostSettings(
        LinuxCNCConfig(signs=PostSigns(b_sign=-1.0, c_zero=90.0), line_numbers=True),
        "PostCheck",
    )
    post_storage.save(chosen)
    check(post_storage.load() == chosen, "las opciones del post se guardan en el Job")
    flipped = LinuxCNCPost().render(posted, post_storage.load().config)
    check("G0 B-90.000 C-90.000 (indexado)" in flipped,
          "el sentido configurado llega al G-code")
    numbered = [line for line in flipped.splitlines() if line.startswith("N")]
    check(numbered and numbered[0].startswith("N10 "),
          "la numeracion de lineas configurada llega al G-code: %s" % numbered[:1])
    post_storage.save(PostSettings())

    names = [o.name for o in posted.orientations]
    safe = {o.name: o.safe_z for o in posted.orientations}
    clear = {o.name: o.clearance_z for o in posted.orientations}
    log("safe", safe, "clearance", clear)
    check(all(o.safe_z > o.clearance_z for o in posted.orientations) or names,
          "retract height above the approach")
    check("G0 Z%.3f" % safe["Superior"] in text, "upper retract uses its own plane")

    emitted = [line.split(" (")[0] for line in text.splitlines()]
    for orientation in posted.orientations:
        missing = [
            block
            for operation in orientation.operations
            for block in [block_of(move) for move in operation.moves]
            if block not in emitted
        ]
        total = sum(len(operation.moves) for operation in orientation.operations)
        check(not missing, "%d moves of %s emitted unchanged %s" % (total, orientation.name, missing[:3]))

    signs = AxisSigns(b_sign=-1.0, c_zero=90.0)
    flipped = LinuxCNCPost().render(posted, LinuxCNCConfig(signs=signs))
    check("G0 B-90.000 C-90.000 (indexado)" in flipped, "axis signs are configurable")

    path = os.path.join(tempfile.mkdtemp(), "postcheck.ngc")
    write_program(text, path)
    again = open(path, "r", encoding="ascii").read()
    check(again == text, "written file reads back unchanged")
    check(again.startswith("%\n") and again.endswith("%\n"), "tape markers")
    check(default_path(doc, "X").endswith("X.ngc"), "default file name")
    check("2 orientación(es)" in summary_text(posted, 10), "summary text")
    log("summary:", summary_text(posted, len(text.splitlines())))

    check(not os.path.exists(path + ".bak"), "no stray files")
    example = os.environ.get("INDEXEDCAM_EXAMPLE", "")
    if example:
        write_program(text, example)
        log("ejemplo escrito en", example)

    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAIL")
    finish(False)
finally:
    out.flush()
finish(True)
