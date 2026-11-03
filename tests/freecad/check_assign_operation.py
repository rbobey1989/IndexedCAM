"""FreeCAD end-to-end check of the Job-first flow (Face Orientation + Assign Operation).

The Job and its operations are created natively by CAM; IndexedCAM adds the
orientations inside the Job, orients the operations, and drives the program,
preview, rename and save/reload. Run headless with the AppImage:
    INDEXEDCAM_ROOT=<repo> INDEXEDCAM_LOG=<log> FreeCAD.AppImage tests/freecad/check_assign_operation.py
The last line of the log is PASS on success.
"""

import os
import sys
import tempfile
import traceback

import FreeCAD as App
import FreeCADGui as Gui

ROOT = os.environ.get("INDEXEDCAM_ROOT", os.getcwd())
LOG = os.environ.get("INDEXEDCAM_LOG", os.path.join(tempfile.gettempdir(), "check_assign.log"))
sys.path.insert(0, ROOT)
out = open(LOG, "w")


def log(*args):
    out.write(" ".join(str(a) for a in args) + "\n")
    out.flush()


def check(condition, message):
    log(("ok   " if condition else "FAIL ") + message)
    if not condition:
        raise AssertionError(message)


def zs(op):
    return sorted({round(c.Parameters["Z"], 2) for c in op.Path.Commands if "Z" in c.Parameters})


try:
    from Path.Main.Gui import Job as Gui_Job
    import Path.Op.MillFace as MillFace
    import Path.Op.PocketShape as PocketShape
    import Path.Op.Profile as Profile
    from IndexedCAM.Commands import assign_operation, face_orientation
    from IndexedCAM.Commands.context import build_context
    from IndexedCAM.Commands.transaction import DocumentTransaction
    from IndexedCAM.Core import local_model
    from IndexedCAM.Core.document_storage import orientations_group
    from IndexedCAM.Core.face_orientation import FaceOrientationService
    from IndexedCAM.Core.indexed_setup import IndexedSetup
    from IndexedCAM.Core.job_context import JobError, find_jobs, resolve_job
    from IndexedCAM.Core.operation_assignment import AssignmentError, AssignOperationWorkflow

    face_orientation.register()
    assign_operation.register()
    check(assign_operation.COMMAND_NAME in Gui.listCommands(), "command registered")

    doc = App.newDocument("Assign")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 60, 40, 30
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)

    try:
        resolve_job(doc, [box], lambda jobs: None)
        check(False, "no Job must be reported")
    except JobError:
        check(True, "without a Job IndexedCAM asks to create it in CAM")

    # the user creates the Job (and operations) with the native CAM workbench
    job = Gui_Job.Create([box], openTaskPanel=False)
    clone = job.Model.Group[0]
    op1 = MillFace.Create("Facing", parentJob=job)
    op2 = PocketShape.Create("Pocket", parentJob=job)
    op3 = Profile.Create("Contour", parentJob=job)
    for op in (op1, op2, op3):
        op.Base = [(clone, ["Face6"])]
    doc.recompute()
    check(resolve_job(doc, [box], lambda jobs: None) is job, "Job found from the selected part")
    ctx = build_context(doc, job)
    manager, bridge, program = ctx.manager, ctx.bridge, ctx.program
    check(orientations_group(job) is None, "nothing is created inside the Job until needed")

    from IndexedCAM.Commands import program as program_command

    def make_setup(face, name, operations):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Box", face)
        Gui.Selection.addSelection(doc.Name, job.Name)
        workflow = face_orientation.FaceOrientationWorkflow(
            FaceOrientationService(), manager, face_orientation._shared_triad(),
            lambda orientation, default: name,
            lambda: DocumentTransaction(doc, "Create indexed setup"),
            lambda setup: ctx.assigner.assign(setup.name, operations),
        )
        return workflow.run(Gui.Selection.getSelectionEx())

    side = make_setup("Face2", "Lateral X", [op1, op3])
    check(side.metadata["source"] == "Box.Face2", "setup remembers its source face")
    group = orientations_group(job)
    check(group is not None and group in job.Group and group.InList == [job],
          "Orientations group lives inside the Job")
    check([o.Label for o in group.Group] == ["Lateral X"], "one object per orientation")
    check(group.Group[0].B == 90.0 and group.Group[0].Source == "Box.Face2", "orientation shows B and source")
    model = local_model.find(job, "Lateral X")
    check(model in job.Model.Group, "local model added to Job.Model")
    check(op1.IndexedSetup == "Lateral X" and op3.IndexedSetup == "Lateral X",
          "operations chosen at creation are bound")
    check(op1.Base[0][0] is model and op1.Base[0][1] == ("Face6",),
          "Base moved to the local model, same face")
    check(abs(model.Shape.Faces[1].CenterOfMass.z) < 1e-6, "setup face is at local Z=0")
    check(len(manager.get("Lateral X").operations) == 2, "Setup.operations updated")

    top = make_setup("Face6", "Superior", [])
    check(local_model.find(job, "Superior") is not None and top.operations == [],
          "orientation without operations still gets its local model")
    ctx.assigner.assign("Superior", [op2])
    check(op2.IndexedSetup == "Superior", "operation associated afterwards")
    check(max(zs(op2)) == 40.0 or max(zs(op2)) == 10.0, "heights follow the local model: %s" % zs(op2))
    check(len(group.Group) == 2 and [o.Label for o in group.Group] == ["Lateral X", "Superior"],
          "two orientations, one object each")
    check(len([o for o in doc.Objects if hasattr(o, "IndexedCAMJob")]) == 0, "IndexedCAM created no Job")
    check(len(find_jobs(doc)) == 1, "single Job")
    check([o.Name for o in job.Operations.Group] == [op1.Name, op2.Name, op3.Name],
          "operations stay chained in the same Job, in order")

    try:
        AssignOperationWorkflow(manager, bridge, ctx.assigner, lambda s, o: None).run()
    except AssignmentError:
        check(False, "assign with setups and operations must not fail")
    wf = AssignOperationWorkflow(manager, bridge, ctx.assigner,
                                 lambda s, o: ("Superior", [o[0]]))
    reassigned = wf.run()
    check(reassigned.setup.name == "Superior" and op1.IndexedSetup == "Superior",
          "Assign Operation re-orients an existing operation")
    ctx.assigner.assign("Lateral X", [op1])
    check(len(bridge.operations_of("Lateral X")) == 2, "operation moved back")

    # deleting an operation in CAM is reflected by the next sync
    spare = MillFace.Create("Spare", parentJob=job)
    ctx.assigner.assign("Superior", [spare])
    check(len(manager.get("Superior").operations) == 2, "Setup lists the new operation")
    doc.removeObject(spare.Name)
    ctx.assigner.sync_operations()
    check(len(manager.get("Superior").operations) == 1, "deleted operation pruned from Setup")

    program.sync(bridge.bound_steps())
    check([s.operation for s in program.steps()] == [op1.Name, op3.Name, op2.Name],
          "new steps are appended in association order")
    program.move(op2.Name, 1)
    check([(s.setup, s.operation) for s in program.steps()] ==
          [("Lateral X", op1.Name), ("Superior", op2.Name),
           ("Lateral X", op3.Name)],
          "user can reorder the program")
    items = program_command.resolve_program(program, manager, bridge, doc)
    check(items[0].previous is None and items[1].needs_transition and items[2].needs_transition,
          "transitions required between different Setups")
    check(items[0].end is not None and items[1].start.b == manager.get("Superior").b,
          "step poses use the Setup angles")
    log("start", items[0].start, "end", items[0].end)
    check(60.0 < items[0].start.point[0] <= 70.5 and items[0].start.b == 90.0,
          "step start lies above the X=60 face, in part coordinates")
    from IndexedCAM.Machine.envelope import Envelope

    env = bridge.envelope_for(op1, Envelope())
    check((env.tool.radius, env.tool.length) == (2.5, 50.0), "envelope takes the CAM tool size")
    check(env.cutting_length == 30.0 and [p.name for p in env.place((0, 0, 0), 0, 0)][:2] == ["tool", "shank"],
          "envelope separates flutes (CuttingEdgeHeight) and shank")
    from IndexedCAM.Core.collision_checker import checker_for_operation, check_operation

    checker = checker_for_operation(bridge, box, op1, Envelope(), margin=1.0)
    frame = manager.get("Lateral X").local_frame()
    result = check_operation(checker.cutting_collision, op1.Path.Commands, frame, 90.0, 0.0)
    check(result is None, "facing the side with the real tool is collision-free: %s" % result)
    check(len(checker._obstacles) == 1, "checker built from the part only")
    from IndexedCAM.Commands import preview
    from IndexedCAM.Gui.tool_view import ToolView

    clips = preview.build_clips(doc, manager, program, bridge)
    kinds = [c.kind for c in clips]
    check(kinds == ["operation", "transition", "operation", "transition", "operation"],
          "preview clips: %s" % kinds)
    check(all(c.error is None for c in clips if c.kind == "transition"),
          "transitions are collision-free: %s" % [c.error for c in clips])
    check(all(len(c) > 0 for c in clips), "every clip has samples")
    log("first collisions:", [c.first_collision() for c in clips])
    scene = Gui.ActiveDocument.ActiveView.getSceneGraph()
    count = scene.getNumChildren()
    view = ToolView()
    view.show_path(clips[1].tips())
    clips[1].poses(0)
    view.show_tool(clips[1].poses(0), collides=False)
    check(scene.getNumChildren() == count + 2, "path and tool nodes added to the 3D scene")
    view.show_tool(clips[1].poses(5), collides=True)
    check(scene.getNumChildren() == count + 2, "showing another pose replaces the tool node")
    view.clear()
    check(scene.getNumChildren() == count and not view.visible, "ToolView.clear restores the scene")
    preview.register()
    check(preview.COMMAND_NAME in Gui.listCommands(), "preview command registered")
    window = preview.PreviewWindow(clips)
    window.show()
    window._list.setCurrentRow(1)
    check(window._slider.maximum() == len(clips[1]) - 1, "player slider spans the transition")
    window._slider.setValue(10)
    check("Transición" in window._status.text() and window._view.visible, "player shows the tool")
    window._toggle()
    window._tick()
    check(window._slider.value() == 11, "play advances one sample")
    window._toggle()
    window._find_collision()
    check("sin colisiones" in window._status.text(), "collision search reports clean clip")
    window.close()
    check(not window._view.visible, "closing the player clears the 3D view")
    program.move(op3.Name, 0)
    check(program.steps()[0].operation == op3.Name, "program can be reordered")

    # renaming propagates to the local model and the operations
    from IndexedCAM.Commands import rename_setup

    rename_setup.register()
    check(rename_setup.COMMAND_NAME in Gui.listCommands(), "rename command registered")
    ops_before = [o.Name for o in bridge.operations_of("Lateral X")]
    renamed = rename_setup.RenameSetupWorkflow(
        manager, bridge, lambda setups, err: ("Lateral X", "Cara Lateral"),
        lambda: DocumentTransaction(doc, "Rename indexed setup"), program,
    ).run()
    check({s.setup for s in program.steps()} == {"Cara Lateral", "Superior"},
          "program follows the Setup rename")
    check(renamed.name == "Cara Lateral" and "Lateral X" not in manager, "Setup renamed")
    model = local_model.find(job, "Cara Lateral")
    check(model is not None and local_model.find(job, "Lateral X") is None, "local model follows")
    check(model.Label == "IndexedCAM_Local_Cara Lateral", "local model label updated")
    check([o.Name for o in bridge.operations_of("Cara Lateral")] == ops_before,
          "operations follow the new name")
    check(op1.Base[0][0] is model and len(op1.Path.Commands) > 0, "operation still bound and valid")
    check(manager.get("Cara Lateral").operations == ops_before, "Setup.operations unchanged")

    path = os.path.join(tempfile.gettempdir(), "assign_check.FCStd")
    doc.saveAs(path)
    check(os.path.getsize(path) < 150000, "file size small: %d bytes" % os.path.getsize(path))
    App.closeDocument(doc.Name)
    reopened = App.openDocument(path)
    rjob = find_jobs(reopened)[0]
    rctx = build_context(reopened, rjob)
    check("Cara Lateral" in rctx.manager, "renamed orientation survives save/reload")
    check(orientations_group(rjob) is not None, "Orientations group survives reload inside the Job")
    check(local_model.find(rjob, "Cara Lateral") is not None, "local model survives reload")
    check(len(rctx.program) == 3, "program survives reload")
    check(len(rctx.bridge.operations_of("Cara Lateral")) == 2,
          "operations keep the new name after reload")

    # a second Job in the same document keeps its own, independent orientations
    other = reopened.getObject("Box")
    reopened.recompute()
    job2 = Gui_Job.Create([other], openTaskPanel=False)
    check(len(find_jobs(reopened)) == 2, "document can hold several Jobs")
    ctx2 = build_context(reopened, job2)
    check(ctx2.manager.names() == [], "a new Job starts without orientations")
    ctx2.manager.add(IndexedSetup(name="Otro", normal=(0, 0, 1), b=0, c=0,
                                  metadata={"source": "Box.Face6"}))
    check(rctx.manager.names() == ["Cara Lateral", "Superior"], "orientations belong to their Job")
    check(resolve_job(reopened, [other], lambda jobs: jobs[-1]) is job2,
          "ambiguous selection asks which Job")
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
Gui.getMainWindow().close()
