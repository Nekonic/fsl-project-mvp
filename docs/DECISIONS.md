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
