# Developing Grabarr source adapters

Adding a new source to Grabarr is a **single file** in
`grabarr/adapters/` with the `@register_adapter` decorator. No
registry to edit, no setup boilerplate beyond implementing the
`SourceAdapter` Protocol.

This guide walks through the full process with a minimal example.

## Contract

Every adapter implements `grabarr.adapters.base.SourceAdapter` — a
runtime-checkable `typing.Protocol`. The canonical definition lives
at `specs/001-grabarr-core-platform/contracts/source-adapter.py`.

At a glance:

```python
class SourceAdapter(Protocol):
    id: str                              # snake_case, process-wide unique
    display_name: str                    # what the UI shows
    supported_media_types: set[MediaType]
    requires_cf_bypass: bool
    supports_member_key: bool
    supports_authentication: bool

    async def search(self, query, media_type, filters, limit=50) -> list[SearchResult]: ...
    async def get_download_info(self, external_id, media_type) -> DownloadInfo: ...
    async def health_check(self) -> HealthStatus: ...
    def get_config_schema(self) -> ConfigSchema: ...
    async def get_quota_status(self) -> QuotaStatus | None: ...
```

If your adapter sits on top of the vendored Shelfmark cascade, subclass
`grabarr.adapters.anna_archive.AnnaArchiveAdapter` and override only
the bits that differ (see `libgen.py` / `zlibrary.py` for examples —
each is ≤ 100 lines).

## Minimal skeleton

```python
# grabarr/adapters/myservice.py
from __future__ import annotations

import datetime as dt

import httpx

from grabarr.adapters.base import (
    AdapterConnectivityError,
    ConfigField,
    ConfigSchema,
    DownloadInfo,
    HealthStatus,
    MediaType,
    QuotaStatus,
    SearchFilters,
    SearchResult,
)
from grabarr.core.enums import AdapterHealth, UnhealthyReason
from grabarr.core.rate_limit import rate_limiter
from grabarr.core.registry import register_adapter


@register_adapter
class MyServiceAdapter:
    id = "myservice"
    display_name = "My Service"
    supported_media_types = {MediaType.EBOOK}
    requires_cf_bypass = False
    supports_member_key = False
    supports_authentication = False

    def __init__(self) -> None:
        rate_limiter.configure(self.id, "search", per_minute=30)

    async def search(self, query, media_type, filters, limit=50):
        await rate_limiter.acquire(self.id, "search")
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.get("https://myservice/api/search",
                                     params={"q": query, "limit": limit})
                r.raise_for_status()
            except httpx.HTTPError as exc:
                raise AdapterConnectivityError(str(exc)) from exc
        return [
            SearchResult(
                external_id=hit["id"],
                title=hit["title"],
                author=hit.get("author"),
                year=hit.get("year"),
                format=hit.get("format", "epub"),
                language=hit.get("lang"),
                size_bytes=hit.get("size"),
                quality_score=50.0,
                source_id=self.id,
                media_type=media_type,
                metadata={},
            )
            for hit in r.json().get("hits", [])
        ]

    async def get_download_info(self, external_id, media_type):
        return DownloadInfo(
            download_url=f"https://myservice/dl/{external_id}",
            size_bytes=None,
            content_type=None,
            filename_hint=f"{external_id}.epub",
            extra_headers={},
        )

    async def health_check(self):
        return HealthStatus(
            status=AdapterHealth.HEALTHY,
            reason=None, message=None,
            checked_at=dt.datetime.now(dt.UTC),
        )

    def get_config_schema(self):
        return ConfigSchema(fields=[])

    async def get_quota_status(self):
        return None
```

Save the file, restart Grabarr — that's it. The registry auto-discovers
the new adapter at startup (`grabarr.adapters.__init__` calls
`discover_adapters`). It immediately shows up:

- in `GET /api/sources`,
- in the `Sources` admin UI page,
- as a selectable source in any profile's edit form.

## What each method should do

### `search(query, media_type, filters, limit)`

Return up to `limit` normalized `SearchResult` objects. Apply filters
on the adapter side where the source natively supports them (language,
year range, format). The orchestrator drops everything else.

- On transport failure: raise `AdapterConnectivityError`.
- On 5xx: raise `AdapterServerError`.
- On 429 / rate-limit: raise `AdapterRateLimitError`.
- On cookies-expired / login redirect: raise `AdapterAuthError`.

The orchestrator catches any `AdapterError` subclass and moves on to
the next source in the profile.

### `get_download_info(external_id, media_type)`

Resolve a `SearchResult.external_id` to a concrete HTTP URL. For
cascading sources like AA, this may loop through sub-sources until
one responds. Honour any failure-threshold or retry semantics the
source expects.

Return a `DownloadInfo` carrying:
- `download_url` — the URL to `GET`.
- `size_bytes` — if known from metadata (helps `hybrid` mode).
- `content_type` — for early Content-Type rejection.
- `filename_hint` — what to save the file as.
- `extra_headers` — any auth / cookie / UA overrides.

### `health_check()`

A cheap probe (single HTTP request to a lightweight endpoint).
Return a `HealthStatus`. The monitor runs this every 60 s.

Do NOT consume quota in this probe if your source has a quota.

### `get_config_schema()`

Return a `ConfigSchema` describing the settings your adapter reads.
Keys are dot-paths like `sources.<adapter_id>.<field>` that the
operator can set in `config.yaml` or via `GRABARR_*` env vars. The
UI renders your schema on the Sources page.

### `get_quota_status()`

Return `None` for unlimited sources; a real `QuotaStatus` for quota-
bound sources (see `ZLibraryAdapter` for the pattern).

## Rate limiting

`grabarr.core.rate_limit.rate_limiter` is the process-wide
`RateLimiter`. Configure your buckets in `__init__`:

```python
rate_limiter.configure(self.id, "search", per_minute=30)
rate_limiter.configure(self.id, "download", per_minute=10)
```

Acquire tokens before every outbound request:

```python
await rate_limiter.acquire(self.id, "search")
```

## Tests

A minimal adapter test looks like:

```python
@pytest.mark.asyncio
async def test_myservice_search_parses_response(respx_mock):
    adapter = MyServiceAdapter()
    respx_mock.get("https://myservice/api/search").mock(
        return_value=Response(200, json={"hits": [{"id": "1", "title": "X"}]})
    )
    results = await adapter.search("q", MediaType.EBOOK, SearchFilters())
    assert results[0].title == "X"
```

Use `respx` so tests don't touch the real network.

## See also

- `grabarr/adapters/internet_archive.py` — a full native adapter
  implementation (~330 lines) including a per-media-type file-
  preference ladder.
- `grabarr/adapters/libgen.py` + `zlibrary.py` — examples of
  extending the vendored Shelfmark cascade.
- `grabarr/adapters/_welib_template.py.example` — a copy-pasteable
  starting point.
