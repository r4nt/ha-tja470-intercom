import json
import os

def main():
    storage_dir = os.path.join(".", ".storage")
    if not os.path.exists(storage_dir):
        os.makedirs(storage_dir)

    lovelace_path = os.path.join(storage_dir, "lovelace")
    lovelace_resources_path = os.path.join(storage_dir, "lovelace_resources")

    # 1. Write lovelace config if missing (HA migrates lovelace -> lovelace.lovelace on startup)
    if not os.path.exists(lovelace_path) and not os.path.exists(os.path.join(storage_dir, "lovelace.lovelace")):
        lovelace_data = {
            "version": 1,
            "minor_version": 1,
            "key": "lovelace",
            "data": {
                "config": {
                    "views": [
                        {
                            "title": "Overview",
                            "path": "overview",
                            "cards": [
                                {
                                    "type": "custom:tja470-intercom-card"
                                }
                            ]
                        }
                    ]
                }
            }
        }
        with open(lovelace_path, "w", encoding="utf-8") as f:
            json.dump(lovelace_data, f, indent=2)
        print("Created default Lovelace dashboard config.")

    # 2. Write lovelace resources config if missing
    if not os.path.exists(lovelace_resources_path):
        lovelace_resources_data = {
            "version": 1,
            "minor_version": 1,
            "key": "lovelace_resources",
            "data": {
                "items": [
                    {
                        "url": "/tja470-intercom/tja470-intercom-card.js?v=1.0.5",
                        "type": "module",
                        "id": "tja470_intercom_card"
                    }
                ]
            }
        }
        with open(lovelace_resources_path, "w", encoding="utf-8") as f:
            json.dump(lovelace_resources_data, f, indent=2)
        print("Created default Lovelace resources config.")

if __name__ == "__main__":
    main()
