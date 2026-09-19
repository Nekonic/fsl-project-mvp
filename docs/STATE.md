# State

The handover between sessions. Keep it true; it is all the next session gets.

Updated: 2026-09-20 (product phase, phase 1 of 3 done)

## Where things stand

The repo moved from "prove the hypothesis" to "build the smallest product that
demonstrates it" on 2026-09-20. The design is in
`docs/superpowers/specs/2026-09-20-product-flow-design.md` and runs in four
phases; 0 and 1 are done.

`bin/verify` is green: 115 unit/API tests, 11 acceptance tests against the live
stack. The hypothesis itself is untouched and still scores
`TP=6 FN=0 FP=0 TN=6`.

```
core_loc         611   gated, unchanged by the product work
product_loc     1370   not gated (was 1031 before the console)
dependencies       6
services           7
```

**You can now run the whole loop in a browser.** Open `/`, start a session,
then open the red and blue windows side by side: fire cases from one, watch the
score move in the other, edit a Suricata rule and fire again.

## In progress

Nothing. Phase 2 is next.

## Done since v1.0

- **Phase 1: the red team got a REST surface, and the console got a shell.**
  The reason there was no red team screen was never the screen - firing an
  attack had no endpoint, and the rule is that every UI action is an API call
  first. `POST /api/sessions/<id>/attacks/` fires one catalogue case and
  records its ground truth; `/api/wargames/` and `/api/wargames/<id>/cases/`
  describe what can be fired.

  The console became four pages - main, session, red, blue - and the session
  number moved from a text box in the nav into the URL. That box was the
  reason the old console looked broken: nothing told you whether the number
  was right, and a session that did not exist rendered as an empty page. The
  `blueteam` app is now `console`, because it serves both teams, and the blue
  team's three pages are tabs on one screen so defending does not mean a page
  load between every rule edit.

  Two things were measured rather than assumed, both in DECISIONS: firing one
  case per request does not move the score, and `bin/measure` was undercounting
  untracked files - which had already produced one false green.

- **Phase 0: the ratchet split into `core_loc` and `product_loc`.** One number
  could not gate a hypothesis that must shrink and a product shell that must
  grow. `core_loc` covers scoring, ingest, rules and the harness and still only
  falls; everything else is reported.

- **Tried to replace Django entirely, and did not.** Built against `wsgiref`
  and `sqlite3`, verified green end to end, then discarded because
  `production_loc` went 1642 -> 1678. Two dependencies bought with 36 lines of
  routing and persistence we would own. No file changed; the whole result is
  the DECISIONS entry.

- **Translated the remaining Korean.** The design document and the README were
  still Korean, so CLAUDE.md's claim that the repo is written in English was
  not true. Every tracked file is English now except
  `docs/superpowers/plans/`, which is archived and which CLAUDE.md now names as
  the one exception. No metric moved; docs are never counted.

  Three pieces of drift surfaced while reading the design closely enough to
  translate it: it still described the platform as "Django + DRF", it called
  the Docker socket mount read-only when compose mounts it writable, and
  section 3.3 had been inserted ahead of 3.2. All corrected.

- **Shrank `redteam/harness.py`.** `Harness` had one public method and no
  state outliving the call, so it is functions now. `build_request` used to
  return a dict that `fire` unpacked back into a `requests.Request` - two
  representations of one thing - and returns the prepared request itself
  instead. `-11 LOC`.

  The tests improved with it: they assert on the prepared body, content type
  and query string, so they pin what leaves the process rather than what we
  meant to send. `check_path_preserved` was left exactly as it was.

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

The remaining phases of the product design. Take the top one.

### 1. Phase 2 - the labelled Kali terminal

A `kali` service running `ttyd`, framed in the red team window, so attacks can
be typed instead of chosen from a list. Labelling is a "start attack / stop"
pair in the UI that writes one `Case` with `correlation: "window"` and the Kali
container's address - which needs **no new endpoint**, because
`POST /api/sessions/<id>/cases/` already takes all four fields.

This is also what closes the known gap below: `window` correlation has never
run against the live stack. Add the acceptance test that scores a window case
in the same phase, or the gap moves rather than closes.

Costs one compose service. Write down why in DECISIONS when you add it.

### 2. Phase 3 - compare the two strategies

`GET /api/sessions/<id>/score/?correlation=marker|window|both`, and a mitmproxy
service that stamps `X-FSL-Case` onto the Kali container's traffic so the same
attack can be scored both ways at once. The user's reason for wanting this:
the scoring criteria are themselves under test, and a comparison is data.

Costs a second compose service.

## Known gaps

- **Window correlation is never exercised end to end.** `correlation: window`
  is implemented and unit-tested to its boundaries, but no case in
  `redteam/cases/` uses it, so it has never run against the real stack. It
  needs a non-HTTP tool (nmap) and the tool container's IP. Out of scope for
  v1.0 by the design document; close this gap before trusting the strategy.
- The `platform` container mounts the Docker socket to validate rules. It is a
  container escape path. Acceptable in a local lab, not beyond one.
