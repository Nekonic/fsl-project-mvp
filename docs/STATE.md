# State

The handover between sessions. Keep it true; it is all the next session gets.

Updated: 2026-09-20 (the target is a site, and the red team is a box with tools on it)

## Where things stand

The repo moved from "prove the hypothesis" to "build the smallest product that
demonstrates it" on 2026-09-20. The design is in
`docs/superpowers/specs/2026-09-20-product-flow-design.md` and runs in four
phases; all four are done.

`bin/verify` is green: 246 unit/API tests, 87 acceptance tests against the live
stack. The hypothesis itself is untouched and still scores
`TP=6 FN=0 FP=0 TN=6`.

```
core_loc         611   gated, unchanged by the product work
product_loc     3415   not gated (was 1031 before the console)
dependencies       6
services           8   one attacker image now, not two - see DECISIONS
tests            273   a floor: it may only go up
```

**You can now run the whole loop in a browser.** Open `/`, start a session,
then open the three windows side by side: fire cases from one, watch the
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

- **The target is a site, not the appliance in front of it.** The shell was
  told to attack `waf-edge:8080`, which tells an attacker that a WAF exists,
  what it is called, and that the site is a lab on a high port. It answers to
  `http://shop.com` now - no port, because a site does not have one.

  Port 80 needed a sysctl (nginx runs as uid 101 in the CRS image) and a no-op
  over the image's own low-port guard, whose assumption the sysctl makes
  untrue. The host still publishes 8080: that is the operator's browser, not
  the attacker's view.

  The name was doing two jobs - naming the site and choosing which segment to
  leave by - so they are separated. The public name is aliased on one segment,
  which makes it unambiguous from a box attached to four; the `waf-<origin>`
  names stay as pure routing and nobody types them. The shell always dials the
  site, and the console's origin selector writes a file the stamping proxy
  reads per request, rewriting the connection host while leaving `Host` alone.

- **The red team is a box, not a button list.** Every case encodes a path only
  this target has, which is right for a baseline and useless as an attacker.
  The shell now has the tools to be one - nmap, whatweb, ffuf, gobuster,
  nikto, sqlmap, hydra, curl, wget, nc, dig, jq - and the red window leads
  with it, with the buttons below labelled as the scripted baseline.

  One attacker image instead of two: a case with `tool:` runs in the same
  image the shell opens on, so neither can depend on something the other
  lacks. `services` went 9 to 8.

  Two routes out, and the console says which: HTTP goes through the stamping
  proxy and carries its address, raw TCP leaves from the box itself. A window
  records whichever the work will use, because the wrong one matches no alert
  and reads as a defence that missed.

  The scanners are **not** cases, and that was measured rather than assumed -
  see the backlog.

- **The console no longer runs the attacks it collects.** A script-tag payload
  went out as a case, came back as a request path, and the board rendered it
  into `innerHTML`. Juice Shop's own challenge text did it too - it describes
  its DOM XSS challenge with an iframe whose src is `javascript:`, and the red
  window drew that as markup. Every value interpolated into markup now goes
  through one `esc()`, and a test scans the templates for any that does not.

  The comment explaining the fix broke the console, because it contained a
  literal closing script tag: the HTML parser ends the element at the first
  one it sees, so everything after it stopped being JavaScript and `esc`
  silently did not exist. Tested for now as well.

- **The board is top-N tables, the way real consoles are.** Rebuilt after two
  attempts put the wrong things on it, both from summaries rather than the
  source. Cloudflare's security events screen is a summary, one time series
  and top events by source - each a table of a dimension with its count.
  Igloo's names the thing that makes an address useful: the engine that raised
  an alert is obvious, but what its source and destination *belong to* is not.

  So: top source addresses with zone and country, top destinations with zone,
  top signatures with engine, top request paths with method - and the same
  zone and destination columns beside `From` in the alert list. `topology.py`
  is the zone registry now, not a diagram.

  Off the board: the segments table (how this range is built is a finding for
  this file, not for a room watching traffic) and the Host column (it showed
  an internal Docker alias, and Cloudflare's "host" is the attacked domain).

- **The console is two windows, because it is watched from two distances.**
  It had become a document - map, then topology, then counters, then the alert
  list, each appended below the last on one scroll. Making it a grid on one
  screen did not fix it: a control room has a **status board** read from
  across the room and an **analyst screen** read sitting in front of it, and
  neither is a section of the other.

  `/board/<id>/` is the board. `/blue/<id>/` is the alert list: filters, the
  table, the whole log record behind a row, plus the scoreboard and the rules.
  The session page opens three windows now.

  An acceptance test keeps the two disjoint, because this went wrong by
  accretion and would go wrong again the same way.

  Two traps: Django's `{# #}` is single-line only, so the multi-line ones
  rendered across the top of the console; and `hidden` versus `flex` is
  decided by the order Tailwind emits them, so showing a tab sets `display`
  outright.

- **The console draws the range, from the range.** `GET
  /api/sessions/<id>/topology/` reads the shape off Docker - segments from the
  compose project label, addresses from `network inspect`, outside from
  `fsl.origin` - and the blue window draws it under the map. Nothing is
  maintained beside the stack, so the only way for the picture to be wrong is
  for the question to be wrong.

  It said two true things immediately, neither of them visible before:

  ```
  ways in: waf, platform        unwatched: mgmt
  ```

  A crossing had to be defined as a foot on each **side** rather than on two
  networks - the proxy is on all four origins and crosses nothing, because
  they are all outside. That leaves the WAF, which is the design, and the
  platform, whose simplification compose has admitted in a comment since the
  segments were made. A comment nobody opens and an amber box beside the
  alerts are not the same thing.

  Suricata is placed by resolving `NetworkMode: container:<waf>`: it is on no
  network of its own, so a diagram built from networks alone has no IDS in it.

  The numbers on it are the alerts, not a second count - `placed + unplaced ==
  alerts` is an acceptance test - which is what makes it one object with the
  stream beside it rather than a decoration.

- **The attacks come from four countries.** A subnet is a place on the map and
  the bridge driver refuses more than one subnet on a network, so each origin
  is its own network - `edge-br`, `edge-hk`, `edge-kp` beside `edge`. Nothing
  had to be taught to use them: a container on all four picks its source
  address by routing, so dialling `waf-edge-hk` *is* the choice of origin, and
  the WAF already answered under per-network aliases. `core_loc` did not move.

  The red window has a selector - a place, or Rotate - and `GET /api/origins/`
  is the whole of it. Origins are discovered from a `fsl.origin` label on the
  network rather than listed in Python, because a list would be a second copy
  of the compose file that decides which addresses exist.

  Three things are silent when wrong and all three had to be right before one
  alert appeared: every origin subnet in `HOME_NET`, every new `ethN` in the
  af-packet list, and every name sorting after `edge` so the published port
  does not move back inside the estate. See DECISIONS.

  One rotating run: Russia 6, Brazil 6, Hong Kong 3, North Korea 3.

- **A breach is no longer handed to the case before it.** `bin/verify` came
  back red on a test this work does not touch. With `platform/` and `redteam/`
  reverted to HEAD on the same stack it failed **three runs in four**, so the
  baseline was already carrying it.

  The target records a solve on its own clock, 19-26ms *before* the attack
  that caused it was stamped on the firing side's, and `attribute()` required
  `started_at <= achieved_at`. The skew cannot be subtracted - a `docker exec`
  round trip is ~40ms, so it cannot be measured to better than its own size -
  so the fix is `CLOCK_SKEW = 100ms` on the lower bound and nothing else.
  Four runs in four now.

- **The console has a map and the attacks are on it.** `GET
  /api/sessions/<id>/map/` returns origins as points; the Live tab draws them
  over coastlines generated by `bin/worldmap` from Natural Earth and committed,
  so nothing is fetched at runtime. The projection is generated rather than
  borrowed because most "equirectangular" world SVGs are clipped and would put
  points tens of pixels off with no assertion able to notice - checked by eye
  against ten known cities first.

  Geolocation turned out to belong to the **address**, not the alert: only
  Suricata's records keep the whole document, so ModSecurity's carry no geo at
  all. Placing each address once and then counting every alert from it avoids
  both halved origins and a change to `ingest/elastic.py`, which is gated.
  `core_loc` did not move.

  Rotation was measured and split out - see the backlog. The bridge driver
  refuses multiple subnets on one network, so a second origin country is a
  second network.

- **The IDS rules match attacks rather than encodings.** A space sent as `+`
  instead of `%20` is a space to the application but not to a `\s`, so the same
  injection was caught one way and slid past the other. `[\s+]` on sids
  9000001-9000003 closes it, and the benign cases stayed true negatives - which
  was the real risk, since the class is more permissive.

  The claim had to be narrowed twice before it was true, and both corrections
  are in DECISIONS. The stack was never evaded: ModSecurity catches this by
  other means, so a combined verdict says "detected" either way and the hole
  was invisible. The test therefore asks **which engine fired**, not whether
  anything did.

  It also turned up a trap worth knowing: sessions overlap in time, so a
  readiness check that asks what is in a session's window is answered by the
  neighbouring session's traffic. Wait on the control case.

- **The front door is on the outside.** Traffic to the published port reached
  the WAF on its estate-side address, so the range's own attacks were logged as
  coming from inside. Docker picks that target by **network name,
  alphabetically** - not by `priority`, which changed nothing - so `app` became
  `estate` and `edge` now sorts first. Console-fired attacks needed a separate
  fix: the platform shares both segments with the WAF, so network-scoped
  aliases (`waf-edge`, `waf-estate`) name the way in rather than the host.

  ```
  before  src=172.30.0.1 -> 172.30.0.3   inside
  after   src=5.188.10.1 -> 5.188.10.4   outside
  ```

  And a correctness bug this uncovered: **Filebeat's registry lived inside the
  container**, so every recreate re-shipped every log from the beginning -
  14,242 stale events landed in the last-ten-minutes window and would have been
  scored as current. It is a named volume now. See DECISIONS, along with the
  data-stream deletion that cleaning up required.

- **The network is segmented and the defence is no longer optional.** Three
  networks replace one flat bridge: `edge` on public space where the attacker
  lives, `app` and `mgmt` on RFC 1918. The WAF is the only member of both
  `edge` and `app`, so it is the way across by topology rather than by policy,
  and Suricata - still in its namespace - now watches a real choke point on
  both interfaces.

  The bypass that made every score meaningless returns `000` where it used to
  return `200`, and the attacker sits at `5.188.10.3`, which geolocates. **No
  new service**: `services` is still 9.

  The first verify after this was red and it was a cold stack, not the change.
  See DECISIONS - that trap has now cost two sessions.

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

### 1. A marker a scanner can carry

Adding nmap and nikto to the catalogue was tried and withdrawn. The marker is
appended as `--headers=X-FSL-Case: <id>`, which is sqlmap's syntax; neither
tool takes it, so both came back `FN` with zero alerts while plainly reaching
the target. That is a harness failure recorded as a defence failure.

ffuf, gobuster, curl and whatweb all take a custom header, so a per-tool flag
in `SUPPORTED_TOOLS` would cover most of it. nmap and nikto cannot carry one
at all: either they are correlated by window - which needs the tool container
to have a known address, and `--ip` on the run would give it one - or they
stay at the shell, where a labelled window already scores them.

Worth doing only if the scripted baseline should include recon at all. It may
not: the argument for the shell is that recon is what a person does.

## Known gaps

- **State the console can change survives the session that set it.** The
  chosen origin and any rule suppression are files, with no expiry a test run
  respects, and both fail as something else: "attributed to an address on the
  wrong continent", "the probe raised no alert at all". The acceptance suite
  resets the origin and refuses to run while anything is suppressed. Anything
  added with that shape needs the same treatment.

- **Never `docker network rm` a compose network while its containers run.**
  They reconnect without their service alias, nothing warns, and the failures
  read as something else: the WAF died on `host not found in upstream
  "juice-shop"` and took Suricata with it; later every ingest returned 503.
  `docker compose up -d --force-recreate <service>` puts the alias back. This
  cost an hour twice in one session - see DECISIONS.

- The `platform` container mounts the Docker socket to validate rules, and the
  Kali terminal is an unauthenticated root shell on 7681. Both are container
  escape paths, acceptable in a local lab and nowhere else.
- Two labelled terminal windows less than four seconds apart overlap, because
  `WINDOW_SLACK` is two seconds at each end. The console does not say so on
  screen yet. See DECISIONS.
- Nothing stops two people opening the same session in four windows. One user,
  one session was a deliberate scope decision; revisit it only if the answer to
  "who is in front of this" changes.
