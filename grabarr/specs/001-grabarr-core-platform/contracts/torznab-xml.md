# Torznab Endpoint Contract

**Scope**: All `/torznab/{slug}/api?...` and `/torznab/{slug}/download/...`
responses. This is Grabarr's *arr-facing surface and MUST NOT drift from
the standard Torznab spec (Constitution Article I).

**Reference spec**: https://torznab.github.io/spec-1.3-draft/

## Authentication

Every `t=` request (except `t=caps`) MUST include `apikey=<per-profile
API key>`. Missing or invalid keys return:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: TorznabApiKey realm="grabarr:{slug}"
Content-Type: application/xml; charset=utf-8

<?xml version="1.0" encoding="UTF-8"?>
<error code="100" description="Invalid API key"/>
```

`t=caps` is unauthenticated (Prowlarr reads it before the user enters a
key).

---

## `GET /torznab/{slug}/api?t=caps`

Returns the capabilities document.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server
      version="1.0"
      title="Grabarr ({profile_name})"
      strapline="Shadow-library bridge via Torznab"
      email=""
      url="http://{host}:{port}/torznab/{slug}/"
      image=""/>
  <limits max="100" default="50"/>
  <searching>
    <search available="yes" supportedParams="q"/>
    <book-search available="yes" supportedParams="q,author,title"/>
    <movie-search available="yes" supportedParams="q"/>
    <music-search available="yes" supportedParams="q,artist,album"/>
    <tv-search available="no"/>
  </searching>
  <categories>
    <!-- One <category> element per profile.newznab_categories entry -->
    <category id="7020" name="Books"/>
    <category id="7030" name="Books/Comics"/>
    <!-- ... -->
  </categories>
</caps>
```

**Notes**:
- `max` MUST be 100 (matches orchestrator cap, FR-013).
- `default` MUST be 50.
- The `<searching>` flags MUST declare `available="yes"` only for the query
  types the profile's `media_type` supports. For example, an `ebook` profile
  returns `book-search` = yes and `movie-search` = no.

---

## `GET /torznab/{slug}/api?t=search&q={query}&apikey={key}`

Returns an RSS 2.0 feed with `torznab:` extensions.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <atom:link href="http://{host}/torznab/{slug}/api?t=search&amp;q={query}"
               rel="self" type="application/rss+xml"/>
    <title>Grabarr :: {profile_name}</title>
    <description>{profile.description}</description>
    <link>http://{host}/torznab/{slug}/</link>
    <language>en-us</language>
    <category>{first_newznab_category}</category>

    <item>
      <title>The Name of the Wind - Patrick Rothfuss (2007).epub</title>
      <description>EPUB via Anna's Archive (aa-fast). ISBN 9780756404741.</description>
      <guid isPermaLink="true">
        http://{host}/torznab/{slug}/download/{token}.torrent
      </guid>
      <pubDate>Wed, 23 Apr 2026 10:12:42 +0000</pubDate>
      <size>1048576</size>
      <category>7020</category>
      <link>http://{host}/torznab/{slug}/download/{token}.torrent</link>
      <enclosure
          url="http://{host}/torznab/{slug}/download/{token}.torrent"
          length="1048576"
          type="application/x-bittorrent"/>

      <!-- Torznab attrs -->
      <torznab:attr name="category" value="7020"/>
      <torznab:attr name="seeders" value="1"/>
      <torznab:attr name="peers" value="0"/>
      <torznab:attr name="downloadvolumefactor" value="0"/>
      <torznab:attr name="uploadvolumefactor" value="1"/>
      <torznab:attr name="infohash" value="{40-char hex}"/>
      <torznab:attr name="grabs" value="0"/>
      <torznab:attr name="language" value="en"/>
      <torznab:attr name="author" value="Patrick Rothfuss"/>
      <torznab:attr name="isbn" value="9780756404741"/>
      <torznab:attr name="year" value="2007"/>
    </item>
    <!-- additional <item> elements ... -->
  </channel>
</rss>
```

**Attribute rules**:
- `seeders = 1`, `peers = 0`, `downloadvolumefactor = 0`,
  `uploadvolumefactor = 1`, `infohash` — all four MUST be present (FR-015).
- `category` MUST appear both as `<category>` and as a `torznab:attr
  name="category"`.
- `size` MUST equal the file's byte length (or a best-effort estimate for
  async-streaming results where exact size is not yet known — estimates
  MUST be within ±5 % of the eventual actual size).
- `pubDate` MUST be RFC-822 formatted.
- `enclosure.type` MUST be `application/x-bittorrent`.
- Empty result set MUST return a valid RSS feed with zero `<item>`
  elements — NEVER HTTP 500.

---

## `GET /torznab/{slug}/api?t=book&q={query}&author={author}&title={title}&apikey={key}`

Same shape as `t=search`; additional query params are passed to the
underlying orchestrator as filters.

---

## `GET /torznab/{slug}/api?t=music&q={query}&artist={artist}&album={album}&apikey={key}`

Same shape; applicable only to profiles with `media_type` in
`{music, audiobook}`.

---

## `GET /torznab/{slug}/api?t=movie&q={query}&apikey={key}`

Same shape; applicable only to profiles with `media_type` in
`{video, software, game_rom}`.

---

## `GET /torznab/{slug}/download/{token}.torrent`

Returns the `.torrent` bencoded blob. `{token}` is the `downloads.token`
generated when the search result was emitted.

```http
HTTP/1.1 200 OK
Content-Type: application/x-bittorrent
Content-Disposition: attachment; filename="{sanitized_title}.torrent"
X-Grabarr-Download-Mode: sync | async_streaming | hybrid
X-Grabarr-Torrent-Mode: active_seed | webseed
Content-Length: {N}

<bencoded .torrent bytes>
```

**Rules**:
- Unknown or expired tokens return `404 Not Found` (body: empty or a short
  text message).
- The `.torrent` file MUST be consumable by Deluge, qBittorrent,
  Transmission, and rTorrent without configuration changes (Constitution
  Article I).
- For `active_seed` mode, the `announce` URL in the torrent MUST be
  `http://{host}:{tracker_port}/announce`.
- For `webseed` mode, the torrent MUST include the `url-list` key pointing
  at `http://{host}/torznab/{slug}/seed/{token}` and MUST still include a
  (dummy but valid) tracker URL so clients that require one don't reject
  the torrent.
- Response MUST begin within 2 seconds of request (async-streaming
  performance gate from SC-004).

---

## `GET /torznab/{slug}/seed/{token}` (webseed)

HTTP range-aware file server used by `webseed`-mode torrents.

- MUST support `Range: bytes=X-Y` with 206 Partial Content.
- MUST support HEAD returning the total `Content-Length`.
- MUST set `Content-Type` from the verified file (e.g. `application/epub+
  zip` for EPUB).
- MUST return `404` for unknown tokens, `410 Gone` for tokens whose
  retention window has expired.
- MUST tolerate slow or concurrent clients (used as webseed peers for the
  duration of the seed-retention window).

---

## `GET /announce` (active-seed tracker)

Standard BitTorrent HTTP tracker announce. Runs on the dedicated tracker
port (default 8999), NOT on the main API port.

**Query parameters**: `info_hash`, `peer_id`, `port`, `uploaded`,
`downloaded`, `left`, `event` (optional: `started`, `stopped`, `completed`),
`numwant` (optional), `compact` (0 or 1).

**Response (compact=1)**:

```
d8:intervali1800e5:peers6:{binary peer IP+port}e
```

**Response (compact=0)**:

```
d8:intervali1800e5:peersld2:ip11:192.168.1.14:porti45001eeee
```

- `interval` MUST be 1800 (30 minutes).
- Grabarr's libtorrent session is always returned as a peer for known
  info_hashes.
- Unknown info_hash returns a bencoded `d14:failure reason...e` rather than
  an HTTP error.
