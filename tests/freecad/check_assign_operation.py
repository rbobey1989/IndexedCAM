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

    manager = SetupManager(DocumentStorage(doc))
    bridge = CamBridge(doc)

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
        lambda s, t: None, doc.getObject)
    assign_operation_wf.run()
    check(len(manager.get("Superior").operations) == 1, "cancelled operation pruned from Setup")

    # renaming propagates to the local model and the operations
    from IndexedCAM.Commands import rename_setup

    rename_setup.register()
    check(rename_setup.COMMAND_NAME in Gui.listCommands(), "rename command registered")
    ops_before = [o.Name for o in bridge.operations_of(job, "Lateral X")]
    renamed = rename_setup.RenameSetupWorkflow(
        manager, bridge, lambda setups, err: ("Lateral X", "Cara Lateral"),
        lambda: DocumentTransaction(doc, "Rename indexed setup"),
    ).run()
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
    check(len(CamBridge(reopened).operations_of(CamBridge(reopened).find_job(), "Cara Lateral")) == 2,
          "operations keep the new name after reload")
    log("PASS")
except Exception:
    log(traceback.format_exc())
    log("FAILED")
Gui.getMainWindow().close()
