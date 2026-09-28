"""Client for the shouldiputtheheatingon API."""
from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

TIMEOUT = ClientTimeout(total=20)


class ApiError(Exception):
    """Any failure talking to the server."""


class AuthError(ApiError):
    """The server doesn't recognise our token."""


class RateLimited(ApiError):
    """We reported too soon after the last report."""


class HeatingApi:
    def __init__(self, session: ClientSession, base_url: str, token: str | None = None) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._token = token

    async def _request(self, method: str, path: str, json: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            async with self._session.request(
                method, self._base + path, json=json, headers=headers, timeout=TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise AuthError("Token rejected")
                if resp.status == 429:
                    raise RateLimited(await resp.text())
                if resp.status >= 400:
                    raise ApiError(f"HTTP {resp.status}: {await resp.text()}")
                if resp.status == 204:
                    return None
                return await resp.json()
        except (ClientError, TimeoutError) as err:
            raise ApiError(str(err)) from err

    async def register(self, cell_i: int, cell_j: int) -> dict:
        return await self._request(
            "POST", "/api/v1/devices",
            {"source": "home_assistant", "cell": {"i": cell_i, "j": cell_j}},
        )

    async def report(self, payload: dict) -> None:
        await self._request("POST", "/api/v1/report", payload)

    async def delete_device(self) -> None:
        await self._request("DELETE", "/api/v1/devices/me")
