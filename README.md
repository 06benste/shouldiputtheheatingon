# Should I put the heating on?

Share your heating status from Home Assistant and see it on a live, anonymous map of homes with their heating on, at [shouldiputtheheatingon.com](https://shouldiputtheheatingon.com).

## Privacy design

- **Location is rounded inside Home Assistant.** The integration converts the home location to a grid cell (about 5 km square) and only ever sends the cell indices. The server never sees coordinates.
- **Sparse areas are hidden.** Cells with fewer than 3 fresh homes aren't shown on the map, though they still count towards the national headline.
- **No history.** Each home has one row holding its latest reading. Nothing is logged over time.
- **No third-party services.** Outside temperatures come only from each home's own outdoor sensor. An area's outside temperature is the median of its homes' readings. The backend makes no outbound requests.
- **No identifiers in public data.** The map shows no device IDs, and readings within a cell are shuffled on every refresh.
- **Tokens are hashed.** The server stores only a SHA-256 hash of each home's token, never the token itself.
- **Leaving is instant.** Deleting the integration removes the home from the map immediately. Homes silent for 30 days are purged automatically.

## Install

Install through [HACS](https://hacs.xyz): HACS → ⋮ → Custom repositories → add `https://github.com/06benste/shouldiputtheheatingon` with type *Integration*, then download **Should I put the heating on?**. Restart Home Assistant, then add **Should I put the heating on?** under Settings → Devices & services.

You choose:
- **Thermostat** (required): any `climate` entity. "On" means `hvac_action` is `heating`.
- **Indoor temperature sensor** (optional): otherwise the thermostat's reading is used.
- **Outdoor temperature sensor** (required): a physical sensor outside, or the temperature from any weather integration already in Home Assistant.
- **Heating active sensor** (optional): a `binary_sensor`/`switch` for thermostats that don't report `hvac_action`, such as a boiler relay.

It reports every 5 minutes, plus within about a minute of the heating switching on or off. Fahrenheit setups are converted to Celsius. Change entities or refresh your area under the integration's **Configure** button.

### Hive users

Hive has no official public API. Rather than asking people for their Hive password, use Home Assistant's built-in Hive integration and share its thermostat. It reports `hvac_action`, so no extra sensor is needed.

## Running your own server

The public map is hosted at shouldiputtheheatingon.com, but the backend is open source if you'd rather run your own instance — see [DEPLOYMENT.md](DEPLOYMENT.md).
