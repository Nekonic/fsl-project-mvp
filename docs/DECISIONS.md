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
