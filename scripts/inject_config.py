import json
import os
import uuid

def main():
    storage_dir = os.path.join(".", ".storage")
    if not os.path.exists(storage_dir):
        os.makedirs(storage_dir)

    entries_path = os.path.join(storage_dir, "core.config_entries")
    
    if os.path.exists(entries_path):
        with open(entries_path, "r", encoding="utf-8") as f:
            try:
                entries_data = json.load(f)
            except json.JSONDecodeError:
                entries_data = {}
    else:
        entries_data = {}

    # Initialize default structure if needed
    if not isinstance(entries_data, dict) or "data" not in entries_data:
        entries_data = {
            "version": 1,
            "minor_version": 1,
            "key": "core.config_entries",
            "data": {
                "entries": []
            }
        }
    
    entries = entries_data["data"].setdefault("entries", [])

    # Find user_id from .storage/auth if it exists, otherwise fall back to a dummy user_id
    user_id = "mock_user_id"
    auth_path = os.path.join(storage_dir, "auth")
    if os.path.exists(auth_path):
        with open(auth_path, "r", encoding="utf-8") as f:
            try:
                auth_data = json.load(f)
                users = auth_data.get("data", {}).get("users", [])
                for u in users:
                    if u.get("name") == "test":
                        user_id = u.get("id")
                        break
            except Exception:
                pass

    # 1. Inject mock mobile_app config entry for testing/development
    has_mock_iphone = False
    for entry in entries:
        if entry.get("domain") == "mobile_app" and entry.get("unique_id") == "mock_iphone_unique_id":
            has_mock_iphone = True
            data = entry.setdefault("data", {})
            if "app_data" not in data:
                print("Updating existing mock mobile_app with app_data...")
                data["app_data"] = {
                    "push_token": "mock_push_token",
                    "push_url": "https://push.example.com",
                }
            if "manufacturer" not in data:
                data["manufacturer"] = "Apple"
            if "model" not in data:
                data["model"] = "iPhone"
            if "user_id" not in data or data["user_id"] == "mock_user_id":
                data["user_id"] = user_id
            break

    if not has_mock_iphone:
        print("Injecting mock mobile_app config entry...")
        mock_mobile_entry = {
            "entry_id": "mock_mobile_app_entry_id",
            "version": 1,
            "minor_version": 1,
            "domain": "mobile_app",
            "title": "Mock iPhone",
            "data": {
                "device_id": "mock_iphone",
                "device_name": "Mock iPhone",
                "app_id": "io.robbie.HomeAssistant",
                "app_name": "Home Assistant",
                "app_version": "2024.1",
                "os_name": "iOS",
                "os_version": "17.0",
                "supports_encryption": False,
                "webhook_id": "mock_webhook_id",
                "manufacturer": "Apple",
                "model": "iPhone",
                "user_id": user_id,
                "app_data": {
                    "push_token": "mock_push_token",
                    "push_url": "https://push.example.com",
                },
            },
            "options": {},
            "pref_disable_new_entities": False,
            "pref_disable_polling": False,
            "source": "registration",
            "unique_id": "mock_iphone_unique_id",
            "disabled_by": None,
            "discovery_keys": {},
            "subentries": [],
            "created_at": "2026-06-10T10:00:00+00:00",
            "modified_at": "2026-06-10T10:00:00+00:00",
        }
        entries.append(mock_mobile_entry)

    # 1b. Inject mock device_registry, entity_registry, and restore_state entries
    device_registry_path = os.path.join(storage_dir, "core.device_registry")
    if os.path.exists(device_registry_path):
        with open(device_registry_path, "r", encoding="utf-8") as f:
            try:
                device_registry_data = json.load(f)
            except json.JSONDecodeError:
                device_registry_data = {}
    else:
        device_registry_data = {}

    if not isinstance(device_registry_data, dict) or "data" not in device_registry_data:
        device_registry_data = {
            "version": 1,
            "minor_version": 12,
            "key": "core.device_registry",
            "data": {
                "devices": [],
                "deleted_devices": []
            }
        }
    
    devices = device_registry_data["data"].setdefault("devices", [])
    has_mock_device = False
    for device in devices:
        if any(ident == ["mobile_app", "mock_iphone"] for ident in device.get("identifiers", [])):
            has_mock_device = True
            break

    if not has_mock_device:
        print("Injecting mock device registry entry...")
        mock_device = {
            "area_id": None,
            "config_entries": ["mock_mobile_app_entry_id"],
            "config_entries_subentries": {"mock_mobile_app_entry_id": [None]},
            "configuration_url": None,
            "connections": [],
            "created_at": "2026-06-10T10:00:00+00:00",
            "disabled_by": None,
            "entry_type": None,
            "hw_version": None,
            "id": "mock_iphone_device_registry_id",
            "identifiers": [["mobile_app", "mock_iphone"]],
            "labels": [],
            "manufacturer": "Apple",
            "model": "iPhone",
            "model_id": None,
            "modified_at": "2026-06-10T10:00:00+00:00",
            "name_by_user": None,
            "name": "Mock iPhone",
            "primary_config_entry": "mock_mobile_app_entry_id",
            "serial_number": None,
            "sw_version": "17.0",
            "via_device_id": None
        }
        devices.append(mock_device)
        with open(device_registry_path, "w", encoding="utf-8") as f:
            json.dump(device_registry_data, f, indent=2)

    entity_registry_path = os.path.join(storage_dir, "core.entity_registry")
    if os.path.exists(entity_registry_path):
        with open(entity_registry_path, "r", encoding="utf-8") as f:
            try:
                entity_registry_data = json.load(f)
            except json.JSONDecodeError:
                entity_registry_data = {}
    else:
        entity_registry_data = {}

    if not isinstance(entity_registry_data, dict) or "data" not in entity_registry_data:
        entity_registry_data = {
            "version": 1,
            "minor_version": 22,
            "key": "core.entity_registry",
            "data": {
                "entities": [],
                "deleted_entities": []
            }
        }

    entities = entity_registry_data["data"].setdefault("entities", [])
    has_mock_entity = False
    for entity in entities:
        if entity.get("entity_id") == "device_tracker.mock_iphone":
            has_mock_entity = True
            break

    if not has_mock_entity:
        print("Injecting mock entity registry entry...")
        mock_entity = {
            "aliases": [],
            "aliases_v2": [None],
            "area_id": None,
            "categories": {},
            "capabilities": None,
            "config_entry_id": "mock_mobile_app_entry_id",
            "config_subentry_id": None,
            "created_at": "2026-06-10T10:00:00+00:00",
            "device_class": None,
            "device_id": "mock_iphone_device_registry_id",
            "disabled_by": None,
            "entity_category": None,
            "entity_id": "device_tracker.mock_iphone",
            "hidden_by": None,
            "icon": None,
            "id": "mock_iphone_entity_registry_id",
            "has_entity_name": True,
            "labels": [],
            "modified_at": "2026-06-10T10:00:00+00:00",
            "name": None,
            "object_id_base": "mock_iphone",
            "options": {"conversation": {"should_expose": False}},
            "original_device_class": None,
            "original_icon": "mdi:cellphone",
            "original_name": "Device Tracker",
            "platform": "mobile_app",
            "suggested_object_id": "mock_iphone",
            "supported_features": 0,
            "translation_key": None,
            "unique_id": "tracker_unique_id_mock_iphone",
            "previous_unique_id": None,
            "unit_of_measurement": None
        }
        entities.append(mock_entity)
        with open(entity_registry_path, "w", encoding="utf-8") as f:
            json.dump(entity_registry_data, f, indent=2)

    restore_state_path = os.path.join(storage_dir, "core.restore_state")
    if os.path.exists(restore_state_path):
        with open(restore_state_path, "r", encoding="utf-8") as f:
            try:
                restore_state_data = json.load(f)
            except json.JSONDecodeError:
                restore_state_data = {}
    else:
        restore_state_data = {}

    if not isinstance(restore_state_data, dict) or "data" not in restore_state_data:
        restore_state_data = {
            "version": 1,
            "minor_version": 1,
            "key": "core.restore_state",
            "data": []
        }

    states = restore_state_data.setdefault("data", [])
    has_mock_state = False
    for state_item in states:
        state_entry = state_item.get("state", {})
        if state_entry.get("entity_id") == "device_tracker.mock_iphone":
            has_mock_state = True
            break

    if not has_mock_state:
        print("Injecting mock device tracker restore state...")
        import datetime
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        mock_state = {
            "state": {
                "entity_id": "device_tracker.mock_iphone",
                "state": "home",
                "attributes": {
                    "source_type": "gps",
                    "latitude": 48.8584,
                    "longitude": 2.2945,
                    "gps_accuracy": 15,
                    "friendly_name": "Mock iPhone",
                },
                "last_changed": now_utc,
                "last_reported": now_utc,
                "last_updated": now_utc,
                "context": {
                    "id": "mock_context_id_iphone",
                    "parent_id": None,
                    "user_id": None
                }
            },
            "extra_data": None,
            "last_seen": now_utc
        }
        states.append(mock_state)
        with open(restore_state_path, "w", encoding="utf-8") as f:
            json.dump(restore_state_data, f, indent=2)

    # 2. Inject Hager TJA470 Intercom config entry if configuration file exists
    config_file = os.path.expanduser("~/.tja470_config.json")
    if os.path.exists(config_file):
        print("Injecting configuration from ~/.tja470_config.json...")
        with open(config_file, "r", encoding="utf-8") as f:
            try:
                tja_config = json.load(f)
            except json.JSONDecodeError:
                tja_config = {}

        host = tja_config.get("host")
        username = tja_config.get("username")
        password = tja_config.get("password")
        client_uuid = tja_config.get("uuid")
        cookies = tja_config.get("cookies", {})

        if all([host, username, password, client_uuid]):
            # Find existing tja470_intercom entry
            has_tja = False
            for entry in entries:
                if entry.get("domain") == "tja470_intercom":
                    has_tja = True
                    break

            if not has_tja:
                print("Creating new TJA470 Intercom configuration entry...")
                entry_data = {
                    "cookies": cookies,
                    "host": host,
                    "password": password,
                    "username": username,
                    "uuid": client_uuid,
                }
                new_entry = {
                    "entry_id": uuid.uuid4().hex,
                    "version": 1,
                    "minor_version": 1,
                    "domain": "tja470_intercom",
                    "title": f"TJA470 Intercom ({host})",
                    "data": entry_data,
                    "options": {
                        "notify_devices": ["notify.mobile_app_mock_iphone"]
                    },
                    "pref_disable_new_entities": False,
                    "pref_disable_polling": False,
                    "source": "user",
                    "unique_id": host,
                    "disabled_by": None,
                    "discovery_keys": {},
                    "subentries": [],
                    "created_at": "2026-06-10T10:00:00+00:00",
                    "modified_at": "2026-06-10T10:00:00+00:00",
                }
                entries.append(new_entry)
        else:
            print("Error: Missing required fields in ~/.tja470_config.json, skipping intercom entry creation.")

    with open(entries_path, "w", encoding="utf-8") as f:
        json.dump(entries_data, f, indent=2)
    print("Configuration file updated.")

if __name__ == "__main__":
    main()
