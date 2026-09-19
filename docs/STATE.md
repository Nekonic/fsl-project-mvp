# State

The handover between sessions. Keep it true; it is all the next session gets.

Updated: 2026-09-19 (v1.0 + 1 backlog item)

## Where things stand

v1.0 proves the hypothesis. `bin/verify` is green: 103 unit/API tests, 11
acceptance tests against the live stack.

Last full run: `TP=6 FN=0 FP=0 TN=6`, no pipeline warnings. Adding a rule that
matches `apple` turns `normal-product-search` into a false positive and moves
precision to 0.83 — so the score responds to defence changes in the predicted
direction, which is the whole point.

```
production_loc  1684   (v1.0: 1703)
dependencies       6   (v1.0: 7)
services           8
```

## In progress

Nothing. Start at the top of the backlog.

## Done since v1.0

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

### 1. Remove Kibana

One service, roughly 1GB of RAM, and zero lines of code that anything else
needs. The blue team console already lists detections, and Elasticsearch stays,
so ad-hoc queries are still possible with curl. Expect `-1 service`.

Worth stating the loss: Kibana is genuinely useful for a defender pivoting
through logs, and the production repo may well want it back. It earns nothing
for *this* repo's hypothesis.

### 2. Delete the dead marker-probing in `ingest/elastic.py`

`_MARKER_KEYS` tries four spellings and `_header_lookup` then does a
case-insensitive sweep. That was written before we knew where the marker
actually lands. We now know: Suricata puts it in `http.request_headers` as a
list of `{name, value}`, ModSecurity in `transaction.request.headers` keyed
exactly `X-FSL-Case`. Expect `-15 LOC`.

Keep one test per real shape. Do not keep tests for spellings we invented.

### 3. Collapse the Django boilerplate

`fsl/urls.py`, `fsl/wsgi.py`, `api/apps.py`, `blueteam/apps.py`,
`blueteam/urls.py`, `api/urls.py`, `manage.py` are 45 lines across seven files,
most of them ceremony. Routing could live in one module. Expect `-20 LOC` and
four fewer files.

### 4. Shrink `redteam/harness.py`

191 lines, the second largest file. `Harness` holds three fields and could be
functions taking a `requests.Session`. Do not touch `check_path_preserved` — it
guards a real bug that made the score lie (see DECISIONS).

### 5. Consider replacing Django entirely

The largest remaining win and the riskiest. Django plus DRF is two dependencies
carrying an ORM, migrations, templates and routing for five models and ten
endpoints. `sqlite3` and a small framework would be a fraction of that.

Do not start this until 1-4 are done; by then the Django surface will be small
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
