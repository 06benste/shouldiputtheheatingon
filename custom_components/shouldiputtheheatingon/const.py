"""Constants for the Should I put the heating on? integration."""
from datetime import timedelta
import math

DOMAIN = "shouldiputtheheatingon"
DEFAULT_URL = "https://clownfish-app-57tmd.ondigitalocean.app"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_DEVICE_ID = "device_id"
CONF_CELL_I = "cell_i"
CONF_CELL_J = "cell_j"
CONF_CLIMATE = "climate_entity"
CONF_INDOOR = "indoor_temperature_entity"
CONF_OUTDOOR = "outdoor_temperature_entity"
CONF_ACTIVE = "heating_active_entity"
CONF_UPDATE_AREA = "update_area"

REPORT_INTERVAL = timedelta(minutes=5)
# The server rejects reports closer together than 60 s.
MIN_SECONDS_BETWEEN_REPORTS = 65

# Privacy grid. Must match backend/app/grid.py. About 5 km x 5 km in the UK.
CELL_LAT = 0.045
CELL_LON = 0.075


def cell_for(lat: float, lon: float) -> tuple[int, int]:
    """Round a location to its grid cell. Only the cell ever leaves Home Assistant."""
    return math.floor(lat / CELL_LAT), math.floor(lon / CELL_LON)


def cell_centre(i: int, j: int) -> tuple[float, float]:
    return round((i + 0.5) * CELL_LAT, 3), round((j + 0.5) * CELL_LON, 3)


def signal_update(entry_id: str) -> str:
    """Dispatcher signal fired whenever the reporter's state changes."""
    return f"{DOMAIN}_update_{entry_id}"
