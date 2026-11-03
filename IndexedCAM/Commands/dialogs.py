"""Qt dialogs shared by the commands (Job choice, operation checklist)."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

DIALOG_TITLE = "IndexedCAM"


def choose_job(jobs: Sequence[Any]) -> Optional[Any]:
    """Ask which Job to use when several fit."""
    import FreeCADGui as Gui
    from PySide import QtWidgets

    labels = [job.Label for job in jobs]
    label, accepted = QtWidgets.QInputDialog.getItem(
        Gui.getMainWindow(), DIALOG_TITLE, "Job de CAM:", labels, 0, False
    )
    return jobs[labels.index(label)] if accepted else None


def operation_label(operation: Any) -> str:
    owner = getattr(operation, "IndexedSetup", "")
    return "{}{}".format(operation.Label, "   → {}".format(owner) if owner else "")


def _checklist(operations: Sequence[Any], checked: Sequence[Any]) -> Any:
    from PySide import QtCore, QtWidgets

    listing = QtWidgets.QListWidget()
    for operation in operations:
        item = QtWidgets.QListWidgetItem(operation_label(operation))
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(
            QtCore.Qt.Checked if operation in checked else QtCore.Qt.Unchecked
        )
        listing.addItem(item)
    return listing


def _checked(listing: Any, operations: Sequence[Any]) -> List[Any]:
    from PySide import QtCore

    return [
        operations[row]
        for row in range(listing.count())
        if listing.item(row).checkState() == QtCore.Qt.Checked
    ]


def choose_operations(
    title: str, message: str, operations: Sequence[Any], checked: Sequence[Any] = ()
) -> Optional[List[Any]]:
    """Checklist of Job operations; None when cancelled."""
    import FreeCADGui as Gui
    from PySide import QtWidgets

    dialog = QtWidgets.QDialog(Gui.getMainWindow())
    dialog.setWindowTitle(title)
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(QtWidgets.QLabel(message))
    listing = _checklist(operations, checked)
    layout.addWidget(listing)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if not dialog.exec_():
        return None
    return _checked(listing, operations)


def choose_setup_and_operations(
    title: str, setups: Sequence[Any], operations: Sequence[Any]
) -> Optional[Tuple[str, List[Any]]]:
    """Pick a Setup and tick the operations to orient to it."""
    import FreeCADGui as Gui
    from PySide import QtWidgets

    dialog = QtWidgets.QDialog(Gui.getMainWindow())
    dialog.setWindowTitle(title)
    layout = QtWidgets.QVBoxLayout(dialog)
    setup_box = QtWidgets.QComboBox()
    for setup in setups:
        setup_box.addItem(
            "{}  (B={:.2f}, C={:.2f})".format(setup.name, setup.b, setup.c), setup.name
        )
    setup_box.setCurrentIndex(setup_box.count() - 1)
    layout.addWidget(QtWidgets.QLabel("Setup:"))
    layout.addWidget(setup_box)
    layout.addWidget(QtWidgets.QLabel("Operaciones que se realizarán orientadas a él:"))
    listing = _checklist(operations, ())

    def preselect(*_: Any) -> None:
        from PySide import QtCore

        name = setup_box.currentData()
        for row, operation in enumerate(operations):
            listing.item(row).setCheckState(
                QtCore.Qt.Checked
                if getattr(operation, "IndexedSetup", "") == name
                else QtCore.Qt.Unchecked
            )

    setup_box.currentIndexChanged.connect(preselect)
    preselect()
    layout.addWidget(listing)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if not dialog.exec_():
        return None
    return setup_box.currentData(), _checked(listing, operations)
