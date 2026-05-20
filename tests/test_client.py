import httpx
import pytest

from magma_explorer.client import Client, ClientError, ManifestSnapshot
from magma_explorer.magma import Magma


def _manifest_payload(n: int = 2) -> dict:
    return {
        "count": n,
        "magmas": [
            {
                "canonical_hash": f"hash{i}",
                "size": i + 1,
                "satisfies_255": True,
                "right_cancellative": False,
                "idempotent": True,
                "display_reorder": None,
                "comment": f"comment {i}",
                "submitted_at": "2026-01-01 00:00:00",
                "submitted_by": "test",
                "url": f"https://example.com/{i}.txt",
            }
            for i in range(n)
        ],
    }


def _client(handler) -> Client:
    return Client(transport=httpx.MockTransport(handler))


async def test_fetch_manifest_parses_entries():
    def handler(request):
        return httpx.Response(200, json=_manifest_payload(2), headers={"ETag": "v1"})

    async with _client(handler) as client:
        snap = await client.fetch_manifest()

    assert isinstance(snap, ManifestSnapshot)
    assert snap.etag == "v1"
    assert len(snap.magmas) == 2
    assert all(isinstance(m, Magma) for m in snap.magmas)


async def test_fetch_manifest_304_returns_none():
    def handler(request):
        return httpx.Response(304)

    async with _client(handler) as client:
        snap = await client.fetch_manifest(etag="v1")

    assert snap is None


async def test_fetch_manifest_sends_if_none_match():
    captured: dict[str, str | None] = {}

    def handler(request):
        captured["if_none_match"] = request.headers.get("if-none-match")
        return httpx.Response(304)

    async with _client(handler) as client:
        await client.fetch_manifest(etag="v1")

    assert captured["if_none_match"] == "v1"


async def test_fetch_manifest_http_error_raises():
    def handler(request):
        return httpx.Response(500)

    async with _client(handler) as client:
        with pytest.raises(ClientError):
            await client.fetch_manifest()


async def test_fetch_manifest_malformed_json_raises():
    def handler(request):
        return httpx.Response(200, content=b"not json")

    async with _client(handler) as client:
        with pytest.raises(ClientError):
            await client.fetch_manifest()


async def test_fetch_manifest_missing_magmas_raises():
    def handler(request):
        return httpx.Response(200, json={"count": 0})

    async with _client(handler) as client:
        with pytest.raises(ClientError):
            await client.fetch_manifest()


async def test_fetch_manifest_malformed_entry_raises():
    def handler(request):
        return httpx.Response(
            200,
            json={"count": 1, "magmas": [{"canonical_hash": "x"}]},  # missing size
        )

    async with _client(handler) as client:
        with pytest.raises(ClientError):
            await client.fetch_manifest()


async def test_fetch_table_returns_text():
    def handler(request):
        return httpx.Response(200, text="0 1\n1 0")

    async with _client(handler) as client:
        text = await client.fetch_table("https://example.com/x.txt")

    assert text == "0 1\n1 0"


async def test_fetch_table_404_raises():
    def handler(request):
        return httpx.Response(404)

    async with _client(handler) as client:
        with pytest.raises(ClientError):
            await client.fetch_table("https://example.com/x.txt")
