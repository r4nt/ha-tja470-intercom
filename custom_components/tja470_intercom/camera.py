"""Camera platform for Hager TJA470 Intercom."""
from __future__ import annotations

from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.const import CONF_HOST

from .const import DOMAIN
from .coordinator import TJA470Coordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the camera platform for TJA470."""
    coordinator: TJA470Coordinator = entry.runtime_data.coordinator

    async_add_entities([TJA470Camera(coordinator)])


class TJA470Camera(CoordinatorEntity[TJA470Coordinator], Camera):
    """Camera entity representing the TJA470 Intercom video stream."""

    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_translation_key = "camera"

    def __init__(self, coordinator: TJA470Coordinator) -> None:
        """Initialize camera."""
        super().__init__(coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self.coordinator.entry.entry_id}_call_update",
                self.async_write_ha_state,
            )
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of camera image from RTSP stream."""
        stream_url = await self.stream_source()
        if not stream_url:
            return None

        # Prepend input options to let FFmpeg fail fast if the stream is offline/unreachable
        input_source = f"-rtsp_transport tcp -timeout 5000000 -i {stream_url}"

        # Capture a snapshot frame from the RTSP stream using ha-ffmpeg helper
        image = await async_get_image(
            self.hass,
            input_source,
            output_format="mjpeg",
        )
        if not image:
            return None
        return image

    async def stream_source(self) -> str | None:
        """Return the RTSP stream source."""
        prov = self.coordinator.data.get("provisioning")
        if not prov or not prov.rtsp_video_url:
            return None

        host = self.coordinator.entry.data[CONF_HOST]
        # Replace ${ipadress} placeholder with actual host IP
        return str(prov.rtsp_video_url.replace("${ipadress}", host))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return camera state attributes."""
        return {
            "config_entry_id": self.coordinator.entry.entry_id,
        }
