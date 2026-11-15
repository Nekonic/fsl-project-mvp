# fsl-project-mvp

사이버 공격·방어 훈련장입니다. 레드팀이 공격하는 웹사이트는 Django 게시판과
WordPress 회사 사이트로, 각자 MySQL을 쓰고 앞단에 WAF가 붙어 있습니다. 블루팀은
Suricata와 ModSecurity로 방어하고, 점수는 플랫폼이 양쪽 모두 매깁니다.
이 저장소는 버릴 프로토타입이고, 실제 제품은 별도 저장소에서 개발합니다.

Kolla-Ansible 2025.1 이상으로 구축한 OpenStack에서 돌아갑니다. 컴퓨트 노드는
KVM(`nova_compute_virt_type: kvm`)을 권장하며, KVM 없이 QEMU 에뮬레이션으로도
동작하지만 느립니다. 운영자 PC에서 `bin/cloud up`을 실행하면 Heat 스택으로 플랫폼 VM을
만들고, 그 VM은 GHCR에 미리 빌드해 둔 이미지를 pull해 플랫폼을 `docker compose`로
띄웁니다. 이어서 플랫폼이 OpenStack API로 훈련 환경 호스트 VM을 한 대 더 띄우고, 이
호스트에서 슬롯마다 훈련 환경을 컨테이너로 돌립니다.

- `CLAUDE.md`: 저장소의 목적, 점수 계산 방식, 작업 규칙
- `docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`:
  2026-10-08에 승인한 방향. 일부는 아직 구현 전
- `docs/ARCHITECTURE.md`: 훈련 환경 구성과 앞으로의 방향
- `docs/THREAT-MODEL.md`: 훈련 환경이 흉내 내는 것과 뺀 것
- `docs/STATE.md`: 작업 현황
- `docs/OPENSTACK.md`: 클라우드(Kolla-Ansible 2025.1 이상) 요구 사항, 프로젝트와
  플랫폼 VM, 훈련 환경, VM 한 대로 돌려 보는 체험 구성
- `docs/TROUBLESHOOTING.md`: 훈련 환경에서 겪은 문제와 원인, 해결 방법(영어)

## 필요한 것

운영자 PC(`bin/cloud`를 실행하는 곳):

- `git`, `ssh`, `ssh-keygen`, Python 3.10 이상. `platform/requirements.txt`의
  Django(5.2 이상)가 Python 3.10 이상을 요구합니다.
- `python-openstackclient`, `python-heatclient`. 3단계에서 `.venv`에 설치하며, Python
  venv 모듈이 있어야 합니다. Debian·Ubuntu에서는 `python3-venv`
  (`sudo apt install python3-venv`)입니다.
- 클라우드 API와 플랫폼 VM의 floating IP까지 닿는 네트워크 경로
- github.com, ghcr.io로 나가는 인터넷. `bin/cloud`는 무엇이든 지우기 전에 이미지를
  pull할 수 있는지부터 확인합니다.

클라우드:

- x86_64 호스트에 Kolla-Ansible 2025.1 이상으로 구축한 OpenStack.
  `nova_compute_virt_type: kvm`을 권장하며, `qemu`(KVM 없는 에뮬레이션)로도 동작하지만
  느립니다. Heat는 기본으로 켜져 있고, Cinder·Octavia·Designate는 필요 없습니다.
- floating IP 풀이 있는 외부 네트워크. VM이 그 네트워크로 인터넷에 나갈 수 있어야
  합니다(`docs/OPENSTACK.md` §2.5, §2.6).
- 플랫폼 VM과 훈련 환경 호스트, VM 두 대분의 자원. 슬롯(훈련 환경 한 벌)은 모두 훈련
  환경 호스트에서 돕니다.
  - 플랫폼 VM: `compute.flavors.platform`에 지정한 flavor. RAM 8 GB 이상, 예제 값은
    `m1.large`(2 vCPU, 8 GB, 60 GB)
  - 훈련 환경 호스트: `compute.flavors.range`에 지정한 flavor. 예제 값은
    `dba.range`(6 vCPU, 16 GB, 60 GB)
  - 예제 flavor 기준 합계 vCPU 8, RAM 24 GB, 인스턴스 2, floating IP 1, 컴퓨트 노드
    디스크 120 GB.
    Nova 기본 quota(코어 20, RAM 51200 MB, 인스턴스 10)로 충분합니다. Nova에는 디스크
    quota가 없으니 120 GB는 quota가 아니라 컴퓨트 노드에 실제로 확보돼 있어야 하는
    디스크입니다.
  - 슬롯 수(`compute.slots`)를 늘리면 VM이 아니라 같은 훈련 환경 호스트의 컨테이너가
    늘어납니다. `cloud.example.yaml` 주석은 슬롯당 메모리를 1.2 GB 정도로 잡습니다.

VirtualBox나 VMware VM 한 대에 클라우드 전체를 올려 먼저 시험해 보려면
`docs/OPENSTACK.md` §9를 참고하세요.

## 기동

1. **클라우드 준비(관리자, 최초 1회).** 외부 네트워크, 프로젝트 `fsl-range`, member
   사용자 `fsl-range`, flavor `m1.large`, 훈련 환경 호스트용 flavor(예제는
   `dba.range`), 베이스 이미지 `ubuntu-24.04`를 만듭니다. 명령은 `docs/OPENSTACK.md` §2.5, §3.1, §3.3, §3.6에
   있습니다. 관리자 계정으로 이미지를 올릴 때 `--public`을 붙이지 않으면
   `fsl-range`에서 이미지가 보이지 않습니다.
2. **clone.**

   ```bash
   git clone https://github.com/Nekonic/fsl-project-mvp.git && cd fsl-project-mvp
   ```

3. **virtualenv 생성, OpenStack CLI 설치.** 이후 명령은 전부 `.venv/bin/`으로
   실행하므로 activate는 하지 않아도 됩니다.

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r platform/requirements.txt python-openstackclient python-heatclient
   ```

4. **운영자 키 생성.** 플랫폼 VM에 로그인할 ssh 키입니다. 훈련 환경 키는 따로 만들
   필요가 없습니다. 플랫폼이 훈련 환경 호스트에 로그인할 때 쓰는 키로,
   `~/.ssh/fsl-platform`이 없으면 처음 `bin/cloud up`을 실행할 때 생성됩니다.

   ```bash
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/fsl_claude
   ```

5. **`deploy/openstack/cloud.yaml` 작성.** 예제를 복사한 뒤 자기 환경 값만 바꿉니다.
   복사본은 gitignore 대상입니다.

   ```bash
   cp deploy/openstack/cloud.example.yaml deploy/openstack/cloud.yaml
   mkdir -p ~/.config/fsl && (umask 077; touch ~/.config/fsl/fsl-range.password)
   ```

   `~/.config/fsl/fsl-range.password`에는 `fsl-range` 사용자의 비밀번호를 한 줄로
   적고, `cloud.yaml`에서는 키 두 개를 바꿉니다.

   - `identity.keystone`: `/v3`를 뺀 Keystone URL. 예제 값은 메인테이너의 랩 주소
   - `network.external`: 1단계에서 만든 외부 네트워크 이름

   나머지 키는 위 단계에 맞춰 이미 채워 두었으니 그대로 둡니다. 키별 설명은
   `docs/OPENSTACK.md` §4에 있습니다. 값이 잘못되면 아무것도 바꾸기 전에 로더에서
   거부하고, 문제가 된 키를 알려 줍니다.

6. **Nova 키페어 생성.** `fsl-range` 사용자 권한으로 운영자 키의 공개키를
   등록합니다.

   ```bash
   export OS_AUTH_URL=<identity.keystone>/v3 OS_IDENTITY_API_VERSION=3 OS_INTERFACE=public \
     OS_REGION_NAME=RegionOne OS_USER_DOMAIN_ID=default OS_PROJECT_DOMAIN_ID=default \
     OS_PROJECT_NAME=fsl-range OS_USERNAME=fsl-range \
     OS_PASSWORD="$(cat ~/.config/fsl/fsl-range.password)"
   .venv/bin/openstack keypair create --public-key ~/.ssh/fsl_claude.pub fsl-claude
   ```

   `<identity.keystone>`에는 `cloud.yaml`의 해당 값(예: `http://192.168.100.10:5000`)을
   넣고, region·interface·domain도 `cloud.yaml`에 적은 값을 씁니다.

7. **`bin/cloud up` 실행.**

   ```bash
   .venv/bin/python bin/cloud up
   ```

   `bin/cloud up`을 실행하면 플랫폼 VM을 만들고, 이어서 플랫폼 자체 API로 훈련 환경을
   만들면서 단계마다 진행 상황을 출력합니다. 첫 실행은 이후보다 오래 걸리는데,
   훈련 환경 호스트를 띄우고 그 호스트에 Docker를 설치한 다음 GHCR에서 훈련 환경
   이미지를 전부 pull해야 첫 슬롯이 뜨기 때문입니다. 끝나면
   `the range is ready; the platform is at http://ADDRESS:8000/`가 출력됩니다.

8. **동작 확인.** 브라우저로 그 주소에 접속합니다.

   - 홈 화면 **대상 시스템** 아래에 커뮤니티 게시판이 보이면, 첫 과정
     **로그 분석 기초**의 **레슨 1**에서 **시작**을 누릅니다.
   - 몇 초 안에 블루팀 콘솔이 과정 안내 화면으로 열립니다. **시작**을 누르면 회사
     네트워크를 그린 **구성도** 창이 뜨고, 옆 레슨 노트에 첫 단계가 나옵니다.
   - 훈련 네트워크가 아직 준비되지 않았다는 안내가 나오면 기다리면 됩니다. 닫힌
     세션의 슬롯은 초기화부터 거칩니다.

   터미널에서는 레슨 시작 전에 `curl -s http://ADDRESS:8000/api/range/ready/`를
   호출하면 `"ready": true`가 나옵니다. 빈 슬롯이 하나라도 있으면 `true`입니다.
   슬롯이 1개면 세션이 열려 있는 동안 `false`였다가 세션이 닫히고 슬롯 초기화가
   끝나면 다시 `true`가 되고, 슬롯이 여러 개면 모든 슬롯에 세션이 열릴 때까지
   `true`입니다.

9. **실패 시.** `bin/cloud up`은 처음 실패한 지점에서 멈추고 원인을 출력합니다.
   `cloud.yaml`의 키, 없는 flavor나 이미지, public이 아닌 GHCR 패키지는 이름까지
   나옵니다. 훈련 환경 호스트 설정이 실패하면 슬롯 단계 `SETUP_FAILED`와 함께, 원인이
   기록된 그 호스트의 `/var/log/cr-setup.log`를 알려 줍니다. 원인을 고치고 같은
   명령을 다시 실행하면 멈춘 지점부터 이어서 진행합니다. 설정에 실패했거나 이미지
   태그·설정 번들이 바뀐 훈련 환경 호스트는, 열린 세션이 없으면 그 실행에서 지우고
   다시 띄웁니다.

   - 플랫폼 VM: `ssh -i ~/.ssh/fsl_claude ubuntu@ADDRESS`로 접속해
     `systemctl status cr-platform`(마지막 부팅의 기동 결과),
     `sudo cloud-init status --long`, `sudo docker logs cr-platform`을 확인합니다.
   - Heat 스택: 6단계에서 쓴 셸에서
     `.venv/bin/openstack stack failures list cr-platform`을 실행합니다.
   - 스택은 생성됐는데 VM에서 `cr-platform`이 한 번도 실행되지 않은 경우:
     `sudo docker ps`에 `cr-platform` 컨테이너가 없고, 원인은
     `sudo cloud-init status --long`에 나옵니다. VM이 인터넷에 나가지 못하는 경우가
     많습니다(`docs/OPENSTACK.md` §2.6). 첫 부팅이 느렸을 뿐이면 `bin/cloud up`을
     다시 실행해 마무리하고, 아니면 원인을 고친 뒤
     `.venv/bin/python bin/cloud up --replace`를 실행합니다. 그 VM에는 저장된 데이터가
     없으므로 백업 없이 교체됩니다.
   - 위 경우나 `down` 직후처럼 새 플랫폼 VM이 이전 VM의 DB를 넘겨받지 못할 때가
     있습니다. 이때 `bin/cloud up`은 `backups/db-<UTC 시각>.sqlite3` 가운데 행이 있는
     가장 최근 백업을 복원하고 파일 이름을 출력합니다. 그런 백업이 없으면 빈 DB로
     시작한다고 알려 줍니다.
   - 처음부터 다시 하려면 `.venv/bin/python bin/cloud down`을 실행한 뒤
     `bin/cloud up`을 다시 실행합니다. `down`은 훈련 환경과 스택을 지우고, 키페어와
     훈련 환경 키는 남깁니다. 스택이 실패했거나 VM에 플랫폼 컨테이너도 DB도 없어서
     물어볼 플랫폼이 없으면 스택만 지웁니다. 플랫폼 VM에 DB가 있으면 먼저
     백업하는데, 백업이 안 되면 아무것도 지우지 않고 중단합니다. 플랫폼 컨테이너가
     멈춰 있으면 먼저 띄우고, VM의 ssh나 Docker가 응답하지 않거나 컨테이너가 뜨지
     않으면 중단합니다. 이 경우 ssh(운영자 키, 보안 그룹, 경로)부터 고치세요.

## 전체 구성

### 실행 위치

플랫폼과 주변 서비스는 VM 한 대에서 돌아가며, 이 VM은 Heat 스택
(`deploy/openstack/platform.yaml`)으로 만듭니다. 플랫폼은 member 역할 사용자
`fsl-range`로 OpenStack API를 호출해 훈련 환경을 관리합니다. 플랫폼 VM에
`CR_SUBSTRATE=range.openstack.connect`가 설정돼 있어서 훈련 환경을 OpenStack에 만들고
관리하는 구조입니다. 세션은 `/api/range/ready/`에서 슬롯이 준비됐다고 나와야 시작할
수 있습니다.

`cr-platform.service`는 cloud-init 단계에서 설치되며, 부팅할 때마다
`/opt/cr/compose.yaml` 기준으로 `docker compose pull`과 `docker compose up -d`를
실행합니다.

- 직접 빌드하는 이미지는 platform, board, corp, corp-db, gns3, kali, waf, edge 여덟
  개입니다. `dev`에 push할 때마다 `.github/workflows/images.yml`로 빌드해
  `ghcr.io/nekonic/cr-<name>`에 올리며, 태그는 커밋 SHA와 `dev`입니다.
- VM은 clone한 커밋의 SHA를 `/opt/cr/.env`에 `CR_IMAGE_TAG`로 적어 두기 때문에
  정확히 그 커밋의 이미지로 뜹니다.
- GitHub는 저장소가 public이어도 첫 push 때 생긴 패키지를 private으로 둡니다. 여덟
  개 모두 한 번씩 public으로 바꿔 두지 않으면 로그인 없는 pull이 실패합니다.
  github.com의 패키지 페이지에서 **Package settings**, **Change visibility**,
  **Public** 순서로 바꾸며, 되돌릴 수 없습니다.
- VM에서 도는 컨테이너는 `cr-platform`, `cr-elasticsearch`, `cr-kibana`, `cr-gns3`,
  `cr-collector`입니다. 로그는 ssh로 접속해 `sudo docker logs cr-platform`
  (다른 컨테이너는 해당 이름)으로 봅니다.
- 아직 push하지 않은 커밋을 띄우려면 `--sideload`를 씁니다(`docs/OPENSTACK.md`
  §5.3).

Elasticsearch의 managed GeoIP downloader는 꺼 두고, 대신
`config/ingest-geoip`의 `GeoLite2-City.mmdb`를 읽게 했습니다. 이 디렉터리는 bind
mount라 컨테이너를 다시 만들어도 남습니다. 클라우드에서는 Elasticsearch가 다운로드
CDN에 접속하지 못해서 cloud-init 단계에서 `bin/fetch-geoip`로 이 파일을 채우며,
파일은 커밋하지 않습니다.

플랫폼은 시작하면 먼저 docker 소켓 그룹을 설정하고, 서비스를 띄우는 동안
백그라운드에서 세 가지를 처리합니다.

- Elasticsearch ingest pipeline 등록. 이벤트마다 시각을 정하고 출발지 주소의 위치를
  찾아 붙이는 pipeline입니다.
- Kibana data view, "Alerts" 검색, "Overview" 대시보드 import
- Kibana 기본 경로를 그 검색으로 지정

이 객체들은 Kibana 기본 space에 있고, 5601번 포트로만 접근할 수 있습니다.

세션을 열면 세션 전용 Kibana space "SOC"가 생깁니다(`compose.yaml`에서 설정하는
`KIBANA_URL`). space id는 `soc-` 뒤에 세션 인덱스 패턴을 붙인 `soc-logs-<slot>`이고,
data view "logs-*"와 "Events" 검색이 들어 있습니다. 이 space에서는 엔진과 센서가
구성도상 이름으로 필드에 나오고, 플랫폼 내부 필드는 숨겨집니다.

플랫폼이 훈련 환경용으로 만드는 OpenStack 네트워크는 관리망 `cr-mgmt` 하나뿐이고,
플랫폼은 이 망으로 훈련 환경 호스트에 접속합니다. 슬롯의 나머지 네트워크는 모두
훈련 환경 호스트 안의 Docker 네트워크입니다. `sN_internet`은 출발지 서브넷 30개를 둔
모의 인터넷, `sN_estate`는 WAF와 대상 시스템이 있는 회사 내부망입니다.

```mermaid
flowchart TB
  person(["브라우저"])

  subgraph cloud["OpenStack 프로젝트 fsl-range"]
    api["OpenStack API<br/>Keystone, Neutron, Nova"]
    subgraph heat["Heat 스택 cr-platform"]
      fip["floating IP<br/>8000, 8002, 3080, ssh, ping"]
      subgraph vm["플랫폼 VM, Ubuntu 24.04"]
        unit["cr-platform.service<br/>docker compose pull, up -d"]
        stack["플랫폼 컨테이너<br/>(다음 그래프)"]
      end
    end
    mgmt["cr-mgmt<br/>플랫폼이 만듦"]
    subgraph rangevm["훈련 환경 호스트 cr-range, Ubuntu 24.04"]
      slots["슬롯마다 docker compose 프로젝트 하나<br/>s1, s2, ..."]
    end
  end

  person -->|":8000"| fip
  fip --> vm
  unit -->|"부팅할 때마다"| stack
  stack -->|"/api/range/fabric/, /slot/"| api
  api -.->|만듦| mgmt
  api -.->|부팅| rangevm
  stack -->|"cr-mgmt로 ssh, docker exec"| rangevm
```

### 세션의 구성

레드팀은 블루팀의 WAF와 IDS를 거쳐 워게임을 공격하고, 센서 경보는 Elasticsearch로
들어갑니다. 플랫폼은 이 경보와 대상 시스템 자체 기록으로 점수를 매깁니다. 첫 번째
점수는 레드팀이 가져간 목표이고, 두 번째 점수는 방어가 맞게 또는 틀리게 판단한
건수(TP, FP, FN, TN)입니다. 공격 성공 여부는 플랫폼이 아니라 대상 시스템 자체
데이터로 정합니다. 플랫폼은 게시판의 경우 공격자가 제출한 해시를 세션을 열 때 떠 둔
게시판 계정 사본과 대조하고, corp의 경우 corp DB의 변경 로그를 읽습니다.

`compose.yaml`에는 플랫폼 VM에서 상시 떠 있는 서비스가 정의돼 있습니다. 플랫폼,
Elasticsearch, Kibana, `gns3`(학습자용 구성도), `collector`이며, `collector`는 훈련
환경의 syslog만 받는 Filebeat입니다.

세션별 서비스는 그 세션에 배정된 슬롯, 다시 말해 훈련 환경 호스트의 docker compose
프로젝트 `sN`에서 돕니다. Kali(마커를 붙이는 프록시와 고객 트래픽), 에지(nftables
라우터), WAF, board·corp와 각각의 MySQL, Suricata 센서 두 개로 구성되며, 센서는
하나가 슬롯의 인터넷 브리지를, 다른 하나가 estate 브리지를 봅니다. 센서 경보와 WAF
audit log는 훈련 환경 호스트의 rsyslog로 `collector`에 보냅니다.

닫힌 세션은 `CR_RETAIN_CLOSED_MINUTES`분(기본 60, `compose.yaml`에서 설정) 동안 DB에
남아 있어서, 그동안 점수와 결과 보고를 볼 수 있습니다. 그 뒤에는 플랫폼이 세션을
케이스, 탐지 기록, 고객 요청, 목표와 함께 삭제합니다. 이 확인은 플랫폼 시작 시와
세션이 닫힐 때마다 하며, 열린 세션은 지우지 않습니다.

워게임을 추가하려면 아래가 필요합니다.

- `compose.yaml`, `scenario.yaml`, `objectives.yaml`을 담은 `wargames/` 아래 폴더
- `redteam/cases/` 아래 케이스 파일
- `platform/range/declaration.yaml`: `cr-range` 항목의 `wargames:` 아래에 워게임
  이름, `cr-waf` 항목의 `names:` 아래에 사이트 이름
- `deploy/range-host/slot.yaml`: WAF가 프록시하는 서비스마다 `x-wargames.fronts`
  아래에 estate 주소의 마지막 옥텟, 서비스마다 `x-wargames.limits` 아래에
  capability와 자원 제한, `waf` 서비스의 `extra_hosts`에 서비스 이름과 estate 주소,
  `kali` 서비스의 `extra_hosts`에 사이트 이름
- `platform/tests/test_containment.py`의 `LEARNER_FACING`과 `CAPABILITIES`에 서비스
  추가
- `deploy/waf/board.com.conf`의 `server` 블록

`platform/wargames.py`는 `scenario.yaml`을 기준으로 워게임을 찾습니다. 워게임은
둘입니다. 게시판은 Django로 만들었고 `loot_verified`로 채점하며, 제출한 해시를 게시판
계정 스냅샷과 대조합니다. corp는 WordPress이고 `effect_observed`로 채점하며, corp DB의
변경 로그를 봅니다.

```mermaid
flowchart LR
  person(["브라우저"])

  subgraph platformvm["플랫폼 VM"]
    console["콘솔과 /api/"]
    scoring["채점"]
    collector["collector<br/>Filebeat, syslog 수신"]
    es[("elasticsearch")]
  end

  subgraph slot["세션 슬롯, cr-range의 compose 프로젝트 sN"]
    kali["kali<br/>공격 터미널<br/>프록시가 케이스마다 라벨"]
    edge["에지<br/>nftables 라우터"]
    edgesensor["sN-inet 쪽<br/>Suricata"]
    waf["waf<br/>nginx + ModSecurity CRS"]
    board["board<br/>+ MySQL"]
    corp["corp<br/>WordPress + MySQL"]
    estate["sN-estate 쪽<br/>Suricata"]
    rsyslog["훈련 환경 호스트의 rsyslog"]
  end

  person -->|":8000"| console
  console -->|"터미널"| kali
  kali --> edge
  edge --> waf
  waf --> board
  waf --> corp
  edgesensor -.->|"eve.json"| rsyslog
  waf -.->|"audit log"| rsyslog
  estate -.->|"eve.json"| rsyslog
  rsyslog -.->|"syslog, 5140/udp"| collector
  collector --> es
  es -->|경보| scoring
  board -.->|자체 기록| scoring
  console --> scoring
```

그래프에 빠진 부분:

- Kali의 raw TCP는 프록시를 거치지 않고 에지를 지나 WAF로 갑니다.
- 스크립트 케이스는 공격자 박스에서 나갑니다. 플랫폼이 Kali 컨테이너에서 고른
  출발지 주소로 `curl`이나 도구를 실행합니다.
- 플랫폼은 센서 룰과 프록시의 케이스 라벨을 쓰고, 공격자 명령 로그와 corp-db의 MySQL
  바이너리 로그(`mysqlbinlog`)를 읽습니다.
- 게시판 자체 기록(`auth_user` 테이블)은 WAF를 거치지 않고 게시판 컨테이너 안에서
  읽습니다.
- 위 명령은 모두 훈련 환경 호스트의 `mgmt` 주소로 ssh 접속한 뒤, 슬롯 컨테이너
  (`sN-kali`, `sN-board` 등)에 `sudo docker exec`로 실행합니다.

Kali 터미널은 레드팀 콘솔에 있고, 레슨과 시나리오에서는 블루팀 콘솔의 Kali 창에도
뜹니다. 플랫폼 안의 ttyd가 훈련 환경 호스트의 `mgmt` 주소로 ssh 접속한 뒤 세션 슬롯의
Kali 컨테이너에 `docker exec`로 들어가는 구조입니다(`/vm-terminal/kali/?arg=<세션 id>`).
프롬프트는 `(root㉿kali)`입니다. WAF 터미널도 같은 방식으로 슬롯의 WAF 컨테이너에
root로 붙습니다. 네트워크 구성은 `docs/ARCHITECTURE.md`를 보세요.

## OpenStack 운영

위 단계는 최단 경로만 다뤘고, 여기서는 부분별로 자세히 설명합니다.

클라우드마다 다른 값은 모두 `deploy/openstack/cloud.yaml` 파일 하나에 모았습니다.
gitignore 대상이며 `deploy/openstack/cloud.example.yaml`을 복사해 만듭니다. 들어 있는
항목:

- Keystone URL, region, interface, domain, 프로젝트와 member 사용자
- 비밀번호를 읽을 위치: `password_file` 또는 `password_env`. 비밀번호 자체는 파일에
  넣지 않음
- 외부 네트워크, DNS, 테넌트 MTU, platform·estate·mgmt CIDR
- 베이스 이미지 이름, availability zone, 슬롯 수
- flavor 두 개: `platform`과 `range`(훈련 환경 호스트)
- 운영자 키페어와 키 파일, 훈련 환경 키
- 스택, 저장소, ref

스크립트와 Heat 스택은 모두 이 파일을 읽습니다. 해석할 수 없는 값이 있으면 아무것도
건드리기 전에 거부하고, 잘못된 키를 전부 알려 줍니다.

클라우드에 올려 둘 이미지는 하나뿐입니다. Canonical의 기본 Ubuntu 24.04 클라우드
이미지를 수정하지 않고 `compute.base_image`에 적은 이름으로 업로드합니다. 다운로드,
체크섬, `openstack image create` 명령은 `docs/OPENSTACK.md`에 있습니다. VM 두 대 모두
이 이미지로 부팅하고, 부팅할 때 cloud-init으로 각자 설정합니다.

- 플랫폼 VM: 저장소를 clone하고 `compose.yaml`을 띄움
- 훈련 환경 호스트: Nova user data로 설정 번들(`deploy/range-host/setup.sh`)을 받아
  Docker를 설치하고, 플랫폼의 `CR_IMAGE_TAG`로 GHCR에서 훈련 환경 이미지를 전부
  pull한 뒤, 초기화에 쓸 대상 시스템 볼륨 원본을 떠 둠

운영자 PC에서, `.venv`에 OpenStack CLI를 설치한 상태(3단계)로 실행합니다.

```bash
.venv/bin/python bin/cloud up        # 플랫폼 VM, 그다음 훈련 환경 전체
.venv/bin/python bin/cloud down      # DB 백업, 키 보관, 훈련 환경과 스택 제거
```

`up`은 다음 순서로 진행합니다.

1. 플랫폼 Heat 스택(`deploy/openstack/platform.yaml`)이 없으면 만듭니다.
   `--replace`를 주면 기존 스택을 `bin/platform-rebuild`로 교체합니다.
2. API가 응답할 때까지 기다립니다.
3. 플랫폼 자체 훈련 환경 API를 차례로 호출합니다. 먼저 fabric(관리망, 키페어,
   보안 그룹), 다음으로 slot(훈련 환경 호스트 부팅 또는 교체)을 호출하고, 훈련 환경
   호스트가 떠서 설정을 마치면 configure를 호출합니다.
4. `/api/range/ready/`가 ready가 될 때까지 기다립니다.
5. 예전 VM 방식 훈련 환경이 남긴 자원을 지우고(`DELETE /api/range/leftovers/`) 지운
   항목을 출력합니다.

처음 만난 drift, 막힌 슬롯, 실패한 설정, 거부된 configure 가운데 하나라도 나오면 그
자리에서 멈추고 이유를 출력합니다.

`up`과 `down`은 모두 테스트 클라우드에서 돌려 봤습니다. 2026-10-20에 실제로 돌린
경로는 `up --replace --sideload`, 컨테이너가 멈춘 채 인계를 받지 못한 플랫폼에서의
일반 `up`, `down`, `down` 뒤의 `up`(행이 있는 가장 최근 백업 복원)입니다
(`docs/DECISIONS.md` 2026-10-20, "Live checks of the bring-up paths").
같은 날 수정 두 건을 더 넣고 나서 컨테이너가 멈춘 플랫폼에서의 `down`, 비밀번호 줄이
없는 플랫폼에서의 `up`, 처음 생성한 훈련 환경 키, 훈련 환경 VM을 다시 빌드하지 않는
`down` 뒤의 `up`도 돌렸고, VM 한 대에 빈 클라우드를 올려 §9 전체도
돌렸습니다(`docs/DECISIONS.md` 2026-10-20, "The one-VM trial and the last bring-up fixes").
모두 훈련 환경 호스트 도입 전, 훈련 환경이 VM 여러 대로 돌던 시기의 기록입니다. 단계는
`docs/OPENSTACK.md` §5에 있습니다.

플랫폼 VM만 만들거나 교체하려면 `bin/platform-rebuild`만 실행합니다.

```bash
.venv/bin/python bin/platform-rebuild            # --cloud PATH, --ref REF
```

무엇이든 지우기 전에 ref 커밋에 해당하는 이미지 여덟 개를 ghcr.io에서 로그인 없이
pull할 수 있는지 확인합니다. 이어서 훈련 환경 키(아래)를 보관하고 DB를 백업한 뒤
(ssh로 `bin/backup` 실행), 스택을 지우고 `cloud.yaml`의 파라미터 전체로 다시 만들어
`/api/sessions/`가 응답할 때까지 기다립니다. `bin/platform-rebuild`와
`bin/cloud down`이 `backups/`에 남기는 DB 백업 개수는 `cloud.yaml`의
`backups.keep`(기본 1)으로 정합니다.

새 VM은 `ref`를 clone하고, 그 커밋 태그가 붙은 이미지를 pull해서 뜹니다. 클라우드
값은 cloud-init 단계에서 `/opt/cr/openstack.env`에 기록됩니다. 비밀번호와 플랫폼의
훈련 환경 ssh 키, 이 두 비밀은 스택에 넣지 않습니다. Nova 메타데이터 서비스는
컨테이너를 포함한 VM의 모든 프로세스에 user data를 내주기 때문에, 스택에 넣은 비밀은
VM 안 어디서든 읽힙니다. VM이 ssh에 응답하고 cloud-init이 끝나면
`bin/platform-rebuild`가 ssh로 다음을 실행합니다.

1. `/opt/cr/openstack.env`에 `CR_OPENSTACK_PASSWORD` 추가
2. 플랫폼 데이터 볼륨의 `/data/ssh/id_ed25519`에 훈련 환경 키 기록
3. 백업해 둔 DB 복원. 이전 VM에 DB가 없었으면 `backups/`에서 행이 있는 가장 최근
   백업 복원
4. 플랫폼 컨테이너 재생성

훈련 환경 키는 운영자 PC의 `keys.range` 파일(모드 0600)입니다. 이 파일이 없으면
상황에 따라 처리가 다릅니다.

- 스택이 없거나 스택의 VM에 DB가 없으면 `bin/platform-rebuild`가 새로
  생성(`ssh-keygen`, ed25519)
- DB가 있는 VM을 교체할 때는 실행 중인 플랫폼에서 한 번 복사해 옴
- 실패한 스택을 교체할 때는 거부

키가 그대로 남으므로 훈련 환경 호스트와 `cr-platform` 키페어는 새 플랫폼도 계속
신뢰하고, 플랫폼을 교체하는 동안 훈련 환경은 그대로 둬도 됩니다.

아직 push하지 않은 커밋을 띄울 때는 두 명령 모두 `--sideload NAME=TARBALL`
(여러 번 지정 가능)을 씁니다. TARBALL은 이 체크아웃에서 빌드한 이미지 하나를
`docker save`로 저장한 파일입니다. VM은 여전히 `ref`를 clone하고 그 커밋의 이미지를
전부 pull하며, 재구축 과정에서 추가로 다음을 합니다.

- git bundle로 이 체크아웃의 HEAD를 checkout
- tarball마다 `docker load`하고 clone한 커밋의 태그를 붙임. 플랫폼 VM의 compose는 이
  태그를 쓰지만, 훈련 환경 호스트는 이 태그로 GHCR에서 직접 pull하므로 sideload한
  이미지를 받지 못함
- 모든 서비스 재생성(`--force-recreate`). 그래서 bind mount한 파일도 HEAD 기준이 됨

무엇이든 지우기 전에 두 경우는 거부합니다. `ghcr.io/nekonic/cr-NAME:<commit>`
하나만 담겨 있지 않은 tarball, 그리고 이미지를 빌드한 커밋과 HEAD 사이에 빌드
컨텍스트(`.github/workflows/images.yml`)가 달라진 이미지입니다. sideload한 VM을
재부팅하면 clone한 커밋의 이미지를 GHCR에서 pull하면서 sideload한 이미지를 덮어쓸 수
있으니, 재부팅하지 말고 push한 뒤 재구축하세요.

스택의 `address` 출력값이 floating IP입니다. 콘솔은 `http://ADDRESS:8000/`이고 로그인
없이 열립니다. 9200과 5601은 VM loopback에만 열려 있고, 5140/udp는 VM의 모든
주소에서 받습니다.

VM의 체크아웃 위치는 `/opt/cr`이고 소유자는 `ubuntu`입니다. compose,
`bin/backup`, 아래 복원 절차는 이 디렉터리에서 실행하세요. 마지막 부팅의 기동 결과는
`systemctl status cr-platform`으로 봅니다.

`bin/cloud up`이 거치는 훈련 환경 단계는 직접 호출해도 됩니다. 먼저 fabric입니다.

```bash
curl -s -X POST -H "Content-Type: application/json" -d "{}" http://ADDRESS:8000/api/range/fabric/
```

`GET`은 없는 것, 있는 것, 선언과 달라진 것(drift), 남은 것을 보여 주고, `DELETE`는
fabric을 내립니다. 서버가 붙어 있으면 `DELETE`는 거부됩니다.

그다음 POST 한 번이면 훈련 환경 호스트 `cr-range`가 베이스 이미지로 부팅되고, user
data로 설정 번들이 들어갑니다. 포트는 두 개를 답니다. `mgmt` 쪽 포트는 보안 그룹
`cr-mgmt`(플랫폼만 접속 가능)를 쓰고, 플랫폼 자체 네트워크 쪽 포트는 보안 그룹
`cr-egress`(인바운드 없음)를 쓰는 이미지 pull용입니다. 설정을 마치고 ready를 알리면
플랫폼이 두 번째 포트를 떼어 내므로, 설정이 끝난 훈련 환경 호스트에는
`cr-range.mgmt`만 남고 인터넷으로 나가는 경로도, DNS 리졸버도 없습니다.

```bash
curl -s -X POST -H "Content-Type: application/json" -d "{}" http://ADDRESS:8000/api/range/slot/
```

같은 경로로 `GET`하면 훈련 환경 호스트 설정이 `/var/lib/cr/ready`를 남길 때까지
`SETTING_UP`, 설정이 실패하면 `SETUP_FAILED`가 나옵니다. 실패하면
`/api/range/ready/`는 슬롯 단계를 `SETUP_FAILED`로 보고하면서 훈련 환경 호스트의
`/var/log/cr-setup.log`를 가리키고, `bin/cloud up`은 그 이유를 출력하며 멈춥니다.
이미 떠 있는 훈련 환경 호스트에 같은 POST를 보내면, 설정에 실패했거나 이미지 태그·설정
번들이 플랫폼과 다를 때 호스트를 교체합니다. 세션이 슬롯을 잡고 있으면 교체하지
않습니다.

그다음 `POST /api/range/configure/`를 호출하면 슬롯마다 아래 작업이 진행됩니다.
플랫폼이 `deploy/range-host/slot.yaml`과 워게임별 `wargames/<w>/compose.yaml`로 슬롯
compose 파일을 만들어 ssh로 훈련 환경 호스트에 올리고
`deploy/range-host/slot.sh up N`을 실행합니다. 이 스크립트는 compose 프로젝트 `sN`을
띄우고, Kali와 에지에 출발지 주소를 붙이고, 훈련 환경 호스트의 rsyslog가 슬롯 로그를
전달하도록 설정합니다. 끝으로 플랫폼이 두 센서에 기본 룰을 넣습니다.

`POST /api/range/slot/rebuild/`는 슬롯의 compose 프로젝트를 볼륨째 내립니다. 바꾼
데이터와 룰은 남지 않으니, 다시 띄우려면 `configure/`를 실행하세요.

세션을 닫으면 `slot.sh reset N`으로 그 슬롯을 제자리에서 초기화합니다.

- Kali와 WAF: 컨테이너 재생성
- 대상 시스템: 지운 뒤 훈련 환경 호스트에 떠 둔 원본 볼륨으로 복구
- 에지: neighbour 테이블만 비움. 에지와 센서는 계속 돎
- 슬롯 로그: 제자리에서 비우고 센서가 로그 파일을 다시 엶. 이어서 플랫폼이 두
  센서에 기본 룰을 다시 넣음

초기화하는 동안 `GET /api/range/ready/`에는 phase `RESETTING`이 나오고 세션은 열 수
없습니다. 초기화에 실패하면 이유와 함께 `RESET_FAILED`가 나오며,
`POST /api/range/configure/`로 다시 시도합니다.

훈련 환경을 몇 벌 세울지는 `cloud.yaml`의 `compute.slots`(기본 1)로 정합니다.
슬롯마다 훈련 환경 호스트에 compose 프로젝트 `sN`을 따로 두고, 인터넷·estate
네트워크도 따로 만듭니다. 슬롯 N의 estate는 `network.estate`의 N번째 /24(예제 기준
`10.30.N.0/24`)이고, 컨테이너 이름은 `sN-<service>`입니다. 세션 하나가 슬롯 하나를
차지하므로 슬롯 수만큼 세션을 동시에 돌릴 수 있고, 세션을 닫으면 그 슬롯만
초기화합니다. `slot/`, `slot/rebuild/`, `configure/`는 `?slot=N`을 받으며, 생략하면
모든 슬롯에 적용됩니다.

`GET /api/range/leftovers/`는 훈련 환경 호스트 도입 전 VM 방식 훈련 환경이 프로젝트에
남긴 자원을 보여 줍니다. 당시의 VM과 이미지 빌더, 폐기한 세그먼트의 포트·서브넷·
네트워크, 보안 그룹 `cr-range`와 `cr-build`, 당시 이미지가 대상입니다. 같은 경로로
`DELETE`하면 지우며, `bin/cloud up`이 마지막 단계에서 호출합니다.

훈련 환경은 Heat 스택 밖에 있어서 플랫폼 VM보다 오래 남을 수 있습니다.
`bin/platform-rebuild`로 플랫폼을 교체하면 훈련 환경 키가 유지되므로 슬롯과 fabric도
계속 동작합니다. 이후 `POST /api/range/fabric/`를 호출하면 새 서버가 `mgmt`에 다시
붙고, `configure/`를 호출하면 훈련 환경 syslog가 새 서버로 향합니다. 키를 보관하지
않고 스택을 직접 지우면 새 VM이 새 키를 만들고, fabric은 예전 키페어를 drift로
보고합니다. 이때는 먼저 `/api/range/slot/`(`?slot=` 없이 보내면 훈련 환경 호스트까지
지웁니다)과 `/api/range/fabric/`에 `DELETE`를 보내세요.

스택은 `keys.operator`가 가리키는 키페어로 부팅하므로 이 키페어가 프로젝트에 먼저
있어야 합니다.

```bash
openstack keypair create --public-key PUBLIC_KEY_FILE fsl-claude
```

## 포트

| 포트 | | 사용처 |
|---|---|---|
| 8000 | 콘솔, `/api/`, Kibana(`/kibana/`), 터미널(`/vm-terminal/kali/`, `/vm-terminal/waf/`) | 사용자 브라우저 |
| 8002 | 레드·블루팀 콘솔의 웹사이트 창(`/site/<세션 id>/<host>/`). 요청은 고객 주소로 Kali 컨테이너에서 에지를 거쳐 해당 세션의 WAF로 감 | 사용자 브라우저 안의 iframe |
| 3080 | `gns3`: GNS3 3.1 API와 웹 UI. 학습자용 구성도(아래) | 사용자 브라우저 안의 iframe, `mgmt`를 거친 `platform/gns3.py` |
| 5140/udp | `collector`, Filebeat의 syslog 입력 | 훈련 환경 호스트의 rsyslog. 슬롯마다 센서 두 개의 경보와 WAF audit log 전송 |
| 5601 | Kibana 직접 접속. 플랫폼 호스트 loopback에만 열림. 8000번의 `/kibana/`는 세션별 space와 그 안의 Discover만 제공 | 운영자(ssh 터널) |
| 9200 | Elasticsearch | acceptance 테스트 |

8000과 8002는 플랫폼 이미지 안의 nginx에서 서비스합니다. 8002는 대상 사이트 전용
origin이라 대상 시스템에 심긴 스크립트가 콘솔을 읽거나 조작하지 못합니다. 다만 쿠키는
포트가 아니라 호스트 단위라서 그런 스크립트도 콘솔로 갈 쿠키를 설정할 수는 있는데,
콘솔은 쿠키를 쓰지 않습니다. `/vm-terminal/`은 nginx가 플랫폼 안의 ttyd 프로세스로
넘기고, ttyd는 훈련 환경 호스트의 `mgmt` 주소로 ssh 접속해 `docker exec`로 슬롯
컨테이너를 엽니다.

**학습자용 구성도(3080번 포트).** 세션마다 학습자가 지키는 회사 네트워크를 실습용
네트워크 구성도로 보여 줍니다.

- 장비 이름 대신 역할 이름을 씁니다. 호스트 쪽 링크 끝에는 인터페이스와 프리픽스 없이
  주소만 표시하고, DB 스위치와 관제 스위치로 가는 링크에는 라벨을 달지 않습니다.
  DMZ는 캡션에 네트워크를 덧붙이고, 인터넷·DB존·관리망은 이름만 둡니다.
- 관리망, 플랫폼, 장비 자체의 이름은 표시하지 않습니다.
- 구성도는 슬롯과 그 세션의 워게임마다 한국어로 하나씩 두고, GNS3에서 모든 노드를
  시작한 상태로 열어 둡니다.
- 노드는 고정된 busybox 이미지 하나로 호스트마다 띄운 표시용 컨테이너라서 링크 끝이
  전부 초록색입니다. 실제 장비는 훈련 환경에서 돕니다.
- 전체 배선은 `deploy/topology/system/`에 있으며 학습자에게는 보여 주지 않습니다.
- 블루팀 콘솔의 구성도 창(구성도 탭)은 `/static/web-ui/map.html`을 iframe으로
  띄웁니다. 이 페이지는 읽기 전용으로 로그인하고 웹 UI 사용 통계 전송을 끈 다음,
  해당 세션의 구성도를 창 크기에 맞춰 보여 줍니다. 보기 전용이라 편집 컨트롤은 없고,
  드래그로 이동하고 휠로 확대·축소합니다.
- `gns3` 컨테이너에는 `CAP_NET_ADMIN`, `/dev/net/tun`, Docker 소켓, 호스트 pid
  네임스페이스가 붙어 있습니다. GNS3가 스위치를 돌리고 docker 노드를 시작하려면
  필요합니다(`docs/ARCHITECTURE.md`, 네트워크 구성도).

`compose.yaml`은 9200과 5601을 늘 `127.0.0.1`에 publish하고, 8000, 8002, 3080은
`CR_PUBLISH`, 5140/udp는 `CR_SYSLOG_PUBLISH`로 따로 지정하지 않으면 `127.0.0.1`에
publish합니다. 플랫폼 VM에서는 8000, 8002, 3080을 VM 자신의 주소(`CR_PUBLISH`)에,
5140/udp를 `0.0.0.0`(`CR_SYSLOG_PUBLISH`)에 publish합니다. 8000, 8002, 3080은 플랫폼
템플릿의 보안 그룹에서 엽니다(`docs/OPENSTACK.md` §3.5).

대상 시스템은 외부에 공개하지 않습니다. 명령줄 케이스와 acceptance 테스트도 콘솔과
마찬가지로 훈련 환경 안에서 대상 시스템에 접속합니다. 훈련 환경 안에서 대상 시스템은
WAF 뒤 80번 포트에 있고, `http://board.com`과 `http://corp.com`은 `Host` 헤더로
구분하는 가상 호스트입니다. 슬롯의 Kali 컨테이너에는 슬롯 compose 파일로 이 두
이름만 `/etc/hosts`에 들어가며, 둘 다 그 슬롯의 WAF를 가리킵니다.

## 세션 진행

콘솔(`http://ADDRESS:8000/`)에 접속해 세션을 시작합니다. 레슨이나 시나리오는 공격과
방어를 모두 담은 블루팀 콘솔로 열리고, 워게임(사람 대 사람)은 공격자에게 레드팀
콘솔, 방어자에게 블루팀 콘솔을 엽니다. 콘솔은 한국어로만 제공합니다.

- **레드팀** 콘솔(공격자용): 목표, "탈취한 해시 제출", Kali 터미널, 대상 시스템을
  띄우는 웹사이트 창. 미리 준비한 공격은 실행하지 않으며, 스크립트 케이스는
  하네스(`redteam/run.py`, acceptance 테스트)와 시나리오 엔진이 실행합니다.
- **블루팀** 콘솔: 도구를 프레임으로 띄운 사이드바
  - Kibana: 세션 전용 data view로 Discover를 엶. 레슨에서는 빈 쿼리, 그 밖에는 경보
    쿼리
  - WAF 터미널
  - 웹사이트 창: Chrome 네트워크 패널처럼 개발자 도구를 배치한 사이트 브라우저
  - 구성도 창(GNS3 구성도)
  - 경보 창과 IDS 룰 창(시나리오나 레슨에 필요할 때)
  - 구분선 아래 Kali 터미널. 레슨과 시나리오에서만 보이고 워게임에서는 숨김

  블루팀 콘솔은 `/api/`를 호출해 세션, 사이트 요청, 기초 레슨이나 단계형 시나리오의
  단계와 힌트, 시나리오 상태와 정·오탐 판단, ingest, 탐지 기록을 가져옵니다. 세션이
  닫히면 세션 페이지에 결과가 나옵니다. 탈취된 목표를 먼저 보여 주고, 이어서 공격을
  몇 건 탐지했고 정상 요청이 몇 건 통과했는지를 평이한 문장으로 보여 줍니다.

안내 없이 연 세션(`{"scenario": "board"}`, 홈 카드의 "워게임 시작")은 전체 방어
설정, CRS paranoia level 1(PL1)로 하는 일반 워게임입니다. 워게임에 선언된 다른 방어
설정은 `{"defense": "<name>"}`으로 고릅니다(`minimal`은 PL4). 에이전트는
`PUT /api/sessions/<id>/waf/`로 WAF 설정을 조정하고, `GET`으로 WAF 파일의 현재
내용을 받습니다.

### 레슨

홈 화면에는 기초 레슨 여섯 개가 과정 두 개로 묶여 있습니다. 레슨은 id로 엽니다
(`{"lesson": "f1"}`부터 `f6`까지). `{"guidance": true}`만 보내면 F1이 열립니다.

과정 1 "로그 분석 기초"(F1-F3)는 훈련 환경을 읽기만 합니다.

- F1: 구성도에서 공격자와 웹 서버 주소, customers에서 출발한 요청이 지나는 장비, DMZ
  대역, 로그 서버를 읽습니다.
- F2: 게시판 검색창으로 검색하고, 개발자 도구에서 메서드, 파라미터, 경로, 상태
  코드를 확인합니다.
- F3: 직접 작성한 KQL로 그 검색을 Kibana에서 찾고, `and`·`not`으로 리버스 프록시 뒤
  구간의 건수를 센 다음, 해당 행의 출발지와 X-Forwarded-For 헤더를 읽습니다.

과정 2 "공격 탐지 실습"(F4-F6)은 훈련 환경을 바꿉니다. 학습자는 Kali 창과 웹사이트
창에서 공격하고, 같은 블루팀 콘솔에서 방어합니다.

- F4: XSS 요청을 보내고(퍼센트 인코딩된 URL, CRS 이상 점수), IDS 룰을 작성한 뒤,
  대소문자로 우회하고 `nocase`와 올린 `rev`로 고칩니다(defense `xss-gap`).
- F5: 게시판 `sort` 파라미터에 sqlmap을 돌리고, 판정, 실행이 남긴 WAF 기록 수
  (Kibana), 탐지한 룰을 읽습니다.
- F6: 범위가 넓은 WAF 예외 처리(defense `overbroad`)를 악용해 탐지되지 않은 채 계정을
  덤프하고, 두 배가 된 감점을 확인한 뒤 예외를 지우고 공격을 다시 실행합니다.

과정의 첫 레슨은 과정 안내로 시작합니다. 안내 화면에는 과정에서 할 일과 필요한 참고
카드(KQL, Kibana 필드, 구성도의 주소, 룰 형태)가 나오고, 같은 카드는 레일에서 여는
참고 열에도 남습니다. Kibana 단계의 강조 표시는 학습자가 맞는 쿼리를 쓸 때까지 쿼리
입력창에 머뭅니다. 답도 Kibana에 그 쿼리가 있어야 인정하므로, 구성도나 참고 열에서
짐작한 값으로는 통과하지 못합니다.

답은 모두 학습자 자신의 기록이나 세션 구성도에서 읽으며, 고정된 정답 키는 없습니다.
학습자가 직접 돌린 sqlmap도 다른 레드팀 행동과 똑같이 두 점수에 모두 반영됩니다.

레슨 노트는 블루팀 콘솔에서 창 옆에 붙는 열로, 레슨 단계를 안내합니다.

- 플랫폼이 단계마다 확인하고(`POST /api/sessions/<id>/lesson/steps/<step>/check/`),
  단계 진입, 통과, 건너뜀을 기록합니다.
- 레슨은 첫 단계의 창으로 열립니다. 단계 대상은 구성도, 페이지, 개발자 도구,
  Kibana, 터미널 줄에 강조 표시됩니다.
- 세션 응답에는 정답 키가 들어 있지 않습니다. 단계 명령은 학습자가 그 단계에 들어간
  뒤에야 입력할 문구로 나오고, 공격을 대신 실행하는 버튼은 없습니다.
- 도움은 단계마다 넛지, 힌트 순으로 나옵니다. 단계 카드에서 앞으로 가는 버튼은
  하나뿐인데, 통과한 단계에서는 "다음", 그 밖에는 "건너뛰기"입니다. "건너뛰기"는
  단계를 건너뜀으로 기록하고 다음 단계로 넘길 뿐, 학습자 대신 아무것도 실행하지
  않습니다. 힌트를 썼는지는 세션에 기록되고, 결과 화면에는 틀린 뒤 통과한 단계 수도
  나옵니다.
- 레슨의 마지막 단계는 강조 표시와 힌트 없이 혼자 풉니다.

레슨이 재생하는 정상 요청은 정상 케이스로 채점합니다. 첫 레슨의 요청은 세션을 열 때,
이후 레슨의 요청은 학습자가 그 레슨의 단계를 처음 통과하거나 건너뛰거나 힌트를 볼 때
재생합니다.

한 과정의 레슨은 같은 세션에서 이어서 진행합니다. 레슨의 마지막 단계를 통과하거나
건너뛰면 레슨 노트에 과정의 다음 레슨 이름이 나오고 대기합니다. 학습자가 "다음
레슨"을 누르면 같은 세션에서 다음 레슨이 시작되며
(`POST /api/sessions/<id>/lesson/ {"lesson": "f2"}`), 그 레슨의 방어 설정도 이 호출로
그 자리에서 적용됩니다. 레슨 사이에 훈련 환경을 초기화하지 않고, 레슨마다 시작한 뒤에
일어난 일만 판정합니다. 과정이 끝나면 레슨 노트에 그 과정에서 들은 레슨이 레슨별
통과 단계 수와 함께 나열되고, 같은 버튼은 확인을 받은 뒤 세션을 종료합니다. 과정 1은
훈련 환경을 읽기만 하므로 결과 화면에 레슨만 나오고 점수는 나오지 않습니다.

### 시나리오

기초 다음 단계는 시나리오입니다(`{"scenario": "1.1"}`). 고객과 공격자가 게시판을 쓰는
동안 학습자가 실제 도구로 방어합니다.

- 시나리오는 상황 설명으로 시작하며, 상황, 목표, 평가 방법, 시간이 나옵니다. 시간과
  공격 일정은 이 화면에서 시작을 누른 순간부터 흐릅니다.
- 상단 상태 표시줄에는 남은 시간, 최근 1분간의 고객 차단과 경보 요청, 탈취된 목표가
  나옵니다.
- 학습자에게 보이지 않는 공격 일정에 따라 평소 경로로 공격이 들어옵니다. 공격으로
  덤프한 계정이 게시판 계정과 일치하면 첫 번째 점수에 들어갑니다.
- "최종 점검 시작"을 누르거나 일정이 되면 몇 분짜리 최종 점검이 열리고, 플랫폼이
  과제 유형별로 판정합니다.
  - judgement(판단): 점검을 시작할 때 목록에 있던 경보 항목을 모두 올바르게 판단하면
    통과입니다. 지금까지 나온 항목 중 판단하지 않은 것이 있으면 학습자가 누른 "최종
    점검 시작"은 시작되지 않고 남은 개수를 알려 줍니다. 차단된 고객은 보고만 하고
    집계하지 않습니다.
  - availability(가용성)와 unknown: 차단된 고객이 없고 공격을 모두 막아야 통과입니다.
    시나리오 2.3은 이상 점수 임계치도 5/4 이하여야 합니다.
  - detection(탐지): 모든 공격이 Suricata 경보를 일으키고 그 경보가 공격 수법을
    짚어야(corroborated) 하며, 고객 요청은 경보를 하나도 일으키지 않아야 통과입니다.

시나리오 목록:

- `1.1` "고객 요청과 공격 구분하기": 경보가 난 요청마다 고객인지 공격인지, 공격이
  데이터를 가져갔는지 판단(`/api/sessions/<id>/triage/`)
- `1.2`, `1.3`: 물려받은 예외 규칙 때문에 sqlmap이 계정을 가져가는 상황에서 경보
  판단. 1.3은 공격 종류까지 판단
- `2.1` "한글 검색 오탐 해결": PL3 WAF에 거부당하는 고객이 다시 서비스를 받게 하되
  sqlmap은 통과시키지 않음
- `2.2`, `2.3`: PL2에서 차단된 고객이 서비스를 받게 함. 2.3은 PL3에서 이상 점수
  임계치를 5/4로 낮추면서 해결
- `3.1`~`3.4`: IDS 룰 창에서 sort 공격, 그 tamper 변형, 댓글 XSS에 IDS 경보가 나게
  함. 두 번째 점수에만 반영
- `4.1`: 처음 보는 sqlmap 변형과 새 오탐을 도움 없이 처리

힌트는 학습자가 막혔을 때 제안하고, 열어 본 경우에만 기록합니다. 결과 보고에는 차단된
고객과 공격 타임라인이 추가됩니다. 자세한 내용은 `docs/ARCHITECTURE.md`의
"시나리오" 절을 보세요.

### 명령줄에서 케이스 실행

스크립트 케이스는 acceptance 테스트처럼 명령줄에서도 돌릴 수 있습니다. 대상 시스템을
외부에 공개하지 않으므로 하네스는 훈련 환경 안쪽인 플랫폼에서 실행합니다.

```bash
sudo docker exec cr-platform python redteam/run.py --tool-target http://board.com
```

하네스는 `--cases` 파일명과 `case_file`이 일치하는 시나리오로 세션을 엽니다
(`board.yaml`은 board, `corp.yaml`은 corp, 그 밖에는 board). 그다음 각 케이스를
`--platform`(기본 `http://localhost:8000`)의 플랫폼을 거쳐 실행합니다.
`--tool-target`(기본 `http://board.com`)은 도구 컨테이너에서 대상 시스템에 접속할 때
쓰는 주소입니다. corp를 돌리려면 `--cases redteam/cases/corp.yaml`을 추가하세요.

## 검증

```bash
bin/verify --changed  # 변경이 닿는 단위 테스트와 ratchet만
bin/verify --fast     # 단위·API 테스트와 지표, 스택 불필요
bin/verify            # test/의 acceptance 테스트까지, 실행 중인 스택 대상
```

훈련 환경은 OpenStack에서만 돌아가므로 노트북에서는 `--changed`와 `--fast`까지만
돌릴 수 있고, acceptance 테스트는 플랫폼 VM에서 돌려야 합니다.

`--changed`는 `dev`와의 merge-base(또는 지정한 커밋이나 `A..B`)를 기준으로, 바뀐
파일마다 닿는 테스트와 그 이유를 출력합니다. 아무것도 실행하지 않고 그 결과만 보려면
`bin/select-tests`를 씁니다. `--live`를 함께 주면 변경이 닿는 acceptance 모듈까지
실행합니다(`bin/acceptance --only`).

전체 실행은 플랫폼을 재시작하고 대상 시스템, 룰, 공격자 출발지를 초기화하므로 다른
사람이 쓰는 스택에서는 돌리지 마세요. 삭제하는 세션은 전체 실행이 직접 만든 것뿐입니다.

acceptance 단계는 `bin/acceptance`로 실행합니다. Elasticsearch만 읽는 검사용 pytest
프로세스 하나와, 세션을 같이 쓰는 모듈 묶음마다 프로세스를 하나씩 띄웁니다. 묶음은
슬롯이 비는 대로 시작하므로 훈련 환경 슬롯 수(`GET /api/range/ready/`의
`max_sessions`)만큼 동시에 돕니다. 세션 두 개를 한꺼번에 여는
`test_concurrent_sessions`는 슬롯 두 개를 씁니다. unit 테스트는 그 옆에서 가장 낮은
CPU 우선순위로 돕니다. 레드팀 실행은 sqlmap 케이스 가운데 덤프 하나만 쏘며,
`CR_SQLMAP_VARIANTS=1 bin/verify`로 돌리면 sqlmap 변형을 전부 쏩니다.

분할 결과는 `bin/acceptance --plan`으로 보고, 설명은 `test/README.md`에 있습니다.
플랫폼 VM은 localhost에서 수신하지 않으므로 VM에서는
`CR_PLATFORM_URL=http://<address>:8000 bin/verify`로 실행하세요. acceptance 테스트는
모두 OpenStack에서 돌고, 일부러 skip하는 테스트가 하나 있습니다. `test_lesson.py`의
F1 구성도 테스트는 코스마다 한 번씩 도는데, F1으로 시작하지 않는 코스(`c2`는 F4로
시작)에서는 skip하므로 전체 실행 결과에 skip이 하나 나옵니다.

세션을 직접 지우려면 `bin/prune`을 씁니다. `--apply` 없이 실행하면 dry run입니다.

```bash
bin/prune --keep 20 --apply      # 최신 20개만 남김
bin/prune --ids FILE --apply     # FILE에 적힌 닫힌 세션만
```

템플릿에 Tailwind 클래스를 추가했다면 `bin/build-css`를 실행하세요. 생성된
스타일시트는 커밋 대상이고, 최신 여부를 검사하는 테스트는 없습니다.

## 백업과 복원

플랫폼 DB에는 세션, 케이스, 탐지 기록, 목표, 룰셋, 비활성화한 룰이 들어 있습니다.
플랫폼 VM `cr_platformdata` 볼륨의 `/data/db.sqlite3`, SQLite 파일 하나이고 백업
대상은 이것뿐입니다. Elasticsearch의 `cr_esdata` 볼륨과 `cr_collectordata`에 있는
collector registry는 백업하지 않으며, `bin/cloud down`으로 VM을 지울 때 함께
사라집니다. `down`은 먼저 DB를 백업해 `backups/`에 사본을 남깁니다.

```bash
CR_PLATFORM_EXEC="ssh -i ~/.ssh/fsl_claude ubuntu@ADDRESS sudo docker exec -i cr-platform python -" \
  bin/backup      # 플랫폼이 서비스 중일 때 backups/db-<UTC time>.sqlite3를 씀
```

`CR_PLATFORM_EXEC`는 플랫폼 환경에서 `python -`을 실행하는 명령입니다.
`bin/backup`은 다음 순서로 동작합니다.

1. SQLite `VACUUM INTO`로 빈 공간을 정리한 사본을 플랫폼 컨테이너 안 임시 파일에 씀.
   삭제한 세션이 차지하던 공간은 복사되지 않음
2. 그 파일을 1 MiB 단위로 스트리밍해 가져옴. 수 GB짜리 DB는 ssh로 몇 분 걸리며,
   600초 동안 데이터가 오지 않을 때만 중단
3. `PRAGMA integrity_check`로 사본 검사
4. 어느 단계든 실패하면 아무것도 남기지 않음

새 사본이 검사를 통과하면 `--keep`(기본 1, 새 사본 포함)을 넘는 이전
`db-<UTC time>.sqlite3` 파일을 지웁니다. 이름이 다른 파일은 건드리지 않습니다.
`bin/platform-rebuild`는 VM을 교체할 때 이 백업과 복원을 직접 실행합니다.

직접 복원하려면 파일을 VM에 복사한 뒤, VM에서 플랫폼을 멈추고 진행합니다.

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

`--entrypoint sh`는 인자를 무시하는 이미지 entrypoint를 대체하고, `--user cr`은
사본을 플랫폼 사용자 소유로 남깁니다. `docker cp`로 복사하면 root 소유가 되어
플랫폼에서 쓸 수 없습니다. 예전 `-journal` 파일은 반드시 지워야 하는데, 남아 있으면
SQLite가 복원한 파일에 그 내용을 재생하기 때문입니다. 더 새로운 마이그레이션은
플랫폼이 시작할 때 적용합니다. `bin/platform-rebuild`도 같은 단계를 거칩니다.

## 보안 한계(실습 전용)

- Elasticsearch는 보안 기능 없이 돕니다.
- Django는 `DEBUG`를 끄고, 비밀 키는 플랫폼 데이터 볼륨에 한 번 생성해 둔 것을
  씁니다. `DJANGO_ALLOWED_HOSTS`를 따로 지정하지 않으면 `localhost`, `127.0.0.1`,
  `[::1]`에만 응답하며, 플랫폼 VM은 여기에 자기 floating IP를 추가합니다.
- 플랫폼에 Docker 소켓이 마운트되어 있어 컨테이너 탈출 경로가 됩니다.
- `/vm-terminal/` 아래 터미널은 별도 로그인 없이 슬롯의 Kali·WAF 컨테이너 root 셸을
  내줍니다. 두 컨테이너 모두 지정한 몇 가지를 뺀 capability를 전부 버리고
  `no-new-privileges`로 돌며, Docker user namespace remap 때문에 컨테이너의 root는
  훈련 환경 호스트에서 권한 없는 사용자입니다. 슬롯은 모두 훈련 환경 호스트의 커널을
  공유합니다(`docs/THREAT-MODEL.md`).

플랫폼 VM도 마찬가지이고, 거기에 더해 프로젝트 비밀번호가 `/opt/cr/openstack.env`와
플랫폼 컨테이너 환경 변수에 평문으로 들어 있습니다. VM의 ssh, 8000, 8002, 3080은 모든
주소에 열려 있고, 8000은 로그인 없이 접속됩니다.
