"""Async HTTP client for eq677.icarm.cloud.

A single :class:`httpx.AsyncClient` is used without ``base_url`` because the
manifest host (``eq677.icarm.cloud``) and the table CDN host
(``eq677-magmas.icarm.cloud``) are different subdomains. Conditional GET
(``If-None-Match``) is sent for the manifest only; table fetches are
content-addressed by canonical hash and don't need revalidation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Self

import httpx

from magma_explorer import __version__
from magma_explorer.magma import Magma

MANIFEST_URL = "https://eq677.icarm.cloud/manifest.json"

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
USER_AGENT = f"MagmaExplorer/{__version__}"


class ClientError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ManifestSnapshot:
    magmas: tuple[Magma, ...]
    etag: str | None


class Client:
    def __init__(
        self,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch_manifest(self, etag: str | None = None) -> ManifestSnapshot | None:
        """Fetch the manifest. Returns ``None`` if the server reports 304."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag

        try:
            resp = await self._http.get(MANIFEST_URL, headers=headers)
        except httpx.HTTPError as exc:
            raise ClientError(f"manifest request failed: {exc}") from exc

        if resp.status_code == 304:
            return None
        if resp.status_code != 200:
            raise ClientError(f"manifest returned HTTP {resp.status_code}")

        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise ClientError(f"manifest is not valid JSON: {exc}") from exc

        entries = payload.get("magmas")
        if not isinstance(entries, list):
            raise ClientError("manifest missing `magmas` array")

        try:
            magmas = tuple(Magma.from_manifest_entry(e) for e in entries)
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError(f"manifest entry malformed: {exc}") from exc

        return ManifestSnapshot(magmas=magmas, etag=resp.headers.get("ETag"))

    async def fetch_table(self, url: str) -> str:
        """Fetch a single op-table by its absolute URL (the manifest's `url` field)."""
        try:
            resp = await self._http.get(url, headers={"Accept": "text/plain"})
        except httpx.HTTPError as exc:
            raise ClientError(f"table fetch failed: {exc}") from exc
        if resp.status_code != 200:
            raise ClientError(f"table fetch HTTP {resp.status_code}")
        return resp.text
