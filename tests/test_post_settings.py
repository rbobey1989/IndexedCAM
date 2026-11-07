import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.post_settings import MemoryPostStorage, PostSettings  # noqa: E402
from IndexedCAM.Post.linuxcnc import AxisSigns, LinuxCNCConfig  # noqa: E402


def test_defaults_match_the_controller_config():
    settings = PostSettings()
    assert settings.config == LinuxCNCConfig()
    assert settings.signs == AxisSigns()
    assert settings.config.units == "mm" and settings.config.tool_length == "G43.4"


def test_every_option_survives_a_round_trip():
    settings = PostSettings(
        LinuxCNCConfig(
            units="in",
            decimals=4,
            feed_decimals=0,
            line_numbers=True,
            line_start=100,
            line_step=5,
            tool_length="G43",
            coolant=False,
            stop_spindle_between=False,
            vertical_before_tool_change=True,
            default_feed=750.0,
            header=("Job: prueba",),
            signs=AxisSigns(b_sign=-1.0, c_sign=-1.0, b_zero=10.0, c_zero=-90.0),
        ),
        name="Test000",
    )
    assert PostSettings.from_dict(settings.to_dict()) == settings


def test_empty_data_is_the_default_and_bad_data_is_rejected():
    assert PostSettings.from_dict({}) == PostSettings()
    with pytest.raises(ValueError):
        PostSettings.from_dict({"units": "furlongs"})


def test_storage_round_trip():
    storage = MemoryPostStorage()
    assert storage.load() == PostSettings()
    configured = PostSettings(LinuxCNCConfig(signs=AxisSigns(b_sign=-1.0)), "Job")
    storage.save(configured)
    assert storage.load() == configured


def test_describe_mentions_the_signs():
    text = PostSettings(LinuxCNCConfig(signs=AxisSigns(b_sign=-1.0)), "Test000").describe()
    assert "B gain -1.0" in text and "Test000" in text


def test_invalid_units_are_rejected_when_building_the_config():
    with pytest.raises(ValueError):
        LinuxCNCConfig(units="furlongs")
