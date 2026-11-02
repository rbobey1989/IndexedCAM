"""FreeCAD GUI entry point for the IndexedCAM workbench."""

import FreeCADGui as Gui


class IndexedCAMWorkbench(Gui.Workbench):
    """Workbench entry point registered with FreeCAD."""

    MenuText = "IndexedCAM"
    ToolTip = "Indexed 3+2 machining workbench"

    def Initialize(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(IndexedCAMWorkbench())
