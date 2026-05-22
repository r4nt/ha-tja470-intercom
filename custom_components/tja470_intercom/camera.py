"""Camera platform for Hager TJA470 Intercom."""
from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.const import CONF_HOST

from .const import DOMAIN
from . import TJA470Coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the camera platform for TJA470."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: TJA470Coordinator = data["coordinator"]

    async_add_entities([TJA470Camera(coordinator)])


class TJA470Camera(CoordinatorEntity[TJA470Coordinator], Camera):
    """Camera entity representing the TJA470 Intercom video stream."""

    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_icon = "mdi:doorbell-video"

    def __init__(self, coordinator: TJA470Coordinator) -> None:
        """Initialize camera."""
        super().__init__(coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_camera"
        self._attr_name = "Camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of camera image from RTSP stream."""
        stream_url = self.stream_source()
        if not stream_url:
            return None

        # Capture a snapshot frame from the RTSP stream using ha-ffmpeg helper
        return await async_get_image(
            self.hass,
            stream_url,
            output_format="mjpeg",
        )

    def stream_source(self) -> str | None:
        """Return the RTSP stream source."""
        prov = self.coordinator.data.get("provisioning")
        if not prov or not prov.rtsp_video_url:
            return None

        host = self.coordinator.entry.data[CONF_HOST]
        # Replace ${ipadress} placeholder with actual host IP
        return prov.rtsp_video_url.replace("${ipadress}", host)
