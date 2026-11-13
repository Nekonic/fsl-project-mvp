# fsl-project-mvp

A training range for cyber attack and defence. The range is the set of
containers and networks where the attack and the defence happen. A red team attacks two
websites: a Django board and a WordPress company site. Each has its own MySQL
database, and a WAF sits in front of both. A blue team defends with Suricata
and ModSecurity. The platform scores both teams. This repo is a throwaway
prototype. The production project is in another repo.

It runs on OpenStack deployed with Kolla-Ansible 2025.1 or later and
`nova_compute_virt_type: kvm`. One Heat stack creates the platform VM. The
platform VM runs the platform as containers (`docker compose`, prebuilt images
from GHCR). The platform then boots one more VM, the range host, through the
OpenStack API, and runs each copy of the range on it as containers.
`bin/cloud` does all of this from your machine.

- `CLAUDE.md`: what the repo is for, how the score works, the working rules
- `docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`:
  the approved direction (2026-10-08). Parts of it are not built yet.
- `docs/ARCHITECTURE.md`: how the range is put together, and where it is going
- `docs/THREAT-MODEL.md`: what the range imitates and what it leaves out
- `docs/STATE.md`: where the work stands
- `docs/OPENSTACK.md`: what the cloud needs (Kolla-Ansible 2025.1 or later), the project
  and the platform VM, the range, and a trial on one VM
- `docs/TROUBLESHOOTING.md`: problems the range has had, their causes and fixes
- `README.ko.md`, `docs/ARCHITECTURE.ko.md`: this README and the architecture
  document in Korean

## Requirements

The operator machine, where you run `bin/cloud`:

- A machine with `git`, `ssh`, `ssh-keygen` and Python 3.10 or newer. The
  platform uses Django 5.2, which needs Python 3.10.
- `python-openstackclient` and `python-heatclient`, installed into `.venv`
  (step 3). It needs the Python venv module (`python3-venv` on Debian and Ubuntu:
  `sudo apt install python3-venv`).
- A network route to the cloud's API and to the platform VM's floating IP.
- Internet access to github.com and ghcr.io. Before `bin/cloud` deletes
  anything, it checks that it can pull the images.

The cloud:

- OpenStack deployed with Kolla-Ansible 2025.1 or later on x86_64 hosts, with
  `nova_compute_virt_type: kvm`. Heat is on by default. You do not need Cinder,
  Octavia or Designate.
- An external network with a floating-IP pool, and Internet access for the VMs
  on it (`docs/OPENSTACK.md` §2.5 and §2.6).
- Room for two VMs: the platform VM and the range host. A slot is one copy of
  the range, and every slot runs on the range host.
  - The platform VM is 2 vCPU, 8 GB, 60 GB (`compute.flavors.platform`).
  - The range host takes the flavor named in `compute.flavors.range`. The
    example names `dba.range`: 6 vCPU, 16 GB, 60 GB.
  - Together that is 8 vCPU, 24 GB RAM, 2 instances, 1 floating IP and 120 GB
    of disk on the compute node. Nova's default quotas (20 cores, 51200 MB,
    10 instances) already allow this. Nova has no disk quota, so the 120 GB is
    capacity.
  - Each further slot (`compute.slots`) adds containers on the same range
    host, not VMs. The comment in `cloud.example.yaml` budgets about 1.2 GB of
    memory per slot.

To check on one machine first, `docs/OPENSTACK.md` §9 builds the whole cloud in
a single VM on VirtualBox or VMware.

## Bringing it up

1. **Prepare the cloud (an admin, once).** Create the external network, the
   project `fsl-range` with a member user `fsl-range`, the flavor `m1.large`,
   a flavor for the range host (the example names `dba.range`), and the base
   image `ubuntu-24.04`. The commands are in
   `docs/OPENSTACK.md` §2.5, §3.1, §3.3 and §3.6. When you upload the image as
   admin, add `--public`. Otherwise `fsl-range` cannot see it.
2. **Clone.**

   ```bash
   git clone https://github.com/Nekonic/fsl-project-mvp.git && cd fsl-project-mvp
   ```

3. **Make the virtualenv and install the OpenStack CLI in it.** Every later
   command runs through `.venv/bin/`, so you do not activate anything.

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r platform/requirements.txt python-openstackclient python-heatclient
   ```

4. **Make the operator key.** This is the ssh key you use to log in to the
   platform VM. The range key needs no step. It is the key the platform uses to
   log in to the range host, and the first `bin/cloud up` makes
   `~/.ssh/fsl-platform` if it is missing.

   ```bash
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/fsl_claude
   ```

5. **Write `deploy/openstack/cloud.yaml`.** Copy the example. git ignores the
   copy. Change only your own values.

   ```bash
   cp deploy/openstack/cloud.example.yaml deploy/openstack/cloud.yaml
   mkdir -p ~/.config/fsl && (umask 077; touch ~/.config/fsl/fsl-range.password)
   ```

   Write the `fsl-range` user's password on one line in
   `~/.config/fsl/fsl-range.password`. Then set two keys in `cloud.yaml`:

   - `identity.keystone`: Keystone's URL without `/v3`. The example holds the
     maintainer's lab address.
   - `network.external`: the name of the external network from step 1.

   Leave the other keys alone. They already match the steps above.
   `docs/OPENSTACK.md` §4 describes every key. If a value is wrong, the loader
   refuses before it changes anything and names the key.

6. **Create the Nova keypair** from the public half of the operator key. Do it
   as the `fsl-range` user:

   ```bash
   export OS_AUTH_URL=<identity.keystone>/v3 OS_IDENTITY_API_VERSION=3 OS_INTERFACE=public \
     OS_REGION_NAME=RegionOne OS_USER_DOMAIN_ID=default OS_PROJECT_DOMAIN_ID=default \
     OS_PROJECT_NAME=fsl-range OS_USERNAME=fsl-range \
     OS_PASSWORD="$(cat ~/.config/fsl/fsl-range.password)"
   .venv/bin/openstack keypair create --public-key ~/.ssh/fsl_claude.pub fsl-claude
   ```

   Replace `<identity.keystone>` with that value from `cloud.yaml`, for
   example `http://192.168.100.10:5000`. Use the values in `cloud.yaml` for the
   region, the interface and the domain too.

7. **Bring it all up.**

   ```bash
   .venv/bin/python bin/cloud up
   ```

   `bin/cloud up` creates the platform VM. Then it builds the range through
   the platform's own API and prints each step. The first run boots the range
   host, which installs Docker and pulls every range image from GHCR before
   its first slot starts, so it takes longer than later runs. It ends with
   `the range is ready; the platform is at http://ADDRESS:8000/`.

8. **Check that it works.** Open that address in a browser.

   - The home page lists the board wargame. Under **Lessons**, press **Start**
     on **Lesson 1**.
   - The session page opens within seconds. Under **Blue team console**, press
     **Open**. The console shows the **Map** pane with the company network drawn
     on it. Beside it, the lesson note names the first step.
   - If the page says the practice network is not ready, wait. A closed session
     resets its slot first.

   From a terminal, `curl -s http://ADDRESS:8000/api/range/ready/` answers
   `"ready": true` before you start the lesson. It answers `"ready": false`
   while a session is open, and `true` again after the session closes and the
   slot has reset.

9. **If it fails.** `bin/cloud up` stops at the first failure and says why. It
   names the `cloud.yaml` key, the missing flavor or image, the GHCR package
   that is not public, or a range host that failed its setup (slot phase
   `SETUP_FAILED`, with `/var/log/cr-setup.log` on the range host saying why).
   Fix the cause and run the same command again. It continues where it
   stopped. A range host that failed its setup, or whose image tag or setup
   bundle no longer matches, is deleted and booted again by that run when no
   session is open.

   - Platform VM: log in with `ssh -i ~/.ssh/fsl_claude ubuntu@ADDRESS`. Then
     run `systemctl status cr-platform` (how the last boot's bring-up went),
     `sudo cloud-init status --long` and `sudo docker logs cr-platform`.
   - Heat stack: in the shell of step 6, run
     `.venv/bin/openstack stack failures list cr-platform`.
   - The stack exists, but the VM never ran `cr-platform`. `sudo docker ps`
     shows no `cr-platform` container, and `sudo cloud-init status --long`
     shows why. Often the VM has no Internet (`docs/OPENSTACK.md` §2.6). If the
     first boot is only slow, run `bin/cloud up` again and it finishes.
     Otherwise fix the cause and run
     `.venv/bin/python bin/cloud up --replace`. That VM has stored nothing, so
     it is replaced without a backup.
   - Sometimes the new platform VM gets no database from the old one, as in
     the case above or after a `down`. Then `bin/cloud up` restores the newest
     `backups/db-<UTC time>.sqlite3` that holds rows and prints its name. If
     there is none, it starts with an empty database and says so.
   - To start over, run `.venv/bin/python bin/cloud down`, then
     `bin/cloud up` again. `down` removes the range and the stack, including a
     failed stack. It keeps the keypair and the range key.
     If the platform VM holds the database, `down` backs it up first. If it
     cannot back it up, it refuses and deletes nothing. If the platform container
     is stopped, `down` starts it first. It refuses when ssh or Docker on the
     VM does not answer, or when the container does not start. Fix ssh first
     (the operator key, the security group, the route).

## How it fits together

### Where it runs

The platform and the services around it run in one VM. A single Heat stack
(`deploy/openstack/platform.yaml`) creates that VM. The platform controls the
range through the OpenStack API as the member-role user `fsl-range`. On the VM,
`CR_SUBSTRATE=range.openstack.connect` tells the platform that the range is the
OpenStack slot. A session cannot start until `/api/range/ready/` reports the
slot ready.

Cloud-init installs `cr-platform.service`. At every boot it runs
`docker compose pull` and `docker compose up -d` on `/opt/cr/compose.yaml`.

- We build eight images: platform, board, corp, corp-db, gns3, kali, waf and
  edge.
  `.github/workflows/images.yml` builds them on every push to `dev`. It
  publishes them as `ghcr.io/nekonic/cr-<name>`, tagged with the commit SHA
  and with `dev`.
- The VM writes the SHA of the commit it cloned into `/opt/cr/.env` as
  `CR_IMAGE_TAG`. It therefore runs the images of exactly that commit.
- GitHub makes a package private on the first push, even when the repository is
  public. Make each of the eight public once. Otherwise the pull without a
  login fails. On github.com open the package page, then **Package settings**,
  **Change visibility**, **Public**. You cannot undo this.
- The containers on the VM are `cr-platform`, `cr-elasticsearch`,
  `cr-kibana`, `cr-gns3` and `cr-collector`. To read a log, log in with ssh
  and run `sudo docker logs cr-platform` (or another name).
- To run a commit that is not pushed, use `--sideload` (`docs/OPENSTACK.md`
  §5.3).

Elasticsearch's managed GeoIP downloader is off. Elasticsearch reads
`GeoLite2-City.mmdb` from `config/ingest-geoip` instead. This is a bind mount
that survives a container recreate. Cloud-init fills it with `bin/fetch-geoip`,
because the cloud's Elasticsearch cannot reach the download CDN. The file is
not committed.

When the platform starts, it first sets the docker socket group. While it
starts serving, it also does three things in the background:

- It registers the Elasticsearch ingest pipeline. The pipeline sets each
  event's time and looks up the location of source addresses.
- It imports Kibana's data view, the "Alerts" search and the "Overview"
  dashboard.
- It sets Kibana's default route to that search.

These objects are in Kibana's default space. Only port 5601 reaches them.

When a session opens, it gets its own Kibana space, "SOC" (`KIBANA_URL`, set in
`compose.yaml`). The space id is `soc-` plus the session's index pattern,
`soc-logs-<slot>`. The space has a data view "logs-*" and an "Events" search.
They show the engine and the sensor's map name as fields and hide the
platform's internal fields.

The platform builds one OpenStack network for the range: `cr-mgmt`, the
management network, which the platform uses to reach the range host. Each
slot's other networks are Docker networks on the range host: `sN_internet` is
the simulated Internet, with 30 origin subnets, and `sN_estate` is the
company's internal network, where the WAF and the targets sit.

```mermaid
flowchart TB
  person(["browser"])

  subgraph cloud["OpenStack project fsl-range"]
    api["OpenStack API<br/>Keystone, Neutron, Nova"]
    subgraph heat["Heat stack cr-platform"]
      fip["floating IP<br/>8000, 8002, 3080, ssh and ping"]
      subgraph vm["platform VM, Ubuntu 24.04"]
        unit["cr-platform.service<br/>docker compose pull, up -d"]
        stack["the platform's containers<br/>(next graph)"]
      end
    end
    mgmt["cr-mgmt<br/>built by the platform"]
    subgraph rangevm["range host cr-range, Ubuntu 24.04"]
      slots["one docker compose project per slot<br/>s1, s2, ..."]
    end
  end

  person -->|":8000"| fip
  fip --> vm
  unit -->|"every boot"| stack
  stack -->|"/api/range/fabric/, /slot/"| api
  api -.->|builds| mgmt
  api -.->|boots| rangevm
  stack -->|"ssh over cr-mgmt, docker exec"| rangevm
```

### What a session contains

The red team attacks a wargame through the blue team's WAF and IDS. The sensors
send their alerts to Elasticsearch. The platform scores from the alerts and
from the target's own records. The first score is the objectives the red team
took. The second score counts the defence's right and wrong calls (TP, FP, FN,
TN). The target's own data decides whether an attack worked, not the platform.
For the board, the platform compares the hashes the attacker submits with a copy
of the board's accounts taken when the session opened. For corp, it reads the
changes in corp's database log.

`compose.yaml` lists the services on the platform VM; one copy of each runs as
long as the VM does: the platform, Elasticsearch, Kibana, `gns3` (the learners'
maps), and `collector`. The collector is a Filebeat that only receives syslog
from the range.

One session's services run in its slot, the docker compose project `sN` on the
range host: Kali (with the stamping proxy and the customers' traffic), the
edge (an nftables router), the WAF, the board and corp with their MySQL
databases, and two Suricata sensors, one on the slot's Internet bridge and one
on its estate bridge. The range host's rsyslog sends the sensors' alerts and
the WAF's audit log to `collector`.

A closed session stays in the database for `CR_RETAIN_CLOSED_MINUTES` (default
60, set in `compose.yaml`). That is long enough to read its score and debrief.
After that the platform deletes the session with its cases, detections,
customer requests and objectives. It checks at start and each time a session
closes. It never deletes an open session.

To add a wargame you need:

- a folder under `wargames/` with `compose.yaml`, `scenario.yaml` and
  `objectives.yaml`;
- a case file under `redteam/cases/`;
- in `platform/range/declaration.yaml`, its name under `wargames:` in the
  `cr-range` entry and its site name under `names:` in the `cr-waf` entry;
- in `deploy/range-host/slot.yaml`, the last octet of the estate address of
  each service the WAF proxies to under `x-wargames.fronts`, the capabilities
  and limits of each of its services under `x-wargames.limits`, the service's
  name and estate address in the `waf` service's `extra_hosts`, and the site
  name in the `kali` service's `extra_hosts`;
- its services in `LEARNER_FACING` and `CAPABILITIES` in
  `platform/tests/test_containment.py`;
- a `server` block in `deploy/waf/board.com.conf`.

`platform/wargames.py` finds the wargame from `scenario.yaml`. There are two
wargames. The board is Django and is scored by `loot_verified`: submitted
hashes checked against the snapshot of the board's accounts. Corp is WordPress
and is scored by `effect_observed`: the changes in corp's database log.

```mermaid
flowchart LR
  person(["browser"])

  subgraph platformvm["Platform VM"]
    console["console and /api/"]
    scoring["scoring"]
    collector["collector<br/>Filebeat, syslog in"]
    es[("elasticsearch")]
  end

  subgraph slot["One session's slot, compose project sN on cr-range"]
    kali["kali<br/>attack terminal<br/>proxy labels each case"]
    edge["edge<br/>nftables router"]
    edgesensor["Suricata<br/>on sN-inet"]
    waf["waf<br/>nginx + ModSecurity CRS"]
    board["board<br/>and its MySQL"]
    corp["corp<br/>WordPress and its MySQL"]
    estate["Suricata<br/>on sN-estate"]
    rsyslog["the range host's rsyslog"]
  end

  person -->|":8000"| console
  console -->|"terminal"| kali
  kali --> edge
  edge --> waf
  waf --> board
  waf --> corp
  edgesensor -.->|"eve.json"| rsyslog
  waf -.->|"audit log"| rsyslog
  estate -.->|"eve.json"| rsyslog
  rsyslog -.->|"syslog, 5140/udp"| collector
  collector --> es
  es -->|alerts| scoring
  board -.->|its own records| scoring
  console --> scoring
```

Not drawn in the graph:

- Kali's raw TCP skips the proxy and goes through the edge to the WAF.
- Scripted cases leave from the attacker box: the platform runs `curl` or the
  tool in the Kali container, from the chosen origin.
- The platform writes the sensors' rules and the proxy's case label. It reads
  the attacker's command log and corp-db's MySQL binary log (`mysqlbinlog`).
- The platform reads the board's own records (its `auth_user` table) inside
  the board's container, not through the WAF.
- Each of these commands runs as ssh to the range host's `mgmt` address and
  `sudo docker exec` into the slot's container (`sN-kali`, `sN-board` and so
  on).

The Kali terminal appears in the red console, and in the Kali pane of the blue
console in a lesson or scenario. It is a ttyd inside the platform
that logs in over ssh to the range host's `mgmt` address and runs
`docker exec` into the Kali container of the session's slot
(`/vm-terminal/kali/?arg=<session id>`). Its prompt reads `(root㉿kali)`. The
WAF's terminal opens the slot's WAF container the same way, as root. The networks are in
`docs/ARCHITECTURE.md`.

## Operating on OpenStack

The steps above are the short path. This section explains each part.

Everything that differs between clouds is in one file,
`deploy/openstack/cloud.yaml`. git ignores it. You make it by copying
`deploy/openstack/cloud.example.yaml`. It holds:

- Keystone URL, region, interface, domain, project and member user;
- where to read the password: `password_file` or `password_env`. The password
  itself never goes in the file;
- the external network, DNS, the tenant MTU, and the platform, estate and mgmt
  CIDRs;
- the base image name, an availability zone and the number of slots;
- two flavors: `platform` and `range` (the range host);
- the operator's keypair and key file, and the range key;
- the stack, the repository and the ref.

Every script and the Heat stack read this file. If a value does not parse, they
refuse before they touch anything and name every bad key.

The cloud needs exactly one uploaded image: Canonical's stock Ubuntu 24.04
cloud image, uploaded unchanged under the name set in `compute.base_image`.
`docs/OPENSTACK.md` has the download, checksum and `openstack image create`
commands. Both VMs boot from that image, and cloud-init sets each up at boot:

- the platform VM clones the repository and starts `compose.yaml`;
- the range host gets its setup bundle in the Nova user data
  (`deploy/range-host/setup.sh`). It installs Docker, pulls every range image
  from GHCR at the platform's `CR_IMAGE_TAG`, and keeps a pristine copy of the
  targets' volumes for resets.

With the OpenStack CLI in `.venv` (step 3), run these on the operator's
machine:

```bash
.venv/bin/python bin/cloud up        # the platform VM, then the whole range
.venv/bin/python bin/cloud down      # back up the database, keep the key, remove range and stack
```

`up` does these things in order:

1. It creates the platform's Heat stack (`deploy/openstack/platform.yaml`) if
   there is none. With `--replace` it replaces an existing stack through
   `bin/platform-rebuild`.
2. It waits for the API.
3. It calls the platform's range API in order: fabric (the management
   network, keypair and security groups), then slot (boots or replaces the
   range host). It waits until the range host stands and its setup is done,
   then calls configure.
4. It waits until `/api/range/ready/` says ready.
5. It removes what the earlier range of VMs left (`DELETE
   /api/range/leftovers/`) and prints each item.

It stops at the first drift, blocked slot, failed setup or refused configure,
and says why.

`up` and `down` both ran on the test cloud. On 2026-10-20 these
paths ran live: `up --replace --sideload`, plain `up` on a platform whose
container was stopped and which had not taken its hand-over, `down`, and `up`
after `down`, which restored the newest backup that holds rows
(`docs/DECISIONS.md` 2026-10-20, "Live checks of the bring-up paths"). Later that
day, after two more fixes, these ran live too: `down` on a platform whose container
was stopped, `up` on a platform whose `openstack.env` had lost its password
line, the first range key, and `up` after `down` without rebuilding a range
VM. The whole of §9 ran in one VM on an empty cloud (`docs/DECISIONS.md`
2026-10-20, "The one-VM trial and the last bring-up fixes"). All of these ran
on the range of VMs that came before the range host. `docs/OPENSTACK.md` §5
has the steps.

`bin/platform-rebuild` alone creates or replaces only the platform VM:

```bash
.venv/bin/python bin/platform-rebuild            # --cloud PATH, --ref REF
```

Before it deletes anything, it checks that the eight images for the ref's
commit can be pulled from ghcr.io without a login. It keeps the range key
(below) and backs up the database (`bin/backup` over ssh). Then it deletes the
stack, creates it again with every parameter from `cloud.yaml`, and waits until
`/api/sessions/` answers. `backups.keep` in `cloud.yaml` (default 1) sets how
many database backups `bin/platform-rebuild` and `bin/cloud down` leave in
`backups/`.

The new VM clones `ref`, pulls the images tagged with that commit, and starts.
Cloud-init writes the cloud's values into `/opt/cr/openstack.env`. Two secrets
are kept out of the stack: the password and the platform's range ssh key. Nova's
metadata service gives user data to every process on the VM, including
containers, so a secret in the stack would be readable there. When the VM
answers ssh and cloud-init is done, `bin/platform-rebuild`:

1. appends `CR_OPENSTACK_PASSWORD` to `/opt/cr/openstack.env`;
2. writes the range key to `/data/ssh/id_ed25519` in the platform's data
   volume;
3. restores the database it backed up, or, when the old VM held none, the
   newest backup in `backups/` that holds rows;
4. recreates the platform container.

The range key is a file on the operator's machine, `keys.range` (mode 0600). If
the file does not exist:

- `bin/platform-rebuild` makes it (`ssh-keygen`, ed25519) when the stack does
  not exist or its VM holds no database;
- it copies the key once from the running platform when you replace a VM that
  holds a database;
- it refuses when you replace a failed stack.

Because the key survives, the range host and the `cr-platform` keypair keep
trusting the new platform. The range can stay up while you replace the
platform.

To run a commit that is not pushed yet, both commands take `--sideload
NAME=TARBALL` (repeatable). TARBALL is a `docker save` tarball of one image
built from this checkout. The VM still clones `ref` and pulls every image at
that commit. Then the rebuild:

- checks out this checkout's HEAD from a git bundle;
- runs `docker load` on each tarball and tags the image with the cloned
  commit. The platform VM's compose uses that tag. The range host pulls its
  images from GHCR at that tag, so it never sees a sideloaded image;
- recreates every service (`--force-recreate`), so bind-mounted files are
  HEAD's too.

Before it deletes anything, it refuses two things: a tarball that does not hold
exactly one `ghcr.io/nekonic/cr-NAME:<commit>`, and any image whose build
context (`.github/workflows/images.yml`) differs between the commit it came
from and HEAD. A sideloaded VM that reboots may pull the cloned commit's images
from GHCR over the sideloaded ones. Push and rebuild instead of rebooting.

The stack's `address` output is the floating IP. The console is at
`http://ADDRESS:8000/` and asks for no login. Ports 9200 and 5601 listen only on
the VM's loopback. Port 5140/udp listens on all of the VM's addresses.

On the VM the checkout is `/opt/cr`, owned by `ubuntu`. Run compose,
`bin/backup` and the restore below there. `systemctl status cr-platform` shows
how the last boot's bring-up went.

You can also call by hand the range steps that `bin/cloud up` runs. First the
fabric:

```bash
curl -s -X POST -H "Content-Type: application/json" -d "{}" http://ADDRESS:8000/api/range/fabric/
```

`GET` shows what is missing, present, changed from what was declared (drift) or
left over. `DELETE` takes the fabric down. It is refused while a server is
attached.

Then one POST boots the range host `cr-range` from the base image, with its
setup bundle in the user data. It has two ports: one on `mgmt` (security group
`cr-mgmt`, which only the platform reaches) and one on the platform's own
network (security group `cr-egress`, no ingress), which it uses to pull
images. Once its setup reports ready, the platform detaches that second port.
A set-up range host keeps only `cr-range.mgmt`: no way to the Internet and no
DNS resolver.

```bash
curl -s -X POST -H "Content-Type: application/json" -d "{}" http://ADDRESS:8000/api/range/slot/
```

`GET` on the same path reports the range host `SETTING_UP` until its setup
marks `/var/lib/cr/ready`, and `SETUP_FAILED` if the setup fails. Then
`/api/range/ready/` reports the slot phase `SETUP_FAILED`, naming
`/var/log/cr-setup.log` on the range host, and `bin/cloud up` stops with that
reason. On a range host that already stands, the same POST replaces
it when its setup failed or its image tag or setup bundle is not the
platform's, unless a session holds a slot.

`POST /api/range/configure/` then starts each slot. The platform renders the
slot's compose file from `deploy/range-host/slot.yaml` and each wargame's
`wargames/<w>/compose.yaml`, sends it to the range host over ssh, and runs
`deploy/range-host/slot.sh up N`. That starts the compose project `sN`, gives
Kali and the edge their origin addresses, and sets up the range host's rsyslog
to forward the slot's logs. The platform then loads the baseline rules into
both sensors.

`POST /api/range/slot/rebuild/` takes the slot's compose project down with its
volumes. Edited data and rules do not carry over. Run `configure/` after it to
start the slot again.

Closing a session resets its slot in place with `slot.sh reset N`:

- Kali and the WAF are recreated.
- The targets are removed and restored from the pristine volumes the range
  host keeps.
- The edge's neighbour table is flushed. The edge and the sensors keep running.
- The slot's logs are emptied in place, and the sensors reopen their log
  files. The platform then loads the baseline rules into both sensors again.

Meanwhile `GET /api/range/ready/` reports phase `RESETTING`, and opening a
session is refused. If the reset fails, it reports `RESET_FAILED` with the
reason, and `POST /api/range/configure/` retries.

`compute.slots` in `cloud.yaml` (default 1) sets how many copies of the range
stand. Each copy is its own compose project `sN` on the range host, with its
own Internet and estate networks. Slot N's estate is the Nth /24 of
`network.estate` (`10.30.N.0/24` in the example), and its containers are named
`sN-<service>`. Each session holds one slot, so that many sessions can run at
once. Closing a session resets only its slot. `slot/`, `slot/rebuild/` and
`configure/` take `?slot=N`. Without it they act on every slot.

`GET /api/range/leftovers/` lists what the range of VMs before the range host
left in the project: its VMs, image builders, the ports, subnets and networks
of retired segments, the security groups `cr-range` and `cr-build`, and its
images. `DELETE` on the same path removes them. `bin/cloud up` calls it last.

The range is not part of the Heat stack, so it can outlive the platform VM. When
you replace the platform with `bin/platform-rebuild`, the range key is kept, so
the slot and the fabric keep working. The next `POST /api/range/fabric/`
attaches the new server to `mgmt` again, and `configure/` points the range's
syslog at it. If you delete the stack by hand without keeping the key, the new
VM makes a new key, and the fabric reports the old keypair as drift. Then first
send `DELETE` to `/api/range/slot/` (without `?slot=`, which also deletes the
range host) and `/api/range/fabric/`.

The stack boots with the keypair that `keys.operator` names. The keypair must be
in the project first:

```bash
openstack keypair create --public-key PUBLIC_KEY_FILE fsl-claude
```

## Ports

| Port | | Used by |
|---|---|---|
| 8000 | the console and `/api/`; Kibana at `/kibana/`; the terminals at `/vm-terminal/kali/` and `/vm-terminal/waf/` | a person's browser |
| 8002 | the Website pane of the red and blue consoles: `/site/<session id>/<host>/`. The request goes to that session's WAF from a customers address (from the Kali container through the edge) | the iframe in a person's browser |
| 3080 | `gns3`: GNS3 3.1's API and web UI. It holds the learner maps (below) | the iframe in a person's browser, and `platform/gns3.py` over `mgmt` |
| 5140/udp | `collector`, Filebeat's syslog input | the range host's rsyslog, which forwards each slot's two sensors' alerts and its WAF's audit log |
| 5601 | Kibana itself, on the platform host's loopback only. `/kibana/` on 8000 serves only the sessions' spaces, and inside them only Discover | an operator, through an ssh tunnel |
| 9200 | Elasticsearch | the acceptance tests |

The nginx inside the platform image serves ports 8000 and 8002. Port 8002 is a
separate origin for the target site, so a script planted on the target cannot
read or drive the console. Cookies are scoped by host, not port, so such a
script could still set a cookie that the console would send. The console uses
no cookies. nginx passes `/vm-terminal/` to ttyd processes inside the platform.
They log in over ssh to the range host's `mgmt` address and open the slot's
container with `docker exec`.

**The learner map (port 3080).** Each session's map shows the company network
the learner defends, drawn as a lab topology.

- It names roles, not machines. A host's link end shows its address alone,
  with no interface or prefix. Links to the database and monitoring switches
  carry no label. DMZ gains its network in the caption; 인터넷, DB존 and 관리망
  keep their name alone.
- It shows no management segment, no platform and no machine's own name.
- There is one map per slot for the session's wargame, in Korean.
  GNS3 holds each map open with every node started.
- Each host is a display container of one pinned busybox image, so every link
  end is green. The machines themselves run in the range.
- The full wiring is in `deploy/topology/system/`. Learners never see it.
- The blue console's Map pane (tab Map) frames `/static/web-ui/map.html`. That
  page signs in read-only, turns off the web UI's usage statistics, and shows
  the session's map, fitted to the pane. It is
  view-only: no editing controls, drag pans, the wheel zooms.
- The `gns3` container has `CAP_NET_ADMIN`, `/dev/net/tun`, the Docker socket
  and the host's pid namespace. GNS3 needs them to run its switches and start a
  docker node (`docs/ARCHITECTURE.md`, The topology).

`compose.yaml` publishes every port on `127.0.0.1` unless `CR_PUBLISH` says
otherwise. On the platform VM, 8000, 8002 and 3080 are published on the VM's own
address (`CR_PUBLISH`) and 5140/udp on `0.0.0.0` (`CR_SYSLOG_PUBLISH`). The
platform template's security group opens 8000, 8002 and 3080
(`docs/OPENSTACK.md` §3.5).

The target is not published. The command-line cases and the acceptance tests
reach it from inside the range, as the console does. Inside the range the
targets sit behind the WAF on port 80: `http://board.com` and `http://corp.com`,
two virtual hosts chosen by the `Host` header. Each slot's Kali container gets
those two names, and no others, in `/etc/hosts` from the slot's compose file,
pointing at that slot's WAF.

## Running a session

Open the console (`http://ADDRESS:8000/`) and start a session. A lesson or a
scenario opens the blue console, which has both sides. A wargame (person against
person) opens a red console for the attacker and a blue console for the
defender. The console is in Korean only.

- **Red** is the attacker's console. It has the objectives, "Submit stolen
  hashes", a Kali terminal, and a Website pane pointed at the target. It runs no
  prepared attack. The scripted cases belong to the harness (`redteam/run.py`,
  the acceptance tests) and the scenario engine.
- **Blue** is a sidebar of tools in frames:
  - Kibana, opened on Discover in the session's own data view. The query is
    empty in a lesson and the alert query otherwise;
  - a WAF terminal;
  - a Website pane: a site browser with developer tools laid out like Chrome's
    Network panel;
  - the Map pane (the GNS3 map);
  - an Alerts pane and an IDS rules pane, where a scenario or lesson needs
    them;
  - below a divider, a Kali terminal, shown in lessons and scenarios and hidden
    in a wargame.

  The blue console calls `/api/` for the session, the site's requests, the
  steps and hints of a foundation lesson or worked scenario, a scenario's status
  and triage, ingest, and detections. When the session closes, the session page
  shows the result. It lists the objectives lost first. Then it says in plain
  sentences how many attacks were caught and how many benign requests passed.

A session opened with no guidance (`{"scenario": "board"}`, the home card's
"Start wargame") is a plain wargame with the full defense: CRS paranoia level 1
(PL1). `{"defense": "<name>"}` selects another defense setting that the wargame
declares (`minimal` is PL4). An agent tunes the WAF through
`PUT /api/sessions/<id>/waf/`. `GET` returns what is in the WAF's file.

### Lessons

The home page lists six lessons, called foundations, in two courses. Open one
by its id: `{"lesson": "f1"}` to `f6`. `{"guidance": true}` alone opens F1.

Course 1, "로그 분석 기초" (F1-F3), only reads the range:

- F1: read the attacker's and the web server's addresses, the request path
  from kali, the DMZ network and the log server on the map.
- F2: search with the board's search box and read method, parameter, path and
  status code in the developer tools.
- F3: find that search in Kibana with KQL the learner writes. Read both legs of
  the request, before and after the reverse proxy, and the X-Forwarded-For
  header, then count with `and` and `not`.

Course 2, "공격 탐지 실습" (F4-F6), changes it. The learner attacks from the Kali
pane and the Website pane and defends in the same blue console:

- F4: send an XSS probe (403, the CRS anomaly score), write an IDS rule, bypass
  it with letter case and fix it (defense `xss-gap`).
- F5: run sqlmap on the board's `sort` parameter and read the verdict and the
  rules that caught it.
- F6: use an over-broad WAF exception (defense `overbroad`) to dump the accounts
  undetected, read the doubled penalty, remove the exception and replay the
  attack.

A course's first lesson opens on a briefing: what the course does and the
reference cards it needs (KQL, Kibana fields, the map's addresses, rule forms).
The same cards stay in the 참고 column the rail opens. A Kibana step keeps its
highlight on the query bar until the learner's own query matches.

Every answer is read from the learner's own records or the session's map. There
is no fixed answer key. The learner's own sqlmap run counts in both scores like
any other red action.

The lesson note is a column beside the pane in the blue console. It walks
through the lesson's steps.

- The platform checks each step
  (`POST /api/sessions/<id>/lesson/steps/<step>/check/`) and records whether the
  step was reached, passed or skipped.
- Each lesson opens on its first step's pane. A step's target is highlighted on
  the map, the page, the developer tools, Kibana or a terminal line.
- The session payload has no answer key. A step's command appears only once the
  learner reaches the step, as text to type. No button runs an attack.
- Help for each step comes in order: a nudge, then a hint, then "Skip". "Skip"
  records the step as skipped and moves on. It does nothing for the learner. The
  session records hint use.
- A lesson's last step is done alone, with no highlight or hint.

The benign request that a lesson replays is scored as a benign case. The first
lesson replays it at open; a lesson moved to later replays it when the learner
first passes, skips or takes a hint on one of its steps.

The lessons of a course run back to back in one session. When a lesson's last
step passes, the note names the next lesson of the course. After 2 seconds, or when the learner
presses "Next lesson", it starts that lesson in the same session
(`POST /api/sessions/<id>/lesson/ {"lesson": "f2"}`). A lesson that shows a
"Try it yourself" task after its last step, or whose last pass line is longer
than 30 characters, waits for "Next lesson". That call
applies the lesson's defense in place. The range is not reset
between lessons, and each lesson judges only what happened since it started.
At a course's end the note lists the course's lessons taken, and its button closes the session.

### Scenarios

After the foundations come scenarios (`{"scenario": "1.1"}`). Customers and an
attacker use the board while the learner defends with the real tools.

- A scenario opens on a briefing: situation, goal, how it is measured, and time.
- A status bar at the top shows the time left, the customers blocked and the
  alerted requests in the last minute, and the objectives lost.
- An attack schedule that the learner cannot see fires attacks through the
  normal path. If an attack dumps the board's accounts and they match, it counts
  in the first score.
- "Start final check" (or the schedule) opens a final check of a few minutes.
  The platform judges it by task class:
  - judgement: passes when the learner judges right every alerted item listed
    when the check started. Blocked customers are reported but do not count;
  - availability and unknown: pass when no customer is blocked and every attack
    is held. Scenario 2.3 also needs anomaly thresholds of at most 5/4;
  - detection: passes when every attack draws a corroborated Suricata alert and
    no customer request draws one. An alert is corroborated when it mentions the
    attack's mechanism.

The scenarios:

- `1.1` "Telling customer requests from attacks": the learner judges each
  request that drew an alert. Is it a customer or an attack, and did it get the
  data (`/api/sessions/<id>/triage/`)?
- `1.2` and `1.3`: judge alerts when an inherited exception lets sqlmap take the
  accounts. Scenario 1.3 also judges the kind of each attack.
- `2.1` "Fixing false positives on Korean search": the learner makes a PL3 WAF
  serve the customers it refuses, without letting sqlmap through.
- `2.2`: serve the customers that PL2 blocks. `2.3`: serve the customers at PL3
  while lowering the anomaly thresholds to 5/4.
- `3.1` to `3.4`: make the IDS alert on the sort attack, its tamper variant and
  the comment XSS, in an IDS rules pane. These count in the second score only.
- `4.1`: handle an unseen sqlmap variant and new false positives with no help.

A hint is offered when the learner is stuck, and recorded only when opened. The
debrief adds the customers blocked and the attack timeline. Detail:
`docs/ARCHITECTURE.md`, "Scenarios".

### Firing cases from the command line

You can fire the scripted cases from the command line, as the acceptance tests
do. The target is not published, so the harness runs inside the range, from the
platform:

```bash
sudo docker exec cr-platform python redteam/run.py --tool-target http://board.com
```

The harness opens a session for the scenario whose `case_file` matches the
basename of `--cases` (`board.yaml` opens board, `corp.yaml` opens corp, anything
else opens board). It fires each case through the platform at `--platform`
(default `http://localhost:8000`). `--tool-target` (default `http://board.com`)
is the address the tool containers use for the target. For corp, add
`--cases redteam/cases/corp.yaml`.

## Checking it

```bash
bin/verify --changed  # only the unit tests the change reaches, and the ratchet
bin/verify --fast     # unit and API tests and the metrics, no stack needed
bin/verify            # also the acceptance tests in test/, against the live stack
```

The range runs only on OpenStack, so a laptop runs `--changed` and `--fast`
and nothing more. The acceptance tests need the platform VM.

`--changed` compares against the merge-base with `dev` (or a commit, or `A..B`)
and prints which tests each changed file reaches and why. `bin/select-tests`
prints that without running anything. With `--live`, `--changed` also runs the
acceptance modules the change reaches (`bin/acceptance --only`).

The full run restarts the platform and resets the target, the rules and the
attacker's origin. Do not run it against a stack someone is using. It deletes
only the sessions it created.

`bin/acceptance` runs the acceptance step. It starts:

- one pytest process for each session the range can hold at once
  (`max_sessions` in `GET /api/range/ready/`);
- one more for the checks that read only Elasticsearch;
- one for the modules that need the whole range (`test_concurrent_sessions`,
  `test_lesson`).

`bin/acceptance --plan` prints the split, and `test/README.md` explains it. The
platform VM does not listen on localhost, so run it on the VM with
`CR_PLATFORM_URL=http://<address>:8000 bin/verify`. Every acceptance test runs
on OpenStack. One skips by design: `test_lesson.py`'s F1 map test runs once per
course and skips for a course that does not start with F1 (`c2` starts with F4),
so a full run reports one skip.

`bin/prune` deletes sessions by hand. Without `--apply` it is a dry run:

```bash
bin/prune --keep 20 --apply      # keep the newest 20
bin/prune --ids FILE --apply     # only the closed sessions FILE lists
```

After you add a Tailwind class to a template, run `bin/build-css`. The
generated stylesheet is committed, and no test checks that it is current.

## Backup and restore

The platform's database holds sessions, cases, detections, objectives, rule sets
and disabled rules. It is one SQLite file, `/data/db.sqlite3`, on the
`cr_platformdata` volume of the platform VM. Nothing else is backed up: not
Elasticsearch's `cr_esdata` volume, and not the collector's registry in
`cr_collectordata`. These volumes go with the VM when `bin/cloud down` deletes
it. `down` first backs up the database and keeps the copy in `backups/`.

```bash
CR_PLATFORM_EXEC="ssh -i ~/.ssh/fsl_claude ubuntu@ADDRESS sudo docker exec -i cr-platform python -" \
  bin/backup      # writes backups/db-<UTC time>.sqlite3 while the platform serves
```

`CR_PLATFORM_EXEC` is the command that runs `python -` in the platform's
environment. `bin/backup`:

1. writes a compacted copy with SQLite's `VACUUM INTO` into a temporary file
   beside the platform. The space of deleted sessions is not copied;
2. streams the file back in 1 MiB chunks. A database of gigabytes takes minutes
   over ssh. It gives up only after 600 s with no data;
3. checks the copy with `PRAGMA integrity_check`;
4. keeps nothing if any step fails.

After the new copy passes, `bin/backup` removes older `db-<UTC time>.sqlite3`
files beyond `--keep` (default 1, the new one included). It leaves files with
other names. `bin/platform-rebuild` does this backup and the restore for you.

To restore by hand, copy the file to the VM. Then, on the VM, with the platform
stopped:

```bash
ssh -i ~/.ssh/fsl_claude ubuntu@ADDRESS mkdir -p /opt/cr/backups
scp -i ~/.ssh/fsl_claude backups/db-20260925T020000Z.sqlite3 ubuntu@ADDRESS:/opt/cr/backups/
ssh -i ~/.ssh/fsl_claude ubuntu@ADDRESS
cd /opt/cr
sudo docker compose stop platform
sudo docker run --rm --network none --entrypoint sh --user cr \
  -v cr_platformdata:/data -v "$PWD/backups:/backups:ro" "$(sudo docker inspect --format '{{.Config.Image}}' cr-platform)" \
  -c 'rm -f /data/db.sqlite3-journal && cp /backups/db-20260925T020000Z.sqlite3 /data/db.sqlite3'
sudo docker compose start platform
```

`--entrypoint sh` replaces the image's entrypoint, which ignores its arguments.
`--user cr` leaves the copy owned by the platform's user. `docker cp` would
leave it owned by root, and the platform could not write it. You must remove the
old `-journal` file, or SQLite replays it onto the restored file. When the
platform starts, it applies newer migrations. `bin/platform-rebuild` runs these
same steps.

## Security limits (lab use only)

- Elasticsearch runs without security.
- Django runs with `DEBUG` off and a secret key generated once into the
  platform's data volume. It answers only to `localhost`, `127.0.0.1` and
  `[::1]`, unless `DJANGO_ALLOWED_HOSTS` names more. The platform VM adds its
  floating IP.
- The Docker socket is mounted into the platform, which gives a way out of the
  container.
- The terminals under `/vm-terminal/` need no login of their own. They give a
  root shell in the slot's Kali container and in its WAF container. Both drop
  every capability except a listed few and run with `no-new-privileges`, and
  Docker's user namespace remap makes container root an unprivileged user on
  the range host. Every slot shares the range host's kernel
  (`docs/THREAT-MODEL.md`).

The same holds on the platform VM. There the project's password is also in
plain text in `/opt/cr/openstack.env` and in the platform container's
environment. The VM's ssh, 8000, 8002 and 3080 are open to any address, and
8000 asks for no login.
