"""FreeCAD end-to-end check of the orientation flow (Face Orientation + Assign Operation).

The operations are created natively by CAM in any Job; IndexedCAM gives each
Setup its own CAM Job (model and stock in that Setup's frame), moves the
operations into it and drives the program, preview, rename and save/reload.
Run with the AppImage (needs a display):
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
    from IndexedCAM.Core.face_orientation import FaceOrientationService
    from IndexedCAM.Core.job_context import find_jobs
    from IndexedCAM.Core.operation_assignment import AssignmentError, AssignOperationWorkflow

    from IndexedCAM.Gui import restore_observer

    restore_observer.install()
    face_orientation.register()
    assign_operation.register()
    check(assign_operation.COMMAND_NAME in Gui.listCommands(), "command registered")

    doc = App.newDocument("Assign")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 60, 40, 30
    box.Placement = App.Placement(App.Vector(10, 20, 30), App.Rotation())
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)

    ctx = build_context(doc)
    manager, bridge, program = ctx.manager, ctx.bridge, ctx.program
    check(manager.names() == [] and bridge.jobs.jobs() == [], "a new document has no orientations")
    check(find_jobs(doc) == [], "IndexedCAM creates no Job until a Setup needs one")

    # the user creates a Job (and its operations) with the native CAM workbench
    job = Gui_Job.Create([box], openTaskPanel=False)
    clone = job.Model.Group[0]
    op1 = MillFace.Create("Facing", parentJob=job)
    op2 = PocketShape.Create("Pocket", parentJob=job)
    op3 = Profile.Create("Contour", parentJob=job)
    for op in (op1, op3):
        op.Base = [(clone, ["Face6"])]
    op2.Base = []  # a Pocket created without choosing faces
    doc.recompute()
    check([o.Name for o in job.Operations.Group] == [op1.Name, op2.Name, op3.Name],
          "the user Job chains its operations")

    def make_setup(face, name, operations, owner=None):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, owner or clone.Name, face)
        workflow = face_orientation.FaceOrientationWorkflow(
            FaceOrientationService(), manager, face_orientation._shared_triad(),
            lambda orientation, default: name,
            lambda: DocumentTransaction(doc, "Create indexed setup"),
            lambda setup: ctx.assigner.assign(setup.name, operations),
        )
        return workflow.run(Gui.Selection.getSelectionEx())

    side = make_setup("Face2", "Lateral X", [op1, op3])
    check(side.metadata["source"] == "%s.Face2" % clone.Name, "setup remembers its source face")
    jobs = bridge.jobs.jobs()
    check(len(jobs) == 1, "the Setup gets its own CAM Job: %s" % [j.Label for j in jobs])
    lateral_job = jobs[0]
    check(lateral_job.InList == [], "the Job is a root object, like a CAM Job")
    check(doc.getObject("IndexedCAM") is None, "no extra container object in the document")
    check(lateral_job.Label == "Lateral X B90.0 C0.0", "the Job shows the orientation: %s" % lateral_job.Label)
    model = bridge.jobs.model("Lateral X")
    check(abs(bridge.jobs.setup_of(lateral_job).b - 90.0) < 1e-6, "the Job stores its Setup")
    check(abs(model.Shape.BoundBox.ZMax) < 1e-6, "the Job model has the face at local Z=0")
    check(abs(lateral_job.Stock.Shape.BoundBox.ZMax - 1.0) < 1e-6,
          "the Job stock follows its own model: %s" % lateral_job.Stock.Shape.BoundBox)

    # el arbol: todo dentro del Job, como un Job creado desde CAM
    from IndexedCAM.Gui.job_view import OrientationJobViewProvider

    proxy = lateral_job.ViewObject.Proxy
    check(isinstance(proxy, OrientationJobViewProvider),
          "the Job gets CAM's Job view provider: %s" % type(proxy).__name__)
    claimed = [o.Name for o in proxy.claimChildren()]
    log("     claimed:", claimed)
    check(
        all(
            group.Name in claimed
            for group in (
                lateral_job.Operations,
                lateral_job.Model,
                lateral_job.Stock,
                lateral_job.SetupSheet,
                lateral_job.Tools,
            )
        ),
        "Operations, Model, Stock, SetupSheet and Tools are nested inside the Job",
    )
    check(
        bridge.jobs.local_model("Lateral X").Name in claimed,
        "the local model is nested inside its Job too",
    )
    check([o.Name for o in bridge.operations_of("Lateral X")] == [op1.Name, op3.Name],
          "chosen operations moved into the Job")
    check(bridge.setup_of(op1) == "Lateral X", "the owning Job identifies the Setup")
    check(op1.Base[0][0] is model and op1.Base[0][1] == ("Face6",),
          "Base re-pointed to the Job model, same face")
    check([o.Name for o in job.Operations.Group] == [op2.Name],
          "the user Job only keeps what was not assigned")
    check(op1.ToolController in list(lateral_job.Tools.Group), "the tool moves with the operation")
    check(len(manager.get("Lateral X").operations) == 2, "Setup.operations updated")

    top = make_setup("Face6", "Superior", [])
    check(bridge.jobs.find("Superior") is not None and top.operations == [],
          "an orientation without operations still gets its Job")
    ctx.assigner.assign("Superior", [op2])
    superior_model = bridge.jobs.model("Superior")
    check(op2.Base and op2.Base[0][0] is superior_model and op2.Base[0][1] == ("Face6",),
          "operation without Base gets the Setup's own face")
    check(len(op2.Path.Commands) > 2, "operation without Base now has a real path")
    check(len(bridge.jobs.jobs()) == 2, "one Job per orientation")

    face6 = clone.Shape.getElement("Face6")
    placed = [
        op2.Placement.multVec(App.Vector(c.Parameters.get("X", 0), c.Parameters.get("Y", 0), c.Parameters["Z"]))
        for c in op2.Path.Commands
        if "Z" in c.Parameters
    ]
    top_z = clone.Shape.BoundBox.ZMax
    check(all(p.z >= top_z - 1e-6 for p in placed) and any(abs(p.z - top_z) < 1e-6 for p in placed),
          "placed path lies on the face it machines, above the part")
    lat = op1.Placement.multVec(App.Vector(0, 0, 10))
    check(abs(lat.x - (clone.Shape.BoundBox.XMax + 10)) < 1e-6,
          "lateral operation is drawn out of the X face, tool pointing +X")
    check(abs(float(op2.StartDepth.Value) - superior_model.Shape.BoundBox.ZMax) < 1e-6,
          "heights follow the Job model: %s" % op2.StartDepth)

    try:
        AssignOperationWorkflow(manager, bridge, ctx.assigner, lambda s, o: None).run()
    except AssignmentError:
        check(False, "assign with setups and operations must not fail")
    wf = AssignOperationWorkflow(manager, bridge, ctx.assigner, lambda s, o: ("Superior", [o[0]]))
    reassigned = wf.run()
    check(reassigned.setup.name == "Superior" and bridge.setup_of(op1) == "Superior",
          "Assign Operation re-orients an existing operation")
    check(op1 in list(bridge.jobs.find("Superior").Operations.Group)
          and op1 not in list(lateral_job.Operations.Group),
          "the operation moved to the other Job")
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
          "steps follow the Job order")
    program.move(op2.Name, 1)
    check([(s.setup, s.operation) for s in program.steps()] ==
          [("Lateral X", op1.Name), ("Superior", op2.Name), ("Lateral X", op3.Name)],
          "user can reorder the program")
    from IndexedCAM.Commands import program as program_command

    items = program_command.resolve_program(program, manager, bridge, doc)
    check(items[0].previous is None and items[1].needs_transition and items[2].needs_transition,
          "transitions required between different Setups")
    check(items[0].end is not None and items[1].start.b == manager.get("Superior").b,
          "step poses use the Setup angles")
    log("start", items[0].start, "end", items[0].end)
    check(70.0 < items[0].start.point[0] <= 80.5 and items[0].start.b == 90.0,
          "step start lies above the X=70 face (part placed at x=10), in part coordinates")
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
    check(kinds == ["operation", "transition", "operation", "transition", "operation", "parking"],
          "preview clips (incluye el fin vertical): %s" % kinds)
    parking = clips[-1]
    check(parking.frames[-1].b == 0.0 and parking.frames[-1].c == 0.0,
          "el clip final termina con el cabezal vertical")
    check(all(c.error is None for c in clips if c.kind == "transition"),
          "transitions are collision-free: %s" % [c.error for c in clips])
    check(all(len(c) > 0 for c in clips), "every clip has samples")
    check(all("Ø" in c.tool for c in clips), "every clip names its tool: %s" % [c.tool for c in clips][:1])
    check(all(c.tool_mesh and len(c.tool_mesh[1]) > 0 for c in clips), "every clip carries the real tool shape")
    from IndexedCAM.Core.stock_timeline import StockTimeline
    import time as _time

    stock = preview.stock_for_program(doc, bridge)
    check(stock is not None and stock.cells.size > 1000, "voxel stock built for the program: %s" % (stock.cells.shape,))
    full_volume = stock.volume()
    timeline = StockTimeline(stock, clips)
    started = _time.time()
    timeline.final()
    log("stock timeline final in %.2fs, removed %.1f mm3" % (_time.time() - started, full_volume - stock.volume()))
    check(stock.volume() < full_volume, "program removes material from the stock")
    timeline.show(0, 0)
    check(abs(stock.volume() - full_volume) < full_volume * 0.05, "scrubbing back restores the stock")
    from IndexedCAM.Gui.tool_view import build_stock_node

    node = build_stock_node(stock.triangles())
    check(node.getNumChildren() == 4, "stock node has material, hints, points and faces")
    from PySide import QtCore

    window = preview.PreviewWindow(clips, preview.stock_for_program(doc, bridge), bridge.stocks())
    window.show()
    check(len(window._playlist) == sum(len(c) for c in clips),
          "todas las entradas marcadas se reproducen de una vez: %d" % len(window._playlist))
    window._tick_all(False)
    check(len(window._playlist) == 0, "sin nada marcado no hay reproduccion")
    for row in (0, 2):
        window._list.item(row).setCheckState(QtCore.Qt.Checked)
    check(window._playlist.clips() == [0, 2],
          "solo se reproducen las marcadas: %s" % window._playlist.clips())
    window._slider.setValue(window._slider.maximum())
    check(window._clip_index == 2, "el deslizador recorre hasta la ultima marcada")
    window._tick_all(True)
    window._slider.setValue(window._slider.maximum())
    check(window._view._stock is not None, "preview window shows the stock")
    window.close()
    check(window._view._stock is None, "closing the preview removes the stock")
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
    check(window._slider.maximum() == len(window._playlist) - 1,
          "el deslizador recorre toda la seleccion: %d" % window._slider.maximum())
    check(window._slider.value() == window._playlist.first_in(1),
          "al elegir una entrada el deslizador va a su primer fotograma")
    start = window._playlist.first_in(1)
    window._slider.setValue(start + 10)
    check("Transición" in window._status.text() and window._view.visible,
          "player shows the transition: %s" % window._status.text()[:60])
    window._toggle()
    window._tick()
    check(window._slider.value() == start + 11, "play advances one sample")
    window._toggle()
    window._find_collision()
    check("sin colisiones" in window._status.text(),
          "collision search reports clean selection: %s" % window._status.text())
    window.close()
    check(not window._view.visible, "closing the player clears the 3D view")

    # renaming propagates to the Job, its local model and the operations
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
    check(bridge.jobs.find("Cara Lateral") is not None and bridge.jobs.find("Lateral X") is None,
          "the Job follows the rename")
    model = local_model.find(doc, "Cara Lateral")
    check(model is not None and model.Label == "IndexedCAM_Local_Cara Lateral",
          "local model label updated")
    check([o.Name for o in bridge.operations_of("Cara Lateral")] == ops_before,
          "operations follow the new name")
    check(op1.Base[0][0] is bridge.jobs.model("Cara Lateral") and len(op1.Path.Commands) > 0,
          "operation still bound and valid")
    check(manager.get("Cara Lateral").operations == ops_before, "Setup.operations unchanged")

    path = os.path.join(tempfile.gettempdir(), "assign_check.FCStd")
    doc.saveAs(path)
    check(os.path.getsize(path) < 400000, "file size: %d bytes" % os.path.getsize(path))
    App.closeDocument(doc.Name)
    reopened = App.openDocument(path)
    reopened.recompute()
    rctx = build_context(reopened)
    check("Cara Lateral" in rctx.manager, "renamed orientation survives save/reload")
    check(len(rctx.bridge.jobs.jobs()) == 2, "the two Jobs survive reload")
    reloaded = local_model.find(reopened, "Cara Lateral")
    check(reloaded is not None, "local model survives reload")
    log("     visibilidad:", [(o.Name, o.Visibility) for o in reopened.Objects
                             if hasattr(o, "LocalPlacement") or hasattr(o, "IndexedCAMSetup")])
    check(all(not o.Visibility for o in reopened.Objects if hasattr(o, "LocalPlacement")),
          "local models stay hidden after reopening")
    check(len([o for o in reopened.Objects if hasattr(o, "LocalPlacement")])
          == len(rctx.manager.list()), "one local model per orientation after reload")
    check(len(rctx.program) == 3, "program survives reload")
    check(len(rctx.bridge.operations_of("Cara Lateral")) == 2,
          "operations keep the new name after reload")
    check(abs(rctx.bridge.jobs.model("Cara Lateral").Shape.BoundBox.ZMax) < 1e-6,
          "the Job model is still in the local frame after reload")
    rjob = rctx.bridge.jobs.find("Cara Lateral")
    check(isinstance(rjob.ViewObject.Proxy, OrientationJobViewProvider),
          "the Job view provider survives the reload")
    rclaimed = [o.Name for o in rjob.ViewObject.Proxy.claimChildren()]
    check(
        reloaded.Name in rclaimed and rjob.Operations.Name in rclaimed,
        "the tree is still nested after reload: %s" % rclaimed,
    )
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
    finish(False)
finish(True)
