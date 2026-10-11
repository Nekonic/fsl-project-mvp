# OpenStack

What this project needs from an OpenStack cloud, and how to set it up from
nothing: the cloud (Kolla-Ansible 2026.1 or later), the project, the one base
image, `cloud.yaml`, the platform VM, the range, and the checks. Written for
an operator rebuilding the cloud side or onboarding a new cloud.

Facts marked **(this cloud)** come from the running cloud on
`master@192.168.0.100` as recorded in `docs/STATE.md` and `docs/DECISIONS.md`;
the cloud was not reachable when this file was written (2026-10-11), so they
were not re-read live. Everything else is from this repo's code or the primary
sources listed at the end.

## Target: one-click build

The end state: one command builds the whole environment, with nothing
compiled or installed by hand on the cloud and exactly one image uploaded by
hand, the stock Ubuntu 24.04 cloud image.

1. `bin/cloud up` reads `deploy/openstack/cloud.yaml` (§4) and has Heat create
   the platform VM (`deploy/openstack/platform.yaml`); its first boot pulls the
   platform and session images from GHCR instead of building them.
2. It hands the VM the password and the range ssh key over ssh.
3. It drives the platform's own range API: fabric, golden images (each built
   on a builder booted from the stock Ubuntu image; the OPNsense edge image
   downloaded from the official release by such a builder and uploaded to
   Glance), then the slot, then `configure/`, until `ready/` says ready.

| Piece | Status | Where |
|---|---|---|
| Kolla-Ansible cloud with Heat, Glance, Nova, Neutron (ML2/OVS) | done (this cloud) | §2 |
| Project `fsl-range`, member user, quotas, flavors | done by hand, admin only | §3 |
| One base image, stock Ubuntu 24.04, checksum-verified upload | by hand, once per cloud | §3.6 |
| `cloud.yaml`: every cloud-specific value, validated | built | §4 |
| Platform images on GHCR (`.github/workflows/images.yml`) | built | §5 |
| Heat stack pulls images instead of `--build` | built | §5 |
| `bin/platform-rebuild`: lossless replace (store + range key carried over), driven by `cloud.yaml` | built, not run | §5 |
| `bin/cloud up|down` | built, not run | §5 |
| Fabric via `POST /api/range/fabric/` | done | §6 |
| Golden images built on the cloud via `POST /api/range/images/` | done | §6 |
| `fsl-kali` built on Ubuntu (no second base image) | built, not run | §6 |
| `fsl-opnsense-<version>` built by an Ubuntu builder from the official nano image | built, not run | §3.6 |
| OPNsense edge configured over mgmt ssh (`configure/`) | built, not run | §6 |
| Slot + configure via `/api/range/slot/`, `/api/range/configure/` | done (with pfSense) | §6 |
| Acceptance on substrate openstack | deferred (23 passed / 17 failed / 21 errors, with pfSense) | §7 |

Steps below carry **[one-click]** where the script replaces them, and
**[admin, once]** where they stay manual because a member cannot do them.

## 1. What this project needs from OpenStack

The platform runs on one of two substrates (`FSL_SUBSTRATE`):

- `range.docker.Docker` — the whole range as compose stacks on one Docker
  host. Needs only a VM with Docker; OpenStack is just where the VM lives.
  This is the MVP path (OpenStack range is out of the MVP per the 2026-10-08
  spec; `docs/STATE.md` backlog 0).
- `range.openstack.connect` — the range as Nova servers on Neutron networks
  the platform creates as a member user. The platform VM runs only the control
  plane (platform, Elasticsearch, Kibana, collector).

The edge (firewall + Suricata) is an OPNsense VM and exists only on substrate
openstack. On docker the sensor is a Suricata container.

APIs the platform calls (`platform/range/openstack.py`): Keystone v3 (password
auth in the configured domain), Nova (servers, keypairs, flavors,
`os-interface`, rebuild, `os-getVNCConsole`, console log), Neutron (networks
with tags, subnets, ports with fixed IPs and `allowed_address_pairs`, security
groups), Glance v2 (images: list, create a record, delete; the edge's builder
uploads the image data with `PUT /v2/images/{id}/file`). The operator also
uses Heat for the platform VM. No Cinder, Octavia or Designate.

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
(`fsl-edge`, `fsl-kali`, `fsl-waf`, `fsl-wg-board`) + up to 4 image
builders at once during `POST /api/range/images/` (one per built host). Also
1 network for the stack + 3 for the range, 1 + 32 subnets, 1 router, 1
floating IP, and image storage for 4 golden images.

```bash
openstack quota show fsl-range
openstack quota set --cores 24 --ram 65536 --instances 12 fsl-range   # example
```

### 3.3 Flavors [admin, once]

A member cannot create flavors. `compute.flavors` in `cloud.yaml` names them:

| Key | Use | Notes |
|---|---|---|
| `platform` | platform VM | 8 GB RAM or more; 4 GB OOM-killed Elasticsearch once sessions stacked up (DECISIONS 2026-10-10). Example `m1.large` (8 GB / 4 vCPU / 80 GB) |
| `builder` | image builders | the OPNsense builder holds the 3 GB raw image, its qcow2 and a 2 GB QEMU guest: 4 GB RAM and 20 GB disk or more (`m1.medium`) |
| `range` | every slot VM no role names | 20 GB disk or more: a golden image's min disk is its builder's disk |
| `edge` (required), or any other role name | the host filling that role | the edge is required: OPNsense wants 3 GB RAM or more (its image says `min_ram` 3072), so the `range` flavor would fail at boot |

**(this cloud)** `m1.platform8` (8 GB / 2 vCPU) exists and runs
`fsl-acceptance`. Check every flavor `cloud.yaml` names exists on the cloud
you use; the platform refuses a missing one by name.

```bash
openstack flavor create --ram 8192 --vcpus 4 --disk 80 m1.large
```

### 3.4 Keypairs

- `fsl-claude` — the operator's key the platform VM boots with (stack
  parameter `key_name`, `keys.operator` in `cloud.yaml`). Create it as `fsl-range` before the stack:
  `openstack keypair create --public-key ~/.ssh/fsl_claude.pub fsl-claude`
- `fsl-platform` — the platform's own range key, imported by
  `POST /api/range/fabric/` from `/data/ssh/id_ed25519` in the platform
  container. Never create it by hand. See §6.3 on drift.

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

The cloud holds exactly one image uploaded by hand: Canonical's Ubuntu 24.04
cloud image, unmodified. Nothing is baked into it; every package, tool, key
and setting the project needs is installed or written at boot by cloud-init
(the platform VM, the builders) or by the platform over ssh (`configure/`).

| Image | How it gets there | One-click |
|---|---|---|
| `compute.base_image` (e.g. `ubuntu-24.04`) | stock `noble-server-cloudimg-amd64.img`, checksum verified, uploaded as is (below) | by hand, once |
| `fsl-waf`, `fsl-wg-board`, `fsl-kali` | golden images, built by the platform on builders booted from the base image (§6) | yes |
| `fsl-opnsense-<version>` | built by the platform on a builder booted from the base image, from the official OPNsense nano image (below) | yes |

The base image, as a project member, on a machine with the openstack CLI
(`SHA256SUMS` lists one line per file of that build; `--ignore-missing`
checks the one downloaded) [U1]:

```bash
curl -fLO https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
curl -fLO https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
sha256sum --ignore-missing -c SHA256SUMS
openstack image create --disk-format qcow2 --container-format bare \
  --file noble-server-cloudimg-amd64.img ubuntu-24.04
```

The `.img` is a qcow2 disk. `SHA256SUMS.gpg` beside it signs the list; to
check it as well, import Ubuntu's cloud-image signing key, compare its
fingerprint with the one Ubuntu publishes, and run `gpg --verify
SHA256SUMS.gpg SHA256SUMS`. The name you give the image is
`compute.base_image`. The platform refuses to build while the cloud holds
none, or more than one active image, of that name.

What used to assume more than the stock image: `fsl-kali` was built on a
second uploaded image (`kali-rolling`). It is now built on Ubuntu; its setup
enables the `universe` and `multiverse` components itself and installs the
tools from the Ubuntu archive (`wordlists` is Kali-only; the motd's list is
dirb's, linked to the old path).

**The OPNsense image [one-click].** `fsl-edge` declares `setup:
deploy/opnsense/build.sh` and `uploads: opnsense`. On `POST
/api/range/images/` the platform boots a builder from the base image with the
bundle in its user data and no credential, in the security group
`fsl-build`, which the images step makes if absent: its only ingress rule is
tcp 8080 from the platform's address on the platform network (replaced when
that address changes), and it keeps Neutron's default egress. The builder:

1. installs `curl`, `bzip2`, `openssl`, `qemu-utils`, `qemu-system-x86`,
   `dosfstools`, `mtools`, `fdisk`, `python3` (nothing assumed of the image);
2. downloads `OPNsense-<version>-nano-amd64.img.bz2`, its `.sig` and
   `OPNsense-<version>.pub` from `opnsense.mirror`/`<version>/`;
3. checks the archive against `opnsense.image_sha256` and the key's DER
   SHA256 against `opnsense.pubkey_sha256`, both copied from the release
   announcement [O3], not from the mirror, as the manual advises [O1];
4. unpacks it and verifies the signature on the unpacked image (`openssl
   base64 -d`, `openssl dgst -sha256 -verify`) [O1];
5. boots it once under QEMU (KVM when the builder has it, TCG otherwise) with
   three virtio NICs and a FAT seed disk holding `conf/config.xml`, presses a
   key at the configuration importer's prompt and names the seed disk
   (`vtbd1`) [O4], waits for `login:` and powers it off over the QEMU monitor
   (`deploy/opnsense/importer.py`);
6. converts it with `qemu-img convert -O qcow2 -c` to
   `/var/lib/fsl-serve/disk.qcow2`, starts `python3 -m http.server 8080` on
   it as the transient unit `fsl-serve`, and prints the ready line with the
   disk's SHA256 on its console;
7. the platform reads that line through Nova, pulls the disk over the
   platform network, refuses it if its SHA256 differs, then creates the
   Glance record `fsl-opnsense-<version>` (qcow2, bare, private,
   `hw_vif_model=virtio`, `hw_disk_bus=virtio`, `os_distro=freebsd`,
   `min_ram` 3072, `fsl_bundle`) and `PUT`s the file with its own fresh token
   [G3]; once Glance says active, the platform deletes the builder. A record
   left `queued` by an interrupted upload is filled on the next call.

The nano image is a preinstalled serial-console disk whose `/conf/config.xml`
is created from the default on first boot. That default assigns only LAN
(static 192.168.1.1/24) and WAN, so the third NIC, mgmt, would get no address
and the platform could not reach a new edge; the importer step is how the
image starts from a config of ours without anyone at its console. The image's config
(`deploy/opnsense/config.xml`, rendered with the MTU and the platform's
public key) gives root no password (`*`) and only the platform's key, sshd
without password logins, opt1 (mgmt) by DHCP: the stock default password
`opnsense` never exists on it. The bundle digest covers the release settings,
the MTU, the platform key and the scripts, so any of them changing builds a
new image; a new version also gets a new name. An `fsl-opnsense-*` image
of a release `cloud.yaml` no longer names is listed as a leftover and removed
by `DELETE /api/range/images/` (and by `bin/cloud up` once the range is
ready on the new images), but only when it carries `fsl_bundle`, the mark of
an image this platform made, and no server in the project boots from it; any
other image of that name is left alone. Nothing in this path has run
against a cloud yet; the console strings the importer waits for are read from
the OPNsense source [O4] and the docs [O1], not observed.

**Licence (researched 2026-10-11, not legal advice).** OPNsense is BSD
2-clause, "Copyright © 2025 by Deciso B.V.", based on FreeBSD [O2]. Its
trademark policy lets the name be used "to promote OPNsense based products"
but asks for permission at project@opnsense.org before using a derivative of
the name [O2]. The project builds the image from the official release on each
cloud and does not publish it; describing the range as "based on OPNsense" is
within the policy, naming the image anything like "FSL-OPNsense" in public is
not without permission. The image's Glance name stays private to the project.

## 4. cloud.yaml

`deploy/openstack/cloud.example.yaml` is committed; copy it to
`deploy/openstack/cloud.yaml` (git ignores it) and fill it in. No secret goes
in it: only where to read the password. `platform/range/cloud.py` reads it
and refuses it before anything is touched, naming every problem by its dotted
key (an unknown key, a missing one, a Keystone URL ending in `/v3`, an
unquoted version, overlapping CIDRs, a password written into the file).

| Key | Example | Used by |
|---|---|---|
| `identity.keystone` | `http://192.168.0.110:5000` | Keystone base URL without `/v3`; CLI and platform |
| `identity.region`, `identity.interface` | `RegionOne`, `public` | the catalogue endpoints the CLI and the platform call |
| `identity.domain` | `default` | the id of the user's and the project's domain |
| `identity.project`, `identity.user` | `fsl-range` | the member the CLI and the platform sign in as |
| `identity.password_file` or `identity.password_env` | `~/.config/fsl/fsl-range.password` | exactly one; read on the operator's machine, appended to the VM's `openstack.env` over ssh |
| `network.external` | `provider` | the stack's router and floating IP |
| `network.dns` | `[8.8.8.8, 8.8.4.4]` | the platform network's DNS |
| `network.mtu` | `1450` | the edge's interfaces (the tenant networks' MTU; 1450 on VXLAN) |
| `network.platform`, `.estate`, `.mgmt` | `10.20.0.0/24`, `10.30.0.0/24`, `10.31.0.0/24` | private, non-overlapping, outside Docker's default local address pools (172.17.0.0/16 to 172.31.0.0/16 and 192.168.0.0/16, moby `daemon/libnetwork/ipamutils/utils.go`), `compose.yaml`'s networks and the declared origins |
| `compute.base_image` | `ubuntu-24.04` | the platform VM and every builder |
| `compute.availability_zone` | `""` | the platform VM, builders and slot VMs; empty lets Nova choose |
| `compute.flavors` | `platform`, `builder`, `range`, `edge` (required, 3 GB RAM or more), per role | §3.3 |
| `keys.operator`, `keys.operator_file` | `fsl-claude`, `~/.ssh/fsl_claude` | the keypair the platform VM boots with and its private half |
| `keys.range` | `~/.ssh/fsl-platform` | the platform's range key, kept across rebuilds |
| `opnsense.version`, `.mirror` | `"26.7"`, `https://pkg.opnsense.org/releases` | the image release (January and July; updates have no images [O1]) |
| `opnsense.image_sha256`, `.pubkey_sha256` | from the release announcement [O3] | §3.6 |
| `platform.stack`, `.repository`, `.ref` | `fsl-platform`, this repo, `dev` | the stack and the checkout it clones |

Where each value lands: `bin/platform-rebuild` and `bin/cloud` set the
openstack CLI's `OS_*` variables from `identity` (no openrc needed) and pass
every Heat parameter from the file (`Cloud.heat_parameters()`); the template
has no defaults and writes the values into `/opt/fsl/openstack.env` as
`FSL_OPENSTACK_*` and `FSL_OPNSENSE`, which the platform reads (`settings.py`)
and refuses by name when one it needs is missing.

## 5. The platform VM

### 5.1 The Heat stack

`deploy/openstack/platform.yaml` creates network `fsl-platform`
(`network.platform`), a router to `network.external`, group `fsl-platform`, a
port, a floating IP (**(this cloud)** `192.168.0.210`) and a server from
`compute.base_image` whose cloud-init installs Docker, sets Docker's MTU to the
network's, adds 4 GB swap, clones `repository` at `ref` into `/opt/fsl`,
writes `/opt/fsl/openstack.env` (every cloud value but the password) and
`/opt/fsl/.env` (`FSL_PUBLISH=<fixed IP>`, `FSL_SYSLOG_PUBLISH=0.0.0.0`), and
enables `fsl-platform.service`.

`FSL_PUBLISH` is the VM's fixed IP, so 8000 listens on that address, not
loopback; the floating IP NATs to it. `FSL_PUBLISH=0.0.0.0` on a VM is an
environment error recorded in DECISIONS 2026-10-10.

The password stays out of Heat and user data: Nova's metadata service answers
from inside containers on the VM, so anything in user data is readable there.

### 5.2 One command [one-click]

From the operator's machine, with `python-openstackclient` and
`python-heatclient` installed and the repo's `.venv` (PyYAML):

```bash
.venv/bin/python bin/cloud up            # --replace to replace a standing platform
.venv/bin/python bin/cloud down
```

`up`: refuses without a usable `cloud.yaml`; reads the stack's status and
refuses while it is `*_IN_PROGRESS`; creates the stack if absent, and if it is
`*_FAILED` deletes its builders and the stack (`--wait`) and creates it again
(`--replace` replaces a working one through `bin/platform-rebuild`, below); waits for the
API; `POST fabric/` (stops on drift); `POST images/` until every image is
ready with no builder left (stops on a failed image or one no script builds);
`POST slot/` (stops when blocked); `GET ready/` until the slot leaves
`NOT_STANDING`/`REBUILDING`; `POST configure/`, retried while it answers 503
as the VMs' ssh comes up, stopping on 409; `GET ready/` until ready; then
`DELETE images/` removes leftovers no server boots from. `down`:
keeps the range key, backs up the store (`bin/backup`), `DELETE slot/`,
`DELETE fabric/`, deletes every server whose name starts with `fsl-build-`,
which carries the `fsl_image` property and which has a port on this stack's
own network (the stack's `network` resource; such a port would fail the
stack delete), then deletes the stack; Glance keeps the images. A `*_FAILED` stack has
no platform to ask: `down` deletes its builders and the stack only. Not yet
run against a cloud.

### 5.3 Rebuild and delete — lossless

```bash
.venv/bin/python bin/platform-rebuild    # --cloud PATH, --ref REF
```

It refuses unless every platform image for the ref's commit is public on GHCR,
keeps the range key (`keys.range`, taken once from the running platform),
backs up the store with `bin/backup`, deletes and recreates the stack, appends
the password, writes the kept key to `/data/ssh/id_ed25519`, restores the
store, and waits for `/api/sessions/`. With the key carried over, the fabric's
`fsl-platform` keypair stays valid and the slot need not be torn down. Not
yet run against the cloud.

## 6. The range (substrate openstack)

Everything is through the platform's API, as `fsl-range`. Each `GET` reads the
plan (missing, present, drifted, left over); `POST` converges; `DELETE` tears
down. `bin/cloud up` runs these in order; by hand:

```bash
P=http://$ADDRESS:8000/api/range
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/fabric/     # fsl-internet (30 origin /24s, DHCP off), fsl-estate, fsl-mgmt (no gateway),
                                  # keypair fsl-platform, groups fsl-range/fsl-reach, platform port fsl-platform.mgmt
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/images/     # repeat until "clean": true; builders on FSL_OPENSTACK_BUILD_NETWORK
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/slot/       # boots fsl-edge, fsl-kali, fsl-waf, fsl-wg-board
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/configure/  # the edge's config.xml + reboot; WAF log forwarding
curl -s $P/ready/
```

Notes:

- Networks are found by tag `fsl.segment.id=<segment>`, not name; the fabric
  needs the Neutron `standard-attr-tag` extension (on by default).
- Image builds need `FSL_OPENSTACK_BUILD_NETWORK` (the template writes the
  stack's network, which has a router) and `compute.base_image` present exactly
  once. Nova user data is capped at 65535 bytes base64 per image bundle.
- The edge's Internet and estate ports hold every origin's `.1` and the
  estate's gateway and have `allowed_address_pairs 0.0.0.0/0`, so the edge
  forwards un-NATted; Kali's Internet port holds ~100 origin addresses.
  cloud-init applies only a port's first address, hence the slot's `bootcmd`.
- The edge's NICs are ordered internet, estate, mgmt, which FreeBSD names
  vtnet0, vtnet1, vtnet2 and the config assigns to WAN, LAN and opt1. It runs
  no cloud-init; the platform reaches it as root over mgmt with its key.
- The edge's Suricata watches the WAN in IDS (pcap) mode with hardware
  offloading off [O5]; HOME_NET is the estate and mgmt, because OPNsense's
  suricata.yaml sets EXTERNAL_NET to `!$HOME_NET` and includes
  `conf.d/*.yaml` [O6].
- `configure/` writes `/conf/config.xml`, the Suricata include
  (`/usr/local/etc/suricata/conf.d/fsl.yaml`) and the rule file, reboots the
  edge, and waits up to 15 minutes for a new boot time before checking it.
- A guest needs a config drive; without one it gets no metadata.
- Nova here answers 404 for the console of a powered-off guest.

### 6.1 Session reset

`POST $P/slot/rebuild/` Nova-rebuilds every slot VM from its golden image,
keeping ports and addresses; closing a session calls it. It wipes the pushed
config, so run `configure/` again.

### 6.2 Teardown order

Slot, then fabric. `DELETE $P/fabric/` refuses while any server other than the
platform has a port on a range network. Images stay; `DELETE $P/images/`
removes only failed builders and images of older bundles.

### 6.3 Keypair drift

The fabric compares keypair `fsl-platform` with the platform's
`/data/ssh/id_ed25519`. A new VM without the kept key makes a new one, and
`GET fabric/` reports `keypair fsl-platform holds another public key` (drift,
409 on POST). Today: tear down slot → fabric before replacing the VM. With
`bin/platform-rebuild` the key is carried over and nothing drifts.


## 7. Verification

```bash
curl -s http://$ADDRESS:8000/api/range/ready/          # the slot's readiness
curl -s http://$ADDRESS:8000/api/range/fabric/ | jq .clean
ssh ubuntu@$ADDRESS 'cd /opt/fsl && FSL_PLATFORM_URL=http://'$ADDRESS':8000 bin/verify'
```

`bin/verify` restarts the platform and resets the range; never run it against
a stack someone is using.

**Acceptance on substrate openstack: deferred** (OpenStack range is out of
the MVP). Last run 2026-10-09, with pfSense: 23 passed, 78 skipped, 17
failed, 21 errors. Causes (`docs/STATE.md` backlog 0):

- session fixtures hold a session open while others POST a new one, and the
  single-slot range answers 409;
- `/api/rules/apply/` wrote and reloaded `/var/lib/suricata/rules/local.rules`
  on the edge, which its Suricata never loads; fixed 2026-10-11: the sensor
  host in `declaration.yaml` names its rule file and reload command;
- the VM had no GeoLite2 database (`bin/fetch-geoip` now runs at first boot).

The MVP gate ran on substrate docker on `fsl-acceptance` (192.168.0.220,
`m1.platform8`): 146 passed, 0 failed (2026-10-10). That VM is temporary and
is to be deleted once no longer needed; it holds cores the quota needs.

## 8. Known issues

- MTU (`network.mtu`), no resize (§2.4), TaaS override (§2.3), no Cinder,
  keypair drift (§6.3), full core quota (§3.2).
- A member cannot create flavors or change quotas; the stack uses no
  admin-only Heat resource.
- `platform.ref` is required (example value `dev`; `--ref` overrides it): the
  VM only sees pushed commits.
- The project password is plain text in `/opt/fsl/openstack.env` and the
  platform container's environment.
- The edge's builder serves its disk over plain HTTP on the platform network
  until it is deleted; integrity rests on the SHA256 it prints on its console,
  which the platform reads through Nova and checks before the upload.
- Every edge built from one image shares its sshd host keys (generated on the
  builder's QEMU boot); the platform pins each server's key by its own alias.
- The nano image keeps `/var/log` and `/tmp` in memory [O1]; nothing is kept
  there across a reboot, and the edge's logs live in Elasticsearch.
- The platform reaches Kali over `mgmt`: origin addresses collide with the
  platform's docker edge bridges.

## Sources

- [K1] Kolla-Ansible 2026.1 quickstart — https://docs.openstack.org/kolla-ansible/2026.1/user/quickstart.html
- [K2] kolla-ansible stable/2026.1 `etc/kolla/globals.yml` — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2026.1/etc/kolla/globals.yml
- [K3] kolla-ansible stable/2026.1 `ansible/group_vars/all/neutron.yml` (`enable_neutron_taas: false`); TaaS added in 18.0.0 — https://docs.openstack.org/releasenotes/kolla-ansible/2024.1.html
- [K4] kolla-ansible stable/2026.1 `ansible/roles/neutron/tasks/config.yml` — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2026.1/ansible/roles/neutron/tasks/config.yml
- [K5] Kolla-Ansible, OpenStack service configuration overrides — https://docs.openstack.org/kolla-ansible/latest/admin/advanced-configuration.html
- [N1] Nova configuration, `allow_resize_to_same_host` (default False) — https://docs.openstack.org/nova/latest/configuration/config.html
- [H1] Heat `OS::Nova::Server` (`flavor_update_policy` RESIZE|REPLACE, default RESIZE; `user_data_update_policy` default REPLACE) — https://opendev.org/openstack/heat/src/branch/master/heat/engine/resources/openstack/nova/server.py
- [G3] Glance API v2, upload binary image data (`PUT /v2/images/{image_id}/file`) — https://docs.openstack.org/api-ref/image/v2/
- [U1] Ubuntu 24.04 cloud images and their `SHA256SUMS` — https://cloud-images.ubuntu.com/noble/current/
- [O1] OPNsense manual, Initial Installation & Configuration (image types, nano, download and verification, release schedule) — https://docs.opnsense.org/manual/install.html
- [O2] OPNsense legal guidelines (BSD 2-clause licence, trademark policy) — https://opnsense.org/legal-guidelines/
- [O3] OPNsense 26.7 release notes (26.7.6 on 2026-10-08; the 26.7 image checksums and public key) — https://docs.opnsense.org/releases/CE_26.7.html
- [O4] OPNsense core, `src/sbin/opnsense-importer` (the boot-time configuration importer and its prompts) — https://github.com/opnsense/core
- [O5] OPNsense manual, Intrusion Prevention System (capture modes; offloading off) — https://docs.opnsense.org/manual/ips.html
- [O6] OPNsense core, `src/opnsense/service/templates/OPNsense/IDS/suricata.yaml` (EXTERNAL_NET is !$HOME_NET; `conf.d/*.yaml` included) — https://github.com/opnsense/core
