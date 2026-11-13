# OpenStack

This file says what this project needs from an OpenStack cloud and how to set
one up from nothing. It covers the cloud (Kolla-Ansible 2025.1 or later), the project,
the one base image, `cloud.yaml`, the platform VM, the range and the checks. It
is written for an operator who rebuilds the cloud side or onboards a new cloud.
`README.md` has the numbered steps to bring the product up. This file has the
detail behind them. §9 builds the whole cloud in one VM so you can check that it
works.

Words used in this file:

- **Range**: what the platform builds for training: one VM, the range host,
  and the containers and Docker networks on it.
- **Range host** (`cr-range`): the one range VM. It runs every slot as
  containers.
- **Slot**: one full copy of the range, the Docker Compose project `sN` on the
  range host: `sN-kali`, `sN-edge`, `sN-waf`, the two sensors and the targets.
  One open session uses one slot.
- **Edge** (`sN-edge`): the slot's router between its Internet network and its
  estate network, an Alpine container with nftables. Two Suricata containers
  watch the slot's bridges.
- **Estate network** (`sN_estate`): the slot's Docker network behind the edge.
  It holds the WAF and the targets' front ends.
- **Fabric**: the management network, security groups and keypair the platform
  creates before the range host (`POST /api/range/fabric/`).
- **Store**: the platform's SQLite database (`db.sqlite3`).
- **Substrate**: what the platform builds the range on (`CR_SUBSTRATE`); here
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
   slot, which boots the range host from the stock Ubuntu image with its setup
   bundle in the user data; `configure/`, which starts each slot as containers
   on it. Then it waits until `ready/` says ready, and removes what the VM range
   of before left in the project (`DELETE leftovers/`, §5.5).

| Piece | Status | Where |
|---|---|---|
| Kolla-Ansible cloud with Heat, Glance, Nova, Neutron (ML2/OVN) | done (this cloud) | §2 |
| Project `fsl-range`, member user, quotas, flavors | done by hand, admin only | §3 |
| One base image, stock Ubuntu 24.04, upload with checksum check | by hand, once per cloud; done (this cloud, 2026-10-20) | §3.6 |
| `cloud.yaml`: every cloud-specific value, validated | done (this cloud, 2026-10-20) | §4 |
| Platform and range images on GHCR (`.github/workflows/images.yml`) | done (public, pulled 2026-10-11; `cr-kali`, `cr-waf` and `cr-edge` added with the range host) | §5 |
| Heat stack pulls images instead of `--build` | done (2026-10-11) | §5 |
| `bin/platform-rebuild`: replace the VM without losing data (store and range key carried over), driven by `cloud.yaml` | done (2026-10-15, `bin/cloud up --replace --sideload` twice, 28 and 55 min with a 6 GB store; the range stood through) | §5 |
| `bin/cloud up|down` | done (2026-10-11); since 2026-10-20 `up` after `down` restores the newest backup that holds rows (run live 2026-10-20) | §5 |
| Fabric via `POST /api/range/fabric/` | done | §6 |
| Range host `cr-range` via `POST /api/range/slot/`: stock Ubuntu, set up from its user data, every image pulled from GHCR | done | §3.6, §6 |
| Slots as Compose projects on the range host via `POST /api/range/configure/` | done; reset in place at close (§6.1) | §6 |
| Acceptance on the OpenStack substrate | 70 passed / 0 failed / 0 skipped (2026-10-17, two workers, on the VM range of before) | §7 |

Steps below are tagged **[one-click]** where the script does them for you. They
are tagged **[admin, once]** where you must do them by hand because a member
user cannot.

## 1. What this project needs from OpenStack

The platform builds the range as one Nova server, the range host `cr-range`,
and runs every slot on it as Docker containers. It creates the server as a
member user. cloud-init writes `CR_SUBSTRATE=range.openstack.connect` on the
platform VM to select this.

The platform VM runs only the control plane as containers: platform,
Elasticsearch, Kibana, gns3 and the collector. `docker compose` pulls their
prebuilt images from GHCR. Every acceptance test runs and passes on OpenStack,
and none is marked skipped there (`docs/DECISIONS.md` 2026-10-11, which
replaced the 2026-10-08 spec's "OpenStack work, not MVP").

The cloud therefore holds two VMs: the platform VM `cr-platform` and the range
host `cr-range`. The edge, Kali, the WAF, the sensors and the targets of each
slot are containers on the range host (§6).

The platform calls these APIs (`platform/range/openstack.py`):

- Keystone v3, with password authentication in the configured domain.
- Nova: servers, keypairs, flavors and `os-interface`.
- Neutron: networks with tags, subnets, ports and security groups.
- Glance v2: find the base image by name, and list and delete the project's
  own images that the VM range of before left (§5.5).

The operator also uses Heat for the platform VM. The project uses no Cinder,
Octavia or Designate.

## 2. What the cloud needs (Kolla-Ansible 2025.1 or later)

The product supports OpenStack deployed with Kolla-Ansible 2025.1 or later (the
user's ruling of 2026-10-24: later releases are much the same). **(this cloud)**
It runs the Kolla images tagged 2025.2 (seen on 2026-10-24:
`quay.io/openstack.kolla/cinder-backup:2025.2-ubuntu-noble` on `stg01`), so the
commands below use 2025.2. Any release from 2025.1 on is installed the same way:
change `2025.2` to that release in the `pip install` line, the constraints URL
and `openstack_release`. The previous cloud ran 2026.1, and the measurements
marked as coming from it are about 2026.1.

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
way (`platform/range/openstack.py`), because the management network needs no
resolver. The product therefore does not depend on `[ovn] dns_servers`. A
cloud admin who wants the cloud's other VMs to resolve names sets
`[ovn] dns_servers` in `neutron.conf` (Kolla: an override file, §2.3's
mechanism). §8 has the symptom.

**MTU.** The tenant networks' MTU is 1442 on OVN (Geneve) and 1450 on VXLAN with
ML2/OVS. Set `network.mtu` to the value `openstack network show` reports for a
tenant network on your cloud.

### 2.1 Install and deploy [admin, once]

These commands follow the 2025.2 quickstart [K1]:

```bash
sudo apt install -y git python3-dev libffi-dev gcc libssl-dev libdbus-glib-1-dev python3-venv
python3 -m venv /opt/kolla-venv && . /opt/kolla-venv/bin/activate
pip install -U pip
pip install git+https://opendev.org/openstack/kolla-ansible@stable/2025.2
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
pip install python-openstackclient python-heatclient -c https://releases.openstack.org/constraints/upper/2025.2
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
openstack_release: "2025.2"
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
the Open vSwitch agent. To enable it on 2026.1, the release of the previous cloud:

```yaml
enable_neutron_taas: "yes"     # defined in ansible/group_vars/all/neutron.yml, default false [K3]
```

```bash
cp /etc/kolla/globals.yml /etc/kolla/globals.yml.before-taas
kolla-ansible reconfigure -i /root/all-in-one -t neutron
```

**The 2026.1 bug.** Measured on the previous cloud. We did not run TaaS on 2025.x. The
same code is in `stable/2025.2` (read, not run): the task copies
`neutron_taas.conf` only for `neutron-server` and `neutron-openvswitch-agent`,
and `neutron.conf.j2` lists the service plugins for every Neutron service. So
the bug probably applies there too; this is not checked on 2025.x.


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

The platform VM is reached on a floating IP. The platform VM and the range
host download their packages and images through a router on an external
network. A fresh
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
| platform VM (cloud-init, `cr-platform.service`) | the Ubuntu archive; github.com; ghcr.io; docker.elastic.co; geoip.elastic.co | `apt` (Docker, git, chrony); `git clone` of `platform.repository`; `cr-platform` and `cr-gns3`; Elasticsearch, Kibana and Filebeat; `bin/fetch-geoip` |
| the range host (`deploy/range-host/setup.sh`) | the Ubuntu archive; ghcr.io; Docker Hub | `docker.io`, `docker-compose-v2`, `ethtool`, `rsyslog`, `acl`; `cr-kali`, `cr-waf`, `cr-edge`, `cr-board`, `cr-corp`, `cr-corp-db`; the pinned Suricata (`jasonish/suricata`) and MySQL images |
| the operator machine | the cloud's API; the floating IP; github.com; ghcr.io | `bin/cloud`; the check that the images can be pulled |

The range host reaches the Internet only through its second port, on the
platform's own network (`CR_OPENSTACK_BUILD_NETWORK`), in the security group
`cr-egress`, which admits nothing in. The slots' containers have no Internet:
every slot network is an internal Docker network with no host address (§6).

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

The platform VM and the range host are the project's only two instances,
however many slots run. With the example flavors they need 8 vCPU, 24 GB RAM, 2
instances and 1 floating IP.

- The platform VM is 2 vCPU, 8 GB RAM and 60 GB disk (`m1.large`).
- The range host is the `compute.flavors.range` flavor, for example `dba.range`
  (6 vCPU, 16 GB RAM, 60 GB disk, §3.3).

Nova's default quotas (20 cores, 51200 MB of RAM, 10 instances) and Neutron's
default network quotas already cover this. A new cloud sets none.

Nova has no per-project disk quota. The 120 GB of flavor disk (60 + 60) is
space that the compute node's instance storage must have, at a disk allocation
ratio of 1.0 [N2].

A further slot adds no instance, network, port or security group rule. It runs
on the range host as more containers, so what bounds the slots is the range
host's flavor. A bigger flavor means replacing the range host (§2.4: resize is
off).

**(this cloud)** These are the figures:

- Since 2026-10-24 the quota is 24 cores, 57344 MB of RAM and 12 instances
  (Nova's default, 20 / 51200 / 10, until then).
- The platform VM (2 cores, 8 GB) and the range host on `dba.range` (6 cores,
  16 GB) bring the project to 8 cores, 24 GB and 2 instances. `compute.slots`
  is 2.
- The fabric holds 1 network (`cr-mgmt`) with 1 subnet, and the groups
  `cr-reach`, `cr-mgmt` and `cr-egress`. The stack also needs 1 network, 1
  router and 1 floating IP.

```bash
openstack quota show fsl-range
openstack quota set --cores 24 --ram 65536 --instances 12 fsl-range   # example
```

### 3.3 Flavors [admin, once]

A member user cannot create flavors. `compute.flavors` in `cloud.yaml` names
exactly two:

| Key | Use | Notes |
|---|---|---|
| `platform` | platform VM | 8 GB RAM or more. With 4 GB, the OOM killer once killed Elasticsearch when sessions stacked up (DECISIONS 2026-10-10). Example `m1.large` (8 GB / 2 vCPU / 60 GB) |
| `range` | the range host `cr-range` | It runs every slot: per slot Kali, the edge, the WAF, two Suricata sensors, two MySQL 8, Django and WordPress. The rendered slot gives each container a memory limit (`deploy/range-host/slot.yaml`). Example `dba.range` (16 GB / 6 vCPU / 60 GB) |

**(this cloud)** The cloud has `m1.large` (8 GB / 2 vCPU / 60 GB), `m1.medium`
(4 GB / 2 vCPU / 30 GB), `dba.medium` (8 GB / 4 vCPU / 40 GB) and `dba.range`
(16 GB / 6 vCPU / 60 GB). `cloud.yaml` names `m1.large` for `platform` and
`dba.range` for `range`. The range host keeps its flavor until it is replaced
(`DELETE $P/slot/`, then `bin/cloud up`). Check that both flavors `cloud.yaml`
names exist on your cloud. The platform refuses a missing flavor and names it.

```bash
openstack flavor create --ram 8192 --vcpus 2 --disk 60 m1.large
openstack flavor create --ram 16384 --vcpus 6 --disk 60 dba.range
```

A new cloud makes these two flavors, and `cloud.example.yaml` names them.

### 3.4 Keypairs

- `fsl-claude` is the operator's key that the platform VM boots with. It is the
  stack parameter `key_name` and `keys.operator` in `cloud.yaml`. Make the key,
  then create the keypair as `fsl-range` before the stack. Use the sign-in
  variables from `README.md` step 6:
  `ssh-keygen -t ed25519 -N "" -f ~/.ssh/fsl_claude` and
  `openstack keypair create --public-key ~/.ssh/fsl_claude.pub fsl-claude`
- `cr-platform` is the platform's own range key. `POST /api/range/fabric/`
  imports it from `/data/ssh/id_ed25519` in the platform container. Never create
  this keypair by hand. The key file it comes from (`keys.range`) needs no step
  either. The first `bin/cloud up` on a cloud with no stack makes the file if it
  is missing. §6.3 covers a mismatch between the two.

### 3.5 Security groups

| Group | Made by | Rules |
|---|---|---|
| `cr-platform` | Heat stack | tcp 22, tcp 8000, tcp 8002, tcp 3080, icmp in |
| `cr-reach` | fabric | on the platform's `mgmt` port; nothing in except udp 123 (NTP) from members of `cr-mgmt`, then udp 5140 from exactly the range host's `mgmt` address (`configure/`) |
| `cr-mgmt` | fabric | on the range host's `mgmt` port; all IPv4 in, only from members of `cr-reach` (the platform's `mgmt` port) |
| `cr-egress` | fabric | on the range host's port on the platform's network, which it pulls its images over; no rule in |

`bin/cloud up` deletes the groups `cr-range` and `cr-build` of the VM range of
before (§5.5).

Port 8002 is the blue console's Website pane. The platform sends each request
over an ssh stream to the range host (over `mgmt`) and into the slot's Kali
container. Kali sends it from a customers address through the edge to the WAF
(`docs/ARCHITECTURE.md`, the Website pane's egress). A platform stack made
before 2026-10-13 lacks the rule. Add it by hand:

```bash
openstack security group rule create --protocol tcp --dst-port 8002 cr-platform
```

The range has no Internet, so the platform is its only time source.

- The platform VM runs chrony. cloud-init sets `allow <network.mgmt>` and `local
  stratum 10`, so the platform keeps serving its own clock if it loses its
  upstream time source.
- The range host takes its time from the platform's `mgmt` address. It gets a
  `systemd-timesyncd` drop-in (`/etc/systemd/timesyncd.conf.d/60-cr.conf`,
  `NTP=<platform mgmt>`) at every `configure/`. The step waits for the first
  answer. The containers share the range host's clock.
- A rebuilt platform VM has a new `mgmt` address. The range host takes it at
  the next `configure/`.
- A range made before 2026-10-15 gets the udp 123 rule at the next `bin/cloud up`
  (`POST /api/range/fabric/` plans it as `ntp`).
- A platform VM booted before 2026-10-15 lacks chrony. Run what cloud-init runs:

```bash
sudo install -d /etc/chrony/conf.d
printf 'allow 10.31.0.0/24\nlocal stratum 10\n' | sudo tee /etc/chrony/conf.d/cr-range.conf
sudo apt-get -y install chrony
```

Port 3080 is the GNS3 server (`compose.yaml` `gns3`). The blue console's Map
pane shows its web UI in a frame. A platform stack made before P1 of the
scenario course lacks the rule. Add it by hand:

```bash
openstack security group rule create --protocol tcp --dst-port 3080 cr-platform
```

### 3.6 Images

The cloud holds exactly one image that you upload by hand: Canonical's Ubuntu
24.04 cloud image, unmodified. Nothing is baked into it, and the platform
builds no Glance image. cloud-init installs or writes every package, tool, key
and setting at boot (the platform VM, the range host). The platform does the
rest over ssh (`configure/`).

| Image | How it gets there | One-click |
|---|---|---|
| `compute.base_image` (e.g. `ubuntu-24.04`) | the stock `noble-server-cloudimg-amd64.img`, checksum verified, uploaded as is (below) | by hand, once |
| the slots' container images | pulled from GHCR and Docker Hub by the range host at its first boot (below) | yes |

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
boot the range host while the cloud holds none, or more than one active image,
of that name. **(this cloud)** The admin uploaded `ubuntu-24.04` and made it
public. It is the only image uploaded by hand.

**The range host's setup [one-click].** The range host boots the base image
with its setup bundle in the Nova user data
(`platform/range/rangehost.py` `bundle()` and `user_data()`). Nova caps user
data at 65535 bytes of base64, and the platform refuses a bigger bundle. The
bundle holds `deploy/range-host/setup.sh` and files the platform generates:

- `images.txt`: every image the slots run, at the platform's tag
  (`CR_IMAGE_TAG`, the commit of the platform checkout, from `/opt/cr/.env`):
  `ghcr.io/nekonic/cr-kali`, `cr-waf`, `cr-edge`, `cr-board`, `cr-corp`,
  `cr-corp-db`, and the pinned `jasonish/suricata` and `mysql`.
- `pristine.yaml` and `wargames.txt`: the targets, rendered once to make their
  pristine data.
- `daemon.json` for Docker: the tenant MTU (`network.mtu`), the address pool
  10.40.0.0/16 cut into /28s, the `local` log driver and `userns-remap:
  default`, so a container's root is an unprivileged user on the host.

`setup.sh` does these steps while the range host has its egress port:

1. It enables `universe`, purges `snapd` and `modemmanager`, and installs
   `docker.io`, `docker-compose-v2`, `ethtool`, `rsyslog` and `acl`.
2. It raises the inotify limits and sshd's `MaxSessions` and `MaxStartups`,
   because the platform runs many commands at once over one shared ssh
   connection.
3. It installs `daemon.json` and restarts Docker.
4. It pulls every image in `images.txt`, five tries each.
5. It brings the targets up once as the Compose project `pristine`, waits until
   they are healthy, stops them and copies their volumes to
   `/opt/cr/pristine/<service><path>`. Then it removes them with `down -v`.
6. It loads rsyslog's `imfile` module.

cloud-init then marks `/var/lib/cr/ready`, or `/var/lib/cr/failed` with the
last lines of `/var/log/cr-setup.log` on the console. Until then the platform
reports the range host `SETTING_UP`, or `SETUP_FAILED` (§6).

The images must be public and exist for the tag. The tag and every bundle file
are part of the bundle's digest, which the range host carries in its metadata
(`cr_bundle`, beside the tag in `cr_tag`). A platform on a new commit, or a
change to a file in the bundle, makes the range host stale, and `POST slot/`
replaces it (§6). A tag that moves (`dev`) does not change the digest.

Every bundle digest hashes each file's name, its content and its mode. The mode
is only the executable bit, 0755 or 0644, as git tracks it. A checkout's umask
therefore does not change a digest: a sideloaded checkout (files 0664) and a
cloud-init clone (files 0644) of one commit plan the same range host.

A sideloaded image (§5.3) is loaded on the platform VM only. The range host
pulls every slot image from GHCR at the platform's tag, so a changed Kali, WAF,
edge or target reaches the range only through a pushed commit whose images
`images.yml` has published.

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
| `network.mtu` | `1450` (**(this cloud)** `1442`) | the tenant networks' MTU (1450 on VXLAN with ML2/OVS, 1442 on Geneve with ML2/OVN, §2); Docker on the platform VM and on the range host, and every slot network |
| `network.platform`, `.estate`, `.mgmt` | `10.20.0.0/24`, `10.30.0.0/16`, `10.31.0.0/24` | The ranges must be private and must not overlap. They must also stay outside Docker's default local address pools (172.17.0.0/16 to 172.31.0.0/16 and 192.168.0.0/16, moby `daemon/libnetwork/ipamutils/utils.go`), `compose.yaml`'s networks and the declared origins. `network.estate` must be a /16 or wider: slot N's estate is its Nth /24 (10.30.N.0/24), a Docker network on the range host, not a Neutron network |
| `compute.base_image` | `ubuntu-24.04` | the platform VM and the range host |
| `compute.availability_zone` | `""` | the platform VM and the range host; if empty, Nova chooses |
| `compute.flavors` | `platform`, `range`, exactly these two | §3.3 |
| `compute.slots` | `1` (**(this cloud)** `2`) | optional; how many slots the range host runs, which is how many sessions can run at once (§6.4); `CR_OPENSTACK_SLOTS` |
| `keys.operator`, `keys.operator_file` | `fsl-claude`, `~/.ssh/fsl_claude` | the keypair the platform VM boots with, and its private half |
| `keys.range` | `~/.ssh/fsl-platform` | the platform's range key, kept across rebuilds |
| `platform.stack`, `.repository`, `.ref` | `cr-platform`, this repo, `dev` | the stack, and the checkout it clones |
| `backups.keep` | `1` | optional; how many store backups `backups/` keeps after a rebuild or `down`, counting the new one (`bin/backup --keep`). Without it, one |

Where each value goes:

- `bin/platform-rebuild` and `bin/cloud` set the openstack CLI's `OS_*`
  variables from `identity`, so no openrc file is needed.
- They pass every Heat parameter from the file (`Cloud.heat_parameters()`).
- The template has no defaults. It writes the values into
  `/opt/cr/openstack.env` as `CR_OPENSTACK_*`.
- The platform reads those variables (`settings.py`). If one it needs is
  missing, it refuses and names the variable.

## 5. The platform VM

### 5.1 The Heat stack

`deploy/openstack/platform.yaml` creates:

- the network `cr-platform` (`network.platform`)
- a router to `network.external`
- the group `cr-platform`
- a port
- a floating IP
- a server from `compute.base_image`

The server's cloud-init does these steps:

1. Installs Docker.
2. Sets Docker's MTU to the network's MTU.
3. Adds 4 GB of swap.
4. Clones `repository` at `ref` into `/opt/cr`.
5. Writes `/opt/cr/openstack.env`. It holds every cloud value except the
   password, and `CR_TOOL_IMAGE=cr-kali`, the attacker host the launcher runs
   tools on.
6. Writes `/opt/cr/.env` with `CR_PUBLISH=<fixed IP>` and
   `CR_SYSLOG_PUBLISH=0.0.0.0`.
7. Enables `cr-platform.service`.

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

`CR_PUBLISH` is the VM's fixed IP. Port 8000 therefore listens on that address,
not on loopback, and the floating IP NATs to it. Setting `CR_PUBLISH=0.0.0.0` on
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
   the stack (`--wait`) and creates it again.
   (`--replace` replaces a working stack through `bin/platform-rebuild`, below.)
4. It asks the VM over ssh whether it took its hand-over, whether or not the API
   answers, and then waits for the API. A container can answer before the
   password line is written, and a range build on it would fail. The hand-over
   is the step that gives a new VM the password, the range key and the store
   (§5.3). A VM never took it when `/opt/cr/openstack.env` has no
   `CR_OPENSTACK_PASSWORD`. In that case `up` does the hand-over first. If the
   `cr-platform` container is stopped, `up` starts it first, because the key is
   written into that container. The redone hand-over keeps every other line of
   `openstack.env`, `CR_SIDELOADED` included. `up` refuses a `--sideload` here,
   because it applies only to a new VM.
5. It sends `POST fabric/`. It stops on drift (a resource that exists but
   differs from what the platform would create).
6. It sends `POST slot/`. It stops when the slot is blocked. If no range host
   stands, this boots `cr-range` (§6). If the range host is stale, because the
   platform's tag or the bundle's digest differs from the one it was booted
   with, this deletes it and boots a new one, but only when no session holds
   any slot. While a session holds one, the slot reads blocked and `up` stops.
7. It sends `GET ready/` until no slot reads `NOT_STANDING`, `REBUILDING`,
   `RESETTING` or `STALE`. A range host that is still running its setup reads
   `SETTING_UP`, and its slots `REBUILDING`.
8. It sends `POST configure/`. It retries while the answer is 503, which means
   the range host's ssh is not up yet. It stops on 409.
9. It sends `GET ready/` until the range is ready.
10. It sends `DELETE leftovers/`, which removes what the VM range of before
    left in the project (§5.5), and prints what it removed.

`down` does these steps:

1. It asks the VM over ssh whether a running `cr-platform` container or a store
   file exists. The store file is `db.sqlite3` in the `cr_platformdata` volume.
2. If neither exists, as after a first boot that never started the platform,
   there is nothing to back up and no platform to ask. `down` then deletes only
   the stack and the servers of step 7.
3. If ssh does not answer, or Docker does not, `down` cannot tell. It refuses and
   deletes nothing.
4. If a store file exists beside a stopped platform container, `down` starts the
   container, because the backup runs through `docker exec`. It refuses, and
   deletes nothing, when the container does not start.
5. It keeps the range key and backs up the store (`bin/backup --keep`,
   `backups.keep`).
6. It waits for the API. Then it runs `DELETE slot/`, which takes every slot
   down and deletes the range host, and `DELETE fabric/`.
7. It deletes every server whose name starts with `cr-build-`, which carries the
   `cr_image` property and which has a port on this stack's own network (the
   stack's `network` resource): a builder the VM range of before may have left.
   Such a port would make the stack delete fail.
8. It deletes the stack.

A `*_FAILED` stack has no platform to ask. For it, `down` deletes those
servers and the stack only.

We ran `down` on 2026-10-11, on the VM range of before. It took 26 s. It left
no stack, builder, range network, port, router or range security group. It
kept the Glance images, the reserved floating IP, the `fsl-claude` keypair and
the `cr-build` group.

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

1. It refuses unless every image `images.yml` publishes (`platform`, `board`,
   `corp`, `corp-db`, `gns3`, `kali`, `waf`, `edge`) is public on GHCR for the
   ref's commit, except the ones it sideloads.
2. It keeps the range key (`keys.range`), which it takes once from the running
   platform.
3. It backs up the store with `bin/backup`. If the old VM holds a store but its
   `cr-platform` container is stopped, it starts the container first. If the old
   VM has neither a running `cr-platform` container nor a store file, it says so,
   skips the backup and makes the range key if it is missing. If ssh to the old VM
   does not answer, it refuses.
4. It deletes and recreates the stack.
5. It starts the `cr-platform` container on the new VM if it is stopped, then
   writes the kept key to `/data/ssh/id_ed25519` through `docker exec`.
6. It restores the store.
7. It rewrites the password line in `/opt/cr/openstack.env`, and the
   `CR_SIDELOADED` line when the run sideloads. It keeps every other line, and
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

Because the key is carried over, the fabric's `cr-platform` keypair stays valid.
You do not need to tear the slot down. The range host holds a port on the
stack's own network (its egress port, §2.6). Whether the stack delete succeeds
while that port stands has not been run since the range became one host;
`bin/cloud down` deletes the range host before the stack.

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
- The new VM holds one copy in `/opt/cr/backups`, the one it was restored from.

The store stays small. The platform deletes sessions that were closed more than
`CR_RETAIN_CLOSED_MINUTES` ago, with their records. The default is 60
(`platform/cr/settings.py`, set in `compose.yaml`, overridden in
`/opt/cr/.env`). It does this at start and after every close, 2,000 rows per
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
   `/opt/cr`.
3. It runs `docker load` on each tarball and tags the image with the cloned
   commit (`CR_IMAGE_TAG` in `/opt/cr/.env`).
4. It stops the platform for the restore.
5. It recreates every service with `docker compose up -d --force-recreate`.
   HEAD's compose file may add services. A file bind-mounted into a running
   container, such as `filebeat.yml`, keeps the cloned commit's copy until the
   container is recreated.

`CR_IMAGE_TAG` stays the cloned commit. The range host pulls every slot image
from GHCR at that tag (§3.6), so a sideloaded image is loaded on the platform VM
only. A sideloaded `board`, `corp`, `corp-db`, `kali`, `waf` or `edge` never
reaches the range; push the commit and let `images.yml` publish its images
instead. The rebuild still writes `CR_SIDELOADED=<names>` beside the password
in `/opt/cr/openstack.env`, and a hand-over that `up` redoes on a standing VM
keeps the line. To see the names, run
`sudo docker exec cr-platform env | grep CR_SIDELOADED` on the VM.

A pushed commit with a changed slot image reaches the range through `POST
slot/`. The new tag makes the range host stale, and `POST slot/` deletes it and
boots a new one from the stock image, which pulls the new images (§3.6, §6).
Every slot goes with it, so this waits until no session holds any slot. Until
then `ready/` reads the slots `STALE`. `bin/cloud up` sends `POST slot/` and
then `configure/`. By hand:

```bash
P=http://ADDRESS:8000/api/range
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/slot/        # deletes the stale range host, boots a new one
curl -s $P/ready/                                                          # REBUILDING while the setup runs (SETTING_UP)
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/configure/   # every slot up on the new range host
```

Before it deletes anything, the command refuses in these cases:

- an unknown name
- a name given twice
- a missing tarball
- a tarball that does not hold exactly one `ghcr.io/nekonic/cr-NAME:<commit>`
- an image whose build context in `.github/workflows/images.yml` differs between
  the commit it was built from and HEAD. The built-from commit is the tarball's
  tag, or the cloned commit for an image that is pulled.

Build a tarball on any x86_64 Docker host from a clean export of the commit:

```bash
git archive $C platform | tar -x -C ctx
docker build --platform linux/amd64 -t ghcr.io/nekonic/cr-platform:$C ctx/platform
docker save -o cr-platform-$C.tar ghcr.io/nekonic/cr-platform:$C
.venv/bin/python bin/cloud up --replace --sideload platform=cr-platform-$C.tar
```

The `gns3` image goes the same way. The refusal names every image whose build
context differs from HEAD.

A sideloaded VM that reboots runs `cr-platform.service` again. Its `compose
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
| cloud-init, `cr-platform.service` at 8f9acb0 | 2 min | 2 min | done, no errors; `python3-venv` 3.12.3, `nodejs` 18.19.1; `/etc/sysctl.d/90-cr-syslog.conf` applied (`net.core.rmem_max = 33554432`) |
| HEAD bundle, two tarballs loaded | 2 min 29 s | 1 min 4 s | 111 MB and 241 MB; the containers run images labelled with HEAD and 1814e5c |
| Password, range key | 1 s | 1 s | key fingerprint unchanged |
| Store upload (`scp`) | 30 min 41 s | 14 min 39 s | 3.1 and 6.8 MB/s |
| Restore, `compose up -d`, API | 1 min 3 s | 1 min 4 s | migrate: no migrations to apply (the store was already at 0026); 0020-0026 `[X]` |
| Fabric, images, slot, configure, ready (the VM range of before) | 5 min 14 s | 46 s | no drift; run 1 rebuilt `cr-wargame-host` for the new tag (3 min 43 s); both slots READY on the same servers |
| Total | 54 min 33 s | 28 min 18 s | |

Security group `cr-platform`: 22, 8000, 8002, 3080 and ICMP. After each run a
board session (497, 514) opened in about 5 s. Its map pane (now Map) drew the
learner map from `cr-gns3` with every link end green. Its close reset the slot
to READY within 2 minutes. The old VM's Elasticsearch data does not move. Only
the store does.

### 5.4 The rename cut-over

On 2026-11-13 every name the code gives the cloud moved from the prefix `fsl` to
`cr` (`docs/DECISIONS.md`, 2026-11-13). A cloud brought up before that still
runs the old names: stack `fsl-platform`, `/opt/fsl`, the volume
`fsl_platformdata`, slot servers, networks and groups named `fsl-*`. The renamed
code cannot see them, so take them down with the code that made them, once:

1. Push the renamed code to `dev` and wait for `images.yml`. Make the new
   packages public (README, "Package settings"): `cr-platform`, `cr-gns3`,
   `cr-board`, `cr-corp`, `cr-corp-db`, and since the range host also
   `cr-kali`, `cr-waf` and `cr-edge`.
2. Check out the last commit before the rename beside this checkout, give it
   the current `cloud.yaml` and take the cloud down from there. `down` backs up
   the store into that checkout's `backups/`, deletes the slots, the fabric,
   the builders and the stack, and keeps the floating IP and Glance:

   ```bash
   git worktree add ../cr-cutover <the commit before the rename>
   cp deploy/openstack/cloud.yaml ../cr-cutover/deploy/openstack/
   (cd ../cr-cutover && "$OLDPWD/.venv/bin/python" bin/cloud down)
   mkdir -p backups && cp ../cr-cutover/backups/db-*.sqlite3 backups/
   ```

3. Delete what `down` leaves under the old names: the role images, the
   OPNsense image and the builders' security group. Keep `fsl-claude`. The
   range host needs none of these images (§3.6).

   ```bash
   .venv/bin/openstack image delete fsl-kali fsl-waf fsl-wargame-host fsl-opnsense-<version>
   .venv/bin/openstack security group delete fsl-build
   .venv/bin/openstack server list --name '^fsl-'; .venv/bin/openstack network list --name fsl-internet
   .venv/bin/openstack keypair list
   ```

   The server and network lists are empty and the keypairs are `fsl-claude`
   alone when the old range is gone.
4. In `cloud.yaml` set `platform.stack: cr-platform`.
5. Bring the cloud up from this checkout with the `openstack` CLI on PATH:
   `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python bin/cloud up`. `platform.ref`
   must be a ref name with no `/` in it; push a branch so named if the working
   branch has one. It creates `cr-platform`, restores the newest backup in
   `backups/` and builds the fabric, the range host and the slots under the new
   names.
6. Point the `cloud` git remote at the new checkout path:
   `git remote set-url cloud ssh://ubuntu@ADDRESS/opt/cr`.

If step 2 is skipped while `platform.stack` still names `fsl-platform`,
`bin/platform-rebuild` and `bin/cloud down` find the store under
`fsl_platformdata` and refuse instead of deleting the old VM.

### 5.5 From the VM range to the range host

Before the range host, each slot was four VMs (`cr-edge`, `cr-kali`, `cr-waf`,
`cr-wargame-host`, and `-N` names for slot N) on its own Neutron networks,
booted from role images the platform built on builder VMs, with an OPNsense
edge. A cloud that still runs that range moves to the range host with one
`bin/cloud up` on the new code:

1. Push the code to `dev`, wait for `images.yml` and make `cr-kali`, `cr-waf`
   and `cr-edge` public beside the other packages.
2. In `cloud.yaml`, give `compute.flavors` exactly `platform` and `range`, name
   a flavor big enough for every slot under `range` (§3.3), make
   `network.estate` a /16 (`10.30.0.0/16`) and delete the `opnsense` section.
   The platform refuses the old keys and names them.
3. Run `.venv/bin/python bin/cloud up --replace`. The platform VM is replaced
   with its store and range key (§5.3). `POST fabric/` makes the group
   `cr-egress` and lists the old range networks as leftovers, not drift. `POST
   slot/` boots `cr-range` beside the old VMs, which keep running until the end.
   `configure/` starts the slots on it.
4. Once the range is ready, the same `up` sends `DELETE leftovers/`. It removes
   what the VM range left:
   - the old slot VMs, found by their `cr_host` metadata, and any builder (the
     `cr_image` metadata), waiting until Nova has deleted them
   - the ports, subnets and networks of the segments the slots now carry as
     Docker networks (`cr-internet`, `cr-estate` and their `-N` copies), and
     detached ports on `cr-mgmt`
   - the security groups `cr-range` and `cr-build`
   - the project's images carrying the `cr_bundle` property: the role images
     (`cr-kali`, `cr-waf`, `cr-wargame-host`) and `fsl-opnsense-<version>`

`GET $P/leftovers/` lists the same without deleting anything. The base image
carries no `cr_bundle`, so it stays.

The old VMs and the range host stand side by side until step 4. **(this cloud)**
That fits the quota exactly: the platform VM (2 cores, 8 GB), two slots of four
`m1.medium` VMs (16 cores, 32 GB) and `cr-range` on `dba.range` (6 cores,
16 GB) are 24 cores and 56 GB of the 24 cores and 57344 MB (§3.2). The cloud
now runs `cr-platform` and `cr-range`.

## 6. The range (substrate openstack)

Everything goes through the platform's API, as `fsl-range`.

- Each `GET` reads the plan: what is missing, present, drifted or unused.
- `POST` makes the cloud match the plan.
- `DELETE` tears down.

`bin/cloud up` runs these calls in order. By hand:

```bash
P=http://$ADDRESS:8000/api/range
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/fabric/     # cr-mgmt (DHCP on, no gateway), keypair cr-platform,
                                  # groups cr-reach/cr-mgmt/cr-egress, platform port cr-platform.mgmt
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/slot/       # boots cr-range: port cr-range.mgmt in cr-mgmt, a second port on
                                  # CR_OPENSTACK_BUILD_NETWORK in cr-egress; replaces a stale range host when no session holds a slot
curl -s $P/ready/                 # REBUILDING while the range host reads SETTING_UP
curl -s -X POST -H 'Content-Type: application/json' -d '{}' $P/configure/  # each slot: its Compose project up, log forwarding, baseline rules
curl -s $P/ready/
curl -s -X DELETE $P/leftovers/   # what the VM range of before left (§5.5)
```

Notes:

- The platform finds networks by the tag `cr.segment.id=<segment>`, not by
  name. The fabric needs the Neutron `standard-attr-tag` extension, which is on
  by default. The fabric carries only the `mgmt` segment. A range network of
  any other segment, or of a slot tag other than 1, is listed as a leftover.
- Booting the range host needs `CR_OPENSTACK_BUILD_NETWORK`, `CR_IMAGE_TAG` and
  exactly one `compute.base_image`. The template writes the stack's network,
  which has a router, into `CR_OPENSTACK_BUILD_NETWORK`; the range host pulls
  its images over it (§2.6).
- The range host boots with a config drive and the keypair `cr-platform`. Its
  metadata names it (`cr_host=cr-range`) and records the tag (`cr_tag`) and the
  bundle digest (`cr_bundle`) it was booted with (§3.6).
- The platform reports the range host `SETTING_UP` until `/var/lib/cr/ready`
  exists, and `SETUP_FAILED`, with the last lines of `/var/log/cr-setup.log`,
  when `/var/lib/cr/failed` does. It asks over ssh.
- The platform reaches the range host as `ubuntu` over `mgmt`, with one shared
  ssh connection per host (`ControlMaster auto`, `ControlPersist 60`). A role
  that a container fills (the `compose:` map in
  `platform/range/declaration.yaml`) runs its command with `sudo docker exec
  sN-<service>`. The `wargames` role runs on the range host itself.

**The slot.** Slot N is the Docker Compose project `sN` on the range host.
`platform/range/rangehost.py` renders it from `deploy/range-host/slot.yaml`
and each wargame's `wargames/<w>/compose.yaml`, and sends it over ssh with
`deploy/range-host/slot.sh` into `/opt/cr/sN/`.

| Container | Image | On |
|---|---|---|
| `sN-kali` | `cr-kali` (`deploy/kali/Dockerfile`) | `sN_internet`, about 100 origin addresses |
| `sN-edge` | `cr-edge` (`deploy/edge/`: Alpine and nftables) | `sN_internet` (`wan`, every origin's `.1`) and `sN_estate` (`lan`, `.1`) |
| `sN-waf` | `cr-waf` (`deploy/waf/Dockerfile`: nginx, ModSecurity, CRS) | `sN_estate` `.247` |
| `sN-edge-sensor` | `jasonish/suricata`, pinned by digest | host network, `af-packet` on the bridge `sN-inet` |
| `sN-estate-sensor` | the same | host network, `af-packet` on the bridge `sN-estate`, with a BPF filter on the board's and corp-wp's addresses |
| `sN-board`, `sN-board-db` | `cr-board`, `mysql` | `sN_estate` `.59` (board) and `board-default` |
| `sN-corp-wp`, `sN-corp-db` | `cr-corp`, `cr-corp-db` | `sN_estate` `.60` (corp-wp) and `corp-default` |

- `sN_internet` is the bridge `sN-inet` on 172.30.N.0/24, an address range
  that exists only on the range host. `sN_estate` is the bridge `sN-estate` on
  slot N's /24 of `network.estate` (10.30.N.0/24). Each wargame's backend is
  its own `<w>-default` network.
- Every slot network is `internal`, with `gateway_mode_ipv4: isolated`, so the
  range host holds no address on any bridge, and has the tenant MTU. No
  container publishes a port and nothing is NATed.
- The edge forwards between its two legs (nftables `forward` policy accept)
  and accepts nothing addressed to itself (`input` policy drop). It holds only
  `NET_ADMIN`.
- Kali knows only `board.com` and `corp.com`, both the WAF's address. The WAF
  reaches the targets by the names `board` and `corp-wp`.
- The ground truth of the board (`/internal/auth-users`, the snapshot that
  submitted loot is checked against) is read inside the board container
  through the `board` role, not over a port. corp's effect reader gets
  `corp-db`'s binary log the same way, and so does the harness's
  `run_on_role`.
- Each sensor runs one thread with `cluster_flow`. The estate sensor's config
  is `deploy/suricata/suricata.yaml` with the slot's `af-packet` entry; the
  edge sensor's is `deploy/range-host/edge-sensor.yaml`. Their rule files are
  `/opt/cr/sN/{edge,estate}-rules/local.rules`.
- rsyslog on the range host reads `/var/log/cr/sN/edge/eve.json`,
  `/var/log/cr/sN/estate/eve.json` and `/var/log/cr/sN/waf/audit.log`
  (`/etc/rsyslog.d/60-cr-sN.conf`) and forwards them over UDP 5140 to the
  platform's `mgmt` address. Each slot has fixed sender names: `cr-edge`,
  `cr-range` and `cr-waf` for slot 1, `cr-edge-N`, `cr-range-N` and `cr-waf-N`
  for slot N. The logs are under `/var/log` because Ubuntu's rsyslog runs as
  the `syslog` user, which AppArmor confines there.

`configure/` does these steps for each slot:

1. It opens the collector to the range host's `mgmt` address (`cr-reach`) and
   sets the range host's time source (§3.5), side by side.
2. It sends the slot's files and runs `slot.sh up N`:
   1. It makes the slot's rule and log directories. The WAF's log directory is
      owned by the remapped `www-data` and readable by `syslog`.
   2. `docker compose up --no-start --pull never` creates the containers and
      their new, empty volumes.
   3. It copies the targets' pristine data (§3.6) into each empty volume of a
      container that has never run.
   4. `up -d --wait --pull never` starts the slot. MySQL finds an initialised
      datadir and skips its initialisation; the board skips creating its posts
      and comments but still sets the seeded accounts' passwords afresh, and
      corp skips its install but sets a new admin password hash.
   5. It gives Kali its origin addresses and default route, and the edge every
      origin's gateway, with `nsenter ... ip -batch`.
   6. It routes the WAF and the targets' front ends through the edge.
   7. It switches TSO, GSO and GRO off on every interface the sensors watch:
      the containers' interfaces, both bridges and their ports.
   8. It lets each bridge forward to itself past Docker's isolation rules
      (`DOCKER-USER`).
   9. It installs the slot's rsyslog file and restarts rsyslog.
3. It seeds both sensors with the baseline rules through `rules/suricata.py`.

Secrets stay per session. The board's `seed` sets each seeded account's
password on every start, so every session's hashes have new salts. corp's
entrypoint deletes `wp-config.php` before the WordPress image's entrypoint
runs, which then writes new random keys and salts, and on restored data it
sets the admin password again.

Each healthcheck probes every second during its start period
(`start_interval: 1s`, Docker Engine 25 or later), so `--wait` sees a container
healthy about a second after it is.

The learner's terminals (`platform/vm-terminal.sh cr-kali`, `cr-waf`) ssh to
the range host's `mgmt` address and run `sudo docker exec -it ... sN-kali bash
-l`, or `sN-waf`. Both shells are root inside their container.

### 6.1 Session reset

Closing a session resets its slot in place, with no Nova call. The platform
runs `slot.sh reset N` on the range host:

| Container | Reset at close |
|---|---|
| `sN-kali`, `sN-waf` | recreated from their images (`up -d --force-recreate`), then Kali's origin addresses and the WAF's route set again |
| the targets | removed with their volumes and created again, the volumes restored from `/opt/cr/pristine`, then started, beside the step above |
| `sN-edge` | keeps running; its neighbour table is flushed |
| the two sensors | keep running; their `eve.json` and the WAF's `audit.log` are emptied in place and the sensors reopen their log files |

The platform then seeds both sensors with the baseline rules again and marks
the slot's disabled rules enabled. If the slot's files are gone from the range
host, the reset configures the slot instead.

A restart of the platform during a reset does not lose it. The reset leaves a
file `slot-N` in `/data/reset-owed` until it succeeds. At boot the platform
does the reset again for each slot that still has one, as a close does.
`/api/range/ready/` shows that slot `RESETTING`, then `READY` or
`RESET_FAILED` with the reason.

While the reset runs, `ready/` answers phase `RESETTING`. A refused `POST
/api/sessions/` names the reset, so a client waits and does not call
`configure/`. A failed reset reads `RESET_FAILED` with its reason. `POST
$P/configure/` retries it. `POST $P/slot/rebuild/` takes the slot's Compose
project down with its volumes (`slot.sh down N`). A configure does not follow
it, so run `configure/` after it.

On the VM range of before, the close rebuilt Kali and the WAF with Nova and
reset the edge and the wargame host in place; close to READY took 70-82 s for
one slot (2026-10-24, `docs/TROUBLESHOOTING.md`). The range host's reset has
not been timed here.

These trade-offs are recorded. They are not verified threats:

- The edge and the sensors are not recreated between sessions. No learner has
  a shell on them; the platform alone reaches them.
- The slots share the range host's kernel. A container escape from Kali or the
  WAF reaches the range host and every slot on it, and would persist to the
  next session (`docs/THREAT-MODEL.md`).
- The target data every session starts from is the same copy, made at the
  range host's setup. What a learner could reuse across sessions is renewed at
  each start: the board's password salts, corp's keys and salts, and corp's
  admin hash.

### 6.2 Teardown order

Delete the slot, then the fabric. `DELETE $P/slot/` takes every slot down
(`slot.sh down N`) and deletes the range host. `DELETE $P/slot/?slot=N` takes
one slot's Compose project down and leaves the range host. `DELETE $P/fabric/`
refuses while any server other than the platform has a port on a range
network. Teardown also deletes the ports that no server holds any more (Nova
leaves the pre-created `cr-platform.mgmt` port standing when it deletes a
platform VM), and the next attach deletes such a leftover before it makes a
new port. It also deletes the groups `cr-range` and `cr-build` if they are
still there.

### 6.3 Keypair drift

The fabric compares the keypair `cr-platform` with the platform's
`/data/ssh/id_ed25519`. A new VM without the kept key makes a new key. Then `GET
fabric/` reports `keypair cr-platform holds another public key` (drift, and
`POST` answers 409). The fix is to delete the slot and then the fabric before
you replace the VM. With `bin/platform-rebuild` the key is carried over and
nothing drifts.

### 6.4 Range slots

`compute.slots: N` sets how many slots the range host runs.

- Slot N is the Compose project `sN`: containers `sN-*`, networks
  `sN_internet` (172.30.N.0/24) and `sN_estate` (10.30.N.0/24), and its files
  in `/opt/cr/sN/` and `/var/log/cr/sN/`. A slot has no Neutron resource of its
  own, and `network.estate` as a /16 holds slots 1 to 255.
- The platform gives each session the first free READY slot and keeps it for the
  life of the session. The close resets only that slot.
- The collector writes each slot's syslog to `logs-N-*`. It tells the slots apart
  by the sender's name (`cr-waf-2`, `cr-edge-2`, `cr-range-2`). A session reads
  its slot's index.

To add a slot to a standing range by hand (`bin/cloud up` does this for every
slot):

```bash
echo CR_OPENSTACK_SLOTS=2 >> /opt/cr/openstack.env    # or compute.slots in cloud.yaml before bin/cloud up
docker compose up -d --force-recreate platform
curl -s -X POST -H 'Content-Type: application/json' -d '{}' "$P/configure/?slot=2"   # s2 on the same range host
curl -s $P/ready/                                                                    # slots[].phase READY
```

The range host's bundle does not depend on the slot count, so adding a slot
does not replace it.

On the VM range of before, on 2026-10-12, two sessions opened at once took
slots 1 and 2, a third answered 409, and each session ingested only its own
case's alerts.

## 7. Verification

```bash
curl -s http://$ADDRESS:8000/api/range/ready/          # the slot's readiness
curl -s http://$ADDRESS:8000/api/range/fabric/ | jq .clean
ssh ubuntu@$ADDRESS 'cd /opt/cr && CR_PLATFORM_URL=http://'$ADDRESS':8000 bin/verify'
```

`bin/verify` runs with the checkout's `.venv/bin/python`. The platform VM
creates `/opt/cr/.venv` at first boot. `bin/verify` restarts the platform and
resets the range. Never run it against a stack that someone is using.

`bin/verify --changed --live` runs only the acceptance modules that a change
reaches (`bin/acceptance --only`). `--fast` runs no acceptance.

Since 2026-10-17 the whole acceptance suite runs here with no skip: 70 passed, 0
failed, 0 skipped (`docs/DECISIONS.md` "No acceptance test is skipped on
OpenStack"). The latest full run, 2026-10-20 on bf96876's code, passed unit 1718 and
acceptance 73, with 0 failed, 0 errors and 0 skipped (about 22 minutes).

A change to a slot image (`deploy/kali`, `deploy/waf`, `deploy/edge`, a
target) reaches the range only through a pushed commit: the new tag makes the
range host stale, and `bin/cloud up` replaces it when no session holds a slot
(§5.3). A change to the slot's files (`deploy/range-host/slot.yaml`, the
sensors' configs) reaches a slot at its next `configure/`.

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
The slowest item is `test_disabled_rule`'s setup (578 s).

We checked live the same day:

- The edge's Suricata 8.0.6 loads the `conf.d/cr.yaml` include and `cr.rules`
  (4 of 4 rules).
- `suricatasc` is at `/usr/local/bin/suricatasc` with its socket at
  `/var/run/suricata-command.socket`, as the declaration names.
- The WAN pass rule is in pf.
- All of this survives a reboot. The edge answers again in about 30 s.
- Kali on Ubuntu has mitmproxy (8.1.1), mitmdump, nikto, ffuf, gobuster, whatweb,
  dirb with its wordlists, sqlmap, nmap, hydra and nc.
- A session close resets the range (§6.1). Close to READY measured 93 s.

We did not check whether that OPNsense edge survived an OPNsense update.

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
  - A fabric made before that commit keeps the old subnet. Run `openstack subnet
    set --dns-nameserver 0.0.0.0 cr-mgmt`, then reboot the range host so that
    it asks DHCP again. The range host resolves names through its port on the
    platform's network (`network.dns`).
  - A cloud admin can also set `[ovn] dns_servers`, which helps the cloud's other
    VMs. The product no longer needs it.
- A member user cannot create flavors or change quotas. The stack uses no
  admin-only Heat resource.
- `platform.ref` is required (example value `dev`; `--ref` overrides it). The VM
  sees only pushed commits.
- The project password is plain text in `/opt/cr/openstack.env` and in the
  platform container's environment.
- Kali's origin addresses exist only inside the range host's slot networks,
  so they never meet the Docker networks `compose.yaml` declares on the
  platform VM. The platform reaches Kali only through `docker exec` on the
  range host.
- The edge forwards whatever reaches it, so Kali reaches the board's estate
  address on port 8000 past the WAF, as `test/test_range_isolation.py`
  asserts. By name Kali reaches only `board.com` and `corp.com`, the WAF.
- Fixed 2026-10-12 on the VM range, after we measured it first. Kali had a
  `mgmt` port. While
  every range port sat in `cr-range`, an nmap from Kali found these open ports
  on `mgmt`:
  - the wargame host's 22, 80 and 8000 (`/internal/auth-users` answered 200 with
    every password hash)
  - the edge's 22, 80 and 443 (the OPNsense GUI)
  - the WAF's 22 and 80

  The `mgmt` ports were then put in `cr-mgmt`, which admits only the
  platform's port. Kali now has no port on any Neutron network; the range
  host's `mgmt` port is in `cr-mgmt`. `test/test_attacker_reach.py` scans every
  network Kali holds an address on besides its route out, and
  `test/test_range_isolation.py` checks that no container reaches the range
  host, the platform, the Internet, the metadata service or another slot.
- On the VM range a server's `/etc/hosts` came from the user data it was booted
  with, and a Nova rebuild passed none, so on 2026-10-12 the WAF and Kali kept
  an old board address. The containers' names now come from the rendered slot
  (`extra_hosts`), which every recreate applies.
- Operator machine on the same subnet as the cloud. Suppose the operator's
  Wi-Fi uses the same subnet as the cloud's addresses, and the cloud is reached
  over a tunnel (WireGuard or another VPN). The connected route then wins, and
  cloud addresses go out the Wi-Fi interface. Put /32 `AllowedIPs` for the cloud
  hosts in the tunnel, or run a proxy bound to the tunnel interface. Check the
  route before any cloud call.

## 9. Try it in one VM (VirtualBox or VMware)

This section is for checking that the product runs. It is not for operating it.
One Ubuntu 24.04 VM holds an all-in-one Kolla-Ansible cloud and this
repo's numbered steps. The 2026-10-20 trial ran 2026.1; the commands below use
2025.2 and were not run again. It follows the official quickstart [K1] and the
hypervisors' manuals [V1][W1]. Run end to end on 2026-10-20 (on a KVM host; the
VirtualBox/VMware settings themselves were not exercised).

### 9.1 The VM

- Ubuntu 24.04 Server with **8 vCPU, 40 GB RAM and a 250 GB disk** (allocated as
  needed). The 2026-10-20 trial used these sizes for the VM range of before.
  The range host needs less disk. The sizes come from these figures:
  - The platform VM and the range host need 24 GB of RAM and 120 GB of disk
    with the example flavors (§3.2). Nova counts RAM and disk one to one
    (`initial_ram_allocation_ratio` and `initial_disk_allocation_ratio` are 1.0
    [N2]).
  - Kolla's own services need the quickstart's minimum of 8 GB and 40 GB [K1].
  - The rest of the disk is margin for Glance's one image and Nova's cache of
    it.
  - 24 GB of guests plus Kolla's 8 GB is 32 GB. The other 8 GB are headroom for
    the VM's page cache.
  - Nova shares CPU 4 to 1 by default [N2], so 8 vCPU carry the two VMs' 8.
  - The host needs more than 40 GB of RAM and 250 GB of free disk.
- The whole 250 GB must reach Nova. Ubuntu's guided storage makes the root
  logical volume at most 100 GiB of a disk this large. It leaves the rest of the
  volume group unused [S1]. Nova would then see about 100 GB, less than the
  two VMs' 120 GB, and the range host would fail with `NoValidHost`.
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
pip install git+https://opendev.org/openstack/kolla-ansible@stable/2025.2
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
pip install python-openstackclient -c https://releases.openstack.org/constraints/upper/2025.2
kolla-ansible post-deploy -i ./all-in-one
. /etc/kolla/admin-openrc.sh
```

### 9.3 The project, then this repo's steps

Stay in that shell as admin. Do these steps:

1. Create the external network on the second adapter's network, with the plan's
   subnet and pool (§2.5).
2. Create the project, user, quota, flavors and base image. Upload the base image
   with `--public` (§3.1, §3.3, §3.6). Nova's default quotas already cover the
   two VMs (§3.2).

In `cloud.yaml`, `identity.keystone` is `http://192.168.100.10:5000`.

Then open a new shell. The admin shell holds the Kolla venv and the admin `OS_*`
variables, and README step 6 sets those of the `fsl-range` user. Follow
`README.md` from step 2 in that new shell, in the same VM and as your own user. The browser of step 8 is the host's browser. It opens the
floating IP that `bin/cloud up` prints. The external network makes that address
reachable on the host's network.

## Sources

- [K1] Kolla-Ansible 2025.2 quickstart — https://docs.openstack.org/kolla-ansible/2025.2/user/quickstart.html
- [K2] kolla-ansible stable/2025.2 `etc/kolla/globals.yml` — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2025.2/etc/kolla/globals.yml
- [K7] Kolla-Ansible 2025.2, Libvirt guide (`nova_compute_virt_type`: kvm is the default) — https://docs.openstack.org/kolla-ansible/2025.2/reference/compute/libvirt-guide.html
- [K8] Kolla-Ansible 2025.2, Neutron networking (`neutron_external_interface` goes on `br-ex`, physical network `physnet1`; the page says an interface plugged into a bridge cannot hold a usable IP address) — https://docs.openstack.org/kolla-ansible/2025.2/reference/networking/neutron.html
- [K3] kolla-ansible stable/2025.2 `ansible/group_vars/all/neutron.yml` (`enable_neutron_taas: false`); TaaS added in 18.0.0 — https://docs.openstack.org/releasenotes/kolla-ansible/2024.1.html
- [K4] kolla-ansible stable/2025.2 `ansible/roles/neutron/tasks/config.yml` (the 2026.1 bug in §2.3 was measured on stable/2026.1) — https://opendev.org/openstack/kolla-ansible/src/branch/stable/2025.2/ansible/roles/neutron/tasks/config.yml
- [K5] Kolla-Ansible, OpenStack service configuration overrides — https://docs.openstack.org/kolla-ansible/latest/admin/advanced-configuration.html
- [N1] Nova configuration, `allow_resize_to_same_host` (default False) — https://docs.openstack.org/nova/latest/configuration/config.html
- [N2] Nova configuration, `initial_cpu_allocation_ratio` 4.0, `initial_ram_allocation_ratio` 1.0, `initial_disk_allocation_ratio` 1.0, `reserved_host_memory_mb` 512 — same page
- [N3] Neutron, DNS resolution for instances with ML2/OVN (`[ovn] dns_servers`, the host's resolvers as the fallback, and `0.0.0.0` announcing none), and `get_dhcp_dns_servers` in `neutron/common/ovn/utils.py` — https://docs.openstack.org/neutron/latest/admin/config-dns-res.html
- [V1] VirtualBox manual (nested virtualization, "Enable Nested VT-x/AMD-V"; bridged networking; promiscuous mode "Allow All") — https://www.virtualbox.org/manual/UserManual.html
- [S1] Canonical Subiquity, `subiquity/common/storage/sizes.py` (`scaled_rootfs_size`: "Use at most 100G of a large disk") — https://github.com/canonical/subiquity/blob/main/subiquity/common/storage/sizes.py
- [W1] Broadcom KB 389469, "Virtualized Intel VT-x/EPT is not supported on this platform" (names the Workstation setting "Virtualize Intel VT-x/EPT or AMD-V/RVI") — https://knowledge.broadcom.com/external/article/389469
- [H1] Heat `OS::Nova::Server` (`flavor_update_policy` RESIZE|REPLACE, default RESIZE; `user_data_update_policy` default REPLACE) — https://opendev.org/openstack/heat/src/branch/master/heat/engine/resources/openstack/nova/server.py
- [U1] Ubuntu 24.04 cloud images and their `SHA256SUMS` — https://cloud-images.ubuntu.com/noble/current/
