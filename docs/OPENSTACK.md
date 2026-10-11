# OpenStack

What this project needs from an OpenStack cloud, and how to set it up from
nothing: the cloud (Kolla-Ansible 2026.1 or later), the project, the platform
VM, the range, and the checks. Written for an operator rebuilding the cloud
side or onboarding a new cloud.

Facts marked **(this cloud)** come from the running cloud on
`master@192.168.0.100` as recorded in `docs/STATE.md` and `docs/DECISIONS.md`;
the cloud was not reachable when this file was written (2026-10-11), so they
were not re-read live. Everything else is from this repo's code or the primary
sources listed at the end.

## Target: one-click build

The end state: one command builds the whole environment from prebuilt
artifacts, with nothing compiled or installed by hand on the cloud.

1. Heat creates the platform VM (`deploy/openstack/platform.yaml`); its first
   boot pulls the platform and session images from GHCR instead of building
   them.
2. The script hands the VM the password and the range ssh key over ssh.
3. The platform builds the range through its own API: fabric, then golden
   images imported into Glance from prebuilt qcow2 files (GitHub Release
   assets, Glance `web-download`), then the slot, then `configure/`.

| Piece | Status | Where |
|---|---|---|
| Kolla-Ansible cloud with Heat, Glance, Nova, Neutron (ML2/OVS) | done (this cloud) | §2 |
| Project `fsl-range`, member user, quotas, flavors | done by hand, admin only | §3 |
| Platform images on GHCR (`.github/workflows/images.yml`) | in progress | §4 |
| Heat stack pulls images instead of `--build` | in progress | §4 |
| `bin/platform-rebuild`: lossless replace (store + range key carried over) | in progress | §4 |
| Fabric via `POST /api/range/fabric/` | done | §5 |
| Golden images built on the cloud via `POST /api/range/images/` | done | §5 |
| Golden images imported from GitHub Release qcow2 (`web-download`) | in progress (being designed) | §5 |
| `fsl-pfsense` / `fsl-pfsense-edge` image | pending: licence/redistribution of a built pfSense image unverified; install not automated | §3.6 |
| Slot + configure via `/api/range/slot/`, `/api/range/configure/` | done | §5 |
| Acceptance on substrate openstack | deferred (23 passed / 17 failed / 21 errors) | §6 |

Steps below carry **[one-click]** where the script is meant to replace them,
and **[admin, once]** where they stay manual because a member cannot do them.

## 1. What this project needs from OpenStack

The platform runs on one of two substrates (`FSL_SUBSTRATE`):

- `range.docker.Docker` — the whole range as compose stacks on one Docker
  host. Needs only a VM with Docker; OpenStack is just where the VM lives.
  This is the MVP path (OpenStack range is out of the MVP per the 2026-10-08
  spec; `docs/STATE.md` backlog 0).
- `range.openstack.connect` — the range as Nova servers on Neutron networks
  the platform creates as a member user. The platform VM runs only the control
  plane (platform, Elasticsearch, Kibana, collector).

pfSense CE is FreeBSD and runs only as a VM, so the pfSense edge (firewall +
Suricata package) exists only on substrate openstack. On docker the sensor is a
Suricata container.

APIs the platform calls (`platform/range/openstack.py`): Keystone v3 (password
auth, domain `default`), Nova (servers, keypairs, flavors, `os-interface`,
rebuild, `os-getVNCConsole`, console log), Neutron (networks with tags,
subnets, ports with fixed IPs and `allowed_address_pairs`, security groups),
Glance v2 (images). The operator also uses Heat for the platform VM. No Cinder,
Octavia or Designate.

## 2. Cloud prerequisites (Kolla-Ansible 2026.1+)

**(this cloud)** kolla-ansible 2026.1 (Gazpacho, 22.x; host had
22.2.1.dev9), all-in-one inventory `/root/all-in-one`, Ubuntu images,
ML2/Open vSwitch, API endpoints on `192.168.0.110`, no Cinder.

### 2.1 Install and deploy [admin, once]

From the 2026.1 quickstart [K1]:

```bash
python3 -m venv /opt/kolla-venv && . /opt/kolla-venv/bin/activate
pip install -U pip
pip install git+https://opendev.org/openstack/kolla-ansible@stable/2026.1
sudo mkdir -p /etc/kolla && sudo chown $USER:$USER /etc/kolla
cp -r /opt/kolla-venv/share/kolla-ansible/etc_examples/kolla/* /etc/kolla
cp /opt/kolla-venv/share/kolla-ansible/ansible/inventory/all-in-one .
kolla-ansible install-deps
kolla-genpwd
# edit /etc/kolla/globals.yml (below)
kolla-ansible bootstrap-servers -i ./all-in-one
kolla-ansible prechecks -i ./all-in-one
kolla-ansible deploy -i ./all-in-one
pip install python-openstackclient python-heatclient -c https://releases.openstack.org/constraints/upper/2026.1
kolla-ansible post-deploy        # writes /etc/kolla/clouds.yaml
```

The kolla venv on this cloud has no Heat client; drive Heat from a separate
venv with `python-openstackclient` and `python-heatclient` **(this cloud)**.

### 2.2 globals.yml

```yaml
kolla_base_distro: "ubuntu"
openstack_release: "2026.1"
network_interface: "<mgmt NIC>"
neutron_external_interface: "<NIC with no IP, for provider/floating IPs>"
kolla_internal_vip_address: "192.168.0.110"   # this cloud's API address
neutron_plugin_agent: "openvswitch"           # the default [K2]
enable_heat: "yes"        # default follows enable_openstack_core [K2]; keep it on
enable_horizon: "yes"     # optional; noVNC console URLs come from Nova either way
#enable_cinder: false     # default [K2]; the project works without volumes
```

Heat, Glance, Nova, Neutron, Keystone, Placement are all in
`enable_openstack_core` (default true) [K2]. Nothing else is required.

### 2.3 Tap-as-a-Service (optional; dropped from the design)

TaaS was enabled on this cloud on 2026-09-30 for an organiser-owned sensor;
that sensor was then dropped (`docs/STATE.md`, "Tap-as-a-Service is dropped
from the design"). It stays enabled here, off every path. A new cloud does not
need it. If you enable it on 2026.1:

```yaml
enable_neutron_taas: "yes"     # defined in ansible/group_vars/all/neutron.yml, default false [K3]
```

```bash
cp /etc/kolla/globals.yml /etc/kolla/globals.yml.before-taas
kolla-ansible reconfigure -i /root/all-in-one -t neutron
```

**The 2026.1 bug.** kolla-ansible adds `taas` to `service_plugins` for all
three Neutron API services, but its config task writes `neutron_taas.conf`
only for services in `services_need_neutron_taas_conf` — `neutron-server` and
`neutron-openvswitch-agent` [K4]. `neutron_rpc_server` and
`neutron_periodic_worker` then exit with `No providers specified for 'TAAS'`
and every agent reads dead. The fix uses kolla's per-service override, which
the same task merges from `{{ node_custom_config }}/neutron/{{ item.key }}.conf`
[K4][K5]:

```bash
c=/etc/kolla/neutron-server/neutron_taas.conf
mkdir -p /etc/kolla/config/neutron
cp $c /etc/kolla/config/neutron/neutron-rpc-server.conf
cp $c /etc/kolla/config/neutron/neutron-periodic-worker.conf
kolla-ansible reconfigure -i /root/all-in-one -t neutron
openstack network agent list          # every agent Alive :-)
docker ps --filter name=neutron       # rpc_server and periodic_worker Up
```

A later reconfigure keeps the override files **(this cloud)**. Checked as a
member: a tap service plus a `BOTH` tap flow goes ACTIVE and `br-tap` exists.
Whether this is fixed upstream after 2026.1 was not checked.

### 2.4 Nova: resize is off

`allow_resize_to_same_host` defaults to `False` [N1], and on an all-in-one
cloud there is no other host, so a resize cannot be scheduled. It is not set
on this cloud. Changing a server's flavor therefore means **replacing** it.
Heat's `OS::Nova::Server` applies a flavor change by resize unless
`flavor_update_policy: REPLACE` [H1]; on this cloud use a stack replace
(delete + create, as `bin/platform-rebuild` does) rather than a flavor update.
To allow resize instead: `[DEFAULT] allow_resize_to_same_host = True` in
`/etc/kolla/config/nova.conf`, then `kolla-ansible reconfigure -t nova` [K5][N1].

## 3. Project, user, quotas, flavors, keys, groups, images

### 3.1 Project and user [admin, once]

```bash
openstack project create fsl-range
openstack user create --project fsl-range --password-prompt fsl-range
openstack role add --project fsl-range --user fsl-range member
```

**(this cloud)** project id `64ffc2a247464ebdae21cfdae0f96d90`; password only
in `/root/fsl-range.password`; `/root/fsl-range-openrc.sh` sources it. The
platform signs in as this member, never admin; the user's domain is `default`.

### 3.2 Quotas [admin, once]

**(this cloud)** cores quota is 20 and currently full (platform VM, the
temporary `fsl-acceptance` VM, the slot). Budget: platform VM + 4 slot VMs
(`fsl-pfsense`, `fsl-kali`, `fsl-waf`, `fsl-wg-board`) + up to 3 image
builders at once during `POST /api/range/images/`. Also 1 network for the
stack + 3 for the range, 1 + 32 subnets, 1 router, 1 floating IP.

```bash
openstack quota show fsl-range
openstack quota set --cores 24 --ram 65536 --instances 12 fsl-range   # example
```

### 3.3 Flavors [admin, once]

A member cannot create flavors. Needed:

| Flavor | Use | Notes |
|---|---|---|
| ≥ 8 GB RAM, 2+ vCPU | platform VM | 4 GB (`m1.windows`, 2 vCPU/4 GB/60 GB) OOM-killed Elasticsearch once sessions stacked up (DECISIONS 2026-10-10); one session stack holds about 1.5 GB |
| `m1.small` | slot VMs and image builders (`FSL_OPENSTACK_FLAVOR`, default `m1.small`) | golden images have min disk 20 GB, so the flavor's disk must be ≥ 20 |

**(this cloud)** `m1.platform8` (8 GB / 2 vCPU) exists and runs
`fsl-acceptance`. The in-progress template change defaults the stack to
`m1.large`; check that the flavor exists and is ≥ 8 GB on the cloud you use,
or pass `--flavor`.

```bash
openstack flavor create --ram 8192 --vcpus 2 --disk 60 m1.platform8
```

### 3.4 Keypairs

- `fsl-claude` — the operator's key the platform VM boots with (stack
  parameter `key_name`). Create it as `fsl-range` before the stack:
  `openstack keypair create --public-key ~/.ssh/fsl_claude.pub fsl-claude`
- `fsl-platform` — the platform's own range key, imported by
  `POST /api/range/fabric/` from `/data/ssh/id_ed25519` in the platform
  container. Never create it by hand. See §5.3 on drift.

### 3.5 Security groups

| Group | Made by | Rules |
|---|---|---|
| `fsl-platform` | Heat stack | tcp 22, tcp 8000, icmp in |
| `fsl-range` | fabric | all IPv4 in; on every range port (anti-spoofing stays on) |
| `fsl-reach` | fabric | nothing in, then udp 5140 from exactly the edge and the WAF (`configure/`) |

8002 (the blue console's site browser) is served only on substrate docker
(`SITE_PORT` is `None` on openstack). The README says the acceptance VM's
group opens 8002; the template's `fsl-platform` group does not, and whether
8002 is open on `192.168.0.210` was not checked live. On a docker-substrate
VM open it:

```bash
openstack security group rule create --protocol tcp --dst-port 8002 fsl-platform
```

### 3.6 Images

| Image | How it gets there | One-click |
|---|---|---|
| `ubuntu-24.04` | Ubuntu cloud image, uploaded once | yes, `web-download` |
| `kali-rolling` | Kali cloud image, base for `fsl-kali` | yes, `web-download` |
| `fsl-waf`, `fsl-wg-board`, `fsl-kali` | golden images, built by the platform (§5) | target: imported from Release qcow2 |
| `fsl-pfsense` | pfSense CE 2.9.0 installed by hand (below) | pending |
| `fsl-pfsense-edge` | `fsl-pfsense` + Suricata 8.0.5 package + sshd + MTU 1450 + OPT1 mgmt NIC, made by hand; the steps are not in the repo | pending |

Base images by URL, Glance pulls it (interoperable import, `web-download`,
enabled by default) [G1][G2] **[one-click]**:

```bash
openstack image create --disk-format qcow2 --container-format bare ubuntu-24.04
openstack image import --method web-download \
  --uri https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img ubuntu-24.04
```

The same two commands are the target for the golden images, with the URI of a
GitHub Release asset; set `--property fsl_bundle=<digest>` and `--min-disk 20`
so `POST /api/range/images/` reads them as current (it matches the
`fsl_bundle` property to the bundle digest, `platform/range/images.py`).

**pfSense licence (researched 2026-10-11, not legal advice).** The $0
Netgate Store order is pfSense CE, whose source is Apache 2.0
(pfsense/pfsense `LICENSE`); FreeBSD is BSD and the Suricata engine GPLv2.
Keeping a built image and redeploying it on our own cloud is allowed.
Publishing it is allowed by copyright but not under the pfSense name: the
trademark policy (pfsense.org/trademarks.html) lets the name travel only with
"bit-for-bit identical copies of official pfSense releases", and Netgate's
docs (docs.netgate.com/pfsense/en/latest/general/can-i-sell-pfsense.html) say
"ONLY an UNMODIFIED version of pfSense software can still be called 'pfSense
software'". So the project publishes the install automation (official
installer + our `config.xml`, restorable from a FAT partition per
docs.netgate.com/pfsense/en/latest/backup/restore-during-install.html), never
the image. Unclear: whether the Netgate EULA covers installer-produced
binaries; ask legal@netgate.com before any publication.

**pfSense (manual, pending automation).** pfSense CE has no cloud image and no
scripted install; its only installer is Netgate's online one
(`netgate-installer-v1.2-RELEASE-amd64.iso`, from a $0 Netgate Store
checkout). With no Cinder, the install goes onto a server's root disk through
Nova stable rescue, which boots the ISO as a CD-ROM with the disk still
attached [N2]. As `fsl-range`, following README "The pfSense image":

```bash
openstack image create netgate-installer --file netgate-installer.iso --disk-format iso --container-format bare --private --property hw_rescue_device=cdrom --property hw_rescue_bus=scsi --property hw_scsi_model=virtio-scsi
openstack network create fsl-pfsense-build-lan
openstack subnet create --network fsl-pfsense-build-lan --subnet-range 192.168.1.0/24 --no-dhcp --gateway none fsl-pfsense-build-lan
openstack server create --image cirros-0.6.3 --flavor m1.small --network fsl-platform --network fsl-pfsense-build-lan --wait fsl-pfsense-build
openstack server rescue --image netgate-installer fsl-pfsense-build
openstack console url show --novnc fsl-pfsense-build
# noVNC: Install CE, WAN vtnet0 DHCP, LAN vtnet1 default, ZFS/GPT on vtbd0, then Halt
openstack server unrescue fsl-pfsense-build
openstack server image create --name fsl-pfsense --wait fsl-pfsense-build
openstack image set --property hw_vif_model=virtio --property hw_disk_bus=virtio --property os_distro=freebsd fsl-pfsense
openstack server delete fsl-pfsense-build && openstack network delete fsl-pfsense-build-lan
```

pfSense writes only to the video console; use noVNC, not `console log show`.
Its WAN MTU must be 1450 (the tenant network's). Its web GUI is not exposed;
reach it with an ssh tunnel through the platform's `mgmt` address (the edge's
`mgmt` port, `10.31.0.158` here). Whether a built pfSense image may be
redistributed as a Release asset is unverified, so it is not in the one-click
path yet.

## 4. The platform VM

### 4.1 The Heat stack

`deploy/openstack/platform.yaml` creates network `fsl-platform`
(`10.20.0.0/24`), a router to `provider`, group `fsl-platform`, a port, a
floating IP (**(this cloud)** `192.168.0.210`) and an Ubuntu 24.04 server
whose cloud-init installs Docker, sets Docker's MTU to the network's (1450
here), adds 4 GB swap, clones `repository` at `ref` into `/opt/fsl`, writes
`/opt/fsl/openstack.env` (every `FSL_OPENSTACK_*` but the password) and
`/opt/fsl/.env` (`FSL_PUBLISH=<fixed IP>`, `FSL_SYSLOG_PUBLISH=0.0.0.0`),
and enables `fsl-platform.service`.

| Parameter | Default | |
|---|---|---|
| `keystone` | (required) | Keystone base URL without `/v3`, e.g. `http://192.168.0.110:5000` |
| `user` | `fsl-range` | |
| `image` | `ubuntu-24.04` | |
| `flavor` | `m1.windows` on dev; `m1.large` in the in-progress change | must be ≥ 8 GB (§3.3) |
| `key_name` | `fsl-claude` | |
| `external_network` | `provider` | |
| `cidr` | `10.20.0.0/24` | must not overlap compose subnets or `172.17.0.0/16` |
| `dns` | `8.8.8.8,8.8.4.4` | |
| `repository`, `ref` | this repo, `dev` | only pushed commits are cloned |

`FSL_PUBLISH` is the VM's fixed IP, so 8000 listens on that address, not
loopback; the floating IP NATs to it. `FSL_PUBLISH=0.0.0.0` on a VM is an
environment error recorded in DECISIONS 2026-10-10.

The password stays out of Heat and user data: Nova's metadata service answers
from inside containers on the VM, so anything in user data is readable there.

### 4.2 Create (today, manual)

As `fsl-range` (`. fsl-range-openrc.sh`):

```bash
openstack stack create --wait -t deploy/openstack/platform.yaml \
  --parameter keystone=http://192.168.0.110:5000 --parameter flavor=m1.platform8 fsl-platform
ADDRESS=$(openstack stack output show fsl-platform address -f value -c output_value)
{ printf 'FSL_OPENSTACK_PASSWORD='; cat PASSWORD_FILE; echo; } | ssh ubuntu@$ADDRESS \
  'cloud-init status --wait >/dev/null && cat >> /opt/fsl/openstack.env && sudo docker compose -f /opt/fsl/compose.yaml up -d platform'
ssh ubuntu@$ADDRESS systemctl status fsl-platform
```

On substrate openstack also set in `/opt/fsl/openstack.env`:
`FSL_TOOL_IMAGE=fsl-kali` (the launcher requires the attacker role's name;
DECISIONS 2026-10-09) and `FSL_SENSOR_RELOAD` for the pfSense sensor (unset
today, a known acceptance failure, §6). Run `bin/fetch-geoip` on the VM once
(the in-progress template does it at first boot).

### 4.3 Rebuild and delete — target: lossless [one-click]

Today a new VM builds every image (`up -d --build`), starts with an empty
store, and makes a new range ssh key, so the range must be torn down first
(§5.3). The in-progress change (not yet on `dev`):

- `.github/workflows/images.yml` pushes `ghcr.io/nekonic/fsl-{platform,board,corp,corp-db,kali,proxy}` tagged by commit on every push to `dev`.
- The template pulls them (`compose pull`, then `up -d` without `--build`)
  with `FSL_IMAGE_TAG` set to the cloned commit, and runs `bin/fetch-geoip`.
- `bin/platform-rebuild` refuses unless every image for the commit is
  public on GHCR, keeps the range key (`~/.ssh/fsl-platform`, taken once from
  the running platform), backs up the store with `bin/backup`, deletes and
  recreates the stack, appends the password, writes the kept key to
  `/data/ssh/id_ed25519`, restores the store, and waits for `/api/sessions/`.

```bash
. fsl-range-openrc.sh
bin/platform-rebuild --keystone http://192.168.0.110:5000 \
  --password-file PASSWORD_FILE --flavor m1.platform8 --ref dev
```

With the key carried over, the fabric's `fsl-platform` keypair stays valid and
the slot need not be torn down. Pending until the change lands and is run
against the cloud. Delete without replacing:

```bash
curl -s -X DELETE http://$ADDRESS:8000/api/range/slot/
curl -s -X DELETE http://$ADDRESS:8000/api/range/fabric/
openstack stack delete --yes --wait fsl-platform
```

## 5. The range (substrate openstack)

Everything is through the platform's API, as `fsl-range`. Each `GET` reads the
plan (missing, present, drifted, left over); `POST` converges; `DELETE` tears
down. All of it is **[one-click]**.

```bash
P=http://$ADDRESS:8000/api/range
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/fabric/     # fsl-internet (30 origin /24s, DHCP off), fsl-estate 10.30.0.0/24,
                                  # fsl-mgmt 10.31.0.0/24 (no gateway), keypair fsl-platform,
                                  # groups fsl-range/fsl-reach, platform port fsl-platform.mgmt
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/images/     # repeat until "clean": true (~7 min; builders on FSL_OPENSTACK_BUILD_NETWORK)
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/slot/       # boots fsl-pfsense, fsl-kali, fsl-waf, fsl-wg-board
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/configure/  # pfSense WAN/30 gateways, Suricata, syslog; WAF log forwarding
curl -s $P/ready/
```

Notes:

- Networks are found by tag `fsl.segment.id=<segment>`, not name; the fabric
  needs the Neutron `standard-attr-tag` extension (on by default).
- Image builds need `FSL_OPENSTACK_BUILD_NETWORK` (the template writes the
  stack's network, which has a router) and `ubuntu-24.04` present exactly once.
  Nova user data is capped at 65535 bytes base64 per image bundle.
- The edge's Internet port holds every origin's `.1` and has
  `allowed_address_pairs 0.0.0.0/0`; Kali's holds ~100 origin addresses.
  cloud-init applies only a port's first address, hence the slot's `bootcmd`.
- A guest needs a config drive; without one it gets no metadata.
- Nova here answers 404 for the console of a powered-off guest.

### 5.1 Session reset

`POST $P/slot/rebuild/` Nova-rebuilds every slot VM from its golden image,
keeping ports and addresses; closing a session calls it. It wipes the pushed
config, so run `configure/` again.

### 5.2 Teardown order

Slot, then fabric. `DELETE $P/fabric/` refuses while any server other than the
platform has a port on a range network. Images stay; `DELETE $P/images/`
removes only failed builders and images of older bundles.

### 5.3 Keypair drift

The fabric compares keypair `fsl-platform` with the platform's
`/data/ssh/id_ed25519`. A new VM without the kept key makes a new one, and
`GET fabric/` reports `keypair fsl-platform holds another public key` (drift,
409 on POST). Today: tear down slot → fabric before replacing the VM. With
`bin/platform-rebuild` the key is carried over and nothing drifts.

## 6. Verification

```bash
curl -s http://$ADDRESS:8000/api/range/ready/          # the slot's readiness
curl -s http://$ADDRESS:8000/api/range/fabric/ | jq .clean
ssh ubuntu@$ADDRESS 'cd /opt/fsl && FSL_PLATFORM_URL=http://'$ADDRESS':8000 bin/verify'
```

`bin/verify` restarts the platform and resets the range; never run it against
a stack someone is using.

**Acceptance on substrate openstack: deferred** (OpenStack range is out of
the MVP). Last run 2026-10-09: 23 passed, 78 skipped, 17 failed, 21 errors.
Causes (`docs/STATE.md` backlog 0):

- session fixtures hold a session open while others POST a new one, and the
  single-slot range answers 409;
- `/api/rules/apply/` runs the compose reload (`suricatasc`) against the
  pfSense sensor because `FSL_SENSOR_RELOAD` is unset on the VM;
- the VM had no GeoLite2 database (`bin/fetch-geoip` never ran).

The MVP gate ran on substrate docker on `fsl-acceptance` (192.168.0.220,
`m1.platform8`): 146 passed, 0 failed (2026-10-10). That VM is temporary and
is to be deleted once no longer needed; it holds cores the quota needs.

## 7. Known issues

- MTU 1450 (§4.1, §3.6), no resize (§2.4), TaaS override (§2.3), no Cinder
  (§3.6), keypair drift (§5.3), full core quota (§3.2).
- A member cannot create flavors or change quotas; the stack uses no
  admin-only Heat resource.
- `ref` defaults to `dev`: the VM only sees pushed commits.
- The project password is plain text in `/opt/fsl/openstack.env` and the
  platform container's environment.
- The platform reaches Kali over `mgmt`: origin addresses collide with the
  platform's docker edge bridges.

## Sources

- [K1] Kolla-Ansible 2026.1 quickstart — https://docs.openstack.org/kolla-ansible/2026.1/user/quickstart.html
- [K2] kolla-ansible stable/2026.1 `etc/kolla/globals.yml` — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2026.1/etc/kolla/globals.yml
- [K3] kolla-ansible stable/2026.1 `ansible/group_vars/all/neutron.yml` (`enable_neutron_taas: false`); TaaS added in 18.0.0 — https://docs.openstack.org/releasenotes/kolla-ansible/2024.1.html
- [K4] kolla-ansible stable/2026.1 `ansible/roles/neutron/tasks/config.yml` — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2026.1/ansible/roles/neutron/tasks/config.yml
- [K5] Kolla-Ansible, OpenStack service configuration overrides — https://docs.openstack.org/kolla-ansible/latest/admin/advanced-configuration.html
- [N1] Nova configuration, `allow_resize_to_same_host` (default False) — https://docs.openstack.org/nova/latest/configuration/config.html
- [N2] Nova, rescue (stable device rescue, `hw_rescue_device`/`hw_rescue_bus`) — https://docs.openstack.org/nova/latest/user/rescue.html
- [H1] Heat `OS::Nova::Server` (`flavor_update_policy` RESIZE|REPLACE, default RESIZE; `user_data_update_policy` default REPLACE) — https://opendev.org/openstack/heat/src/branch/master/heat/engine/resources/openstack/nova/server.py
- [G1] Glance interoperable image import (`web-download`) — https://docs.openstack.org/glance/latest/admin/interoperable-image-import.html
- [G2] OpenStackClient `image create` / `image import --method web-download --uri` — https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/image-v2.html
