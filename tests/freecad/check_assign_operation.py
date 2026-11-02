"""FreeCAD end-to-end check for #13 (Assign Operation).

Uses the real selection, Face Orientation workflow pieces, the CAM bridge and the
native CAM operation panel. Run headless with the AppImage:
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
    from IndexedCAM.Commands import assign_operation, face_orientation
    from IndexedCAM.Commands.transaction import DocumentTransaction
    from IndexedCAM.Core import local_model
    from IndexedCAM.Core.cam_bridge import CamBridge
    from IndexedCAM.Core.document_storage import DocumentStorage
    from IndexedCAM.Core.face_orientation import FaceOrientationService
    from IndexedCAM.Core.operation_assignment import (
        OPERATION_TYPES,
        AssignmentError,
        AssignOperationWorkflow,
        Choice,
    )
    from IndexedCAM.Core.setup_manager import SetupManager

    face_orientation.register()
    assign_operation.register()
    check(assign_operation.COMMAND_NAME in Gui.listCommands(), "command registered")

    doc = App.newDocument("Assign")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 60, 40, 30
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)

    from IndexedCAM.Commands import program as program_command
    from IndexedCAM.Core.document_storage import ProgramDocumentStorage
    from IndexedCAM.Core.program import Program, Step

    manager = SetupManager(DocumentStorage(doc))
    bridge = CamBridge(doc)
    program = Program(ProgramDocumentStorage(doc))

    def make_setup(face, name):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, "Box", face)
        workflow = face_orientation.FaceOrientationWorkflow(
            FaceOrientationService(), manager, face_orientation._shared_triad(),
            lambda orientation, default: name,
            lambda: DocumentTransaction(doc, "Create indexed setup"),
        )
        return workflow.run(Gui.Selection.getSelectionEx())

    side = make_setup("Face2", "Lateral X")
    top = make_setup("Face6", "Superior")
    check(side.metadata["source"] == "Box.Face2", "setup remembers its source face")

    def assign(setup_name, key):
        op_type = next(t for t in OPERATION_TYPES if t.key == key)
        workflow = AssignOperationWorkflow(
            manager, bridge, assign_operation.CamOperationLauncher(doc),
            lambda setups, types: Choice(setup_name, op_type), doc.getObject,
            lambda: DocumentTransaction(doc, "Prepare indexed setup for CAM"),
            program=program,
        )
        return workflow.run()

    first = assign("Lateral X", "MillFace")
    check(first is not None and first.operation is not None, "operation created for Lateral X")
    check(Gui.Control.activeDialog(), "native CAM panel is open")
    op1 = first.operation
    model = local_model.find(doc, "Lateral X")
    check(op1.IndexedSetup == "Lateral X", "operation is bound to its Setup")
    check(op1.Base[0][0] is model and op1.Base[0][1] == ("Face2",), "Base = Face2 of the local model")
    op1.ViewObject.Proxy.panel.accept()
    doc.recompute()
    check(op1.Name in [o.Name for o in doc.Objects], "operation survives accepting the panel")
    check(abs(model.Shape.Faces[1].CenterOfMass.z) < 1e-6, "setup face is at local Z=0")
    check(max(zs(op1)) == 10.0 and len(op1.Path.Commands) < 100, "facing path: clearance Z=10, short")
    check(len(manager.get("Lateral X").operations) == 1, "Setup.operations updated")

    second = assign("Superior", "PocketShape")
    second.operation.ViewObject.Proxy.panel.accept()
    doc.recompute()
    job = bridge.find_job()
    check(len([o for o in doc.Objects if hasattr(o, "IndexedCAMJob")]) == 1, "one Job only")
    check([o.Name for o in job.Operations.Group] == [op1.Name, second.operation.Name],
          "both operations chained in the same Job, in order")
    check(sorted(m.Name for m in job.Model.Group if m.Name.startswith("IndexedCAM_Local_")) ==
          ["IndexedCAM_Local_Lateral X".replace(" ", "_"), "IndexedCAM_Local_Superior"],
          "one light local model per Setup")

    third = assign("Lateral X", "Profile")
    third.operation.ViewObject.Proxy.panel.accept()
    check(len(bridge.operations_of(job, "Lateral X")) == 2, "several operations for one Setup")

    # cancelling the panel removes the operation and the Setup list follows
    fourth = assign("Superior", "MillFace")
    name4 = fourth.operation.Name
    fourth.operation.ViewObject.Proxy.panel.reject()
    doc.recompute()
    check(doc.getObject(name4) is None, "cancelling the panel deletes the operation")
    assign_operation_wf = AssignOperationWorkflow(
        manager, bridge, assign_operation.CamOperationLauncher(doc),
        lambda s, t: None, doc.getObject, program=program)
    assign_operation_wf.run()
    check(len(manager.get("Superior").operations) == 1, "cancelled operation pruned from Setup")

    check([(s.setup, s.operation) for s in program.steps()] ==
          [("Lateral X", op1.Name), ("Superior", second.operation.Name),
           ("Lateral X", third.operation.Name)],
          "program holds the surviving steps in creation order")
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
    program.move(third.operation.Name, 0)
    check(program.steps()[0].operation == third.operation.Name, "program can be reordered")

    # renaming propagates to the local model and the operations
    from IndexedCAM.Commands import rename_setup

    rename_setup.register()
    check(rename_setup.COMMAND_NAME in Gui.listCommands(), "rename command registered")
    ops_before = [o.Name for o in bridge.operations_of(job, "Lateral X")]
    renamed = rename_setup.RenameSetupWorkflow(
        manager, bridge, lambda setups, err: ("Lateral X", "Cara Lateral"),
        lambda: DocumentTransaction(doc, "Rename indexed setup"), program,
    ).run()
    check({s.setup for s in program.steps()} == {"Cara Lateral", "Superior"},
          "program follows the Setup rename")
    check(renamed.name == "Cara Lateral" and "Lateral X" not in manager, "Setup renamed")
    model = local_model.find(doc, "Cara Lateral")
    check(model is not None and local_model.find(doc, "Lateral X") is None, "local model follows")
    check(model.Label == "IndexedCAM_Local_Cara Lateral", "local model label updated")
    check([o.Name for o in bridge.operations_of(job, "Cara Lateral")] == ops_before,
          "operations follow the new name")
    check(op1.Base[0][0] is model and len(op1.Path.Commands) > 0, "operation still bound and valid")
    check(manager.get("Cara Lateral").operations == ops_before, "Setup.operations unchanged")

    path = os.path.join(tempfile.gettempdir(), "assign_check.FCStd")
    doc.saveAs(path)
    check(os.path.getsize(path) < 150000, "file size small: %d bytes" % os.path.getsize(path))
    App.closeDocument(doc.Name)
    reopened = App.openDocument(path)
    reopened_manager = SetupManager(DocumentStorage(reopened))
    check("Cara Lateral" in reopened_manager, "renamed Setup survives save/reload")
    check(local_model.find(reopened, "Cara Lateral") is not None, "local model survives reload")
    check(len(Program(ProgramDocumentStorage(reopened))) == 3, "program survives reload")
    check(len(CamBridge(reopened).operations_of(CamBridge(reopened).find_job(), "Cara Lateral")) == 2,
          "operations keep the new name after reload")
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
Gui.getMainWindow().close()
