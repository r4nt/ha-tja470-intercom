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


@pytest.fixture(autouse=True)
def mock_sip_phone():
    """Mock TJA470SipPhone to avoid starting a real SIP socket client in tests."""
    from unittest.mock import MagicMock, AsyncMock
    mock_phone = MagicMock()
    mock_phone.start = AsyncMock()
    mock_phone.stop = AsyncMock()
    
    from pyVoIP.VoIP.status import PhoneStatus
    mock_phone.get_status = MagicMock(return_value=PhoneStatus.INACTIVE)
    
    with patch("custom_components.tja470_intercom.TJA470SipPhone", return_value=mock_phone):
        yield mock_phone


