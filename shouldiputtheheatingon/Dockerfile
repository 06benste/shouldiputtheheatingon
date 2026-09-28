FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/static ./static

RUN useradd --create-home --uid 1000 app && mkdir -p /srv/data && chown app /srv/data
USER app

# App Platform sets PORT from http_port. One worker: the rate limiter and
# purge job live in-process.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-server-header"]
