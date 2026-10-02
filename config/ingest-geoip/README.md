# GeoIP databases (durable home)

Elasticsearch reads its ingest-geoip databases from this directory, with the
managed downloader turned off (`ingest.geoip.downloader.enabled: false` in
`compose.yaml`). The databases are loaded once and not refreshed, so they
survive a container recreate instead of being fetched on every start — the
cloud's Elasticsearch cannot reach the download CDN through the VPN.

The `.mmdb` files are not committed (`.gitignore`). Populate this directory
once, before `docker compose up`:

```bash
bin/fetch-geoip
```

It fetches `GeoLite2-City.mmdb` from `geoip.elastic.co` (the same source the
managed downloader uses) and checks its MD5. The `fsl-geoip` pipeline uses the
City database for both the source IP and ModSecurity's client IP.

This product includes GeoLite data created by MaxMind, available from
<https://www.maxmind.com>. GeoLite2 is distributed under MaxMind's End User
Licence Agreement: keep the attribution above, and replace an old database
within 30 days of a new release. The licence is reviewed before this moves to
the production repository.
