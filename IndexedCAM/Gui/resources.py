"""Locate bundled GUI resources."""

import os

_ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Resources", "icons")


def icon_path(name: str) -> str:
    """Absolute path of an icon in ``IndexedCAM/Resources/icons``."""
    return os.path.join(_ICONS, name)
