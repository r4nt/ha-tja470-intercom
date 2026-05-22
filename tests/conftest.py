"""Fixtures for testing."""
from unittest.mock import patch
import pytest

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    yield

@pytest.fixture(autouse=True)
def mock_ffmpeg():
    """Mock ffmpeg setup to avoid needing ffmpeg binary in tests."""
    with patch("homeassistant.components.ffmpeg.async_setup", return_value=True):
        yield

