"""Safety distance used to retract and index the head (no FreeCAD needed).

The tool tip retracts onto a sphere around the part whose radius is the part's
half-diagonal: the head turns with the tool pointing radially outward, so the
shank, the holder and the head are always further from the centre than the tip
and nothing else has to be added. ``margin`` is extra clearance on top of that
radius and defaults to zero, the smallest sphere that works: retracts that are
too high are the most common reason a posted program does not fit the machine's
Z travel.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict

from IndexedCAM.Core.document_storage import JobSettingStorage as _JobSettingStorage

MINIMUM_MARGIN = 0.0
MAXIMUM_MARGIN = 500.0
PROPERTY_NAME = "IndexedCAMSafety"


@dataclass(frozen=True)
class SafetyConfig:
    """Retract clearance and which parts of the machine are modelled.

    ``holder`` and ``head`` default to False: only the tool is considered, both
    when checking collisions and when drawing. A collet holder is much slimmer
    than the stand-in cylinder, so modelling it made the retracts long for no
    reason; turn them on to check against the real (bulkier) hardware.
    """

    margin: float = MINIMUM_MARGIN
    holder: bool = False
    head: bool = False

    def __post_init__(self) -> None:
        value = float(self.margin)
        if not math.isfinite(value):
            raise ValueError("el margen de seguridad debe ser un numero finito")
        if value < MINIMUM_MARGIN:
            raise ValueError("el margen de seguridad no puede ser negativo")
        if value > MAXIMUM_MARGIN:
            raise ValueError(
                "el margen de seguridad no puede pasar de {:g} mm".format(MAXIMUM_MARGIN)
            )
        object.__setattr__(self, "margin", value)

    @property
    def is_minimum(self) -> bool:
        return self.margin == MINIMUM_MARGIN

    def describe(self) -> str:
        parts = [
            "Distancia de seguridad: la mínima (0 mm)"
            if self.is_minimum
            else "Distancia de seguridad: {:g} mm".format(self.margin)
        ]
        accessories = [name for name, on in (("portaherramientas", self.holder), ("cabezal", self.head)) if on]
        parts.append("modela " + " y ".join(accessories) if accessories else "solo la herramienta")
        return " · ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {"margin": self.margin, "holder": self.holder, "head": self.head}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SafetyConfig":
        return cls(
            float(data.get("margin", MINIMUM_MARGIN)),
            bool(data.get("holder", False)),
            bool(data.get("head", False)),
        )


class MemorySafetyStorage:
    """In-memory storage, for tests."""

    def __init__(self, config: SafetyConfig = SafetyConfig()) -> None:
        self._config = config

    def load(self) -> SafetyConfig:
        return self._config

    def save(self, config: SafetyConfig) -> None:
        self._config = config


class JobSafetyStorage(_JobSettingStorage):
    """Safety config stored on the Job (hidden JSON property)."""

    property_name = PROPERTY_NAME
    tooltip = "Safety distance of the head"

    def load(self) -> SafetyConfig:
        raw = self._raw()
        if not raw:
            return SafetyConfig()
        try:
            return SafetyConfig.from_dict(json.loads(raw))
        except (ValueError, TypeError, AttributeError):
            return SafetyConfig()

    def save(self, config: SafetyConfig) -> None:
        self._store(config.to_dict())
