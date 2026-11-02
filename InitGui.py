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
        from IndexedCAM.Commands import face_orientation

        face_orientation.register()
        commands = [face_orientation.COMMAND_NAME]
        self.appendToolbar("IndexedCAM", commands)
        self.appendMenu("IndexedCAM", commands)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(IndexedCAMWorkbench())
