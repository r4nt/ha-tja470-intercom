# ha-tja470-intercom

Draft:
Home assistant integration for TJA470 intercom.
This uses the aiotja470-intercom package.
Must pass highest home assistant guidelines.
Config flow:
Ask user for IP / user / password with explanation on how to set that up on the tja470 web interface.
Read free devices. If there are no free devices, guide the user through how to add one in the tja470 web interface.
If there is a free device, generate a uuid and connect to it. Read the provisioning info and remember:
- all endpoints and their number
- endpoints names, including sip addresses

Create devices for the doors/gates that are connected to the tja470 intercom.
Provide services to open the doors / gates, either for the currently active door/gate (will change when the bell rings), or with a number (using the respective API).
Provide service to swtich the camera.

Make sure to store all information that is necessary to re-connect, i.e. the uuid etc, and manage the auth cookie.
Allow users to look up the provisioning data including the sip auth info on the integration.

Open question: best way to make it into an actual intercom with UX, and how to connect all of this in a way that video/audio works when the user is not in the home network.