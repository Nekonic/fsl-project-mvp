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
