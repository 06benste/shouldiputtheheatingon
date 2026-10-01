# Should I put the heating on?

Share your heating status from Home Assistant and see it on a live, anonymous map of homes with their heating on, at [shouldiputtheheatingon.co.uk](https://shouldiputtheheatingon.co.uk/).

## Install

Install through [HACS](https://hacs.xyz): HACS → ⋮ → Custom repositories → add `https://github.com/06benste/shouldiputtheheatingon` with type *Integration*, then download **Should I put the heating on?**. Restart Home Assistant, then add **Should I put the heating on?** under Settings → Devices & services.

You choose:
- **Thermostat** (required): any `climate` entity. "On" means its mode is heat, heat/cool or auto, i.e. the heating is switched on, whether or not it's firing at that moment.
- **Indoor temperature sensor** (optional): otherwise the thermostat's reading is used.
- **Outdoor temperature sensor** (required): a physical sensor outside, or the temperature from any weather integration already in Home Assistant.
- **Heating active sensor** (optional): a `binary_sensor`/`switch` that says whether the heating is switched on, if the thermostat's mode doesn't.

It reports every 5 minutes, plus within about a minute of the heating switching on or off. Fahrenheit setups are converted to Celsius. Change entities or refresh your area under the integration's **Configure** button.

### Hive users

Hive has no official public API. Rather than asking people for their Hive password, use Home Assistant's built-in Hive integration and share its thermostat. No extra sensor is needed.

## Privacy design

- **Location is rounded inside Home Assistant.** The integration converts the home location to a grid cell (about 5 km square) and only ever sends the cell indices. The server never sees coordinates.
- **Only the area is shown.** Every home with a fresh reading appears on the map as its ~5 km cell, never a precise location. A cell with a single home shows that home's readings.
- **No history.** Each home has one row holding its latest reading. Nothing is logged over time.
- **No third-party services.** Outside temperatures come only from each home's own outdoor sensor. An area's outside temperature is the median of its homes' readings. The backend makes no outbound requests.
- **No identifiers in public data.** The map shows no device IDs, and readings within a cell are shuffled on every refresh.
- **Tokens are hashed.** The server stores only a SHA-256 hash of each home's token, never the token itself.
- **Leaving is instant.** Deleting the integration removes the home from the map immediately. Homes silent for 30 days are purged automatically.
