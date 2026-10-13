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
| One base image, stock Ubuntu 24.04, checksum-verified upload | by hand, once per cloud; done (this cloud, noble 20260911) | §3.6 |
| `cloud.yaml`: every cloud-specific value, validated | done (this cloud, 2026-10-11) | §4 |
| Platform images on GHCR (`.github/workflows/images.yml`) | done (public, pulled 2026-10-11) | §5 |
| Heat stack pulls images instead of `--build` | done (2026-10-11) | §5 |
| `bin/platform-rebuild`: lossless replace (store + range key carried over), driven by `cloud.yaml` | built; the store and key carry-over not checked live | §5 |
| `bin/cloud up|down` | done (2026-10-11); `up` after `down` starts with an empty store | §5 |
| Fabric via `POST /api/range/fabric/` | done | §6 |
| Golden images built on the cloud via `POST /api/range/images/` | done | §6 |
| `fsl-kali` built on Ubuntu (no second base image) | done (2026-10-11, every tool present) | §6 |
| `fsl-wargame-host`: every wargame (board, corp) as its GHCR containers on one host image, no image per wargame | built 2026-10-11; not run on a cloud | §3.6, §6 |
| `fsl-opnsense-<version>` built by an Ubuntu builder from the official nano image | done (26.7, 2026-10-11) | §3.6 |
| OPNsense edge configured over mgmt ssh (`configure/`) | done (2026-10-11; survival of an OPNsense update not checked) | §6 |
| Slot + configure via `/api/range/slot/`, `/api/range/configure/` | done (OPNsense edge; automatic after a close, §6.1) | §6 |
| Acceptance on substrate openstack | 77 passed / 0 failed / 71 skipped (2026-10-13, two workers; the skips are `COMPOSE_RANGE_ONLY`) | §7 |

Steps below carry **[one-click]** where the script replaces them, and
**[admin, once]** where they stay manual because a member cannot do them.

## 1. What this project needs from OpenStack

The platform runs on one of two substrates (`FSL_SUBSTRATE`):

- `range.docker.Docker` — the whole range as compose stacks on one Docker
  host. Needs only a VM with Docker; OpenStack is just where the VM lives.
  Both substrates are first-class: every acceptance test must run and pass
  on substrate openstack as on docker, none marked docker-only or skipped
  there (`docs/DECISIONS.md` 2026-10-11, superseding the 2026-10-08 spec's
  "OpenStack work, not MVP").
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

**(this cloud)** cores quota is 20, RAM 50 GB, instances 10; it holds the
platform VM (m1.large, 2 cores) and, since 2026-10-12, two slots
(`compute.slots: 2`) of 4 VMs each (`fsl-edge`, `fsl-kali`, `fsl-waf`,
`fsl-wargame-host`, 2 cores each): 9 instances, 18 cores, 40 GB. Each slot
beyond the first adds 2 networks (`fsl-internet-N`, `fsl-estate-N`), 31
subnets, 9 ports and 3 collector rules in `fsl-reach`: measured with two
slots, networks 6/100, subnets 64/100, ports 25/500, security group rules
26/100, security groups 6/10. Image builders (one per built host, 2 cores
each on `m1.linux`) boot only as many at once as the quota leaves room for
(Nova `GET /limits` against the builder flavor): with both slots standing
that is one, and the next boots once the first is deleted, so
`POST /api/range/images/` repeated until clean builds them one at a time. With
no room and no builder at work, `images/` answers 503 and names the fix:
`DELETE /api/range/slot/?slot=2` or a higher quota. Also 1 network for the
stack, 1 router, 1 floating IP, and image storage for 4 golden images.

```bash
openstack quota show fsl-range
openstack quota set --cores 24 --ram 65536 --instances 12 fsl-range   # example
```

### 3.3 Flavors [admin, once]

A member cannot create flavors. `compute.flavors` in `cloud.yaml` names them:

| Key | Use | Notes |
|---|---|---|
| `platform` | platform VM | 8 GB RAM or more; 4 GB OOM-killed Elasticsearch once sessions stacked up (DECISIONS 2026-10-10). Example `m1.large` (8 GB / 2 vCPU / 60 GB) |
| `builder` | image builders | the OPNsense builder holds the 3 GB raw image, its qcow2 and a 2 GB QEMU guest: 4 GB RAM and 20 GB disk or more (`m1.medium`) |
| `range` | every slot VM no role names | 20 GB disk or more: a golden image's min disk is its builder's disk |
| `edge` (required), or any other role name | the host filling that role | the edge is required: OPNsense wants 3 GB RAM or more (its image says `min_ram` 3072), so the `range` flavor would fail at boot |
| `wargames` (optional) | `fsl-wargame-host` | runs two MySQL 8, Django and WordPress containers at once; the example names `m1.medium` (4 GB). Without it the host takes `range`. Its memory use is not measured |

**(this cloud)** `platform` is `m1.large` (8 GB / 2 vCPU / 60 GB, created
2026-10-11; `m1.platform8` was deleted), and `builder`, `range` and `edge` are
`m1.linux` (4 GB / 2 vCPU / 30 GB). Check every flavor `cloud.yaml` names exists on the cloud
you use; the platform refuses a missing one by name.

```bash
openstack flavor create --ram 8192 --vcpus 2 --disk 60 m1.large
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
| `fsl-platform` | Heat stack | tcp 22, tcp 8000, tcp 8002, tcp 3080, icmp in |
| `fsl-range` | fabric | all IPv4 in; on every range port off `mgmt` (anti-spoofing stays on) |
| `fsl-reach` | fabric | nothing in, then udp 5140 from exactly the edge, the WAF and the wargame host (`configure/`) |
| `fsl-mgmt` | fabric | all IPv4 in from members of `fsl-reach` (the platform's `mgmt` port) only; on every range host's `mgmt` port, so Kali's `mgmt` port reaches no one |
| `fsl-build` | images step | tcp 8080 from the platform's address only (§3.6); `bin/cloud down` leaves it |

8002 is the blue console's site browser on both substrates; on openstack the
platform proxies it to the session's slot's WAF over `mgmt`. A platform
stack made before 2026-10-13 lacks the rule; add it by hand:

```bash
openstack security group rule create --protocol tcp --dst-port 8002 fsl-platform
```

3080 is the GNS3 server (`compose.yaml` `gns3`), whose web UI the blue
console's Topology pane frames. A platform stack made before P1 of the
scenario course lacks the rule; add it by hand:

```bash
openstack security group rule create --protocol tcp --dst-port 3080 fsl-platform
```

### 3.6 Images

The cloud holds exactly one image uploaded by hand: Canonical's Ubuntu 24.04
cloud image, unmodified. Nothing is baked into it; every package, tool, key
and setting the project needs is installed or written at boot by cloud-init
(the platform VM, the builders) or by the platform over ssh (`configure/`).

| Image | How it gets there | One-click |
|---|---|---|
| `compute.base_image` (e.g. `ubuntu-24.04`) | stock `noble-server-cloudimg-amd64.img`, checksum verified, uploaded as is (below) | by hand, once |
| `fsl-waf`, `fsl-kali` | golden images, built by the platform on builders booted from the base image (§6) | yes |
| `fsl-wargame-host` | built the same way; holds Docker and every wargame's GHCR images at the platform's tag (below) | yes |
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
none, or more than one active image, of that name. **(this cloud)**
`ubuntu-24.04` is the noble 20260911 build; its SHA256 matched `SHA256SUMS`
(2026-10-11), and it is the only image uploaded by hand.

What used to assume more than the stock image: `fsl-kali` was built on a
second uploaded image (`kali-rolling`). It is now built on Ubuntu; its setup
enables the `universe` and `multiverse` components itself and installs the
tools from the Ubuntu archive (`wordlists` is Kali-only; the motd's list is
dirb's, linked to the old path).

**The wargame host [one-click].** No wargame has an image of its own; the
image count is fixed at five (base, `fsl-opnsense-<version>`, `fsl-waf`,
`fsl-kali`, `fsl-wargame-host`) however many wargames there are.
`fsl-wargame-host` declares `wargames: [board, corp]` and `publish: {board:
8000, corp-wp: 80}`. Its bundle holds `deploy/wargame-host/setup.sh` and three
files the platform generates: each wargame's own `compose.yaml` rendered for
the host (no `build:`, no session network, `container_name` set to the
service, `${FSL_IMAGE_TAG}` replaced by the platform's tag, the published
ports added) and `daemon.json` with the tenant MTU (`network.mtu`), as the
platform VM has. The setup enables `universe`, installs `docker.io` and
`docker-compose-v2`, installs the files under `/opt/fsl/wargames/` and runs
`docker compose pull` on each while the builder still has the Internet: the
range has none. The images are the ones the docker substrate runs
(`ghcr.io/nekonic/fsl-board`, `fsl-corp`, `fsl-corp-db`, the pinned `mysql`),
so they must be public and exist for the tag (`FSL_IMAGE_TAG`, the platform
checkout's commit, from `/opt/fsl/.env`). The tag is in the bundle's digest,
so a platform on a new commit plans a new host image. A tag that moves (`dev`)
does not: rebuild by deleting the image.

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
other image of that name is left alone. Run on this cloud 2026-10-11 with
26.7: the archive SHA256 matched, the `.sig` verified ("Verified OK") over the
unpacked image, the importer's console strings appeared as read from the
source [O4], the builder went from boot through import to power-off in about
a minute, `fsl-serve` served the disk, and the Glance image went active with
the properties above.

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
| `network.address` | `""` (**(this cloud)** `192.168.0.210`) | optional; a floating IP the project already holds, which the stack associates and never releases, so the address survives `bin/cloud down` and every rebuild; empty, the stack allocates a new one (§5.1) |
| `network.dns` | `[8.8.8.8, 8.8.4.4]` | the platform network's DNS |
| `network.mtu` | `1450` | the edge's interfaces (the tenant networks' MTU; 1450 on VXLAN) |
| `network.platform`, `.estate`, `.mgmt` | `10.20.0.0/24`, `10.30.0.0/24`, `10.31.0.0/24` | private, non-overlapping, outside Docker's default local address pools (172.17.0.0/16 to 172.31.0.0/16 and 192.168.0.0/16, moby `daemon/libnetwork/ipamutils/utils.go`), `compose.yaml`'s networks and the declared origins |
| `compute.base_image` | `ubuntu-24.04` | the platform VM and every builder |
| `compute.availability_zone` | `""` | the platform VM, builders and slot VMs; empty lets Nova choose |
| `compute.flavors` | `platform`, `builder`, `range`, `edge` (required, 3 GB RAM or more), per role | §3.3 |
| `compute.slots` | `1` (**(this cloud)** `2`) | optional; how many copies of the range stand, so how many sessions run at once (§6.4); `FSL_OPENSTACK_SLOTS` |
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
port, a floating IP and a server from
`compute.base_image` whose cloud-init installs Docker, sets Docker's MTU to the
network's, adds 4 GB swap, clones `repository` at `ref` into `/opt/fsl`,
writes `/opt/fsl/openstack.env` (every cloud value but the password, and
`FSL_TOOL_IMAGE=fsl-kali`, the attacker host the launcher runs tools on) and
`/opt/fsl/.env` (`FSL_PUBLISH=<fixed IP>`, `FSL_SYSLOG_PUBLISH=0.0.0.0`), and
enables `fsl-platform.service`.

With `network.address` set, `bin/platform-rebuild` looks the floating IP up
by address (`openstack floating ip list --floating-ip-address`) before it
deletes anything, refuses if the project holds none, and passes its id as
`floating_ip_id`; the stack then creates an `OS::Neutron::FloatingIPAssociation`
instead of an `OS::Neutron::FloatingIP`. Deleting the association only sets
the floating IP's `port_id` to null (Heat `neutron/floatingip.py`,
`FloatingIPAssociation.handle_delete`), so the address stays in the project.
Neutron's default policy lets only an admin choose the address, so it is
created once, as admin: **(this cloud)** `openstack floating ip create
--project fsl-range --floating-ip-address 192.168.0.210 provider`.

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
no platform to ask: `down` deletes its builders and the stack only. Run
2026-10-11: `down` took 26 s and left no stack, builder, range network, port,
router or range security group; it kept the Glance images, the reserved
floating IP, the `fsl-claude` keypair and the `fsl-build` group. An `up` after
`down` starts with an empty store: `down`'s backup is not restored (open,
`docs/STATE.md` backlog 0).

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
                                  # keypair fsl-platform, groups fsl-range/fsl-reach/fsl-mgmt, platform port fsl-platform.mgmt
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/images/     # repeat until "clean": true; builders on FSL_OPENSTACK_BUILD_NETWORK
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/slot/       # boots fsl-edge, fsl-kali, fsl-waf, fsl-wargame-host; mgmt ports into fsl-mgmt
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/configure/  # the edge's config.xml + reboot; WAF log forwarding; the wargames and the estate sensor up
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
- The edge's WAN pass rule admits tcp 80 to the WAF's estate address only;
  before 2026-10-12 it passed any destination, and Kali reached the wargame
  host's 8000 and 80 on the estate through the edge, past the WAF.
- A second sensor watches the estate leg (WAF to target), which docker's one
  sensor sees from inside the WAF's namespace and the edge never sees: docker's
  Suricata image and `deploy/suricata/suricata.yaml`, run on `fsl-wargame-host`
  with host networking from `deploy/wargame-host/sensor.yaml`, on the
  interface holding the host's estate address (`af-packet`). Its role is
  `estate-sensor`; the host entry names its rule file and reload command, and
  `logs: {suricata: /var/log/suricata/eve.json}`, which rsyslog forwards to the
  collector tagged `suricata`, as the WAF forwards its audit log. Rule seeding,
  validation and changes go to both sensors.
- `configure/` writes `/conf/config.xml`, the Suricata include
  (`/usr/local/etc/suricata/conf.d/fsl.yaml`) and the rule file, reboots the
  edge, waits up to 15 minutes for a new boot time before checking it, and
  then records `/conf/fsl-settled` for the session reset (§6.1).
- `configure/` ends by starting the wargames on `fsl-wargame-host` over ssh,
  as `ubuntu` with sudo: `docker compose -p <id> -f /opt/fsl/wargames/<id>.yaml
  up -d --wait --pull never` for each (the `wargames` role), and fails with
  compose's output if one does not come up healthy. The board publishes 8000
  and corp-wp 80 on the host; the WAF reaches them by the names `board` and
  `corp-wp` its `/etc/hosts` gives the host's estate address, and the platform
  reads the board's ground truth at the host's mgmt address on 8000. A role
  the host fills (`board`, `board-db`, `corp`, `corp-db`) runs commands inside
  its container (`sudo docker exec <service>`), which is how the corp effect
  reader gets `corp-db`'s binary log and the harness's `run_on_role` reaches
  the same containers it reaches on docker.
- A guest needs a config drive; without one it gets no metadata.
- Nova here answers 404 for the console of a powered-off guest.

### 6.1 Session reset

Closing a session resets the slot; since 2026-10-12 only the VMs that hand
out a shell are rebuilt (see `docs/DECISIONS.md`, "The close resets the edge
and the wargame host in place"):

| VM | Reset at close | Why |
|---|---|---|
| `fsl-kali` | Nova rebuild from its image, then nothing to configure | the red team's root shell; anything outside config can carry over |
| `fsl-waf` | Nova rebuild, then `configure_waf()` (audit-log forwarding) | the blue team's shell (`vm-terminal.sh fsl-waf`) |
| `fsl-edge` | in place: baseline `fsl.rules` written back; `/conf/config.xml`, `conf.d/fsl.yaml` and `fsl.rules` checked by sha256; pf states of every range subnet dropped (`pfctl -k`, mgmt kept); `configctl filter reload`; `configctl ids restart`; wait for the Suricata socket | the session can change only `fsl.rules`, and only the platform reaches its GUI and ssh (`fsl-mgmt`) |
| `fsl-wargame-host` | in place: `docker compose -p <id> down -v` per wargame and for the estate sensor, its `eve.json` and rsyslog's imfile state removed; then the usual `up -d --wait --pull never`, the sensor, the baseline rules seeded into it through `rules/suricata.py`, and log forwarding | the containers mount no host path, run unprivileged and get no docker socket |

OPNsense rewrites `config.xml` on its first boot after an install
(migrations add uuids, defaults and `persisted_at` stamps), so the edge's file
never equals the rendered one. `configure/` therefore ends by writing
`/conf/fsl-settled`: the sha256 of the config the platform rendered and the
sha256 of `/conf/config.xml` once the edge has settled. The in-place reset
compares both against what it renders now and what the edge holds; any
mismatch, a Suricata that does not answer within 60 s, or an edge that does
not hold its addresses, sensor, logging and WAN pass rule afterwards falls
back to the install and reboot (`configure_edge()`), which records again. The
configd actions are OPNsense's own (`actions_ids.conf` `[restart]` runs
`/usr/local/etc/rc.d/suricata restart`; `actions_filter.conf` `[reload]` runs
`/usr/local/etc/rc.filter_configure`, opnsense/core
`src/opnsense/service/conf/actions.d`). `[flush.states]` (`pfctl -F state`)
is not used: states are floating (`all`) and the pass rules keep state with
`flags S/SA`, so flushing every state would drop the platform's own ssh
session to the edge.

The in-place resets start at once, beside the Nova rebuilds; the rebuilt VMs
are configured once Nova has shown each of them rebuilding and back to ACTIVE
(a rebuilt VM never seen leaving ACTIVE within 2 minutes fails the reset), from
a fresh read of the cloud (a VM's ssh host-key alias follows its launch time).
Everything runs under one hold of the rules lock and polls every 2-3 s.
Meanwhile `ready/` answers phase `RESETTING` and a refused
`POST /api/sessions/` names the reset, so a client waits rather than calling
`configure/`. A failed reset reads `RESET_FAILED` with its reason;
`POST $P/configure/` retries it (a full configure, edge reboot included).
`POST $P/slot/rebuild/` still Nova-rebuilds every slot VM and is not followed
by a configure; run `configure/` after it.

Close to READY: 95-116 s per session while every VM was rebuilt and the edge
rebooted; 65.8, 65.9 and 60.1 s with the in-place reset (three board
sessions, 2026-10-12, no fallback).

Recorded trade-offs, not verified threats: the edge's isolation between
sessions is now "config verified by hash" rather than "rebuilt from its
image" (a change that leaves the three files alone, such as a package
installed through the GUI's firmware page, would carry over); a container
escape on the wargame host would persist to the next session, where a rebuild
removed it.

### 6.2 Teardown order

Slot, then fabric (`DELETE $P/slot/` takes every slot, `?slot=N` one). `DELETE $P/fabric/` refuses while any server other than the
platform has a port on a range network. Images stay; `DELETE $P/images/`
removes only failed builders and images of older bundles.

### 6.3 Keypair drift

The fabric compares keypair `fsl-platform` with the platform's
`/data/ssh/id_ed25519`. A new VM without the kept key makes a new one, and
`GET fabric/` reports `keypair fsl-platform holds another public key` (drift,
409 on POST). Today: tear down slot → fabric before replacing the VM. With
`bin/platform-rebuild` the key is carried over and nothing drifts.


### 6.4 Range slots

`compute.slots: N` stands N copies of the range. Slot 1 keeps the names
above; slot N>1 is `fsl-edge-N`, `fsl-kali-N`, `fsl-waf-N`,
`fsl-wargame-host-N`, its ports `<host>-N.<segment>`, its servers tagged
`fsl_slot=N`. Each slot beyond the first stands on its own `fsl-internet-N`
(the same 30 origin /24s) and `fsl-estate-N` (the same estate CIDR), tagged
`fsl.slot=N`; `fsl-mgmt` is shared. The platform gives each session the first
free READY slot and keeps it for the session's life; the close resets only
that slot. The collector writes each slot's syslog to `fsl-logs-slotN-*`,
telling the slots apart by the sender's hostname (`fsl-waf-2`,
`fsl-edge-2.range.internal`); a session reads its slot's index.

Adding a slot to a standing range, by hand (what `bin/cloud up` does for
every slot):

```bash
echo FSL_OPENSTACK_SLOTS=2 >> /opt/fsl/openstack.env    # or compute.slots in cloud.yaml before bin/cloud up
docker compose up -d --force-recreate platform
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/fabric/            # fsl-internet-2, fsl-estate-2, 31 subnets
curl -s -X POST -H 'Content-Type: application/json' -d '{}' "$P/slot/?slot=2"     # the slot's 4 VMs from the same images
curl -s -X POST -H 'Content-Type: application/json' -d '{}' "$P/configure/?slot=2"
curl -s $P/ready/                                                                  # slots[].phase READY
```

Measured 2026-10-12: the slot-2 VMs went ACTIVE within about 30 s and
`configure/?slot=2` took 72 s (edge install and reboot included); slot 1
stayed READY throughout. Two sessions opened at once took slots 1 and 2, a
third answered 409; the same case fired in each left from the same JP origin
address, 106.128.0.14, and its alerts landed in `fsl-logs-slot1-*` (from
`fsl-edge.range.internal`, `fsl-waf`) and `fsl-logs-slot2-*` (from
`fsl-edge-2.range.internal`, `fsl-waf-2`) respectively; each session ingested
only its own case's alerts. Closing slot 2's session rebuilt `fsl-waf-2` and
`fsl-kali-2` only, slot 1 stayed `IN_USE`, and slot 2 was READY 64.9 s later.

## 7. Verification

```bash
curl -s http://$ADDRESS:8000/api/range/ready/          # the slot's readiness
curl -s http://$ADDRESS:8000/api/range/fabric/ | jq .clean
ssh ubuntu@$ADDRESS 'cd /opt/fsl && FSL_PLATFORM_URL=http://'$ADDRESS':8000 bin/verify'
```

`bin/verify` restarts the platform and resets the range; never run it against
a stack someone is using.

**Acceptance on substrate openstack: partial** (the OpenStack range is out of
the MVP). Run 2026-10-11 on a range built from scratch by `bin/cloud up`
(platform VM 192.168.0.210, OPNsense 26.7 edge): 50 passed, 86 skipped, 6
failed, 4 errors (the run before the reset fixes: 24 passed, 14 failed, 22
errors). Left (`docs/STATE.md` backlog 0):

- tests that reach compose containers this range does not have:
  `test_criterion_1_services_answer` (`kali`), the three `test_corp_authz`
  tests (`corp-db`), `test_board_loot` and `test_objectives`;
- `test_map`'s 4 errors: WAF tuning (`PUT /api/sessions/<id>/waf/`) has never
  worked on OpenStack, because `rules/crs.py` hard-codes the Docker image's
  CRS path and nginx pid.

Run time 2,900 s: fixture setup 1,689 s, test bodies 1,179 s, teardown 27 s;
the slowest item is `test_suppression`'s setup (578 s).

Checked live the same day: the edge's Suricata 8.0.6 loads the
`conf.d/fsl.yaml` include and `fsl.rules` (4 of 4 rules), `suricatasc` is at
`/usr/local/bin/suricatasc` with its socket at
`/var/run/suricata-command.socket` as the declaration names, the WAN pass rule
is in pf, and all of it survives a reboot (the edge answers again in about
30 s). Not checked: that it survives an OPNsense update; the edge has no route
to the Internet and cannot resolve `pkg.opnsense.org`. Kali on Ubuntu has
mitmproxy (8.1.1), mitmdump, nikto, ffuf, gobuster, whatweb, dirb with its
wordlists, sqlmap, nmap, hydra and nc. A session close resets the range
(§6.1): close to READY measured at 93 s.

The MVP gate on substrate docker ran on the platform VM itself: 146 passed, 0
failed, twice on 2026-10-11 (before and after the `gw_priority` fix in
`compose.yaml`). The temporary `fsl-acceptance` VM (192.168.0.220) was
deleted the same day; its floating IP 192.168.0.220 is still allocated to
`fsl-range`.

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
- Fixed 2026-10-12, measured first: Kali has a `mgmt` port, and while every
  range port sat in `fsl-range` an nmap from Kali found the wargame host's
  22, 80 and 8000 (`/internal/auth-users` answered 200 with every password
  hash), the edge's 22, 80 and 443 (the OPNsense GUI) and the WAF's 22 and 80
  open on `mgmt`. `mgmt` ports now sit in `fsl-mgmt`, which admits only the
  platform's port (`test/test_attacker_reach.py` scans from Kali). The
  Neutron DHCP port on `mgmt` (dnsmasq, 53) has no security group and still
  answers Kali.
- A server's `/etc/hosts` (and Kali's `board.com`/`corp.com`) comes from the
  user data it was booted with, and the reset's rebuild passes none. On
  2026-10-12 the WAF and Kali, booted while the board had its own VM and
  `fsl-waf` named only `board.com`, kept the old board address and no
  `corp.com` until their servers were deleted and `slot/` booted them again.

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
