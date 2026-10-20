# OpenStack

This file says what this project needs from an OpenStack cloud and how to set
one up from nothing. It covers the cloud (Kolla-Ansible 2026.1), the project,
the one base image, `cloud.yaml`, the platform VM, the range and the checks. It
is written for an operator who rebuilds the cloud side or onboards a new cloud.
`README.md` has the numbered steps to bring the product up. This file has the
detail behind them. §9 builds the whole cloud in one VM so you can check that it
works.

Words used in this file:

- **Range**: the VMs and networks the platform builds for training.
- **Slot**: one full copy of the range, four VMs: `fsl-edge`, `fsl-kali`,
  `fsl-waf` and `fsl-wargame-host`. One open session uses one slot.
- **Edge**: the OPNsense VM that works as the firewall and runs Suricata.
- **Wargame host**: the VM that runs the wargames (`board` and `corp`) as
  containers.
- **Estate network** (`fsl-estate`): the network behind the edge. It holds the
  WAF and the wargame host.
- **Fabric**: the networks, security groups and keypair the platform creates
  before any VM (`POST /api/range/fabric/`).
- **Store**: the platform's SQLite database (`db.sqlite3`).
- **Builder**: a temporary VM that builds one image.
- **Substrate**: what the platform builds the range on (`FSL_SUBSTRATE`); here
  `range.openstack.connect`.

Facts marked **(this cloud)** come from the cloud the product has run on since
2026-10-20: Kolla-Ansible on three nodes, `con01` (10.0.0.11), `com01`
(10.0.0.31) and `stg01` (10.0.0.41). We read them from that cloud on 2026-10-20.
The operator reaches 10.0.0.0/24 and the provider network through a VPN. From
2026-10-11 to 2026-10-20 the product ran on an earlier cloud (an all-in-one host
`master`, ML2/OVS). Where this file quotes a measurement from that time, it says
"the previous cloud". Everything else comes from this repo's code or from the
sources listed at the end.

## Target: one-click build

The end state is one command that builds the whole environment. Nothing is
compiled or installed by hand on the cloud. You upload exactly one image by
hand, the stock Ubuntu 24.04 cloud image.

1. `bin/cloud up` reads `deploy/openstack/cloud.yaml` (§4). It has Heat create
   the platform VM (`deploy/openstack/platform.yaml`). On first boot the VM pulls
   the platform and session images from GHCR. It does not build them.
2. The script gives the VM the password and the range ssh key over ssh.
3. The script then drives the platform's own range API in this order: fabric;
   images (the "golden images" the range boots from), repeated until every
   image is built; slot; `configure/`. Then it waits until `ready/` says ready.
   Each image is built on a builder booted from the stock Ubuntu image. The
   edge's builder downloads the official OPNsense release and serves the
   finished disk; the platform checks its SHA256 and uploads it to Glance.

| Piece | Status | Where |
|---|---|---|
| Kolla-Ansible cloud with Heat, Glance, Nova, Neutron (ML2/OVN) | done (this cloud) | §2 |
| Project `fsl-range`, member user, quotas, flavors | done by hand, admin only | §3 |
| One base image, stock Ubuntu 24.04, upload with checksum check | by hand, once per cloud; done (this cloud, 2026-10-20) | §3.6 |
| `cloud.yaml`: every cloud-specific value, validated | done (this cloud, 2026-10-20) | §4 |
| Platform images on GHCR (`.github/workflows/images.yml`) | done (public, pulled 2026-10-11) | §5 |
| Heat stack pulls images instead of `--build` | done (2026-10-11) | §5 |
| `bin/platform-rebuild`: replace the VM without losing data (store and range key carried over), driven by `cloud.yaml` | done (2026-10-15, `bin/cloud up --replace --sideload` twice, 28 and 55 min with a 6 GB store; the range stood through) | §5 |
| `bin/cloud up|down` | done (2026-10-11); since 2026-10-20 `up` after `down` restores the newest backup that holds rows (run live 2026-10-20) | §5 |
| Fabric via `POST /api/range/fabric/` | done | §6 |
| Golden images built on the cloud via `POST /api/range/images/` | done | §6 |
| `fsl-kali` built on Ubuntu (no second base image) | done (2026-10-11, every tool present) | §6 |
| `fsl-wargame-host`: every wargame (board, corp) runs as its GHCR containers on one host image, with no image per wargame | done (built 2026-10-11, runs the board and corp of every slot since; a sideloaded board reaches it, 2026-10-18) | §3.6, §6 |
| `fsl-opnsense-<version>` built by an Ubuntu builder from the official nano image | done (26.7, 2026-10-11) | §3.6 |
| OPNsense edge configured over mgmt ssh (`configure/`) | done (2026-10-11); we did not check whether it survives an OPNsense update | §6 |
| Slot and configure via `/api/range/slot/` and `/api/range/configure/` | done (OPNsense edge; runs by itself after a close, §6.1) | §6 |
| Acceptance on the OpenStack substrate | 70 passed / 0 failed / 0 skipped (2026-10-17, two workers; no test is skipped by substrate) | §7 |

Steps below are tagged **[one-click]** where the script does them for you. They
are tagged **[admin, once]** where you must do them by hand because a member
user cannot.

## 1. What this project needs from OpenStack

The platform builds the range as Nova servers on Neutron networks. It creates
them as a member user. cloud-init writes `FSL_SUBSTRATE=range.openstack.connect`
on the platform VM to select this.

The platform VM runs only the control plane as containers: platform,
Elasticsearch, Kibana, gns3 and the collector. `docker compose` pulls their
prebuilt images from GHCR. Every acceptance test runs and passes on OpenStack,
and none is marked skipped there (`docs/DECISIONS.md` 2026-10-11, which
replaced the 2026-10-08 spec's "OpenStack work, not MVP").

The edge (firewall and Suricata) is an OPNsense VM.

The platform calls these APIs (`platform/range/openstack.py`):

- Keystone v3, with password authentication in the configured domain.
- Nova: servers, keypairs, flavors, `os-interface`, rebuild and console log.
- Neutron: networks with tags, subnets, ports with fixed IPs and
  `allowed_address_pairs`, and security groups.
- Glance v2: list images, create an image record and delete an image. The
  platform uploads the edge's disk with `PUT /v2/images/{id}/file`, using its
  own token; the builder holds no credential.

The operator also uses Heat for the platform VM. The project uses no Cinder,
Octavia or Designate.

## 2. What the cloud needs (Kolla-Ansible 2026.1)

**(this cloud)** kolla-ansible (Nova reports microversion 2.100), Ubuntu images, ML2/OVN
with Geneve tenant networks, and `nova_compute_virt_type: "kvm"`. The nodes are:

- `con01` (10.0.0.11) is the controller. The API address
  (`kolla_internal_vip_address`) is 10.0.0.10, and every public endpoint is
  `http://10.0.0.10:<port>`.
- `com01` (10.0.0.31) is the one compute node. Its root logical volume was
  extended so that Nova reports `local_gb` 546.
- `stg01` (10.0.0.41) is the storage node, with the Cinder LVM backend `lvm-1`.
  The product does not use Cinder. We mention the node because its cinder-volume
  was down from 2026-09-18 to 2026-10-20. Kolla's default volume group is
  `cinder-volumes`, which does not exist on `stg01`, so the rendered config named
  a missing group. The fix was `cinder_volume_group: "ubuntu-vg"` in
  `globals.yml`.

The sections below show the all-in-one steps, because §9 builds that. A
multi-node cloud such as this one uses the same `globals.yml` keys with its own
inventory.

**ML2/OVN and DNS.** With ML2/OVN, Neutron tells each VM's DHCP client which DNS
resolvers to use. If `[ovn] dns_servers` is empty, Neutron uses the resolvers of
the `neutron-server` host's own `/etc/resolv.conf`. Under systemd-resolved, that
is `127.0.0.53`, which means nothing to a VM (`get_dhcp_dns_servers` in
`neutron/common/ovn/utils.py`). A subnet created with the DNS server `0.0.0.0`
announces no resolver at all [N3]. The platform creates every range subnet that
way (`platform/range/openstack.py`), because the range has no Internet and needs
no resolver. The product therefore does not depend on `[ovn] dns_servers`. A
cloud admin who wants the cloud's other VMs to resolve names sets
`[ovn] dns_servers` in `neutron.conf` (Kolla: an override file, §2.3's
mechanism). §8 has the symptom.

**MTU.** The tenant networks' MTU is 1442 on OVN (Geneve) and 1450 on VXLAN with
ML2/OVS. Set `network.mtu` to the value `openstack network show` reports for a
tenant network on your cloud.

### 2.1 Install and deploy [admin, once]

These commands follow the 2026.1 quickstart [K1]:

```bash
sudo apt install -y git python3-dev libffi-dev gcc libssl-dev libdbus-glib-1-dev python3-venv
python3 -m venv /opt/kolla-venv && . /opt/kolla-venv/bin/activate
pip install -U pip
pip install git+https://opendev.org/openstack/kolla-ansible@stable/2026.1
pip install docker dbus-python
sudo mkdir -p /etc/kolla && sudo chown $USER:$USER /etc/kolla
cp -r /opt/kolla-venv/share/kolla-ansible/etc_examples/kolla/* /etc/kolla
cp /opt/kolla-venv/share/kolla-ansible/ansible/inventory/all-in-one .
kolla-ansible install-deps
kolla-genpwd
# edit /etc/kolla/globals.yml (below)
kolla-ansible bootstrap-servers -i ./all-in-one
kolla-ansible prechecks -i ./all-in-one --use-test-images
kolla-ansible deploy -i ./all-in-one
pip install python-openstackclient python-heatclient -c https://releases.openstack.org/constraints/upper/2026.1
kolla-ansible post-deploy -i ./all-in-one        # writes /etc/kolla/clouds.yaml
```

Three details in these lines each fixed a failure in the 2026-10-20 trial (§9):

- `pip install docker dbus-python` puts both modules in the Kolla venv.
  `bootstrap-servers` installs `python3-docker` for the system Python, but an
  all-in-one run uses the venv's Python, and `prechecks` stops at "Checking
  docker SDK version" without the module. `dbus-python` needs
  `libdbus-glib-1-dev`.
- `--use-test-images` is needed because the images come from the
  `quay.io/openstack.kolla` namespace, which `prechecks` calls test-only.
  `deploy` takes no such flag.
- `post-deploy` needs `-i ./all-in-one`. Without it, it looks for
  `/etc/kolla/ansible/inventory/all-in-one` and stops.

The kolla venv has no Heat client. Run Heat from a separate venv that has
`python-openstackclient` and `python-heatclient`.

### 2.2 globals.yml

```yaml
kolla_base_distro: "ubuntu"                   # the example file defaults to rocky; match the host [K1]
openstack_release: "2026.1"
network_interface: "<NIC with the management IP>"
neutron_external_interface: "<NIC up with no IP: floating IPs and the external network>"
kolla_internal_vip_address: "10.0.0.10"       # this cloud's API address: an unused address on network_interface's network [K1]
nova_compute_virt_type: "kvm"                 # the default [K7]; the compute hosts need VT-x or AMD-V
neutron_plugin_agent: "openvswitch"           # the default [K2]; this cloud runs ML2/OVN, and the product runs on either
enable_heat: "yes"        # default follows enable_openstack_core [K2]; keep it on
enable_horizon: "yes"     # optional; the platform does not use it
#enable_cinder: false     # default [K2]; the project works without volumes
#cinder_volume_group: "ubuntu-vg"   # only if Cinder is on and the host's volume group is not Kolla's default, cinder-volumes (this cloud)
```

Heat, Glance, Nova, Neutron, Keystone and Placement are all part of
`enable_openstack_core`, which is true by default [K2]. Nothing else is
required. The hosts are Ubuntu 24.04 on x86_64, because every image the project
runs is amd64.

On an all-in-one cloud without HAProxy and keepalived, set `enable_haproxy:
"no"`. Set `kolla_internal_vip_address` to the IP of `network_interface` itself
[K2]. The API endpoints are then that address. Keystone is on port 5000. This is
the `identity.keystone` value in `cloud.yaml` (`http://ADDRESS:5000`).

Set `enable_proxysql: "no"` beside it. ProxySQL is enabled with MariaDB, not
with HAProxy, and it binds port 3306 on the VIP. Here the VIP is the host's own
address, so MariaDB then cannot bind its port and `deploy` fails with "Address
already in use".

### 2.3 Tap-as-a-Service (optional; dropped from the design)

We enabled TaaS on the previous cloud (ML2/OVS) on 2026-09-30 for a sensor owned
by the organiser. We then dropped that sensor (`docs/STATE.md`, "Tap-as-a-Service
is dropped from the design"). Nothing uses TaaS, and a new cloud does not need
it. The steps below are the ones we ran on the previous cloud, and they assume
the Open vSwitch agent. To enable it on 2026.1:

```yaml
enable_neutron_taas: "yes"     # defined in ansible/group_vars/all/neutron.yml, default false [K3]
```

```bash
cp /etc/kolla/globals.yml /etc/kolla/globals.yml.before-taas
kolla-ansible reconfigure -i /root/all-in-one -t neutron
```

**The 2026.1 bug.**

- kolla-ansible adds `taas` to `service_plugins` for all three Neutron API
  services.
- Its config task writes `neutron_taas.conf` only for the services in
  `services_need_neutron_taas_conf`, which are `neutron-server` and
  `neutron-openvswitch-agent` [K4].
- `neutron_rpc_server` and `neutron_periodic_worker` then exit with `No
  providers specified for 'TAAS'`, and every agent reads dead.

The fix uses kolla's per-service override. The same task merges the file
`{{ node_custom_config }}/neutron/{{ item.key }}.conf` [K4][K5]:

```bash
c=/etc/kolla/neutron-server/neutron_taas.conf
mkdir -p /etc/kolla/config/neutron
cp $c /etc/kolla/config/neutron/neutron-rpc-server.conf
cp $c /etc/kolla/config/neutron/neutron-periodic-worker.conf
kolla-ansible reconfigure -i /root/all-in-one -t neutron
openstack network agent list          # every agent Alive :-)
docker ps --filter name=neutron       # rpc_server and periodic_worker Up
```

A later reconfigure kept the override files on the previous cloud. We checked as
a member: a tap service plus a `BOTH` tap flow goes ACTIVE and `br-tap` exists. We
did not check whether upstream fixed this after 2026.1.

### 2.4 Nova: resize is off

`allow_resize_to_same_host` is `False` by default [N1]. An all-in-one cloud has
no other host, so a resize cannot be scheduled. This cloud has one compute node
(`com01`) and does not change the setting. To change a server's flavor you must
**replace** the server.

Heat's `OS::Nova::Server` applies a flavor change as a resize unless
`flavor_update_policy: REPLACE` is set [H1]. Replace the stack (delete and
create, as `bin/platform-rebuild` does). Do not update the flavor.

To allow resize instead, set `[DEFAULT] allow_resize_to_same_host = True` in
`/etc/kolla/config/nova.conf`. Then run `kolla-ansible reconfigure -t nova`
[K5][N1].

### 2.5 External network and floating IPs [admin, once]

The platform VM is reached on a floating IP. Its stack, the builders and the
image downloads leave through a router on an external network. A fresh
Kolla-Ansible cloud has none.

Kolla maps `neutron_external_interface` to the physical network `physnet1` on
`br-ex` [K8]. Run these as admin (`source /etc/kolla/admin-openrc.sh`, which
`kolla-ansible post-deploy` writes). Use the subnet, gateway and pool of the
network that interface is wired to:

```bash
openstack network create --external --provider-network-type flat --provider-physical-network physnet1 provider
openstack subnet create --network provider --no-dhcp --subnet-range 192.168.100.0/24 \
  --gateway 192.168.100.1 --allocation-pool start=192.168.100.20,end=192.168.100.99 provider-subnet
```

**(this cloud)** The `provider` network is flat. Its subnet is 192.168.2.0/24
with gateway 192.168.2.1 and the pool 192.168.2.200 to 192.168.2.250.

`provider` is `network.external` in `cloud.yaml`. The gateway must be a real
router that reaches the Internet. The pool must hold only addresses that nothing
else on that network uses. Each floating IP and the gateway address of each
tenant router come from the pool.

### 2.6 Internet egress

The router gives the project's networks source NAT to the Internet. DNS is
`network.dns`. The hosts below must be reachable through it. If you filter with
an allowlist, also allow the hosts the registries redirect to.

| Who | Reaches | For |
|---|---|---|
| platform VM (cloud-init, `fsl-platform.service`) | the Ubuntu archive; github.com; ghcr.io; docker.elastic.co; Docker Hub; geoip.elastic.co | `apt` (Docker, git, chrony); `git clone` of `platform.repository`; the seven `fsl-*` images; Elasticsearch, Kibana and Filebeat; the pinned WAF, Suricata and MySQL images; `bin/fetch-geoip` |
| the Kali builder | the Ubuntu archive; github.com | the tools; ttyd |
| the WAF builder | the Ubuntu archive; github.com; nginx.org | ModSecurity, its nginx connector and the Core Rule Set; the nginx source |
| the wargame host builder | the Ubuntu archive; ghcr.io; Docker Hub | Docker; the wargames' images |
| the edge builder | the Ubuntu archive; `opnsense.mirror` (pkg.opnsense.org) | QEMU and its tools; the OPNsense release |
| the operator machine | the cloud's API; the floating IP; github.com; ghcr.io | `bin/cloud`; the check that the images can be pulled |

The range's own VMs (edge, Kali, WAF, wargame host) have no Internet. The
builders above put everything those VMs run into their images.

## 3. Project, user, quotas, flavors, keys, groups, images

### 3.1 Project and user [admin, once]

```bash
openstack project create fsl-range
openstack user create --project fsl-range --password-prompt fsl-range
openstack role add --project fsl-range --user fsl-range member
```

**(this cloud)** The project and the user sit in the domain `fsl` (id
`c72af53edecb4e31a5645fdd9a07f0f9`), so the commands above also take `--domain
fsl`, and `identity.domain` in `cloud.yaml` is that id. The project `fsl-range`
has the id `3c82e428f6cc4997949a89f5fdee68c7`. The user `fsl-range` is a member
of it. The platform signs in as this member user, never as admin.

### 3.2 Quotas [admin, once]

The platform VM and one slot need 10 vCPU, 24 GB RAM, 5 instances and 1
floating IP.

- The platform VM is 2 vCPU, 8 GB RAM and 60 GB disk (`m1.large`).
- Each of the slot's four VMs (edge, Kali, WAF, wargame host) is 2 vCPU, 4 GB
  RAM and 30 GB disk (`m1.medium`, §3.3).

Nova's default quotas (20 cores, 51200 MB of RAM, 10 instances) and Neutron's
default network quotas already cover this. A new cloud sets none. The image
builders never add to the quota. They use the same `m1.medium` and are deleted
before the slot boots.

Nova has no per-project disk quota. The 180 GB of flavor disk (60 + 4 x 30) is
space that the compute node's instance storage must have, at a disk allocation
ratio of 1.0 [N2].

Each further slot adds 8 vCPU, 16 GB RAM, 120 GB disk and 4 instances. Then you
must raise the quota.

**(this cloud)** These are the figures:

- The quota is 20 cores, 51200 MB of RAM and 10 instances.
- The project also holds a VM that the user owns, `FSL-front` (flavor
  `dba.medium`, 4 vCPU and 8 GB, floating IP 192.168.2.241, on its own network
  `fsl-net` 172.16.10.0/24 and router `fsl-router`). It uses 4 cores and 8 GB of
  the quota.
- The platform VM (2 cores, 8 GB) and one slot (8 cores, 16 GB) bring the project
  to 14 cores, 32 GB and 6 instances. A second slot would need 22 cores, which is
  over the quota of 20. So `compute.slots` is 1 here.
- Each slot beyond the first adds 2 networks (`fsl-internet-N`, `fsl-estate-N`),
  31 subnets, 9 ports and 3 collector rules in `fsl-reach`. On the previous cloud
  with two slots we measured networks 6/100, subnets 64/100, ports 25/500,
  security group rules 26/100 and security groups 6/10.
- The stack also needs 1 network, 1 router and 1 floating IP. Image storage is
  needed for 4 golden images.
- Image builders (one per built host, 2 cores each on `m1.medium`) boot only as
  many at once as the quota leaves room for. The platform checks this with Nova
  `GET /limits` against the builder flavor. When there is room for one builder,
  the next boots after the first is deleted. So you repeat
  `POST /api/range/images/` until it is clean, and it builds the images one at a
  time.
- If there is no room and no builder is working, `images/` answers 503 and names
  the fix: delete a slot (`DELETE /api/range/slot/?slot=N`) or raise the quota.

```bash
openstack quota show fsl-range
openstack quota set --cores 24 --ram 65536 --instances 12 fsl-range   # example
```

### 3.3 Flavors [admin, once]

A member user cannot create flavors. `compute.flavors` in `cloud.yaml` names
them:

| Key | Use | Notes |
|---|---|---|
| `platform` | platform VM | 8 GB RAM or more. With 4 GB, the OOM killer once killed Elasticsearch when sessions stacked up (DECISIONS 2026-10-10). Example `m1.large` (8 GB / 2 vCPU / 60 GB) |
| `builder` | image builders | The OPNsense builder holds the 3 GB raw image, its qcow2 and a 2 GB QEMU guest. It needs 4 GB RAM and 20 GB disk or more (`m1.medium`) |
| `range` | every slot VM that no role key names | The disk must be at least the `builder` flavor's disk, because a golden image's minimum disk is its builder's disk (30 GB with `m1.medium`) |
| `edge` (required), or any other role name | the host that fills that role | The edge is required. OPNsense needs 3 GB RAM or more (its image says `min_ram` 3072), so the `range` flavor would fail at boot |
| `wargames` (optional) | `fsl-wargame-host` | It runs two MySQL 8, Django and WordPress containers at once. The example names `m1.medium` (4 GB). Without this key the host takes `range`. We did not measure its memory use |

**(this cloud)** The admin made two flavors: `m1.large` (8 GB / 2 vCPU / 60 GB)
and `m1.medium` (4 GB / 2 vCPU / 30 GB). `cloud.yaml` names `m1.large` for
`platform` and `m1.medium` for `builder`, `range`, `edge` and `wargames`. Check
that every flavor `cloud.yaml` names exists on your cloud. The platform refuses a
missing flavor and names it.

```bash
openstack flavor create --ram 8192 --vcpus 2 --disk 60 m1.large
openstack flavor create --ram 4096 --vcpus 2 --disk 30 m1.medium
```

A new cloud makes these two flavors, and `cloud.example.yaml` names them.

### 3.4 Keypairs

- `fsl-claude` is the operator's key that the platform VM boots with. It is the
  stack parameter `key_name` and `keys.operator` in `cloud.yaml`. Make the key,
  then create the keypair as `fsl-range` before the stack. Use the sign-in
  variables from `README.md` step 6:
  `ssh-keygen -t ed25519 -N "" -f ~/.ssh/fsl_claude` and
  `openstack keypair create --public-key ~/.ssh/fsl_claude.pub fsl-claude`
- `fsl-platform` is the platform's own range key. `POST /api/range/fabric/`
  imports it from `/data/ssh/id_ed25519` in the platform container. Never create
  this keypair by hand. The key file it comes from (`keys.range`) needs no step
  either. The first `bin/cloud up` on a cloud with no stack makes the file if it
  is missing. §6.3 covers a mismatch between the two.

### 3.5 Security groups

| Group | Made by | Rules |
|---|---|---|
| `fsl-platform` | Heat stack | tcp 22, tcp 8000, tcp 8002, tcp 3080, icmp in |
| `fsl-range` | fabric | all IPv4 in; on every range port except `mgmt` (anti-spoofing stays on) |
| `fsl-reach` | fabric | nothing in except udp 123 (NTP) from members of `fsl-mgmt`, then udp 5140 from exactly the edge, the WAF and the wargame host (`configure/`) |
| `fsl-mgmt` | fabric | all IPv4 in, only from members of `fsl-reach` (the platform's `mgmt` port); applied on every range host's `mgmt` port, so Kali's `mgmt` port reaches no one |
| `fsl-build` | images step | tcp 8080 from the platform's address only (§3.6); `bin/cloud down` leaves it |

Port 8002 is the blue console's Website pane. The platform sends each request
over an ssh stream to the slot's Kali (over `mgmt`). Kali sends it from a
customers address through the edge to the WAF (`docs/ARCHITECTURE.md`, the
Website pane's egress). A platform stack made before 2026-10-13 lacks the rule. Add it by hand:

```bash
openstack security group rule create --protocol tcp --dst-port 8002 fsl-platform
```

The range has no Internet, so the platform is its only time source.

- The platform VM runs chrony. cloud-init sets `allow <network.mgmt>` and `local
  stratum 10`, so the platform keeps serving its own clock if it loses its
  upstream time source.
- Every range host takes its time from the platform's `mgmt` address.
- The Ubuntu hosts (Kali, the WAF, the wargame host) get a `systemd-timesyncd`
  drop-in (`/etc/systemd/timesyncd.conf.d/60-fsl.conf`, `NTP=<platform mgmt>`) at
  every configure and reset. The step waits for the first answer.
- The edge's rendered `config.xml` names the platform in `system/timeservers`,
  with ntpd bound to `opt1`.
- A rebuilt platform VM has a new `mgmt` address. The hosts take it at the next
  reset or `configure/`.
- A range made before 2026-10-15 gets the udp 123 rule at the next `bin/cloud up`
  (`POST /api/range/fabric/` plans it as `ntp`).
- A platform VM booted before 2026-10-15 lacks chrony. Run what cloud-init runs:

```bash
sudo install -d /etc/chrony/conf.d
printf 'allow 10.31.0.0/24\nlocal stratum 10\n' | sudo tee /etc/chrony/conf.d/fsl-range.conf
sudo apt-get -y install chrony
```

Port 3080 is the GNS3 server (`compose.yaml` `gns3`). The blue console's Map
pane shows its web UI in a frame. A platform stack made before P1 of the
scenario course lacks the rule. Add it by hand:

```bash
openstack security group rule create --protocol tcp --dst-port 3080 fsl-platform
```

### 3.6 Images

The cloud holds exactly one image that you upload by hand: Canonical's Ubuntu
24.04 cloud image, unmodified. Nothing is baked into it. cloud-init installs or
writes every package, tool, key and setting at boot (the platform VM, the
builders). The platform does the rest over ssh (`configure/`).

| Image | How it gets there | One-click |
|---|---|---|
| `compute.base_image` (e.g. `ubuntu-24.04`) | the stock `noble-server-cloudimg-amd64.img`, checksum verified, uploaded as is (below) | by hand, once |
| `fsl-waf`, `fsl-kali` | golden images, built by the platform on builders booted from the base image (§6) | yes |
| `fsl-wargame-host` | built the same way. It holds Docker and every wargame's GHCR images at the platform's tag (below) | yes |
| `fsl-opnsense-<version>` | built by the platform on a builder booted from the base image, from the official OPNsense nano image (below) | yes |

Upload the base image as admin with `--public`, on a machine that has the
openstack CLI.

- `SHA256SUMS` lists one line per file of that build. `--ignore-missing` checks
  only the file you downloaded [U1].
- Without `--public`, an admin's image belongs to the admin project and
  `fsl-range` does not see it. The stack then fails on its `image`, and the
  platform finds none.
- As `fsl-range`, signed in as in `README.md` step 6, the same command without
  `--public` works, because the image then belongs to the project.

```bash
curl -fLO https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
curl -fLO https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
sha256sum --ignore-missing -c SHA256SUMS
openstack image create --public --disk-format qcow2 --container-format bare \
  --file noble-server-cloudimg-amd64.img ubuntu-24.04
```

The `.img` file is a qcow2 disk. `SHA256SUMS.gpg` beside it signs the list. To
check the signature as well, import Ubuntu's cloud-image signing key and compare
its fingerprint with the one Ubuntu publishes. Then run `gpg --verify
SHA256SUMS.gpg SHA256SUMS`.

The name you give the image is `compute.base_image`. The platform refuses to
build while the cloud holds none, or more than one active image, of that name.
**(this cloud)** The admin uploaded `ubuntu-24.04` and made it public. It is the
only image uploaded by hand.

`fsl-kali` used to need a second uploaded image (`kali-rolling`). It is now built
on Ubuntu. Its setup enables the `universe` and `multiverse` components itself
and installs the tools from the Ubuntu archive. The `wordlists` package exists
only on Kali. The motd's list is dirb's, linked to the old path.

**The wargame host [one-click].** No wargame has an image of its own. There are
always five images (base, `fsl-opnsense-<version>`, `fsl-waf`, `fsl-kali`,
`fsl-wargame-host`), however many wargames there are.

`fsl-wargame-host` declares `wargames: [board, corp]` and `publish: {board:
8000, corp-wp: 80}`. Its bundle (the files the builder gets in its user data)
holds `deploy/wargame-host/setup.sh` and files the platform generates:

- One `compose.yaml` per wargame (two today), rendered for the host: no
  `build:`, no session network, `container_name` set to the service name,
  `${FSL_IMAGE_TAG}` replaced by the platform's tag, and the published ports
  added.
- `daemon.json` with the tenant MTU (`network.mtu`), as on the platform VM.

The setup does the following while the builder still has the Internet. The
range has none.

1. It enables `universe` and installs `docker.io` and `docker-compose-v2`.
2. It installs the files under `/opt/fsl/wargames/`.
3. It runs `docker compose pull` on each wargame.

The images are the ones the wargames' compose files name
(`ghcr.io/nekonic/fsl-board`, `fsl-corp`, `fsl-corp-db`, the pinned `mysql`).
They must be public and exist for the tag. The tag is `FSL_IMAGE_TAG`, the
commit of the platform checkout, taken from `/opt/fsl/.env`.

The tag is part of the bundle's digest, so a platform on a new commit plans a
new host image. A tag that moves (`dev`) does not change the digest. In that
case, delete the image to rebuild it.

Every bundle digest hashes each file's name, its content and its mode. The mode
is only the executable bit, 0755 or 0644, as git tracks it. A checkout's umask
therefore does not change a digest: a sideloaded checkout (files 0664) and a
cloud-init clone (files 0644) of one commit plan the same image. Every digest
changed once, when this rule began (2026-10-20).

A wargame image sideloaded onto the platform (§5.3) is not on GHCR. The bundle
then also holds a generated `loaded` file. It has one line per image:
`<image> <image id> <name>`, so the id is part of the digest. The platform's
address goes in a second file, `served-from`. The bundle packs it for the
builder and leaves it out of the digest, so a new fixed IP for the platform
does not rebuild the image. After the pulls, the setup does this for each such
image:

1. It fetches the image from the platform with
   `GET /api/range/images/sideloaded/<name>/` (the base URL is in `served-from`)
   and `Host: localhost`, which Django's allowed hosts accept. The reply is a `docker save` stream. The setup
   retries 5 times.
2. It runs `docker load` on it.
3. It refuses the image unless its id equals the platform's.
4. It prunes the GHCR copy.

The builder reaches the platform's port 8000 on the build network
(`fsl-platform` security group, `FSL_PUBLISH` is the fixed IP).

**The OPNsense image [one-click].** `fsl-edge` declares `setup:
deploy/opnsense/build.sh` and `uploads: opnsense`. On `POST /api/range/images/`
the platform boots a builder from the base image. The builder gets the bundle in
its user data and no credential.

The builder runs in the security group `fsl-build`, which the images step makes
if it is absent. Its only ingress rule is tcp 8080 from the platform's address
on the platform network. The rule is replaced when that address changes. The
builder keeps Neutron's default egress.

The builder does these steps:

1. It installs `curl`, `bzip2`, `openssl`, `qemu-utils`, `qemu-system-x86`,
   `dosfstools`, `mtools`, `fdisk` and `python3`. It assumes nothing about the
   image.
2. It downloads `OPNsense-<version>-nano-amd64.img.bz2`, its `.sig` and
   `OPNsense-<version>.pub` from `opnsense.mirror`/`<version>/`.
3. It checks the archive against `opnsense.image_sha256`. It checks the SHA256
   of the key's DER form against `opnsense.pubkey_sha256`. Copy both values from
   the release announcement [O3], not from the mirror, as the manual advises
   [O1].
4. It unpacks the archive. It verifies the signature on the unpacked image
   (`openssl base64 -d`, `openssl dgst -sha256 -verify`) [O1].
5. It boots the image once under QEMU. QEMU uses KVM when the builder has it and
   TCG otherwise. The guest has three virtio NICs and a FAT seed disk that holds
   `conf/config.xml`. The builder presses a key at the configuration importer's
   prompt and names the seed disk (`vtbd1`) [O4]. It waits for `login:` and
   powers the guest off over the QEMU monitor (`deploy/opnsense/importer.py`).
6. It converts the disk with `qemu-img convert -O qcow2 -c` to
   `/var/lib/fsl-serve/disk.qcow2`. It serves that file with `python3 -m
   http.server 8080` as the transient unit `fsl-serve`. It prints a ready line
   with the disk's SHA256 on its console.
7. The platform reads that line through Nova and pulls the disk over the
   platform network. It refuses the disk if the SHA256 differs. It then creates
   the Glance record `fsl-opnsense-<version>` (qcow2, bare, private,
   `hw_vif_model=virtio`, `hw_disk_bus=virtio`, `os_distro=freebsd`, `min_ram`
   3072, `fsl_bundle`) and uploads the file with `PUT`, using its own fresh token
   [G3]. When Glance says the image is active, the platform deletes the builder.
   If an upload was interrupted and left a record `queued`, the next call fills
   it.

The nano image is a preinstalled serial-console disk. Its `/conf/config.xml` is
created from the default on first boot. That default assigns only LAN (static
192.168.1.1/24) and WAN. The third NIC, mgmt, would get no address, and the
platform could not reach a new edge. The importer step lets the image start from
our config without anyone at its console.

The image's config (`deploy/opnsense/config.xml`, rendered with the MTU and the
platform's public key) sets these:

- Root has no password (`*`) and accepts only the platform's key.
- sshd allows no password logins.
- opt1 (mgmt) gets its address by DHCP.

The stock default password `opnsense` never exists on this image.

The bundle digest covers the release settings, the MTU, the platform key and the
scripts. If any of them changes, the platform builds a new image. A new version
also gets a new name.

An `fsl-opnsense-*` image of a release that `cloud.yaml` no longer names is
listed as unused. `DELETE /api/range/images/` removes it, and so does `bin/cloud
up` once the range is ready on the new images. It is removed only if both
conditions hold: it carries `fsl_bundle`, which marks an image this platform
made, and no server in the project boots from it. Any other image of that name
is left alone.

We ran this on the previous cloud on 2026-10-11 with 26.7:

- The archive SHA256 matched.
- The `.sig` verified ("Verified OK") over the unpacked image.
- The importer's console strings appeared as read from the source [O4].
- The builder went from boot through import to power-off in about a minute.
- `fsl-serve` served the disk.
- The Glance image went active with the properties above.

**Licence (researched 2026-10-11, not legal advice).**

- OPNsense is BSD 2-clause, "Copyright © 2025 by Deciso B.V.", and is based on
  FreeBSD [O2].
- Its trademark policy lets the name be used "to promote OPNsense based
  products". It asks for permission at project@opnsense.org before you use a
  derivative of the name [O2].
- This project builds the image from the official release on each cloud and does
  not publish it.
- Describing the range as "based on OPNsense" is within the policy. Naming the
  image anything like "FSL-OPNsense" in public is not, without permission.
- The image's Glance name stays private to the project.

## 4. cloud.yaml

`deploy/openstack/cloud.example.yaml` is committed. Copy it to
`deploy/openstack/cloud.yaml` (git ignores that file) and fill it in. No secret
goes in it, only where to read the password. `platform/range/cloud.py` reads the
file. It refuses the file before touching anything and names every problem by
its dotted key. The problems it finds include an unknown key, a missing key, a
Keystone URL that ends in `/v3`, an unquoted version, overlapping CIDRs and a
password written into the file.

| Key | Example | Used by |
|---|---|---|
| `identity.keystone` | `http://10.0.0.10:5000` | Keystone base URL without `/v3`; CLI and platform |
| `identity.region`, `identity.interface` | `RegionOne`, `public` | the catalogue endpoints the CLI and the platform call |
| `identity.domain` | `default` (**(this cloud)** `c72af53edecb4e31a5645fdd9a07f0f9`, the domain `fsl`) | the id of the user's and the project's domain |
| `identity.project`, `identity.user` | `fsl-range` | the member user the CLI and the platform sign in as |
| `identity.password_file` or `identity.password_env` | `~/.config/fsl/fsl-range.password` | set exactly one; read on the operator's machine and appended to the VM's `openstack.env` over ssh |
| `network.external` | `provider` | the stack's router and floating IP |
| `network.address` | `""` (**(this cloud)** `192.168.2.247`) | optional; a floating IP the project already holds. The stack associates it and never releases it, so the address survives `bin/cloud down` and every rebuild. If empty, the stack allocates a new one (§5.1) |
| `network.dns` | `[8.8.8.8, 8.8.4.4]` | the platform network's DNS |
| `network.mtu` | `1450` (**(this cloud)** `1442`) | the edge's interfaces (the tenant networks' MTU; 1450 on VXLAN with ML2/OVS, 1442 on Geneve with ML2/OVN, §2) |
| `network.platform`, `.estate`, `.mgmt` | `10.20.0.0/24`, `10.30.0.0/24`, `10.31.0.0/24` | The ranges must be private and must not overlap. They must also stay outside Docker's default local address pools (172.17.0.0/16 to 172.31.0.0/16 and 192.168.0.0/16, moby `daemon/libnetwork/ipamutils/utils.go`), `compose.yaml`'s networks and the declared origins |
| `compute.base_image` | `ubuntu-24.04` | the platform VM and every builder |
| `compute.availability_zone` | `""` | the platform VM, builders and slot VMs; if empty, Nova chooses |
| `compute.flavors` | `platform`, `builder`, `range`, `edge` (required, 3 GB RAM or more), per role | §3.3 |
| `compute.slots` | `1` (**(this cloud)** `1`, because the quota has room for one, §3.2) | optional; how many copies of the range stand, which is how many sessions can run at once (§6.4); `FSL_OPENSTACK_SLOTS` |
| `keys.operator`, `keys.operator_file` | `fsl-claude`, `~/.ssh/fsl_claude` | the keypair the platform VM boots with, and its private half |
| `keys.range` | `~/.ssh/fsl-platform` | the platform's range key, kept across rebuilds |
| `opnsense.version`, `.mirror` | `"26.7"`, `https://pkg.opnsense.org/releases` | the image release (released in January and July; updates have no images [O1]) |
| `opnsense.image_sha256`, `.pubkey_sha256` | from the release announcement [O3] | §3.6 |
| `platform.stack`, `.repository`, `.ref` | `fsl-platform`, this repo, `dev` | the stack, and the checkout it clones |
| `backups.keep` | `1` | optional; how many store backups `backups/` keeps after a rebuild or `down`, counting the new one (`bin/backup --keep`). Without it, one |

Where each value goes:

- `bin/platform-rebuild` and `bin/cloud` set the openstack CLI's `OS_*`
  variables from `identity`, so no openrc file is needed.
- They pass every Heat parameter from the file (`Cloud.heat_parameters()`).
- The template has no defaults. It writes the values into
  `/opt/fsl/openstack.env` as `FSL_OPENSTACK_*` and `FSL_OPNSENSE`.
- The platform reads those variables (`settings.py`). If one it needs is
  missing, it refuses and names the variable.

## 5. The platform VM

### 5.1 The Heat stack

`deploy/openstack/platform.yaml` creates:

- the network `fsl-platform` (`network.platform`)
- a router to `network.external`
- the group `fsl-platform`
- a port
- a floating IP
- a server from `compute.base_image`

The server's cloud-init does these steps:

1. Installs Docker.
2. Sets Docker's MTU to the network's MTU.
3. Adds 4 GB of swap.
4. Clones `repository` at `ref` into `/opt/fsl`.
5. Writes `/opt/fsl/openstack.env`. It holds every cloud value except the
   password, and `FSL_TOOL_IMAGE=fsl-kali`, the attacker host the launcher runs
   tools on.
6. Writes `/opt/fsl/.env` with `FSL_PUBLISH=<fixed IP>` and
   `FSL_SYSLOG_PUBLISH=0.0.0.0`.
7. Enables `fsl-platform.service`.

When `network.address` is set, `bin/platform-rebuild` does this before it
deletes anything:

1. It looks the floating IP up by address (`openstack floating ip list
   --floating-ip-address`).
2. It refuses to go on if the project holds no such floating IP.
3. It passes the floating IP's id as `floating_ip_id`.

The stack then creates an `OS::Neutron::FloatingIPAssociation` instead of an
`OS::Neutron::FloatingIP`. Deleting the association only sets the floating IP's
`port_id` to null (Heat `neutron/floatingip.py`,
`FloatingIPAssociation.handle_delete`). The address stays in the project.

Neutron's default policy lets only an admin choose the address, so the floating
IP is created once, as admin. **(this cloud)** `openstack floating ip create
--project fsl-range --floating-ip-address 192.168.2.247 provider`.

`FSL_PUBLISH` is the VM's fixed IP. Port 8000 therefore listens on that address,
not on loopback, and the floating IP NATs to it. Setting `FSL_PUBLISH=0.0.0.0` on
a VM is an environment error (DECISIONS 2026-10-10).

The password stays out of Heat and out of user data. Nova's metadata service
answers inside the containers on the VM, so anything in user data can be read
there.

### 5.2 One command [one-click]

Run this from the operator's machine. `python-openstackclient` and
`python-heatclient` must be installed in the repo's `.venv`, which has PyYAML.
The scripts find the `openstack` command beside `.venv/bin/python`.

```bash
.venv/bin/python bin/cloud up            # --replace to replace a standing platform; --cloud, --ref, --sideload as in §5.3
.venv/bin/python bin/cloud down
```

`up` does these steps in order:

1. It refuses to run without a usable `cloud.yaml`.
2. It reads the stack's status. It refuses while the status is `*_IN_PROGRESS`.
3. If the stack is absent, it creates it. If the stack is `*_FAILED`, it deletes
   the builders and the stack (`--wait`) and creates the stack again.
   (`--replace` replaces a working stack through `bin/platform-rebuild`, below.)
4. It asks the VM over ssh whether it took its hand-over, whether or not the API
   answers, and then waits for the API. A container can answer before the
   password line is written, and a range build on it would fail. The hand-over
   is the step that gives a new VM the password, the range key and the store
   (§5.3). A VM never took it when `/opt/fsl/openstack.env` has no
   `FSL_OPENSTACK_PASSWORD`. In that case `up` does the hand-over first. If the
   `fsl-platform` container is stopped, `up` starts it first, because the key is
   written into that container. The redone hand-over keeps every other line of
   `openstack.env`, `FSL_SIDELOADED` included. `up` refuses a `--sideload` here,
   because it applies only to a new VM.
5. It sends `POST fabric/`. It stops on drift (a resource that exists but
   differs from what the platform would create).
6. It sends `POST images/` until every image is ready and no builder is left. It
   stops on a failed image or an image that no script builds.
7. It sends `POST slot/`. It stops when the slot is blocked.
8. It sends `GET ready/` until the slot leaves `NOT_STANDING` and `REBUILDING`.
9. It sends `POST configure/`. It retries while the answer is 503, which means
   the VMs' ssh is not up yet. It stops on 409.
10. It sends `GET ready/` until the range is ready.
11. It sends `DELETE images/`, which removes unused images that no server boots
    from.

`down` does these steps:

1. It asks the VM over ssh whether a running `fsl-platform` container or a store
   file exists. The store file is `db.sqlite3` in the `fsl_platformdata` volume.
2. If neither exists, as after a first boot that never started the platform,
   there is nothing to back up and no platform to ask. `down` then deletes only
   the builders and the stack.
3. If ssh does not answer, or Docker does not, `down` cannot tell. It refuses and
   deletes nothing.
4. If a store file exists beside a stopped platform container, `down` starts the
   container, because the backup runs through `docker exec`. It refuses, and
   deletes nothing, when the container does not start.
5. It keeps the range key and backs up the store (`bin/backup --keep`,
   `backups.keep`).
6. It waits for the API. Then it runs `DELETE slot/` and `DELETE fabric/`.
7. It deletes every server whose name starts with `fsl-build-`, which carries the
   `fsl_image` property and which has a port on this stack's own network (the
   stack's `network` resource). Such a port would make the stack delete fail.
8. It deletes the stack. Glance keeps the images.

A `*_FAILED` stack has no platform to ask. For it, `down` deletes the builders
and the stack only.

We ran `down` on 2026-10-11. It took 26 s. It left no stack, builder, range
network, port, router or range security group. It kept the Glance images, the
reserved floating IP, the `fsl-claude` keypair and the `fsl-build` group.

On 2026-10-20 a `down` beside a stopped container took 40 s and wrote a backup
of 430,080 bytes that passed `PRAGMA integrity_check`. An `up` after `down`
restores the newest backup that holds rows (§5.3).

If a stack is not `*_FAILED` but its `address` output cannot be read, `up` and
`down` refuse and delete nothing.

### 5.3 Rebuild and delete — lossless

```bash
.venv/bin/python bin/platform-rebuild    # --cloud PATH, --ref REF, --sideload NAME=TARBALL
```

This command replaces the platform VM without losing data. It does these steps:

1. It refuses unless every platform image for the ref's commit is public on GHCR.
2. It keeps the range key (`keys.range`), which it takes once from the running
   platform.
3. It backs up the store with `bin/backup`. If the old VM holds a store but its
   `fsl-platform` container is stopped, it starts the container first. If the old
   VM has neither a running `fsl-platform` container nor a store file, it says so,
   skips the backup and makes the range key if it is missing. If ssh to the old VM
   does not answer, it refuses.
4. It deletes and recreates the stack.
5. It starts the `fsl-platform` container on the new VM if it is stopped, then
   writes the kept key to `/data/ssh/id_ed25519` through `docker exec`.
6. It restores the store.
7. It rewrites the password line in `/opt/fsl/openstack.env`, and the
   `FSL_SIDELOADED` line when the run sideloads. It keeps every other line, and
   the file keeps mode 0600.
8. It waits for `/api/sessions/`.

The password line marks a finished hand-over, so it is written after the store
is in place.

There may be no store to carry over: there may be no stack, the stack may have
failed, or the VM may hold none. The backup just taken may also hold no rows. In
these cases the command restores the newest `backups/db-<UTC time>.sqlite3` that
holds rows, and names it. If there is none, the platform starts empty and says
so. The hand-over that `up` redoes (§5.2) does the same when the VM holds no
store.

Because the key is carried over, the fabric's `fsl-platform` keypair stays valid.
You do not need to tear the slot down.

`bin/backup` works like this:

- It writes a compacted copy of the store into a temporary file inside the
  platform container, using SQLite's `VACUUM INTO`. It streams the copy over ssh
  in 1 MiB chunks. It gives up only after 600 s with no data.
- When the copy passes `integrity_check`, it removes older
  `backups/db-<UTC time>.sqlite3` files beyond `--keep` (default 1, counting the
  new one). If the store held no rows, as a new VM's does, it removes none. It
  never removes a file with any other name.
- `bin/platform-rebuild` and `bin/cloud down` pass `backups.keep` from
  `cloud.yaml` as `--keep`.
- The new VM holds one copy in `/opt/fsl/backups`, the one it was restored from.

The store stays small. The platform deletes sessions that were closed more than
`FSL_RETAIN_CLOSED_MINUTES` ago, with their records. The default is 60
(`platform/fsl/settings.py`, set in `compose.yaml`, overridden in
`/opt/fsl/.env`). It does this at start and after every close, 2,000 rows per
transaction (`platform/api/retention.py`). It never touches open sessions. A
backup therefore carries about an hour of closed sessions plus the open ones.
The store is copied back with `scp` and put in place while the platform is
stopped.

**An unpushed commit (`--sideload NAME=TARBALL`).** Sideloading means loading a
Docker image from a tarball instead of pulling it from GHCR. Both
`bin/platform-rebuild` and `bin/cloud up` take the flag, once per image.

1. The VM clones `platform.ref`, a pushed commit whose images GHCR has. It
   starts that commit as usual.
2. The rebuild copies this checkout's HEAD as a git bundle and checks it out in
   `/opt/fsl`.
3. It runs `docker load` on each tarball and tags the image with the cloned
   commit (`FSL_IMAGE_TAG` in `/opt/fsl/.env`).
4. It stops the platform for the restore.
5. It recreates every service with `docker compose up -d --force-recreate`.
   HEAD's compose file may add services. A file bind-mounted into a running
   container, such as `filebeat.yml`, keeps the cloned commit's copy until the
   container is recreated.

`FSL_IMAGE_TAG` stays the cloned commit. The range's image builders pull the
wargames' images from GHCR at that tag. A tag that GHCR does not have would make
the `fsl-wargame-host` build fail.

A sideloaded wargame image (`board`, `corp`, `corp-db`) reaches the range from
the platform instead:

1. The rebuild writes `FSL_SIDELOADED=<names>` beside the password in
   `/opt/fsl/openstack.env`. A later rebuild without `--sideload` makes a VM
   without it. A hand-over that `up` redoes on a standing VM keeps the line.
2. The platform adds the image's id to the `fsl-wargame-host` bundle. The
   platform's address is not part of its digest, so a `down` then `up` that
   gives the platform a new fixed IP does not rebuild the image (live,
   2026-10-20: every image was ready on the first plan).
3. The builder pulls GHCR's copy at the cloned tag. It then loads the sideloaded
   one from `GET /api/range/images/sideloaded/<name>/`
   (`platform/api/sideloaded.py`, §3.6).

A new board is therefore a new `fsl-wargame-host` image. It is built when the
range's images are next planned. `bin/cloud up` does that, and it takes about 4
to 5 minutes.

A slot that was already up keeps the wargame host it booted, with the old board,
because a close resets that host in place (§6.1). When no session is open,
rebuild every slot and configure it again:

```bash
P=http://ADDRESS:8000/api/range
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/slot/rebuild/
curl -s $P/ready/          # until no slot is REBUILDING
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/configure/   # retry on 503 until ssh is up
curl -s $P/ready/          # every slot READY
```

This is still open: the reset does not yet notice that a wargame host booted from
an image other than the ready one. Until it does, a deploy that changes a
wargame image needs the slot rebuild above (`docs/DECISIONS.md` 2026-10-18,
"Foundations rebuilt as integrated attack and defence lessons"). To see the
sideloaded names, run `sudo docker exec fsl-platform env | grep FSL_SIDELOADED`
on the VM.

Before it deletes anything, the command refuses in these cases:

- an unknown name
- a name given twice
- a missing tarball
- a tarball that does not hold exactly one `ghcr.io/nekonic/fsl-NAME:<commit>`
- an image whose build context in `.github/workflows/images.yml` differs between
  the commit it was built from and HEAD. The built-from commit is the tarball's
  tag, or the cloned commit for an image that is pulled.

Build a tarball on any x86_64 Docker host from a clean export of the commit:

```bash
git archive $C platform | tar -x -C ctx
docker build --platform linux/amd64 -t ghcr.io/nekonic/fsl-platform:$C ctx/platform
docker save -o fsl-platform-$C.tar ghcr.io/nekonic/fsl-platform:$C
.venv/bin/python bin/cloud up --replace --sideload platform=fsl-platform-$C.tar
```

A changed board goes the same way (`git archive $C wargames/board/app`, `docker
build ... ctx/wargames/board/app`, `--sideload board=fsl-board-$C.tar`). The
refusal names every image whose build context differs from HEAD.

A sideloaded VM that reboots runs `fsl-platform.service` again. Its `compose
pull` can replace the sideloaded images with GHCR's for the same tag. Push and
rebuild instead of rebooting it. MicroK8s calls importing images from `.tar`
archives without a registry "Image side-loading"
(https://canonical.com/microk8s/docs/sideload).

**Runs 2026-10-15.** We ran `bin/cloud up --replace --sideload platform=...
--sideload gns3=...` over `dev` = 8f9acb0, untouched. Both runs exited 0. Both
slots were READY and no session was open before each run.

- Run 1 ran HEAD d20b35e from the previous platform VM.
- Run 2 ran HEAD 412e379 (the backup fix that run 1's `bin/verify` found) from
  run 1's VM.
- The platform image was built from each HEAD. The gns3 image was built from
  1814e5c, whose `deploy/gns3` is the same.

| Stage | Run 1 | Run 2 | Evidence |
|---|---|---|---|
| Refusal checks, GHCR, bundle | 15 s | 13 s | 5 images public at 8f9acb0; contexts equal |
| Backup (`bin/backup` over ssh) | 12 min 8 s | 7 min 50 s | 5,957,828,608 bytes, integrity_check ok; 1,878,072 detections |
| Stack delete, create | 10 s, 23 s | 10 s, 22 s | reserved floating IP re-associated |
| Server created to ssh | 21 s | about 20 s | |
| cloud-init, `fsl-platform.service` at 8f9acb0 | 2 min | 2 min | done, no errors; `python3-venv` 3.12.3, `nodejs` 18.19.1; `/etc/sysctl.d/90-fsl-syslog.conf` applied (`net.core.rmem_max = 33554432`) |
| HEAD bundle, two tarballs loaded | 2 min 29 s | 1 min 4 s | 111 MB and 241 MB; the containers run images labelled with HEAD and 1814e5c |
| Password, range key | 1 s | 1 s | key fingerprint unchanged |
| Store upload (`scp`) | 30 min 41 s | 14 min 39 s | 3.1 and 6.8 MB/s |
| Restore, `compose up -d`, API | 1 min 3 s | 1 min 4 s | migrate: no migrations to apply (the store was already at 0026); 0020-0026 `[X]` |
| Fabric, images, slot, configure, ready | 5 min 14 s | 46 s | no drift; run 1 rebuilt `fsl-wargame-host` for the new tag (3 min 43 s); both slots READY on the same servers |
| Total | 54 min 33 s | 28 min 18 s | |

Security group `fsl-platform`: 22, 8000, 8002, 3080 and ICMP. After each run a
board session (497, 514) opened in about 5 s. Its map pane (now Map) drew the
learner map from `fsl-gns3` with every link end green. Its close reset the slot
to READY within 2 minutes. The old VM's Elasticsearch data does not move. Only
the store does.

## 6. The range (substrate openstack)

Everything goes through the platform's API, as `fsl-range`.

- Each `GET` reads the plan: what is missing, present, drifted or unused.
- `POST` makes the cloud match the plan.
- `DELETE` tears down.

`bin/cloud up` runs these calls in order. By hand:

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

- The platform finds networks by the tag `fsl.segment.id=<segment>`, not by
  name. The fabric needs the Neutron `standard-attr-tag` extension, which is on
  by default.
- Image builds need `FSL_OPENSTACK_BUILD_NETWORK` and exactly one
  `compute.base_image`. The template writes the stack's network, which has a
  router, into `FSL_OPENSTACK_BUILD_NETWORK`.
- Nova caps user data at 65535 bytes of base64 per image bundle.
- The edge's Internet and estate ports hold every origin's `.1` and the estate's
  gateway. They have `allowed_address_pairs 0.0.0.0/0`, so the edge forwards
  traffic without NAT. Kali's Internet port holds about 100 origin addresses.
  cloud-init applies only a port's first address, so the slot's `bootcmd` adds
  the others.
- The edge's NICs are ordered internet, estate, mgmt. FreeBSD names them vtnet0,
  vtnet1 and vtnet2, and the config assigns them to WAN, LAN and opt1. The edge
  runs no cloud-init. The platform reaches it as root over mgmt with its key.
- The edge's Suricata watches the WAN in IDS (pcap) mode with hardware
  offloading off [O5]. HOME_NET is the estate and mgmt. OPNsense's
  `suricata.yaml` sets EXTERNAL_NET to `!$HOME_NET` and includes `conf.d/*.yaml`
  [O6].
- The edge's WAN pass rule admits tcp 80 to the WAF's estate address only. Before
  2026-10-12 it passed any destination, and Kali reached the wargame host's ports
  8000 and 80 on the estate through the edge, past the WAF.
- A second sensor watches the estate leg, the traffic from the WAF to the target,
  which the edge never sees. The second sensor works like this:
  - It runs docker's Suricata image and `deploy/suricata/suricata.yaml` on
    `fsl-wargame-host`, with host networking, from
    `deploy/wargame-host/sensor.yaml`.
  - It listens on the interface that holds the host's estate address
    (`af-packet`, the `default` entry).
  - Every sensor start first writes the platform's `suricata.yaml` to the host.
    A change therefore reaches a standing slot at its next reset.
  - Its role is `estate-sensor`. The host entry names its rule file and reload
    command, and `logs: {suricata: /var/log/suricata/eve.json}`. rsyslog
    forwards that log to the collector tagged `suricata`, as the WAF forwards its
    audit log.
  - Rule seeding, validation and changes go to both sensors.
- `configure/` does these steps on the edge:
  1. It writes `/conf/config.xml`, the Suricata include
     (`/usr/local/etc/suricata/conf.d/fsl.yaml`) and the rule file.
  2. It reboots the edge.
  3. It waits up to 15 minutes for a new boot time before checking the edge.
  4. It records `/conf/fsl-settled` for the session reset (§6.1).
- `configure/` ends by starting the wargames on `fsl-wargame-host` over ssh, as
  `ubuntu` with sudo. For each wargame (the `wargames` role) it runs `docker
  compose -p <id> -f /opt/fsl/wargames/<id>.yaml up -d --wait --pull never`. If
  one does not come up healthy, `configure/` fails and shows compose's output.
  - The board publishes port 8000 on the host. corp-wp publishes port 80.
  - The WAF reaches them by the names `board` and `corp-wp`. Its `/etc/hosts`
    maps those names to the host's estate address.
  - The platform reads the board's accounts (`/internal/auth-users`, the
    snapshot that submitted loot is checked against) at the host's mgmt address
    on port 8000.
  - A role the host fills (`board`, `board-db`, `corp`, `corp-db`) runs commands
    inside its container (`sudo docker exec <service>`). This is how the corp
    effect reader gets `corp-db`'s binary log. It is also how the harness's
    `run_on_role` reaches the wargame containers.
- A guest needs a config drive. Without one it gets no metadata.
- Nova here answers 404 for the console of a powered-off guest.

### 6.1 Session reset

Closing a session resets the slot. Since 2026-10-12 only the VMs that hand out a
shell are rebuilt (see `docs/DECISIONS.md`, "The close resets the edge and the
wargame host in place"):

| VM | Reset at close | Why |
|---|---|---|
| `fsl-kali` | Nova rebuild from its image, then its time source (the platform over `mgmt`) | It is the red team's root shell. Anything outside the config can carry over |
| `fsl-waf` | Nova rebuild, then its time source and `configure_waf()` (audit-log forwarding) | It is the blue team's shell (`vm-terminal.sh fsl-waf`) |
| `fsl-edge` | in place: the baseline `fsl.rules` is written back; `/conf/config.xml`, `conf.d/fsl.yaml` and `fsl.rules` are checked by sha256; the pf states of every range subnet are dropped (`pfctl -k`, mgmt kept); `configctl filter reload`; `configctl ids restart`; wait for the Suricata socket | The session can change only `fsl.rules`, and only the platform reaches the edge's GUI and ssh (`fsl-mgmt`) |
| `fsl-wargame-host` | in place: `docker compose -p <id> down -v` for each wargame and for the estate sensor; its `eve.json` and rsyslog's imfile state are removed. Then its time source, the usual `up -d --wait --pull never`, the sensor with the platform's `suricata.yaml`, the baseline rules seeded into it through `rules/suricata.py`, and log forwarding | The containers mount no host path, run unprivileged and get no docker socket |

OPNsense rewrites `config.xml` on its first boot after an install. Its
migrations add uuids, defaults and `persisted_at` stamps. The edge's file
therefore never equals the rendered one. For this reason `configure/` ends by
writing `/conf/fsl-settled`. The file holds two hashes: the sha256 of the config
the platform rendered, and the sha256 of `/conf/config.xml` once the edge has
settled.

The in-place reset compares both hashes against what the platform renders now
and what the edge holds. The reset falls back to the install and reboot
(`configure_edge()`), which records the hashes again, in any of these cases:

- a hash does not match
- Suricata does not answer within 60 s
- the edge does not hold its addresses, sensor, logging and WAN pass rule
  afterwards

The configd actions are OPNsense's own. `actions_ids.conf` `[restart]` runs
`/usr/local/etc/rc.d/suricata restart`. `actions_filter.conf` `[reload]` runs
`/usr/local/etc/rc.filter_configure` (opnsense/core
`src/opnsense/service/conf/actions.d`).

The reset does not use `[flush.states]` (`pfctl -F state`). States are floating
(`all`), and the pass rules keep state with `flags S/SA`. Flushing every state
would drop the platform's own ssh session to the edge.

The in-place resets start at once, beside the Nova rebuilds. The platform
configures the rebuilt VMs only after Nova has shown each of them rebuilding and
back to ACTIVE. If a rebuilt VM is never seen leaving ACTIVE within 2 minutes,
the reset fails. The platform configures them from a fresh read of the cloud,
because a VM's ssh host-key alias follows its launch time. Everything runs under
one hold of the rules lock and polls every 2-3 s.

While the reset runs, `ready/` answers phase `RESETTING`. A refused `POST
/api/sessions/` names the reset, so a client waits and does not call
`configure/`. A failed reset reads `RESET_FAILED` with its reason. `POST
$P/configure/` retries it (a full configure, edge reboot included). `POST
$P/slot/rebuild/` still Nova-rebuilds every slot VM. A configure does not follow
it, so run `configure/` after it.

Close to READY took 95-116 s per session while every VM was rebuilt and the edge
rebooted. With the in-place reset it took 65.8, 65.9 and 60.1 s (three board
sessions, 2026-10-12, no fallback).

These trade-offs are recorded. They are not verified threats:

- The edge's isolation between sessions is now "config verified by hash". It used
  to be "rebuilt from its image". A change that leaves the three files alone
  would carry over. An example is a package installed through the GUI's firmware
  page.
- A container escape on the wargame host would persist to the next session. A
  rebuild would have removed it.

### 6.2 Teardown order

Delete the slot, then the fabric. `DELETE $P/slot/` takes every slot.
`DELETE $P/slot/?slot=N` takes one. `DELETE $P/fabric/` refuses while any server
other than the platform has a port on a range network. Teardown also deletes the
ports that no server holds any more (Nova leaves the pre-created
`fsl-platform.mgmt` port standing when it deletes a platform VM), and the next
attach deletes such a leftover before it makes a new port. The images stay.
`DELETE $P/images/` removes only failed builders and images of older bundles.

### 6.3 Keypair drift

The fabric compares the keypair `fsl-platform` with the platform's
`/data/ssh/id_ed25519`. A new VM without the kept key makes a new key. Then `GET
fabric/` reports `keypair fsl-platform holds another public key` (drift, and
`POST` answers 409). The fix is to delete the slot and then the fabric before
you replace the VM. With `bin/platform-rebuild` the key is carried over and
nothing drifts.

### 6.4 Range slots

`compute.slots: N` sets how many copies of the range stand.

- Slot 1 keeps the names used above.
- Slot N>1 uses `fsl-edge-N`, `fsl-kali-N`, `fsl-waf-N` and
  `fsl-wargame-host-N`. Its ports are `<host>-N.<segment>`. Its servers are
  tagged `fsl_slot=N`.
- Each slot beyond the first stands on its own `fsl-internet-N` (the same 30
  origin /24s) and `fsl-estate-N` (the same estate CIDR), tagged `fsl.slot=N`.
  `fsl-mgmt` is shared.
- The platform gives each session the first free READY slot and keeps it for the
  life of the session. The close resets only that slot.
- The collector writes each slot's syslog to `logs-N-*`. It tells the slots apart
  by the sender's hostname (`waf-2`, `firewall-2.localdomain`). A session reads
  its slot's index.

To add a slot to a standing range by hand (`bin/cloud up` does this for every
slot):

```bash
echo FSL_OPENSTACK_SLOTS=2 >> /opt/fsl/openstack.env    # or compute.slots in cloud.yaml before bin/cloud up
docker compose up -d --force-recreate platform
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/fabric/            # fsl-internet-2, fsl-estate-2, 31 subnets
curl -s -X POST -H 'Content-Type: application/json' -d '{}' "$P/slot/?slot=2"     # the slot's 4 VMs from the same images
curl -s -X POST -H 'Content-Type: application/json' -d '{}' "$P/configure/?slot=2"
curl -s $P/ready/                                                                  # slots[].phase READY
```

We measured this on 2026-10-12:

- The slot-2 VMs went ACTIVE within about 30 s.
- `configure/?slot=2` took 72 s, including the edge install and reboot.
- Slot 1 stayed READY throughout.
- Two sessions opened at once took slots 1 and 2. A third answered 409.
- We fired the same case in each session. Both left from the same JP origin
  address, 106.128.0.14.
- The alerts landed in `fsl-logs-slot1-*` (from `fsl-edge.range.internal`,
  `fsl-waf`) and `fsl-logs-slot2-*` (from `fsl-edge-2.range.internal`,
  `fsl-waf-2`). Each session ingested only its own case's alerts.
- Closing slot 2's session rebuilt only `fsl-waf-2` and `fsl-kali-2`. Slot 1
  stayed `IN_USE`. Slot 2 was READY 64.9 s later.

## 7. Verification

```bash
curl -s http://$ADDRESS:8000/api/range/ready/          # the slot's readiness
curl -s http://$ADDRESS:8000/api/range/fabric/ | jq .clean
ssh ubuntu@$ADDRESS 'cd /opt/fsl && FSL_PLATFORM_URL=http://'$ADDRESS':8000 bin/verify'
```

`bin/verify` runs with the checkout's `.venv/bin/python`. The platform VM
creates `/opt/fsl/.venv` at first boot. `bin/verify` restarts the platform and
resets the range. Never run it against a stack that someone is using.

`bin/verify --changed --live` runs only the acceptance modules that a change
reaches (`bin/acceptance --only`). `--fast` runs no acceptance.

Since 2026-10-17 the whole acceptance suite runs here with no skip: 70 passed, 0
failed, 0 skipped (`docs/DECISIONS.md` "No acceptance test is skipped on
OpenStack"). The latest full run, 2026-10-20 on bf96876's code, passed unit 1718 and
acceptance 73, with 0 failed, 0 errors and 0 skipped (about 22 minutes).

A change to a range host's image (`deploy/kali`, `deploy/waf`, ...) reaches a
standing slot only at its next reset. After `bin/cloud up`, open and close one
session per slot before the run.

**The first acceptance run on the OpenStack substrate**, 2026-10-11, on a range
built from scratch by `bin/cloud up` on the previous cloud (OPNsense 26.7 edge):
50 passed, 86 skipped, 6 failed, 4 errors. The run before the reset fixes gave 24
passed, 14 failed, 22 errors. We have since fixed or deleted what that run left:

- Tests that reached compose containers (`kali`, `corp-db`) now reach the slot's
  hosts through `run_on_role`.
- WAF tuning (`PUT /api/sessions/<id>/waf/`) uses the WAF host's declared rule
  file, reload command and pid (`rules/crs.py` `Layout`), not the Docker image's.
- We deleted the compose-only checks on 2026-10-17.

Run time was 2,900 s: fixture setup 1,689 s, test bodies 1,179 s, teardown 27 s.
The slowest item is `test_suppression`'s setup (578 s).

We checked live the same day:

- The edge's Suricata 8.0.6 loads the `conf.d/fsl.yaml` include and `fsl.rules`
  (4 of 4 rules).
- `suricatasc` is at `/usr/local/bin/suricatasc` with its socket at
  `/var/run/suricata-command.socket`, as the declaration names.
- The WAN pass rule is in pf.
- All of this survives a reboot. The edge answers again in about 30 s.
- Kali on Ubuntu has mitmproxy (8.1.1), mitmdump, nikto, ffuf, gobuster, whatweb,
  dirb with its wordlists, sqlmap, nmap, hydra and nc.
- A session close resets the range (§6.1). Close to READY measured 93 s.

We did not check whether the edge survives an OPNsense update. The edge has no
route to the Internet and cannot resolve `pkg.opnsense.org`.

## 8. Known issues

- Related sections: MTU (`network.mtu`), no resize (§2.4), the TaaS override
  (§2.3), no Cinder, keypair drift (§6.3), and the full core quota (§3.2).
- Every name lookup on a range host waits about 25 s, and `POST
  /api/range/configure/` answers 409 `container corp-wp is unhealthy`. This
  happened on the first `bin/cloud up` on this cloud (ML2/OVN, 2026-10-20). With no
  `[ovn] dns_servers`, Neutron announced `127.0.0.53`, the resolver of the
  `neutron-server` host (§2). The hosts' systemd-networkd sent that address out
  of `ens3`, so each lookup timed out (`getent` took 24.6 s). WordPress's
  healthcheck, `wp core is-installed` with a 5 s timeout, took 29.2 s.
  - Fixed in commit 68efc7c: `platform/range/openstack.py` creates every range
    subnet with the DNS server `0.0.0.0`, which announces no resolver. After the
    fix on the standing range, `getent` failed in 0.03 s and `wp core
    is-installed` took 1.9 s.
  - A fabric made before that commit keeps the old subnets. Run `openstack subnet
    set --dns-nameserver 0.0.0.0 <subnet>` on each range subnet (32 with one
    slot), then reset or reboot the range hosts so that they ask DHCP again.
  - A cloud admin can also set `[ovn] dns_servers`, which helps the cloud's other
    VMs. The product no longer needs it.
- A member user cannot create flavors or change quotas. The stack uses no
  admin-only Heat resource.
- `platform.ref` is required (example value `dev`; `--ref` overrides it). The VM
  sees only pushed commits.
- The project password is plain text in `/opt/fsl/openstack.env` and in the
  platform container's environment.
- The edge's builder serves its disk over plain HTTP on the platform network
  until the builder is deleted. Integrity rests on the SHA256 that the builder
  prints on its console. The platform reads it through Nova and checks it before
  the upload.
- Every edge built from one image shares its sshd host keys, which the builder's
  QEMU boot generates. The platform pins each server's key by its own alias.
- The nano image keeps `/var/log` and `/tmp` in memory [O1]. Nothing there
  survives a reboot. The edge's logs live in Elasticsearch.
- The platform reaches Kali over `mgmt` because Kali's origin addresses collide
  with the Docker networks `compose.yaml` declares on the platform VM.
- Fixed 2026-10-12, after we measured it first. Kali has a `mgmt` port. While
  every range port sat in `fsl-range`, an nmap from Kali found these open ports
  on `mgmt`:
  - the wargame host's 22, 80 and 8000 (`/internal/auth-users` answered 200 with
    every password hash)
  - the edge's 22, 80 and 443 (the OPNsense GUI)
  - the WAF's 22 and 80

  `mgmt` ports now sit in `fsl-mgmt`, which admits only the platform's port
  (`test/test_attacker_reach.py` scans from Kali). The Neutron DHCP port on `mgmt`
  (dnsmasq, 53) has no security group and still answers Kali.
- A server's `/etc/hosts` (and Kali's `board.com` and `corp.com`) comes from the
  user data it was booted with. The reset's rebuild passes none. On 2026-10-12
  the WAF and Kali had booted while the board had its own VM, and `fsl-waf` named
  only `board.com`. They kept the old board address and had no `corp.com` until
  we deleted their servers and `slot/` booted them again.
- Operator machine on the same subnet as the cloud. Suppose the operator's
  Wi-Fi uses the same subnet as the cloud's addresses, and the cloud is reached
  over a tunnel (WireGuard or another VPN). The connected route then wins, and
  cloud addresses go out the Wi-Fi interface. Put /32 `AllowedIPs` for the cloud
  hosts in the tunnel, or run a proxy bound to the tunnel interface. Check the
  route before any cloud call.

## 9. Try it in one VM (VirtualBox or VMware)

This section is for checking that the product runs. It is not for operating it.
One Ubuntu 24.04 VM holds an all-in-one Kolla-Ansible 2026.1 cloud and this
repo's numbered steps. It follows the official quickstart [K1] and the
hypervisors' manuals [V1][W1]. Run end to end on 2026-10-20 (on a KVM host; the
VirtualBox/VMware settings themselves were not exercised).

### 9.1 The VM

- Ubuntu 24.04 Server with **8 vCPU, 40 GB RAM and a 250 GB disk** (allocated as
  needed). The sizes come from these figures:
  - The range's VMs need 24 GB of RAM and 180 GB of disk (§3.2). Nova counts RAM
    and disk one to one (`initial_ram_allocation_ratio` and
    `initial_disk_allocation_ratio` are 1.0 [N2]).
  - Kolla's own services need the quickstart's minimum of 8 GB and 40 GB [K1].
  - 30 GB of disk is margin for the images Glance holds.
  - 24 GB of guests plus Kolla's 8 GB is 32 GB. The other 8 GB are headroom for
    the VM's page cache and the builders' image conversions.
  - Nova shares CPU 4 to 1 by default [N2], so 8 vCPU carry the range's 10.
  - The host needs more than 40 GB of RAM and 250 GB of free disk.
- The whole 250 GB must reach Nova. Ubuntu's guided storage makes the root
  logical volume at most 100 GiB of a disk this large. It leaves the rest of the
  volume group unused [S1]. Nova would then see about 100 GB, and the second
  builder or the slot would fail with `NoValidHost`.
  - In the installer's storage step, edit `ubuntu-lv` to use the whole volume
    group.
  - On an installed VM, run `sudo lvextend -r -l +100%FREE
    /dev/ubuntu-vg/ubuntu-lv`. `df -h /` then shows about 245 GB.
- Turn on nested virtualization in the hypervisor's own setting. In VirtualBox:
  Settings, System, Processor, **Enable Nested VT-x/AMD-V** [V1]. In VMware
  Workstation: Processors, **Virtualize Intel VT-x/EPT or AMD-V/RVI** [W1].
- Give the VM two network adapters on the same network. The host must reach that
  network, and it must reach the Internet.
  - VMware Workstation: set both adapters to **NAT**.
  - VirtualBox: set both to **Bridged Adapter** on the host's wired interface. On
    the second adapter, under Advanced, set Promiscuous Mode to **Allow All**
    [V1].
- The commands below use the plan in the table. Replace it with your network's
  own values. In VMware Workstation, the Virtual Network Editor shows the NAT
  subnet, its gateway and its DHCP range. The pool must lie outside the DHCP
  range.

| | Example |
|---|---|
| Network | 192.168.100.0/24 |
| Gateway | 192.168.100.1 |
| First adapter (management, fixed) | 192.168.100.10 |
| Floating-IP pool | 192.168.100.20 to 192.168.100.99 |

After the install, find the adapters' names with `ip -br link` (here NIC1 and
NIC2). Give the first the fixed address and bring the second up with no address.
Put this in `/etc/netplan/60-kolla.yaml`, then run `sudo netplan apply`:

```yaml
network:
  version: 2
  ethernets:
    NIC1:
      dhcp4: false
      addresses: [192.168.100.10/24]
      routes: [{to: default, via: 192.168.100.1}]
      nameservers: {addresses: [8.8.8.8, 8.8.4.4]}
    NIC2:
      dhcp4: false
      dhcp6: false
      optional: true
```

The two settings do the following:

- `dhcp4: false` on NIC1 matters because the installer's own
  `50-cloud-init.yaml` merges with this file. Without the setting, it would
  leave a DHCP address and a second default route beside the fixed one.
- `optional: true` on NIC2 keeps boot from waiting for an address that the
  adapter never gets.

Kolla-Ansible runs its playbooks with sudo, and the deploying user must not be
asked for a password. Give that user passwordless sudo:

```bash
echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/90-kolla
```

Install the quickstart's packages and check that the CPU's virtualization
reaches the VM:

```bash
sudo apt update && sudo apt install -y git python3-dev libffi-dev gcc libssl-dev libdbus-glib-1-dev python3-venv cpu-checker
sudo kvm-ok          # "KVM acceleration can be used"
```

### 9.2 The cloud

These are the quickstart's all-in-one steps [K1], run in `~`:

```bash
python3 -m venv ~/kolla-venv && . ~/kolla-venv/bin/activate && pip install -U pip
pip install git+https://opendev.org/openstack/kolla-ansible@stable/2026.1
pip install docker dbus-python
sudo mkdir -p /etc/kolla && sudo chown $USER:$USER /etc/kolla
cp -r ~/kolla-venv/share/kolla-ansible/etc_examples/kolla/* /etc/kolla
cp ~/kolla-venv/share/kolla-ansible/ansible/inventory/all-in-one .
kolla-ansible install-deps
kolla-genpwd
```

Append this to `/etc/kolla/globals.yml` (§2.2). The example file is all
comments:

```yaml
kolla_base_distro: "ubuntu"
network_interface: "NIC1"
neutron_external_interface: "NIC2"
kolla_internal_vip_address: "192.168.100.10"
enable_haproxy: "no"
enable_proxysql: "no"
nova_compute_virt_type: "kvm"
```

Then deploy. This step pulls the images from quay.io and is the long one. It
took 11 min 39 s on 2026-10-20. §2.1 gives the reasons for the extra `pip install`,
`--use-test-images` and `-i`.

```bash
kolla-ansible bootstrap-servers -i ./all-in-one
kolla-ansible prechecks -i ./all-in-one --use-test-images
kolla-ansible deploy -i ./all-in-one
pip install python-openstackclient -c https://releases.openstack.org/constraints/upper/2026.1
kolla-ansible post-deploy -i ./all-in-one
. /etc/kolla/admin-openrc.sh
```

### 9.3 The project, then this repo's steps

Stay in that shell as admin. Do these steps:

1. Create the external network on the second adapter's network, with the plan's
   subnet and pool (§2.5).
2. Create the project, user, quota, flavors and base image. Upload the base image
   with `--public` (§3.1, §3.3, §3.6). Nova's default quotas already cover one
   slot (§3.2).

In `cloud.yaml`, `identity.keystone` is `http://192.168.100.10:5000`.

Then open a new shell. The admin shell holds the Kolla venv and the admin `OS_*`
variables, and README step 6 sets those of the `fsl-range` user. Follow
`README.md` from step 2 in that new shell, in the same VM and as your own user. The browser of step 8 is the host's browser. It opens the
floating IP that `bin/cloud up` prints. The external network makes that address
reachable on the host's network.

## Sources

- [K1] Kolla-Ansible 2026.1 quickstart — https://docs.openstack.org/kolla-ansible/2026.1/user/quickstart.html
- [K2] kolla-ansible stable/2026.1 `etc/kolla/globals.yml` — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2026.1/etc/kolla/globals.yml
- [K7] Kolla-Ansible 2026.1, Libvirt guide (`nova_compute_virt_type`: kvm is the default) — https://docs.openstack.org/kolla-ansible/2026.1/reference/compute/libvirt-guide.html
- [K8] Kolla-Ansible 2026.1, Neutron networking (`neutron_external_interface` must be up without an IP) — https://docs.openstack.org/kolla-ansible/2026.1/reference/networking/neutron.html
- [K3] kolla-ansible stable/2026.1 `ansible/group_vars/all/neutron.yml` (`enable_neutron_taas: false`); TaaS added in 18.0.0 — https://docs.openstack.org/releasenotes/kolla-ansible/2024.1.html
- [K4] kolla-ansible stable/2026.1 `ansible/roles/neutron/tasks/config.yml` — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2026.1/ansible/roles/neutron/tasks/config.yml
- [K5] Kolla-Ansible, OpenStack service configuration overrides — https://docs.openstack.org/kolla-ansible/latest/admin/advanced-configuration.html
- [N1] Nova configuration, `allow_resize_to_same_host` (default False) — https://docs.openstack.org/nova/latest/configuration/config.html
- [N2] Nova configuration, `initial_cpu_allocation_ratio` 4.0, `initial_ram_allocation_ratio` 1.0, `initial_disk_allocation_ratio` 1.0, `reserved_host_memory_mb` 512 — same page
- [N3] Neutron, DNS resolution for instances with ML2/OVN (`[ovn] dns_servers`, the host's resolvers as the fallback, and `0.0.0.0` announcing none), and `get_dhcp_dns_servers` in `neutron/common/ovn/utils.py` — https://docs.openstack.org/neutron/latest/admin/config-dns-res.html
- [V1] VirtualBox manual (nested virtualization, "Enable Nested VT-x/AMD-V"; bridged networking; promiscuous mode "Allow All") — https://www.virtualbox.org/manual/UserManual.html
- [S1] Canonical Subiquity, `subiquity/common/storage/sizes.py` (`scaled_rootfs_size`: "Use at most 100G of a large disk") — https://github.com/canonical/subiquity/blob/main/subiquity/common/storage/sizes.py
- [W1] Broadcom KB 389469, "Virtualized Intel VT-x/EPT is not supported on this platform" (names the Workstation setting "Virtualize Intel VT-x/EPT or AMD-V/RVI") — https://knowledge.broadcom.com/external/article/389469
- [H1] Heat `OS::Nova::Server` (`flavor_update_policy` RESIZE|REPLACE, default RESIZE; `user_data_update_policy` default REPLACE) — https://opendev.org/openstack/heat/src/branch/master/heat/engine/resources/openstack/nova/server.py
- [G3] Glance API v2, upload binary image data (`PUT /v2/images/{image_id}/file`) — https://docs.openstack.org/api-ref/image/v2/
- [U1] Ubuntu 24.04 cloud images and their `SHA256SUMS` — https://cloud-images.ubuntu.com/noble/current/
- [O1] OPNsense manual, Initial Installation & Configuration (image types, nano, download and verification, release schedule) — https://docs.opnsense.org/manual/install.html
- [O2] OPNsense legal guidelines (BSD 2-clause licence, trademark policy) — https://opnsense.org/legal-guidelines/
- [O3] OPNsense 26.7 release notes (26.7.6 on 2026-10-08; the 26.7 image checksums and public key) — https://docs.opnsense.org/releases/CE_26.7.html
- [O4] OPNsense core, `src/sbin/opnsense-importer` (the boot-time configuration importer and its prompts) — https://github.com/opnsense/core
- [O5] OPNsense manual, Intrusion Prevention System (capture modes; offloading off) — https://docs.opnsense.org/manual/ips.html
- [O6] OPNsense core, `src/opnsense/service/templates/OPNsense/IDS/suricata.yaml` (EXTERNAL_NET is !$HOME_NET; `conf.d/*.yaml` included) — https://github.com/opnsense/core
