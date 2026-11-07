"""Post processor options, stored in the Job (no FreeCAD needed).

Everything that depends on the machine and the controller rather than on the
geometry: the sense and zero of B and C, units, formatting, tool length mode,
coolant, feeds. They are saved inside the .FCStd so the same Job is posted the
same way next time, and they are edited in the dialog the Postprocesar command
opens.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

from IndexedCAM.Post.linuxcnc import AxisSigns, LinuxCNCConfig

PROPERTY_NAME = "IndexedCAMPOST"


@dataclass(frozen=True)
class PostSettings:
    """``LinuxCNCConfig`` plus the description printed in the header."""

    config: LinuxCNCConfig = LinuxCNCConfig()
    name: str = ""

    @property
    def signs(self) -> AxisSigns:
        return self.config.signs

    def describe(self) -> str:
        return "{} · {} · {} · {}".format(
            self.config.units, self.config.tool_length, self.config.signs.describe(), self.name or "programa"
        )

    def to_dict(self) -> Dict[str, Any]:
        config = self.config
        signs = config.signs
        return {
            "name": self.name,
            "units": config.units,
            "decimals": config.decimals,
            "feed_decimals": config.feed_decimals,
            "line_numbers": config.line_numbers,
            "line_start": config.line_start,
            "line_step": config.line_step,
            "tool_length": config.tool_length,
            "coolant": config.coolant,
            "stop_spindle_between": config.stop_spindle_between,
            "default_feed": config.default_feed,
            "header": list(config.header),
            "signs": {
                "b_sign": signs.b_sign,
                "c_sign": signs.c_sign,
                "b_zero": signs.b_zero,
                "c_zero": signs.c_zero,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostSettings":
        if not data:
            return cls()
        signs = data.get("signs") or {}
        config = LinuxCNCConfig(
            units=data.get("units", "mm"),
            decimals=int(data.get("decimals", 3)),
            feed_decimals=int(data.get("feed_decimals", 1)),
            line_numbers=bool(data.get("line_numbers", False)),
            line_start=int(data.get("line_start", 10)),
            line_step=int(data.get("line_step", 10)),
            tool_length=data.get("tool_length", "G43.4"),
            coolant=bool(data.get("coolant", True)),
            stop_spindle_between=bool(data.get("stop_spindle_between", True)),
            default_feed=float(data.get("default_feed", 300.0)),
            header=tuple(data.get("header", ())),
            signs=AxisSigns(
                b_sign=float(signs.get("b_sign", 1.0)),
                c_sign=float(signs.get("c_sign", 1.0)),
                b_zero=float(signs.get("b_zero", 0.0)),
                c_zero=float(signs.get("c_zero", 0.0)),
            ),
        )
        return cls(config=config, name=str(data.get("name", "")))


class MemoryPostStorage:
    """In-memory storage, for tests."""

    def __init__(self, settings: PostSettings = PostSettings()) -> None:
        self._settings = settings

    def load(self) -> PostSettings:
        return self._settings

    def save(self, settings: PostSettings) -> None:
        self._settings = settings


class JobPostStorage:
    """Post settings stored on the ``Orientations`` group of the Job."""

    def __init__(self, job: Any) -> None:
        self._job = job

    def load(self) -> PostSettings:
        from IndexedCAM.Core.document_storage import orientations_group

        group = orientations_group(self._job)
        raw = getattr(group, PROPERTY_NAME, "") if group is not None else ""
        if not raw:
            return PostSettings()
        try:
            return PostSettings.from_dict(json.loads(raw))
        except (ValueError, TypeError, AttributeError):
            return PostSettings()

    def save(self, settings: PostSettings) -> None:
        from IndexedCAM.Core.document_storage import ensure_orientations_group, orientations_group

        group = orientations_group(self._job)
        if group is None:
            group = ensure_orientations_group(self._job)
        if not hasattr(group, PROPERTY_NAME):
            group.addProperty(
                "App::PropertyString", PROPERTY_NAME, "IndexedCAM", "Post processor options"
            )
            group.setEditorMode(PROPERTY_NAME, 2)
        setattr(group, PROPERTY_NAME, json.dumps(settings.to_dict()))
