import json
import os
import uuid

def main():
    config_file = os.path.expanduser("~/.tja470_config.json")
    if not os.path.exists(config_file):
        print("~/.tja470_config.json not found, skipping config injection.")
        return

    print("Injecting configuration from ~/.tja470_config.json...")
    with open(config_file, "r", encoding="utf-8") as f:
        tja_config = json.load(f)

    host = tja_config.get("host")
    username = tja_config.get("username")
    password = tja_config.get("password")
    client_uuid = tja_config.get("uuid")
    cookies = tja_config.get("cookies", {})

    if not all([host, username, password, client_uuid]):
        print("Error: Missing required fields in ~/.tja470_config.json")
        return

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

    # Find existing tja470_intercom entry
    for entry in entries:
        if entry.get("domain") == "tja470_intercom":
            print("TJA470 Intercom is already registered, skipping injection.")
            return

    entry_data = {
        "cookies": cookies,
        "host": host,
        "password": password,
        "username": username,
        "uuid": client_uuid,
    }

    print("Creating new TJA470 Intercom configuration entry...")
    new_entry = {
        "entry_id": uuid.uuid4().hex,
        "version": 1,
        "minor_version": 1,
        "domain": "tja470_intercom",
        "title": f"TJA470 Intercom ({host})",
        "data": entry_data,
        "options": {
            "notify_devices": ["persistent_notification", "send_message"]
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

    with open(entries_path, "w", encoding="utf-8") as f:
        json.dump(entries_data, f, indent=2)
    print("Configuration injected successfully.")

if __name__ == "__main__":
    main()
