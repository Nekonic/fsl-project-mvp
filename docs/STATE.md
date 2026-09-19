# State

The handover between sessions. Keep it true; it is all the next session gets.

Updated: 2026-09-19 (v1.0 + 4 backlog items)

## Where things stand

v1.0 proves the hypothesis. `bin/verify` is green: 103 unit/API tests, 11
acceptance tests against the live stack.

Last full run: `TP=6 FN=0 FP=0 TN=6`, no pipeline warnings. Adding a rule that
matches `apple` turns `normal-product-search` into a false positive and moves
precision to 0.83 — so the score responds to defence changes in the predicted
direction, which is the whole point.

```
production_loc  1653   (v1.0: 1703)
dependencies       6   (v1.0: 7)
services           7   (v1.0: 8)
```

## In progress

Nothing. Start at the top of the backlog.

## Done since v1.0

- **Collapsed the Django boilerplate.** Every route now lives in
  `fsl/urls.py`; `api/urls.py` and `blueteam/urls.py` were two copies of the
  same two imports. Both `apps.py` files said only what Django's default
  `AppConfig` already says. `fsl/wsgi.py` and the `WSGI_APPLICATION` setting
  went with them - runserver falls back to `get_wsgi_application()` when that
  setting is absent. `-15 LOC, five fewer files`.

  `manage.py` stays. The Dockerfile runs migrations through it and it is the
  entry point anyone would reach for.

- **Deleted the dead marker-probing.** `_MARKER_KEYS` guessed at four spellings
  of the header, all inherited from the eve-log `custom:` hypothesis that
  measurement later showed does nothing at all. Each engine logs the marker in
  exactly one place and the code now looks in exactly that place. `-6 LOC`.

  The estimate said `-15`; four lines went back as a comment recording why
  narrowing this is safe. Matching stays case-insensitive because HTTP header
  names are — a property of the protocol, not a guess. Two test files had the
  invented shape baked into their fixtures and were passing on data Suricata
  never produces.

  This tick also hit a false red twice: sessions created just after a stack
  restart ingest nothing, and the score came back all-FN reading as "no attack
  was detected at all". `score_when_ready` now checks for an empty ingest and
  says so. See DECISIONS for that and for why truncating `eve.json` in place
  breaks Filebeat.

- **Removed Kibana.** One service and about a gigabyte of RAM, for something
  no other part of the stack referenced. The console already lists detections
  and Elasticsearch stays, so curl still answers ad-hoc questions.
  `-10 LOC, -1 service`.

  Note for whoever wants it back: `docker compose stop kibana` fails silently
  once the service is gone from compose.yaml, which leaves the container
  running as an orphan. Remove the container first, or use
  `docker compose up -d --remove-orphans`.

- **Dropped djangorestframework.** `serializers.py` is gone; the views are plain
  Django returning `JsonResponse`, and the shape of every response is now one
  tuple of field names per resource. `-19 LOC, -1 dependency`.

  Two things it exposed. `bin/verify`'s bind-mount guard was grepping raw JSON
  text and broke on a single space, because DRF rendered `{"ok":true}` and
  Django renders `{"ok": true}` - it parses the response now. And the
  acceptance fixture stopped waiting at the first true positive, which races
  ModSecurity: Suricata alerts reach Elasticsearch first, so half the
  detections were still missing. It waits for both engines now.

## Backlog

Ordered by value over risk. Take the top one. If you finish it and have room,
stop anyway — a small verified step handed over cleanly beats two rushed ones.

### 1. Shrink `redteam/harness.py`

191 lines, the second largest file. `Harness` holds three fields and could be
functions taking a `requests.Session`. Do not touch `check_path_preserved` — it
guards a real bug that made the score lie (see DECISIONS).

### 2. Translate docs/superpowers/specs/ to English

CLAUDE.md states the repo is written in English. The design document is still
210 lines of Korean, so the briefing is not true. It is the canonical reference
a session reads when it needs the why behind a decision, and it costs roughly
twice the tokens it should.

Not counted by `bin/measure` - docs never are - so judge it on the briefing
being honest, not on the numbers moving.

### 3. Consider replacing Django entirely

The largest remaining win and the riskiest. Django plus DRF is two dependencies
carrying an ORM, migrations, templates and routing for five models and ten
endpoints. `sqlite3` and a small framework would be a fraction of that.

Do not start this until 1-2 are done; by then the Django surface will be small
enough to judge honestly. Note the cost: the production repo's main site is
Django, so diverging here loses shared ground.

## Known gaps

- **Window correlation is never exercised end to end.** `correlation: window`
  is implemented and unit-tested to its boundaries, but no case in
  `redteam/cases/` uses it, so it has never run against the real stack. It
  needs a non-HTTP tool (nmap) and the tool container's IP. Out of scope for
  v1.0 by the design document; close this gap before trusting the strategy.
- The `platform` container mounts the Docker socket to validate rules. It is a
  container escape path. Acceptable in a local lab, not beyond one.
