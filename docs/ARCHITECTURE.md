# 아키텍처

이 문서에서는 훈련 환경의 구성, 그 안에서 트래픽과 증거가 흘러가는 경로, 그렇게 설계한 이유를 설명합니다. 점수 정의는 `CLAUDE.md`에, 미해결 문제와 측정으로 확인한 특이 사항은 `docs/STATE.md`에 정리해 두었습니다.

훈련 환경은 OpenStack에서만 운영하며, docker substrate는 2026-10-21에 삭제했습니다(`docs/DECISIONS.md`). Docker 자체는 지금도 쓰는데, 플랫폼 VM에서는 플랫폼 서비스를, 훈련 환경 호스트에서는 모든 슬롯의 컨테이너를, GNS3에서는 표시용 노드를 Docker로 띄웁니다. 로컬 개발 환경에서는 훈련 환경을 띄우지 않고 유닛 테스트만 돌립니다. 훈련 환경은 마지막 "OpenStack" 절에서 다루며, 이미 구축한 부분과 아직 계획 단계인 부분을 나눠 적었습니다(`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`).

이 레포는 가설에서 출발했습니다. 레드팀 공격에 정답 데이터(ground truth) 라벨을 붙이고 Suricata와 ModSecurity 경보를 그 라벨에 자동으로 맞추면, 오탐과 미탐을 기계적으로 채점할 수 있다는 가설입니다. 목표 점수는 이 가설을 확인한 뒤에 추가했습니다.

이 문서에서 쓰는 용어:

- **훈련 환경**(range): 네트워크, 호스트, 대상 앱 전체
- **세션**: 공격하는 레드팀과 방어하는 블루팀이 훈련 환경을 함께 쓰는 1회 단위
- **워게임**: 대상 앱과 그 목표, 케이스. `board`와 `corp` 두 가지가 있음
- **케이스**: harness가 보내는 공격 요청 또는 정상 요청 묶음. 경보가 몇 건 나오든 판정은 1건으로 셈
- **마커**: 케이스 요청에 붙는 `X-Request-ID` 값. 플랫폼은 이 값으로 경보와 케이스를 매칭함
- **정답 데이터**(ground truth): 대상 시스템이 직접 저장한 데이터로, 공격자가 실제로 무엇을 빼 갔는지 보여 줌. board에서는 제출된 탈취 데이터와 대조하는 비밀 값, corp에서는 DB 변경 로그
- **substrate**: 플랫폼이 훈련 환경을 올리는 기반. `CR_SUBSTRATE`로 고르며 지원 대상은 OpenStack뿐
- **`estate`**: 대상 앱이 있는 내부 네트워크
- **슬롯**: 훈련 환경 호스트에서 docker compose 프로젝트 `sN`으로 뜨는 훈련 환경 단위. 세션마다 슬롯을 하나씩 씀
- **방어 설정**(posture): 시작 시점의 방어 상태. WAF 설정과 IDS 룰 파일로 구성되며, 워게임이 `defense:` 맵에 선언하고 세션은 그중 하나로 시작함. 코드에서는 posture라고 부름
- **코치**(coach): 레슨 강조 기능. 단계에서 다루는 화면 요소에 원을 두르고 옆에 한 줄 안내를 붙임
- **격리 경계**(isolation seam): 관심사 하나를 파일 하나에서만 다루게 하는 규칙. 목록은 "격리 경계" 절 참고
- **플랫폼 DB**(store): 플랫폼의 SQLite 데이터베이스 `/data/db.sqlite3`
- **유닛**(unit): 단계 엔진이 실행하는 기초 레슨이나 시나리오. 본문에서는 주로 "레슨"이라고 씀
- **박스**(box): 역할 하나를 맡는 컨테이너. 공격 박스(Kali)가 대표적인 예
- **훈련 환경 호스트**(range host): 모든 슬롯의 컨테이너를 돌리는 VM `cr-range`

## 훈련 환경

플랫폼 VM에서는 컨트롤 플레인인 `compose.yaml`(프로젝트 `cr`)을 실행합니다. 이 프로젝트는 상시 하나만 띄워 두고, 그 안에서 플랫폼, Elasticsearch, Kibana, `collector`, GNS3 서버가 `mgmt` 네트워크 위에서 돌아갑니다. 서비스 수는 `bin/measure`로 이 파일에서 셉니다. 훈련 환경은 VM을 하나 더 써서, 훈련 환경 호스트 `cr-range`에 슬롯마다 compose 프로젝트로 띄웁니다("OpenStack" 절).

세션을 열어도(`POST /api/sessions/`) 스택을 새로 띄우지 않고, 아래 작업만 합니다.

- 준비된 빈 슬롯 중 첫 번째 슬롯에 세션 할당
- 센서에 룰을 넣고, 세션의 defense에 맞는 WAF 설정 작성
- baseline 읽기. baseline은 이후 채점할 때 비교 기준으로 쓰는 대상 시스템 데이터의 스냅숏

세션은 슬롯당 하나씩 동시에 돌아갑니다. `max_sessions`는 슬롯 수와 같고, 이보다 많이 열려고 하면 409를 반환합니다. 세션을 닫으면 해당 슬롯만 리셋합니다.

닫힌 세션은 플랫폼 DB에 `CR_RETAIN_CLOSED_MINUTES`분(기본 60, `compose.yaml`에서 설정) 동안 보관합니다.

- 보관 기간이 지난 닫힌 세션은 `platform/api/retention.py`에서 딸린 데이터와 함께 모두 삭제함. 기동 시(`cr/wsgi.py`)와 세션을 닫을 때마다 실행
- 세션의 탐지 기록과 고객 요청을 트랜잭션당 2,000행씩 지운 다음 세션을 지우므로, 세션을 여러 개 정리해도 플랫폼 DB의 쓰기 잠금을 오래 잡지 않음
- 플랫폼 DB는 `transaction_mode: IMMEDIATE`(`cr/settings.py`)로 설정한 SQLite라서, 읽은 뒤 쓰는 트랜잭션은 시작 시점에 쓰기 잠금을 잡음. 곧장 `database is locked`로 실패하지 않고 busy timeout 30초 동안 기다림
- `bin/backup`은 `VACUUM INTO`로 플랫폼 DB 스냅숏을 뜨고 최근 사본을 `--keep`개(기본 1)만 남김. `bin/platform-rebuild`와 `bin/cloud down`에서는 `cloud.yaml`의 `backups: {keep}` 값을 씀

워게임은 훈련 환경 호스트의 슬롯마다 GHCR 컨테이너로 돕니다.

- 준비 상태 점검과 세션 baseline 읽기는 `board` 역할 runner(`sudo docker exec sN-board`)로 board 컨테이너 안에서 함. `loot.ground_truth`는 컨테이너 안에서 `127.0.0.1`의 `BOARD_API_URL` 포트로 요청하며, board 포트는 어디에도 publish하지 않음

대상 시스템을 워게임이라고 부르며, 워게임마다 `wargames/` 아래에 폴더가 있습니다. 슬롯마다 그 폴더의 `compose.yaml`을 실행하며, 워게임은 두 개입니다.

- `board`(Django와 MySQL, `loot_verified`)
- `corp`(WordPress와 MySQL, `effect_observed`)

워게임 목록은 `wargames/<id>/scenario.yaml`에서 읽습니다(`platform/wargames.py`).

- 필수 필드: `name`, `description`, `image`, `public_url`, `objective_model`, `case_file`
- 선택 필드 `category`, `difficulty`(easy, medium, hard), `minutes`. API 응답에는 들어가지만 콘솔에는 하나도 표시하지 않음(2026-11-14)
- 선택 필드 `defense`, `foundations`, `scenarios`는 "세션, WAF 설정 조정, 단계 엔진"과 "시나리오" 절에서 설명
- `image`는 아직 쓰는 곳이 없음

이미지 빌드와 pull 경로:

- 앱 이미지는 CI(`.github/workflows/images.yml`)에서 빌드
- 훈련 환경용 이미지도 CI에서 빌드: Kali(`deploy/kali/Dockerfile`), WAF(`deploy/waf/Dockerfile`), 에지(`deploy/edge/Dockerfile`)
- 훈련 환경 호스트는 각 이미지를 `ghcr.io/nekonic/cr-<name>:<CR_IMAGE_TAG>`로 pull함. 태그는 플랫폼이 자기 태그를 호스트 설치 번들과 슬롯별 compose 파일에 적어 넣은 값
- 도구 케이스는 공격 컨테이너에서 실행(`redteam/tools.py`, `TOOL_IMAGE` 기본값은 `cr-kali`)

새 워게임을 추가할 때 필요한 것:

- `wargames/` 아래 폴더의 `scenario.yaml`, `objectives.yaml`, `compose.yaml`, 그리고 `redteam/cases/` 아래 케이스 파일
- `declaration.yaml`: 훈련 환경 호스트의 `wargames:` 목록에 넣을 이름, `cr-waf`의 `names:` 목록에 넣을 사이트 이름
- `deploy/range-host/slot.yaml`: WAF가 프록시하는 서비스별 estate 주소 마지막 옥텟(`x-wargames.fronts`), 서비스별 `cap_add`와 자원 제한(`x-wargames.limits`), `waf` 서비스 `extra_hosts`의 서비스 이름과 estate 주소, `kali` 서비스 `extra_hosts`의 사이트 이름. `fronts`와 `limits`는 슬롯을 렌더링할 때 `rangehost.compose`에서 읽음
- `platform/tests/test_containment.py`의 `LEARNER_FACING`과 `CAPABILITIES`에 넣을 서비스
- `deploy/waf/board.com.conf`의 `server` 블록

워게임 `compose.yaml`에는 `container_name`을 고정하지 않습니다. 컨테이너 이름은 슬롯에서 `sN-<service>`(`s1-board`, `s2-corp-wp`)로 붙이고, 호스트 이름은 서비스 이름을 그대로 씁니다. 고정 이름은 컨트롤 플레인의 `cr-platform`, `cr-elasticsearch`, `cr-kibana`, `cr-collector`, `cr-gns3`에만 쓰며, 아래 첫 번째 표에서도 서비스를 이 이름으로 적었습니다.

훈련 환경에 영향을 주는 엔드포인트는 쿼리나 본문으로 `session`을 받습니다. rules, validate, 룰 비활성화, `/api/attacker/`, origin, label, canary가 여기에 해당합니다.

- `session`이 없으면 쓰기 요청은 가장 최근에 연 세션에 적용하고, 열린 세션이 없으면 409 반환
- `session`이 없는 읽기 요청은 가장 최근 세션 기준
- 닫힌 세션을 지정한 쓰기 요청은 거부
- 비활성화한 룰은 세션에 묶어 저장(마이그레이션 0014). 마이그레이션 0028에서 모델 이름을 `Suppression`에서 `DisabledRule`로, `restored_at`을 `enabled_at`으로 바꿨으며 기존 행은 그대로 남음

실제로 적용 중인 룰 파일은 슬롯의 센서마다 따로 있습니다.

- 세션을 열 때 그 defense의 룰 파일을 슬롯 센서에 넣음. 룰 파일이 `local.rules`면 넣지 않음("세션, WAF 설정 조정, 단계 엔진" 참고)
- 한 슬롯에 적용한 룰은 다른 슬롯에 반영되지 않음(2026-10-13 측정)

| 서비스 | 실행 위치 | 이미지 | 네트워크 | 호스트 포트 |
|---|---|---|---|---|
| `kali` | 훈련 환경 호스트, 슬롯 N | `deploy/kali/Dockerfile`로 빌드한 `ghcr.io/nekonic/cr-kali` (공격 도구와 마커 프록시를 넣은 Ubuntu 24.04) | internet | |
| `edge` | 훈련 환경 호스트, 슬롯 N | `deploy/edge/Dockerfile`로 빌드한 `ghcr.io/nekonic/cr-edge` (Alpine과 nftables 기반 라우터) | internet, estate | |
| `waf` | 훈련 환경 호스트, 슬롯 N | `deploy/waf/Dockerfile`로 빌드한 `ghcr.io/nekonic/cr-waf` (nginx 1.24, ModSecurity v3, CRS) | estate | |
| `edge-sensor` | 훈련 환경 호스트, 슬롯 N | digest로 고정한 `jasonish/suricata`, 브리지 `sN-inet` 감시(`deploy/range-host/edge-sensor.yaml`) | 호스트 네트워크 | |
| `estate-sensor` | 훈련 환경 호스트, 슬롯 N | digest로 고정한 `jasonish/suricata`, 브리지 `sN-estate` 감시(`deploy/suricata/suricata.yaml`) | 호스트 네트워크 | |
| `board` | 훈련 환경 호스트, 슬롯 N | `wargames/board/app`으로 빌드한 `ghcr.io/nekonic/cr-board` (gunicorn 위의 Django, 포트 8000) | estate, `board-default` | |
| `board-db` | 훈련 환경 호스트, 슬롯 N | digest로 고정한 `mysql` | `board-default` | |
| `corp-wp` | 훈련 환경 호스트, 슬롯 N | `wargames/corp/app`으로 빌드한 `ghcr.io/nekonic/cr-corp` (WordPress 6.6.2, 취약 버전으로 고정한 플러그인 3개, `Host` 헤더 `corp.com`) | estate, `corp-default` | |
| `corp-db` | 훈련 환경 호스트, 슬롯 N | `wargames/corp/db`로 빌드한 `ghcr.io/nekonic/cr-corp-db` (MySQL 8.4, binlog `ROW`) | `corp-default` | |
| `cr-elasticsearch` | 플랫폼 VM | `elasticsearch:8.15.0` | mgmt | 9200 |
| `cr-collector` | 플랫폼 VM | `filebeat:8.15.0`, syslog 입력만 사용 | mgmt | 5140/udp |
| `cr-kibana` | 플랫폼 VM | `kibana:8.15.0`, `/kibana/` 경로로 제공 | mgmt | 5601 |
| `cr-platform` | 플랫폼 VM | `platform/` (waitress 위의 Django, nginx 뒤에서 동작). `/kibana/`의 Kibana, `/vm-terminal/kali/`와 `/vm-terminal/waf/`의 VM 터미널도 nginx로 제공 | mgmt | 8000, 8002 |
| `cr-gns3` | 플랫폼 VM | `deploy/gns3`로 빌드한 `ghcr.io/nekonic/cr-gns3` (gns3-server 3.1.0a6, qemu, uBridge 1.2.3, busybox-static, docker-cli). 플랫폼이 업로드하고 열고 시작한 학습자 구성도를 보관. `CAP_NET_ADMIN`, `/dev/net/tun`, Docker 소켓, 호스트 pid 네임스페이스 사용 | mgmt | 3080 |

8000, 8002, 3080은 `CR_PUBLISH`에, 5140/udp는 `CR_SYSLOG_PUBLISH`에 바인딩하며 두 변수 모두 기본값은 127.0.0.1입니다. 9200과 5601은 loopback에만 바인딩하고, 훈련 환경 호스트에서는 포트를 전혀 publish하지 않습니다. 표의 슬롯 컨테이너 이름은 `sN-<service>`(`s1-kali`) 형식이고, 슬롯 네트워크는 모두 internal입니다.

| 구간 | 서브넷 | 이름 |
|---|---|---|
| `internet` | 출발지마다 /24, 총 서른 개(`declaration.yaml`). 예: `ru` 5.188.10.0/24, `us` 73.0.0.0/24. 슬롯 브리지 `sN-inet` 위 | 인터넷 |
| `estate` | `cloud.yaml`의 `estate` /16에서 슬롯 N에 할당한 /24(10.30.N.0/24), 슬롯 브리지 `sN-estate` | 애플리케이션 estate (서비스망) |
| `mgmt` | `cloud.yaml`의 `mgmt` CIDR. fabric이 만드는 Neutron 네트워크는 이것뿐 | 관리망 |

GeoIP용 출발지 정보가 서브넷에 들어 있어서 출발지 서브넷은 `declaration.yaml`에 고정해 둡니다.

`mgmt`는 모든 슬롯이 공유합니다. 플랫폼은 이 네트워크로 훈련 환경 호스트에 접속하고, 훈련 환경 호스트는 모든 슬롯의 syslog를 이 네트워크로 collector에 보냅니다(`docs/DECISIONS.md`, 2026-10-10).

플랫폼 VM의 compose 네트워크 이름도 `mgmt`지만 별개의 Docker 브리지이며, `cloud.yaml`의 CIDR이 이 브리지와 겹치면 안 됩니다.

선언에는 인터넷 구간 하나에 출발지 서른 개가 들어 있습니다.

- Cloudflare Radar 기준 HTTP 요청 점유율 상위 30개국
- 출발지마다 GeoIP상 해당 국가로 판정되는 /24를 하나씩 갖고, 공격 주소 약 100개 중 일부를 배정받음
- 슬롯마다 `internet` 브리지 하나에 서른 개가 모두 올라감. `deploy/range-host/slot.sh`에서 에지에는 출발지별 게이트웨이 주소를, Kali에는 출발지별로 배정된 주소를 붙임(`nsenter`로 `ip -batch` 실행). 브리지 자체 서브넷 172.30.N.0/24는 아무도 읽지 않는 자리 채움용
- 이 표는 `bin/pick-origins`로 다시 만들 수 있음. acceptance 테스트에서 모든 서브넷을 점수 계산이 읽는 파이프라인과 대조함

망 분리는 훈련 환경 호스트 위 슬롯의 docker 네트워크로 하고, 호스트 바깥은 fabric의 보안 그룹으로 막습니다.

- 슬롯 네트워크는 모두 `internal`, `gateway_mode_ipv4: isolated`. 훈련 환경 호스트는 슬롯 브리지에 주소가 없고, 어느 슬롯 네트워크에도 외부로 나가는 경로나 NAT가 없음
- Kali는 `internet`에만 붙어 있고 아는 이름은 `board.com`, `corp.com` 둘뿐인데 둘 다 WAF를 가리킴. 에지는 `internet`과 `estate` 사이를 NAT 없이 라우팅하고, DB는 자기 워게임의 `<wargame>-default` 네트워크에만 붙음
- `test/test_attacker_reach.py`에서는 실제 훈련 환경에서 Kali가 `board:8000`에도 `corp-wp`에도 이름으로 접근하지 못하는지 확인함. 포트 스캔은 `test/test_range_isolation.py`로 옮겼고, 여기서 Kali로 훈련 환경 호스트, 플랫폼, 훈련 환경 호스트의 `mgmt` 네트워크를 스캔함. `test/test_board_exfil.py`는 `board.com`을 거쳐 board에 접근함
- 실제 훈련 환경의 격리 증거는 `test/test_range_isolation.py`로, Kali, WAF, board 각각에서 격리를 검증함. 훈련 환경 호스트의 sshd, 플랫폼, 인터넷, 메타데이터 서비스, 다른 슬롯 어디에도 닿지 않아야 하고, Kali는 WAF에 닿으며 에지를 거쳐 board의 estate 주소에도 닿음. `board-db`는 이름이 풀리지 않고, SYN 스캔은 동작함
- 렌더링한 슬롯 compose 파일이 격리 조건을 어기면 `platform/tests/test_containment.py`에서 `bin/verify`를 실패시킴("OpenStack" 절)
- `test/test_concurrent_sessions.py`에서는 동시에 연 두 세션이 서로 보이지 않는지 검증함
- 출발지 서브넷과 슬롯 내부 주소는 선언, `cloud.yaml`, `deploy/range-host/slot.yaml`에서 정함. 훈련 환경 호스트의 `mgmt` 주소는 Neutron이 할당하므로, 뷰에서 요청마다 어댑터를 새로 만들어 주소를 읽음
- 훈련 환경 내부에서 온 요청(채점 서버를 뺀, 슬롯이 보고하는 모든 주소. 훈련 환경 호스트의 `mgmt` 주소 포함)을 거부하는 규칙은 해당 주소를 30초간 캐시함. substrate에 연결하지 못하면 훈련 환경이 비어 있다고 보고 요청을 허용함(`docs/THREAT-MODEL.md`)

플랫폼에서 훈련 환경으로는 `mgmt`로만 접근합니다.

- 공격자 트래픽은 에지를 거쳐야만 내부망(`estate`)에 들어옴
- 플랫폼은 `cr-reach` 소속 포트로 `mgmt`의 훈련 환경 호스트에 접속함. 훈련 환경 호스트에서 플랫폼으로 여는 연결은 NTP와 5140/udp syslog뿐("OpenStack" 절). 그래도 API에서 호출자를 직접 검사함(`docs/THREAT-MODEL.md`)

전체 경로는 이 문서 끝부분 "OpenStack 훈련 환경: 목표 구조"의 그림에 있습니다.

`deploy/suricata/suricata.yaml`은 estate 센서 설정 파일입니다. `rangehost.estate_sensor`에서 af-packet 항목을 슬롯 브리지 `sN-estate` 하나로 바꾸고, 스레드 1개에 board와 corp-wp의 estate 주소만 받는 BPF 필터를 겁니다. `HOME_NET`은 10/8, 172.16/12, 192.168/16이고 출발지 대역은 넣지 않았기 때문에 공격자 주소는 외부로 취급합니다(`docs/DECISIONS.md`, 2026-10-21, "The estate sensor's HOME_NET and a repeated lesson move").

WAF는 `board.com`을 `board:8000`으로 넘깁니다(`board`와 `corp-wp`의 estate 주소 .59, .60은 WAF의 `extra_hosts`에 지정). `/internal/`은 board가 서비스하지 않는 경로로 보내 board 자체의 404 응답이 그대로 나가게 했습니다(`deploy/waf/board.com.conf`). `corp.com`은 같은 파일의 두 번째 vhost로, `corp-wp:80`으로 갑니다.

첫 번째 워게임은 board입니다.

- gunicorn 위의 Django 3.2.4와 digest로 고정한 MySQL. 패치하지 않은 Django 버전이라 `order_by` SQL Injection 취약점(CVE-2021-35042)이 알려져 있음
- 기동 시 마이그레이션과 시드 데이터 입력을 직접 수행
- board와 DB 모두 훈련 환경 호스트에 포트를 publish하지 않으므로 훈련 환경 밖에서는 접근할 수 없음
- 채점 기준은 탈취된 계정 정보. 세션이 시작되면 플랫폼에서 `/internal/auth-users`로 board `auth_user`의 사용자 이름과 비밀번호 해시를 읽어 세션 스냅숏으로 보관함
- 플랫폼은 이 경로를 `board` 역할 runner로 board 컨테이너 안에서 `127.0.0.1`로 읽고, WAF에서는 이 경로를 전달하지 않음. 슬롯 브리지를 지나지 않는 읽기라 WAF와 IDS 어느 쪽에도 보이지 않음

두 번째 워게임은 corp입니다. WordPress 6.6.2(`corp-wp`)에 플러그인 세 개를 미패치 버전으로 고정했습니다.

- Ultimate Member 2.6.6(CVE-2023-3460): 가입 요청에 `wp_capabilities`를 주입해 administrator 권한 획득
- WP GDPR Compliance 1.4.2(CVE-2018-19207): 인증 없이 옵션을 바꿔 관리자 자가 가입 허용
- Easy Post Submission 2.3.0(CVE-2026-4431): 인증 없이 글 덮어쓰기

세 취약점 모두 기본 OWASP CRS로는 탐지되지 않습니다. 데이터베이스 `corp-db`는 `--binlog-format=ROW`로 띄운 MySQL 8.4이고, WordPress 자체에는 계측 코드를 넣지 않았습니다. corp는 공격으로 데이터베이스에 커밋된 변경을 기준으로 채점합니다("점수 계산 방식" 참고).

## 선언과 substrate 경계

"substrate 경계"(seam)는 플랫폼과 OpenStack 연동 어댑터 사이의 인터페이스로, `platform/range/ports.py`에 정의돼 있습니다.

지원하는 substrate는 OpenStack뿐입니다(2026-10-20 결정, 2026-10-11 결정을 대체). docker 어댑터는 2026-10-21에 삭제했습니다.

훈련 환경이 어떤 구성인지는 OpenStack에 묻지 않고 `platform/range/declaration.yaml`에서 읽습니다. 이 파일에 들어 있는 항목:

- 구간별 id, 표시 이름, 공격 출발지
- 역할 표: attacker, scorer(플랫폼), gateway, proxy, sensor, edge, estate-sensor, wargames, board, board-db, corp, corp-db
- 호스트별 구간(`hosts:`): 설치 스크립트(`setup`)와 실행할 `wargames`를 가진 유일한 호스트인 훈련 환경 호스트 `cr-range`, 슬롯의 `cr-waf`, `cr-edge`, `cr-kali`
- 역할별로 대응하는 슬롯 compose 서비스(`compose:`)
- 센서별 감시 대상 호스트(`watches:`)
- 기본 출발지
- 방어 대상 사이트(서울)

출발지가 선언된 구간만 외부 구간으로 봅니다.

선언에는 `estate`와 `mgmt`의 주소도, 호스트 주소도 적지 않습니다. estate /16과 `mgmt`는 `cloud.yaml`에서, 슬롯 내부 주소는 슬롯 템플릿에서, 훈련 환경 호스트의 `mgmt` 주소는 Neutron에서 정해지므로 플랫폼은 이 값들을 substrate에서 가져옵니다. 선언에 적은 서브넷과 클라우드가 할당한 서브넷이 다르면, 호스트가 하나도 없는 서브넷에 경보가 묶여 버립니다.

구간은 태그로 찾습니다.

- Neutron 네트워크는 `cr.segment.id=mgmt` 태그가 붙은 `mgmt` 하나뿐이고, 어댑터는 태그가 붙은 네트워크만 가져옴. 슬롯의 `internet`, `estate` 구간은 렌더링한 슬롯 compose 파일에서 읽음(`platform/range/openstack.py`의 `_read`)
- 이름으로 매칭하던 방식은 Heat 스택 접미사와 중복되는 Neutron 이름 때문에 깨졌음
- 역할은 선언에서 지정한 호스트를 가리킴. 어댑터는 메타데이터 `cr_host`가 `cr-range`인 서버를 훈련 환경 호스트로 찾고(`slot.host_of`), 나머지 호스트는 슬롯 컨테이너로 취급
- `compose:`로 서비스에 대응시킨 역할은 해당 슬롯 컨테이너 안에서 실행(훈련 환경 호스트에서 `sudo docker exec sN-<service>`). `wargames` 역할은 훈련 환경 호스트 자체에서 실행

코어 코드와 플랫폼 대부분은 이 인터페이스의 메서드 네 개만 씁니다.

- `describe()`: 구간, 구간별 노드와 주소, 센서로 이루어진 구조를 반환
- `segments()`: 센서 검사 없이 호스트별로 어느 구간에 있는지 반환
- `runner(role, segment)`: 떠 있는 컨테이너나 훈련 환경 호스트에서 명령 실행. 대상 역할은 센서, 프록시, 플랫폼이 명령 로그를 읽어 가는 공격 박스, board, corp-db
- `launcher(segment)`: 구간에서 일회성 도구를 실행하고 출력을 반환

`range.substrate()`는 `CR_SUBSTRATE`에 지정한 어댑터(기본값 `range.openstack.connect`)를 생성하고, `CR_SUBSTRATE_OPTIONS`에서 그 이름 아래 둔 옵션에 `declared=RANGE`를 더해 넘깁니다.

- `CR_OPENSTACK_KEYSTONE`, `_USER`, `_PASSWORD`, `_PROJECT`, `_SSH_USER`, `_SSH_KEY`, `_REGION`, `_INTERFACE`, `_DOMAIN`을 받으며, 하나라도 빠지면 빠진 이름을 밝히고 거부
- 훈련 환경 구성을 정하는 값 `_BASE_IMAGE`, `_FLAVOR`(훈련 환경 호스트의 flavor), `_AVAILABILITY_ZONE`, `_SUBNETS`, `_MTU`, `_SLOTS`, `_BUILD_NETWORK`(훈련 환경 호스트가 이미지를 받아 오는 플랫폼 자신의 네트워크), `_PLATFORM`도 받음. 이 값들은 실제로 쓰는 시점에 이름을 밝히고 거부
- `CR_IMAGE_TAG`도 받음. 훈련 환경 호스트 이미지에 쓰고, 부팅할 때 `/opt/cr/.env`에 기록
- 코드에 기본값을 둔 것은 `_SLOTS`(비어 있으면 1)와 `_MTU`(비어 있으면 슬롯을 렌더링할 때 1500)뿐이고, 값은 모두 Heat 스택을 거쳐 `deploy/openstack/cloud.yaml`에서 옴. 이 파일은 `platform/range/cloud.py`에서 읽고 검증
- `redteam/harness.py`에는 launcher를, `platform/rules/suricata.py`에는 runner를 넘김. 둘 다 `subprocess`를 import하지 않고 substrate 이름도 쓰지 않음

어댑터의 호출별 동작:

- 구조: `mgmt`는 Keystone v3, `tags-any`를 쓰는 Neutron, Nova에서 읽음. 슬롯의 `internet`과 `estate`, 그 노드와 주소는 렌더링한 슬롯 compose 파일(`rangehost.compose`)에서 읽음
- 센서: 훈련 환경 호스트가 떠 있으면 두 센서를 모두 보고함. 센서가 gateway 트래픽을 실제로 보는지는 확인하지 않음
- runner: 훈련 환경 호스트의 `mgmt` 주소로 `ssh`하며, 호스트마다 연결을 공유함(`ControlMaster auto`, `ControlPersist 60`). `compose:`로 서비스에 대응시킨 역할은 해당 슬롯 컨테이너 안에서 실행(`sudo docker exec sN-<service>`, `range/rangehost.exec_in`)
- address: 훈련 환경이 맡는 역할마다 훈련 환경 호스트의 `mgmt` 주소
- launcher: `runner("attacker")`로 슬롯의 Kali 컨테이너에서 도구 실행. 넘겨받은 구간은 확인하지 않고 거부 메시지에만 쓰며, 출발 국가는 `set-origin` SNAT로 정해짐. 다른 이미지는 거부하므로 도구는 슬롯의 공격 컨테이너에서만 실행됨
- 검증 대상: 공개 API 레퍼런스와 로컬 sshd로 만든 fake를 대상으로 한 유닛 테스트. 훈련 환경 호스트 도입 전인 2026-10-08에는 `fsl-range` 클라우드에서 `/api/range/`로 VM 훈련 환경을 구축했고, `launcher()`로 `ru`, `tw` 출발지에서 sqlmap을 실행함

compose에서 Docker 소켓을 플랫폼에 마운트하고, entrypoint에서 플랫폼 사용자를 그 소켓 그룹에 넣습니다. 플랫폼은 이 소켓으로 자기 NIC를 읽고, GNS3는 표시용 노드를 띄웁니다. 컨테이너 탈출 경로가 되는 구성이지만 아직 없애지 않았고, 남은 작업은 `docs/STATE.md`의 "The substrate seam" 항목에 있습니다.

## 네트워크 구성도

훈련 환경의 네트워크 구성은 GNS3 프로젝트 파일로 관리합니다. `revision` 9라서 GNS3 2.2에서 열리고, 3.x에서는 불러올 때 업그레이드됩니다. 구성도는 두 가지입니다.

- **시스템 구성도**, `deploy/topology/system/range-openstack.gns3`: 선언의 전체 배선. 관리 구간, 플랫폼 VM, 훈련 환경 호스트 `cr-range`와 그 위의 슬롯 1개 분량 컨테이너가 들어 있음. 영어로만 작성했으며 개발과 GNS3 MCP용. GNS3 서비스는 레포의 구성도를 읽지 않으므로 학습자에게는 노출되지 않음
- **학습자용 구성도**, `deploy/topology/range-openstack.gns3`: 학습자가 방어하는 회사 웹 서비스 네트워크. 실습 토폴로지를 그리는 방식(Cisco NetAcad lab topology, NSRC 워크숍 logical diagram)을 따른 논리 구성도이며, 들어가는 요소는 아래 목록 참고

학습자용 구성도에 넣는 것(기업 논리 구성도 방식):

- 아이콘 위의 역할 호스트 이름
- 호스트 쪽 링크 끝마다 주소만 표기(`10.30.1.59`). 인터페이스, 포트, 프리픽스는 적지 않음. 스위치 쪽 끝, 관리 링크, DB 스위치로 가는 링크(주소가 Docker 브리지 대역)에는 라벨 없음
- 영역 넷: KISA ISMS-P 2.6.1에서 쓰는 영역 이름(DMZ, DB존)과 인터넷, 관리망. 라벨 붙은 링크가 있는 영역은 캡션에 네트워크를 덧붙임(`DMZ 10.30.1.0/24`)
- IDS는 별도 센서 상자("IDS")로 그리고, 트래픽을 받아 보는 호스트와 점선으로 연결. 대상은 `router`(슬롯 `internet` 브리지를 보는 에지 센서)와 사이트(슬롯 `estate` 브리지를 보는 estate 센서)로, Kibana의 `sensor` 값이 가리키는 호스트와 같음
- 초록 화살표(선으로 그린 화살촉)와 "웹 요청" 글자로 internet → router → waf → 사이트 순서의 요청 흐름 표시

그 밖에는 아무것도 넣지 않습니다. 제목, 범례, 기계 자체의 이름, `cr-`, 관리 주소, Docker 브리지 모두 없습니다.

- 흐름은 왼쪽에서 오른쪽으로 한 줄(internet, router, waf, 사이트)이고, `sw1`은 그 줄 위, `sw3`은 아래에 두어 링크끼리 겹치지 않음
- `topology.for_wargame`은 어떤 영역에 그 워게임의 노드가 하나도 남지 않을 때만 그 영역과 안쪽 그림을 지움. 그런 영역 밖의 선, 센서 상자, 글자는 남김

학습자용 구성도의 노드:

- `customers`와 `kali`(공격자의 Kali 박스)는 `internet` 스위치에 연결
- `router`: 슬롯의 에지 라우터 컨테이너. 에지 센서는 옆에 IDS 센서 상자로 그림
- `sw1`: 서비스 구간. `waf`와 사이트(`board.com` 또는 `corp.com`, WAF 호스트에 선언된 이름) 연결
- `sw2`: 데이터베이스 구간. 사이트 뒤에 있고 데이터베이스(`board-db`) 연결
- `sw3`: 관제 구간. `log-server`(Elasticsearch)와, 기록을 보내는 호스트인 라우터, WAF, 사이트를 연결. 두 센서의 eve.json과 WAF audit 로그는 훈련 환경 호스트에서 전달

스위치 번호는 실습 토폴로지 관례(`sw1`, `sw2`, `sw3`, NSRC의 `sw1`)를 따르고, 순서는 서비스, 데이터베이스, 관제로 고정합니다. 스위치별 구간은 영역 캡션으로 알 수 있습니다.

템플릿에는 두 워게임의 사이트와 데이터베이스를 함께 그려 두고(둘 다 `sw2`), `topology.for_wargame`에서 세션 워게임에 해당하는 것만 남깁니다. 고객을 선언하지 않은 워게임(`corp`, `traffic.yaml` 없음)에는 `customers` 노드가 없습니다.

`topology.learner(declaration, wargame)`는 훈련 환경의 이름을 구성도 이름으로 바꿉니다.

- 호스트: `cr-kali`는 `kali`이고, 그 호스트에서 고객 트래픽을 만들면 `customers`이기도 함. `cr-edge`는 `router`, 훈련 환경 호스트와 그 사이트 컨테이너는 사이트, `cr-elasticsearch`는 `log-server`
- 역할
- 구간 → 스위치: 출발지는 `internet`, estate는 `sw1`, 워게임 compose 네트워크는 `sw2`, 관리 구간은 NIC 이름만 쓰는 `sw3`
- 센서 → 그 센서가 NIC를 쓰는 노드

오버레이, 레슨의 훈련 환경 질문, 인터페이스 읽기는 모두 이 매핑을 거칩니다. 오버레이는 `GET /api/sessions/<id>/topology/`로 받는, 실시간 주소가 붙은 호스트 목록입니다(아래에서 설명).

그리기 규칙:

- 링크는 모두 직선(수평, 수직, 대각선)이고 다른 링크나 노드를 가로지르지 않음
- 링크가 바로 위에서 들어오는 노드는 이름을 옆에 둠
- 호스트는 모두 크기와 선 굵기가 같은 정사각형 틀(`host-*.svg`). GNS3 이미지를 빌드할 때 `deploy/gns3/symbols.py`로 만들고 `provision.py`로 업로드
- 틀 안에는 GNS3 번들 affinity 글리프를 넣음. 틀 색은 공격자 빨강, WAF(방패) 초록, 라우터(affinity 라우터 글리프)와 사이트·DB 파랑, 고객과 로그 서버 회색
- 스위치와 인터넷은 GNS3 번들의 정사각형 스위치와 지구본 아이콘을 그대로 씀
- `kali` 틀에는 OffSec의 Kali 드래곤을 넣음. 프레스 팩의 `kali-dragon-black.svg`를 고정 커밋에서 받아 sha256으로 확인하고, 수정 없이 틀 안에 배치. 상표 표기는 `host-kali.txt`와 메인 페이지 하단(`topology.trademark`)에 둠

**학습자용 구성도의 호스트는 모두 표시용 컨테이너입니다.**

- GNS3는 노드 상태에 따라 링크 끝 색을 칠하기 때문에, 멈춘 노드는 링크 끝이 전부 빨강으로 그려짐
- 그래서 호스트마다 고정 이미지(`busybox`, `topology.DISPLAY_IMAGE`)의 `docker` 노드로 두고, `sleep`만 실행하며 콘솔은 없음
- 실제 기계는 훈련 환경에서 돌고, 구성도 노드는 표시만 함
- 측정값(제품을 한국어 전용으로 바꾸기 전, 플랫폼 VM에서 슬롯 1에 board 구성도, 슬롯 2에 corp 구성도를 두 언어로 올린 상태): 표시용 컨테이너 26개, 그 프로세스와 runc shim의 PSS 115MB, uBridge 프로세스 12MB(`docs/DECISIONS.md`)

구간은 `ethernet_switch` 노드로 그립니다. 시스템 구성도에서 나머지를 그리는 방식:

- OpenStack VM `cr-platform`, `cr-range` 두 대는 디스크 이미지 없는 `qemu` 노드
- 슬롯 1개 분량 컨테이너(`cr-kali`, `cr-edge`, `cr-waf`, 두 센서, 대상 시스템 넷)는 실제 이미지를 지정했지만 시작하지 않는 `docker` 노드. 에지는 NIC 두 개(`wan`, `lan`)를 갖고, 대상 시스템은 워게임 네트워크별 스위치(`board-default`, `corp-default`)에 연결
- 호스트 네트워크에서 도는 센서는 NIC가 없고, 옆의 메모로 어느 노드의 네트워크를 감시하는지 표시
- 선언된 구간마다 해당 스위치를 감싼 제목 붙은 사각형(Internet, Application estate, Management and monitoring)
- 컨테이너와 VM마다 쉬운 말로 쓴 메모를 붙임. GNS3 3.1에서는 노드 라벨이 곧 노드 이름

구성도 검사는 `platform/tests/test_gns3_topology.py`에서 합니다.

- `declaration.yaml`과 워게임 compose 파일로부터 시스템 구성도에 있어야 할 노드와 링크를 도출하고, GNS3 구조 규칙을 검사
- 워게임별 학습자용 구성도는 시스템 구성도를 축약한 것이라 시스템 구성도와 대조함. 노드, `topology.learner`를 거쳐 시스템 구성도 배선과 대조한 링크, 로그 링크, 배치, 표시용 노드를 검사

`bin/check-topology`는 gns3-server 2.2.61과 3.1.0a6을 `~/.cache/fsl/check-topology` 아래 venv에 설치한 뒤, 릴리스별로 각 파일 사본에 `load_topology`를 돌립니다. 각 학습자용 구성도에서 픽스처 훈련 환경으로 워게임마다 생성한 훈련 환경 구성도에도 돌리고, 노드가 지정한 번들 심볼이 해당 릴리스에 모두 있는지도 확인합니다.

### 훈련 환경 자체의 구성도

학습자에게는 자기 훈련 환경의 주소가 보입니다. 이 구성도는 `api/maps.py`에서 학습자용 구성도를 바탕으로 만들며, 슬롯과 그 세션의 워게임마다(`slot 1 board`, `slot 2 corp`) 프로젝트를 따로 만듭니다(`topology.labelled`). 링크 양 끝에는 실습 토폴로지처럼 모두 라벨을 붙입니다.

라벨:

- 호스트 쪽 끝에는 그 스위치 구간의 주소를 프리픽스 없이 적고(`10.30.1.247`), 값은 `topology.learner`로 읽습니다. 공격자는 기본 출발지의 주소, 고객은 가장 많이 쓰는 출발지의 주소를 적습니다(`traffic.yaml`의 가중치 기준이며, `attacker.customer_origins`처럼 기본 출발지는 제외). 해당 주소가 없으면 라벨을 붙이지 않습니다.
- 스위치 쪽, `sw3` 쪽, DB 스위치 쪽 끝(`topology.UNLABELLED`)의 라벨은 비워 둡니다. 인터페이스, 포트, Docker 브리지 이름은 라벨에 적지 않습니다.

영역 캡션:

- 영역 캡션 뒤에는 그 스위치에 붙은 라벨의 네트워크를 덧붙입니다(`DMZ 10.30.1.0/24`).
- 스위치의 캡션으로는 그 스위치를 감싼 가장 작은 상자의 텍스트를 씁니다(`topology.captions`).
- 인터넷, DB존, 관리망 캡션에는 이름만 적습니다.
- 같은 주소는 `GET /api/sessions/<id>/lesson/addresses/`에서 `{host, zone, address}` 행으로도 내려 주며(`topology.addresses`), 참고 열의 주소 카드에서 씁니다.

라벨 위치(`topology.leaving`):

- 라벨은 링크가 나가는 쪽 노드 옆에 수평으로 놓습니다.
- 수평이거나 완만한 링크는 선의 위나 아래에 둡니다. 노드의 다른 링크를 보고 공간이 더 남는 쪽을 고르고, 글자 밑으로 선이 지나가지 않게 합니다.
- 가파른 링크는 노드 아래에 둡니다. 노드 이름이 옆에 있으면 노드 위에 두되, 같은 규칙으로 선의 왼쪽이나 오른쪽을 고릅니다. 이름이 위에 있는 노드라면 노드 오른쪽에 둡니다.
- 라벨은 모든 선, GNS3 상태 표시(3.1 웹 UI 기준 지름 6 단위의 원, 노드 중심에서 선을 따라 60 단위 지점), 노드 이름, 영역 테두리와 캡션을 피해서 놓습니다.
- 글자 폭은 글자당 7 단위로 어림합니다. 웹 UI에서 `font-size: 10.0`이 13.3px로 렌더링되기 때문입니다.
- 완만한 링크의 라벨이 자기 노드 이름과 겹치면 선 반대쪽으로 옮깁니다.
- 왼쪽에 놓는 라벨은 `text-anchor: end`로 오른쪽 정렬합니다.

id와 이름: 프로젝트 id는 `uuid5(<learner id>, "slot-<n>-<wargame>")`이고, 노드와 링크 id는 적재할 때마다 새로 만듭니다(`gns3.fresh_ids`, 아래 3단계). 프로젝트 이름에는 키를 붙이고 `show_interface_labels`를 켭니다.

인터페이스는 어댑터의 `interfaces()`로 읽습니다.

- 훈련 환경 호스트에서는 명령 한 번(`rangehost.listed`)으로 슬롯의 docker 네트워크와 서브넷을 나열하고, 슬롯 컨테이너마다 `nsenter`로 들어가 `ip -o -4 addr`을 읽습니다. 호스트 네트워크를 쓰는 컨테이너(센서)는 건너뜁니다.
- 플랫폼 VM 자체의 NIC는 호스트 네트워크로 띄운 `busybox` 컨테이너에서 같은 `ip` 명령으로 읽습니다(`interfaces.on_this_host`). 플랫폼에는 SSH로 접속하지 않습니다.
- 세션 구성도를 만들 때 읽은 인터페이스는 세션이 끝날 때까지 보관했다가 주소를 묻는 단계의 답으로 씁니다(`_map_found`). 슬롯은 세션을 닫을 때만 초기화하므로, 세션이 슬롯을 쓰는 동안에는 주소가 바뀌지 않습니다. 빈 결과는 보관하지 않고, 보관한 결과로 답할 수 없는 질문이 들어오면 슬롯을 다시 읽습니다. 세션을 닫으면 보관한 값도 지웁니다.

프로젝트는 `gns3.publish`에서 다음 순서로 GNS3에 올립니다.

1. GNS3 admin으로 로그인합니다. 비밀번호는 `CR_GNS3_ADMIN_PASSWORD` 또는 `/run/cr-gns3/admin-password`에서 읽습니다. GNS3 데이터 디렉터리는 읽기 전용으로 마운트하고, 이 파일 권한은 Docker 소켓 그룹 기준 0640입니다.
2. GNS3 프로젝트 목록에 해당 프로젝트가 있으면 삭제합니다. GNS3에 없는 프로젝트를 DELETE하면 ERROR 로그가 남기 때문입니다.
3. 노드와 링크 id를 새로 만든 뒤 portable 프로젝트로 가져옵니다(`gns3.fresh_ids`: 이번 적재에서 뽑은 nonce로 id마다 uuid5를 만듦). 프로젝트 id는 URL에 있는 값이 `project.gns3`에 그대로 들어갑니다. GNS3는 스위치의 커널 브리지와 TAP 이름을 노드 id로 짓는데, 적재가 중간에 실패하면 이 브리지와 TAP이 사용 중 상태로 남습니다. 그래서 직전 적재의 id는 다시 쓰지 않습니다.
4. `auto_close`를 끕니다. 가져온 프로젝트는 파일 내용과 상관없이 이 값이 켜진 채로 만들어지고, 마지막 웹 클라이언트가 나가면서 프로젝트가 닫히면 노드도 멈추기 때문입니다.
5. 프로젝트를 열고 노드를 시작합니다.
6. 적재에 실패하면 2단계부터 다시 시도합니다. 최대 `gns3.LOAD_TRIES`(3)번, `LOAD_PAUSE`(3초) 간격입니다.

구성도를 올리는 시점:

- 세션을 열 때
- 슬롯을 초기화한 뒤
- 구성도 창에서 요청이 왔는데(`GET /api/topology/?session=`) GNS3에 그 구성도가 열려 있지 않을 때

바뀌지 않은 구성도는 다시 올리지 않습니다. 슬롯마다 가장 최근 세션의 구성도만 남기고 나머지는 삭제하며, 생성한 구성도는 커밋하지 않습니다. GNS3에서 구성도를 불러오지 못하면 엔드포인트는 세션 워게임의 학습자용 구성도를 파일에서 읽어 내려 주고, 그 이유를 `detail`에 적습니다.

학습자용 구성도는 한국어로 그립니다. 제품이 한국어 전용이기 때문입니다(`docs/DECISIONS.md`, 2026-11-13).

- 영역 캡션은 `docs/vocabulary.md`의 용어로 적습니다. 노드 이름은 역할 이름을 그대로 쓰고, 호스트·네트워크 이름과 IDS는 장비에서 쓰는 이름 그대로 적습니다.
- id는 시스템 구성도와 다르게 씁니다. GNS3 compute는 노드를 노드 id만으로 관리해서, 열려 있는 두 프로젝트가 같은 id를 공유할 수 없기 때문입니다.

`gns3` 서비스(`deploy/gns3`, MCP extra를 포함한 gns3-server 3.1.0a6)는 시작할 때 다음 작업을 합니다.

- 플랫폼에서 올린 구성도만 둡니다. 템플릿 하나로 모든 워게임을 그리므로 따로 복사해 넣는 구성도는 없습니다.
- 컨트롤러 데이터베이스가 만들어지기 전에 admin 비밀번호를 설정합니다(`CR_GNS3_ADMIN_PASSWORD`, 없으면 `/var/lib/cr-gns3/admin-password`에 한 번만 생성).
- learner 사용자에게 `/` 경로의 내장 Auditor 역할을 줍니다(`CR_GNS3_AUDITOR_PASSWORD`, 없으면 `/var/lib/cr-gns3/auditor-password`에 한 번만 생성하고, 플랫폼은 같은 마운트에서 읽음).
- 제목이 Map인 `/static/web-ui/map.html`을 씁니다. 이 페이지는 learner로 로그인한 뒤, 번들 웹 UI가 컨트롤러 정보를 읽는 위치(`localStorage`의 `controller-1`, `controllerIds`)에 토큰을 넣습니다. 링크 끝 라벨을 프로젝트가 지정한 위치에 그리도록 `showInterfaceLabels`는 켜고 `integrateLinkLabelsToLinks`는 끕니다. `statistics_command`는 `false`로 두어 웹 UI가 학습자 브라우저에서 사용 통계를 보내지 않게 합니다.

이 페이지는 같은 출처(same-origin) 프레임 안에서 프로젝트를 열고, 구성도가 그려지기 전에 보기 전용으로 바꿉니다.

- 스타일시트로 편집용 화면 요소를 모두 숨깁니다. 대상은 제목 표시줄, 도구 열, 컨텍스트 메뉴, 토폴로지 요약, 대화 상자, Angular CDK 오버레이이고, `svg.map` 안의 모든 요소에서 포인터 이벤트도 뺍니다.
- 프레임 window에 캡처 단계 리스너를 걸어 신뢰된(trusted) 클릭, 더블클릭, 컨텍스트 메뉴, 키 입력, 드롭을 모두 막습니다. mousedown도 `svg.map` 자체를 왼쪽 버튼으로 누른 경우만 빼고 모두 막습니다.
- 페이지에서 직접 만든 합성 이벤트는 신뢰된 이벤트가 아니어서, 숨긴 컨트롤을 페이지가 직접 누르는 동작은 그대로 됩니다.

구성도가 그려지면 페이지에서 다음을 처리합니다.

- 토폴로지 요약 창을 닫습니다. 3.1.0a6 번들에서는 이 창의 표시 여부가 상수로 박혀 있습니다.
- 웹 UI의 이동 모드를 계속 켜 둡니다. 구성도를 끌면 화면이 이동하고, 휠로 확대·축소합니다.
- 확대 비율을 초기화합니다.
- 그림이 화면에 다 들어올 때까지 웹 UI의 축소 버튼을 누릅니다(누를 때마다 0.1). 웹 UI가 프로젝트의 `zoom` 값을 읽지 않기 때문입니다.
- mousemove를 한 번 보내 그림을 가운데로 옮깁니다. 웹 UI는 `movementX`/`movementY`만큼 화면을 이동합니다.

페이지와 콘솔은 이렇게 맞물립니다.

- 창의 "화면에 맞추기" 버튼을 누르면 프레임에 `fit`을 보내 같은 초기화와 맞춤을 다시 합니다. 콘솔은 창을 열 때와 창 크기가 바뀔 때마다 `fit`을 보냅니다.
- 콘솔은 창을 열 때마다 불러오는 중으로 표시하고, 페이지에서 `{map: "drawn"}`(첫 맞춤 뒤) 또는 `{map: "fitted"}`(이후 맞춤마다)가 올 때까지 프레임을 숨겨 둡니다. 이후 맞춤은 그림이 프레임 안에 들어올 때까지 재시도합니다.
- 코치의 `{locate}`에는 노드, 링크, 링크 끝 라벨, 영역의 창 안 사각형으로 답합니다. 링크 끝 라벨 위치는 Auditor 토큰으로 `/v3/projects/<id>/nodes`와 `/links`를 한 번 읽어서 알아냅니다.
- 말풍선이 구성도의 글자를 가리지 않도록 모든 영역 도형의 사각형(`zones`)과 모든 노드·인터페이스 라벨·영역 캡션의 사각형(`text`)도 함께 보냅니다.
- 서버 쪽에서는 이와 별개로 Auditor 역할에 모든 쓰기가 거부됩니다.

개발용 MCP(`/v3/mcp/`)를 쓰려면 `docker exec cr-gns3 python /opt/cr-gns3/provision.py api-key <name>`으로 API 키를 발급합니다. 콘솔 어디에도 MCP는 노출하지 않습니다. 콘솔의 구성도 탭 이름은 구성도(`blue.pane.topology`) 한 단어입니다. 학습자가 읽는 문구 중 GNS3라는 이름이 나오는 곳은 구성도가 열려 있지 않을 때의 안내(`topology.no_web_ui`)뿐입니다.

읽기 전용 사용자에게는 프로젝트를 열 권한이 없습니다(`Project.Allocate`). 그래서 프로젝트는 플랫폼에서만 올립니다. `gns3.publish`에서 admin으로 프로젝트를 열고 노드를 시작하며, 구성도 창에서 요청이 오면 GNS3에 열려 있지 않은 프로젝트를 올립니다. `provision.py`는 아무것도 열거나 시작하지 않습니다. 이렇게 하면 Auditor 화면에서는 프로젝트가 열려 있고 초록색으로 보입니다.

서비스 요구 사항:

- 릴리스 태그로 빌드하고 `cap_net_admin,cap_net_raw` 파일 capability를 준 uBridge 1.2.3
- `ethernet_switch` 노드용 `CAP_NET_ADMIN`과 `/dev/net/tun`. 3.1은 스위치마다 컨테이너 자체의 네트워크 네임스페이스 안에 커널 브리지와 TAP을 만듭니다.
- `docker` 노드용 호스트 Docker 소켓. 노드마다 호스트 데몬에 `GNS3.<node>.<project id>` 컨테이너가 생깁니다.
- Debian `docker-cli`. GNS3가 docker 노드를 `docker exec`로 닫기 때문입니다.
- `busybox-static`. GNS3가 시작하는 docker 노드마다 복사해 넣기 때문입니다.
- 호스트 pid 네임스페이스(`pid: host`). uBridge가 시작된 노드의 인터페이스를 컨테이너의 호스트 pid 네임스페이스로 옮기기 때문입니다.
- `qemu-system-x86`. 시스템 구성도의 `qemu` 노드용으로 남겨 둡니다.

이미지 관련 기타 사항:

- 3.1.0a6은 `[ai-features]` extra 없이는 시작하지 않습니다. 이 extra에는 시작할 때 skills 레포를 clone하는 copilot이 딸려 오는데, 이미지에서는 `skills_config.py`의 `enabled`를 `False`로 바꿔 둡니다. 그 줄이 없어지면 이미지 빌드가 실패합니다.
- 호스트 데몬은 컨테이너의 bind mount를 호스트 경로 기준으로 해석합니다. 그래서 데이터 디렉터리를 양쪽 모두 같은 경로(`/var/lib/cr-gns3`)로 둡니다.
- 서버는 `gns3` 사용자로 돌고, 플랫폼의 `cr`처럼 시작할 때 소켓 그룹에 들어갑니다.
- `GET /api/topology/`는 GNS3에서 프로젝트 상태가 `opened`일 때만 웹 UI(`web_ui`)를 내려 줍니다. 그 외에는 콘솔의 구성도 창에 구성도가 열려 있지 않다고 표시합니다.

`GET /api/topology/`는 substrate의 학습자용 구성도를 반환하고, `?session=<id>`를 붙이면 위에서 설명한 그 세션 워게임의 구성도를 반환합니다.

- 구성도는 GNS3(`platform/gns3.py`)나 레포 파일에서 가져옵니다.
- `web_ui`는 GNS3 웹 UI에서 해당 프로젝트 id를 가리킵니다.
- 구성도 창에는 이 구성도만 보입니다. 구성은 프레임 안의 GNS3 웹 UI와 맞추기 버튼입니다.

`GET /api/sessions/<id>/topology/`는 세션 워게임의 학습자용 구성도를 읽어 `project.nodes`를 덧붙입니다.

- `project.nodes`에는 같은 훈련 환경 조회에서 얻은 호스트 노드별·스위치별 주소와 `running` 또는 `not reported` 상태가 들어갑니다.
- 세션 오버레이에는 구성도에 있는 호스트와, 구성도에 있는 스위치 위의 주소만 나열합니다.
- 오버레이에서는 훈련 환경이 보고한 이름으로 호스트를 배치합니다. 슬롯마다 컨테이너는 선언된 호스트 이름(`cr-kali`, `cr-waf`)으로 보고되고, 슬롯 접미사는 syslog 송신자 이름(`cr-waf-2`)에만 붙습니다.

## 격리 경계

격리 경계는 관심사 하나를 파일 하나에서만 다루게 하는 규칙입니다. 예를 들어 Elasticsearch와 통신하는 파일은 `platform/ingest/elastic.py`뿐입니다. 아래 표에는 관심사별 담당 파일과, 현재 코드에서 이 규칙을 벗어나는 곳(알려진 예외)을 적었습니다.

| 관심사 | 담당 파일 | 알려진 예외 |
|---|---|---|
| Elasticsearch | `platform/ingest/elastic.py` | `platform/register_pipeline.py`에서 기동 시 `geoip` ingest 파이프라인을 PUT |
| Kibana HTTP API, saved object, Discover 링크 | `platform/kibana.py` | `platform/nginx.conf`에 Kibana API 경로가 들어 있음. 관리용 API, Default space, space 접두어 없는 경로, `?namespaces=`를 거부하고, `GET /kibana/s/<space>/api/spaces/space`에는 SOC space만 담은 응답을 직접 반환 |
| GNS3 API | `platform/gns3.py` | GNS3 컨테이너 안의 `deploy/gns3/provision.py`가 admin으로 로그인해 학습자 계정을 만들고 심볼을 올림. GNS3에서 `/static/web-ui/map.html`로 서빙하는 `deploy/gns3/auditor.html`은 learner로 로그인해 `/v3/projects/<id>/nodes`와 `/links`를 읽음. 콘솔의 구성도 창은 `gns3.py`가 알려 준 포트와 경로의 웹 UI를 프레임으로 띄움 |
| CRS 설정과 nginx reload | `platform/rules/crs.py` | `entrypoint.sh`에서 `vm-terminal.sh cr-waf`를 실행해 사용자에게 슬롯 WAF 컨테이너의 쉘을 열어 줌(훈련 환경 호스트로 ssh한 뒤 `sudo docker exec -it sN-waf bash -l`). audit 로그의 rsyslog 전달 설정은 훈련 환경 호스트에서 `range/rangehost.forwarding`이 작성. WAF의 audit 로그 파일은 `deploy/range-host/slot.yaml`에서 `rangehost.LOGS`가 정한 경로로 마운트하며, 둘 다 `deploy/waf/modsecurity.conf`의 `SecAuditLog`와 맞는지 `platform/tests/test_range_host.py`의 `test_the_waf_s_audit_log_is_forwarded_from_where_modsecurity_writes_it`로 확인. F6의 WAF 창 단계에서 학습자가 입력할 명령(`grep -n ruleRemove {waf_rules}`, `{sudo}nano {waf_rules} && {waf_reload}`)을 보여 주며, 이 명령은 `wargames.lesson`에서 선언된 예외 파일과 reload 명령(`settings.CR_WAF`)으로 채움. 플랫폼에서 터미널을 조작하지는 않음 |
| Suricata 프로세스 | `platform/rules/suricata.py` | `declaration.yaml`의 각 센서 호스트(`sensor`는 `cr-edge`, `estate-sensor`는 `cr-range`)에 `suricata.py`로 넘길 룰 파일과 reload 명령을 지정. 두 센서의 설정(`deploy/range-host/edge-sensor.yaml`, `deploy/suricata/suricata.yaml`)과 compose 서비스는 `platform/range/rangehost.py`에서 렌더링하고, `deploy/range-host/slot.sh`에서 슬롯과 함께 센서를 올리고 내리며, 초기화 때 센서 로그 파일을 다시 열게 하고 에지 라우터를 설정. 그 뒤의 기본 룰 적용은 `suricata.py`로 처리 |
| 공격 박스 | `platform/attacker.py` | `platform/operator_log.py`에서 `/var/log/commands.log`를 읽음. 터미널 연결 설정에 `cr-kali`를 지정하고, `entrypoint.sh`에서 `vm-terminal.sh cr-kali`를 실행. 웹사이트 창(`platform/api/site.py`)은 예외가 아님. 박스에는 `attacker.py`(`customer_origins`, `unbound_source`, 명령을 담은 `as_customer`)와 substrate의 `opened`(훈련 환경 호스트로 연 ssh 스트림으로 슬롯의 Kali 컨테이너에 접속)로만 접근 |
| 대상 시스템 자체의 기록 | `platform/api/loot.py`(board), `platform/api/effect.py`(corp) | 없음. `loot.py`는 `board` 역할 runner로 board 컨테이너 안에서 `127.0.0.1`에 HTTP 요청을 보내고, `effect.py`는 `corp-db`에 `docker exec`하는 runner로 corp에 접근 |

## 파일

본문에서 따로 다루지 않는 주요 파일입니다.

| 파일 | 하는 일 |
|---|---|
| `deploy/filebeat/filebeat.yml` | collector의 Filebeat 설정. `event.module`과 슬롯(`cr_slot`) 태그를 붙여 `logs-<slot>-sensors` 인덱스에 기록 |
| `deploy/elastic/ingest-pipeline.json` | `geoip` ingest 파이프라인. 이벤트 시각을 `@timestamp`로 옮기고, `src_ip`에 GeoIP를 붙이고, `cr_slot`을 삭제 |
| `deploy/proxy/stamp.py` | `X-Request-ID`를 붙이는 mitmdump 스크립트. Kali 이미지에 `/usr/local/lib/web-proxy.py`로 설치 |
| `deploy/kali/operator-log.sh` | Kali 쉘 훅. 입력한 명령을 마커와 함께 `/var/log/commands.log`에 추가 |
| `deploy/kali/Dockerfile`, `deploy/waf/Dockerfile`, `deploy/edge/Dockerfile` | 슬롯의 Kali, WAF, 에지 이미지. `.github/workflows/images.yml`로 빌드하고 GHCR에서 pull |
| `deploy/edge/edge.nft` | 에지 nftables 룰. loopback 외 input은 drop, forward는 accept |
| `deploy/range-host/setup.sh` | Nova user data로 한 번 실행하는 훈련 환경 호스트 설치 스크립트. 패키지, Docker `daemon.json`, sshd와 inotify 한도, 이미지, pristine 볼륨 |
| `deploy/range-host/slot.yaml` | 슬롯 하나의 compose 프로젝트 템플릿. `range/rangehost.py`에서 값을 채워 워게임별 `compose.yaml`과 합침 |
| `deploy/range-host/slot.sh` | 훈련 환경 호스트에서 슬롯 N의 `up`, `reset`, `down` 실행 |
| `deploy/range-host/edge-sensor.yaml` | 에지 센서의 Suricata 설정 |
| `platform/range/rangehost.py` | 훈련 환경 호스트의 설치 번들과 user data, 슬롯별 compose 파일과 부속 파일, 그리고 이를 실행할 명령을 생성 |
| `platform/tests/test_containment.py` | 렌더링한 슬롯 compose 파일이 격리 조건을 어기면 `bin/verify`를 실패 처리 |
| `test/test_range_isolation.py` | Kali, WAF, board에서 격리를 확인하는 실환경 검사 |
| `platform/scoring/` | `correlate.py`는 마커나 시간 창으로 탐지를 케이스에 매칭하고, `metrics.py`는 TP, FP, FN, TN을 집계 |
| `platform/scoreboard.py` | 목표 점수. 탐지를 시도에 귀속시키고, `corroborated`를 판정하고, 탈취된 목표를 집계 |
| `platform/game.py` | 게임 점수(speed, accuracy, coverage, response). 점수의 `game` 블록에 들어감 |
| `platform/disable.py` | Suricata 룰을 정해진 시각까지 주석 처리해 비활성화하고 다시 활성화(`# cr-disabled`) |
| `platform/api/models.py` | Django 모델: `Session`, `Case`, `CustomerRequest`, `Detection`, `Objective`, `RuleSet`, `DisabledRule` |
| `platform/cr/urls.py` | 전체 엔드포인트의 라우트 표 |
| `platform/api/refusals.py` | 예외를 HTTP 상태 코드로 변환(`/api/` 아래 404는 JSON). 변경 요청(POST 등)의 동일 출처 검사도 담당 |
| `platform/api/reachability.py` | 슬롯이 보고하는 모든 주소(채점 서버 주소 제외)에서 온 요청을 거부하는 미들웨어 |
| `platform/range/declared.py` | `declaration.yaml`을 읽어 `Declaration`으로 변환 |
| `platform/range/openstack.py` | OpenStack 어댑터(`connect`): Keystone, Neutron, Nova, ssh |
| `bin/verify` | ratchet 검사(게이트 대상 수치가 커지는 변경을 거부, `CLAUDE.md` 참고)와 변경이 닿는 테스트 실행(`--changed`, `--fast`. 테스트 선택은 `bin/select-tests`) |

## 요청의 출처

| 경로 | 발신자 | 경보에 찍히는 출발지 주소 | 마커 |
|---|---|---|---|
| 터미널, HTTP | Kali, 자체 프록시(`127.0.0.1:8081`) 경유 | Kali, 선택한 출발지 | 프록시가 추가 |
| 터미널, raw TCP | Kali에서 직접, 프록시 미경유 | Kali, 선택한 출발지 | 없음 |
| API로 실행한 케이스, HTTP | 공격 박스. 플랫폼이 launcher로 박스에서 `curl` 실행(`views._fire`: 시나리오 일정, 레슨 시드, `POST /api/sessions/<id>/attacks/`) | 공격 박스, 선택한 출발지 | harness가 추가 |
| API로 실행한 케이스, 도구 | 공격 박스. 플랫폼이 launcher로 박스에서 도구 실행 | 공격 박스, 선택한 출발지 | sqlmap `--headers=` |
| CLI 실행, HTTP | 공격 박스. `redteam/run.py`가 `launcher(<선언된 기본 출발지>)`로 박스에서 `curl` 실행 | 공격 박스, 기본 출발지 | harness가 추가 |
| CLI 실행, 도구 | 공격 박스, `launcher(<선언된 기본 출발지>)` | 공격 박스, 기본 출발지 | sqlmap `--headers=` |
| 사이트 브라우저 | 학습자 브라우저, 플랫폼 nginx 8002번 포트와 `platform/api/site.py` 경유 | 고객 주소. Kali에 있는 주소이며, `cr-users` 계정으로 보내 에지를 통과 | 세션 비밀값 `browse-<hex>`, `site.py`에서 설정. API에는 `browse`로 표시 |
| 고객 | `deploy/traffic/users.py`, Kali 컨테이너의 `cr-users`로 실행 | 기본이 아닌 출발지에 있는 페르소나 자신의 주소. 공격자가 요청을 보내는 주소는 쓰지 않음 | 요청마다 새 UUID |

프록시는 `mitmdump` 스크립트입니다.

- Kali 컨테이너의 메인 프로세스로, 이미지의 `CMD`에서 `/usr/local/lib/web-proxy.py`로 127.0.0.1:8081에 `mitmdump`를 띄웁니다.
- `/var/lib/session/active`와 `/var/log/commands.log`는 root 전용 0600입니다. 컨테이너 안에서는 플랫폼의 명령도, 학습자의 셸도 root로 돕니다.
- `X-Request-ID`가 없는 요청에는 `/var/lib/session/active`의 값을 그 헤더로 넣습니다.
- 플랫폼에서는 `runner("proxy")`로 훈련 환경 호스트에 ssh한 뒤 Kali에 `docker exec`해서 `active` 파일을 씁니다.
- TLS는 가로채지 않습니다. 프록시는 환경 변수로 지정만 할 뿐 강제하지 않으므로, `curl --noproxy '*'`로 보내면 프록시를 거치지 않습니다.
- 로그인 셸의 `http_proxy`와 `HTTP_PROXY`는 `/etc/profile.d/proxy.sh`에서 지정합니다.

터미널에서 사용자가 입력한 명령도 기록합니다.

- Kali 쉘에서 명령마다 현재 `/var/lib/session/active` 마커를 붙여 `/var/log/commands.log`에 추가합니다.
- 플랫폼은 `runner("attacker")`로 이 파일을 읽어 `GET /api/sessions/<id>/commands/`로 제공합니다.

Kali 창(레드팀 콘솔의 창, 레슨·시나리오 세션에서는 블루팀 콘솔의 창)에는 세션 API가 알려 주는 URL(`GET /api/sessions/<id>/`의 `kali_terminal`)을 프레임으로 띄웁니다.

- URL은 `/vm-terminal/kali/?arg=<세션 id>`이고, 플랫폼 안의 ttyd에서 `platform/vm-terminal.sh`를 실행합니다. ttyd는 `-t disableLeaveAlert=true`로 띄우므로, 다음 레슨으로 넘어가거나 세션을 끝낼 때 브라우저의 "사이트에서 나가시겠습니까?" 창이 뜨지 않습니다. 스크립트는 훈련 환경 호스트의 mgmt 주소로 ssh 접속해 세션 슬롯의 `sudo docker exec -it ... sN-kali bash -l`을 실행합니다.
- `entrypoint.sh`에서 두 ttyd를 `TERMINAL_KEEP=1`로 띄우면, 스크립트가 자기 자신을 `tmux new-session -A -s <host>-<세션 id>` 안에서 다시 실행합니다(`platform/tmux.conf`: 상태 줄 없음, 대체 화면 없음. 출력은 xterm 스크롤백에 남음). 세션 이름의 호스트에는 `cr-`를 붙이지 않습니다(예: `kali-12`). 새로고침해도 같은 셸에 다시 붙으므로 실행 중인 sqlmap과 그 출력이 그대로 남습니다. 세션 id가 숫자일 때만 tmux 세션 이름으로 씁니다. tmux가 없으면 유지 터미널도 일반 셸로 열리고, 새로고침하면 셸이 유지되지 않습니다.

`vm-terminal.sh`는 플랫폼 runner가 훈련 환경 호스트에 쓰는 별칭 `cr-<server id>-<launch time>`(`OpenStack.host_key_alias`)으로 호스트 키를 확인하고, `StrictHostKeyChecking=accept-new`를 씁니다.

- 훈련 환경 호스트를 재부팅하거나 새로 만들면 별칭이 바뀌므로, "REMOTE HOST IDENTIFICATION HAS CHANGED" 경고 없이 새 키가 등록됩니다.
- 이미 알고 있는 별칭인데 키가 바뀌었다면 접속을 거부합니다.

터미널별 로그인 방식:

- Kali는 `/root`에서 root 로그인 셸로 열립니다(호스트 이름 `kali`, Kali 기본 두 줄 프롬프트(`deploy/kali/bashrc`), motd 없음). `no-new-privileges` 때문에 `sudo`로 얻을 권한이 없어서 처음부터 root 셸을 줍니다. `/etc/profile.d/proxy.sh`(`http_proxy`)와 명령 훅(`/usr/local/lib/shell-hook.sh`의 `__log_command`, `/etc/bash.bashrc`에서 로드)이 로그인할 때처럼 적용됩니다.
- WAF는 슬롯 WAF 컨테이너의 root 로그인 셸로 열립니다(호스트 이름 `waf`). 그래서 레슨에서 알려 주는 reload 명령에 `sudo`가 없습니다(`nginx -t && nginx -s reload`).
- 두 셸 모두 `TERM=xterm-256color`, `TZ=KST-9`(POSIX 시간대 문자열)로 엽니다. WAF 이미지에 tzdata가 없어서 `TZ=Asia/Seoul`이 "Asia"라는 이름의 UTC로 읽혔기 때문입니다(21회차). WAF의 nginx와 ModSecurity는 UTC로 둡니다. 수집 파이프라인에서 감사 로그의 시간대 없는 `time_stamp`를 UTC로 읽기 때문입니다.
- syslog 송신자 이름은 훈련 환경 호스트의 rsyslog 템플릿에서 슬롯마다 고정하므로(`cr-waf`, `cr-waf-2`), Filebeat에서 송신자 이름으로 슬롯을 구분합니다.

블루팀 콘솔의 WAF 창에는 세션 API가 알려 주는 URL(`GET /api/sessions/<id>/`의 `waf_terminal`)을 프레임으로 띄웁니다.

- URL은 `/vm-terminal/waf/?arg=<세션 id>`이고, 같은 `auth_request /terminal-allowed`로 보호합니다.

블루팀 콘솔의 웹사이트 창은 콘솔 안에 넣은 브라우저이며 아래 요소로 구성됩니다.

- 뒤로, 앞으로, 새로 고침. 페이지를 불러오는 동안에는 중지 버튼과 얇은 진행 막대 표시
- 전체 URL(`http://board.com/<경로>`)을 보여 주는 주소창. http에는 Chrome처럼 "주의 요함"을 표시하고, URL이나 경로를 입력해 Enter로 이동 가능
- iframe 안의 페이지
- "개발자 도구" 토글. F12로도 열리며, 페이지 안에 포커스가 있어도 동작

다른 호스트 주소를 입력하면 Chrome의 "사이트에 연결할 수 없음" 페이지가 나옵니다.

대상 시스템은 외부에 공개하지 않으므로, 8002의 nginx에서 `/site/<세션>/<호스트>/<경로>`를 플랫폼의 기록기로 넘깁니다. 이때 터미널과 같은 `auth_request /terminal-allowed`를 거칩니다. 기록기 경로는 `/site-proxy/<세션>/<호스트>/`(`platform/api/site.py`)이고, 원래 경로와 쿼리는 `X-Site-Uri`에 담아 넘깁니다.

기록기는 이 요청을 훈련 환경의 고객 쪽에서(아래 참고) Chrome처럼 보냅니다.

- `Host: <호스트>`, `Connection: keep-alive`, `Accept-Encoding: gzip, deflate`를 보내고, 응답은 압축을 풀어서 넘깁니다.
- 페이지 이동이면 `Upgrade-Insecure-Requests: 1`을 보내고, 세션이 그 호스트에서 받아 둔 쿠키도 붙입니다.
- 헤더 순서는 Chrome을 따르고(`CHROME_ORDER`), 리다이렉트는 따라가지 않습니다.
- 브라우저가 보낸 헤더 중 넘기는 것은 `Accept`, `Accept-Language`, `Content-Type`, `User-Agent`, `Referer`, `Origin`뿐입니다. 뒤의 두 헤더는 `http://<호스트>/`에 접속한 브라우저가 보낼 값으로 고쳐 씁니다(`as_browsed`).
- `X-Forwarded-For`는 넘기지 않습니다. 그래서 고객 주소는 WAF에서 붙고, 대상 시스템에는 학습자의 LAN 주소가 남지 않습니다.

기록기의 응답:

- 없는 세션이면 404, 닫힌 세션이면 409를 WAF 호출 없이 응답
- 요청 대상으로 쓸 수 없는 경로면 400 응답
- 연결 3초, 읽기 20초 안에 응답이 없으면 502("board.com did not answer") 응답
- 페이지는 도착하는 대로 브라우저로 스트리밍

이 경로의 기타 사항:

- 8000의 nginx는 `/site-proxy/`에 404를 응답합니다.
- 플랫폼의 POST 동일 출처 검사에서 이 경로는 제외하므로 대상 시스템의 폼도 제출됩니다.
- 모든 페이지는 WAF를 거쳐 판정합니다. 차단되면 WAF 자체의 403 페이지가 보이고, 그 기록은 Kibana에 남습니다.
- 경로와 쿼리는 브라우저가 보낸 그대로 전달합니다(`$request_uri`에 대한 `map`).

접두사를 벗어나게 될 값은 nginx에서 고쳐 씁니다.

- `Location` 헤더(`proxy_redirect`)
- HTML 안의 `href="/`, `src="/`, `action="/`, `http://<호스트>/`, `http://<호스트>"`(`sub_filter`, 이를 위해 업스트림에 비압축 응답을 요청). WordPress가 이스케이프한 `http:\/\/corp.com\/`도 포함

쿠키:

- nginx에서 브라우저의 `Cookie`와 응답의 `Set-Cookie`를 지웁니다. 그래서 플랫폼 쿠키는 대상 시스템으로 가지 않고, 대상 시스템의 쿠키도 브라우저에 닿지 않습니다.
- 대신 대상 시스템의 쿠키는 기록기에서 세션·호스트별로 보관합니다(`site._keep_cookies`). `Secure` 쿠키는 버리고, 만료된 쿠키는 지우고, 세션을 닫으면 모두 잊습니다. 보관한 쿠키는 이후 요청에 `Cookie`로 붙이므로, 이 창에서 로그인하면 세션 동안 로그인이 유지됩니다.
- 쿠키를 지워도 대상 페이지의 스크립트까지 막지는 못합니다. 그 스크립트는 플랫폼 호스트(8002번 포트)에서 실행되는데 쿠키는 포트별로 분리되지 않으므로, `document.cookie`로 8000의 콘솔이 보낼 쿠키를 설정할 수 있습니다.
- 지금은 콘솔에서 쿠키를 쓰지 않지만, 나중에 쿠키를 추가하면 이 방법으로 접근이 가능해집니다.

nginx는 `</body>` 앞에 스크립트도 넣습니다.

- `location.pathname + search`를 부모 창에 post합니다. 페이지 안에서 링크를 눌렀을 때 주소창과 방문 기록이 함께 바뀌는 것은 이 덕분입니다.
- F12를 부모 창으로 넘깁니다.
- 코치의 `{locate: <selector>}`에 그 요소의 사각형으로 답하고, 스크롤하거나 크기가 바뀔 때도 다시 답합니다. 출처가 콘솔 호스트인 부모 창의 메시지에만 답합니다.
- 따로 요청을 보내지는 않습니다.
- 링크를 `http://<site>/...` 주소로 보이게 바꿉니다. nginx가 고친 마크업에는 프록시 경로가 남아 있지만, 마우스를 올리면 고객이 보게 될 주소가 나옵니다. 이런 링크를 일반 클릭하면 프록시 경로로 보냅니다.

웹사이트 창의 출구(`site.found_egress`, 세션마다 한 번 결정)는 고객 주소입니다. 그래서 창의 요청은 고객과 같은 경로를 지나고, 센서에도 고객 요청과 똑같이 보입니다. 출발지는 `attacker.customer_origins` 중 시나리오 고객 트래픽의 비중이 가장 큰 출발지(`customers.declared`, 없으면 id 순으로 첫 번째)입니다.

- 기록기에서 Kali로 ssh stdio 스트림을 열고(`OpenStack.opened`) 그 안에서 `attacker.as_customer`를 실행합니다.
  - `as_customer`는 Python 브리지로, Kali의 출발지 SNAT가 적용되지 않는 `cr-users` 계정으로 돕니다. 그 슬롯에서 고객 트래픽을 한 번도 돌린 적이 없으면 계정과 예외 규칙을 만듭니다.
  - 브리지는 해당 출발지의 첫 주소에 바인드해 WAF의 `estate` 주소 80번 포트로 연결합니다.
  - 요청은 NAT 없이 에지를 라우팅되어 지납니다. 에지 센서에는 `waf`로 가는 요청이 보이고, estate 센서에는 `waf`가 `X-Forwarded-For`에 고객 주소를 담아 `board.com`으로 보내는 요청이 보입니다.
- 컨테이너 이름이나 `mgmt` 주소는 쓰지 않습니다.

이 경로는 콘솔의 8000과 출처가 다른 별도 포트 8002에서 서비스하고, 모든 응답에 `Content-Security-Policy: sandbox allow-forms allow-scripts allow-same-origin`을 붙입니다.

- 대상 시스템은 레드팀이 스크립트를 심을 수 있는 곳입니다. 콘솔과 출처가 같으면 그 스크립트로 콘솔과 콘솔 API를 읽고 조작할 수 있습니다.
- `allow-same-origin` 없는 sandbox(불투명 출처)로 두면 8000번 포트에서도 막을 수 있지만, Chromium 기반 내장 브라우저에서는 그런 프레임이 거부됩니다(Claude 데스크톱 브라우저에서 `ERR_BLOCKED_BY_CLIENT`). 그래서 사이트는 별도 포트로 분리했습니다.
- `SITE_PORT`는 8002입니다.
- 세션 API는 `site: {port, path}` 또는 `null`을 내려 주며, 이 값이 없으면 콘솔에서 창을 숨깁니다.
- 8002는 플랫폼 템플릿의 security group에서 엽니다(`docs/OPENSTACK.md` §3.5).

기록기는 세션마다 최근 요청 200개를 플랫폼 메모리에 보관합니다. 재시작하면 사라지고, 세션이 닫히면 지웁니다. 요청마다 다음 내용이 들어갑니다.

- 메서드, `http://<호스트><경로>`, 상태 코드와 상태 문구
- 유형과 분류(`Sec-Fetch-Dest` 기준, 없으면 content type으로 판단)
- 개시자, 전송 크기, 시간
- 출구 주소, 원격 주소, 페이지에서 정한 리퍼러 정책
- 마커를 뺀, 보낸 그대로의 요청 헤더
- 받은 그대로의 응답 헤더(Chrome 패널처럼 `Set-Cookie` 포함)
- 압축을 푼 본문. 각각 64 KB로 자르며, 응답은 스트리밍하면서 앞 64 KB만 남김

목록에는 학습자의 요청 외에 두 종류의 행이 더 나옵니다.

- 첫 페이지 이후 세션·호스트마다 한 번 가져오는 `/favicon.ico`
- 페이지가 참조하는 같은 호스트의 스타일시트·스크립트·이미지 중 예전에 200으로 받았고 1.5초 안에 다시 요청되지 않은 항목마다 넣는 `disk cache` 행(`cache: "disk"`, 크기 0)

목록은 `GET /api/sessions/<id>/site/requests/?after=<id>`, 요청 하나의 전체 내용은 `.../site/requests/<id>/`로 가져옵니다.

개발자 도구 패널은 Chrome의 네트워크 패널을 본뜬 것으로, 페이지 아래에 붙어 있고 위쪽 가장자리를 끌어 높이를 조절합니다.

- 패널이 열려 있고 탭이 보이며 세션이 열려 있는 동안 2초마다 목록을 가져옵니다. 닫힌 세션은 409를 응답하고, 그러면 폴링을 멈춥니다.
- 열은 이름(경로 마지막 부분과 쿼리, 마우스를 올리면 전체 URL), 상태(4xx와 5xx는 빨간색), 유형, 개시자, 크기, 시간입니다.
- 도구 모음에는 지우기, 필터, 로그 보관(끄면 페이지 이동 시 목록을 지움), 유형 칩(모두, Fetch/XHR, 문서, CSS, JS, 이미지)이 있습니다.
- 행을 고르면 헤더, 페이로드, 미리보기, 응답 탭이 나옵니다.
  - 헤더 탭에는 일반(요청 URL, 요청 메서드, 상태 코드, 원격 주소, 리퍼러 정책), 응답 헤더, 요청 헤더가 나오고, 항목마다 원본 보기가 있습니다.
  - 페이로드 탭에는 디코딩한 쿼리 문자열 매개변수(소스 보기, 인코딩된 URL 보기)와 폼 본문이 나옵니다.
- 행, 탭, 줄에는 코치용 `data-coach`를 붙입니다.
- 라벨은 Chrome의 한국어 문구(`front_end/core/i18n/locales/ko.json`)를 그대로 씁니다. 패널 어디에도 "WAF"라는 말은 없습니다.

브라우징 요청에는 세션 고유의 비밀값을 마커로 붙입니다.

- 비밀값은 `Session.browse_marker`로, `browse-` 뒤에 무작위 16진수 32자리를 붙인 값이며 세션을 만들 때 생성합니다. 브라우저가 보낸 `X-Request-ID`는 기록기에서 덮어씁니다.
- 요청은 고객 주소에서 나갑니다(위 참고).
- 이 요청에서 나온 경보도 다른 경보와 똑같이 수집되어 목록에 나오므로, 학습자는 Kibana와 `/detections/`에서 찾아볼 수 있습니다.
- `/score/`에서는 재실행(`views.REPLAY_MARKS`)을 빼는 것과 같은 방식으로, 그 세션의 비밀값이 붙은 탐지 기록을 뺍니다. 브라우징은 케이스가 아니므로 정탐도 오탐도 아니고, 출처를 알 수 없는 경보로도 치지 않습니다.
- 손으로 보낸 `X-Request-ID: browse`는 알 수 없는 마커로 취급되어 점수에 들어갑니다.
- `POST /api/attacker/label/`은 `browse`로 시작하는 label을 거부합니다.
- API에는 비밀값이 노출되지 않습니다. `/detections/`, `/api/detections/<id>/`(`raw` 포함), 네트워크 패널에는 그 자리에 `browse`가 나옵니다. Kibana는 블루팀의 도구이므로 비밀값이 그대로 보입니다.
- 레드팀 콘솔의 웹사이트 창도 같은 세션의 같은 창입니다. 워게임에서는 공격자의 브라우징에도 세션 비밀값이 붙으므로, 방어자의 브라우징처럼 `/score/`에서 빠지고 방어자의 네트워크 패널에 나옵니다. 미해결: 사람 대 사람 워게임인 4.2는 아직 만들지 않았습니다.

API로 실행한 HTTP 케이스는 출발지 선택 여부와 상관없이 세션 워게임의 `Host`인 `board.com`을 싣습니다.

- 출발지를 고르면 공격 박스에서 `set-origin`을 실행해 박스의 출발 주소를 그 출발지 주소로 바꿉니다(SNAT). 대상 URL은 출발지와 상관없이 같습니다(`ATTACKER_TARGET_URL`).
- `rotate`는 무작위 선택이 아니라 세션별 라운드 로빈입니다.

API로 실행한 도구 케이스는 출발지의 대상 URL로 보냅니다. 출발지를 고르지 않았으면 선언된 기본 출발지에서 `TARGET_URL`(`http://board.com`)로 보냅니다.

대상 시스템은 호스트에 publish하지 않으므로 명령줄 harness도 훈련 환경 안에서 접근합니다.

- `redteam/run.py`는 플랫폼에서 실행하며, acceptance 테스트도 같은 방식으로 돌립니다.
- 출발지 옵션은 없습니다.
- `--target`의 기본값은 `--cases` 파일이 속한 시나리오의 `public_url`(board는 `http://board.com`)이고, 이 주소는 포트 80의 WAF로 해석됩니다.
- `--tool-target`의 기본값은 `http://board.com`입니다.

WAF 컨테이너에서는 `deploy/waf/modsecurity.conf`의 `SecRuleEngine On`, CRS 기본 임계치 5, Paranoia Level 1로 CRS를 돌립니다.

- Paranoia Level과 룰 예외는 세션마다 따로 둡니다(`Session.waf`). 세션을 열 때 시나리오의 defense 값으로 쓰고, 이후에는 `/api/sessions/<id>/waf/`로 바꿉니다("세션, WAF 설정 조정, 단계 엔진").
- `GET`은 10초 timeout으로 파일을 읽으므로, 폴링 한 번이 서버 스레드를 10초 넘게 잡지 않습니다.
- Suricata 룰은 모두 `alert`이므로 훈련 환경에서 차단은 WAF에서만 일어납니다.

## 경보의 경로

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, logs-<slot>-sensors
                                     (event.module) pipeline geoip
                                                          |
             POST /api/sessions/<id>/ingest/ (called by tests, at close, by the scenario engine and by lesson checks)
                                                          |
             parse per event.module, copy the marker onto alerts, store
             as Detection rows in SQLite
```

`ingest/` 호출 시점:

- `test/conftest.py`와 세션 화면의 종료 확인에서 호출합니다.
- `redteam/run.py`는 호출하지 않고 curl 명령만 출력합니다.
- 워게임 세션은 종료할 때 한 번 수집합니다.
- 레슨과 시나리오는 진행 중에도 수집합니다. 시나리오 엔진은 15초마다 최근 180초를, 기록을 읽는 단계 점검은 점검할 때마다 최근 600초를 수집합니다.
- 종료 뒤에는 따로 수집하지 않습니다. 이벤트 시각이 종료 1분 뒤보다 늦은 경보는 `ingest/`를 다시 호출해도 조회 기간 밖이라 들어오지 않습니다.

경보에 마커가 붙는 방식:

- ModSecurity audit log에는 요청 헤더가 남으므로 경보에 마커가 처음부터 들어 있습니다.
- Suricata alert 이벤트에는 요청 헤더가 없고, `http` 이벤트에만 있습니다(`dump-all-headers: request`일 때. `custom: [X-Request-ID]`로는 남지 않습니다).
- 그래서 ingest에서 `(flow_id, tx_id)`가 같은 `http` 이벤트의 마커를 alert로 복사합니다. `flow_id`만으로 조인하던 때는 keep-alive 연결의 경보가 전부 그 연결의 첫 케이스로 잡혔습니다.

ingest를 호출할 때마다 수행하는 작업:

- 비활성화 시간이 지난 룰부터 다시 활성화합니다.
- `logs-<N>-*`를 읽습니다(`ELASTIC_SESSION_INDEX`, N은 세션의 슬롯).
  - 공유 수집기는 syslog 줄마다 송신자 hostname으로 슬롯(도메인 앞의 `-N`, 없으면 슬롯 1)을 판별해 태그를 붙이고 그 슬롯의 인덱스에 씁니다. 이 태그는 ingest 파이프라인에서 저장 전에 지웁니다.
  - Filebeat에서 모든 이벤트에 `event.module`(`suricata` 또는 `modsecurity`)을 붙이고, 둘 다 아닌 syslog 줄은 버립니다.
  - 따라서 인덱스에는 두 엔진의 이벤트만 남고, 학습자가 Kibana에서 볼 수 있는 필드·인덱스·헤더 어디에도 플랫폼 이름이 드러나지 않습니다(케이스 마커는 `X-Request-ID` 헤더에 실립니다).
- Elasticsearch에는 세션 시작 1분 전부터 종료 시각(또는 현재) 1분 뒤까지의 `@timestamp`로 조회합니다.
  - `geoip` 파이프라인에서 `@timestamp`를 이벤트 발생 시각(Suricata의 `timestamp`, ModSecurity의 `transaction.time_stamp`)으로 덮어씁니다.
  - 그래서 조회 기간은 Filebeat가 읽은 시점이 아니라 이벤트가 발생한 시점 기준입니다.
- 오래된 순으로 5000건씩 읽습니다.
  - 결과가 잘리면 받은 문서 중 가장 최근 `@timestamp`부터 다시 조회하고(`api/views.py` `_fetched`, 최대 40회 추가), 이미 읽은 문서는 `_id`로 건너뜁니다.
  - 그래도 조회 기간을 다 못 읽었거나 5000건이 전부 같은 시각이면 응답에 `truncated`를 싣고 세션에 `read_of`를 기록하며, 점수에는 `score.warning.truncated`가 붙습니다.
  - sqlmap 케이스 하나만으로 기록이 5000건을 넘기 때문에, 한 번만 읽던 때는 그 뒤에 실행한 케이스가 모두 FN으로 처리됐습니다.
- Suricata `alert` 이벤트는 그대로 쓰고, ModSecurity 기록은 매칭된 룰 메시지마다 `Detection`(id `<Elasticsearch _id>:<n>`)으로 나눕니다.
- 이벤트 시각이 조회 기간을 벗어난 경보는 버리고 `stale`로 셉니다.
- 마커 없이 저장된 행에 나중에 찾은 마커를 채웁니다.
- `src_host`와 `dest_host`는 substrate의 구간 정보로 채우고, substrate에 접근할 수 없으면 비워 둡니다.
  - 단계 폴링과 답 확인 때마다 클라우드를 조회하지 않도록, ingest와 `/detections/`는 열린 세션의 구간 정보를 세션이 닫힐 때까지 재사용합니다.
  - `/top/`, `/map/`, `/topology/`는 매번 새로 조회합니다.

Elasticsearch는 저장과 색인 시점 GeoIP 보강 용도로만 쓰므로 Logstash는 두지 않았습니다.

- 조회 기간 검색 외에 쿼리 엔진은 쓰지 않습니다.
- `GET /api/sessions/<id>/map/`과 `/top/`은 SQLite 사본을 놓고 Python에서 계산합니다.
- `src_geo.location`은 `geo_point`가 아니라 float 두 개로 매핑합니다.
- `bin/worldmap`으로 남위 60도에서 자른 Equal Earth 도법 월드맵을 생성하지만, 블루팀 대시보드를 없앤 뒤로는 이 지도를 그리는 콘솔 화면이 없습니다.

`src_geo`는 geoip 프로세서 두 개에서 씁니다. 하나는 `src_ip`(Suricata), 다른 하나는 `transaction.client_ip`(ModSecurity)를 대상으로 합니다.

- compose에서 관리형 다운로더를 끄고 `bin/fetch-geoip`로 채운 `./config/ingest-geoip`를 bind-mount합니다. 그래서 컨테이너를 다시 만들어도 `GeoLite2-City.mmdb`가 남습니다.
- 파이프라인은 기동 시 entrypoint에서 등록합니다(`platform/register_pipeline.py`). `kibana.py`처럼 백그라운드로 돌기 때문에 Elasticsearch가 올라오는 중에도 플랫폼은 서비스를 시작합니다.
- 플랫폼은 waitress(스레드 16개)로 127.0.0.1:8001에서 서비스합니다.
- entrypoint에서 nginx 설정을 검사하고, 이 포트가 연결을 받기 시작한 뒤에 nginx를 띄웁니다. 그래서 플랫폼이 뜨는 중이라 nginx가 502를 내는 일은 없습니다.
- nginx는 모든 location에 `proxy_max_temp_file_size 0`과 1 MB 요청 본문 버퍼를 적용해, 프록시 응답이나 요청 본문을 임시 파일로 쓰지 않습니다.

Django는 `DJANGO_DEBUG=1`이 아니면 `DEBUG`를 끄고 실행합니다.

- `DJANGO_SECRET_KEY`가 없으면 entrypoint에서 `/data/secret-key`(모드 600)에 키를 한 번 생성합니다.
- `DEBUG`가 꺼져 있는데 키가 없으면 `cr/wsgi.py`에서 서비스를 거부합니다.
- `/api/` 아래 404는 JSON `{detail}`로 응답합니다(`api/refusals.py`).

## 세션, WAF 설정 조정, 단계 엔진

세션은 `POST /api/sessions/` `{scenario, guidance, lesson, defense}`로 열고, 이 값을 세션에 저장합니다(마이그레이션 0015, 0022).

- `scenario`는 워게임(기본값 `board`)이나 시나리오 id입니다. 시나리오로 열 때는 `lesson`, `guidance`, `defense`를 받지 않습니다("시나리오").
- 워게임 세션의 `defense`는 그 워게임에 선언된 `defense` 항목 중 하나입니다(기본값 `full`).
- `guidance`는 기본값이 꺼짐이고 `lesson`을 주면 켜지며, 워게임에 `foundations`가 선언돼 있어야 씁니다. `guidance: false`와 `lesson`을 함께 주면 거부합니다.
- `{"lesson": "f1"}`~`"f6"`은 해당 기초 레슨을 열고, `{"guidance": true}`만 주면 `order`가 가장 앞인 레슨(f1)을 엽니다.
- 레슨은 `Session.lesson`에 저장하고 `lesson_id`로 보고합니다. 가이드 세션에서 defense를 지정하지 않으면 레슨에 선언된 `defense`를 씁니다.
- 세션 `kind`는 `scenario`, `lesson`(가이드), `wargame` 중 하나입니다.
- 저장된 레슨 id에 해당하는 레슨이 더 이상 없으면 `lesson: null`, `lesson_id: null`로 읽히고 kind는 `lesson`으로 남습니다. 이전 과정의 세션이 여기에 해당합니다(`docs/DECISIONS.md` 2026-10-14).
- 마이그레이션 0026에서 `Session.mode`를 지우고 `Session.result_cache`를 비웠기 때문에, 저장된 결과는 레슨 판정 없이 다시 채점됩니다. 요청 본문의 `mode`는 무시합니다.
- `GET /api/sessions/?ids=1,2`로 세션 목록을 특정 id로 좁힐 수 있습니다.

board에 선언된 defense:

| defense | 설정 |
|---|---|
| `minimal` | CRS paranoia level 4, `local.rules` |
| `full` | paranoia level 1, 같은 `local.rules` |
| `ids` | paranoia level 1, `no-uri-sqli.rules` (sid 9000001을 뺀 `local.rules`) |
| `xss-gap`, `overbroad` | "기초 레슨 F1-F6" 참고 |
| `level2`, `level3`, `inherited`, `untuned`, `broken-rule`, `spelled` | 시나리오용 방어 설정, "시나리오" 참고 |

레슨마다 `defense`가 이 목록에 있는지 discovery 시점에 대조합니다. `minimal`로 시작하는 레슨이나 시나리오는 없으므로, `minimal`은 이름을 직접 지정할 때만 쓰입니다.

세션을 열 때의 처리:

- 그 defense의 룰 파일을 센서에 넣고, defense가 없으면 `local.rules`를 넣습니다(`suricata.seed`).
- defense가 있으면 CRS 설정을 씁니다(`crs.apply`).
- 가이드 세션은 이어서 레슨의 `cases`를 한 번 재실행합니다(`meta.seed`. curl이 보고한 상태 코드를 기록하고, 403이면 `blocked`). 그래서 학습자가 들어올 때는 이미 Kibana에 ModSecurity와 Suricata 기록이 있습니다. 단계형 시나리오는 재실행하지 않습니다.

룰 파일이 `local.rules`이면 센서에 넣는 단계를 건너뜁니다. 준비 확인(readiness)에서 모든 센서에 이 파일이 들어간 뒤에야 슬롯을 내주기 때문입니다. 룰 파일은 슬롯별 센서가 따로 갖고 있으므로(2026-10-13 측정: 슬롯 1에 적용한 sid가 슬롯 2에는 없었음), 다른 룰 파일은 해당 슬롯의 센서에만 넣습니다.

세션을 열면서 재실행에 실패하면 503으로 응답하고 세션을 닫습니다.

`platform/rules/crs.py`에서 설정을 `REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`로 생성합니다. `crs-setup.conf` 다음, 룰보다 먼저 로드되는 CRS hook이며 내용은 아래와 같습니다.

- `tx.blocking_paranoia_level`과 `tx.detection_paranoia_level`을 설정하는 `SecAction`
- 항목별 런타임 예외 규칙(id 10000~10020). 형식은 `ctl:ruleRemoveTargetById=<id>;<target>`, `ctl:ruleRemoveById=<id>`, 또는 CRS `tag`와 target을 지정한 항목(예: `OWASP_CRS`)이면 `ctl:ruleRemoveTargetByTag=<tag>;<target>`입니다. 경로가 있으면 `SecRule REQUEST_FILENAME "@beginsWith <path>"`로 범위를 좁힙니다.

파일 적용 순서:

1. `runner("gateway")`로 세션의 WAF에 파일을 씁니다.
2. `nginx -t && nginx -s reload`를 실행하고, nginx가 거부하면 이전 파일로 되돌립니다.
3. reload 전에 없던 워커가 뜨면 반환합니다. 워커 PID는 `/proc`에서 부모 PID로 찾습니다. 새 연결부터 새 설정이 적용되고, 이전 워커는 처리 중이던 느린 요청을 마저 끝낼 수 있습니다.
4. 5초 안에 새 워커가 보이지 않으면 reload가 안 된 것으로 보고, 이전 파일로 되돌려 다시 reload한 뒤 요청을 거부합니다.

입력은 쓰기 전에 검증합니다.

- paranoia는 1-4
- 룰 id는 900000-999999, 또는 영문자·`_`·`-`로 된 tag와 target
- target은 `ARGS`, `ARGS_GET`, `ARGS_POST`, `ARGS_NAMES`, `REQUEST_COOKIES`, `REQUEST_HEADERS`(`:이름` 선택), `REQUEST_URI_RAW`(PL3에서는 한글 검색어가 이 대상으로도 920272에 매칭됨), `REQUEST_BODY` 중 하나
- 경로는 `[A-Za-z0-9_./-]`
- 항목은 최대 20개
- `thresholds` `{inbound, outbound}`(1-100000)는 선택 항목이며, 레벨과 같은 `SecAction`에 `tx.inbound_anomaly_score_threshold`와 `tx.outbound_anomaly_score_threshold`로 넣은 뒤 다시 읽어 확인

`PUT`에서 `thresholds`를 빼면 현재 값을 유지하고, `"thresholds": null`이면 값을 지웁니다.

설정 변경은 `PUT /api/sessions/<id>/waf/`로 합니다. 에이전트용 경로라서 이를 호출하는 콘솔 화면은 없습니다.

`GET`에서는 세션 WAF의 파일을 `crs.read`로 다시 읽습니다. `crs.read`는 Paranoia Level과 `ctl:ruleRemove*` 줄을 모두 파싱하고, 주석 처리된 줄은 건너뛰며 이어지는 줄은 합칩니다. 그래서 학습자가 설정을 조정하는 WAF 터미널에서 직접 고친 내용도 보고에 반영됩니다.

WAF 상태 스냅샷:

- 시나리오 최종 점검에서 구간을 판정할 때마다, 그리고 세션을 닫을 때마다 슬롯을 초기화하기 전에 `crs.read`로 읽은 내용을 스냅샷으로 남깁니다.
- 스냅샷은 `Session.waf_snapshots`에 쌓입니다(마이그레이션 0021): `{at, scenario_window|closed, waf}`. 이전 과정의 세션에는 VERIFY 실행 때 남은 `{at, run, waf}`도 있습니다.
- 가장 최근 스냅샷은 `Session.waf`이기도 해서, 닫힌 세션도 파일을 포함한 학습자의 마지막 설정을 보고합니다(한 번도 읽지 못했으면 `file: null`).
- WAF를 읽지 못하면 스냅샷은 남기지 않지만, 최종 점검이나 세션 종료가 막히지는 않습니다.

조치 유형(`lesson.fix_class(waf, posture)`, 결정 D1)은 학습자가 세션에 선언된 방어 설정(posture), 곧 세션이 시작한 defense에서 무엇을 바꿨는지를 나타냅니다. 결과는 아래 중 하나이고, 위에서부터 차례로 확인합니다.

1. `level`: Paranoia Level을 방어 설정보다 낮춤. 레벨이 없는 파일은 CRS 기본값 1로 간주
2. `threshold`: anomaly 임계치를 방어 설정보다 높임. 설정하지 않았으면 CRS 기본값 inbound 5, outbound 4로 간주
3. `rule`: 방어 설정에 없던 예외 규칙으로 룰 전체를 뺌
4. `target`: 추가한 예외 규칙으로 모든 경로에서 target을 뺌
5. `path_target`: 추가한 예외 규칙이 모두 특정 경로 하나에서만 target을 뺌
6. null: 추가한 것이 없음

시나리오 최종 점검에서는 조치 유형을 판정 옆에 함께 보고하지만(`result.fix`, `result.scenario.fix`), 판정에는 영향을 주지 않습니다.

`platform/lesson.py`에는 조치 유형 함수 외에 아래가 들어 있습니다.

- 단계 답 처리 함수: `answered`, `status_said`, `an_address`, `alerts_on`, `rules_named`, `added_rules`, `raised_rev`, `pasted_rows`, `server_errors`, `server_error_sources`, `alerted_by`, `detected_penalty`, `objective_outcome`
- 도움 사용 횟수
- 시나리오 디브리핑에 보여 주는 추가·삭제된 예외 규칙과 파일 diff(`exclusions_changed`, `config_diff`)

`views.REPLAY_MARKS`(`seed`, `verify`, `check`, `replay`) 중 하나가 마커로 붙은 케이스는 `/score/`(TP/FP/FN/TN, 케이스가 일으킨 경보, 게임)에서 제외하고, corp의 효과 관찰에서 변화를 귀속시키는 시간 구간에서도 제외합니다.

- 정상 `seed` 케이스만은 예외입니다. 레슨의 seed 재실행을 정상 케이스로 채점하기 때문에(2026-10-18) 레슨 세션에도 TN이 생깁니다.
- 지금 쓰는 마커는 `seed`뿐입니다. `verify`, `check`, `replay`는 이전 세션에 남은 재실행이 계속 두 점수에서 빠지도록 목록에 남겨 뒀습니다.

콘솔은 화면 네 개이고, 모든 화면은 `/api/`에서 데이터를 가져옵니다. 사용자가 승인한 정적 시안에 사용자 결정 두 가지를 반영했습니다(`docs/DECISIONS.md` 2026-10-11, 콘솔 재설계). 색상 팔레트와 컴포넌트 클래스는 `base.html`과 `platform/console/components.css`에 있고, `bin/build-css`로 `tailwind.css`에 넣습니다. 머리글에는 경로 표시(breadcrumb)와 훈련 환경 상태를 둡니다. 콘솔은 한국어 전용이며 언어 전환은 없습니다.

- **메인**(`/`):
  - 진행 중인 세션은 진행 내용(과정 이름, 과정에 속하지 않은 레슨이면 레슨 이름, 시나리오 번호와 제목, 또는 워게임과 대상 시스템)과 기초 레슨 세션의 현재 단계를 함께 보여 줍니다. "준비 중 n초"는 세션을 여는 중일 때만(`ready`, `Session.ready_at` 기준) 표시합니다(80초라는 예상치는 추측이라 뺐습니다).
  - "대상 시스템" 아래에 워게임 카드(이름과 한 줄 설명)가 있습니다. `GET /api/wargames/`의 공격 케이스·정상 케이스·목표 수는 운영자에게만 보입니다. 페이지 제목, 예상 소요 시간, 분류, 난이도, 시나리오 유형·안내 수준 칩은 두지 않습니다(2026-11-14).
  - 카드마다 그 아래에 기초 레슨 묶음, 시나리오 묶음("시나리오"), 워게임 묶음이 있고, 행마다 버튼은 모두 "시작"입니다.
    - 기초 레슨 묶음에는 레슨마다 "레슨 n"과 제목이 나옵니다. 시작 버튼을 누르면 레슨에 선언된 defense로 `{scenario, guidance: true, lesson, defense}`를 보내고, 시나리오를 시작할 때처럼 블루팀 콘솔로 바로 갑니다. 레슨 중에 콘솔 버튼 하나만 있던 세션 화면은 거치지 않습니다(2026-11-15).
    - 시나리오 행에는 번호와 제목만 나옵니다. 실습 내용 한 줄(`practise`)은 셋이 제목을 되풀이했고 하나는 과정 1 정렬 단계의 답인 `?sort=`를 노출해서 뺐습니다(2026-11-15).
    - 워게임 묶음(`[data-wargame-start]`)에는 제목과 시작 버튼만 있습니다. 시작하면 `{scenario}`만 보내므로 가이드 없이 defense `full`로 열립니다.
  - 카드 그리드는 위쪽 정렬이라 짧은 카드가 긴 카드 높이로 늘어나지 않습니다.
  - 이 브라우저에서 가장 최근에 연 실행을 보여 주던 줄("마지막 세션: n번 (레슨) 종료")은 끝난 세션 표와 겹쳐서 뺐습니다(2026-11-15). `cr-opened-sessions`는 세션 화면과 블루팀 화면에서 계속 씁니다.
  - 끝난 레슨 세션 행에는 과정 이름(과정 밖이면 레슨 이름)이 나옵니다. 결과 칸에는 과정 카드의 `scored`가 켜져 있을 때만 목표를 보여 주고(`wargames._course_scored`: `kali`나 `replay` check가 있는 과정), 과정 1은 "—"로 표시합니다.
  - 끝난 세션 목록에는 진행 내용과 `result`가 함께 나옵니다. `result`는 시나리오면 마지막 최종 점검의 통과·미통과(`scenario.phase.passed`, `scenario.phase.failed`. 영어 표기 없음)(`result.scenario`), 아니면 전체 목표 중 탈취된 목표 수(`result.lost`. 그중 알아채지 못한 수는 이제 붙이지 않음)입니다.
  - 결과는 한 번 채점해서 채점 입력과 함께 저장합니다(`Session.result_cache`, 마이그레이션 0018). 입력은 `ended_at`, 힌트 수, 최종 점검별 판정이고, 탐지 기록·케이스·목표는 각각의 마지막 id와 행 수, 탐지 기록은 여기에 마커가 있는 행 수까지 들어갑니다.
  - 목록을 그릴 때는 세션마다 집계값 세 개만 읽고, 늦은 수집처럼 입력이 바뀐 세션만 다시 채점합니다.
  - 시작이 거부되면 누른 버튼 아래에 알립니다. 409일 때는 "열린 세션 종료"에서 열린 세션을 나열하고, 하나씩 `ingest/` 후 `close/`로 닫습니다. `max_sessions`는 `GET /api/range/ready/`로 받습니다.
  - Kali 상표 고지(`topology.trademark`)는 하단에 있습니다. 전에는 구성도 창 아래에 있었습니다.
  - 훈련 환경 관리 항목(경보 수집 확인, 열린 세션 수, 훈련 환경 상태, 워게임 카드의 개수)은 `?operator`일 때만 보입니다.
- **세션**(`/session/<id>/`):
  - 머리글에는 가이드 세션의 현재 단계(`main.step`. 라벨이나 레슨 번호 없이)와, 진행 중이면 탈취된 목표(결과 화면에서는 주 점수에 나오므로 생략)가 나옵니다. 세션 종류는 쓰지 않고, 경로 표시에 이미 있는 대상 시스템은 반복하지 않으며, 상태는 세션을 여는 중일 때만 보여 줍니다. 그 아래 줄에는 과정이나 레슨 이름과 시각이 나옵니다. 진행 중인 시나리오는 시작 시각만 보여 주는데, 시나리오 시계는 세션이 열릴 때가 아니라 상황 설명에서 시작을 누를 때 돌기 시작하기 때문입니다.
  - "블루팀 콘솔 열기" 버튼이 있고, "레드팀 콘솔 열기" 버튼은 워게임 세션에만 있습니다.
  - 워게임 세션은 `GET /api/sessions/<id>/cases/`로 최근 케이스를 보여 줍니다. 레슨은 진행 중에 자동 요청을, 시나리오는 예정된 공격을 숨기므로 둘 다 최근 활동 패널이 없습니다(시나리오에서는 콘솔에 경보가 떠 있는데도 "아직 공격이 없다"고 나왔습니다).
  - 세션이 닫히면 아래 순서로 보여 줍니다.
    1. 시나리오의 판정 배너와 디브리핑("시나리오")
    2. 주 점수: 모든 등급의 목표별 결과 열(지킴, 탈취됨 · 탐지, 탈취됨 · 미탐), 감점(난이도 ×1 또는 ×2), 탈취 판정 방법 한 줄
    3. "탐지 결과" 아래 방어 판단 집계. 예를 들면 "공격 8건 중 7건 정탐", "정상 요청 4건 중 3건 경보 없이 통과"이고, 틀린 항목은 그 아래에 한 번만 나열합니다. 실행 한 번을 1건으로 센다는 설명 줄이나 탐지가 공격 기법을 짚었는지 보여 주는 열은 없습니다(`corroborated`는 API에만 있음). 시나리오 결과에서는 차단된 고객 요청을 결과 보고에만 두고, 실행된 공격이 없으면 없다고 밝히며, 요청별 표가 비면 숨깁니다. 요청별 결과는 배지 대신 색 글자로, 목표 결과는 "탈취됨, 탐지"나 "탈취됨, 미탐"으로 표시합니다.
    시나리오 결과 보고에서는 빈 항목(기록된 공격 로그, 적용 전·후로 판정한 요청, 남은 위험이 없을 때)과 0회인 최종 점검 횟수를 빼고, 공격 출발지는 나라 이름으로 보여 주며(`scenario.origin.<code>`), "웹방화벽 설정을 바꾸지 않았습니다"처럼 시나리오에 맞는 문구를 씁니다.
  - TP/FP/FN/TN과 게임 밸런스는 API에만 있고 사람이 읽는 문구에는 나오지 않습니다(`test_strings.py`).
  - 레슨 세션 화면에서는 실행마다 케이스 이름으로 부르고, Kali 실행은 케이스 id 대신 "레슨 n · m단계"로 부릅니다(`per_case[].lesson`, `.step`, `.seed`). 레슨 카드에는 수강한 레슨마다 통과한 단계가 나옵니다(건너뛴 수는 없음).
  - "다시 시작"을 누르면 같은 시나리오, 같은 레슨(`lesson_id`가 있으면 `{scenario, guidance: true, lesson, defense}`), 또는 같은 워게임을 다시 엽니다. 레슨과 시나리오는 블루팀 콘솔로 열립니다.
  - 이미 닫힌 세션을 종료하면(두 번 누르거나 다른 탭에서 닫은 경우) 세션을 다시 읽고, `ended_at`이 있으면 409 영어 메시지 대신 종료됐다고 알린 뒤 결과를 보여 줍니다(`base.html`의 `alreadyClosed`. 메인 화면과 레슨 끝에서도 동일).
- **블루팀**(`/blue/<id>/`):
  - 왼쪽 메뉴와 창으로 구성됩니다. 메뉴는 Kibana, 웹사이트, 구성도 순이고, 그다음 `judgement` 시나리오의 경보, `detection`·`unknown` 시나리오나 그 창을 쓰는 단계가 있는 레슨(F4)의 IDS 룰, WAF가 옵니다. 그 아래 구분선 밑에 Kali가 있습니다.
  - Kali는 세션 `kind`가 `lesson`이나 `scenario`일 때만 보입니다. `wargame` 세션에서는 사람이 레드팀 콘솔에서 공격하므로 방어자에게 공격자 쉘을 주지 않습니다.
  - Kali 창은 한 번만 로드하는 별도 프레임이라 다른 창으로 옮겨도 돌고 있던 sqlmap이 끊기지 않습니다.
  - WAF 창 배너에는 WAF 박스(`waf_box`, `waf`)와 CRS 룰 디렉터리(`waf_rules`)만 나옵니다. 이 디렉터리는 선언된 예외 파일 `settings.CR_WAF.rules`가 있는 디렉터리입니다.
- **레드팀**(`/red/<id>/`):
  - 위쪽에는 세션과 워게임 이름, 목표(한국어 이름은 `objective.<key>`), "탈취한 해시 제출"이 있습니다.
  - 왼쪽 메뉴의 창은 두 개로, 세션의 Kali 터미널과 웹사이트 창(주소 표시줄과 개발자 도구, 블루팀 콘솔과 같은 스크립트)입니다.
  - 미리 준비한 공격은 실행하지 않으므로 케이스 목록, 실행 버튼, 기록 창, 출발지 선택이 없습니다(2026-10-18).
  - 화면 폭이 좁으면 메뉴가 창 위로 올라가며, 레드팀·블루팀 화면 모두 가로 스크롤이 생기지 않습니다.

가이드 세션(기초 레슨이나 단계형 시나리오)의 레슨 노트는 창을 덮지 않고 창 옆에 열로 붙습니다.

- 너비는 340 px(1280 px 이하에서는 300 px)이고, 접으면 44 px 띠("단계 n/N")가 됩니다. 1024 px 미만에서는 창 아래 패널로 내려갑니다. 머리글은 레슨이면 "레슨 노트", 시나리오면 "시나리오 노트"이고 부제는 없습니다.
- 노트 구성(위에서부터):
  - 단계 카드: 단계 n/N, 단계 제목, 할 일, 단계 진입 후 입력할 명령, 단계의 창이 안 보일 때 나오는 "<창> 열기" 버튼, 질문과 입력란, 상태 줄, 도움말, 이전, 다음 버튼(`step-next`. 통과한 단계에서는 `lesson.coach.next`, 아니면 `lesson.skip`으로 읽힘)
  - F6의 목표 카드는 단계 카드와 직접 해 보기 카드 뒤에 옵니다. 이론 카드는 없습니다(2026-11-13, 이론에 있던 내용은 참고 열과 과정 안내로 옮김).
  - F6의 목표 카드(`lesson_objectives`): 모든 목표를 난이도와 함께 나열하고, 레슨 시작 후 목표별로 탈취 여부와 그 탈취의 탐지 여부를 보여 줌. 감점 열과 합계는 없음
  - 단계형 시나리오의 카드와 힌트
  - F4와 F6의 채점하지 않는 "직접 해보기" 카드
  - 접힌 단계 목록
- 단계 목록의 체크 표시는 `progress`에서 통과로 판정한 단계에만 붙고, 통과하지 않고 넘어간 단계에는 "건너뜀"이 붙습니다.
- 노트 접힘 상태는 사용자별로 저장합니다(`cr-lesson-note`). 보던 단계는 `cr-lesson-step-<id>-<lesson>`에 남고, 메인과 세션 화면에서 이 값을 읽어 "단계 n/N"을 표시합니다. 이 기록이 없는 브라우저(새 브라우저, 저장소를 지운 경우)에서는 서버에 `reached`로 기록된 가장 뒤 단계부터 엽니다(2026-11-14).

진행 상황은 세션 단위로 두고 레슨별로 저장합니다(`Session.lesson_steps[<lesson>][<step>]`, 마이그레이션 0020과 0027).

- 단계마다 `reached`, `passed`, `skipped`(시각), `hint`(보여 준 힌트 단계), `tries`(틀린 답 수, 초기화하지 않음)를 남깁니다. 틀린 뒤 통과한 단계는 세션 `course` 행의 `retried`에 집계합니다.
- 현재 레슨의 기록은 `GET /api/sessions/<id>/`와 모든 단계·힌트 응답의 `progress`에 담아 돌려줍니다.
- 단계 기록에는 그 단계에서 얻은 것도 함께 남습니다. 단계에 진입하면 `command`, 통과하면 `ok`(통과 시 보여 주는 문장), 단계형 시나리오에서 힌트 단계가 3(`lesson.ANSWER`)에 이르면 `answer`가 들어갑니다.
- `POST /api/sessions/<id>/lesson/steps/<step>/ {state: reached|skipped}`로 단계 진입이나, 통과하지 않고 넘어간 것을 기록합니다. check가 Kali 케이스를 가리키는 단계에 진입하면 그 단계에 마커가 발급되고, 플랫폼은 이 마커를 스탬프 프록시의 `/var/lib/session/active`에 씁니다.
- 통과하지 않은 단계에서 다음을 누르거나 목록으로 이동하면 `skipped`를 보내고, 이전을 누르거나 통과한 경우에는 보내지 않습니다.
- 통과 문장은 통과한 단계에만 보이고, 다음 단계는 빈 카드로 시작합니다.

단계는 레슨에 선언합니다(`scenario.yaml`에서 기초 레슨이나 단계형 시나리오의 `steps`). 단계 구성:

- `id`
- `check`: `kind`는 `click`, `answer`, `choice`, `rules`, `sent`, `kali`, `loot`, `triage`, `waf_changed`, `replay` 중 하나(`wargames.CHECK_KINDS`, discovery 시점에 검증)
- `point`
- 학습자가 입력할 터미널 `command`. `command` 안의 `{waf_rules}`, `{waf_reload}`, `{sudo}`는 `wargames.lesson`이 선언된 WAF 구성(`settings.CR_WAF`)으로 채웁니다.

기초 레슨 단계에는 Kibana `query`가 없고, Kibana 대상에 `kql:`을 붙일 수 있습니다. 학습자가 직접 제출한 쿼리(Discover URL의 `query`, 없으면 쿼리 입력창)가 이 정규식에 맞을 때까지(대소문자 무시) 강조는 쿼리 입력창에만 머뭅니다(단계 `write`. 말풍선 없이 테두리만 그림). 따라서 학습자가 쿼리를 쓰기 전에는 어떤 강조로도 답이 드러나지 않습니다.

세션 API는 브라우저에 필요한 것만 내려보냅니다.

- 보내는 것은 check의 `kind`와 `form`, `options`(`form: order`이면 학습자용 구성도에서 스위치를 제외한 모든 호스트), 단계 자신의 `match` 또는 `about`으로 가리킨 단계의 `match`, check에 `dev`가 있을 때의 `dev: true`(정규식은 보내지 않음), 기초 레슨 마지막 단계의 `solo`뿐입니다.
- `accept` 목록이나 정답 규칙은 브라우저로 나가지 않습니다.
- 단계의 `command`는 `progress`에 그 단계 진입이 기록된 뒤에야 응답에 포함됩니다. 입력할 문구일 뿐이라 실행 버튼이나 복사 버튼은 없습니다.
- 통과 문장(`<text>.ok.<step>`, 선택형 단계에서 고른 답에 따라 문장이 달라지면 `<text>.ok.<step>.<option>`)과 단계형 시나리오의 정답은 `strings.html` 끝의 `{% comment %}` 구역에 두어 Django가 렌더링하지 않습니다. 이 구역은 `console/strings.py`가 읽어, 학습자가 얻은 시점에 단계의 `progress` 기록에 넣습니다.
- check를 통과해도 단계가 넘어가지는 않고, 학습자가 '다음'을 눌러야 합니다. 마지막 단계만 레슨 끝 카드로 자동 전환됩니다(아래 통과 문장 항목 참고). 이전/다음은 check 없이도 이동할 수 있습니다.

check 종류별 통과 조건:

- `answer`, `choice`: 입력한 텍스트가 허용 값 중 하나와 대소문자·공백 구분 없이 같으면 통과(`lesson.answered`).
  - `form: order`는 입력한 순서대로 호스트(공백, 쉼표, `>`, `→`로 구분)를 비교하고, 호스트는 맞는데 순서만 틀리면 `<text>.wrong.<step>.order`로 알려 줍니다.
  - `wrong_if` 규칙의 `match`가 답에 맞으면 `<text>.wrong.<step>.<says>`를 띄웁니다.
  - `known`에 있는 값을 입력하면 `<text>.wrong.<step>.<value>`를 띄웁니다.
  - 허용 값은 `accept` 목록이거나, `of:`로 세션 기록에서 읽어 옵니다("기초 레슨 F1-F6").
  - 구성도 주소 단계(`of: address`)에서 틀리게 입력한 IPv4 주소가 학습자 구성도의 다른 장비 주소이면 `lesson.check.wrong.address_of`로 "다른 장비의 주소"라는 것만 알려 줍니다(`views._whose_address`). waf 주소가 F1 마지막 단계의 답이라 장비 이름과 주소는 되풀이하지 않고, 다른 단계는 각자의 문장을 씁니다.
  - `status`는 코드만 입력해도, 개발자 도구에 보이는 대로 사유 문구를 붙여도(`200 OK`) 인정합니다(`lesson.status_said`).
  - `of: rule`(`wargames.ANSWERS_OF`)은 학습자 자신의 요청이면 요청의 `path`와 `marker: browse`를, Kali 단계의 실행이면 `marker: step:<id>`를 받고, 룰 `family`로 범위를 좁힐 수 있습니다. 플랫폼은 최근 600초를 수집해 그 요청이나 실행에 해당하는 세션의 ModSecurity 탐지 기록을 모으고, CRS 합계 룰(id가 949, 959, 980으로 시작)을 제외한 나머지 `ruleId`를 모두 허용 값으로 인정합니다(`lesson.rules_named`). 기록이 없으면 사유는 `lesson.check.unrecorded`입니다.
  - `rule: <id>`가 붙은 `of: rule_matched`는 같은 탐지 기록에서 그 룰 하나만 보고 `present`나 `absent`를 허용 값으로 정합니다. 기록된 실행에 탐지가 하나도 없으면 `absent`입니다.
  - 기록된 Kali 실행의 탐지 기록이 세션에 이미 있으면 다시 수집하지 않습니다. 실행은 로그가 `RUN_SETTLED` 동안 조용해진 뒤에 기록하고, 기록 시점의 수집이 이미 그 로그를 읽었기 때문입니다.
- 활성 줄 가운데 플랫폼이 읽을 수 있는 `sid:<숫자>`(뒤에 `;`나 `)`)가 없는 줄이 있으면 문법 검사와 적용 모두 그 룰 파일을 거부합니다(`disable.unread`). Suricata 8은 `sid:9100001 rev:1;`도 불러오지만(2026-11-15 라이브 센서에서 `suricata -T`로 확인), 플랫폼은 이 sid를 인식하지 못해 확인 단계에서 룰을 추가하지 않았다고 판정하게 됩니다. 이때 문법 검사는 Suricata가 파일을 통과시킨 뒤 `{ok: false, unread_sid: true, errors: [해당 줄]}`로 응답합니다.
- `rules`: 센서의 룰 파일(`GET /api/rules/`)에 방어 설정의 룰 파일에는 없는 sid나 내용이 달라진 sid가 생기면 통과(`lesson.added_rules`, `disable.sids`)하며, 응답에 `added`가 붙습니다. `needs: nocase`이면 그 룰에 `nocase`나 `i` 플래그를 단 pcre도 있어야 합니다(`lesson.ignores_case`). `match`가 있으면 그 룰이 실제로 경보를 내야 하는데, 이 세션의 마지막 적용(세션 `RuleSet`의 `applied_at`) 이후 웹사이트 창에서 보낸 요청 중 `match`에 맞는 요청에 그 sid 경보가 있어야 통과합니다. 그렇지 않으면 `<fail>.unsent`(해당 요청 없음), `lesson.check.unrecorded`(센서가 아직 그 요청을 기록하지 않음), sid를 담은 `<fail>.silent`, sid와 대신 경보가 난 URL을 담은 `<fail>.elsewhere` 중 하나로 응답합니다. `quiet_on:`은 평범한 요청 URI 목록입니다. 룰의 URI content가 이 가운데 한 URI에 모두 포함되면(`lesson.alerts_on`, pcre가 있는 룰은 이 방식으로 판정하지 않음) 평범한 검색마다 경보를 낼 룰로 보고, 경보를 읽기 전에 sid와 목록에서 처음 걸린 URI를 담은 `<fail>.broad`로 바로 실패시킵니다. URI content가 없는 룰(`http.header`만 쓰는 룰 등)은 넓은 룰로 판정하지 않습니다.
- `triage`(`judged: customer | attack | all`): 학습자가 옳게 판정하면 통과("시나리오"). `judged: verified`는 시나리오의 최종 점검이 시작되면 통과합니다.
- `sent`: 웹사이트 창에서 보낸 요청이 `match`에 맞으면 통과. 보낸 요청이 `wrong_if` 규칙의 `match`에 걸리면 통과 대신 `loud: true`와 함께 `<text>.wrong.<step>.<says>`를 띄웁니다(카드의 예시 단어로 검색한 F3 검색 단계).
- `waf_changed`(`removed_target`): 방어 설정이 선언한 예외의 target을 WAF 파일의 어떤 예외도 더는 가리키지 않고, 파일의 Paranoia Level 줄이 여전히 방어 설정의 단계를 지정하고 있으면 통과. Level 줄을 지우거나 바꾸면 되살릴 줄(예외를 뺀 방어 설정의 `crs.rendered`)을 담은 `<fail>.paranoia`로 실패합니다.
- `replay`: `after`로 지정한 단계를 통과한 뒤, 아래 두 조건이 모두 맞으면 통과.
  - 공격(`sent` 정규식이나 `kali` 케이스)이 `expect`를 만족할 것. 학습자가 추가한 sid의 경보가 있거나, 실행이 차단되어(탐지 기록에 949110) 탈취 데이터가 인정되지 않아야 합니다.
  - 같은 시각 이후의 정상 요청이 각자의 `expect`를 만족할 것. `status_class`가 맞거나, 추가한 sid의 경보가 없거나, WAF 기록이 없어야 합니다.
  사유에는 어느 쪽이 빠졌는지가 나옵니다(`lesson.check.replay_attack`, `lesson.check.replay_benign`). 정상 요청을 보냈는데 맞지 않으면 그 요청과 어긋난 내용을 함께 알려 주며, 사유는 `lesson.check.replay_benign.status`(2xx 아님), `.alerted`(추가한 sid가 경보를 냄), `.waf_logged`입니다(`views._benign_fault`).
- `click`: check를 호출하는 즉시 통과하고, 플랫폼이 따로 확인하는 조건은 없습니다.

check 판정은 모두 플랫폼에서 `POST /api/sessions/<id>/lesson/steps/<step>/check/`로 합니다.

- 본문은 답, 선택지, 붙여 넣은 표이면 `{answer}`, 백그라운드 폴링이면 `{poll: true}`입니다.
- 이 호출로 `passed`를 기록하고 `{passed, reason, hint, hints, progress}`를 응답합니다. `rules` check는 `added`, `kali`와 `replay` check는 `kali`, `loot` check는 `loot`도 함께 돌려줍니다. 폴링에서 확실한 잘못(정상 replay 요청 실패, 지워진 Paranoia Level 줄)이 나오면 `loud: true`도 붙입니다.
- `reason`은 값이 딸린 `strings.html` 키입니다.
- 폴링이 아닌 check가 실패하면 오답으로 집계합니다. 오답이 두 번 나오면 그 단계의 힌트 단계를 올리고 힌트를 기록하며, 단계형 시나리오에서는 그 대신 시나리오의 다음 힌트를 제안합니다(`scenario_run.stuck`).

check는 학습자가 누르지 않아도 실행됩니다.

- `sent`, `triage`, `kali`, `replay`, `waf_changed`는 단계와 탭이 화면에 보이고 세션이 열려 있는 동안 5초마다 조용히 폴링합니다. 폴링(`{poll: true}`)은 훈련 환경 작업용의 긴 대기 시간이 아니라 기본 90초(`PATIENCE`)만 기다리므로, 응답 없는 폴링이 단계를 붙잡아 두지 않습니다. 세션이 닫힌 것을 알아채기 위해 화면은 30초마다 세션을 다시 읽습니다. 응답에 `loud`가 없으면 폴링 결과는 화면에 아무것도 남기지 않고, `loud`가 있으면 오답처럼 사유를 띄우며 replay의 정상 요청 줄은 "확인 중"에서 "문제 있음"으로 바뀝니다.
- `sent`와 `replay`는 웹사이트 창에 단계의 `match`(`replay`는 정상 요청의 `sent`)에 맞는 경로가 나타나고 1.5초가 지났을 때도 실행됩니다.
- `rules`는 룰 편집기에서 파일을 적용할 때도 실행됩니다. `match`가 있는 `rules` 단계는 이때 조용히 실행되고 별도의 확인 버튼을 띄우며, 학습자는 요청을 보낸 뒤 이 버튼을 누릅니다.
- 통과하면 그 단계에 `ok` 문장을 띄우고 '다음'을 강조한 채 머물며, 넘어가는 것은 학습자가 '다음'을 눌렀을 때입니다. '다음'을 누르라고 안내하는 통과 문장은 없습니다. 마지막 단계를 통과하면 레슨 끝 카드로 넘어가고, 이 카드는 버튼을 누를 때까지 기다립니다.
- 카드의 창 열기 버튼 중 웹사이트 창 버튼은, 창에 다른 페이지(XSS 검색 뒤 남은 403 페이지 등)가 떠 있으면 게시판 첫 화면도 다시 엽니다. 이후 단계들이 게시판 검색창에서 검색하기 때문입니다.
- Kali 단계 카드에는 그 실행이 테두리도 케이스 이름도 없는 한 줄로 표시됩니다. 실행 중 문장과 "Kibana에서 이 실행 시간대 열기"만 있고 "기록된 실행" 라벨은 없습니다. 단계 문구에도 실행 중 문장에도 실행이 끝나면 확인한다는 말은 넣지 않았습니다. 다음 단계에서는 이 행을 되풀이하지 않고, 이어지는 Kibana 단계의 열기 버튼으로 실행 시간대를 엽니다. 이 링크는 실행 시간대를 빈 쿼리로 엽니다. 화면을 다시 불러오거나, 가진 행에 시간대가 없으면(기록을 모으는 도중 학습자가 '다음'을 누른 경우) Kali check를 폴링해 이 행을 다시 읽습니다. 학습자가 넘어간 뒤 도착한 결과도 행에 반영됩니다. Kali 단계는 실행이 끝나면 폴링으로 자동 통과하며, 확인 버튼은 더 빨리 확인하고 싶을 때만 씁니다.
- 대상이 Kibana이거나 이후 단계가 Kibana를 여는 단계에서는 답과 함께 Kibana에 입력된 쿼리 `query`를 보냅니다. `kql`이 있는 check는 그 쿼리가 정규식에 맞지 않으면 통과하지 않습니다(`<text>.wrong.<step>.kql`). 따옴표 안에 와일드카드를 넣은 쿼리(`: "...*..."`, `views.QUOTED_WILDCARD`)는 이보다 먼저 `lesson.check.wrong.kql_quoted`로 실패합니다. Kibana에서 읽는 기초 레슨 답에는 모두 `kql`이 있어서, 구성도·참고·앞 카드에서 짐작한 값으로는 통과할 수 없습니다. `leg: upstream` check에서 `not destination : <주소>`에 board.com 자신의 주소를 넣은 쿼리도 `kql` 사유로 실패합니다(`views._excludes_the_site`). 단계에서 남겨야 할 구간을 빼 버리기 때문입니다.
- `dev`(정규식)가 있는 check는 웹사이트 창의 개발자 도구에서 읽는 답입니다. 개발자 도구가 열려 있으면 선택된 요청 행의 id를 `dev_request`로 함께 보내고(아니면 `null`), 그 행이 세션에 기록된 요청이면서 경로가 `dev`에 맞을 때만 통과합니다. 행을 고르지 않았거나, 기록된 요청이 아니거나, 경로가 맞지 않으면 `lesson.check.wrong.dev`로 실패합니다(`views._dev_picked`). 적용 단계는 F2의 메서드, 경로, 상태 코드, 파라미터, 정렬, 없는 글 단계와 F4의 인코딩 단계, F5의 정렬·오류 단계입니다.
- 숫자 뒤에 한두 글자짜리 단위("20점", "1973건" 같은)가 붙은 답은 숫자로 읽고(`lesson._unit_dropped`), `%`는 단위로 보지 않습니다.
- 기초 레슨의 마지막 단계에서는 "레슨이 끝났습니다."를 띄우고, 다음 레슨 이름이 적힌 버튼("다음 레슨: <제목>")을 학습자가 누를 때까지 기다립니다("과정마다 세션 하나"). 과정의 마지막 레슨(과정 1은 F3, 과정 2는 F6) 뒤에는 그 과정에서 들은 레슨을 레슨별 통과 단계 수와 함께 카드에 나열하고, "세션 종료" 버튼으로 세션을 닫습니다. 점수는 결과 화면에 있으니 이 카드에는 다시 싣지 않습니다. 단계형 시나리오의 마지막 단계에서는 안내 단계를 마쳤다고 알립니다(`scenario.note.done`).
- 통과 문장은 마지막 단계에서도 질문 아래 그 자리에 남습니다. 오답 문장은 학습자가 다시 입력하거나 다른 선택지를 누르면 사라지고, KQL 문제를 알리는 문장은 Kibana 쿼리가 바뀌면 사라집니다.
- 순서 고르기는 누른 버튼에 번호를 매기는 것으로만 순서를 표시하고, 아래에 이어 붙인 줄은 따로 없습니다. 버튼을 다시 누르면 빠진다는 안내는 질문에 들어 있습니다.
- 참고 칸의 열림 상태는 세션·레슨별로 따로 저장하므로(`cr-lesson-reference-<session>-<lesson>`) 새 레슨은 참고가 닫힌 상태로 열립니다.
- 룰 편집기에서 적용하지 않은 수정은 localStorage(`cr-rules-draft-<session>`, 기준 버전 포함)에 보관했다가 다시 불러올 때 복원하고 그 사실을 알립니다. 적용하면 지우며, 기준 버전이 다른 초안은 복원하지 않습니다.
- 대상 창이 이미 열려 있는 `click` 단계는 도달하는 즉시 통과합니다. 시나리오 1.1에는 경보 창을 여는 단계가 없습니다. 경보 창이 열린 채 시작하므로 첫 단계부터 고객 요청을 판정합니다.
- 오답이면 무엇이 틀렸는지 알려 줍니다.
- 최근 수집(`within`)은 구간의 최신 기록부터 읽고 잘림을 기록하지 않습니다. sqlmap 케이스 하나만으로도 기록이 5000건을 넘기 때문입니다.

도움말은 단계마다 정해진 순서로 열립니다. "힌트 보기"를 누르거나 오답·실패한 check가 두 번 나오면 다음 수준이 열립니다.

- 기초 레슨: 넛지(`<text>.nudge.<step>`, 어디를 볼지), 그다음 힌트(`<text>.hint.<step>`, 어떻게 읽는지. 정답은 말하지 않음) 순서이고, 3단계(`lesson.SKIP_OFFERED_IN_FOUNDATIONS`)에 이르면 힌트 버튼이 사라집니다.
- 단계형 시나리오: 정답 단계를 유지합니다(`lesson.ANSWER`, `lesson.SKIP_OFFERED`).
- 건너뛰기는 도움말 단계 다음에 붙어 있지 않습니다. 통과하지 않은 단계에서는 하나뿐인 다음 버튼이 `lesson.skip`으로 표시되고, 누르면 그 단계를 건너뜀으로 기록합니다.
- 누를 때마다 `POST /api/sessions/<id>/lesson/hints/ {step, level: "hint"}`로 단계의 `hint` 단계를 올립니다. 처음 한 번은 레슨 정보와 함께 `Session.hints`에 기록합니다(`{lesson, step, level}`. 마이그레이션 0017과 0027). 가이드 세션이 아니거나 레슨에 없는 단계·단계값이면 400, 닫힌 세션이면 409를 응답합니다.
- 한 단계에서 60초가 지나면 버튼 문구만 "새 힌트 보기"로 바뀌고, 학습자가 누르기 전에는 아무것도 기록하지 않습니다.
- 기초 레슨의 마지막 단계는 혼자 푸는 단계라 강조 표시, 넛지, 힌트가 없습니다.
- 건너뛰기는 `POST /api/sessions/<id>/lesson/steps/<step>/ {state: skipped}`를 보낸 뒤 다음 단계로 진입하는 동작입니다. 마지막 단계에서는 건너뜀을 기록하고 레슨 끝 카드를 띄우며, 이 카드도 통과했을 때처럼 버튼을 누를 때까지 기다립니다. 단계형 시나리오면 단계를 닫습니다.
- 학습자 대신 입력하거나 실행하거나 적용하거나 인정해 주는 동작은 없습니다. 그래서 건너뛴 단계의 기록을 읽는 뒤 단계는, 학습자가 그 단계를 수행하거나 함께 건너뛸 때까지 답할 수 없습니다. 보내지 않은 요청에 관한 답이나, 실행하지 않은 공격의 탈취 데이터가 그런 경우입니다.
- `result.scenario.helped`(`["hint"]` 또는 없음)가 있으면 메인 화면과 닫힌 세션 화면의 통과·미통과 옆에 "힌트 사용"이 붙습니다.

레슨은 첫 단계가 지정한 창(`opens`)으로 열립니다. 콘솔 코드에는 레슨 단계 이름도 CSS 선택자도 없고, 단계가 가리킬 곳은 `scenario.yaml`의 `point`에 로케이터와 필요한 창 `opens`로 적습니다. 이렇게 가리키는 강조 표시를 코치라고 부릅니다.

로케이터 종류:

- `panel`: 콘솔 요소. 사이트 주소창, 룰 편집기, 목표 행 등.
- `map`: `node`, `link`, `label: [host, switch]`, `zone`. `{switch:<host>}`는 서버에서 풀어 줍니다.
  - `{locate}`에는 `deploy/gns3/auditor.html`이 `postMessage`로 답합니다. `node`는 장비 아이콘과 이름만 포함하고 링크의 주소 라벨은 넣지 않으므로, board.com 테두리 안에 그 단계가 묻는 주소가 보이지 않습니다. 답에는 사각형, 모든 영역(zone) 도형의 사각형(`zones`), 노드·인터페이스 라벨·영역 캡션의 사각형(`text`, 말풍선이 이들을 가리지 않게 하려는 것)이 들어갑니다.
  - 이 페이지는 `{fit}`를 받으면 화면을 다시 맞추고, 첫 화면 맞춤이 끝나면 `{map: "drawn"}`을, 이후 맞출 때마다 `{map: "fitted"}`를 보냅니다.
- `site`: 출처가 다른 사이트 프레임 안의 선택자. nginx가 주입한 스크립트가 응답합니다.
- `dev`: 개발자 도구의 `data-coach` 이름. 토글, 매칭된 행, 탭, 줄 등.
- `kibana`: 출처가 같은 Kibana 프레임 안의 대상. 형태:
  - `query`
  - `hits`: 결과가 없으면 대신 `discoverNoResults`를 가리킴(그 경우용 단계). 테두리는 건수에만 두름.
  - `doc: <field>`: 문서 플라이아웃의 필드 행. 플라이아웃의 필드 필터로 행을 화면에 띄움.
  - `sidebar: <field>`: 필드 팝오버가 열려 있으면 팝오버의 "N개 레코드에서 계산" 줄(`dscFieldStats-statsFooter`), 없으면 Top values.
  - 위 형태 어디에든 `kql: <pattern>`을 붙이면 학습자의 쿼리가 맞을 때까지 쿼리 입력창을 가리킴.
  단계의 체크에 `leg`이 지정되어 있으면 코치는 그 구간 행의 펼치기 버튼을 가리키고, 다른 이벤트가 열려 있으면 플라이아웃의 화살표도 함께 가리킵니다. 구간 행이란 출발지가 다른 행의 목적지인 행, 또는 그 반대인 행입니다. 구간 행을 찾지 못하거나 열린 문서의 순서를 알 수 없으면 값 대신 필드 필터를 가리킵니다. `point`에 `keep: true`가 있으면 도착한 뒤에도 플라이아웃을 열어 둡니다.
- `term`: `{pane: kali | waf, match}`. xterm 버퍼에서 맞는 줄을 가리킵니다. 선택 항목인 `done` 패턴이 마지막으로 입력한 명령 뒤에 출력되면 테두리가 단계의 확인 버튼으로 옮겨 가는데, 그 명령에 단계 명령의 낱말이 따옴표를 빼고 모두 들어 있을 때만 그렇습니다. 그래서 앞 단계에서 끝난 실행을 이 단계가 끝난 것으로 표시하지 않습니다. 단계 명령이 실행되는 동안에는 실행 카드의 "아직 실행 중" 줄만 보이고, "기록을 모으는 중" 상태 줄과 앞서 나온 빨간 "실행 기록 없음"은 지웁니다. 빈 프롬프트를 가리키는 말풍선은 명령 입력 자리를 가리지 않도록 프롬프트 줄 아래에 둡니다.

두 단계 로케이터는 `until: sent`까지 첫 대상을 가리키다가 `then`으로 넘어갑니다(정렬 선택 상자, 그다음 페이로드 줄). `until: applied`는 단계에서 추가한 룰이 적용되고 편집기에 미적용 변경이 남지 않을 때까지, `until: dev_open`은 개발자 도구가 열릴 때까지 첫 대상을 가리킵니다. F4의 탐색 단계는 카드에서 검색 전에 개발자 도구를 열라고 하므로 개발자 도구 버튼을 먼저, 그다음 검색창을 가리킵니다. 적용하면 콘솔이 학습자가 새로 쓴 줄의 sid를 바로 추가된 것으로 표시하므로, 테두리는 check 응답을 기다리지 않고 적용 버튼을 떠납니다. `then` 안에 다시 `until`과 `then`을 중첩할 수 있으며, F4의 룰 단계는 룰 편집기, 사이트 검색창, 확인 버튼(`#step-act`) 순으로 가리킵니다.

강조 표시 렌더링:

- 창만 어둡게 하고(`pointer-events: none`) 대상에는 기본 색 테두리를 두르며, 옆에 한 줄 콜아웃을 붙입니다(`<text>.callout.<step>`, 두 번째 대상은 `.callout.<step>.then`, 세 번째 대상은 `.then.then`). 2026-11-15부터 레슨 단계에는 자체 콜아웃이 없습니다. 기존 콜아웃이 전부 테두리가 보여 주는 대상의 이름을 다시 부르거나 카드 내용을 반복했기 때문입니다. 단계 콜아웃은 테두리만으로는 할 일이 드러나지 않는 곳에만 남겼습니다. 구간 행의 펼치기 버튼, 플라이아웃의 필드, 열린 문서 플라이아웃 닫기(`covered`), 다음 문서로 넘기기(`other`), 구간별로 확인할 이벤트(`verify.<leg>`), Kali 확인 버튼이 그렇습니다. 개발자 도구 열기, 행 고르기, 개발자 도구 탭, 쿼리 작성·실행, 구간 없는 행 펼치기, 추가할 룰 줄, 적용 누르기에는 문구가 없고(탭과 룰 줄은 21회차에 뺐습니다. 단계 카드에 이미 나옵니다), 문구가 없는 단계는 테두리만 그립니다.
- 콜아웃은 창 안에서 뒤집거나 밀어서 배치하며, 대상, 왼쪽 메뉴, 툴바, 노트를 덮지 않습니다. 사이트 프레임이나 Kibana 프레임이 알려 주는 대상 주변의 글자와 컨트롤도 덮지 않습니다(Kibana는 테두리에서 220px 안의 글자와 컨트롤이며, 문서 플라이아웃에 가려진 것은 제외).
- 한 줄로 놓을 자리가 없으면 두세 줄로 줄바꿈합니다.
- 플라이아웃 단계(다음 이벤트 화살표)는 플라이아웃 안부터 찾습니다.
- 대상이 노트 카드 안에 있으면 콜아웃은 카드 옆 창에 둡니다.
- 지시선은 글자를 가로지르지 않고, 콜아웃이 테두리에서 48px 안에 있으면 그리지 않습니다.
- 구성도 위 테두리는 노드 옆 구성도 글자에 닿지 않을 때까지 여백을 줄이며(`clearOfText`), 가장 작을 때는 노드 자체의 사각형입니다.
- 로케이터가 있는 단계의 힌트는 "표시한 곳을 확인해 보세요."입니다.
- 단계의 창이 보이지 않으면 단계 카드에 "<창> 열기" 버튼(`lesson.open.<pane>`)이 나옵니다. 버튼 이름에 여는 대상이 드러나므로 강조 표시만 하고 콜아웃은 붙이지 않습니다(마지막 단계에는 강조도 없음). 단계 콜아웃은 선택 사항이며, 강조한 대상의 이름만 말하는 콜아웃(검색창, kali, DMZ)은 쓰지 않습니다.
- 약 2초 동안 대상을 찾지 못하면 카드에 어디를 볼지 안내합니다(`lesson.coach.missing`).
- 구성도는 창 크기가 마지막으로 맞춘 크기와 다를 때(창을 열거나 크기가 바뀔 때)만 화면에 다시 맞추고, 단계가 바뀌거나 레슨의 마지막 단계에 이르는 것만으로는 다시 그리지 않습니다.

모든 기초 레슨과 단계형 시나리오 단계의 `point`가 렌더링된 콘솔에서 찾아지는지는 `test_every_point_a_foundation_or_scenario_step_names_resolves_on_the_blue_console`로 확인합니다.

룰 편집기(`#lesson-rules`, 결정 D3)는 블루팀 콘솔의 IDS 룰 창에 있고, `detection`이나 `unknown` 유형 시나리오에서 `rulesPane()`으로 띄웁니다.

- 읽기는 `GET /api/rules/?session=<id>`입니다.
- `POST /api/rules/validate/`로 검사하고, 불러온 버전을 기준으로 `POST /api/rules/apply/`로 씁니다.
- 룰 검사 응답의 `errors`에는 거부한 모든 센서의 출력에서 Suricata `Error`가 들어 있는 줄을 담고, `output`에는 그런 줄이 가장 많은 거부 센서의 출력을 담습니다. 거부한 센서는 없지만 sid를 읽을 수 없는 룰이 있으면 `unread_sid: true`로 응답하며, `errors`에는 해당 룰 줄, `output`에는 빈 문자열이 들어갑니다.
- 두 센서는 콘솔 로그를 켠 같은 Suricata 이미지라서 각자 `-T` 오류 줄을 출력합니다.

### 기초 레슨 F1-F6과 두 과정

설계는 `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`의 P2 단계이고, 2026-10-18에 공격과 방어를 함께 다루는 레슨으로 다시 만들었습니다(`docs/DECISIONS.md`, "Foundations rebuilt as integrated attack and defence lessons").

board의 `scenario.yaml`에는 `foundations:` 목록을 선언합니다. 이 목록은 discovery 시점에 검사하며, id는 기초 레슨과 시나리오를 통틀어 유일해야 합니다(`wargames.checked_groups`). 가르치는 역할은 기초 레슨이 맡고, 단계형 시나리오 1.1과 3.1도 같은 엔진으로 단계를 실행합니다.

`courses:`도 함께 선언합니다(`wargames.checked_courses`). 모든 기초 레슨은 정확히 한 과정에 속하고, 과정마다 `id`, 문자열 키 `text`, `reference` 카드가 있습니다. 과정 `c1` "로그 분석 기초"는 f1-f3으로 훈련 환경을 읽기만 하고(defense `full`, 룰·Kali·WAF 변경 없음), 과정 `c2` "공격 탐지 실습"은 f4-f6으로 훈련 환경을 바꿉니다(`docs/DECISIONS.md`, "The six foundations become two courses"). 과정 1의 단계는 학습자 자신의 검색어나 마커로 자기 요청을 찾으므로, 훈련 환경이 새로 만든 상태이거나 다른 트래픽이 없다는 전제에 기대지 않습니다.

- `GET /api/wargames/`는 `courses`(`id`, `title`, `lessons`, `scored`)를 나열하고, 메인 페이지는 과정마다 구역을 나눠 레슨을 보여 줍니다. `scored`(`wargames._course_scored`)는 `kali`나 `replay` check가 있는 과정에서 true이며, 그 과정 레슨 세션의 점수 표시 여부를 정합니다.
- `GET /api/sessions/<id>/`에는 `lesson_course`(`id`, `text`, `lessons`, `reference`)가 들어 있습니다.
- 과정의 첫 레슨은 아직 어느 단계에도 진입하지 않은 동안 창 위에 과정 안내(`<course>.brief`와 접힌 참고 카드)를 띄웁니다. 시작을 누르면 첫 단계에 진입하며(`POST .../steps/<id>/ {state: reached}`), 에이전트는 이 요청을 바로 보냅니다. 과정 2 안내에는 주소가 세션마다 다를 수 있다는 말이 있습니다.
- 레일의 참고 버튼을 누르면 왼쪽 열이 열리고, 과정 카드와 레슨 자체의 `reference:` 카드(`lesson.ref.<id>.title`, `.body`, `.rows`)가 보입니다. `addresses` 카드는 `GET .../lesson/addresses/`로 채우며, F1은 주소를 묻는 레슨이라 주소 카드가 없습니다.

- `wargames.foundations()`: 기초 레슨을 `order` 순으로 나열.
- `wargames.lesson(lesson_id=...)`: 기초 레슨이나 단계가 있는 시나리오를 찾고, 그 밖의 id는 거부하며, 기초 레슨에는 `group: foundations`를 붙임.
- `GET /api/wargames/`는 `foundations`를 나열합니다(`wargames._foundation_card`). 카드 항목은 `id`, `order`, `title` 문자열 키, `minutes`, `level`, `defense`, `prerequisites`, 단계 수, `step_ids`, `changes_waf`입니다.
- 메인 페이지는 기초 레슨을 레슨 목록 맨 앞에 두고 소요 시간, 학습 내용, 시작 버튼(그 레슨을 안내와 함께 엶)을 같이 보여 줍니다.
- 모든 레슨은 `board-normal-search`를 시드로 재생합니다. 첫 레슨은 열 때, 뒤에 넘어간 레슨은 학습자가 그 레슨에서 처음 통과하거나 건너뛰거나 힌트를 볼 때 재생하며(`views._seed_once_worked`, 결과 화면의 `begun()`과 같은 기준), 따라서 콘솔이 자동으로 넘긴 뒤 학습자가 손대지 않은 레슨에는 정상 케이스가 추가되지 않습니다. 이 시드는 정상 케이스로 두 번째 점수에 들어가므로(`views._replayed`가 정상 `meta.seed` 케이스를 남김) 닫힌 레슨 세션에 TN이 생기고, 레슨 세션에서는 `no_benign`과 `no_marker`를 표시하지 않습니다.

아래는 레슨별 defense, 시작 창, 학습자가 하는 일, 답을 읽어 오는 곳입니다.

**f1 구성도 읽기**(`lesson.map`). defense `full`, 구성도 창에서 시작.

- 학습자는 kali와 board.com의 주소를 읽고, customers의 요청이 거치는 호스트를 순서대로 고르고(`path`, 출발지 `customers`), DMZ 네트워크를 읽은 다음 로그를 모으는 호스트를 답합니다. 혼자 푸는 단계에서는 waf의 주소를 묻고, 호스트가 어느 영역에 있는지는 묻지 않습니다.
- 답은 세션의 학습자용 구성도에서 읽습니다(`views._range_fact`: `topology.learner`를 거친 `topology.address`, `topology.subnet`, `topology.route`, `topology.hosts`).
  - `address`: 링크 라벨의 주소. 프리픽스 길이는 있어도 없어도 됨.
  - `subnet`: 호스트가 붙은 스위치의 네트워크
  - `path`: 단계의 `from`(기본 `customers`), 구성도에 있는 경유 역할, 사이트 순(`customers > router > waf > board.com`).
  - `logs`: `log-server` 노드

**f2 개발자 도구로 HTTP 요청 읽기**(`lesson.http`). defense `full`, 웹사이트 창에서 시작.

- 학습자는 게시판 검색창으로 검색한 뒤 네트워크 패널에서 메서드, 파라미터, 경로, 상태 코드를 읽고, 게시판 정렬 기능이 쓰는 파라미터를 찾습니다. 혼자 푸는 단계에서는 `/posts/9999/`의 상태 코드를 묻는데, 카드에도 HTTP 참고에도 그 글이 없다거나 404의 뜻은 나오지 않습니다.
- 답은 학습자가 웹사이트 창에서 보낸 요청 기록에서 읽습니다: `method`, `parameter`, `path`(요청 URL에 적힌 그대로. 답에 호스트나 쿼리가 들어가거나 끝의 /가 빠지면 `wrong_if`로 안내), `status`.

**f3 Kibana에서 내 요청 찾기**(`lesson.logs`). defense `full`, 웹사이트 창에서 시작.

- 학습자는 영문자와 숫자로 된 자기만의 단어로 검색하고(예시 단어 `kim0413`은 검색 단계에서 인정하지 않음) Kibana에 `url : *단어*`를 입력합니다. 카드마다 쿼리를 다시 적어 주고, 화면의 열 이름을 그대로 써서 아래를 묻습니다.
  - Kibana에 나오는 건수(그 단어로 한 모든 검색의 두 구간)
  - 학습자가 `and`와 `not`으로 작성한 쿼리(내 단어이면서 `destination`이 waf 주소가 아닌 것)의 건수. 이 단계의 check에는 Kibana 쿼리가 맞아야 하는 정규식 `kql`이 있습니다. Kibana를 여는 단계에서는 답을 보낼 때마다 Kibana에 입력된 쿼리도 함께 보내며, 쿼리가 맞지 않으면 숫자와 상관없이 오답으로 처리합니다(`lesson.logs.wrong.upstream.kql`). 앞 건수 단계의 통과 문장은 url 쿼리로 내 로그를 찾았다는 말만 하고, 구간마다 몇 줄이 남는지는 말하지 않습니다.
  - 그 쿼리로 남은 행의 `source_ip`(waf 자신의 주소)
  첫 건수 단계의 check에도 `kql`(`url` 조건)이 있고, 답이 참고의 주소 표에 있는 출발지 단계에도 있습니다. X-Forwarded-For 단계의 `kql`은 url 조건에 더해 `x_forwarded_for` 조건(`request_header.x_forwarded_for : *`)을 요구합니다. 이 조건이 없으면 앞 단계에서 남은 url 쿼리만으로 통과해 버립니다.
  혼자 푸는 단계에서는 그 행의 `request_header.x_forwarded_for`(customers 주소)를 Document 창에서 읽게 합니다. 웹사이트 창이 customers 자리에서 접속한다는 사실은 이 단계의 통과 문장에서 처음 나옵니다.
- 답은 기록된 센서 http 이벤트에서 구간별로 읽습니다(`sensor_source`, `forwarded_for`).
  - `dest_ip`가 board.com의 주소이면 `upstream`(waf가 넘긴 요청), 아니면 `inbound`(waf에 도착한 요청). `leg: both`는 두 구간을 모두 씀.
  - `hits`는 레슨(또는 세션) 시작 이후, 학습자의 가장 최근 검색 단어가 url에 포함된 해당 구간 http 이벤트 수입니다.

**f4 XSS 요청 차단과 IDS 룰 작성**(`lesson.xss`). defense `xss-gap`, 웹사이트 창에서 시작.

- 학습자는 `<script>alert(1)</script>`를 보내고 개발자 도구의 요청 URL에서 `<`가 무엇으로 바뀌었는지(`%3C`) 읽습니다. 주소창에는 `<`로 보이고 화면에는 nginx의 403 페이지가 뜨기 때문에 상태 코드는 따로 묻지 않습니다. 이어서 탐지한 룰 하나와 Total Score를 읽고, 대소문자를 섞은 요청을 보내 Kibana에서 그 Total Score를 읽은 뒤(CRS 참고에서는 CRS가 대소문자를 가리지 않는다는 설명을 뺐습니다) 두 요청에 IDS 경보가 있었는지 답합니다. 다음으로 URI의 `<script`를 잡는 룰을 작성·적용하고 `<script>alert(1)</script>`를 검색한 뒤 확인 버튼을 누르는데, 그 룰이 이 검색에 경보를 냈을 때만 통과합니다. 그다음 Kibana에서 그 경보의 `destination`을 읽고(waf 주소입니다. 웹방화벽이 요청을 막아서 들어오는 구간의 센서만 요청을 봤습니다), 대소문자를 섞은 요청이 빠져나가는 것을 확인한 뒤 `nocase`를 붙이고 `rev`를 올립니다. Suricata 참고 카드는 완성된 룰 대신 대괄호로 빈칸을 둔 룰 형태만 보여 주고, Kibana url의 `%3C`를 어떤 문자열로 찾는지는 알려 주지 않습니다. Kibana 단계에서는 학습자의 쿼리가 웹방화벽 로그와 script(또는 alert)를 지정할 때까지 쿼리 입력창만 가리키며, 그 check에도 같은 `kql`이 걸려 있습니다. 네트워크 패널은 열려 있는 동안 받은 요청만 보여 주므로 첫 카드에서 개발자 도구부터 열라고 안내합니다. `match: '<script'`가 붙은 `rules` 단계와 `nocase` 단계에는 `quiet_on`(평범한 검색 두 개)이 있어, `content:"/search/"`처럼 모든 검색에 경보를 내는 룰은 사유와 함께 실패합니다. 혼자 푸는 단계에서는 대소문자를 섞은 요청과 일반 검색을 다시 보내며, 일반 검색에 내 룰이 경보를 내면 바로 알려 줍니다(`lesson.check.replay_benign.alerted`).
- 답을 읽는 곳:
  - `char: "<"`가 붙은 `escaped`: 기록된 쿼리에 그 문자의 퍼센트 인코딩(`%3C`)이 있으면 그 값
  - `rule`: 요청의 ModSecurity 룰 id. 949110은 제외.
  - `anomaly_total`: 949110의 `Total Score: N`
  - `alerted`, `alerted_destination`(학습자가 추가한 룰이 낸 경보의 `dest_ip`), `alerted_sid_present`: 기록 시간대의 Suricata 경보 중 url이 그 기록의 url과 같은 것을 `lesson.added_rules`와 대조합니다(`views._alerts_for`). url이 없는 경보는 browse 마커가 있을 때 셉니다. 마커만으로 맞추던 시절에는 공격 몇 초 뒤 보낸 일반 검색이 공격 경보를 뒤집어써서 replay의 일반 검색이 통과하지 못했습니다(17회차).
  - `match: '<script'`가 붙은 `rules`, `needs: nocase`가 붙은 `rules`. 뒤의 것은 세션에서 마지막으로 적용한, 대소문자를 구분하던 판보다 룰의 `rev`가 커야 통과(`lesson.raised_rev`, 아니면 `lesson.xss.fail.nocase.rev`). 처음부터 `nocase`로 쓴 룰은 올릴 판이 없습니다.
  - `replay`

**f5 sort 파라미터 SQL Injection 분석**(`lesson.sqli`). defense `full`, 웹사이트 창에서 시작.

- 학습자는 sort 값을 읽고, 주소창에서 `)`를 붙여 상태 코드를 확인한 뒤 WAF 룰이 탐지했는지 답합니다. Kali 창에 sqlmap을 입력해 판정 결과, 실행이 남긴 WAF 기록 수(source_ip Top values의 "Calculated from N records"나 Documents 건수. 출발지 자체는 구성도에 있는 kali 주소), 스캐너를 식별한 룰을 읽습니다. 기록 수 단계의 `kql`은 웹방화벽 조건과 `source_ip` 조건을 함께 요구하므로, 앞 단계에서 남은 쿼리로는 안 되고 이 단계의 쿼리를 직접 작성해야 합니다. 이어서 `--random-agent`를 붙여 다시 실행합니다. 혼자 푸는 단계에서는 재실행 기록의 웹방화벽 로그에 913100이 있는지 묻습니다. 스캐너 룰의 답을 미리 보여 주지 않도록 CRS 참고에서 913 계열 줄을, 혼자 푸는 단계 제목에서 913100을 뺐습니다. Kibana에서 읽는 답에는 모두 `kql`이 있습니다.
- 답을 읽는 곳:
  - `param_value`, `status`
  - `waf_detected`: 요청의 ModSecurity 탐지 기록. 500은 룰 없이 기록되므로 탐지가 아님.
  - `sqlmap_found`: `attacker.sqlmap_found`로 박스의 `<home>/.local/share/sqlmap/output/<host>/log`를 읽어 `Parameter:` 줄이 있는지 확인.
  - `run_records`: 실행의 Kibana 조회 기간에 든 ModSecurity 기록 수, 또는 실행 마커가 붙은 기록 수(주소나 비율을 입력하면 wrong_if로 건수를 입력하라고 안내)
  - `marker: step:<id>`와 `family: "913"`(스캐너)이 붙은 `rule`. 이어서 재실행 기록에 대한 `rule: "913100"`이 붙은 `rule_matched`(새 User-Agent에 더는 매칭되지 않으면 `absent`)

**f6 넓은 예외 처리로 놓친 공격 확인하기**(`lesson.miss`). defense `overbroad`, WAF 창에서 시작.

- 학습자는 예외 파일을 grep해 빠진 파라미터를 찾고, sqlmap으로 계정을 덤프해 표를 붙여 넣습니다. 이어서 어느 엔진이 경보를 냈는지, 실행이 WAF 로그에 남긴 status 500 기록이 몇 건인지(이 기록의 rule_id는 `-`: 기록은 됐지만 매칭된 룰 없음), 관리자 목표가 탐지되었을 때 붙는 감점이 얼마인지 답합니다. 그다음 예외를 지우고 nginx를 reload합니다. 혼자 푸는 단계에서는 덤프를 다시 실행하고 정렬을 한 번 바꿉니다.
- 답을 읽는 곳:
  - `excluded_target`: 적용 중인 WAF 파일의 파라미터 이름(`sort`. `ARGS:sort`로 답하면 `lesson.miss.wrong.excluded.prefix`)
  - `loot`: 세션 스냅샷과 대조.
  - `alerted_by`: 실행의 탐지 기록으로 없음, IDS만, WAF만, 둘 다를 구분.
  - `server_errors`: Kibana가 여는 조회 기간의 WAF(ModSecurity) 로그 중 status 500 기록 수(`lesson.server_errors`). 출발지 IP는 kali의 주소라 구성도에 있고 F5에서 이미 물었으므로 다시 묻지 않습니다. sqlmap도 실행 끝에 같은 수를 출력하며, 통과 문장에서 두 값을 맞춰 보라고 합니다. rule_id 역시 앞 단계에서 `-`가 매칭된 룰 없음이라는 뜻이라고 이미 알려 줬으므로 묻지 않습니다.
  - `objective:`가 붙은 `detected_penalty`: 그 목표가 탐지되었을 때의 감점, 곧 난이도 ×1. 값은 `wargames.objectives`의 등급에서 읽고, 채점하지 않는 시나리오에서는 비어 있습니다. 통과 문장은 통과 시점의 목표 행에 따라 달라지므로(`lesson.miss.ok.cost.undetected`, `.detected`, `.kept`, `views._outcome`), 관리자 계정이 탈취되지 않았는데 8점이 감점됐다고 말하는 일은 없습니다.
  - `waf_changed`. Paranoia Level 줄도 그대로 남아 있어야 합니다(카드에서 그 줄은 두라고 안내).
  - `replay`: 실행이 차단되고 탈취 데이터가 없는지, 일반 정렬이 2xx이면서 WAF 기록이 없는지

방어 설정 `xss-gap`과 `overbroad`:

- `xss-gap`: CRS paranoia level 1 + `no-xss.rules`(`local.rules`에서 sid 9000003을 뺀 파일).
- `overbroad`: level 1 + `no-uri-sqli.rules` + 예외 `{tag: OWASP_CRS, target: "ARGS:sort"}`. WAF 파일에서는 `SecAction "id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetByTag=OWASP_CRS;ARGS:sort"`로 들어가며, 이 때문에 CRS 룰 전체가 `sort`를 검사하지 않습니다.

F6의 sqlmap 명령에는 `--skip-waf`를 붙입니다. 이 옵션이 없으면 sqlmap이 WAF 존재를 확인하려고 보내는 요청 하나가 IDS 9000003, 9000004와 CRS 룰 하나에 걸려 실행이 탐지된 것으로 집계됩니다. 기초 레슨 질문에는 `accept` 목록이 없습니다(단계형 시나리오 3.1의 선택형 단계 하나는 `accept` 목록을 씁니다).

과정마다 세션 하나. `POST /api/sessions/<id>/lesson/ {"lesson": "<id>"}`는 열려 있는 가이드 세션을 그 자리에서 다른 기초 레슨으로 전환합니다. 콘솔의 다음 레슨은 세션의 과정 안에서만 이어지고(`views._next_lesson`), 과정 요약에도 그 과정의 레슨만 나옵니다. 과정 1은 `course.logs.done`, 과정 2는 `course.attack.done`으로 끝나며 둘 다 마지막 레슨이 끝났다고 알리고, 과정 1 문구에서는 다음 과정인 과정 2도 소개합니다. 과정 2의 점수는 결과 화면에서 봅니다. 전환 시 동작:

- 그 레슨이 선언한 방어 설정이 `Session.defense`와 다르면 레슨의 CRS 설정을 씁니다(`PUT /waf/`와 같은 `crs.apply`). 센서 룰 파일은 방어 설정의 룰 파일이 바뀔 때만 다시 넣습니다.
- `Session.lesson`과 `Session.defense`를 갱신합니다.
- `Session.lessons`에 `{id, started_at}`를 추가합니다(마이그레이션 0027). 첫 항목은 기초 레슨을 열 때 씁니다.
- 스탬프 프록시의 라벨을 지웁니다.
- 레슨의 `cases`는 이 시점에 재생하지 않고, 학습자가 그 레슨에서 처음 통과하거나 건너뛰거나 힌트를 볼 때 재생합니다.
- 세션 상세를 응답합니다.

닫힌 세션, 시나리오 세션, 가이드가 없는 세션은 409, 기초 레슨이 아닌 id는 400으로 거부합니다.

상세에 포함되는 항목:

- `lessons`
- `next_lesson`(세션 과정 안에서 `order` 순으로 다음 기초 레슨의 `{id, text}`, 과정의 마지막 레슨 뒤에는 null)
- `course`(들은 레슨별 `[{id, text, steps, passed, skipped, hints, retried}]`. `retried`는 틀린 뒤 통과한 단계 수라서, 둘 중 하나를 고르는 문항에서 다른 쪽을 다시 고른 경우도 결과 화면에 남습니다)

콘솔은 다음 레슨을 제안만 합니다.

- 기초 레슨의 마지막 단계를 통과하거나 건너뛰면 카드에 "레슨이 끝났습니다."와 "다음 레슨: <제목>" 버튼이 나옵니다. 자동으로 넘어가지 않고, 학습자가 버튼을 누르면 전환을 요청하고 화면을 다시 불러와 새 레슨을 엽니다.
- 과정의 마지막 레슨 뒤에는 그 과정에서 들은 레슨을 세션의 `course` 행에서 읽어(`/api/wargames/`는 읽지 않음) "N개 단계 중 n개 통과"와 함께 카드에 나열합니다(체크 표시는 없고, 단계를 모두 건너뛴 레슨은 0으로 표시). 세션에서 그 과정의 레슨을 모두 들었으면 카드 제목은 과정 제목, 문장은 과정 마침 문장(`<course>.done`)이 되고, 아니면 "레슨이 끝났습니다."가 나옵니다. "직접 해 보기" 카드는 단계 카드 바로 아래에 있습니다. 이 버튼은 세션 화면과 같은 종료 확인(`session.close.consequence`)을 먼저 거친 뒤 수집하고 `POST /close/`로 세션을 종료한 다음 세션 화면을 엽니다. 과정이 `scored`가 아닌 레슨 세션(훈련 환경을 읽기만 하는 과정 1)은 그 화면에 점수를 표시하지 않아 목표, 탐지, 요청별 표, 탈취된 목표 수가 없고, 어떤 검색이 탐지 결과에서 빠지는지 설명하는 문장도 없습니다. 세션 화면의 레슨 카드에는 레슨별로 통과한 단계(와 다시 시도한 단계)가 나오고, Kali 실행마다 "레슨 n · m단계"가 붙습니다.
- 다시 시작하면 학습자가 손댄 첫 레슨(화면의 `begun()`: 통과, 건너뜀, 힌트가 있거나 세션을 연 레슨)을 그 레슨의 방어 설정으로 엽니다. 버튼 이름은 "다시 시작"입니다.

레슨 사이에는 아무것도 초기화하지 않습니다. board의 목표 계층은 유출만 다루기 때문에(세션을 열 때 찍은 스냅샷과 탈취 데이터를 대조) 이렇게 해도 문제가 없고, 레슨이 정답 데이터를 처음 상태 그대로 둡니다. 방어 설정은 F4와 F6이 그 자리에서 바꾸고 F5가 `full`로 되돌립니다.

레슨은 시작 이후에 일어난 일만 판정합니다(`views._lesson_started`, 항목이 둘 이상이면 `Session.lessons`의 마지막 항목).

- `sent` check: 시작 이후 웹사이트 창에서 보낸 요청만 집계.
- `rule` 답: 시작 이후 ModSecurity 기록만 집계.
- `kali` check: 단계의 `reached`와 레슨 시작 중 늦은 시각부터 센서를 읽음.
- `lost_points`: 시작 이후 탈취된 목표만 집계.
- Kibana 링크도 시작 시각부터 엶.
- 단계 기록은 레슨별로 따로 둡니다. 따라서 F2의 `search`를 통과해도 F3의 `search`가 통과되지 않습니다.

학습자 자신의 행동을 추적하는 점검은 세 가지입니다.

- `sent`: 세션의 웹사이트 창이 보관한 요청 중 디코딩한 경로와 쿼리가 단계의 `match` 정규식과 일치하는 요청이 있으면 통과.
- `kali`: 케이스 파일의 도구 케이스를 지정합니다.
  - 학습자가 단계에 진입하면 마커를 만들어 스탬프 프록시의 `/var/lib/session/active`에 씁니다(레슨 전환과 세션 종료 시 삭제). 따라서 학습자가 Kali 창에 입력한 명령은 Kali의 `http_proxy`를 거치면서 마커가 붙어 나갑니다.
  - 단계의 `command`는 입력할 문구일 뿐입니다.
  - 센서의 http 기록에 마커와 도구의 user agent가 함께 있으면 통과하며, `--random-agent`용으로 `ua: any`를 주면 user agent는 보지 않습니다.
  - 통과하면 이 실행을 일반 악성 케이스로 기록하므로(`meta.kali`와 `meta.lesson`, 재생 표시 없음) 다른 레드팀 행동과 마찬가지로 두 점수에 모두 반영되고, 이어서 세션을 수집(ingest)합니다.
  - 학습자가 `http_proxy`를 지우면 요청이 마커 없이 나가 단계를 통과하지 못합니다.
- `loot`: 붙여 넣은 테이블(`tools.dumped`, 또는 `name:hash` 줄과 `| name | hash |` 줄)을 `POST /loot/`와 같은 방식으로 인정하고 kali 케이스에 귀속합니다. 일치한 계정은 `_credit_loot`가 귀속 케이스에 남깁니다(`meta.loot`). 일치한 계정이 세션 스냅숏의 계정을 모두 덮어야 통과하고, 모자라면 일치 수와 전체 수를 담은 `<fail>.partial`로 실패하되 입력 칸은 열어 두므로 나머지를 다시 붙여 넣으면 됩니다. 일부만 붙여 넣어도 일치한 만큼은 인정합니다. 목표 판정은 대상 시스템의 데이터를 따르고, 이 단계는 표 전체를 요구할 뿐입니다.

답으로 읽을 수 있는 값은 아래와 같고, 그 밖의 값은 discovery 시점에 `wargames.read_from_record`에서 거부합니다.

- `of:`가 훈련 환경 사실인 경우: `address`, `subnet`, `path`, `logs`, `excluded_target`, `lost_points`, `detected_penalty`
- `of:`가 요청 사실이고, `about:`이 `match`가 있는 단계를 가리키거나 단계 자체에 `match`가 있는 경우(그 단계와 일치하는 가장 최근 웹사이트 창 기록을 읽음): `status`, `method`, `path`, `parameter`, `param_value`, `escaped`, `sensor_source`, `forwarded_for`, `waf_detected`, `anomaly_total`, `alerted`, `alerted_destination`, `alerted_sid_present`, `hits`
- `of:`가 Kali 사실이고 `about:`이 `kali` 단계를 가리키는 경우: `sqlmap_found`, `run_records`(실행의 WAF 기록 수), `alerted_by`, `server_errors`(실행의 500 기록에서)
- 요청의 `path`나 `step:` 마커와 함께 쓰는 `rule`(위)

## 점수 계산 방식

**목표.** board는 `loot_verified` 방식으로 채점합니다.

- 비밀은 `wargames/board/objectives.yaml`에 정의하며, `/internal/auth-users`에서 읽어 오는 `auth_user`의 사용자 이름·비밀번호 컬럼입니다.
- 등급은 공격자가 비밀을 얼마나 확보했느냐로 나눕니다: 아무 해시 1개(난이도 2), `admin` 계정의 해시(4), 전체 계정의 해시(5).
- 공격자는 빼낸 해시를 레드팀 콘솔의 '탈취한 해시 제출' 패널에서 `POST /api/sessions/<id>/loot/`로 제출합니다. 이 패널은 `loot_verified` 시나리오에만 나옵니다.
- 등급은 제출한 `(username, hash)` 쌍이 세션 시작 시점 스냅샷과 정확히 일치하고, 세션에서 악성 케이스를 한 번 이상 실행한 뒤여야 인정합니다.
- 공격이 무엇을 했는지 플랫폼이 짐작해서 목표를 인정하지는 않습니다. 정답 데이터는 대상 시스템이 직접 남긴 기록이고, 탐지 장비에서는 보이지 않습니다.

인정된 등급은 제출 시각을 기록한 Objective 행으로 남고, 행마다 시간 범위가 붙습니다.

- 제출에 악성 케이스(`case_id`)를 지정했으면 그 케이스 시작 100ms 전부터 종료 100ms 후까지
- 지정하지 않았으면 제출 2분 전부터 제출 100ms 후까지

스냅샷은 세션 시작 시 한 번만 뜹니다.

- 계정을 읽지 못해도 세션은 스냅샷 없이 생성되고, 이 세션에서 `POST /api/sessions/<id>/loot/`를 호출하면 409가 납니다.
- 이후 이 세션 때문에 board를 다시 읽지는 않습니다(슬롯 준비 점검의 `ground_truth`는 세션이 잡지 않은 슬롯에서만 board를 읽습니다). `GET /api/wargames/<id>/objectives/`는 `objectives.yaml`의 등급 목록을, `GET /api/sessions/<id>/objectives/`는 저장된 행을 돌려줍니다.
- `POST /api/sessions/<id>/objectives/`는 관찰을 수행하는데, `loot_verified` 워게임에서는 아무 동작도 하지 않습니다.

corp 워게임은 `effect_observed` 방식입니다. 공격자가 따로 제출하지 않고, 대상 시스템이 자기 DB에 커밋한 행으로 채점합니다.

- `wargames/corp/objectives.yaml`에 읽기 채널(`estate://corp-db`, scope `wp_state`)과 등급 세 개를 선언합니다.
  - 무단 관리자 계정(`rogue_admin`, 난이도 5)
  - 자가 가입이 열린 사이트(`option_flip`, 4)
  - 무단 콘텐츠 작성(`content_write`, 3)
- 세션을 시작하면 기존 관리자, 감시 대상 `wp_options`, 게시된 글을 스냅샷으로 떠 둡니다. corp-db에 읽기 전용 `mysql` SELECT를 날리는데(`platform/api/effect.py`), 네트워크를 거치지 않고 `runner("corp-db")`로 실행합니다.
- `POST /api/sessions/<id>/objectives/`를 호출하면 corp-db의 바이너리 로그를 `mysqlbinlog`로 읽고, 커밋된 변경 중 타임스탬프가 악성 케이스의 시간 범위에 드는 것마다 등급을 인정합니다. 대상 변경은 아래와 같습니다.
  - 스냅샷에 없던 사용자에게 준 `wp_usermeta` 관리자 권한
  - `users_can_register` 또는 `default_role`의 `wp_options` 변경
  - 새로 쓰거나 덮어쓴 `wp_posts` 행
- board와 마찬가지로 이 읽기는 탐지 장비에 보이지 않습니다.

탈취된 목표는 실행 구간이 목표의 시간 범위와 겹치는 악성 케이스에 귀속하고, 겹치는 케이스가 여럿이면 가장 늦게 시작한 케이스로 잡습니다.

- 목표는 그 케이스가 탐지됐을 때만 탐지된 것으로 칩니다.
- 겹치는 케이스가 없으면 미탐으로 칩니다.
- 귀속은 시간으로만 판단하며, 케이스의 `takes:` 필드는 채점에 쓰지 않습니다.

점수의 `objectives` 블록:

- `coverage`: 전체 난이도 대비 탐지된 난이도. 탈취된 것이 없으면 `null`
- `false_positives`: FP
- `damage`: 미탐 난이도 + 탐지된 난이도의 절반. 미탐 손실을 두 배로 치는 부분이 여기입니다.

**탐지.** 경보와 케이스는 케이스마다 선언한 두 전략 중 하나로 매칭합니다.

- `marker`: 경보에 케이스의 `X-Request-ID` 값이 들어 있으면 매칭
- `window`: 경보의 출발지 주소가 케이스와 같고, 경보 시각이 케이스 시작~종료 사이(앞뒤 2초 여유)이면 매칭

전략 간 fallback은 없습니다. 마커가 유실된 marker 케이스는 window로 메우지 않고 미탐으로 드러나야 합니다. 터미널 케이스에는 마커와 시간 구간이 모두 있습니다.

- 점수 엔드포인트에 `?correlation=marker`나 `?correlation=window`를 붙이면 전략을 강제하며, 그 밖의 값은 400입니다.
- 이 파라미터를 넘기는 콘솔 페이지는 없습니다(`session.html`은 `correlation` 없이 `/score/`를 요청합니다).
- 두 전략을 비교하려면 전략별로 엔드포인트를 한 번씩 호출하면 됩니다. 결과가 갈린다면 방어가 아니라 채점 방식 쪽 문제입니다.

`per_case` 항목마다 `expect`와 `corroborated`가 있습니다.

- `expect`: 케이스의 시그니처에 들어 있어야 할 부분 문자열
- `corroborated`: 매칭된 경보 중 하나의 시그니처에 `expect`가 대소문자 구분 없이 들어 있으면 true. 같은 세션에서 정상 케이스에도 매칭된 시그니처는 제외합니다.
- 케이스에 `expect`가 없으면 `null`입니다. `POST /api/sessions/<id>/cases/`로 기록한 window 케이스는 요청 본문에 `expect`를 넣지 않으면 `expect`가 없으므로 `null`이 됩니다.
- 탐지됐지만 corroborated가 아닌 케이스에는 `score.warning.wrong_reason`이 붙습니다.

`expect`는 케이스를 실행할 때 케이스와 함께 저장하므로, 케이스 파일을 고쳐도 끝난 세션이 다시 판정되지는 않습니다. 마이그레이션 0009 이전에 기록된 행은 저장된 `expect`가 없어서 현재 케이스 파일 기준으로 판정합니다. 경보 위험도와 룰 유형은 쓰지 않습니다.

**게임.** 점수의 `game` 블록은 세션이 닫히기 전까지 `{"revealed": false}`이고, 닫힌 뒤에는 구성 요소 네 개와 각 가중치, balance가 들어갑니다.

- speed (0.25): 악성 케이스별로 첫 매칭 경보가 케이스 시작 10초 이내면 1, 120초 이후면 0, 그 사이는 선형. 케이스별 값의 평균
- accuracy (0.30): 재현율 - 오탐률, 하한 0
- coverage (0.20): 공격받은 공격 단계(`platform/lifecycle.py`) 중 탐지된 악성 케이스가 있는 단계의 비율. 공격받은 단계가 없으면 0이며, `objectives` 블록의 `coverage`와는 다른 값
- response (0.25): 차단된 악성 케이스 비율 - 차단된 정상 케이스 비율
  - `meta["blocked"]`가 붙은 케이스가 하나도 없으면 `null`이고, 나머지 가중치를 재정규화합니다.
  - 이 값은 예정된 공격(403, 또는 sqlmap이 스스로 내린 주입 불가 결론)과 레슨의 시드 재실행(403)에서만 설정하고, 그 밖에 실행한 케이스에는 설정하지 않습니다.

`attacker`는 탈취된 목표의 난이도 합(탐지된 목표는 절반)으로, `damage`와 같은 값입니다. `defender`는 구성 요소의 가중 평균에 탈취된 난이도를 곱한 뒤 FP 1건당 1을 뺀 값이고, `balance`는 `defender - attacker`입니다. 탈취된 것이 없으면 balance는 -FP가 됩니다. 가중치와 체류 시간은 v1 기본값입니다(`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`).

**고객.** 점수의 `customers` 블록은 세션에 기록된 고객 요청을 집계합니다("고객 트래픽" 참고).

- `sent`
- `served`(2xx, 3xx)
- `blocked`(403. 단, Django 자체 CSRF 거부는 생성기가 `refused_by: "app"`으로 표시하므로 제외)
- `unanswered`(10초 안에 응답 없음, status 0)
- `other`(그 밖의 4xx, 5xx)
- `alerted`(마커가 경보에 찍힌 고객 요청)
- `blocked_actions`

요청은 한 번씩만 셉니다. 고객 요청은 케이스가 아니어서 `per_case` 목록과 TP/FP/FN/TN에 영향을 주지 않고, 고객 요청 때문에 발생한 경보도 `unattributed`에 넣지 않습니다. 콘솔의 두 번째 점수에는 케이스 문장 옆에 "차단된 고객 요청: M건 중 N건"이 표시됩니다.

점수 엔드포인트는 읽기 전용이고 이력을 남기지 않습니다.

## 고객 트래픽

board 세션에는 고객을 붙일 수 있습니다. 세션 내내 글을 둘러보고, 검색하고, 로그인하고, 댓글을 다는 국내 커뮤니티 사용자들입니다.

구성은 `wargames/board/traffic.yaml`에 선언합니다: 사용자 수, 출발지 가중치, 시드 계정, 글 1-3, 브라우저 User-Agent, 검색어, 댓글 내용, 행동 가중치 프로필.

`platform/traffic.py`는 이 선언을 아래 형태로 렌더링합니다.

- 선언된 가중치대로 출발지에 배분한(최대 잉여 방식) 페르소나 12명. 페르소나마다 출발지 주소, 브라우저, 언어가 따로 있음
- 박스가 돌아가며 실행하는 단계별 흐름 2,000개

로그인과 댓글은 폼 POST로 보냅니다. 흐름은 먼저 페이지를 GET하고, 박스는 그 페이지에서 `csrfmiddlewaretoken`을 꺼내 `csrftoken` 쿠키와 함께 보낸 뒤 302를 따라갑니다. 페이지에 토큰이 없으면(GET이 차단됐으면) 브라우저와 마찬가지로 흐름이 거기서 멈춥니다.

생성기는 `deploy/traffic/users.py`입니다.

- Python 표준 라이브러리만 사용
- 여러 스레드로 계획된 속도에 맞춰 요청 전송
- 요청마다 새 UUID를 `X-Request-ID`에 넣음. 케이스 마커와 형태가 같아서 학습자는 이 값으로 고객과 공격을 가려낼 수 없음
- 요청마다 JSON 한 줄을 `records.jsonl`에 기록
- 계획 파일이 바뀌면 다시 읽고, 파일이 삭제되거나 SIGTERM을 받으면 종료

생성기는 슬롯의 Kali 컨테이너에서 시스템 계정 `cr-users`로 돌립니다.

- 페르소나마다 컨테이너의 출발지 주소 하나에 바인딩하므로, 요청의 출발지 주소는 해당 출발지의 주소가 됩니다.
- 공격자와는 분리합니다. 기본 출발지도, 공격자가 쓰고 있는 출발지의 `source_ip`도, 컨테이너의 바인딩되지 않은 출발 주소(대상으로 `ip route get`)도 쓰지 않습니다. `POSTROUTING -m owner --uid-owner cr-users -j RETURN`을 `ORIGIN-SNAT` SNAT 점프 앞에 넣어 두었기 때문에 공격자의 출발지 변환은 고객에게 적용되지 않습니다.

박스에서 실행하는 명령은 모두 `platform/attacker.py`에 있습니다.

- `place_customers`: 계정, NAT 예외, 프로그램 배치. 컨테이너 안에서 `sudo`로 실행
- `run_customers`: 계획을 쓰고, 프로그램이 떠 있지 않으면 `setsid`와 `setpriv`로 시작
- `stop_customers`
- `customer_records`

프로그램은 Kali 이미지에 넣지 않고 시작할 때마다 플랫폼에서 내려보냅니다. 컨테이너는 닫힐 때마다 이미지로 다시 만들어지기 때문에, 이미지에 넣어 두면 프로그램을 고칠 때마다 새 이미지가 나올 때까지 기다려야 합니다.

API는 `platform/api/customers.py`와 `views.session_traffic`에 있습니다.

- `PUT /api/sessions/<id>/traffic/ {rate, profile}`: 고객을 시작하거나, 실행 중인 생성기의 속도와 프로필을 바꿉니다(페르소나는 유지).
  - `rate`: 초당 요청 수. 기본값 1, 최대 50
  - `profile`: 워게임이 선언한 프로필 중 하나. board에는 `community`(기본값), `plain`(특이한 검색 없음), `readers`(`plain`에서 댓글 제외), `club`(`community`에 댓글 속 코드 질문 추가)이 있음
  - `traffic.yaml`이 없는 워게임은 404, 닫힌 세션은 409, 박스나 출발지가 없으면 503
- `GET`: 새 기록부터 읽은 뒤 아래 값을 돌려줍니다.
  - `declared`, `profiles`, `running`, `rate`, `profile`, `started_at`, `stopped_at`, `error`
  - 건수 `sent`, `served`, `blocked`(앱이 아니라 방어 설정이 낸 403), `unanswered`, `other`
  - `sources`(출발지, 주소, 요청 수)
  - `by_action`(행동별 전송 수와 차단 수)
- `DELETE`: 생성기를 멈추고 마지막으로 보낸 기록까지 읽습니다. 세션을 닫을 때도 슬롯을 초기화하기 전에 같은 처리를 하며, 박스에 연결되지 않으면 닫기는 그대로 진행하고 오류를 `traffic.error`에 남깁니다.

기록은 바이트 오프셋 기준으로 가져와(`tail -c`, 호출당 최대 1 MiB, 완전한 줄만) 호출마다 `bulk_create` 한 번으로 `CustomerRequest` 행에 넣고, 오프셋은 `Session.traffic`에 둡니다.

고객 트래픽 스위치는 테스트용이라 세션 페이지 URL에 `?traffic`이 있을 때만 보입니다. 시나리오에서는 고객을 자동으로 시작합니다.

생성기는 board 자체의 CSRF 거부(`refused_by: "app"`, 차단으로 세지 않음)를 영어 문구뿐 아니라 Django 실패 페이지의 `<span>(403)</span></h1>`로도 식별합니다. board는 고객의 언어로 응답하기 때문에 한국어 고객에게는 거부 메시지도 한국어로 갑니다. 이런 거부는 같은 페르소나의 두 흐름이 로그인 시점의 토큰 교체와 경합할 때 생깁니다.

## 시나리오

시나리오는 훈련 환경에서 제한 시간을 두고 진행하는 실습입니다. 고객과 공격자가 board를 쓰는 동안 학습자가 실제 도구로 방어하고, 마지막 최종 점검 구간(final verification window)에서 결과를 판정합니다.

설계는 `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`의 P4 단계이고, 결정 사항은 `docs/DECISIONS.md`의 2026-10-13 "scenario course" 항목에 있습니다.

**기술자(descriptor).** 기술자는 워게임 `scenario.yaml`의 `scenarios:`에 두고, `wargames.checked_scenarios`로 검증합니다.

| 필드 | 의미 |
|---|---|
| `id`, `order` | `1.1`, `2.1`, ... id는 기초 레슨과 같은 네임스페이스 |
| `task_class` | `judgement`, `availability`, `detection`, `unknown` 중 하나 |
| `guidance` | `worked`(`steps` 선언 가능, 단계 엔진에서 실행), `faded`, `none` |
| `text`, `briefing` | `text`는 문자열 키 접두어. `briefing`은 `situation`, `goal`, `measured_by`를 문자열 키에 연결 |
| `minutes`, `window_minutes` | 시나리오 길이와 최종 점검 구간 길이 |
| `defense` | 워게임 `defense:` 맵의 방어 설정 중 하나(CRS 수준, 예외 규칙, 임계치, Suricata 룰셋) |
| `traffic` | 고객용 `{profile, rate}`(`traffic.yaml`) |
| `red` | `schedule`(기본값) 또는 `person`. `person`이면 사람이 레드팀 콘솔을 쓰고, 시나리오에 공격을 선언하지 않아도 됨 |
| `attacks` | `[{at, case, origin}]`: 연 뒤 몇 초(`minutes` 이내), 악성 케이스, 선택 출발지. 학습자에게는 비공개 |
| `completion` | 종류별. judgement: `{judged: all}`, 선택으로 `pattern: judged`. availability: `{served: all, held: all}`, 선택으로 `thresholds: {inbound, outbound}`. unknown: `{served: all, held: all}`. detection: `{detected_by: suricata}` |
| `cards` | `[{id, when}]`, `when`은 `start`, `alert`, `blocked`, `window` 중 하나 |
| `hints` | 하나씩 차례로 제안하는 힌트 id |

`GET /api/wargames/`는 시나리오별 카드(`wargames.scenario_card`)를 `attacks`를 뺀 채로 나열합니다. `GET /api/sessions/<id>/`는 단계형 시나리오의 `lesson`에서 `attacks`와 `completion`을 빼고 `cases`를 비워서 돌려줍니다.

**열기.** `POST /api/sessions/ {"scenario": "2.1"}`의 처리 순서입니다.

1. 시나리오 id로 워게임을 찾습니다.
2. `lesson`, `guidance`, `defense`가 오면 거부합니다.
3. 다른 세션과 같은 방식으로 선언된 방어 설정을 적용합니다.
4. `scenario_run.begin`에서 고객을 시작하고 `Session.scenario_state`(마이그레이션 0025, `Session.course_scenario` 옆)를 씁니다. 여기에는 공격별 절대 예정 시각을 붙인 일정, 점검 구간, 판정 결과, 힌트 제안, 지금까지 확인한 WAF 버전이 들어갑니다.

단계형 시나리오는 `guidance`를 true로, `lesson`을 자기 id로 설정하므로 단계가 재생 시드 없이 `/lesson/steps/`에서 돌아갑니다. 고객을 시작하지 못하면 세션을 닫고 503을 돌려줍니다.

**엔진**은 `platform/api/scenario_run.py`이고 순수 규칙은 `platform/scenarios.py`에 있습니다. 플랫폼 프로세스 안에서 스레드로 돌며, 첫 시나리오를 열 때와 부팅할 때 `cr/wsgi.py`에서 시작합니다(`resume`: 실행 도중 끊긴 공격을 예정 상태로 되돌림). 틱이나 그 뒤의 연결 정리가 실패하면 각각 로그만 남기고 스레드는 계속 돕니다.

엔진은 `CR_SCENARIO_TICK`(2초)마다 열린 시나리오 세션별로 아래 작업을 합니다.

- 시계가 시작되지 않은 세션은 건너뜁니다. `begin`은 `started: false`를 쓰고, 상황 설명 화면에서 시작을 눌러 `POST .../scenario/start/`가 오면 그 시점을 기준으로 `opened_at`, 점검 구간 시각, 종료 시각, 공격 일정을 한 번 정합니다(2026-11-14). 그 전까지 `time_left`는 `minutes` 전체입니다. `verify-window`는 시계가 멈춰 있으면 먼저 시계를 시작합니다.
- 학습자가 점검 구간을 열지 않았으면 예정 시각(시계 시작 후 `minutes - window_minutes`)에 엽니다.
- 예정 시각이 된 공격을 하나씩 가져와 워커 4개짜리 풀에서 `views._fire`로 실행하고 `meta.scheduled`를 붙입니다. 재생 표시가 아니므로 두 점수 모두에 반영됩니다.
  - sqlmap 덤프는 해당 케이스에 귀속해 `views._credit_loot`로 넘기므로, 첫 번째 점수는 board 자체의 계정과 일치할 때만 손실로 칩니다.
  - 일정 항목에는 `outcome`(held 또는 leaked)이 남습니다.
  - 케이스에는 sqlmap의 결론 줄과 403 횟수가 남습니다(`meta.conclusions`, `meta.forbidden`, 판정에는 미사용).
  - `meta.blocked`는 403이 났거나, 덤프한 행 없이 정상 종료한 sqlmap이 스스로 주입 불가로 결론 낸 경우(`tools.found_not_injectable`)에 설정합니다.
  - sqlmap 케이스는 해시를 크랙할지 묻는 sqlmap의 질문에 거절로 답합니다(`--answers=crack=N`). 그래서 덤프한 칸에는 `loot.matched`가 비교하는 원래 해시가 그대로 남습니다.
- `CR_SCENARIO_OBSERVE`(15초)마다 고객 기록을 가져오고 최근 180초를 수집(ingest)합니다.
- `CR_SCENARIO_WAF_POLL`(20초)마다 WAF 파일을 읽어 터미널에서 바꾼 내용을 잡아냅니다.
- 열린 점검 구간이 끝났고 구간 안에 예정된 공격이 모두 실행됐거나 실패했으면 그 구간을 판정합니다.

세션을 닫으면 아직 예정 상태인 공격은 취소하고, 이미 실행 중인 공격은 끝까지 돌려서 기록합니다.

**최종 점검 구간.** 구간은 `POST .../scenario/verify-window/`("최종 점검 시작")나 일정에 따라 `window_minutes` 동안 열립니다. judgement 시나리오에서 지금까지 나온 항목 중 판정하지 않은 것이 있으면 학습자의 요청에는 409와 남은 개수 `unjudged`로 응답합니다(`scenario_run.unjudged`). 이때 콘솔은 항목을 다시 불러와 남은 개수를 보여 줍니다. 일정에 따른 구간은 이와 상관없이 열립니다. 엔진은 일정에 있는 공격 케이스 중 구간 안에 예정되지 않은 케이스마다 항목을 하나씩 구간 안에 추가합니다.

구간에서는 시나리오 종류별 `completion`을 판정합니다.

- `served`: 구간 안에서 방어 설정에 차단된 고객 요청(앱이 아닌 403)이 없어야 합니다.
- `held`: 구간 안의 공격이 모두 실행됐고 모두 막혔어야 합니다(탈취 데이터 일치 없음, 영향 없음).
- `judged`: 구간이 열릴 때 목록에 있던 항목을 모두 맞게 판정해야 합니다. 목록은 구간과 함께 저장하고, 구간 중에 내린 판정도 인정합니다. 나중에 더 이른 시각으로 기록에 들어온 항목은 추가하지 않습니다.
- `detected_by`: 구간 안의 공격마다 corroborated인 Suricata 경보가 있어야 하고, 고객 요청에서는 경보가 없어야 합니다.
- `thresholds`: 구간의 WAF 스냅샷 시점에 적용 중인 CRS 이상 점수 임계치가 지정값 이하여야 합니다. 임계치를 지정하지 않은 설정은 CRS 기본값(인바운드 5, 아웃바운드 4)으로 동작합니다.

구간의 기타 규칙:

- `red: person`이면 구간 안에서 그 사람이 실행한 악성 케이스(재생 제외)도 예정된 공격과 똑같이 판정합니다.
- judgement 시나리오는 설계 문서의 종류 표대로 판정 결과만 봅니다. 구간 중에 차단된 고객은 결과 옆에 보고만 하고 실패로 치지 않습니다.
- 결과에는 조치 유형이 표시됩니다(그 시점에 찍은 WAF 스냅샷에 대한 `lesson.fix_class`: `level`, `threshold`, `rule`, `target`, `path_target`. "세션, WAF 설정 조정, 단계 엔진" 참고).
- 실패한 구간 뒤에 새 구간을 열 수 있습니다.

**경보 판단**(`GET/POST /api/sessions/<id>/triage/`). 학습자는 경보를 항목 단위로 하나씩 판정합니다.

- 항목은 경보를 일으킨 마커마다 하나입니다. 고객 요청은 요청마다 하나, 공격 케이스는 요청을 몇 개 보냈든 케이스마다 하나입니다(케이스 하나는 판정 하나).
- 항목 id는 마커를 세션의 browse 마커와 함께 해시한 값이라 `/cases/`와 대조할 수 없습니다.
- 항목에는 첫 경보·마지막 경보 시각, 경보 수, 출발지 주소, 요청 하나, WAF 판정(949/959 합계 룰이 동작했으면 `blocked`, 아니면 `logged`나 `none`), 상태 코드, 엔진·ID·메시지·건수를 붙인 룰 최대 12개가 나옵니다. 케이스 이름이나 라벨은 절대 표시하지 않습니다.
- 재생 요청과 학습자 자신의 웹사이트 창 요청은 제외합니다.
- 판정 형식은 `{item, verdict: attack|customer, succeeded}`입니다. `verdict`는 기록(케이스의 `malicious` 또는 고객 행)과, `succeeded`는 대상 시스템(케이스에 일치한 탈취 데이터, 또는 시간 범위 안의 목표)과 대조합니다. 응답에 `right_so_far`가 오고, 콘솔의 맞힌 판정 수는 이 값으로 갱신합니다.
- completion에 `pattern: judged`가 있는 시나리오는 공격의 `pattern`도 묻습니다. 케이스 파일에 있는 악성 케이스의 CAPEC id 중 하나이고, 시나리오 카드의 `patterns`에 나열합니다. 답은 케이스 자신의 `pattern`과 대조하며, 판정과 함께 저장합니다. 정답인 케이스의 `pattern`은 항목에 표시하지 않고, 항목의 `judged`에는 학습자가 고른 값만 되돌려 줍니다.
- 단계 점검 종류 `triage`(`judged: customer | attack | all`)는 학습자가 맞게 판정하면 통과합니다. `judged: verified`는 구간이 열리면 통과하므로, "최종 점검 시작" 안내 단계는 버튼 클릭이 아니라 점검이 실제로 시작돼야 통과합니다.
- 판정 창이 열려 있고 판정 중인 항목이 없으면 15초마다 항목을 다시 읽습니다. 공격으로 판정한 뒤에는 후속 질문 버튼을 닫기 때문에 다시 읽기가 멈추지 않습니다.
- 결과 보고의 판정 줄은 마지막으로 판정된 구간에 나열된 항목만 세므로 맨 위 결과와 합계가 같습니다. 판정된 구간이 없으면 전체 항목을 셉니다.

**상태, 힌트, 결과 보고(debrief).** `GET .../scenario/`의 응답 항목입니다.

- 시나리오 카드
- `phase`(running, window, passed, failed, closed)와 `time_left`
- `started`: 상황 설명 화면이 떠 있고 시계가 시작되지 않았으면 false(이때 `time_left`는 실행 시간 전체)
- 직전 1분 동안 차단된 고객과 경보가 난 요청(`alerted_per_minute`: 경보를 일으킨 서로 다른 마커 수. 고객 요청은 요청마다, 공격 케이스는 요청 수와 관계없이 한 번)
- 탈취된 목표, 점검 구간, 완료 조건
- 표시할 카드와 힌트 제안

힌트는 아래 중 하나가 일어나면 제안만 하고, `Session.hints`에는 기록하지 않습니다.

- 단계 점검이 두 번 실패
- 같은 항목을 두 번 틀리게 판정
- `PUT /waf/`로 이미 적용 중인 파일을 그대로 다시 씀
- 고객이 차단되고 있는데 5분 동안 WAF 변경이 없음

`POST .../scenario/hints/`를 호출하면 다음 힌트를 열고 `Session.hints`에 기록합니다.

`GET .../scenario/debrief/`는 일정이 드러나지 않도록 점검 구간이 판정되거나 세션이 닫히기 전까지 409를 돌려줍니다. 그 뒤에는 Igloo/ASEC 보고서 순서대로 아래 항목을 돌려줍니다.

- `overview`: 마지막 최종 점검의 판정, 조치 유형과 사유, 판정한 점검 수, 전체 단계 중 통과한 단계 수, 사용한 힌트
- `evidence`: 예정된 공격에서 나온 세션 자체의 탐지 기록 최대 20건. 완료 조건에 탐지기가 지정돼 있으면 그 탐지기의 기록이며, 룰·요청·케이스를 포함. Elasticsearch는 조회하지 않음
- `change`: 선언된 방어 설정과 마지막 WAF 스냅샷의 비교. 추가·삭제된 예외 규칙, 양쪽 수준, 그리고 해당 방어 설정으로 `crs.rendered`가 만드는 내용과 예외 파일 간의 줄 단위 diff
- `cases`: 예정된 케이스별로 판정된 구간 이전과 구간 안의 결과(held 또는 leaked)
- `risk`: 조치 유형에 따라 정해지는 문자열 키
- `customers`
- 공격 `timeline`
- `triage`
- `at`: 에이전트용. 시작 시각과 마지막 판정 시각

결과 보고는 `debrief_script.html`로 블루팀 콘솔과 닫힌 세션 페이지에 렌더링합니다.

**콘솔.** 홈 페이지에는 워게임별로 시나리오가 나열됩니다. 시작을 누르면 블루팀 콘솔이 상황 설명 화면(제목, 상황, 목표, 평가 방법, 시간)으로 열리고, 유형·안내 수준 칩은 없습니다. 시계는 이 화면에서 시작을 눌러야 돌기 시작합니다.

- 창 위쪽 띠에 남은 시간, 분당 차단된 고객과 경보가 난 요청, 탈취된 목표, 힌트 제안, 최종 점검 시작 버튼이 나옵니다.
- judgement 시나리오에는 경보 창이 추가됩니다. 이 창은 목록을 가리지 않도록, 카드와 연 힌트는 창 옆의 레슨 노트 열에 두고 강조 표시의 콜아웃은 창 안에만 띄웁니다.
- detection·unknown 시나리오에는 IDS 룰 창(`/api/rules/`를 쓰는 룰 편집기)이 추가됩니다.
- 카드는 정해진 시점에 나타나고, 구간이 판정되면 결과 보고가 열립니다.
- 단계형 시나리오의 단계는 레슨 노트에서 진행되고 힌트 목록은 비어 있습니다. 힌트는 시나리오의 힌트 제안으로만 받습니다.

**board의 시나리오.** board의 시나리오는 열한 개이고, 홈 페이지에서 기초 레슨 다음에 과제 종류 순(`order`)으로 나열됩니다. 표의 "방어 설정"은 시나리오가 시작할 때의 defense입니다.

| Id | 제목 | 종류, 안내 방식 | 방어 설정 | 고객 | 공격(비공개) |
|---|---|---|---|---|---|
| 1.1 | 고객 요청과 공격 구분하기 | judgement, worked | `level2`: PL2 | `community` 초당 2건 | 150초에 sqlmap(`ru`) |
| 1.2 | 차단되지 않은 WAF 경보 판단 | judgement, faded | `inherited`: PL2, 949110과 959100 제거 | `community` 초당 2건 | 120초에 sqlmap, 300초에 검색 인젝션(`ru`) |
| 1.3 | 공격 유형 구분하기 | judgement, none. 공격 패턴도 판정 | `inherited` | `community` 초당 4건 | 90초부터 660초까지 케이스 8개, 모두 `kr`에서: sqlmap 기본과 tamper, 검색·union·로그인 인젝션, XSS 2개, 경로 순회(path traversal) |
| 2.1 | 한글 검색 오탐 해결 | availability, faded | `level3`: PL3 | `readers` 초당 2건 | 240초에 sqlmap(`ru`) |
| 2.2 | 태그·링크 검색 오탐 해결 | availability, faded | `level2` | `community` 초당 2건 | 240초에 sqlmap(`ru`) |
| 2.3 | 이상 점수 임계치 낮추기 | availability, none. 최종 점검은 임계치 5/4 | `untuned`: PL3, 임계치 10,000/10,000 | `plain` 초당 2건 | 600초에 sqlmap(`ru`) |
| 3.1 | 탐지 룰 수정하기 | detection, worked | `broken-rule`: PL1, `broken-sort.rules`(sid 9000101이 `http.request_body`를 읽음) | `plain` 초당 2건 | 120초에 sqlmap(`ru`) |
| 3.2 | sort 공격 탐지 룰 작성하기 | detection, faded | `ids`: PL1, `no-uri-sqli.rules` | `plain` 초당 2건 | 120초에 sqlmap(`ru`) |
| 3.3 | 변형된 공격 탐지하기 | detection, faded | `spelled`: PL1, `spaced-sort.rules`(앞뒤가 공백인 SQL 단어) | `plain` 초당 2건 | 120초에 sqlmap, 300초에 tamper 변형(`ru`) |
| 3.4 | 댓글 XSS 탐지 룰 작성하기 | detection, none | `full`: PL1, `local.rules` | `plain` 초당 2건 | 120초에 댓글 XSS, 240초에 검색 XSS(`ru`) |
| 4.1 | 종합 실습 | unknown, none(카드·힌트 없음) | `full` | `club` 초당 2건(댓글에 코드 질문 추가) | 300초에 `board-sqli-orderby-sqlmap-versioned`, 600초에 sqlmap(`us`) |

고객 요청을 차단하는 CRS 룰:

- PL3에서는 한글 검색이 `ARGS:q` 대상 920272와 942460에 걸립니다(이 둘을 예외 처리하면 `REQUEST_URI_RAW` 대상 920272에 걸림). 한글 검색을 한 번 하고 나면 그 뒤 고객이 여는 모든 페이지가 `REQUEST_HEADERS:Referer` 대상 920272에 막힙니다. 한글 댓글은 `REQUEST_BODY` 대상 920272와 `ARGS:body` 대상 942460에 걸립니다.
- PL2에서는 `<b>` 검색이 941320에, 유튜브 링크가 931130에 걸리며, 둘 다 `ARGS:q` 대상입니다.
- PL1에서는 `club` 프로필 댓글의 코드 질문이 `ARGS:body` 대상 942100, 942190, 941100, 941110, 941160에 걸립니다.

시나리오 4.2(레드팀 콘솔을 쓰는 사람 대 학습자)는 두 번째 사람이 있어야 해서 선언하지 않았습니다. 엔진은 `red: person`을 지원합니다.

## 결정

- **케이스 파일은 워게임마다 하나**이고, 공격과 정상 트래픽을 같은 파일에 둡니다. board는 `redteam/cases/board.yaml`, corp는 `redteam/cases/corp.yaml`입니다. 파일을 나누면 정상 케이스를 빠뜨리기 쉽기 때문입니다. CLI는 `--cases`로 다른 파일을 지정하지 않으면 `board.yaml`을 읽고, `case_file`이 그 파일의 basename과 같은 시나리오로 세션을 엽니다(모르는 파일이면 board).
- **harness는 경로가 바뀐 요청을 보내지 않고 거부합니다.** `requests`는 `/static/../../etc/passwd`를 `/etc/passwd`로 바꾸는데, 이대로 보내면 실제로 나가지 않은 공격이 기록되고 harness의 실패가 방어의 실패로 채점됩니다. 퍼센트 인코딩 차이는 허용합니다.
- **시작조차 못 한 도구는 예외로 처리하고, 도구 케이스에서 0이 아닌 코드로 끝난 도구는 실행한 것으로 셉니다.** sqlmap은 아무것도 찾지 못하면 0이 아닌 코드로 끝나지만, 트래픽은 이미 나간 뒤입니다. HTTP 케이스의 curl이 0이 아닌 코드로 끝나면 요청이 대상에 닿지 않은 것으로 보고 예외로 처리합니다.
- **Kibana는 compose에 포함되며 전체 권한**으로 돕니다(읽기 전용 역할이 아님). 플랫폼이 수집에 쓰는 Elasticsearch를 그대로 읽습니다.
  - 접속은 플랫폼 8000번 포트의 `/kibana/`로 하고, Discover 밖의 요청은 앞단 nginx에서 거부합니다(아래). 운영자는 플랫폼 호스트의 루프백 127.0.0.1:5601에 ssh 터널로 붙습니다. 블루팀 콘솔에서는 Kibana를 프레임으로 띄웁니다.
  - **기동 시 가져오기.** `platform/kibana.py`는 기동할 때 백그라운드로 돌며, `/api/status`로 Kibana가 응답하는지 먼저 확인하고 가져오기를 합니다. Kibana에 연결되지 않거나 502/503/504가 오는 동안은 재시도하고, 그 밖의 HTTP 오류는 상태와 본문을 한 번만 보고합니다. 기동 중인 Kibana는 multipart 가져오기에 415를 돌려줍니다.
  - 가져오는 파일은 `deploy/kibana/objects.ndjson`이고 overwrite로 가져옵니다. 들어 있는 객체:
    - `@timestamp` 기준 data view `logs-*`. runtime field로 Suricata/ModSecurity 필드 쌍을 한 열씩으로 합침(`rule`, `rule_id`, `source_ip`, `destination`, `url`, `status`)
    - "Alerts" 검색과 "Overview" 대시보드. 제목에도, data view의 `sourceFilters`에도 플랫폼 이름이 드러나지 않음
  - `defaultRoute`는 `kibana.py`에서 이 검색으로 지정합니다. data view가 있어야 Kibana의 Welcome 화면이 뜨지 않습니다. Kibana `metaFields`에서 `_index`도 뺍니다.
  - **세션별 space.** 세션을 열면 `kibana.py`에서 그 세션 전용 Kibana space를 만들고 그 안에 data view를 가져옵니다(`ensure_session_view`. `compose.yaml`에서 설정하는 `KIBANA_URL` 필요).
    - space와 data view의 id는 둘 다 `soc-<pattern>`
    - space에서는 Discover를 뺀 모든 기능(대시보드, visualize, dev tools 등)을 끔
    - space 설정에서 ES|QL을 끄고(`enableESQL`. ES|QL은 data view의 패턴과 숨긴 필드를 무시하고 모든 인덱스를 읽음), `defaultColumns`는 세션 열로 둠
    - `defaultRoute`는 그 space의 저장된 검색 "Events"(세션 열, 최신순)로 지정. 그래야 학습자가 default space에 남아 있는 운영자 객체에 닿지 못함
  - **nginx에서 막는 것.** Kibana를 보안 기능 없이 돌리기 때문에, 기능 설정으로 끌 수 없는 것은 nginx에서 막습니다. `platform/nginx.conf`의 처리:
    - Elasticsearch·Kibana 관리 API는 403: console 프록시, ingest pipelines, index management, snapshot and restore, transforms, rollups, remote clusters, license, upgrade assistant, index lifecycle, watcher, data views API, security API, settings API, saved objects import·export, spaces API. 단, spaces API 중 `_active_space`와, nginx가 space 하나로 직접 응답하는 `api/spaces/space` GET은 예외
    - Default space(`s/default/...`)와, space 접두어가 없는 `app`, `spaces`, `api`, `internal` 경로는 403
    - `app/management`, `app/dev_tools`, `app/home`, `app/observability`, `app/security`, `app/kibana_overview` 페이지는 같은 space의 Discover로 리다이렉트
    Discover에서 부르는 호출은 모두 통과시킵니다. 플랫폼 자체 설정(`KIBANA_URL`)은 Kibana에 직접 붙습니다.
  - **학습자에게 보이는 것.**
    - space 이름은 "SOC"
    - data view는 세션의 인덱스 패턴에 걸려 있지만, 이름은 패턴이 아니라 `logs-*`로 보임
    - 공유 runtime field에 추가하는 필드:
      - `log_source`(`suricata` 또는 `modsecurity`)
      - `sensor`: 센서의 구성도 이름. 송신 호스트 이름에서 도메인과 슬롯 번호를 떼고, 첫 `-` 앞부분은 있든 없든 매칭합니다. 그래서 스크립트에 `cr` 호스트 이름이 드러나지 않고, 에지의 `edge`도 구성도 이름으로 읽힙니다. 값은 Suricata 기록이면 `router`와 `board.com`, ModSecurity 기록이면 모두 `waf`이고, 슬롯 접미사는 뗍니다.
      - `request_headers`: 요청 헤더별 `Name: value`. `X-Request-ID`는 제외
      - `request_header`: 자주 쓰는 헤더별로 keyword를 하나씩 둔 composite field(`request_header.host`, `.user_agent`, `.referer`, `.cookie`, `.x_forwarded_for` 등 `kibana.REQUEST_HEADERS_SHOWN`). Suricata의 `http.request_headers`나 ModSecurity의 `transaction.request.headers`에서 읽음
    - `sourceFilters`로 `_index`, `event.*`, `log.*`, `message`, `agent.*`, `ecs.*`, `host`, `host.*`, `input.*`, `error.*`, `http.*`, `transaction.*`, `metadata.*`, `data_stream.*`, `flow_id`, `tx_id`, `pcap_cnt`, `in_iface`, `pkt_src`, `community_id`, `src_ip`, `dest_ip`, `alert.signature`, `alert.signature_id`를 숨김(`kibana.HIDDEN_FIELDS`). KQL 검색은 그대로 됨
  - 가져오기가 거부되면 로그만 남기고 세션은 계속 진행합니다.
  - **Discover 링크.** `GET /api/sessions/<id>/` 응답의 `discover`는 `/kibana/s/<space>/app/discover`에서 그 data view를 쓰는, 저장하지 않은 Discover 상태입니다.
    - 범위는 현재 레슨 시작 시점부터이고, 열은 `event_type, source_ip, destination, url, status, rule_id, rule`입니다(`kibana.SESSION_COLUMNS`, 열 너비 고정). 필터는 걸지 않는데, 훈련 환경 호스트 자체의 syslog 줄은 Filebeat 단계에서 인덱스에 들어가지 않기 때문입니다.
    - 레슨은 빈 쿼리로, 시나리오와 워게임은 경보 쿼리로 엽니다.
    - space나 data view가 아직 준비되지 않았거나 `KIBANA_URL`이 없으면 `discover`는 null이고, 공유 운영자 data view로 대신하지 않습니다. 이때 ELK 창에는 준비 중 문구가 뜨고, 링크가 생길 때까지 세션을 다시 읽습니다. 가져오기는 10초마다 재시도합니다.
    - ELK 창은 이 링크로 엽니다. 저장된 검색에 쿼리를 덮어쓰는 방식은 쓰지 않는데, 그렇게 하면 Kibana가 "Unsaved changes" 배지를 붙이기 때문입니다.
  - 블루팀 콘솔에서는 창을 로드하기 전에, same-origin으로 공유하는 localStorage에 Kibana 첫 방문 안내를 이미 본 것으로 표시해 둡니다(`discover:docExplorerUpdateCalloutClosed`, `discover:docExplorerCalloutClosed`, `data.noDataPopover`). 콘솔을 불러올 때마다(세션을 열거나 레슨을 바꿀 때) `discover:searchText`도 지웁니다. Document 창의 필드 검색어인데, Kibana가 세션이 바뀌어도 이 값을 남겨 두어 앞 레슨에서 입력한 단어가 그대로 채워지기 때문입니다.
- **Elasticsearch는 단일 노드, 힙 512 MB**입니다.
- **누락된 데이터는 0으로 두지 않고 오류로 처리하며, 예외는 명시해 둡니다.**
  - Elasticsearch나 substrate에 연결되지 않거나 룰 파일을 읽지 못하면 503을 돌려줍니다.
  - 대상 시스템에 연결되지 않아도 세션은 만듭니다. 이때 세션은 스냅샷 없이 시작하고, board의 `loot/`는 409를 돌려줍니다.
  - 케이스 실행·기록과 세션 닫기에서는 대상 시스템을 읽지 않습니다. 다만 출발지나 도구 때문에 실행에 substrate가 필요하면 503을 돌려줍니다.
  - ingest 중에 시간이 지난 룰을 다시 활성화하는 작업과 경보를 구간·호스트에 배치하는 작업은 substrate에 연결되지 않아도 진행하고, 이때 배치 결과는 비어 있습니다. 그래서 세션은 그대로 시작하고 멈출 수 있습니다.
  - 분모가 0인 비율은 null이 아니라 0.0입니다. 정밀도, 재현율, F1, FPR와 게임의 speed, coverage, accuracy가 여기에 해당하고, null이 되는 것은 `objectives` 블록의 `coverage`뿐입니다.
- **점수에는 보증하지 못하는 부분을 밝혀 둡니다.** 경고를 붙이는 경우:
  - 정상 케이스 없음(`no_benign`). 세션의 고객이 요청을 보냈으면 점수 API에서 이 경고를 뺍니다. 고객 요청은 케이스로 기록되지 않는 정상 트래픽입니다.
  - marker 케이스는 있는데 마커가 붙은 경보가 하나도 없음(`no_marker`)
  - 출발지 주소가 없는 window 케이스가 있음(`no_source_ip`)
  - 탐지됐지만 corroborated가 아닌 케이스가 있음(`wrong_reason`)
  - Elasticsearch hit가 ingest에서 읽은 것보다 많음(`truncated`)
- **API로 실행하는 케이스**(`views._fire`)는 HTTP 연결 하나에 케이스 하나씩 보내고, CLI는 한 번 실행하는 동안 연결 하나를 계속 씁니다. 당시 케이스 세트(12개)로 측정했을 때 두 방식의 점수와 케이스별 경보 수는 같았습니다. acceptance 테스트에서 CLI를 돌리므로 연결을 공유하는 경로도 계속 테스트됩니다.

## OpenStack

OpenStack 구축은 `docs/STATE.md` 백로그의 OpenStack 항목 순서를 따릅니다. 이 절에는 구축을 마친 것만 적었고, 항목마다 클라우드나 fake 환경에서 돌려 확인했습니다. 남은 작업은 절 끝에 있습니다. 근거는 `docs/STATE.md`("Decided on 2026-09-30"), `docs/superpowers/specs/2026-09-30-openstack-range-placement.md`, `docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`에 있고, 여기에는 구조만 기록합니다.

처음 쓴 클라우드는 KVM 컴퓨트 노드 한 대(8 vCPU, 64 GB)에 ML2/Open vSwitch 기반 kolla-ansible 2026.1을 올린 구성이었습니다. 지금 클라우드는 노드 세 대에 Kolla 2025.2, ML2/OVN이고, 제품이 지원하는 버전은 Kolla-Ansible 2025.1 이상입니다(`docs/OPENSTACK.md` §2). 훈련 환경은 프로젝트 `fsl-range`에 두고 member 역할 사용자 `fsl-range`로 조작합니다. 사용자에게 Horizon은 노출하지 않습니다.

클라우드별 값은 모두 `deploy/openstack/cloud.yaml`에 둡니다. 커밋된 `cloud.example.yaml`을 복사해 만드는 파일로, git에서 무시되고 비밀 값은 들어가지 않습니다. identity, 네트워크와 MTU, 베이스 이미지, zone, 슬롯 수, flavor 두 개(`platform`, `range`), 키, 플랫폼의 스택과 ref, 백업 설정이 이 파일에 들어갑니다.

- 파일 검사는 `platform/range/cloud.py`에서 하고, 문제는 키별로 빠짐없이 보고합니다.
- `bin/platform-rebuild`와 `bin/cloud`는 이 파일 값으로 openstack CLI와 Heat 파라미터를 채워 실행합니다. 스택을 배포하면 이 값이 플랫폼의 `openstack.env`에 기록됩니다.
- `bin/cloud up`은 스택을 만든 뒤 `/api/range/fabric/`을 POST하고, 이어서 `/api/range/slot/`을 POST해 훈련 환경 호스트를 부팅하거나 교체합니다. 호스트가 뜨고 설치가 끝나면 `/api/range/configure/`를 POST하고, `/api/range/ready/`에서 모든 슬롯이 READY가 될 때까지 기다린 다음 마지막으로 `DELETE /api/range/leftovers/`를 보냅니다.
- `bin/cloud down`은 키를 남겨 두고, 플랫폼 DB를 백업한 다음(`bin/backup`, 사본은 `backups.keep`개까지 보관) 슬롯, 훈련 환경 호스트, fabric, 스택을 지웁니다.
- 스택이 `*_FAILED` 상태면 `up`에서는 (남은 빌더 서버부터) 지우고 다시 만들고, `down`에서는 지웁니다.
- VM에 실행 중인 `cr-platform` 컨테이너도 플랫폼 DB 파일도 없으면 백업할 것이 없으므로, `down`과 `up --replace`에서 백업을 건너뜁니다. VM에 ssh가 닿지 않으면 여전히 거부합니다. 플랫폼 DB는 있고 `cr-platform` 컨테이너만 멈춰 있으면 거부하지 않고, `down`에서 컨테이너를 시작해(백업은 `docker exec`로 실행) 백업한 뒤 API가 응답하기를 기다렸다가 훈련 환경을 지웁니다. `up`은 API 응답 여부와 관계없이 매번 VM의 인계(hand-over) 여부를 확인하고, 아직 인계받지 않은 VM(`openstack.env`에 `CR_OPENSTACK_PASSWORD`가 없음)이면 그 자리에서 인계합니다. 인계할 때는 비밀번호와 훈련 환경 키를 넣고(키가 없고 VM에 플랫폼 DB도 없으면 새로 생성), VM에 플랫폼 DB가 없으면 행이 들어 있는 가장 최근 백업을 복원합니다.

### 구축됨: 플랫폼 VM

Heat 템플릿 `deploy/openstack/platform.yaml`로 만드는 리소스:

- 네트워크와 서브넷 `cr-platform`
- 외부 네트워크로 나가는 라우터와 floating IP. `network.address`를 지정하면 프로젝트에 이미 있는 floating IP를 연결만 하고, 스택을 지워도 이 floating IP는 남음
- tcp/22, tcp/8000, tcp/8002, tcp/3080, ICMP를 모든 주소에 여는 보안 그룹
- config drive를 붙인 Nova 서버 `cr-platform`

템플릿에는 기본값이 없고, 파라미터는 모두 `deploy/openstack/cloud.yaml`에서 받습니다(`docs/OPENSTACK.md` §4 참고).

플랫폼 VM에서 cloud-init으로 하는 작업:

- `docker.io`, `docker-compose-v2`, `git` 설치
- 스왑 4 GB 추가
- Docker MTU를 Neutron 네트워크 MTU에 맞춤. 기본 브리지는 `mtu`로, compose가 만드는 것을 포함한 새 브리지 네트워크는 모두 `default-network-opts`로 설정
- `repository`의 `ref`를 `/opt/cr`에 클론
- `/opt/cr/.env`에 `CR_IMAGE_TAG=<체크아웃의 커밋>` 기록
- GeoIP 데이터베이스 다운로드(`bin/fetch-geoip`). 자격 증명은 필요 없음. Elastic GeoIP 엔드포인트는 URL에 약관 동의를 담으면 누구에게나 GeoLite2를 내려 줌
- `ubuntu`를 `docker` 그룹에 추가

systemd 유닛 `cr-platform.service`는 부팅할 때마다 `compose.yaml`의 이미지를 pull하고 `docker compose -f /opt/cr/compose.yaml up -d`를 실행합니다. 유닛에 따로 빌드 단계는 없습니다. pull이 실패해도 유닛은 멈추지 않고(`ExecStartPre=-`), 이 경우 `up`에서 없는 이미지를 체크아웃으로 빌드합니다. `bin/platform-rebuild`는 이런 빌드를 피하려고 ghcr.io를 먼저 확인합니다.

플랫폼 VM에서는 플랫폼 컨테이너(`compose.yaml`)만 돌립니다. board의 정답 데이터는 훈련 환경 호스트에 있는 board 컨테이너 안에서 읽습니다.

cloud-init에서 `CR_PUBLISH`를 VM 고정 주소로 설정하므로 8000, 8002, 3080이 그 주소에 publish되고, 보안 그룹에서도 열려 있어 브라우저에서는 floating IP로 콘솔에 접속합니다. `CR_SYSLOG_PUBLISH=0.0.0.0`은 훈련 환경 호스트의 syslog를 받으려고 5140/udp를 모든 주소에 publish하는 설정입니다. 9200은 loopback에만 엽니다.

템플릿 파라미터는 모두 `deploy/openstack/cloud.yaml`에서 받습니다(`bin/platform-rebuild`, `bin/cloud`).

- cloud-init에서 그 값을 `CR_OPENSTACK_*`로 쓰고 `_PROJECT`(스택이 속한 프로젝트), `_SSH_USER=ubuntu`, `_SSH_KEY=/data/ssh/id_ed25519`를 더해 모드 0600의 `/root/openstack.env`로 저장한 뒤, git이 무시하는 `/opt/cr/openstack.env`로 옮깁니다.
- 비밀번호는 템플릿에 넣지 않습니다. Nova가 user data를 보관하고, 메타데이터 서비스가 플랫폼 컨테이너를 포함해 VM에서 도는 모든 것에 이를 내주기 때문입니다.
- `CR_OPENSTACK_PASSWORD`는 VM이 뜬 뒤 `bin/platform-rebuild`에서 ssh로 덧붙입니다. 훈련 환경용 ssh 키도 같은 방식으로 플랫폼 데이터 볼륨에 씁니다(`README.md`).
- 플랫폼 서비스는 이 파일을 `env_file`(`required: false`, `format: raw`)로 읽고, compose는 변수 치환이나 따옴표 제거 없이 값을 그대로 넘깁니다.

VM 위의 플랫폼은 OpenStack 어댑터를 씁니다(cloud-init에서 설정한 `CR_SUBSTRATE=range.openstack.connect`). 훈련 환경 네트워크는 `/api/range/fabric/`으로 직접 만들고, 계획은 `range/fabric.py`에서 세웁니다.

- `mgmt`(DHCP 켬, 게이트웨이 없음). CIDR은 `cloud.yaml`에서 정합니다. 서로 겹치거나 플랫폼 네트워크, Docker 기본 로컬 주소 풀(172.17.0.0/16~172.31.0.0/16, 192.168.0.0/16, moby `daemon/libnetwork/ipamutils/utils.go`), `compose.yaml`에 선언된 네트워크, 선언된 출발지, 훈련 환경 호스트의 Docker 주소 풀 10.40.0.0/16(`cloud.RANGE_HOST_POOL`)과 겹치는 CIDR은 로더에서 거부하고, /16보다 좁은 `estate`도 거부합니다.
- `/data/ssh/id_ed25519` 키로 만드는 키페어 `cr-platform`
- 아래 보안 그룹 세 개

fabric으로 만드는 네트워크는 `mgmt`뿐입니다. 슬롯의 `internet`과 `estate`는 Neutron 네트워크가 아니라 훈련 환경 호스트 위의 docker 네트워크입니다.

키는 첫 fabric POST 때 없을 경우에만 플랫폼에서 만듭니다. `bin/platform-rebuild`는 운영자 PC에 사본을 두고 새 플랫폼 VM마다 넣어 주므로, VM을 교체해도 키페어와 훈련 환경 호스트가 신뢰하는 키가 그대로 유지됩니다.

보안 그룹 세 개:

- `cr-reach`: 플랫폼 자신의 `mgmt` 포트. `cr-mgmt` 멤버의 NTP(udp 123)와 훈련 환경 호스트 `mgmt` 주소의 syslog(udp 5140)만 허용
- `cr-mgmt`: 훈련 환경 호스트의 `mgmt` 포트. `cr-reach` 멤버만 허용
- `cr-egress`: 훈련 환경 호스트가 이미지를 받을 때 쓰는 플랫폼 네트워크 쪽 포트. 인바운드 룰 없음. 훈련 환경 호스트를 설치하는 동안에만 있고, 설치가 ready를 알리면 플랫폼에서 떼어 냄(`_close_egress`)

플랫폼은 자기 서버 id(부팅 때 기록하는 `CR_OPENSTACK_PLATFORM`)로 찾은 `cr-reach` 포트로 `mgmt`에 붙습니다. 그래서 플랫폼에서 훈련 환경 호스트로 ssh할 수 있고, 반대로 훈련 환경 호스트에서 플랫폼으로 여는 연결은 NTP와 syslog뿐입니다.

훈련 환경에는 인터넷이 없어 자체 시간 소스도 없는데, 채점기(플랫폼)는 대상 시스템과 센서의 시각을 자기 시계 기준의 케이스 시간 구간과 비교합니다. 그래서 훈련 환경의 시간은 플랫폼에서 제공합니다.

- 플랫폼 VM에서 chrony 실행(cloud-init: `allow <network.mgmt>`, `local stratum 10`)
- 훈련 환경 호스트는 플랫폼의 `mgmt` 주소로 시간을 맞춥니다. `range/clock.py`에서 `systemd-timesyncd` drop-in을 쓰고 첫 응답을 기다립니다(`keep_time()`). 이 설정과 수집기 룰 열기는 훈련 환경 호스트 세대와 수집기 주소 조합마다 한 번만 하므로(`_heard_and_timed`), 재구축으로 수집기 주소가 바뀐 플랫폼은 다음 configure에서 둘 다 다시 적용합니다. 컨테이너는 호스트 시계를 그대로 씁니다.

**훈련 환경 호스트.** VM `cr-range` 한 대에서 모든 슬롯을 돌립니다. 관리는 `/api/range/slot/`으로 하고, 계획은 `range/slot.py`에서 세웁니다.

- `POST /api/range/slot/`은 이 VM이 없으면 부팅합니다. 손대지 않은 Ubuntu 이미지(`compute.base_image`), flavor `compute.flavors.range`(`CR_OPENSTACK_FLAVOR`), config drive, 키페어 `cr-platform`을 쓰고, 포트는 `mgmt` 위 `cr-mgmt` 소속의 `cr-range.mgmt`와 플랫폼 네트워크(`CR_OPENSTACK_BUILD_NETWORK`) 위 `cr-egress` 소속 포트, 두 개입니다. 두 번째 포트는 설치가 ready를 알리면 플랫폼에서 떼어 냅니다. 그래서 설치가 끝난 훈련 환경 호스트에는 `cr-range.mgmt`만 남고, 인터넷으로 나가는 경로도 DNS 리졸버도 없습니다.
- 설치 번들은 Nova user data에 담습니다(`rangehost.bundle()`, `rangehost.user_data()`). `deploy/range-host/setup.sh`, 이미지 목록, Docker `daemon.json`, pristine 워게임의 compose 파일과 목록이 들어가며, 인코딩한 user data는 Nova 한도인 65,535바이트를 넘으면 안 됩니다.
- `setup.sh`에서는 `docker.io`, `docker-compose-v2`, `ethtool`, `rsyslog`를 설치하고 sshd의 `MaxSessions`, `MaxStartups`와 inotify 한도를 올립니다. 이어서 플랫폼의 `CR_IMAGE_TAG`로 GHCR에서 이미지를 모두 pull하고, 대상 시스템의 pristine 볼륨을 `/opt/cr/pristine`에 떠 둡니다. 그다음 `setup.sh`를 호출한 user-data 스크립트에서 `/var/lib/cr/ready`를 남기고, 실패하면 `/var/lib/cr/failed`를 남기고 로그 끝부분을 콘솔에 찍습니다(`rangehost.user_data`).
- 그전까지 플랫폼은 훈련 환경 호스트 상태를 Nova의 `ACTIVE`가 아니라 `SETTING_UP`이나 `SETUP_FAILED`로 보고합니다. 설치가 실패하면 `/api/range/ready/`의 슬롯 단계가 `SETUP_FAILED`가 되어 훈련 환경 호스트의 `/var/log/cr-setup.log`를 가리키고, `bin/cloud up`은 그 이유를 출력하고 멈춥니다. 다음 `POST /api/range/slot/`에서는 열린 세션이 없으면 설치에 실패한 훈련 환경 호스트를 지우고 다시 부팅합니다(`ensure_slot`).
- `daemon.json`으로 Docker에 테넌트 MTU(`mtu`, `default-network-opts`), /28 단위 주소 풀 10.40.0.0/16, `local` 로그 드라이버, `userns-remap: default`를 설정합니다.
- 서버 메타데이터에는 `cr_host`, `cr_tag`(이미지 태그), `cr_bundle`(번들 digest)을 둡니다. digest는 파일별 이름과 내용을 해시한 값입니다. 태그나 digest가 플랫폼과 다르면 그 훈련 환경 호스트는 `stale`이고, `POST /api/range/slot/`에서 열린 세션이 없으면 VM을 지우고 다시 부팅하며, 세션이 열려 있으면 슬롯을 blocked로 보고합니다.
- Glance 이미지는 만들지 않습니다. 훈련 환경 호스트의 이미지는 GHCR에서만 pull합니다.

초기 데이터 사본은 `setup.sh`에서 한 번 만듭니다. 모든 워게임을 compose 프로젝트 `pristine`으로 띄워 healthy가 되면 멈추고, 컨테이너별 볼륨을 `/opt/cr/pristine/<service><path>`로 복사한 다음 `down -v`로 지웁니다.

**훈련 환경 슬롯.** 동시에 띄울 훈련 환경 사본 수는 `cloud.yaml`의 `compute.slots`(기본 1, 플랫폼에서는 `CR_OPENSTACK_SLOTS`)로 정하며, `max_sessions`도 이 값입니다.

- 슬롯 N은 훈련 환경 호스트의 docker compose 프로젝트 `sN`입니다. `platform/range/rangehost.py`에서 `deploy/range-host/slot.yaml`과 워게임별 `wargames/<w>/compose.yaml`로 렌더링하며, 컨테이너는 `sN-kali`, `sN-edge`, `sN-waf`, `sN-edge-sensor`, `sN-estate-sensor`, `sN-board`, `sN-board-db`, `sN-corp-wp`, `sN-corp-db`입니다.
- 네트워크는 `sN_internet`(브리지 `sN-inet`, 172.30.N.0/24), `sN_estate`(브리지 `sN-estate`, 10.30.N.0/24: 에지 .1, WAF .247, board .59, corp-wp .60), 워게임별 DB용 `<wargame>-default`입니다. 모두 `internal`, `gateway_mode_ipv4: isolated`, 테넌트 MTU이고, publish한 포트도 NAT도 없습니다.
- 표적과 센서의 healthcheck는 평소 60초, 시작 구간에는 1초 간격입니다(`slot.yaml`의 `x-wargames.healthcheck`로 워게임 자체 주기를 덮어씀). 쉬는 슬롯이 바쁜 슬롯에 CPU를 양보하도록 맞춘 값입니다.
- 슬롯마다 `internet` 브리지에 같은 출발지 서브넷 30개가 올라가므로, 어느 슬롯에서든 경보 출발지가 같은 국가로 분류됩니다.
- 슬롯 어댑터(`OpenStack.in_slot(n)`)는 자기 compose 프로젝트만 다룹니다. 역할, runner, 구성도는 모든 슬롯이 같습니다.
- 세션을 열 때 플랫폼에서 세션을 슬롯 하나에 묶습니다(`Session.slot`, unique 제약으로 슬롯당 열린 세션 하나). 잠금을 잡은 상태에서 비어 있고 READY인 첫 슬롯을 고릅니다.
- 세션별 훈련 환경 호출은 모두 해당 슬롯으로 갑니다. close 때는 그 슬롯만 초기화하고, 그 슬롯에서 비활성화한 룰만 다시 활성화합니다. 초기화 상태도 슬롯별로 따로 둡니다(`api/reset.py`). 룰 변경은 슬롯별 차례로 처리하므로 한 슬롯의 초기화가 다른 슬롯의 세션을 붙잡지 않습니다.
- `run_on_role`은 `--session`이나 `--slot`을 받고, 슬롯이 둘 이상인데 둘 다 없으면 실행하지 않습니다.
- 콘솔의 VM 터미널은 `?arg=<id>`(ttyd `-a`)로 세션을 받아 그 슬롯의 컨테이너를 엽니다.

**configure.** `POST /api/range/configure/`(`configure_slot()`)에서는 수집기 룰 열기와 훈련 환경 호스트의 시간 소스 설정을 병렬로 처리하고, 둘 다 훈련 환경 호스트 세대와 수집기 주소 조합마다 한 번만 합니다. 그다음 compose 파일, 두 센서 설정, Kali와 에지의 주소, rsyslog 설정, 기본 룰, 스크립트 자체 등 슬롯 파일을 훈련 환경 호스트의 `slot.sh up N`에 넘깁니다. `slot.sh up`의 처리 순서:

1. 슬롯 디렉터리를 모두 root 소유로 바꿉니다. WAF 로그 디렉터리 `/var/log/cr/sN/waf`에서는 일반 파일 `audit.log`만 남기고 모두 지우며, 이 파일이 없으면 remap된 범위의 `www-data`·`adm` 소유(`0644`)로 만듭니다. 그래야 컨테이너 안에서 root로 도는 nginx 마스터가 파일을 열 수 있고 `syslog`도 읽을 수 있습니다.
2. 컨테이너를 만들고(`up --no-start --pull never`), 한 번도 실행하지 않은 대상 시스템의 빈 볼륨마다 초기 데이터를 복사합니다.
3. 컨테이너를 띄웁니다(`up -d --wait`).
4. Kali에는 출발지 주소들과 기본 출발지 게이트웨이로 가는 default route를, 에지의 `wan`에는 출발지별 게이트웨이 주소를 붙입니다(`nsenter`로 `ip -batch` 실행).
5. WAF와 `estate`의 대상 시스템이 에지의 estate 주소로 라우팅하도록 설정합니다.
6. 모든 브리지와 그 포트, 컨테이너 인터페이스에서 TSO, GSO, GRO를 끕니다. 센서가 실제로 오간 그대로의 패킷을 보게 하기 위해서입니다.
7. `DOCKER-USER`에 브리지별로 같은 브리지로의 forward 허용 룰을 넣습니다.
8. `/etc/rsyslog.d/60-cr-sN.conf`를 설치하고 rsyslog를 재시작합니다. 파일이 바뀌었거나 rsyslog가 돌고 있지 않을 때만 하며, 슬롯 하나씩 차례로 처리합니다(`flock /run/cr-rsyslog.lock`, 먼저 `systemctl reset-failed`).

그 뒤 플랫폼에서 `rules/suricata.py`로 두 센서에 기본 룰을 넣습니다.

**에지.** `sN-edge`(`deploy/edge/`)는 nftables를 넣은 Alpine 컨테이너로, capability는 `NET_ADMIN`뿐입니다. `wan`은 `sN-inet`에, `lan`은 `sN-estate`에 붙습니다. `rp_filter`를 끄고 NAT 없이 forward하므로 출발 국가 주소가 그대로 WAF까지 갑니다. `deploy/edge/edge.nft`에서 input은 loopback 외에는 drop, forward는 accept입니다.

**Kali.** 모든 출발지를 Kali 이미지 하나로 처리합니다. `slot.sh`에서 국가별 주소 약 100개를 `eth0`에 붙이고, `/usr/local/sbin/set-origin`에서 컨테이너의 출발 주소를 국가별로 SNAT하므로 어떤 도구든 고른 국가에서 나갑니다. 마커를 붙이는 프록시가 컨테이너의 메인 프로세스입니다. Kali에 등록된 이름은 `board.com`과 `corp.com` 두 개이고, 둘 다 WAF의 estate 주소를 가리킵니다.

**센서.** `sN-edge-sensor`와 `sN-estate-sensor`는 digest로 고정한 `jasonish/suricata`이며, 호스트 네트워크와 호스트 user namespace(`userns_mode: host`)에서 `NET_ADMIN`, `NET_RAW`, `SYS_NICE`로 돕니다. 각 센서는 브리지 하나를 af-packet 스레드 하나로 봅니다.

- 에지 센서는 인터넷 구간인 `sN-inet`을 봅니다. 설정은 `deploy/range-host/edge-sensor.yaml`이고, `HOME_NET`은 슬롯의 estate /24입니다.
- estate 센서는 `sN-estate`에서 board와 corp-wp 주소로 BPF 필터를 걸어 WAF→대상 시스템 구간을 봅니다. 설정은 `deploy/suricata/suricata.yaml`로 렌더링합니다.
- 둘 다 `/var/lib/suricata/rules/local.rules`에서 룰을 읽고 `suricatasc -c reload-rules`로 reload합니다. 이 경로와 명령은 호스트 항목 `cr-edge`와 `cr-range`에 지정되어 있습니다(estate 센서는 `settings.CR_EXTRA_SENSORS`). 룰 넣기, 검증, 변경, 기준선 검사는 모두 두 센서에 적용합니다.
- EVE 경보와 HTTP 기록은 `/var/log/cr/sN/edge/eve.json`이나 `/var/log/cr/sN/estate/eve.json`에 남습니다.

**로그.** WAF audit 로그는 훈련 환경 호스트의 `/var/log/cr/sN/waf/audit.log`에 씁니다. WAF의 호스트 경로 마운트는 이것 하나이고, 마운트 대상도 이 파일뿐입니다. 디렉터리가 root 소유라서, WAF 안의 root가 호스트의 root 프로세스가 따라갈 링크를 그 안에 만들 수 없습니다(`docs/THREAT-MODEL.md`). `/etc/rsyslog.d/60-cr-sN.conf`(`rangehost.forwarding`)에서 세 파일을 `imfile`로 읽어 플랫폼 `mgmt` 주소의 5140으로 UDP 전달하며, 송신자 이름은 파일별로 고정입니다. 슬롯 1은 `cr-edge`, `cr-range`, `cr-waf`, 슬롯 N은 `cr-edge-N`, `cr-range-N`, `cr-waf-N`이라서 Filebeat의 슬롯 정규식으로 예전처럼 슬롯을 읽을 수 있습니다. 파일을 `/var/log` 아래에 두는 것은 Ubuntu의 rsyslog가 `syslog` 사용자로 권한을 낮추고, AppArmor 프로파일이 읽을 수 있는 위치를 그 아래로 묶어 두기 때문입니다.

**격리.** 학습자가 만지는 컨테이너(Kali, WAF, 에지, 대상 시스템 넷)는 `cap_drop: ALL`에 필요한 capability만 더해 돌립니다.

| 컨테이너 | capability |
|---|---|
| `kali` | `NET_RAW`, `NET_ADMIN`, `SETUID`, `SETGID`, `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `AUDIT_WRITE` |
| `waf` | `NET_BIND_SERVICE`, `SETUID`, `SETGID`, `CHOWN`, `DAC_OVERRIDE` |
| `edge` | `NET_ADMIN` |
| `board`, `board-db`, `corp-db` | `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETUID`, `SETGID` |
| `corp-wp` | 위와 같고 `NET_BIND_SERVICE` 추가 |

- 모두 `no-new-privileges`, Docker 기본 seccomp·AppArmor 프로파일, 메모리·pids 한도를 적용합니다.
- 이 컨테이너 중에는 privileged도, Docker 소켓을 마운트한 것도, 호스트의 network·pid·ipc 네임스페이스를 공유하는 것도 없습니다. 호스트 경로 마운트는 WAF의 audit 로그 파일 하나뿐입니다.
- dockerd를 `userns-remap`으로 돌리므로 컨테이너 안의 root는 호스트에서는 권한 없는 사용자입니다. 호스트 user namespace를 쓰는 것은 센서뿐입니다.
- 렌더링한 슬롯 compose 파일이 이 중 하나라도 어기면 `platform/tests/test_containment.py`에서 `bin/verify`를 실패시킵니다. 실제 환경 검사는 `test/test_range_isolation.py`에서 합니다. 컨테이너를 탈출하면 어디까지 닿는지는 `docs/THREAT-MODEL.md`에 정리돼 있습니다.

**초기화.** `POST /api/sessions/<id>/close/`는 슬롯을 그 자리에서 초기화하며, VM은 재구축하지 않습니다.

- `reset_in_place()`에서 `slot.sh reset N`을 실행합니다. Kali와 WAF는 이미지에서 새로 만들고, 동시에 대상 시스템은 볼륨째 지운 뒤 초기 데이터로 다시 띄웁니다. 에지의 neighbour 테이블을 비우고, 슬롯 로그 파일을 그 자리에서 비운 다음 두 센서가 로그 파일을 다시 열게 합니다.
- 그 뒤 플랫폼에서 두 센서에 기본 룰을 다시 넣습니다.
- 에지와 센서는 내리지 않고 계속 돌립니다.
- 초기화할 슬롯 파일이 훈련 환경 호스트에서 사라졌으면(`/opt/cr/sN/compose.yaml` 없음) 초기화 대신 슬롯을 configure합니다.
- 그래서 앞 세션에서 수정한 룰이나 심어 둔 데이터가 다음 세션에 남지 않습니다.

`POST /api/range/slot/rebuild/`(`rebuild_slot()`)는 `slot.sh down N`으로 슬롯을 내립니다. `compose down -v`를 하고 rsyslog 파일, 슬롯 파일, 로그를 지우며, 다시 올리는 것은 `POST /api/range/configure/`입니다. `DELETE /api/range/slot/`은 모든 슬롯을 내리고, `?slot` 없이 부르면 훈련 환경 호스트와 그 `mgmt` 포트까지 지웁니다.

모든 세션은 같은 초기 데이터에서 시작하지만 비밀 값은 새로 만듭니다.

- board의 `seed`는 시작할 때마다 시드 계정의 비밀번호를 다시 설정합니다. 그래서 세션마다 해시의 salt가 바뀌고, 한 세션에서 훔친 해시는 다음 세션의 정답 데이터와 맞지 않습니다. 시드 글의 날짜도 오늘로 옮깁니다.
- corp의 entrypoint는 이미지의 entrypoint가 돌기 전에 `wp-config.php`를 지웁니다. 그러면 이미지가 무작위 키와 salt로 새 파일을 씁니다. 복원한 데이터에서는 관리자 비밀번호도 다시 설정해 해시를 새로 만듭니다. 설치와 플러그인 설정은 복원한 DB에 이미 있으므로 건너뜁니다.

세션을 닫으면 플랫폼에서 직접 초기화합니다. `platform/api/reset.py`에서 백그라운드 스레드를 띄우고, 룰 잠금을 한 번 잡은 채 초기화를 실행합니다. 훈련 환경 호스트가 ssh에 응답하지 않는 동안은 최대 30분까지 재시도하며, 처음 발생한 실패가 곧 초기화 실패입니다.

close는 즉시 응답하고, 초기화 상태(idle, running, failed와 그 이유)는 플랫폼 프로세스에 보관합니다. 초기화를 시작한 때부터 성공할 때까지 `CR_RESET_OWED_DIR`(`/data/reset-owed`)에 `slot-N` 파일이 남습니다. 부팅할 때 `cr/wsgi.py`에서 이 파일이 남은 슬롯마다 close와 똑같이 초기화를 다시 하므로, 재시작해도 슬롯이 세션을 거부하는 상태로 남지 않습니다. 초기화가 실패하면 파일은 그대로 둡니다. 수동 재시도는 여전히 `POST /api/range/configure/`이고, 실패한 초기화 상태도 이걸로 지워집니다.

**준비 상태.** 모든 슬롯이 사용 중이거나 빈 슬롯 중 준비된 것이 없으면 세션 생성은 409를 돌려줍니다.

`GET /api/range/ready/`는 `slots` 아래에 슬롯별로 다음을 보고합니다.

- 번호와 그 슬롯을 잡은 세션
- 단계: 세션이 잡고 있으면 `IN_USE`, 초기화 중이면 `RESETTING`, 초기화가 실패했으면 이유와 함께 `RESET_FAILED`, 그 밖에는 `NOT_STANDING`, `STALE`(플랫폼보다 오래된 이미지나 슬롯 파일로 도는 훈련 환경 호스트), `SETUP_FAILED`(훈련 환경 호스트 설치 실패. 이유는 그 호스트의 `/var/log/cr-setup.log`), `REBUILDING`(훈련 환경 호스트가 아직 `ACTIVE`가 아니거나 설치가 끝나지 않음), `CHECKING`, `READY`
- 초기화 상태
- 검사 세 가지: 훈련 환경 호스트가 ACTIVE이고 설치가 끝났는지, board의 정답 데이터를 읽을 수 있는지, 센서 룰이 기준선이고 그 슬롯에 비활성화한 룰이 없는지

최상위의 `ready`와 `slot`은 다음 세션을 열 때 배정될 슬롯입니다. 슬롯이 둘 이상이면 슬롯 검사를 병렬로 돌립니다.

`/api/range/slot/`, `slot/rebuild/`, `configure/`는 `?slot=N`을 받고, 없으면 모든 슬롯에 적용합니다.

`POST /api/range/canary/`는 마커를 붙인 케이스를 보내, Suricata와 ModSecurity가 둘 다 경보를 냈는지와 둘의 시계 차이를 보고합니다. 준비 상태 검사에는 포함하지 않으며, 첫 화면에서 둘 다 호출합니다.

**남은 자원.** `GET /api/range/leftovers/`는 훈련 환경 호스트 도입 전의 VM 훈련 환경이 프로젝트에 남긴 자원을 나열하고, `DELETE`로 지웁니다. 대상은 `cr_host` 메타데이터로 찾은 슬롯 VM, 이미지 빌더, 폐기한 구간의 포트·서브넷·네트워크, 보안 그룹 `cr-range`와 `cr-build`, `cr_bundle` 속성이 있는 프로젝트 이미지입니다. `DELETE`는 `bin/cloud up` 마지막 단계에서 호출합니다.

### OpenStack 훈련 환경: 목표 구조

사용자가 2026-09-30에 정하고 2026-10-08에 바꾼 구조입니다. 지금은 역할마다 VM을 두지 않고, 훈련 환경 호스트 한 대에서 모든 슬롯을 컨테이너로 돌립니다.

```
 OpenStack project fsl-range.

 platform VM cr-platform: Ubuntu 24.04, floating IP, docker compose up
   console and /api/, scoring, Elasticsearch, Filebeat, Kibana
   landing page /: start and stop a session, the scoreboard after close
   blue console panes: Kibana, Website, Map, Alerts or IDS rules,
     WAF (ttyd in the platform, ssh to the range host, docker exec), Kali
   red console: Kali (ttyd, ssh to the range host, docker exec), Website
     |
     +--OpenStack API, as member fsl-range--> network, VMs
     +--management network, ssh-------------> range host
                                              (docker exec into a slot)

 range host VM cr-range (Docker, userns-remap): compose project sN per slot

   sN_internet (bridge sN-inet): one subnet per origin country (30)
     kali: holds every attack address; the source is rewritten
           to the chosen country's address as packets leave
       |
       v
     edge: nftables router; its wan holds each subnet's gateway address
           and routes on without NAT, so country sources survive
     edge-sensor (Suricata) on sN-inet: detects
       |
       v
   sN_estate (bridge sN-estate, 10.30.N.0/24)
     waf: nginx + ModSecurity v3 + CRS
          (SecRuleEngine On; the learner tunes CRS to block)
       |
       v
     board (+ board-db on board-default), corp-wp (+ corp-db on corp-default)
     estate-sensor (Suricata) on sN-estate: the WAF-to-target leg

 Evidence (rsyslog imfile on the range host, UDP 5140 over mgmt):
   edge-sensor eve.json ------------> Filebeat --+
   waf ModSecurity audit log --------------------+
   estate-sensor eve.json -----------------------+
                                                 v
   Elasticsearch --> platform ingest --> scoring
   Elasticsearch ----------------> Kibana --> blue team
```

남은 작업:


- 세션 수명 주기: WAF 모드와 시계 차이를 준비 상태 검사에 넣기
- 차단은 구축했습니다. WAF는 `SecRuleEngine On`으로 돌고, 학습자는 WAF 터미널이나 `PUT /api/sessions/<id>/waf/`로 CRS를 조정합니다. 실행한 케이스의 `meta["blocked"]`는 대상 시스템이 아니라 403 응답 여부로 정합니다.
  - 시작 paranoia level은 2026-10-10에 측정했습니다(`docs/DECISIONS.md`). PL1만으로도 board의 SQLi는 차단되고 O'Brien은 통과합니다.
  - 그래서 과차단하도록 만든 방어 설정은 PL1보다 높은 단계에서 시작합니다(시나리오의 `level2`, `level3`). 학습자는 PL을 낮추거나 임계치, 예외 규칙을 조정해 설정을 맞춥니다.

사람이 결정해야 할 남은 사항은 `docs/STATE.md`("Decisions left for a person")에 있습니다.
