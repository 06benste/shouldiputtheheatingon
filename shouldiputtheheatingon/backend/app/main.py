"""shouldiputtheheatingon API.

POST   /api/v1/devices      register a home, returns a token (shown once)
POST   /api/v1/report       send the latest reading (Bearer token)
DELETE /api/v1/devices/me   stop sharing and delete everything about this home
GET    /api/v1/cells        public, aggregated map data
"""
import asyncio
import hashlib
import logging
import random
import secrets
import statistics
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import Device, SessionLocal, init_db, utcnow
from .grid import cell_centre, valid_cell
from .maintenance import maintenance_loop
from .ratelimit import RateLimiter

logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    task = asyncio.create_task(maintenance_loop())
    yield
    task.cancel()


app = FastAPI(title="shouldiputtheheatingon", lifespan=lifespan)
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET"], allow_headers=["*"])

registration_limiter = RateLimiter(settings.registrations_per_ip_per_hour, 3600)


# ---------- helpers ----------

def get_db():
    with SessionLocal() as db:
        yield db


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str:
    if settings.client_ip_header and (value := request.headers.get(settings.client_ip_header)):
        return value.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def current_device(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> Device:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Missing bearer token")
    device = db.scalar(select(Device).where(Device.token_hash == hash_token(token)))
    if device is None:
        raise HTTPException(401, "Unknown token")
    return device


# ---------- schemas ----------

class CellIn(BaseModel):
    i: int
    j: int


class RegisterIn(BaseModel):
    source: Literal["home_assistant", "hive", "other"] = "home_assistant"
    cell: CellIn


class RegisterOut(BaseModel):
    device_id: str
    token: str


class ReportIn(BaseModel):
    heating_on: bool
    target_temp: float | None = Field(None, ge=5, le=35)
    indoor_temp: float | None = Field(None, ge=-10, le=45)
    outdoor_temp: float | None = Field(None, ge=-50, le=55)
    cell: CellIn | None = None


def check_cell(cell: CellIn) -> None:
    if not valid_cell(cell.i, cell.j):
        raise HTTPException(422, "Cell out of range")


# ---------- write endpoints ----------

@app.post("/api/v1/devices", response_model=RegisterOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if not registration_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many registrations from this address")
    check_cell(body.cell)
    token = secrets.token_urlsafe(32)
    device = Device(id=str(uuid.uuid4()), token_hash=hash_token(token), source=body.source,
                    cell_i=body.cell.i, cell_j=body.cell.j, created_at=utcnow())
    db.add(device)
    db.commit()
    return RegisterOut(device_id=device.id, token=token)


@app.post("/api/v1/report", status_code=204)
def report(body: ReportIn, device: Device = Depends(current_device), db: Session = Depends(get_db)):
    now = utcnow()
    if device.reported_at and (now - device.reported_at).total_seconds() < settings.min_report_interval_seconds:
        raise HTTPException(429, "Reporting too often")
    if body.cell:
        check_cell(body.cell)
        device.cell_i, device.cell_j = body.cell.i, body.cell.j
    device.heating_on = body.heating_on
    device.target_temp = None if body.target_temp is None else round(body.target_temp, 1)
    device.indoor_temp = None if body.indoor_temp is None else round(body.indoor_temp, 1)
    device.outdoor_temp = None if body.outdoor_temp is None else round(body.outdoor_temp, 1)
    device.reported_at = now
    db.commit()
    _cache.clear()
    return Response(status_code=204)


@app.delete("/api/v1/devices/me", status_code=204)
def delete_me(device: Device = Depends(current_device), db: Session = Depends(get_db)):
    db.delete(device)
    db.commit()
    _cache.clear()
    return Response(status_code=204)


# ---------- public map data ----------

_cache: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 30


@app.get("/api/v1/cells")
def cells(db: Session = Depends(get_db)):
    if (hit := _cache.get("cells")) and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]

    now = utcnow()
    cutoff = now - timedelta(minutes=settings.stale_after_minutes)
    devices = db.scalars(select(Device).where(Device.reported_at >= cutoff)).all()
    groups: dict[tuple[int, int], list[Device]] = defaultdict(list)
    for d in devices:
        groups[(d.cell_i, d.cell_j)].append(d)

    out_cells = []
    for key, ds in groups.items():
        # Outside temperature comes only from homes' own sensors: the area's median.
        reported = [d.outdoor_temp for d in ds if d.outdoor_temp is not None]
        outside = round(statistics.median(reported), 1) if reported else None
        if len(ds) < settings.min_homes_per_cell:
            continue  # too few homes to show without identifying someone
        lat, lon = cell_centre(*key)
        homes = [{
            "heating_on": d.heating_on,
            "target_temp": d.target_temp,
            "indoor_temp": d.indoor_temp,
            "outdoor_temp": d.outdoor_temp,
            "source": d.source,
            "minutes_ago": int((now - d.reported_at).total_seconds() // 60),
        } for d in ds]
        random.shuffle(homes)  # so order can't be used to track a home over time
        out_cells.append({
            "lat": lat, "lon": lon,
            "homes": len(ds),
            "heating_on": sum(1 for d in ds if d.heating_on),
            "outside_temp": outside,
            "readings": homes,
        })

    outside_all = [d.outdoor_temp for d in devices if d.outdoor_temp is not None]
    result = {
        "generated_at": now.isoformat() + "Z",
        "cell_size_km": 5,
        "min_homes_per_cell": settings.min_homes_per_cell,
        "summary": {
            "homes": len(devices),
            "heating_on": sum(1 for d in devices if d.heating_on),
            "median_outside_temp": round(statistics.median(outside_all), 1) if outside_all else None,
        },
        "cells": out_cells,
    }
    _cache["cells"] = (time.monotonic(), result)
    return result


@app.get("/healthz")
def healthz():
    return {"ok": True}


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
