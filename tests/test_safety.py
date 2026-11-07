import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.preview import sphere_for  # noqa: E402
from IndexedCAM.Commands.safety import SafetyWorkflow  # noqa: E402
from IndexedCAM.Core.safety import (  # noqa: E402
    MAXIMUM_MARGIN,
    MINIMUM_MARGIN,
    MemorySafetyStorage,
    SafetyConfig,
)
from IndexedCAM.Machine.envelope import Envelope  # noqa: E402

BOX = ((0.0, 0.0, 0.0), (60.0, 40.0, 30.0))


def test_the_default_is_the_smallest_retract():
    config = SafetyConfig()
    assert config.margin == MINIMUM_MARGIN == 0.0
    assert config.is_minimum


def test_the_default_matches_the_geometric_minimum_sphere():
    """Sin margen, la esfera es media diagonal + herramienta + portaherramientas."""
    envelope = Envelope()
    sphere = sphere_for(BOX, envelope, SafetyConfig().margin)
    half_diagonal = (60.0**2 + 40.0**2 + 30.0**2) ** 0.5 / 2.0
    assert sphere.radius == pytest.approx(half_diagonal + envelope.tool.length + envelope.holder.length)


def test_a_larger_margin_raises_the_sphere():
    envelope = Envelope()
    low = sphere_for(BOX, envelope, SafetyConfig(0.0).margin)
    high = sphere_for(BOX, envelope, SafetyConfig(25.0).margin)
    assert high.radius - low.radius == pytest.approx(25.0)


def test_margin_cannot_be_negative_or_huge():
    with pytest.raises(ValueError):
        SafetyConfig(-0.1)
    with pytest.raises(ValueError):
        SafetyConfig(MAXIMUM_MARGIN + 1.0)
    with pytest.raises(ValueError):
        SafetyConfig(float("nan"))
    with pytest.raises(ValueError):
        SafetyConfig(float("inf"))


def test_describe_mentions_when_it_is_the_minimum():
    assert "mínima" in SafetyConfig().describe()
    assert "25" in SafetyConfig(25.0).describe()


def test_config_round_trips_through_a_dict():
    config = SafetyConfig(12.5)
    assert SafetyConfig.from_dict(config.to_dict()) == config


def test_missing_or_broken_data_falls_back_to_the_default():
    assert SafetyConfig.from_dict({}) == SafetyConfig()
    storage = MemorySafetyStorage()
    assert storage.load() == SafetyConfig()


def test_workflow_stores_the_value_the_user_chooses():
    storage = MemorySafetyStorage()
    config = SafetyWorkflow(storage, lambda current: 15.0).run()
    assert config == SafetyConfig(15.0)
    assert storage.load() == SafetyConfig(15.0)


def test_workflow_keeps_the_current_value_when_cancelled():
    storage = MemorySafetyStorage(SafetyConfig(5.0))
    assert SafetyWorkflow(storage, lambda current: None).run() is None
    assert storage.load() == SafetyConfig(5.0)


def test_workflow_does_not_write_when_nothing_changed():
    saved = []
    storage = MemorySafetyStorage(SafetyConfig(5.0))
    storage.save = lambda config: saved.append(config)
    SafetyWorkflow(storage, lambda current: 5.0).run()
    assert saved == []


def test_workflow_rejects_an_invalid_value():
    storage = MemorySafetyStorage()
    with pytest.raises(ValueError):
        SafetyWorkflow(storage, lambda current: -3.0).run()


def test_short_retract_keeps_the_head_inside_a_small_machine():
    """El margen es lo que hacía que la retirada no cupiera en el recorrido Z."""
    envelope = Envelope()
    minimal = sphere_for(BOX, envelope, SafetyConfig().margin)
    padded = sphere_for(BOX, envelope, 10.0)
    assert minimal.radius < padded.radius
