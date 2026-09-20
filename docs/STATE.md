# State

The handover between sessions. Keep it true; it is all the next session gets.

Updated: 2026-09-20 (backlog refilled by the user: segment the network)

## Where things stand

The repo moved from "prove the hypothesis" to "build the smallest product that
demonstrates it" on 2026-09-20. The design is in
`docs/superpowers/specs/2026-09-20-product-flow-design.md` and runs in four
phases; all four are done.

`bin/verify` is green: 175 unit/API tests, 29 acceptance tests against the live
stack. The hypothesis itself is untouched and still scores
`TP=6 FN=0 FP=0 TN=6`.

```
core_loc         611   gated, unchanged by the product work
product_loc     2716   not gated (was 1031 before the console)
dependencies       6
services           9   kali and proxy, both raised by hand - see DECISIONS
tests            198   a floor: it may only go up
```

**You can now run the whole loop in a browser.** Open `/`, start a session,
then open the red and blue windows side by side: fire cases from one, watch the
score move in the other, edit a Suricata rule and fire again. The red window
also has a Kali terminal - name an attack, press start, type it, press stop,
and it is scored two ways at once - by time and source, and by a marker the
proxy stamps - with both answers side by side in the blue window.

The blue window is a live console now: it ingests and redraws on a timer, so
alerts arrive while you watch rather than when you press something, and any
alert opens the whole Elasticsearch record behind it.

## In progress

Nothing. The product design is finished; the next item is not written yet.

## Done since v1.0

- **A verdict is the rule change, and it expires.** The alert drawer silences
  the signature that raised it; silenced rules are listed with their deadline
  and a restore button. Every suppression is a false-negative bet, so it comes
  back on its own - nothing here can be switched off for good. The rule is
  commented, not deleted, behind a readable `# fsl-suppressed until <time>`,
  and the original line is stored verbatim so restoring cannot drift.

  `core_loc` did not move: it is all built on the `current()` / `apply()` that
  `rules/suricata.py` already exposes, and the new `suppress.py` is pure text.

  The console does not show a score delta, because there is none: silencing a
  rule does not change alerts already ingested. `test/test_suppression.py` is
  the honest version - the attack is a true positive with the rule on and a
  false negative with it silenced, with a control case still detected so the
  silence is narrow rather than a broken pipeline.

- **Breaches are credited to the attack that took them.** Objectives were
  polled once at the end of a run, so all seven carried one timestamp and
  attribution handed them to whichever case fired last - benign traffic,
  detected by nothing. Coverage read 0% while the attack that took one of them
  was a true positive.

  Two causes, both measured. The platform used its own observation time, which
  trails the deed; it uses the target's `updatedAt` now, which is exact per
  solve. And the target records a solve ~80ms after answering while the red
  team fires the next case ~70ms later, so consecutive cases could not be told
  apart by time at all - the platform holds the case-recording response for a
  quarter second, which spaces them, because the red team blocks on it.

  `core_loc` did not move: the wait is in the API, not in `redteam/harness.py`.
  Recording a case now polls objectives as a side effect, best effort, and a
  target that cannot be asked never costs the case record.

- **The red team takes seven objectives instead of two.** The case file fired
  twelve payloads and took `errorHandling` and `loginAdmin` almost by accident;
  everything else tripped rules and achieved nothing. Four cases now claim an
  objective in a `takes:` field the catalogue and console read, and the
  acceptance suite derives what it asserts from that field rather than
  repeating it, so the two cannot drift.

  `sqli-union-in-search` became `sqli-union-user-table`: the old payload had
  the wrong column count, so Juice Shop errored, the IDS alerted and nothing
  was taken. Nine columns takes the user table. New: a confidential document,
  the metrics endpoint, and a double-encoded null byte that takes two
  objectives with one request.

  Every pair was verified against the live target - Juice Shop's keys and its
  display names disagree, so guessing them from the name does not work.

  Two of the new attacks are detected by nothing at all, on purpose. They are
  plain GETs of files the shop should not serve, so no signature could name a
  mechanism, and they carry no `expect`. An objective taken with nobody
  watching is the most useful line on the board.

  The acceptance suite now resets the target once per run, in `conftest`,
  because a run that starts from whatever the last one left behind measures
  that instead of the defence.

- **A true positive now has to name the right rule.** Each attack case declares
  `expect` - a substring of the signature that should be able to find it - and
  an alert that does not mention the attack's own mechanism is reported as
  `corroborated: false` with a warning. The arithmetic is unchanged on purpose:
  rewriting the TP would hide the disagreement rather than show it.

  Mahoney & Chan's one-byte detector scored 45% on DARPA - level with the best
  real systems of 1999 - and zero on real traffic, and no score of that era
  could tell. Measured here: all six attacks corroborate today, so the baseline
  is honest and a change that makes it dishonest is now visible. `core_loc` did
  not move; the check is in `scoreboard.py`, not in the hypothesis.

- **Objectives lead the score.** The old scoreboard was false positives and
  false negatives and nothing else, which is gameable - twelve fixed public
  payloads, so the blue team's optimal play is twelve matching rules - and
  which measured nothing real: a full twelve-case run achieves **zero** Juice
  Shop objectives while reporting `TP=6`.

  Juice Shop's 116 challenges are now the game. It flips `solved` itself, so
  the platform labels nothing about whether an attack achieved anything, and
  the ground truth is orthogonal to the detector - which is the property
  Sommer & Paxson require and which 5-tuple-plus-time-window labelling does not
  have. Losing an objective always costs, losing one unseen costs double, false
  positives stay separate. The red window leads with the objective list; the
  blue window leads with what was taken and whether it was seen.

  The target never has to be reset: each session snapshots what was already
  solved. DECISIONS has the reset command anyway, and why `--force-recreate` is
  not it.

- **The blue window became a monitoring console.** It ingests on a timer and
  appends only the rows it has not seen (`?after=`), so alerts arrive without a
  refresh - verified by firing attacks with the window open and watching the
  counts move. Event counts by engine, an activity histogram, source and text
  filters, an unattributed-only toggle, and a drawer that opens the raw
  Elasticsearch record behind any alert. `Detection.raw` had held that document
  since v1.0 and had simply never been served.

  Polling rather than WebSockets: channels and daphne would have put
  `dependencies` at 8 permanently, and the tools this imitates poll too. See
  DECISIONS.

- **Phase 3: both strategies score the same traffic.** A mitmproxy service
  stamps `X-FSL-Case` onto the terminal's traffic, reading the active marker
  from a file the platform writes, so one free-form attack now carries a marker
  *and* a source-and-time window. `?correlation=marker|window` on the score
  endpoint forces the strategy for every case, and the blue window shows both
  answers side by side.

  The trap, and it is a bad one: the proxy makes the outbound connection, so
  Suricata sees the proxy's address rather than Kali's. Labelling a window with
  the Kali address would have matched nothing and blamed the defence for it.
  `/api/attacker/` reports the address alerts actually carry. Full reasoning,
  including why the two strategies are not symmetric, is in DECISIONS.

  Cost the second service.

- **Phase 2: the Kali terminal, and the known gap is closed.** A `kali` service
  runs `ttyd`, framed in the red team window. Labelling is a start/stop pair
  that writes one `Case` with `correlation: "window"` and the container's
  address - no new endpoint, because `POST /api/sessions/<id>/cases/` already
  took all four fields. `GET /api/attacker/` answers where the traffic will
  come from, and refuses to guess when the box is down.

  **`correlation: window` has now run against the live stack.** It had been
  unit-tested to its boundaries since v1.0 and never exercised end to end.
  `test/test_window_correlation.py` scores an unlabelled attack typed from Kali
  as a true positive, keeps an adjacent benign window clean, and proves the
  matched alerts carry no marker so it cannot pass via the marker path.

  Cost one service, raised by hand. `ttyd` is not in Kali's repos and the Kali
  mirror redirect breaks TLS before `ca-certificates` exists; both are in
  DECISIONS, as is the four-second minimum between consecutive windows.

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

The user's direction: make the range look and behave like a real network -
a topology anyone can see, defence at the network layer and not only at the
application, and real network appliances if they can be had.

Measured first, because it changes the order. **The defence is optional.**
Everything sits on one flat `172.20.0.0/16` bridge, so the attacker container
can reach the target directly and both the WAF and the IDS disappear:

```
through the WAF   proxy .7 -> waf .4 -> juice-shop .2    4 Suricata events, 2 alerts
around it         kali  .8 ------------> juice-shop .2    0 Suricata events
```

Same SQLi payload, one `--noproxy` flag. Suricata sniffs the WAF's `eth0` from
inside its network namespace, so traffic that never touches the WAF does not
exist as far as the range is concerned. Anyone at the red team terminal can
take every objective and score no alerts at all. That is not a missing feature;
it makes the score meaningless against an attacker who knows the address.

### 1. Segment the network so the defence cannot be walked around

Split the flat bridge into at least attacker / DMZ / app / management, route
between them through a gateway container, and move Suricata off the WAF's
namespace onto the gateway, where it sees traffic between segments rather than
one host's interface.

The acceptance test writes itself and should be written first: the bypass above
must stop working - either refused, or detected. It is the same shape as
`test_suppression.py`, a control case that still works beside the one that
should not.

Costs `services` and probably several compose networks. Each new service costs
a line in DECISIONS, which is the designed friction, not an obstacle.

### 2. Show the topology, generated rather than drawn

The compose file and `docker inspect` already describe the whole range:
segments, addresses, which host each sensor watches. A diagram generated from
them is live and cannot rot; a drawing of it would be wrong within a session.
Worth doing after item 1, when there is a topology worth drawing.

Show where each alert came from, so the picture and the alert stream are the
same object rather than two.

### 3. Real network appliances - feasibility checked, and it is mixed

The two named are not container-shaped, and this is worth knowing before
anyone starts:

- **pfSense / OPNsense** are FreeBSD. There is no usable Docker image; they
  want a VM. The OpenStack path CLAUDE.md names in the fixed stack is the
  honest route, and it is a large step.
- **NAC (PacketFence)** enforces at layer 2 with 802.1X and RADIUS against
  switch ports. A Docker bridge has no port to enforce on and no supplicant,
  so there is nothing for it to do. It needs a virtual switch to be more than
  a decoration.

Container-shaped substitutes that would give item 1 its gateway: VyOS, an
nftables router, OpenWRT. **Nobody has checked whether these publish arm64
images**, and this stack requires arm64 - check that before designing around
one.

## Known gaps

- The `platform` container mounts the Docker socket to validate rules, and the
  Kali terminal is an unauthenticated root shell on 7681. Both are container
  escape paths, acceptable in a local lab and nowhere else.
- Two labelled terminal windows less than four seconds apart overlap, because
  `WINDOW_SLACK` is two seconds at each end. The console does not say so on
  screen yet. See DECISIONS.
- Nothing stops two people opening the same session in four windows. One user,
  one session was a deliberate scope decision; revisit it only if the answer to
  "who is in front of this" changes.
