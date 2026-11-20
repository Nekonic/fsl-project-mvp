# fsl-project-mvp

A cyber attack/defence training range: a red team attacks a web app, a blue
team defends with Suricata and ModSecurity, the platform scores the defence.
This repo builds that product cheaply enough to throw away — the real one lives
in another repo — to find out which screens, scoring and stack it should have.
Build it, measure it, keep what survives, write down what did not. A Django
replacement was built in full, measured and discarded in a day.

## How work runs here

This session is the orchestrator. You state a goal in plain language; the
session scopes it, runs the stages (workflows, subagents), keeps docs matching
the code, and reports. The procedure is the `orchestrate` skill; invoke it when
work starts.

Two review gates, and only these two stop the run:

1. Before building — present a short plan or spec and wait for approval.
2. Before a version goes to `main` — present what changed, visually
   (diagram, table, not walls of prose), with the verification evidence, and
   wait for approval.

Between the gates the session works on its own: report progress, do not ask
"continue?". Stop early only for a real blocker or a decision that changes what
the product does. The code may be replaced at any time, so commits, branches,
tags and pushes to `dev` and to working branches need no gate: push a verified
state to `dev` as a fast-forward, keep as many branches as the work needs, and
tag a version (`vMAJOR.MINOR.PATCH`) when a verified state is worth keeping.
`main` holds only the best version: a tagged state that passed the full
`bin/verify`, a live review round with zero countable findings, and a docs
review that found no document out of step with the code, moved there as a fast-forward after gate 2. Never force-push `dev` or `main`.

Replies are short — the result and the reason, no restatement, no analogy;
detail goes in the commit and `docs/DECISIONS.md`. Documents and replies carry
no commit SHAs: `git log` holds them and a merge or rebase changes them; say
what changed in words and name a version by its tag (2026-11-18, the user's
ruling). Use the words practitioners
use and do not invent terms; when the field already names a thing, quote a
primary source rather than your own sense of the vocabulary.

## Working language

Reply to the user in Korean. Repo files may be written in Korean or English;
no test restricts where Korean appears (2026-11-20, the user's ruling).
Code carries no comments in any language.

The product itself is Korean-only: everything a learner or operator sees in
the console and on the learner map is Korean, and there is no English version
or language switch. This is about the product, not the working language.

The Korean the console shows lives in `strings/console.json` (bundled into
`front/`; the API sends stable English codes and the front end maps them
here) and `strings/server.json` (the Kibana gate page, read only by
`cr/strings.py`). Leave them unread unless you are editing them.
Problem and lesson text is Korean too, but it lives only in database rows,
written through the staff API and moved between stores by its export and
import; no seed, fixture or migration carries it, and test fixtures are English
placeholders (`platform/testing/factories.py`).

Generated code is not committed: `bin/gen-clients` exports the committed
contract `openapi/schema.yaml` and generates `bots/client/` and
`front/src/api/schema.d.ts` from it, because the generators write docstrings
and the no-comments rule has no exception for them. `bin/verify` generates
both before use; the platform Dockerfile's node stage generates only
`front/src/api/schema.d.ts` (`npm run types`) before it builds `front/`, and
the image carries neither.

Korean text is written Korean-first: from the meaning, not translated from the
English sentence, in the usage of Korean security practitioners rather than the
National Institute of Korean Language's norms.

## How the score works

Two separate numbers; the first is the primary score.

What the red team took: the target flips its own ground truth when an objective
falls — for the board, loot that exactly matches the round-start snapshot of
its secret. That is the score: which objectives were lost, and whether the blue
team saw each one go; one lost and undetected counts double. The platform never
decides whether an attack succeeded — the target's own stored data does.

What the defence got wrong: TP, FP, FN, TN per attack case, from matching
alerts to the cases that caused them. Reported beside the first number, never
folded in — a defence that blocks everything scores perfectly here and loses
every objective.

One case is one decision however many alerts it drew (`board-sqli-orderby-sqlmap`
sends about 2,000 requests through the WAF and draws many alerts, and counts once); say so when
reporting, because per-alert counting measures the alert threshold, not the
defence. A true positive must also
survive `expect`: the case names a substring its signature should match, and an
alert that does not mention the attack's mechanism is reported
`corroborated: false`. Only declared cases and the platform-fired benign cases
enter TP/FP/FN/TN; a free action (a request, tool run, command or site-pane
request with no declared case) is reported apart under `free_actions` and
never scored as one.

## What must not break

- `test/` stays green, in particular TP > 0 and TN > 0 — attacks detected,
  benign traffic passes. That is the hypothesis.
- The benign cases in `redteam/cases/` stay; deleting them makes the score look
  good and the platform pointless.
- The target decides whether it was beaten; never mark an objective from the
  platform's own belief about an attack. The objective layer's value is that
  its ground truth is orthogonal to the detector.
- The isolation seams hold (paths under `platform/`):
  `ingest/elastic.py` is the only file that knows Elasticsearch, the ingest
  pipeline included; `rules/suricata.py` the only one that knows the Suricata
  process (rule file, `-T`, the offline `-r` run, reload, packet capture);
  `rules/crs.py` the only one that knows the CRS/ModSecurity configuration,
  the nginx reload and the scratch test instance; `defence/kibana.py` the
  only one that knows the Kibana API; `range/openstack.py` the only one that
  knows the OpenStack API and the only one that reads the stack's live wiring
  the learner map draws from Neutron and the target VM's Docker networks
  (`range/wiring.py` parses it, `range/topology.py` names it for the learner,
  filtered by side); `range/edge.py` the only one that writes the infra
  router's nftables `pool` and `spent` sets; `range/jump.py` the only one
  that knows the platform sshd's jump grants and the per-seat key in a box
  account's `authorized_keys`; `attack/box.py` the only one that knows the
  attacker box (origins, `set-origin`, the command log, the tool image,
  customer origins, stopping runs); and `referee/loot.py` (the board) and
  `referee/effect.py` (corp) the only ones that read the target's ground
  truth. Keep them the only ones. `platform/tests/seams/test_isolation_seams.py`
  holds one pattern per seam (packet capture, the nftables sets, the node
  names `cr-kali`, `cr-waf`, `cr-infra`, `cr-target` and the log index
  patterns among them), scans `platform/`, `front/src`, `bots/`, `test/` and
  `bin/`, and holds the closed list of exceptions below; it fails when the
  two lists differ.
  Known exceptions in code today; do not add more:
  `cr/config.py` holds the defaults the seams are handed (the CRS exclusion
  file and the nginx reload for `rules/crs.py`, the box's label file and
  node names for `attack/box.py`, the log index pattern); the acceptance
  checks of Elasticsearch's own set-up, `test/test_event_time.py`,
  `test/test_geoip_durable.py`, `test/test_origin_placement.py` and
  `test/test_waf_geolocation.py`, read Elasticsearch directly; in each `wargames/<id>/topology.yaml` the sensor device
  `cr-ids` names the rule file and reload command `rules/suricata.py` is
  handed, and the WAF device `cr-waf` the exclusion file and nginx reload
  `rules/crs.py` is handed; `platform/nginx.conf` names the Kibana API
  routes it refuses, hands every other API call inside a space to the
  `kibana-gate` view and answers Kibana's `api/spaces/space` lookup itself;
  `platform/entrypoint.sh` starts `vm-terminal.sh cr-kali attack` and
  `vm-terminal.sh cr-waf defence` and creates the jump host's
  `authorized_keys`;
  `deploy/roles/infra/edge.nft` declares the `pool` and `spent` sets
  `range/edge.py` fills; `front/src/panes/Kibana.tsx`
  presets Kibana's localStorage keys. `docs/ARCHITECTURE.md` keeps the table.
- The dependency graph holds: `platform/tests/seams/test_imports.py` checks
  the layers and import rules of the design (`domain/` imports only the
  standard library; a seam imports no Django and no app; `attack` and
  `defence` never import each other; only `referee/` appends
  `objective.lost`; across an app boundary only `<app>.service`), by AST and
  over model foreign keys and migration dependencies. A new module under
  `platform/` must be given a layer there.
- Fixed by the user: OpenStack, Docker, Suricata, nginx, Elasticsearch.
  Everything else may be replaced if it shrinks the project without breaking
  the above.
- Every UI action is a REST API first: there is one attack API and one
  defence API, and the console, the bots, `test/` and `bin/` are all clients
  of `/api/` through the client generated from `openapi/schema.yaml`. A bot
  seat reaches exactly what a human seat reaches, under the same permission
  class — this is what lets an agent take the human's place. `front/`,
  `bots/`, `test/` and `bin/` never import `platform/`.

## Verifying

Run only what a change needs: `bin/verify --changed` (the tests the change
reaches) by default while working; `--fast` before a commit that touches
shared code; the full `bin/verify` with acceptance only when range-facing
logic changed, and before a push.

## Gotchas

- `platform/` is not a package — `platform` is a stdlib name; never add
  `platform/__init__.py`. Run Python with `platform/` as the working directory
  (same for `test/`).
- No comments or docstrings in code, in `platform/`, `front/src`, `bots/`,
  `bin/`, `test/`, `deploy/`, `wargames/` and `redteam/` alike; name things
  so the code says what it does. Exceptions: `deploy/suricata/rules/`, where
  a commented-out rule is how a rule is disabled, the header Django writes
  into generated migrations, and a script's shebang.
  `platform/tests/seams/test_no_comments.py` scans Python (comment tokens
  and docstrings), shell (trailing comments and Python fed to a heredoc
  included) and TS/TSX/JS.
- `platform/domain/` is the pure core: the game rules as functions over
  frozen dataclasses, tested by `platform/tests/domain/` with no Django in the
  process. Services raise `cr/errors.py` domain errors and never build
  responses; `cr/handler.py` maps them to the one error shape.
- The target is not published; cases are fired from the attacker box inside
  the range (`attack/firing.py`).
  The product runs only on OpenStack: the range is one Heat stack per lease
  (`cr-slot-<n>`: the VMs kali, waf, infra and target on the stack's own
  Neutron LANs, booted from role images baked from `deploy/roles/` into
  Glance), kept ready in a pool per wargame (`compute.pool`), given to a
  lease when it opens and deleted and built again when it closes; `<n>` is
  the reused stack number (`docs/ARCHITECTURE.md` glossary), and the platform
  VM runs the shared control plane from `compose.yaml`. Bring-up
  pulls prebuilt images from GHCR (built by `.github/workflows/images.yml` on
  push to `dev`): `docker compose pull && docker compose up -d` starts the
  control plane (it registers the Elasticsearch ingest pipeline; no service
  holds the Docker socket). Local development runs the unit tests, not
  the range. The `build:` keys stay because the CI build test checks them. The
  platform VM is rebuilt, never patched in place: `bin/cloud up --replace`
  (`bin/platform-rebuild`, then the pool converges; a slot stack rendered from
  the same template, images and flavors stands through);
  the whole cloud side comes up with `uv run bin/cloud init` (admin, once)
  and `uv run bin/cloud up` from `deploy/openstack/cloud.yaml`, the one file
  of cloud-specific values (no secrets; init writes it from
  `cloud.example.yaml`), signing in with the `~/.config/openstack/clouds.yaml`
  entry it names; the cloud holds the stock Ubuntu 24.04 cloud image, uploaded
  as is, and the four role images `compute.images` names (`cr-<role>-bake1`
  by default). OpenStack procedures are in
  `docs/OPENSTACK.md`.
  `README.md` has the ports, `docs/ARCHITECTURE.md` the file map and the isolation seams,
  `docs/superpowers/specs/` the design.
