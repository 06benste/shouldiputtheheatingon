# Should I put the heating on?

A live map of homes with their heating on, built from readings people choose to share from Home Assistant.

```
Home Assistant ──(cell + readings, every 5 min)──▶ FastAPI ──▶ Postgres/SQLite
                                                     │
                                                     ▼
                                    GET /api/v1/cells ──▶ map page (static/index.html)
```

## Privacy design

- **Location is rounded inside Home Assistant.** The integration converts the home location to a grid cell (about 5 km square) and only ever sends the cell indices. The server never sees coordinates.
- **Sparse areas are hidden.** Cells with fewer than `MIN_HOMES_PER_CELL` (default 3) fresh homes aren't shown on the map, though they still count towards the national headline.
- **No history.** Each home has one row holding its latest reading. Nothing is logged over time.
- **No third-party services.** Outside temperatures come only from each home's own outdoor sensor. An area's outside temperature is the median of its homes' readings. The backend makes no outbound requests.
- **No identifiers in public data.** The map API returns no device IDs, and readings within a cell are shuffled on every response.
- **Tokens are hashed.** The server stores only a SHA-256 of each home's token.
- **Leaving is instant.** Deleting the integration calls `DELETE /api/v1/devices/me`. Homes silent for 30 days are purged automatically.

## Deploying to DigitalOcean App Platform

The app spec is in `.do/app.yaml`. It creates one web service built from the `Dockerfile` at the top of the repo and a Postgres 16 database, in the London region.

1. Push this repo to GitHub (the spec already points at `06benste/shouldiputtheheatingon`, branch `main`).
2. Install [doctl](https://docs.digitalocean.com/reference/doctl/how-to/install/) and run `doctl auth init`.
3. Create the app:
   ```bash
   doctl apps create --spec .do/app.yaml
   ```
   Or in the control panel: Apps → Create App → GitHub → pick the repo and `main`. It detects the Dockerfile. Finish creating the app, then go to its **Settings → App Spec → Edit**, replace everything with the contents of `.do/app.yaml`, and save. That adds the database and environment variables and redeploys.
4. When the first deploy finishes, the site is live at the `*.ondigitalocean.app` address shown in the dashboard. Tables are created automatically on startup.
5. Custom domain: uncomment `domains` in the spec, run `doctl apps update <app-id> --spec .do/app.yaml`, and follow the DNS instructions in the dashboard. HTTPS certificates are automatic.

Every push to `main` redeploys. To change a setting, edit it in the spec and run `doctl apps update`, or change it under the app's Settings → Environment Variables (a redeploy follows automatically). If you edit in the dashboard, copy the change back into the spec so the two don't drift.

**Database.** The spec starts with a *dev database*, which is cheap and plenty for launch. When you want backups, standby nodes and more connections, create a managed Postgres cluster and swap in the commented-out `production: true` block. `DATABASE_URL` is injected by App Platform from the database component (`${db.DATABASE_URL}`), already including `sslmode=require`; the app converts it for the psycopg driver.

**Scaling.** Keep `instance_count: 1` for now. Registration and report rate limits are held in memory, so a second instance would double them. Moving the limiter to Postgres or a managed Valkey instance is the step before scaling out.

**Local development.** `docker compose up -d --build` runs the same image with a local Postgres on port 8000. Or, with SQLite and no Docker:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/heating.db` | `postgres://…`, `postgresql://…` or `postgresql+psycopg://…` all work |
| `DB_POOL_SIZE` | `5` | Persistent Postgres connections |
| `DB_MAX_OVERFLOW` | `5` | Extra connections under load. Keep pool + overflow under your database's connection limit |
| `CLIENT_IP_HEADER` | empty | Header with the real client IP. `do-connecting-ip` on App Platform |
| `MIN_HOMES_PER_CELL` | `3` | Hide cells with fewer homes |
| `STALE_AFTER_MINUTES` | `30` | Readings older than this drop off |
| `MIN_REPORT_INTERVAL_SECONDS` | `60` | Per-home report throttle |
| `REGISTRATIONS_PER_IP_PER_HOUR` | `5` | Sign-up throttle |
| `DELETE_INACTIVE_AFTER_DAYS` | `30` | Purge silent homes |
| `PURGE_INTERVAL_MINUTES` | `60` | How often inactive homes are purged |
| `CORS_ORIGINS` | empty | Comma-separated, only if the map is hosted on another domain |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`… |
| `PORT` | `8000` | Set automatically by App Platform |

## API

| Method | Path | Auth | Body / result |
|---|---|---|---|
| POST | `/api/v1/devices` | none | `{"source":"home_assistant","cell":{"i":1143,"j":-35}}` → `{"device_id","token"}` |
| POST | `/api/v1/report` | Bearer | `{"heating_on":true,"target_temp":20,"indoor_temp":18.6,"outdoor_temp":7.5,"cell":{…}}` |
| DELETE | `/api/v1/devices/me` | Bearer | Deletes the home |
| GET | `/api/v1/cells` | none | Summary plus visible cells with anonymous readings |

Temperatures are Celsius. `target_temp` 5–35, `indoor_temp` −10–45, `outdoor_temp` −50–55, all optional in the API. The Home Assistant integration always sends `outdoor_temp` when the sensor has a reading.

## Home Assistant integration

Install through HACS: HACS → ⋮ → Custom repositories → add `https://github.com/06benste/shouldiputtheheatingon` with type *Integration*, then download **Should I put the heating on?**. Restart, then add **Should I put the heating on?** under Settings → Devices & services.

You choose:
- **Thermostat** (required): any `climate` entity. "On" means `hvac_action` is `heating`.
- **Indoor temperature sensor** (optional): otherwise the thermostat's reading is used.
- **Outdoor temperature sensor** (required): a physical sensor outside, or the temperature from any weather integration already in Home Assistant.
- **Heating active sensor** (optional): a `binary_sensor`/`switch` for thermostats that don't report `hvac_action`, such as a boiler relay.

It reports every 5 minutes, plus within about a minute of the heating switching on or off. Fahrenheit setups are converted to Celsius. Change entities or refresh your area under the integration's **Configure** button.

### Hive users

Hive has no official public API. Rather than asking people for their Hive password, use Home Assistant's built-in Hive integration and share its thermostat. It reports `hvac_action`, so no extra sensor is needed.

## Before going live

- Set `DEFAULT_URL` in `const.py` to your domain. That one lives in the Home Assistant integration, so it's a code constant rather than an environment variable; users can still change it in the setup form.
- Add a privacy notice to the site describing the above.
