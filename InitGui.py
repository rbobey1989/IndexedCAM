"""FreeCAD GUI entry point for the IndexedCAM workbench."""

import FreeCADGui as Gui


class IndexedCAMWorkbench(Gui.Workbench):
    """Workbench entry point registered with FreeCAD."""

    MenuText = "IndexedCAM"
    ToolTip = "Indexed 3+2 machining workbench"

    def __init__(self):
        # FreeCAD execs this file with separate globals/locals: import here.
        from IndexedCAM.Gui.resources import icon_path

        self.__class__.Icon = icon_path("indexedcam.svg")

    def Initialize(self):
        from IndexedCAM.Commands import assign_operation, face_orientation, preview, program, rename_setup

        from IndexedCAM.Gui import native_simulator

        native_simulator.install()
        face_orientation.register()
        assign_operation.register()
        rename_setup.register()
        program.register()
        preview.register()
        commands = [
            face_orientation.COMMAND_NAME,
            assign_operation.COMMAND_NAME,
            rename_setup.COMMAND_NAME,
            program.COMMAND_NAME,
            preview.COMMAND_NAME,
        ]
        self.appendToolbar("IndexedCAM", commands)
        self.appendMenu("IndexedCAM", commands)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(IndexedCAMWorkbench())
