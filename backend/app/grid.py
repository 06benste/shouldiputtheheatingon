"""The privacy grid. Clients send cell indices, never coordinates.

Must match CELL_LAT / CELL_LON in the Home Assistant integration.
At UK latitudes each cell is roughly 5 km x 5 km.
"""
import math

CELL_LAT = 0.045
CELL_LON = 0.075
MAX_I = math.floor(90 / CELL_LAT)
MAX_J = math.floor(180 / CELL_LON)


def cell_for(lat: float, lon: float) -> tuple[int, int]:
    return math.floor(lat / CELL_LAT), math.floor(lon / CELL_LON)


def cell_centre(i: int, j: int) -> tuple[float, float]:
    return round((i + 0.5) * CELL_LAT, 4), round((j + 0.5) * CELL_LON, 4)


def valid_cell(i: int, j: int) -> bool:
    return -MAX_I <= i < MAX_I and -MAX_J <= j < MAX_J
