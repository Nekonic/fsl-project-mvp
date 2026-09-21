# Decisions

Append-only. What was tried, what was rejected, and why.

Read this before proposing anything that feels obvious — most of it was already
obvious to someone, and cost a session to disprove. Add to it when an attempt
fails, especially then: a failed attempt written down is worth more than a
half-finished one that is not.

Newest last.

---

## The marker join key is `(flow_id, tx_id)`, not `flow_id`

Suricata alert events carry no HTTP request headers; the marker lives on the
http event of the same transaction. Joining them on `flow_id` alone seems
right and is wrong: under HTTP keep-alive a dozen requests share one TCP flow,
so the flow's first marker gets pinned onto every alert in it and all of them
are attributed to the first case.

This hid for a long time because ModSecurity alerts carry the marker directly,
and they outnumbered Suricata's. The score looked plausible while being false.
It surfaced only when a path-traversal alert turned up wearing the
`sqli-login-bypass` marker.

Alert and http events pair up exactly by `tx_id`. Verified against the stack.

## Suricata `eve-log ... custom: [X-FSL-Case]` does nothing

On Suricata 8.0.7 it has no effect — the header appears nowhere. Verified
directly. `dump-all-headers: request` does work and is what the config uses.

## Suricata path-traversal rules must match `http.uri.raw`

`http.uri` is the normalised buffer: `%2F` is decoded and dot segments are
removed, so `..%2F..%2F` never matches there. The raw buffer sees it.

## Suricata runs in the WAF's network namespace, not host mode

`network_mode: host` attaches to the Linux VM's namespace under Docker Desktop
and colima, so behaviour varies by host. `network_mode: "service:waf"` puts
Suricata on the WAF's `eth0`, which carries both the attacker-to-WAF and
WAF-to-Juice-Shop legs.

## The stack needs a native arm64 Docker host

Elasticsearch's amd64 JVM dies with SIGSEGV under x86 emulation (colima
`vmType: vz`, `arch: x86_64`) on an Apple Silicon host. The symptom is
`starting java failed with [134]`. Run `colima start --profile fsl`.

## ModSecurity overrides mount at the template path

The CRS image generates `/etc/modsecurity.d/modsecurity-override.conf` from a
template with envsubst at boot. Mounting over the destination makes the
container fail to start with "can not modify ... (read-only file system?)".
Mount at `/etc/nginx/templates/modsecurity.d/modsecurity-override.conf.template`.

## Juice Shop's healthcheck must call node by absolute path

The image is distroless: no shell, no wget, no curl, and `node` is not on
`PATH`. Use `/nodejs/bin/node -e '...'`.

## ModSecurity runs in DetectionOnly

Blocking would stop attacks reaching Juice Shop, which would measure blocking
rather than detection.

## Attack cases must not contain a literal `..`

`requests` normalises `/ftp/../../../../etc/passwd` to `/etc/passwd` before
sending, so the traversal never leaves — while ground truth still records
"attack sent". The score then counts a miss where the harness, not the defence,
failed. Use `%2e%2e`. `check_path_preserved` in `redteam/harness.py` now fails
loudly on any such rewrite; do not remove it.

## `platform/` and `test/` are not Python packages

`platform` and `test` are both stdlib module names. An `__init__.py` in either
makes them importable and able to shadow the standard library. Run Python with
`platform/` as the working directory instead.

## The repo is written in English

Korean costs roughly twice the tokens per line and every session pays to re-read
it. Comments, docstrings, commit messages and documents are English; the
conversation with the user stays Korean.

Converting v1.0 grew `production_loc` by 19 and the ratchet refused the commit.
Rather than granting an exception on the ratchet's first use, the comments were
tightened until the total came out one line *below* the old baseline. Keep that
precedent: the ratchet is not negotiable on day one, or it is not a ratchet.

## Benign cases stay

Deleting normal traffic from `redteam/cases/` is the fastest way to make any
score look excellent and the platform worthless. `bin/verify` checks TN > 0 for
this reason.

## Replacing a bind-mounted file breaks the running container

`waf` and `suricata` have single *files* bind-mounted in, not directories.
Docker resolves those to an inode when the container is created. Anything that
replaces the file on the host - `git checkout`, `git reset --hard`, a history
rewrite, an editor that writes via rename - leaves the container holding a
deleted inode, and its config silently disappears.

It surfaced during the v1.0 history cleanup: replaying trees rewrote
`deploy/suricata/suricata.yaml`, and rule validation then failed with
`failed to open file: /etc/suricata//suricata.yaml`, while ModSecurity stopped
producing alerts entirely. Two acceptance tests failed and both looked like
defence failures.

`docker compose restart` does not fix it - the mount is resolved at creation:

```bash
docker compose up -d --force-recreate waf suricata
```

`bin/verify` now checks for this before running the acceptance tests, on the
same principle as everything else here: infrastructure breakage must never be
recorded as a detection result.

## Never truncate a log file Suricata has open

`: > deploy/suricata/logs/eve.json` leaves the file full of NUL bytes, because
Suricata keeps writing at its old offset. Filebeat then fails with
`Error decoding JSON: invalid character '\x00' looking for beginning of value`
and stops shipping that file, so detections silently stop arriving.

Read from a saved byte offset instead (`wc -c` before, `tail -c +N` after), or
restart Suricata after truncating.

## A cold stack looks exactly like a broken defence

Sessions created in the first minutes after `docker compose up` can ingest zero
detections: Elasticsearch, Filebeat and the WAF are still settling. The score
then comes back all-FN, and the acceptance criteria used to report that as "no
attack was detected at all" - the hypothesis failing.

It cost a full diagnosis to establish that the code was fine and the pipeline
was empty. `score_when_ready` now checks for that case and fails with the real
reason. Same principle as the bind-mount guard in `bin/verify`: infrastructure
state must never be recorded as a detection result.

## Replacing Django with stdlib WSGI + sqlite3 was built, measured and rejected

It works. It is bigger. The ratchet refused it and that was the right answer.

The whole platform was rewritten against `wsgiref` and `sqlite3`: a regex
router where handlers register themselves with `@route`, one shared sqlite
connection, and column names chosen to match the JSON field names so a row is
already almost a response. Django template inheritance became marker
substitution in `blueteam/views.py`. The API contract did not move one byte.

It passed everything except the measure of progress:

```
unit + API tests    103 passed (0.07s, against 0.51s under Django)
acceptance (live)    11 passed  - the hypothesis holds without Django
production_loc     1642 -> 1678  REFUSED
dependencies          6 -> 4     Django and pytest-django both gone
services              7 -> 7
```

Where the 36 lines went, after an honest tightening pass had already taken 20
out of a first draft at 1698:

| | |
|---|---|
| `api/views.py` | 189 -> 206 — every ORM call became SQL and a shaped dict |
| `fsl/db.py` 89 | against `api/models.py` 83 — schema, encode, decode |
| `fsl/app.py` 61, `serve.py` 13, `fsl/config.py` 18 | 92 against settings 48 + urls 22 + manage.py 9 |
| `blueteam/views.py` | 12 -> 29 — the template engine had been free |
| templates | 198 -> 183 — the one place that genuinely shrank |

So the trade is exact: **two dependencies and a framework, bought with 36 lines
of routing and persistence that are now ours to maintain.** Deleting Django's
configuration does not delete Django's work; it moves it into the repository.

Two things are worth keeping from the attempt. The rewrite was far easier than
its reputation - one session, and the existing tests needed a new `conftest`
rather than new assertions, because they had always spoken HTTP. And the tests
got six times faster, which is a real cost Django was charging every run.

Neither is worth 36 lines. `production_loc` is the metric this project chose
for "simpler", and it says this is not simpler. Editing `metrics.json` to let
it through was considered and refused: the growth here is avoidable - keeping
Django avoids it entirely - so it does not meet CLAUDE.md's bar of "genuinely
unavoidable", and the second hand-granted exception is the one that ends the
ratchet. The v1.0 precedent stands.

Do not rerun this experiment without new information. The two things that would
change the answer: Django removed for a reason other than size (it is not on
the fixed-stack list, so a licence, a CVE or a hosting constraint could force
it), or `api/views.py` shrinking enough that the hand-written persistence layer
stops being the dominant cost.

## Firing one case per HTTP request does not move the score

`run()` keeps one `requests.Session` for a whole CLI run, and says why: the
traffic has to keep HTTP keep-alive, because a shared TCP flow is what the
`(flow_id, tx_id)` correlation exists to cope with. The console fires one case
per request, so each case gets its own flow. The worry was that this quietly
makes correlation easier and the score better than it should be.

Measured instead of argued. The same twelve cases, same stack, same rules:

```
CLI run (session 1)   TP=6 FP=0 FN=0 TN=6   alerts 4, 5, 7, 7, 1, 94
API run (session 5)   TP=6 FP=0 FN=0 TN=6   alerts 4, 5, 7, 7, 1, 94
```

Not one alert different. No workaround was added, and the platform does not
hold a `requests.Session` per session.

The reasoning behind the result is the opposite of the worry: one case per flow
makes attribution trivial, so the score cannot get worse. What it does mean is
that the console path no longer *exercises* the hard case. That still matters,
and `test/` still covers it, because the acceptance fixture drives the CLI
harness with its shared connection. If that ever changes, the keep-alive
condition stops being tested anywhere and this entry is wrong again.

Firing from inside the network is also about twenty times faster - twelve cases
in 1.5s against roughly 30s - because the platform container reaches the WAF
directly instead of through the host's published port.

## bin/measure does not count what git does not track

It counts `git ls-files`. A file that has been written but not added is
invisible to it, so a change that adds six new files can report that the
project got *smaller*. That happened while building the console: it printed
`product_loc 1031 -> 945` and `bin/verify` said all green. The real number was
1370.

This is the worst shape a measurement bug can take here - it fails towards
"you are doing well" - and nothing else in the run would have caught it.

`bin/verify` now refuses to measure a tree with untracked, non-ignored files
and names them. Same principle as the bind-mount guard and the cold-stack
guard: a broken measurement must never be recorded as a result.

## The Kali terminal costs one service, and the ratchet was told so by hand

`services` went 7 -> 8 and `bin/verify` refused the commit, which is what it is
for. The baseline was raised by hand rather than the service being dropped.

The reason it is worth a service: every case in `redteam/cases/` carries the
`X-FSL-Case` header, so until now the only attacks the platform could score
were ones it had written itself. A person could not sit down and attack the
range. The terminal is what makes the red team a role rather than a script, and
it is what the second correlation strategy exists to serve.

What it bought, beyond the screen: `correlation: window` ran against the live
stack for the first time. It had been implemented and unit-tested to its
boundaries since v1.0 and never once exercised end to end - the known gap in
STATE.md. `test/test_window_correlation.py` now scores an unlabelled attack
typed from the Kali box as a true positive by source IP and time, keeps benign
traffic in an adjacent window clean, and asserts that the alerts it matched
carry no marker, so it cannot pass by accidentally using the marker path.

Two things that bit while building it:

`ttyd` is not packaged in Kali. The upstream static aarch64 build is pinned
and checksummed in `deploy/kali/Dockerfile` instead. arm64 only, which this
stack already required.

`http.kali.org` redirects to a nearby mirror, and some of those serve https
with a certificate the base image cannot verify - because `ca-certificates` is
exactly what the build is there to install. The build failed on that bootstrap
loop with an error that said nothing about it. The Dockerfile pins
`http://kali.download/kali`.

The terminal is a root shell with no authentication, published on 7681. That is
the same bargain as the Docker socket the platform already mounts: acceptable
on a single-host lab, not beyond one.

## Consecutive time windows need more than four seconds between them

`WINDOW_SLACK` is two seconds at each end, so two windows less than four
seconds apart overlap and one window's traffic is attributed to both cases.
The acceptance test leaves six.

This is not a bug: the slack exists because a request's alert can land either
side of the window it belongs to. But it does mean the console's "start / stop"
labelling cannot be used to mark two attacks in quick succession, and whoever
adds a second labelled window to the UI should say so on screen.

## Proxying the terminal moves the source IP, and that is the whole trap

The stamping proxy costs a service (8 -> 9, raised by hand) and buys the one
thing neither strategy could do alone: a single piece of free-form traffic that
carries both a marker and a source-and-time window, so the two can be scored on
identical evidence. `GET /api/sessions/<id>/score/?correlation=` forces the
strategy for every case, which is what makes the two runs comparable.

The trap is that mitmproxy is the one making the outbound connection. The WAF -
and therefore Suricata, which runs in its namespace - sees **the proxy's**
address, not Kali's. Window correlation labelled with the Kali container's
address would have matched nothing at all, and scored every terminal attack as
a miss charged to the defence.

Verified directly. With a marker set, the probe appears in Suricata's log twice:

```
event: http  src_ip: 172.20.0.7 (proxy -> waf)   X-FSL-Case = stamp-probe-abc
event: http  src_ip: 172.20.0.4 (waf -> juice)   X-FSL-Case = stamp-probe-abc
```

So `/api/attacker/` reports the address alerts will actually carry, which is
`ATTACKER_SOURCE_CONTAINER` (the proxy) and not `ATTACKER_CONTAINER` (Kali).
Two settings that look like they should be one, on purpose: when the proxy goes
away, they diverge again and the second is what matters.

It also means the two strategies are not symmetric. The marker is stamped on
both legs of the request, so marker correlation can match alerts on the
WAF-to-target leg; window correlation, labelled with the proxy's address, only
sees the attacker-to-WAF leg. They agree today because the rules fire on the
first leg. If they ever disagree, look here before looking at the defence.

The marker is passed as a file on a shared volume rather than an API the proxy
serves. The proxy reads it per request, so there is nothing to restart and no
second service to keep in step.

## The live console polls, and does not push

Watching a defence happen cannot mean pressing a button. The options were
WebSockets (django-channels plus an ASGI server), server-sent events, or
polling.

Polling won on the metric that is actually gated. `dependencies` would have
gone 6 -> 8 for channels and daphne, and that is a permanent cost on every
install for a console with one user. Server-sent events need no dependency but
hold a worker thread per open tab under `runserver`, which is the same bargain
with a subtler failure. Kibana and Cloudflare's own event views poll on an
interval; this is not a compromise, it is what the tools being imitated do.

What made polling cheap enough to feel live is that the list is incremental.
`?after=<row id>` returns only what the console has not seen, so a two-second
tick moves a handful of rows rather than re-sending eight hundred. A bad
`after` is a 400 rather than a silent fallback to everything: falling back
would arrive on screen as a sudden flood of alerts that are not new, which is
exactly the wrong thing to show someone watching for an attack.

Filtering stayed on the client. The console already holds every row it has been
sent, so a source filter or a search should not cost a round trip, and the
server keeps one query.

The raw log needed no new storage. `Detection.raw` has held the whole
Elasticsearch document since v1.0 and was simply never served - the list
response omits it on purpose, because it is far too heavy per row. One detail
endpoint was the entire change.

## The target judges its own defeat, and that is the point

Scoring was false positives and false negatives and nothing else, and the user
put the objection plainly: it is easy to game and it does not feel like
attacking anything. Both halves are right, and the second one turned out to be
measurable.

Gaming: `redteam/cases/` is twelve fixed, public payloads. The blue team's
optimal play is not to defend but to write twelve rules that match them
exactly. `TP=6 FP=0` while the thirteenth attack walks in.

Not attacking anything: a full twelve-case run was measured against Juice
Shop's own challenge API and achieved **nothing**. The score read `TP=6` - six
attacks, all detected - while the shop was untouched. The two objectives that
had ever fallen, `Login Admin` and `Error Handling`, were taken by the red team
long ago and the platform never counted them.

So objectives now lead the score, and Juice Shop decides them: 116 challenges
with a name, a category and a difficulty, and a `solved` flag the application
sets itself. The platform labels nothing here.

The shape is the one cyber defence exercises settled on. CCDC scores service
uptime, injects and compromise, and detection enters only as mitigation - an
incident report that correctly identifies a red team attack reduces that
event's penalty, with no partial credit for a vague one. NSA CDX plants known
tokens and scores whether they leak; DEF CON attack-defense scores flags
stolen. None of them scores detection mechanically at all. So: losing an
objective always costs, losing one you never saw costs double, and false
positives stay beside the damage rather than inside it.

False positives are not demoted. A defence that sees every attack by alerting
on everything has defended nothing, and blending the two numbers would let it
look as though it had.

**The literature says this is the right fix, in the terms it uses.** Every
labelled IDS dataset since DARPA 1998 labels by the same rule this repo uses -
5-tuple plus time window - and its documented failure mode is exactly the one
measured above. Engelen et al. (WTMC 2021) on CICIDS2017: the strategy "relies
solely on a flow's source and destination IP and a specific data collection
window", so "a resulting flow's content and characteristics are not verified".
Failed attacks, refused connections and attacks against closed ports all
inherit the attack label. Flood et al. (IEEE EuroS&P 2024) found no paper that
appeared to be aware it was working with failed attack data.

Sommer & Paxson (IEEE S&P 2010) state the requirement: "One must collect
ground-truth via a mechanism orthogonal (unrelated) to how the detector works."
The target's own verdict is orthogonal. That is what makes it worth a model.

Two things worth keeping from the reading:

- Public datasets' attack windows are always slightly wrong, and every
  re-labelling team had to retune them by hand. This repo executes the attacks,
  so it records exact start and stop times at source. Do not lose that.
- `TP > 0` does not prove the hypothesis. Mahoney & Chan (RAID 2003) built a
  detector that scored competitively on DARPA by reading one byte of the source
  address and dropped to zero detections on real traffic. The next honest step
  is to check *which* signature fired and whether its evidence matches the
  attack's mechanism, not only that something fired.

## Attribution is by last attempt, not by enclosing window

An objective's time is when the platform noticed the flip, which trails the
deed by up to one poll interval. Requiring that observation to land inside a
case's own window - often a tenth of a second wide - would attribute almost
nothing to anybody. An objective is credited to the last attempt that started
before it, within two minutes. Outside that it belongs to nobody and is
reported undetected, which is honest: no alert was tied to it either.

## The target's solved state survives a restart, and mostly survives a recreate

`docker compose restart juice-shop` keeps every solved challenge - the writable
layer survives. `docker compose up -d --force-recreate juice-shop` reseeds the
database (every challenge's `createdAt` moves) and yet two challenges came back
marked solved two seconds later, in the same millisecond as each other, which
is a bulk write and not two solves. The cause was not established.

What does work, verified:

```bash
docker compose rm -sf juice-shop && docker compose up -d juice-shop
```

The range does not depend on it. Each session snapshots what the target already
considered solved and counts only what appears afterwards, so a dirty target
scores correctly - a session simply cannot win an objective someone already
took. `Session.baseline` is null when the target could not be asked, which is
deliberately not the same as an empty list: treating "unknown" as "nothing was
solved" would hand the red team credit for every objective ever taken.

Note for whoever writes an objective test: Juice Shop's challenge keys and its
display names disagree. "Confidential Document" is `directoryListingChallenge`.
Verify a key against the live catalogue rather than guessing it from the name.

## A true positive is not evidence until you check which rule fired

The score counted an alert inside the window as detection. It never asked
whether the alert was about the attack. A path traversal case credited with an
XSS signature scored exactly as well as one credited with the traversal rule.

The literature calls this being right for the wrong reason and has the
definitive demonstration. Mahoney & Chan (RAID 2003) built **SAD**: it reads
**one byte** at a fixed offset of inbound SYN packets and alerts on any value
it did not see in training. On the third byte of the source address it detected
**79 of 177 attacks (45%) at 43 false alarms** - competitive with the top four
systems in the real 1999 DARPA evaluation, which managed 40-55%. Mixed with
real background traffic it detected **zero**. The score could not tell the
difference, because the score only counted matches.

So each attack case declares `expect`: a substring of the alert signature that
should be able to find it. At scoring, every alert attributed to the case is
checked against it, and a true positive whose evidence fails is reported as
`corroborated: false` plus a warning naming the cases. The arithmetic does not
change - it is still a true positive - because quietly rewriting TP to FN would
hide the disagreement rather than surface it.

The values were read off what the engines actually emit, not guessed: Suricata
says `FSL SQLi attempt - URI`, ModSecurity says `SQL Injection Attack Detected
via libinjection`, so `SQL` covers both. `traversal` matches only Suricata,
which is itself worth knowing.

Three properties worth keeping:

- **`None` is not `False`.** A terminal window declares no mechanism, so it is
  unjudged. Calling that "wrong reason" would be an accusation the data cannot
  support.
- **A generic anomaly alert does not corroborate.** ModSecurity's `Inbound
  Anomaly Score Exceeded` fires for anything over the threshold; on its own it
  says the request was odd, not that it was this attack.
- **`core_loc` did not move.** The check lives in `scoreboard.py`, not in
  `platform/scoring/`. It is a check *on* the correlation rather than part of
  it, and the ratchet protecting the hypothesis stayed at 611.

Measured on the current rule set: all six attacks corroborate. That is the
point of having it - the baseline is honest today, and now a change that makes
it dishonest is visible instead of silent.

## The counting unit is the attack case, and it is stated on purpose

McHugh's critique of the DARPA evaluations (ACM TISSEC 3(4), 2000) says the
unit of analysis is the body of data on which the detector decided, that it is
a property of the detector rather than a free choice, and that evaluations
routinely fail to say what theirs is. His complaint about the sponsor's 0.1%
false-alarm goal - "It is up to them to specify 0.1% of what" - is the whole
problem in one line.

Here the unit is **one red team case**: one TP/FP/FN/TN decision per case,
regardless of how many alerts it drew. `sqlmap-boolean-blind` produces 94
alerts and counts once.

That is deliberate and it matters, because per-alert counting would measure
something else entirely. Suricata's `threshold`, `detection_filter` and
`suppress` change the alert count without changing detection at all, so a
per-alert false positive total is a measurement of `threshold.config`. Julisch
(ACM TISSEC 6(4), 2003) found a few dozen root causes account for over 90% of
alarms, and one legitimate search URL containing `%2E` produced ~108,000
"attack" alerts on a real network. Counting those as 108,000 false positives
would say nothing about the defence.

Per-attack-instance with duplicates collapsed is also what Lincoln Laboratory
actually did - an attack counts as detected if an alert names the right victim
within the attack window, and duplicate alarms in a 60-second same-target
window are consolidated first.

## Guardrails for running this unattended

`/loop` can drive the session protocol with nobody watching. Three ways a
session could make the numbers look good without doing the work, and what now
stops each.

**Deleting tests.** `production_loc` deliberately ignores tests so the suite can
grow freely, which also meant nothing noticed it shrinking. A failing test is
cheaper to delete than the change it was hiding. `tests` is now a metric that
may only go **up**, counted as `def test_` definitions - not parametrized
cases, because `bin/measure` has to run in a fresh clone with nothing but
python3 and cannot ask pytest. Verified by deleting one test: 167 -> 166, run
refused.

**Raising a baseline in silence.** Hand-editing `metrics.json` was always the
documented last resort, but "write down why in DECISIONS" was a sentence, not a
mechanism. `bin/verify` now compares `metrics.json` against the committed one
and refuses any run that raises a gated number - or lowers the test floor -
while changing no line of `docs/DECISIONS.md`. Verified both ways: raising
`services` 9 -> 10 alone is refused and names the metric; the same raise with a
DECISIONS entry passes. The hatch is still open, it just cannot be taken
quietly.

**Writing its own backlog.** The protocol said take the top item and said
nothing about an empty list. Every backlog item this project has had came from
a human deciding what it should be - dropping DRF, replacing Django, making
objectives the score. A loop that invents items is choosing the direction. The
protocol now says stop and say so.

Also written down: commit, never push. Pushing and merging stay with the human
whether or not a loop is driving, because a session that cannot ask is one that
has to stop at the commit.

None of this stops a determined agent. It makes each of these visible in the
transcript and in the diff, which is the only kind of guarantee available here.

## The target records a solve after it has answered, so every poll is late

Objectives are attributed by time, and the timing was wrong in a way that only
showed up once a run took more than one or two.

Measured on a live run. Juice Shop writes `solved` about **80ms after** it has
answered the request that earned it, and the red team fires its next case about
**70ms later**. So every solve landed just inside the *following* case, and
attribution credited it there. `backup-file-null-byte` scored a true positive
and its breach still read MISSED, with coverage 0% across seven breaches:

```
case  :21.205  backup-file-null-byte     <- took it
case  :21.277  normal-product-search     <- credited with it
solve :21.285  forgottenDevBackupChallenge
```

Two things were wrong, and both had to be fixed.

**The stamp.** The platform used its own observation time, which trails by an
unknown amount. The target's `updatedAt` is the real solve time and is distinct
per challenge - every one of them falls inside the window of the case that
earned it. An earlier entry here said those timestamps are rewritten in bulk
and cannot be trusted; that is true of a **restore at boot**, not of a live
solve. A stamp from before the session opened is still refused, with five
seconds of slack because the target keeps its own clock and the API serialises
to milliseconds, so an exact comparison can reject a value that plainly falls
inside the session.

**The spacing.** Even with the right stamp, 80ms of lag against 70ms of gap
means consecutive cases cannot be told apart by time at all. The platform now
holds the case-recording response for a quarter of a second before asking what
fell. The red team blocks on that response, so the wait spaces the cases out -
the fix belongs here rather than in `redteam/harness.py`, which is the
hypothesis and may not grow. Unit tests mock the target and set the wait to
zero; paying it on every recorded case turned a half-second suite into a
ten-second one.

Recording a case now polls objectives as a side effect, which is what gives
per-case granularity in the first place. It is best effort and never at the
case's expense: if the target cannot be asked, the case is still recorded and
the response carries `objectives: null`. Losing ground truth because the shop
would not answer a side question would put a real attack on record as never
having happened.

## A verdict is the rule change, and it expires

The loop no commercial console closes: an analyst records "false positive" and
the rule that produced it is untouched, because recording verdicts and editing
detections belong to different teams and different tools. This range owns both
sides, so the verdict *is* the edit - a button in the alert drawer silences the
signature that raised it.

Three choices worth keeping.

**It expires.** A suppression is a false-negative bet, so it carries a
deadline and comes back on its own; nothing here can be silenced for good.
Sentinel's exceptions default to 24 hours for the same reason, and its docs say
so out loud. The default here is 60 minutes rather than 24 hours, because a
range session lasts minutes and over that horizon 24 hours and "permanent" are
the same thing - being indistinguishable from permanent is the one property a
suppression must not have.

**It comments, it does not delete.** The rule stays in the file behind a
`# fsl-suppressed until <time>` line, and the original is stored verbatim so
restoring cannot drift. A rule file that quietly loses lines is one nobody can
reason about, and the deadline should be readable by whoever opens the file
rather than only by the platform.

**`core_loc` did not move.** `platform/rules/suricata.py` is the only file that
knows the Suricata process and it is gated, so all of this is built on the
`current()` / `apply()` it already exposes: the suppression is an edit to the
rule text, applied the same way the console's rule editor applies one. The new
`platform/suppress.py` is pure text manipulation with no I/O, which is also why
it can be tested without the stack.

**What the console does not claim.** The backlog asked for the score delta on
applying a suppression. There is none to show: silencing a rule does not change
alerts that have already been ingested and scored, so an immediate delta would
be zero and saying otherwise would be a lie about what just happened. The
drawer says instead that the alerts already scored do not change and the cases
have to be fired again. `test/test_suppression.py` is that sentence as a test -
the attack is a true positive with the rule on and a false negative with it
silenced, while a control case stays detected so the silence is narrow rather
than a broken pipeline.

A restore that the IDS refuses leaves the suppression on the books rather than
marking it lifted. A rule that is off with nothing saying so is worse than one
that is openly still off.

## The defence is optional, because there is no network

Measured while scoping the user's request for network-layer defence, and it
reframes that request as a correctness fix rather than a feature.

Every service sits on one flat `172.20.0.0/16` bridge. The WAF is not a
gateway; it is a peer that happens to proxy. Suricata runs inside the WAF's
network namespace sniffing its `eth0` - a deliberate choice, recorded above,
because host mode behaves differently per host - which means it sees exactly
what crosses that one interface and nothing else.

So the same attack, twice:

```
through the WAF   proxy .7 -> waf .4 -> juice-shop .2    4 events, 2 alerts
around it         kali  .8 ------------> juice-shop .2    0 events
```

One `--noproxy` flag removes the WAF and the IDS together. An attacker at the
red team terminal can take every objective and produce no alerts, so the score
says the defence was perfect while nothing was defended.

This has been true since v1.0 and nothing surfaced it, because every attack the
range fired went through the WAF by construction. The terminal is what made it
reachable by a person, and asking for a network tier is what made anyone look.

Not fixed here - it is the top backlog item, and it needs segments, a gateway
and Suricata moved onto it. Written down now because the next session should
not have to rediscover it, and because any score taken before it is fixed
carries this caveat.

## The deployment target is x86_64, and that is not blocked

Development happens on an Apple Silicon Mac, so the stack runs arm64 images and
will keep doing so. The environment it is eventually deployed to is x86_64, and
the question of whether that switch is possible came up before anyone had
tested it.

Tested. `docker.elastic.co/elasticsearch/elasticsearch:8.15.0` pulled as
**amd64** boots and reaches `started` inside the aarch64 colima VM, with
`rosetta: false` - plain qemu binfmt. No SIGSEGV.

**This narrows the earlier entry above rather than contradicting it.** "The
stack needs a native arm64 Docker host" was measured against
`arch: x86_64` - a *fully emulated x86_64 VM*, where the JVM did die. Running
amd64 *containers* inside an aarch64 VM is a different mechanism and works. The
earlier entry is correct about what it tested and should not be read as "amd64
images cannot run here".

The cost is speed: Elasticsearch takes about **60 seconds** to start under
emulation against about **6 seconds** native. Nobody has measured what that
does to a full `bin/verify`, which already spends 85 seconds in the acceptance
suite, or to Suricata's packet handling and sqlmap. Measure before switching,
and consider pinning `platform: linux/amd64` on the services where fidelity
actually matters rather than all of them.

## Layer 2 is the wrong layer for this range

NAC was considered for the network tier and dropped, on the user's call and for
the right reason: this is not a range where anyone plugs a cable into a
corporate switch. PacketFence and its kind enforce at layer 2 with 802.1X and
RADIUS against switch ports, and a Docker bridge has no port to enforce on and
no supplicant to challenge. It would be a service in the diagram with nothing
to do.

The network tier this range needs is routing and filtering between segments,
which is layer 3 and which a container can actually be.

**pfSense and OPNsense were looked at for that tier and are not it.** Both are
FreeBSD, neither ships a usable container, and both want a VM - which is the
OpenStack path CLAUDE.md already names, a large step rather than a compose
change. If a real appliance is ever wanted that is where it goes. What this
range could actually run is a container-shaped gateway: VyOS, nftables,
OpenWRT.

## No address is both safe to fake and publicly geolocatable

Measured against this stack's own Elasticsearch 8.15, thirteen documents
through `fsl-geoip`. Every range that is safe to use in a lab returns nothing:
RFC 1918, CGNAT `100.64/10`, all three RFC 5737 TEST-NETs, RFC 2544
`198.18/15`. So does `1.1.1.1`, which is public - resolvable and public are not
the same thing. Only real allocated space resolves, and using space you do not
own is not on: if anything ever leaves the lab it is indistinguishable from
spoofing, configuring it locally blackholes that range for every container, and
it puts a stranger's address in the logs labelled "attacker".

There is no gap in the research here. It is how the address space is defined.

**The answer is to ship the coordinates.** A hand-built MMDB mapping the lab's
own ranges to chosen cities, chained ahead of GeoLite2 with
`if: ctx.src_geo == null`, because a `geoip` miss is a silent no-op rather than
a failure. Proven on this stack: a 1,067-byte file dropped into
`config/ingest-geoip/` was picked up in about eight seconds with no restart,
and `172.20.0.5` came back as Seoul. It costs no dependency, no service and no
`core_loc` - the generator is a `bin/` script, which the metrics do not count.

It also removes a fragility nobody had noticed: the stack currently downloads
GeoLite2 from `geoip.elastic.co` on first boot. With its own database it can
set `ingest.geoip.downloader.enabled: false` and be genuinely air-gapped.

Two further findings worth having before anyone builds this.

**`on_failure` in the current pipeline never fires for an unresolvable
address.** The processor simply omits `target_field`; no error, no tag. The
existing `on_failure` only catches malformed IP strings. Anything that wants to
know "this address had no location" has to test for the field's absence.

**Renumbering the bridge is one line and changes the wire.** Docker accepts any
subnet in `ipam.config`, so segmenting the network - the item above this one -
is the moment to choose addresses, and choosing RFC 5737 ranges gets real
geolocatable-looking source IPs into the IP header for free. That is more
honest for an IDS exercise than a header, because reading packets is the IDS's
job.

## Forging the source address would hand the red team the scoreboard

The realistic way to geolocate WAF logs is `X-Forwarded-For`: a WAF behind a
CDN geolocates the client header, not the peer. It would be cheap here, too -
`deploy/proxy/stamp.py` already stamps a header on every request, Suricata has
a native `xff:` block whose `mode: overwrite` replaces `src_ip` outright, and
nginx `realip` would feed ModSecurity's `client_ip` without touching
`platform/ingest/elastic.py`.

It is also a scoring hazard, and the reason is structural. `correlation:
window` matches alerts to cases **by source address**, and `attacker.py` exists
because a wrong address scores a real attack as a miss and blames the defence.
Making `src_ip` attacker-controlled means the red team can forge the field the
score is keyed on. Marker correlation is immune; window correlation is not.

So it is not "add XFF". It is a choice, and it has to be made before anything
is built:

- put the addresses on the wire instead, by segmenting with RFC 5737 subnets,
  and leave `src_ip` meaning what it says; or
- use XFF and have the platform match against the synthetic pool as a set
  rather than a single address; or
- use XFF and abandon window correlation for rotated traffic, scoring it by
  marker alone - which would have to be said out loud, because the whole point
  of exercising `window` was that it had never run.

Rotating the address is not only decoration either: window correlation has only
ever seen one fixed proxy address, so it has never actually been tested.

## The attacker gets real public addresses, by the user's decision

The entry above argued against using allocated space nobody here owns. The user
overruled it - "어차피 공인써도 상관없는데" - and that is their call to make on
their own lab. This records what was decided and what makes it work, so nobody
reads the earlier entry and undoes it.

**It also makes the topology more honest, not less.** Only the attacker side
gets public addresses. The DMZ, the application and the management segment stay
RFC 1918, which is what a real company's inside looks like. An attacker on the
internet hitting a private estate is the picture; both sides on `172.20.0.0/16`
never was.

Verified pool, measured against this stack's own GeoLite2:

| range | resolves to | lat, lon |
|---|---|---|
| `5.188.10.0/24` | Russia | 55.7386, 37.6068 |
| `45.155.205.0/24` | Russia, St Petersburg | 59.9417, 30.3096 |
| `185.220.101.0/24` | Germany, Brandenburg | 52.6171, 13.1207 |
| `103.152.220.0/24` | Hong Kong, Kwai Chung | 22.374, 114.1369 |
| `175.45.176.0/24` | North Korea | 40.0, 127.0 |
| `196.16.0.0/24` | Seychelles | -4.5833, 55.6667 |
| `177.54.144.0/24` | Brazil, São Paulo | -23.5475, -46.6361 |
| `123.59.0.0/24` | China | 34.7732, 113.722 |

With a public pool there is no MMDB, no enrich policy and no header rewriting.
GeoLite2 answers, the existing `fsl-geoip` pipeline works unchanged, and
`src_ip` keeps meaning what it says - so `correlation: window` stays honest and
the fork recorded above is closed in favour of putting the addresses on the
wire.

**The one real cost is a blackhole, and it was checked.** Any range assigned to
a bridge is directly connected for every container on it and can never reach
the real thing. The stack reaches Docker Hub (`52/3/34.x`), `geoip.elastic.co`
(`104.197.x`), `docker.elastic.co` (`34.56.x`), `kali.download` (`104.17.x`)
and GitHub (`20.200.x`) - all cloud and CDN space, none of it overlapping the
pool above. **Before adding a range to that table, resolve what the build
actually fetches and check again.** Cloud and CDN blocks move; a range that was
free last month can break `docker compose build` in a way that looks like
anything but a routing decision.

Two consequences worth stating plainly. The lab can never reach those eight
networks - nothing here wants to, and that is why they were picked. And the
logs will name real networks as attackers, which is fine inside the lab and
worth a second thought before a screenshot leaves it.

## The WAF became the gateway by topology, not by policy

The bypass is closed and it cost no new service. `services` is still 9.

Three networks instead of one flat bridge. `edge` carries the attacker on
public space (`5.188.10.0/24`, which GeoLite2 places in Moscow); `app` and
`mgmt` are RFC 1918, because that is what a company's inside looks like. The
WAF is the **only** member of both `edge` and `app`, so it is the way across -
not because a rule says so but because nothing else can carry a packet between
them. Kali resolves `juice-shop` and gets nowhere:

```
kali 5.188.10.3 -> juice-shop:3000   000   (was 200)
kali 5.188.10.3 -> waf:8080          200
```

Suricata stays in the WAF's namespace, which was always the right place and is
now a genuine choke point rather than one host's interface. It watches both of
the WAF's interfaces via `--af-packet` with two entries in the config, because
which one Docker calls `eth0` is not guaranteed. `HOME_NET` had to grow to
include the *edge* subnet: the attacker aims at the WAF's outside address
first, and leaving that out silently drops every alert on the
attacker-to-WAF leg, which is most of them.

**The first full run after this was red, and it was not this change.** TP was
zero, and the cause was a cold stack - `docker compose down` then `up` gives
Filebeat new containers and an empty registry, and the acceptance suite ran
while it was still settling. The entry above about cold stacks has now cost two
sessions; treat a red `bin/verify` in the first minutes after a recreate as
uninformative and run it again before concluding anything. A rerun on the warm
stack passed all 34 acceptance tests unchanged.

Two things this exposed and did not fix, both measured:

- **Published ports enter through `app`, not `edge`.** Traffic to
  `localhost:8080` reaches the WAF on its app-side address, so the CLI
  harness's attacks arrive from `172.30.0.1` - inside the estate, and
  geolocating to nothing. The front door should be on the edge.
- **The platform is on all three segments**, which is a simplification worth
  naming rather than hiding: it launches attacks, reads the target's challenge
  API and writes to Elasticsearch, and in a real estate those are three
  machines. It also means the platform can reach the target directly, so it is
  a bypass path for anything that can make the platform issue requests.

## Docker picks the published port's target by network name, alphabetically

Segmenting put the attacker outside but left the way in on the inside: traffic
to `localhost:8080` reached the WAF on its estate-side address, so the range's
own attacks were logged as coming from `172.30.0.1`.

`priority: 100` on the edge attachment did **not** fix it, and did not even
change which interface came up as `eth0`. What fixed it was renaming the inside
network from `app` to `estate`, so that `edge` sorts first. Measured:

```
before   alert src=172.30.0.1 -> dst=172.30.0.3   iface=eth0   (inside)
after    alert src=5.188.10.1 -> dst=5.188.10.4   iface=eth0   (outside)
```

So the published port follows the alphabetically first network name, not
`priority` and not declaration order. If a segment is ever renamed, check this
again - nothing in the compose file says the name is load-bearing, and the
failure is silent.

The platform needed a separate fix. It shares *both* segments with the WAF, so
`waf` resolved to whichever address answered first, and attacks fired from the
console went out on the estate side. Network-scoped aliases make the way in
explicit: `waf-edge` and `waf-estate` each resolve on one network only, and
`TARGET_URL` names the door rather than the host.

Two smaller traps met on the way. Renaming a network and then running
`docker compose down` leaves the old one orphaned and still holding the subnet,
so the new one cannot be created - `docker network rm fsl_app` first. And
moving a log file the WAF has open is the bind-mount inode trap again, one
entry up: the WAF keeps writing to the moved file and its alerts stop arriving.
Recreate the container, do not just move the file.

## Filebeat's registry has to outlive the container

`docker compose down` then `up` gives Filebeat a new container and an empty
registry, so it re-ships every log file from the beginning. Measured after one
recreate: **14,242 documents in the last ten minutes**, overwhelmingly carrying
`172.20.0.x` - addresses from the flat network that had not existed for an
hour.

This is not the cold-stack delay recorded above. It is worse, and in the
opposite direction: rather than a window with nothing in it, every session
opened afterwards gets a window with thousands of stale events in it, and the
score is computed over them. A range that silently re-scores last week's
traffic as this minute's is not measuring anything.

The registry now lives in a named volume. Recreating Filebeat picks up where it
left off.

Cleaning up after the fact took more than expected and is worth writing down.
The indices are **data streams**, so `DELETE /fsl-logs-*` is refused twice
over - wildcards are disallowed, and a data stream's backing index cannot be
deleted directly. `DELETE /_data_stream/<names>` is the one that works.

## The rules can be walked past with a plus sign

Found by accident: a probe written with `requests`' `params=` raised no alert
at all, because `params=` encodes a space as `+` and every SQLi rule in
`local.rules` matches `\x27\s*(or|and)` - and `+` is not whitespace. The same
payload with `%20` alerts immediately.

```
q=%27%20OR%201%3D1--     alert
q=%27+OR+1%3D1--         nothing
```

This is a real gap in the rule set, not a quirk of the test, and it is the
oldest WAF evasion there is. It is deliberately **not fixed here** - it is a
detection-engineering task with its own acceptance criterion, and it is exactly
the kind of thing the blue team should find and fix from the console. It is on
the backlog with the measurement attached.

## The plus-sign evasion, narrowed twice and then fixed

The entry above said "every SQLi rule" could be walked past with a `+`. That
was written from one probe and it was wrong twice over. Both corrections are
worth more than the fix.

**First narrowing: one alternative already caught it.** `'))+UNION+SELECT`
alerted while `'+OR+1=1--` did not, which made no sense until the rule was read
properly - sid 9000001 has a fifth alternative, `\x27\s*\x29`, that matches
`')` on its own and has nothing to do with whitespace. The rule was catching
that payload for a reason unrelated to the one being tested.

**Second narrowing, and the important one: the stack was never evaded.**
ModSecurity catches the plus-encoded injection by other means, so the combined
verdict is a true positive either way. Defence in depth was working, which is
exactly why nobody noticed the IDS rules had a hole. The honest claim is
narrow: **the Suricata rule set matched an encoding rather than an attack,
while the WAF covered for it.**

That changed what the test had to measure. "Is it detected" passes before the
fix and proves nothing; the criterion is **which engine fired**, and the range
can answer that because detections carry their source.

```
before   only ['modsecurity'] caught the plus-encoded injection
after    both engines
```

The fix is `[\s+]` in place of `\s` on sids 9000001-9000003, wherever
whitespace is expected inside a query or a form body. Suricata 8 also has a
`url_decode` transform, which is the more general answer - it would decode
`+` to a space before matching, and fix encodings nobody has thought of yet.
It was not used because applying it to `http.uri`, which is already normalised,
decodes twice, and the narrower change is the one whose blast radius can be
reasoned about. The transform is the right next step if this class of thing
recurs.

Benign traffic was the risk - `[\s+]` is more permissive - and the acceptance
criteria carried it: `O'Brien's lemonade` and `select the best juice for me`
are still true negatives.

## A session's readiness cannot be judged by what is in its window

Writing the test for the above hit something that will bite again. Sessions
overlap in time, and ingest pulls everything in a session's window, so a
session opened beside another one inherits its alerts. A readiness check of the
form "have both engines appeared in this session yet" was therefore satisfied
**by the neighbouring session's traffic**, seconds after opening and long
before this session's own attack had landed. The test then measured an empty
result and failed for a reason that had nothing to do with the code.

Wait on the control **case**, not on the session: "has the case I know should
be detected been detected, by the engines I expect". `test_evasion.py` and
`test_suppression.py` both do this now, and anything that waits for a pipeline
should.

## The map draws its own projection, because borrowed ones lie

The console plots attack origins on a world map, and the coastlines come from
`bin/worldmap`, which converts Natural Earth 110m land into SVG paths at build
time. The output is committed; nothing is fetched at runtime, because an
isolated range should not depend on a CDN and a map that silently fails to load
is worse than no map.

The projection is computed here rather than taken from a ready-made SVG on
purpose. Most world SVGs described as equirectangular are clipped somewhere
north of 83 and south of 56, so a point plotted with the textbook formula lands
tens of pixels from where the country is drawn - and no assertion catches it,
because the numbers are all correct. Generating the paths with the same
`x = lon + 180, y = 90 - lat` the console uses means the grid and the points
cannot disagree. Verified by eye against ten known cities before anything was
built on it: Moscow, London, New York, São Paulo, Hong Kong, Pyongyang, Sydney,
Cape Town, Brandenburg, Seychelles.

The source data is clipped at about 85.6° south, so Antarctica is a band rather
than a continent. That is the data, not the projection.

## A location belongs to an address, not to an alert

Measured, and it changed the design. Elasticsearch documents carry `src_geo`
once the pipeline has run - 306 of them did. But only **Suricata** detections
keep it: `normalize` stores the whole document as `raw` for Suricata and only
the message sub-object for ModSecurity, whose `raw` is `['details', 'message']`
and has no geo at all.

| source | `raw.src_geo` |
|---|---|
| suricata, public address | present |
| suricata, estate address | absent, correctly |
| modsecurity | never |

Drawing only the alerts that carry geo would have halved every origin and made
the WAF invisible on the map. Fixing `normalize` would have been the direct
route and would have grown `core_loc`, which is gated.

Neither was necessary, because geolocation is a property of the **address**.
Each address is placed once, from whichever alert happened to carry it, and
then every alert from that address counts - and both engines see the same
traffic, so the addresses overlap. `core_loc` did not move.

Addresses that resolve to nothing are counted and reported rather than dropped:
"26 alerts from Russia, 7 from addresses with no location" is a fact about the
range, and a map quietly showing fewer alerts than the counter beside it is
not.

## Rotating the source address needs one network per origin

The attacker is on public space and geolocates, but the whole edge segment is
one subnet, so every attack comes from Moscow. Making them arrive from
different countries means addresses in different ranges, and the obvious way
does not work:

```
docker network create --subnet 185.220.101.0/24 --subnet 175.45.176.0/24 ...
Error response from daemon: bridge driver doesn't support multiple subnets
```

So a second origin is a second network, attached to the attacker's containers
and to the WAF, with Suricata watching another interface. That is real work and
it is not the map, so it is the next backlog item rather than something bolted
on here.

One constraint for whoever takes it: the published port follows the
alphabetically first network name, so any new segment must sort **after**
`edge` or the front door moves back inside the estate. `edge-hk` is safe;
`dmz-hk` is not.

## One network per origin, because a subnet is a place

The map had one pin. Every attack came from Moscow, because the edge segment
is one subnet and a subnet geolocates to one point. The bridge driver refuses
more than one subnet on a network, so each place an attack can come from is
its own network: `edge-br`, `edge-hk`, `edge-kp` beside `edge`, each on a
range checked against this stack's own GeoLite2 first.

Nothing had to be taught how to use them. A container attached to all four
picks its source address by routing, so **dialling the WAF on a segment is
what makes the attack come from that segment** - and the WAF already answered
under a per-network alias for an unrelated reason (it is on several networks
the platform also shares, so `waf` alone was ambiguous). `waf-edge-hk` is both
the way in and the choice of origin, and the console passes a target URL the
harness already took as an argument. `core_loc` did not move.

Measured, first request through the new segment:

```
103.152.220.3 -> 103.152.220.4  eth4  FSL SQLi attempt - URI
172.30.0.3    -> 172.30.0.2     eth1  FSL SQLi attempt - URI
```

Three things are silent when they are wrong, and all three had to be right
before a single alert appeared:

- **`HOME_NET`.** The rules fire on traffic *to* `$HOME_NET`, and the
  destination is the WAF's address on whichever origin was dialled. A missing
  subnet means the attack lands and nothing alerts - which reads as a defence
  that missed.
- **The interface list.** Suricata watches named interfaces in the WAF's
  namespace. A new network is a new `ethN`, and an unwatched choke point sees
  nothing and says nothing about it. All five are listed rather than the ones
  believed to matter, because Docker's attachment order is not guaranteed.
- **The name.** The published port follows the alphabetically first network
  the WAF is on, so every origin must sort after `edge`. `dmz-hk` would have
  moved the front door back inside the estate, undoing an earlier entry here.

Four pins, four countries, one rotating run: Russia 6, Brazil 6, Hong Kong 3,
North Korea 3.

## The origins are discovered, not listed

`fsl.origin` is a Docker network label, set in compose beside the subnet it
describes, and `origins()` reads it back. A table in Python would be a second
copy of the compose file, and the one that would quietly stop being true is
the copy - while the score is read off the addresses the compose file decides.

An origin needs both halves: a network that says where it pretends to be, and
an address on it. A declared network the attacker is not attached to would
offer an attack that cannot be sent. Docker failing to answer is a 503, never
an empty list: "nowhere to attack from" and "cannot ask" are different, and
only one of them is the console's fault.

## A recorded origin carries no address

Caught by reading the output rather than the test. Rotation reported
`source_ip 5.188.10.3` while the alerts carried `5.188.10.4`, and both were
correct: origins are discovered from the attacker box - the proxy, because
that is where terminal traffic leaves from - while a case fired from the
console leaves from the platform, which has its own address on the same
network.

So the case records the origin and the door it dialled, and no address. The
rule this repo keeps is that a wrong address matches no alert at all, which
scores a real attack as a miss and blames the defence for it. The map is drawn
from the alerts, which carry the true one.

The console's selector shows the subnet for the same reason: it is true of
both boxes, and the exact address appears only in the terminal panel, where it
is the proxy's and correct.

## Two clocks, and a breach handed to the case before

`bin/verify` came back red on a test this change does not touch:
`forgottenDevBackupChallenge` was taken by an attack the defence detected, yet
the breach read MISSED.

Checked before attributing it, because a red run is worth nothing if the cause
is guessed. With `platform/` and `redteam/` reverted to HEAD on the same
stack, the same test failed **three runs in four**. The one passing run is why
this was worth measuring rather than reasoning about: a single green run had
already been mistaken for proof once in this session.

The cause is in the timestamps:

```
forgottenDevBackupChallenge   achieved 05:22:53.858   (the target's clock)
backup-file-null-byte         started  05:22:53.884   (the firing side's)
```

The deed is recorded 26ms *before* the attack that caused it. `attribute()`
required `started_at <= achieved_at`, so every objective went to the case
before - which is exactly the defect this module was rewritten to fix, arriving
by a different road. The lead was 19-26ms across the run.

It cannot be corrected by subtracting an offset. A `docker exec` round trip to
read the target's clock takes ~40ms, so the skew cannot be measured to better
than the size of the thing being measured; two attempts an hour apart gave
+8ms and -1ms with +/-20ms of uncertainty. What can be said is that the two
numbers come from two clocks and disagree by tens of milliseconds, so
comparing them exactly was never meaningful.

`CLOCK_SKEW = 100ms` on the lower bound, and nothing else changes. It is four
times the observed lead and under a third of the quarter-second the platform
already holds between cases for a related reason, so a deed cannot fall to a
neighbouring case. The previously flaky test now passes four runs in four.

This is a second thing in one session, which the protocol does not ask for.
The alternative was to discard a finished item over a defect already in the
baseline, and a baseline that fails three runs in four is not a baseline.

## The topology is asked for, not drawn

A picture of a network maintained beside the network is wrong within a
session - an address changes, a segment is added, a sensor moves - and a wrong
picture is worse than none, because it is believed. So the diagram is a read
of the running stack, and the only way for it to be wrong is for the question
to be wrong.

Docker answers all of it. `network ls` filtered on the compose project label
gives the segments, `network inspect` gives each one's subnet and the
addresses on it, and `fsl.origin` - already there for the attack origins -
says which segments are outside. Nothing new had to be written down anywhere
for the picture to exist.

One thing only `docker inspect` knows: **a sensor that shares another
container's namespace is on no network of its own.** Suricata has
`NetworkMode: container:<waf>` and appears in no network's container list, so
a diagram built from networks alone draws a range with no IDS in it - which is
the single box the blue team most needs to see. It is placed where it watches,
by resolving that container id back to a name.

## A crossing is a foot on each side, not two networks

The first version marked any container on more than one segment. Run against
the stack it marked three, and one of them was noise: the proxy is on all four
origin segments, which are all outside, and crossing between two outside
segments threatens nothing. The number that matters - how many ways in there
are past the WAF - was buried under boxes that are not ways in.

So a crossing is a container with a foot on an outside segment *and* on an
inside one. Against the real stack that leaves two:

```
ways in: waf, platform        unwatched: mgmt
```

Both are true and neither was visible before. The WAF is the design. The
platform is the simplification `compose.yaml` has admitted in a comment since
the segments were created - it launches attacks on the edge, reads the
target's challenge API on the estate and writes to Elasticsearch on mgmt, and
in a real estate those are three machines. A comment in a file nobody opens
and an amber box on the console beside the alerts are not the same thing.

`mgmt` having no sensor is the same kind of fact: it is a segment where
attacks could arrive and nothing is listening. Saying "unwatched" is honest;
drawing an empty box and letting it read as "quiet" is not.

## The diagram's numbers are the alerts

Every detection is counted onto the segment its source address falls in, and
an address on no segment is counted as unplaced rather than dropped. The
acceptance suite asserts `placed + unplaced == alerts`, which is what stops
the picture becoming a second count that drifts from the one beside it.

It is throttled to once every fifteen seconds rather than riding the
two-second alert refresh. The shape changes when the stack changes, which is
never during a session, and four `docker` round trips every two seconds is a
cost with nothing on the other side of it.

## One console for the blue team, two views inside it

This went through three shapes before it was right, and the middle one is
worth keeping written down.

It started as a document: a map, then a topology, then counters, then the
alert list, appended one below the next on a page that scrolled. Making that a
grid on one screen was the first correction and was still wrong - a control
room is read from two distances, an overview a room can read and an analyst's
list with filters and the record behind a row, and neither is a section of the
other. So they were split into two addresses, `/board/<id>` and `/blue/<id>`.

That was one step too far, and the reason is the difference between a **view**
and a **product**. Splitting them across screens is the operator's call: open
the blue console twice and leave one on the overview. Baking it into the
routes made that decision for them, and made two things to maintain where
there is one console with two tabs.

So: `/blue/<id>` has Dashboard, Live, Scoreboard and Rules, `/board` is gone,
and the property that mattered is unchanged - only one of them is on screen at
a time, which is what a grid of everything was not.

The overview is drawn from the rows the list is already holding, and the two
server-side parts - the map and the top-N tables - are skipped while the tab
is hidden, because a request nobody is looking at is a request for nothing.

**Removing the second address broke the page in a way worth a test.** One line
still set the href of a link that no longer existed; `getElementById` returned
null, assigning to it threw, and every statement after it - including the one
that picks which panel to show - never ran. The page rendered with all four
panels stacked, and nothing said why. There is now a test that every id the
script reaches for is on the page.

## A top-N table is what a console shows, not a bar

Rebuilt after the first two attempts put the wrong things on the board, both
times from a summary rather than the source. Read properly:

**Cloudflare's security events screen** is a summary grouped by dimension, one
time series, and *top events by source* - IP addresses, user agents, paths,
countries, hosts, ASNs - each a table of one dimension with its count, plus
sampled logs with configurable columns.

**Igloo's write-up of a Korean SOC console** names the defect that makes an
address useful: 탐지 장비 정보는 직관적으로 식별이 가능하나, 이벤트의 출발지 /
목적지 IP 자산의 영역 확인을 위해서는 추가적인 업무가 필요하다. Their answer
is a mapping from address range to the name of the thing that owns it, shown
beside the address - and they say to use a department name and a host for a
small site rather than an institution code.

So: top source addresses with the zone they belong to and where they
geolocate, top destinations with their zone, top signatures with the engine
that raised them, top request paths with the method. The zone mapping is this
range's own segments, which is what `topology.py` is for now - a registry, not
a diagram.

What came off the board, and why:

- **The segments table.** Which container bridges which network and which
  segment has no sensor are findings about how this range is built. They are
  in this file and in a test; a room watching traffic has no use for them, and
  they were written in words nobody outside this repo could read.
- **The Host column.** It showed `waf-edge`, an internal Docker alias.
  Cloudflare's "host" is the attacked domain. Two different things under one
  word is worse than not having the column.

Request paths are decoded before display, because the payload is the point of
the row and `%27+OR+1%3D1--` hides it. That decoding is exactly what made the
XSS above fire, which is not an argument for leaving it encoded - it is an
argument for escaping output, which is now done.

## Never remove a compose network while its containers are running

Cost an hour across two occurrences in one session, with the same silent
symptom both times.

Changing a network's labels means recreating the network. Doing that with
`docker network rm` while containers are attached-but-running, then bringing
the stack back up, reconnects them **without their compose service alias**:

```
DNSNames: ["fsl-juice-shop", "f70a6184cc73"]     # no "juice-shop"
DNSNames: ["fsl-elasticsearch", "5080fa34ffaa"]  # no "elasticsearch"
```

Nothing logs a warning. The WAF died with `host not found in upstream
"juice-shop"` and took Suricata with it, because Suricata shares its
namespace; later the platform could not reach Elasticsearch and every ingest
returned 503 while the console kept polling. Both read as something else
entirely.

`docker compose up -d --force-recreate <service>` puts the alias back. The
rule: recreate the **containers**, not just the network.

## The red team is a box, not a button list

The catalogue was the red team, and every case in it encodes a path only this
target has: `/rest/user/login`, `/ftp/acquisitions.md`, a column count that
matches Juice Shop's products query. That is fine for a baseline - the same
payloads every run, so one score can be compared with the last - and useless
as an attacker. A real one runs tools it chose against a target it is still
working out.

So the shell got the tools it needed to be one: nmap and whatweb for what is
there, ffuf and gobuster for what is served, nikto and sqlmap for what is
wrong with it, hydra for what it will let you in with, and curl, wget,
netcat, dig and jq to improvise. It had curl, nmap and sqlmap. The red window
leads with the box now and the buttons are below it, labelled as the scripted
baseline they are.

**One image, not two.** A case with `tool:` used to run in `fsl-redteam-tools`
- a python-slim base with pip-installed sqlmap - while the person typed at
Kali. Two attacker images means a case can depend on something the shell does
not have, and the other way round. They are the same image now, which also
took `services` from 9 to 8: the `redteam-tools` compose service and its
Dockerfile are gone.

## Two routes out of the box, and the alert says which

The terminal's traffic goes through the stamping proxy, so an alert carries
the proxy's address - that is how a free-form window gets a marker as well as
a time and a source. But `http_proxy` is an HTTP convention. nmap, netcat and
hydra ignore it and leave from the box itself:

```
through the proxy   5.188.10.3    curl, sqlmap, nikto, ffuf, gobuster
direct              5.188.10.2    nmap, nc, hydra
```

Both are true at once, and a window recorded against the wrong one matches no
alert at all - which scores a real attack as a miss and blames the defence.
The API reports both, the window panel asks which route the work will take,
and the origin that has no shell on it offers only the proxy rather than
inventing a direct address.

## Why the scanners are not cases

They were, for about an hour, and the measurement is why they are not.

A case is correlated by a marker header, appended by `build_tool_command` as
`--headers=X-FSL-Case: <id>`. That is **sqlmap's** syntax. nmap does not take
it and nikto does not either, so their traffic carries no marker, nothing
correlates to the case, and both come back `FN` with zero alerts:

```
nmap-service-scan      FN  detected=False  alerts=0
nikto-web-scan         FN  detected=False  alerts=0
```

Both tools reached the target - nikto found `/ftp/` and reported ten items -
so this is a harness failure recorded as a defence failure, which is the one
mistake this platform must not make. `SUPPORTED_TOOLS` is back to sqlmap
alone, with the reason written where the next person will change it.

The shell is where those tools belong anyway: a labelled window scores them
by time and source, which needs nothing appended to anything. Making them
cases needs a per-tool marker flag - ffuf, gobuster, curl and whatweb all
take one, nikto and nmap do not - and that is a separate item.

## Kali's wordlists are symlinks into packages you did not install

`/usr/share/wordlists` comes from the `wordlists` package and is almost
entirely symlinks; `dirb/common.txt` only exists if `dirb` is. Installing
`wordlists` alone leaves the directory looking populated and every path in it
broken, and `rockyou.txt` ships gzipped, which no tool reads. The image
installs `dirb` and unpacks rockyou, and an acceptance test counts the lines
in the list the shell's own help text points at - because the first version
of that help text pointed at a file that was not there.

## The target is a site, not the appliance in front of it

The shell was told to attack `waf-edge:8080`. That tells an attacker three
things they could not possibly know: that there is a web application firewall,
what it is called, and that the site is really a lab on a high port. No
console shows any of it, because no attacker ever sees it.

The target answers to `http://shop.com` now. No port, because a site does not
have one, and that was the last piece of the plumbing showing.

**Port 80 needed two things.** The CRS images run nginx as uid 101, so
`net.ipv4.ip_unprivileged_port_start=0` on the container lets it bind a
privileged port. The image also ships `01-check-low-port.sh`, which refuses
`PORT` below 1024 on the assumption that an unprivileged user cannot bind one
- an assumption the sysctl makes untrue - so a no-op script is mounted over
it. The host still publishes 8080, because that is the operator's browser and
not the attacker's view of the site.

The name was also doing two jobs, and they had to be separated:

- **Naming the site.** One name, the same from everywhere, which is what goes
  on the wire and into every alert.
- **Choosing a segment.** The proxy and the platform sit on all four origin
  networks, so which of the target's addresses they connect to is what decides
  which of their own addresses the alert carries. A name that resolves on
  several of those networks picks an interface at random.

So `shop.com` is aliased on one segment only, which makes it unambiguous even
from a box attached to four, and the `waf-<origin>` names stay as pure
routing. Nobody types them:

- **The shell** always dials `shop.com`. The console's origin selector writes
  a file, the stamping proxy reads it per request and rewrites the connection
  host while leaving the `Host` header alone. Verified: with Hong Kong
  selected, `curl "$FSL_TARGET/..."` produced
  `103.152.220.2 -> 103.152.220.4  Host: shop.com`.
- **The scripted cases** dial the routing name when an origin is chosen, and
  the platform injects the `Host` header so the request still says which site
  it is for. Cases can already declare headers, so this needed no change to
  `harness.py`, which is gated.

`shop.com` is a real registered domain, and this alias only resolves inside
the range's own DNS - the same call the user already made for the attacker's
public addresses, and recorded here so nobody undoes it.

The acceptance suite checks the whole of it: that the shell's target does not
name the appliance, and that choosing an origin moves the source address
without renaming the site.

## Two more pieces of state that survive the session that set them

The origin file is the second thing in this range that a run can leave
pointing somewhere unexpected, after a suppression left silencing a rule. Both
have the same shape: a file the proxy or the IDS reads per request, no
expiry a test run respects, and a failure that reads as something else
entirely - "attributed to an address on the wrong continent", "the probe
raised no alert at all".

The acceptance suite now resets the origin and refuses to run while any rule
is suppressed. Anything else added with that shape needs the same treatment,
and the rule is: **state the console can change must be reset before a
measurement, or the measurement is of the last session.**

## Never test a hypothesis with a mutating command on the live stack

`docker network disconnect fsl_edge fsl-waf` was run to undo a probe, and it
worked: the WAF came off the edge segment and the range stopped having a front
door. The probe itself had already failed for an unrelated reason, so nothing
was learned and the stack had to be rebuilt.

`docker compose up -d --force-recreate waf suricata` put it back. The lesson
is the obvious one, written down because it cost real time twice in this repo
now: read with `inspect`, change with `compose`.
