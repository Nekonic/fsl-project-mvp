# fsl-project-mvp

A cyber attack/defence training range. A red team attacks OWASP Juice Shop or
a Django board on MySQL, a blue team defends them with Suricata and
ModSecurity, and the platform scores what each side achieved. This repo is the
throwaway prototype; the production project lives elsewhere.

- `CLAUDE.md`: what the repo is for, how the score works, the working rules
- `docs/ARCHITECTURE.md`: how the range is put together, and where it is going
- `docs/THREAT-MODEL.md`: what the range emulates and what it leaves out
- `docs/STATE.md`: where the work stands

## How it fits together

### Where it runs

On the OpenStack cloud the whole stack runs inside one VM, which one Heat
stack (`deploy/openstack/platform.yaml`) creates. The platform reads the range through the OpenStack API as the
member-role user `fsl-range`; the range it scores is still the Docker one
inside the VM (backlog 2 in `docs/STATE.md` moves it onto OpenStack).

```mermaid
flowchart TB
  person(["browser"])

  subgraph cloud["OpenStack project fsl-range"]
    api["OpenStack API<br/>Keystone, Neutron, Nova"]
    subgraph heat["Heat stack fsl-platform"]
      fip["floating IP<br/>ssh and ping only"]
      subgraph vm["platform VM, Ubuntu 24.04"]
        unit["fsl-platform.service<br/>docker compose up -d --build"]
        stack["the compose stack<br/>(next graph)"]
      end
    end
    subgraph standin["stand-in range, bin/openstack-range"]
      nets["six networks fsl-*<br/>tagged fsl.segment.id"]
      target["VM fsl-juice-shop<br/>bare Ubuntu"]
    end
  end

  person -->|"ssh tunnel"| fip
  fip --> vm
  unit -->|"every boot"| stack
  stack -->|"describe(), segments()"| api
  api -.->|lists| nets
  api -.->|lists| target
```

### Inside the stack

The red team attacks through the blue team's defences into a wargame; the
blue team's sensors log into Elasticsearch; the platform referees, scoring
from those alerts and from the target's own verdict. The platform, red and
blue teams are in the top `compose.yaml`; each wargame is a folder under
`wargames/` that it includes, so a new wargame is a new folder and one more
`include:` line.

```mermaid
flowchart LR
  person(["browser"])

  subgraph red["Red team"]
    kali["kali<br/>attack terminal"]
    proxy["proxy<br/>labels each case"]
  end

  subgraph blue["Blue team"]
    waf["waf<br/>nginx + ModSecurity CRS"]
    suricata["suricata<br/>IDS on the WAF's traffic"]
    filebeat["filebeat"]
    es[("elasticsearch")]
  end

  subgraph wargames["Wargames, wargames/*"]
    juice["juice-shop<br/>and the wiki behind it"]
    board["board<br/>and its MySQL"]
  end

  subgraph platform["Platform, the referee"]
    console["console and /api/"]
    scoring["scoring"]
  end

  person -->|":8000"| console
  console -->|"/terminal/"| kali
  kali --> proxy
  proxy --> waf
  waf --> juice
  waf --> board
  suricata -.->|watches| waf
  waf -.->|audit log| filebeat
  suricata -.->|alerts| filebeat
  filebeat --> es
  es -->|alerts| scoring
  juice -.->|own verdict| scoring
  console --> scoring
```

Left out to keep the lines readable: Kali's raw TCP goes straight to the WAF
without the proxy; the platform fires scripted cases at the WAF itself; and
through the substrate (`docker exec` here, ssh on OpenStack) it writes the
sensor's rules and the proxy's case label and reads the wiki's read log and
the attacker's command log. The networks are in `docs/ARCHITECTURE.md`.

## Bringing it up

On a host with Docker, clone the repo and bring the stack up:

```bash
docker compose up -d --build
```

The platform sorts out the docker socket group and registers the Elasticsearch
ingest pipeline (which geolocates source addresses) on start, so there is
nothing else to run. Firing the scripted cases from the command line and
`bin/verify`, `--fast` included, need a virtualenv:

```bash
python3 -m venv .venv && .venv/bin/pip install -r platform/requirements.txt
```

| Port | | Used by |
|---|---|---|
| 8000 | the console, `/api/`, and the attacker's terminal at `/terminal/` | a person's browser |
| 8080 | the target, through the WAF | the command-line cases and the acceptance tests |
| 9200 | Elasticsearch | the acceptance tests |

A person needs only 8000: nginx inside the platform's image takes it and
hands `/terminal/` to Kali's ttyd, which publishes no port of its own. Every
port is published on `127.0.0.1` only. Inside the range both targets sit
behind the WAF on port 80: Juice Shop as `http://shop.com` (on the `edge`
network only) and the board as `http://board.com` (on every edge network). A
session is on Juice Shop unless it is created with `{"scenario": "board"}`.

### On OpenStack

`deploy/openstack/platform.yaml` is a Heat template for the platform VM. What
it creates and what its first boot does are in `docs/ARCHITECTURE.md`
("Built: the platform VM"). As a project member, with the project's openrc
sourced and `python-heatclient` installed:

```bash
openstack stack create -t deploy/openstack/platform.yaml --parameter keystone=http://KEYSTONE:5000 fsl-platform
```

`keystone` is Keystone's base URL without `/v3`; the platform adds it. The
user is looked up in domain `default`, and the project is the stack's own.
The password never goes into the stack: Nova keeps an instance's user data,
and its metadata service serves it to whatever runs on the VM, the range's
containers included. Once the stack's `address` answers ssh, add the password
from a file, so it never reaches a command line, and recreate the platform:

```bash
{ printf 'FSL_OPENSTACK_PASSWORD='; cat PASSWORD_FILE; echo; } | ssh ubuntu@ADDRESS 'cloud-init status --wait >/dev/null && cat >> /opt/fsl/openstack.env && sudo docker compose -f /opt/fsl/compose.yaml up -d platform'
```

| Parameter | Default | |
|---|---|---|
| `ref` | `dev` | the branch or tag to clone |
| `repository` | this repo on GitHub | |
| `user` | `fsl-range` | the Keystone user the platform signs in as |
| `key_name` | `fsl-claude` | the keypair whose private key `ssh ubuntu@ADDRESS` needs |
| `image` | `ubuntu-24.04` | |
| `flavor` | `m1.windows` | |
| `external_network` | `provider` | |
| `cidr` | `10.20.0.0/24` | must not overlap the compose subnets or `172.17.0.0/16` |
| `dns` | `8.8.8.8,8.8.4.4` | |

The stack's `address` output is the floating IP. The ports stay on the VM's
loopback, so a person reaches the one they need through ssh:

```bash
ssh -L 8000:127.0.0.1:8000 ubuntu@ADDRESS
```

On the VM the checkout is `/opt/fsl`, owned by `ubuntu`; run compose,
`bin/backup` and the restore below there. `systemctl status fsl-platform`
shows how the last boot's bring-up went.

`openstack stack delete fsl-platform` removes all of it.

`bin/openstack-range up|down`, run on the cloud host with the project's
openrc, builds a stand-in range on the same cloud: the `fsl-claude` keypair
that `key_name` defaults to (from `FSL_RANGE_PUBLIC_KEY`), security group
`fsl-sg` (tcp 22, 80 and 3000, and ICMP), six networks `fsl-<id>` tagged
`fsl.segment.id=<id>` with compose's subnets, and the server `fsl-juice-shop`.
`down` removes it.

## Running a round

Open http://localhost:8000, start a session, and open the red and blue consoles
side by side. The language button in the header switches between English and
Korean.

- **Red** has the objectives, a Kali shell and the scripted cases. A fired
  case is labelled on the way out. Alternatively name a case, press start,
  work in the shell and press stop: everything sent in between is attributed
  to that name.
- **Blue** has a dashboard, live alerts, the scoreboard and the Suricata rules.
  It ingests on a timer. Any alert opens the Elasticsearch record behind it.

The scripted Juice Shop cases can also be fired from the command line, as the
acceptance tests do:

```bash
.venv/bin/python redteam/run.py
```

## Checking it

```bash
bin/verify --fast     # unit and API tests and the metrics, no stack needed
bin/verify            # also the acceptance tests in test/, against the live stack
```

The full run restarts the platform and resets the target, the rules and the
attacker's origin, so do not run it against a stack someone is using. It deletes only the sessions its own run created.
`bin/prune` deletes sessions by hand and is a dry run without `--apply`:

```bash
bin/prune --keep 20 --apply      # keep the newest 20
bin/prune --ids FILE --apply     # only the closed sessions FILE lists
```

After adding a Tailwind class to a template, run `bin/build-css`. The
stylesheet is generated and committed so the console renders without internet
access, and a test fails when it is out of date.

## Backup and restore

The platform's store (sessions, cases, detections, objectives, rule sets,
suppressions) is one SQLite file, `/data/db.sqlite3` on the `fsl_platformdata`
volume. Nothing else is backed up: not Elasticsearch's `fsl_esdata` volume,
not Filebeat's registry in `fsl_filebeatdata`, not ModSecurity's audit log in
`fsl_waflogs`, and not Suricata's `eve.json`, a plain file in
`deploy/suricata/logs`. `docker compose down -v` deletes the four volumes and
leaves that file.

```bash
bin/backup      # writes backups/db-<UTC time>.sqlite3 while the platform serves
```

It uses SQLite's online backup API, checks the copy with `PRAGMA
integrity_check`, and keeps nothing if either step fails. To reach a platform
that is not in Docker, set `FSL_PLATFORM_EXEC` to a command that runs
`python -` with the platform's settings importable.

Restore by hand, with the platform stopped:

```bash
docker compose stop platform
docker run --rm --network none --entrypoint sh --user fsl \
  -v fsl_platformdata:/data -v "$PWD/backups:/backups:ro" fsl-platform \
  -c 'rm -f /data/db.sqlite3-journal && cp /backups/db-20260925T020000Z.sqlite3 /data/db.sqlite3'
docker compose start platform
```

The image's entrypoint ignores its arguments and starts the server, so
`--entrypoint sh` replaces it. The image itself runs as root; `--user fsl`
makes the copy the platform's user's, where `docker cp` would leave it owned
by root and unwritable. The old `-journal` has to go, or SQLite would replay
it onto the restored file. On start the platform applies any migration the
backup predates. The copy has been checked on a scratch volume (it lands
owned by `fsl`); the whole procedure has not been run against a live stack.

## Local lab only

Elasticsearch runs without security and Django with `DEBUG=1`. Django answers
only to `localhost`, `127.0.0.1` and `[::1]` unless `DJANGO_ALLOWED_HOSTS`
names more; to use the range from another machine, tunnel to it. The Docker
socket is mounted into the platform, and the Kali shell at `/terminal/` is an
unauthenticated root shell. Both are container escape paths.

The same holds on the platform VM. There the project's password is also plain
text in `/opt/fsl/openstack.env` and in the platform container's environment.
The VM's ssh port is open to any address.
