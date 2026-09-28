"""All configuration comes from environment variables."""
import os


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./data/heating.db")
    # DigitalOcean (and most hosts) hand out postgres:// or postgresql:// URLs.
    # Point SQLAlchemy at the psycopg 3 driver that's actually installed.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings:
    database_url = _database_url()
    db_pool_size = _int("DB_POOL_SIZE", 5)
    db_max_overflow = _int("DB_MAX_OVERFLOW", 5)
    # Cells with fewer fresh homes than this are hidden from the map (k-anonymity).
    min_homes_per_cell = _int("MIN_HOMES_PER_CELL", 3)
    # Readings older than this drop off the map.
    stale_after_minutes = _int("STALE_AFTER_MINUTES", 30)
    # Reject reports from one device more often than this.
    min_report_interval_seconds = _int("MIN_REPORT_INTERVAL_SECONDS", 60)
    registrations_per_ip_per_hour = _int("REGISTRATIONS_PER_IP_PER_HOUR", 5)
    # Devices that haven't reported for this long are deleted entirely.
    delete_inactive_after_days = _int("DELETE_INACTIVE_AFTER_DAYS", 30)
    purge_interval_minutes = _int("PURGE_INTERVAL_MINUTES", 60)
    # Header holding the real client IP, set by your load balancer.
    # DigitalOcean App Platform: do-connecting-ip. Leave empty to use the socket address.
    client_ip_header = os.getenv("CLIENT_IP_HEADER", "").strip().lower()
    cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()


settings = Settings()
