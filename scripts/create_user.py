import asyncio
import os
import sys

from homeassistant.core import HomeAssistant
from homeassistant.auth import auth_manager_from_config
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.auth.const import GROUP_ID_ADMIN

async def main():
    config_dir = os.path.abspath(".")
    hass = HomeAssistant(config_dir)
    dr.async_setup(hass)
    await asyncio.gather(dr.async_load(hass), er.async_load(hass))
    
    # Load the auth manager
    hass.auth = await auth_manager_from_config(hass, [{"type": "homeassistant"}], [])
    provider = hass.auth.auth_providers[0]
    await provider.async_initialize()
    
    username = "test"
    password = "test"
    
    # Check if user already exists
    users = await hass.auth.async_get_users()
    for u in users:
        if u.name == username:
            print("User test already exists in user registry.")
            await hass.async_stop()
            return
            
    # 1. Create credential in homeassistant provider
    try:
        provider.data.add_auth(username, password)
        await provider.data.async_save()
    except Exception:
        # Username might already exist in provider data
        pass
        
    # Get credentials object
    credentials = await provider.async_get_or_create_credentials({"username": username})
    
    # 2. Create the user in the main auth registry (with admin permissions and owner=True)
    user = await hass.auth.async_create_user(
        name=username,
        group_ids=[GROUP_ID_ADMIN],
    )
    
    # 3. Link user to credentials
    await hass.auth.async_link_user(user, credentials)
    
    # Force saving auth store
    await hass.auth._store._store.async_save(hass.auth._store._data_to_save())
    
    await hass.async_stop()
    print("User test created and linked successfully!")

if __name__ == "__main__":
    asyncio.run(main())
