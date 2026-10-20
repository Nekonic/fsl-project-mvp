# Plan: remove the docker substrate so the product is OpenStack-only

Status: Decided 2026-10-20, not started; run it as the next task. Gate 1 is passed (the user decided D1-D4 and chose to run it next on 2026-10-20): start at commit 1 without presenting the plan again. Done = commits 1-8 each green on `bin/verify --fast`, then the section 5 live rows, then the last commit rewrites `docs/state/now.md` and `docs/STATE.md`, then gate 2 (show the change and wait for the user's push approval).

Ruling: the product is OpenStack-only (`docs/DECISIONS.md`, 2026-10-20). Docker stays as the way the platform VM runs the platform's own services from GHCR images, and as the wargame host's and GNS3's container runtime; it is no longer a substrate the product can run on.

The removal is safe for the OpenStack path. Nothing it uses at runtime depends on `range/docker.py` or `session.yaml`. Four things need care:

- **Unit tests.** About 21 test files open sessions through the Docker adapter, which conftest has turned into a "null range". They need a stand-in.
- **Kali image.** Deleting `deploy/kali/Dockerfile` changes the fsl-kali image's content hash. The cloud then builds a new Kali image and rebuilds both slots.
- **Platform container networks.** Removing the four edge networks from `compose.yaml` changes which network is the platform container's default gateway on the platform VM.
- **Dead branches.** Some code is reached only by the Docker adapter. Removing it was decided as D1–D3 (end of this document).

## 1. Inventory and fate of each file

**Delete** (about 18 files)

| File | Why |
|---|---|
| `platform/range/docker.py` (424 lines) | The adapter itself. Nothing imports it except settings and tests. |
| `session.yaml` | The per-session stack (waf, suricata, filebeat, kali, proxy). |
| `platform/waf-terminal.sh` | Runs `docker exec` into `fsl-<id>-waf-1`. |
| `deploy/nginx/{board.conf,corp.conf,allow-low-port.sh}` | Mounted only by `session.yaml`'s WAF. The WAF VM uses `deploy/waf/`. |
| `deploy/kali/Dockerfile` | Builds the GHCR fsl-kali image. The Kali VM uses `setup.sh`, `bashrc` and `operator-log.sh`, which stay. |
| `deploy/proxy/Dockerfile` | Builds the GHCR fsl-proxy image. `stamp.py` stays because the Kali VM bundle lists it. |
| `deploy/topology/range-docker.gns3`, `range-docker.ko.gns3`, `system/range-docker.gns3` | Docker learner map pair (English and Korean, deleted together) and the docker system map. |
| Tests: `test_docker_runner.py`, `test_range_shape.py`, `test_corp_waf.py` | They test only the deleted adapter or `deploy/nginx/corp.conf`. |

**Change**

| File | Change |
|---|---|
| `platform/fsl/settings.py` | Default `FSL_SUBSTRATE` becomes `range.openstack.connect`. Remove the `/terminal/` and `/waf-terminal/` ternaries, the docker entry of `ELASTIC_SESSION_INDEX`, the docker `FSL_SUBSTRATE_OPTIONS`, and the `'docker'` fallback in `FSL_TOPOLOGY`. |
| `compose.yaml` | Remove networks `edge`, `edge-br`, `edge-hk`, `edge-us` and the platform's attachments to them (including `gw_priority`). Remove the `./session.yaml:/src/session.yaml` mount. Keep `mgmt`, all 5 services, the docker socket mount and `./deploy` / `./wargames` mounts. |
| `platform/nginx.conf` | Remove the `^/terminal/<id>/` (`fsl-$session-kali-1`), `^/waf-terminal/<id>/` and `/terminal/` (`kali:7681`) location blocks. |
| `platform/entrypoint.sh` | Remove the ttyd line on port 7693 (`waf-terminal.sh`). |
| `platform/Dockerfile` | Remove the docker-compose plugin COPY (only `open_session` used it). Keep the docker CLI: sideload (`docker image inspect` / `save`) and `interfaces.on_this_host` use it. |
| `deploy/filebeat/filebeat.yml` | Remove the two `filestream` inputs (`suricata-eve`, `modsecurity-audit`), which only the session filebeat used. The collector keeps the udp syslog input. |
| `deploy/openstack/platform.yaml` | Remove the `ExecStartPre … session.yaml pull` line. On the running VM it is `-`-prefixed, so it fails harmlessly until the VM is rebuilt. |
| `.github/workflows/images.yml`, `bin/platform-rebuild` `IMAGES` | Remove `kali` and `proxy`. |
| `redteam/tools.py` | `TOOL_IMAGE` defaults to `fsl-kali` (the attacker role the OpenStack launcher demands). Fix the hint that says "pull session.yaml". |
| `bin/verify` | Remove the "attacker image present" check (`docker compose -f session.yaml config --images kali`) and the `session.yaml` recreate hint. Keep the `fsl-platform` working-dir check and the `docker compose restart platform`: both are about the platform VM. |
| `bin/select-tests` | Remove `session.yaml` from `RANGE_FACING`. |
| `bin/measure` | Remove `SESSION_FILE`. Count `wargame_services` from `wargames/*/compose.yaml` (D4, decided yes); otherwise it reads 0 once nothing includes them. |
| `platform/range/declaration.yaml`, `declared.py` | Remove the docker-only `compose:` entries (attacker, proxy, gateway, sensor) and the base roles that the openstack overlay overrides. Fold the `openstack:` overlay into the base and drop `flavor_for` / `_overlaid` (D3, decided yes). Keep `fsl-waf`'s `setup`, `files` and `names`, so the WAF image hash is unchanged. |
| `api/views.py`, `api/site.py`, `api/customers.py`, `api/maps.py`, `redteam/run.py` | D1, decided yes: remove branches only the Docker adapter filled: `open_session`, `for_session`, `has_stack`, `drop_users_box`, `_stacks_to_keep` / `STACK_OUTLIVES_ITS_SESSION`, the unslotted per-session GNS3 maps, and the `"compose builds this range"` message. |
| `platform/attacker.py`, `api/site.py`, `api/maps.py`, `api/customers.py`, `api/views.py`, settings `ATTACKER_ORIGIN_MODE` | D2, decided yes: remove the `host-rewrite` origin mode (docker's proxy). On OpenStack it is always `snat`. |
| `test/range.py` | Remove the `Docker` class, `DOCKER_HOSTS`, `SESSION_STACK`, `segments()` and `recreate()` (no acceptance test calls them). Keep a small platform executor for the `scorer` role (`docker exec fsl-platform`). `use()` always picks `ThroughPlatform`. |
| `test/conftest.py` | Remove the `"compose"` default and the docker-only `target_answers` branch in `stack_is_up`. |
| `platform/tests/conftest.py`, `platform/pytest.ini`, `test/pytest.ini` | Covered in section 2. There is no `pytest.ini` at the repo root. |
| `platform/tests/test_verify_stack.py` | Marked as a whole by the module-level `stands_in_for_docker` marker (as are `test_docker_runner.py` and one test in `test_customer_traffic.py`). Retarget it, or drop the marker from it, before the marker is removed from `platform/pytest.ini` and conftest. |
| Docs | `CLAUDE.md` (the pair example on lines 47–48; drop the nginx `/terminal/` and `waf-terminal.sh` seam exceptions; rewrite the bring-up gotcha). `ARCHITECTURE.md` and `.ko.md` (44 and 22 docker mentions; seam table). `README.md` and `.ko.md` need no deletion for this plan: the Docker-mode text (`session.yaml`, `fsl-<id>` projects, `logs-<id>`) is already gone from them (ac94c64); only item 7's local-development note is still to be added. `OPENSTACK.md`, `THREAT-MODEL.md` and `test/README.md` no longer present the docker substrate as a way to run; what Docker text remains in `OPENSTACK.md` is the platform VM's and the wargame host's own Docker, which stays. `STATE.md` ("What exists now" and the backlog; leave the finished-record history as it is). The `DECISIONS.md` entry that supersedes the 2026-10-11 "first-class substrate" ruling is already written (2026-10-20). `now.md`. |

**Keep, even though the name says docker**

| File | Why it stays |
|---|---|
| `wargames/*/compose.yaml` | The wargame host renders them (`range/wargame_host.py`: `COMPOSE`, `render`, `sideloaded_images`). |
| `deploy/suricata/suricata.yaml`, `rules/*.rules` | The wargame host bundle (estate sensor) and the acceptance rule tests use them. |
| `deploy/proxy/stamp.py`; `deploy/kali/{setup.sh,bashrc,operator-log.sh}` | They are in the Kali VM bundle. |
| `deploy/gns3/*`, the gns3 service, the docker socket and `pid: host` | GNS3 uses docker display nodes on the OpenStack maps too. |
| `range/cloud.py` `_compose_networks` / `DOCKER_DEFAULT_POOLS` | These are the platform VM's own docker bridges. After the change only `mgmt` remains. |
| `range/interfaces.py`, `wargame_host.py` docker commands | They run on the wargame host or through the platform's docker. |
| `rules/crs.py` / `rules/suricata.py` default paths | Core code; fallbacks only. Changing them is not needed (`core_loc` unchanged). |
| The `ports.Substrate` duck-typed seam, the unslotted readiness reply | Test fakes use it. Changing it would be a much larger rewrite. |

## 2. How the unit tests change

- **New `platform/tests/standin.py`** (a helper module, not `test_*`, so it does not count in `tests`). It reproduces what the conftest-refused Docker adapter gave the suite before: every range call raises `RangeUnavailable`, `address()` returns `""`, there is no stack to open, and it is unslotted.
- **Conftest.** An autouse fixture replaces `no_real_substrate` and `no_real_session_stack` by setting `settings.FSL_SUBSTRATE = "tests.standin.StandIn"`. `range.substrate()` reads the setting on each call, so no production change is needed. A guard on `range.ports.execute` and `range.openstack.subprocess` stops tests from running real ssh or docker. The `stands_in_for_docker` and `opens_session_stack` markers go.
- **Retarget** tests that patch `range.docker.Docker.runner`, `segments`, `open_session` or `has_stack`, so they patch `api.views.substrate` with a fake (the existing `OneSlot` / `Stand` pattern, keyed by slot instead of session). Files: `test_lesson_api` (14 sites), `test_foundations`, `test_lesson_path`, `test_scenario_engine`, the generic parts of `test_session_start`, `test_session_isolation` and `test_session_stack` (baseline-at-open, a failed open leaves no session, suppression lifecycle, write naming no session / closed session refused), `test_rules`.
- **Settings flip.** Tests that assumed the docker-flavored `settings.RANGE` must move to the OpenStack values: `fsl-suricata`, `fsl-proxy`, `host-rewrite`, `logs-{session}`, `/terminal/`, the crs default paths. That is about 15–25 edits in about 12 files. Their `flavor="openstack"` boilerplate goes away.
- **Retarget, keep:**
  - `test_openstack_sketch`: compare signatures against `ports.Substrate`, not `docker.Docker`.
  - `test_estate_sensor`: pin the sensor image digest in `sensor.yaml` itself, no longer equal to `session.yaml`.
  - `test_range_seam`: point the outage and result tests at `ThroughPlatform`.
  - `test_topology_console`, `test_gns3_maps`, `test_gns3_topology`: OpenStack maps only (the language pair test keeps its one pair).
  - `test_console_behaviour`: the fixture URL becomes `/vm-terminal/waf/?arg=7`.
  - `test_measure` and `composed.py`: no session file.
- **Delete** (about 80 tests). Each tests only the removed mechanism, and each commit message will say so:

| File | Tests deleted | What they test |
|---|---|---|
| `test_docker_runner` | 4 | the docker runner |
| `test_range_shape` | 14 | docker network discovery |
| `test_session_stack` | ~9 | compose project up/down, `STACKS_CHANGING`, `gethostname` |
| `test_session_isolation` | ~18 | `fsl-N-*` containers, per-session index and proxy, `waf-terminal.sh`, nginx `/terminal/<id>` |
| `test_compose` | ~8 | `session.yaml` services, gw_priority, wargames included by the stack |
| `test_range_seam` | ~5 | docker ps, segments, recreate |
| `test_session_start` | 3 | `docker_*` |
| `test_customer_traffic` | 1 | `on_docker` |
| `test_rules` | 2 | docker stdin and missing sensor |
| `test_corp_waf` | 1 | `deploy/nginx/corp.conf` |
| `test_operator_log` | 1 | Dockerfile parity |
| `test_front` | ~2 | kali ports, `/terminal/` |
| `test_prebuilt_images` | ~2 | `session.yaml` pull, kali tag |
| `test_filebeat` | ~3 | filestream inputs |
| `test_gns3_*` | ~3 | docker maps |
| `test_declaration` | ~2 | docker networks |
| `test_api_traffic` | 0 (cleanup) | its fake's `drop_users_box` goes |

## 3. Ratchet effects

| Number | Before | After | Gate |
|---|---|---|---|
| `core_loc` | 584 | 584 (no core file touched) | ok |
| `dependencies` | 6 | 6 | ok |
| `services` | 10 | 5 (the five `session.yaml` services go) | falls; record with `bin/measure --save` |
| `wargame_services` | 4 | 4 with the `bin/measure` change; 0 without it (an artifact of the counting) | reported |
| `product_loc` | 28,192 | about 25,000 (−3,100, of which about 2,390 is GNS3 JSON) | reported |
| `tests` | 1,232 | about 1,150 | reported; each deletion justified. This counts module-level `test_*` functions as `bin/measure` counts them; the "unit 1718" of `now.md` counts pytest items (parametrized cases and class methods included), so the two differ |

No gated number grows. The `core_loc` count stays honest: no logic moves into uncounted paths.

## 4. Commit order (each passes `bin/verify --fast`)

1. **Unit tests stand in for the range without the docker adapter.** Add `standin.py`, switch conftest to it, retarget the `range.docker.Docker.*` patches. `docker.py` and its own tests stay (they still patch `range.docker.subprocess`).
2. **Settings default to OpenStack.** Flip `FSL_SUBSTRATE` and remove the docker branches in settings. Fix the tests that assumed docker-flavored settings. The Docker adapter tests still pass because they build `Docker(declared.read())` directly.
3. **Docker substrate removed.** Delete `docker.py` and its tests, `session.yaml`, `waf-terminal.sh`, the nginx blocks and the ttyd line, the compose plugin, `deploy/nginx/`, the kali and proxy Dockerfiles, the compose edge networks and mount, the filebeat filestream inputs. Update `composed.py`, `test_compose`, `bin/measure`, `bin/select-tests` and `metrics.json` (`--save`).
4. **Images and bring-up.** `images.yml`, platform-rebuild `IMAGES`, the `platform.yaml` pull line, `bin/verify` checks, `redteam/tools.py`.
5. **Docker learner and system maps removed.** The three `.gns3` files and the GNS3 tests.
6. **Acceptance harness OpenStack-only.** `test/range.py`, `test/conftest.py`, `test_range_seam`.
7. D1–D3 (decided yes):
   - 7a. Dead docker branches in views, site, customers, maps and `redteam/run`.
   - 7b. The `host-rewrite` origin mode.
   - 7c. Fold the declaration overlay into the base.
8. **Docs.** The CLAUDE.md seams and exceptions text, the ARCHITECTURE and README pairs (each with its `.ko.md`), OPENSTACK, THREAT-MODEL, `test/README`, STATE, a `DECISIONS` entry, `now.md`. Then a fresh-context reviewer lists doc-versus-code contradictions.

`bin/verify --changed` while working on each; `--fast` before each commit, comparing `bin/measure` against `metrics.json` by hand.

## 5. How it is proven

1. Locally: `bin/verify --fast` green at each commit, with the output shown.
2. Live, on the platform VM (192.168.0.210):
   - a. **Check for an open session** with `GET /api/sessions/?state=open`. If one is open, both `bin/verify` and `--replace` would destroy it. If it is a test session (opened by a harness or an earlier run of this work), back it up (`bin/backup`) and close it (`POST /api/sessions/<id>/close/`), then go on, without asking. If it may be the user's own session (started by a person in the console), ask the user first.
   - b. **Rebuild the VM** with `bin/cloud up --replace --sideload …`. Sideload `platform` only, built from HEAD (an unpushed commit has no GHCR tags). `bin/platform-rebuild` refuses when another image's context differs from the ref the VM cloned, and none does: only `platform/` differs from `origin/dev` (4fd2ab1); board, corp, corp-db and gns3 run GHCR's copies at that tag, and kali and proxy are no longer images. The operator tooling that builds and deploys it is in `docs/state/now.md`, "Operator tooling". This exercises the backup, a fresh `compose.yaml` start with no edge networks, and the store restore.
   - c. **Wait for `GET /api/range/ready/`** to report `ready: true`. Expect a new fsl-kali image build and a rebuild of both slots, because the Kali bundle hash changes (see risk 2).
   - d. **Run the full `bin/verify` on the VM.** Unit tests, then acceptance (73 collected, 0 skipped, TP > 0 and TN > 0), then the ratchet.
   - e. **Run the other live paths untouched:**
     - close a session, then the slot reset, then `ready` again;
     - check the learner and system maps (`GET /api/sessions/<id>/topology/`): the platform node is still placed right with the edge bridges gone;
     - open the WAF and Kali panes (`/vm-terminal/*`);
     - run `bin/cloud up`'s `cloud.yaml` check (`taken()` now holds only `mgmt` and the origins).
3. Gate 2 gets one row per path with its command output.

## 6. Risks

1. **Control-plane start without the edge networks.** The platform's default gateway moves to `mgmt`, and the 8000/8002 publish follows it (the DECISIONS entry of 2026-10-11 on the default gateway). Only a fresh VM rebuild plus acceptance proves it. A rebuilt VM also avoids stale `fsl_edge*` bridges.
2. **Kali image rebuild.** Deleting `deploy/kali/Dockerfile` changes the fsl-kali image hash, so the cloud builds a new image and rebuilds both slots. That costs time, but it is also the live proof of the build path. `fsl-waf`'s hash must stay the same: keep its `files` and `setup` exactly when editing or folding the declaration.
3. **Unit tests drift in meaning.** The stand-in has no `for_session`, so `_written` (writes naming no session) behaves like single-slot OpenStack, not docker. Tests whose assertion changes are listed in the commit; none is loosened silently.
4. **Platform-map placement.** `_own_listed` read the VM's docker bridges, which carried the origin subnets. With them gone the platform node may sit differently on the map. Check it live.
5. **GNS3 pairs.** Delete the English and Korean docker pair in one commit. `bin/check-topology` and the pair test then see only the OpenStack pair and the OpenStack system map.
6. **The seams list in CLAUDE.md and ARCHITECTURE.** Only two exceptions disappear (nginx's `/terminal/` route and `waf-terminal.sh`). `operator_log.py` and the `fsl-kali` wiring via `vm-terminal.sh` stay. No seam file changes.
7. **Local development.** The range can no longer run on a laptop; unit tests still do. Say so in README and CLAUDE.md. The `build:` keys stay, because the CI build test checks them.
8. **The running VM before its rebuild.** Its unit file still pulls `session.yaml`; this is harmless because the line is `-`-prefixed. Do not rely on `git pull` in place; the VM is rebuilt.

## 7. Size estimate

| | Files | Lines |
|---|---|---|
| Deleted | ~18 (~14 production or deploy, ~4 test) | about 4,300 (adapter and session stack ~560, GNS3 JSON ~2,390, test files ~1,250, small scripts and configs ~100) |
| Production changed | ~23 (settings, compose, nginx, entrypoint, Dockerfile, filebeat, declaration and `declared.py`, `platform.yaml`, `images.yml`, 4 `bin/` scripts, `redteam` ×2, `test/range.py`, `test/conftest.py`, views, site, customers, maps and attacker for D1/D2) | about −250 / +60 |
| Unit tests changed | ~35–45 | about −1,000 / +250 (`standin.py` about 40) |
| Docs | ~12 | about −300 / +150 |

`product_loc` falls by about 3,100; `services` goes from 10 to 5.

## Decisions (all decided yes, 2026-10-20)

- **D1.** Remove the views/site/customers/maps branches that only the docker adapter filled (commit 7a, about −40 lines). Otherwise production code is reachable only from test fakes.
- **D2.** Remove the `host-rewrite` origin mode (commit 7b, about −40 lines, touching the `attacker.py` seam file), as its own commit.
- **D3.** Fold the `openstack:` overlay into the base declaration and drop `flavor_for` / `_overlaid` (commit 7c), keeping the `fsl-waf` and `fsl-kali` bundle files byte-for-byte.
- **D4.** `bin/measure` counts `wargame_services` from `wargames/*/compose.yaml`; without it the number drops to 0 for no real reason.

## Critical files for implementation

- `platform/fsl/settings.py`
- `platform/tests/conftest.py`
- `platform/range/declaration.yaml`
- `compose.yaml`
- `test/range.py`
