# 아키텍처

레인지의 구성, 레인지 안에서 트래픽과 증거가 이동하는 경로, 그리고 그 설계 결정을
다룬다. 점수의 정의는 `CLAUDE.md`에, 미해결 문제와 측정된 특이 사항은
`docs/STATE.md`에 있다.

"결정" 절까지는 지금 실행되는 Docker compose 레인지를 설명한다. 마지막 절
"OpenStack"은 그곳에 구축된 것과 계획된 것
(`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`)을 구분한다.

이 저장소의 출발 가설: 레드팀 공격에 ground truth 라벨을 붙일 수 있고, Suricata와
ModSecurity 경보를 그 라벨에 자동으로 매칭할 수 있으므로, 오탐(FP)과 미탐(FN)을
기계적으로 채점할 수 있다. 목표(objective) 점수는 이 가설이 성립한 뒤에 추가했다.

## 레인지

compose 서비스와 네트워크는 아래 표에 있고, `bin/measure`가 그 수를 센다.
compose 파일 둘이 이들을 나눠 갖는다. `compose.yaml`은 컨트롤 플레인이다(프로젝트
`fsl`, 하나만 오래 떠 있음): 플랫폼, Elasticsearch, Kibana, `collector`, GNS3 서버, 그리고 edge
네트워크 넷과 `mgmt`. `session.yaml`은 세션 하나의 데이터 플레인이다: WAF, Suricata,
Filebeat, Kali, 프록시, wargame. 이 파일은 edge 네트워크와 `mgmt`에 `external`
(`fsl_<network>`)로 붙고, 자기 `estate` 네트워크(고정 서브넷 없음, Docker가 사설 풀에서
할당)와 자기 볼륨을 갖는다. 세션을 열면(`POST /api/sessions/`, `platform/range/docker.py`의
`open_session`) 플랫폼 안에서 `docker compose -p fsl-<세션 id> -f session.yaml up -d
--wait --no-build`를 실행한다. 이때 `FSL_HOST_DIR`은 compose가 플랫폼을 띄운 호스트
디렉터리(플랫폼 컨테이너의 `com.docker.compose.project.working_dir` 라벨)로 두어, 스택의
bind mount가 호스트에서 풀리게 하고, `FSL_SESSION`은 세션 id로 둔다. 이어서 플랫폼은
세션의 `estate`에 붙고(`docker network connect`, 별칭 `platform`; 기본 게이트웨이는
`gw_priority: 1`로 플랫폼 자신의 `edge`에 남는다) 세션의 프록시를 그
세션 자신의 WAF로 향하게 한다(`/label/origin`). baseline은 그 뒤에 읽는다. 세션은 동시에
돈다: 세션을 열면 끝난 지 3분이 넘은 세션의 `fsl-<n>` 프로젝트만 `down -v`하고(먼저 그 `estate`에서
빠진다), 어느 것을 내릴지는 잠금 하나 아래에서 정하므로 동시에 열리는 두 세션이 서로의 새 스택을 내리지 않는다. docker는 세션을 최대 `FSL_MAX_SESSIONS`개(기본 2, `platform/fsl/settings.py`)까지
열고 그 이상은 409로 답한다. OpenStack은 레인지 slot마다 하나를 연다. 세션을 닫아도
그 스택은 3분 이상 지난 뒤 다른 세션이 열릴 때까지 남고, 그동안 Filebeat가 마지막 경보를 보낸다. OpenStack substrate에는 `open_session`이 없다. 그 레인지는 Nova VM이라
세션 스택이 뜨지 않는다. wargame은 VM 하나, `fsl-wargame-host`에서 같은 GHCR 컨테이너로
돈다. 준비 상태 점검과 세션 baseline은 어댑터의 `address("board")`, 즉 board의 8000 포트가
publish된 wargame 호스트의 관리망 주소로 board를 읽는다. `loot.ground_truth`가
`BOARD_API_URL`의 호스트를 그 주소로 바꾼다.

대상 시스템 하나가 wargame 하나이고, `wargames/` 아래 폴더 하나다. `session.yaml`이 그
폴더의 `compose.yaml`을 include 한다: `board`(Django와 MySQL, `loot_verified`)와
`corp`(WordPress와 MySQL, `effect_observed`). 플랫폼은 각 wargame을
`wargames/<id>/scenario.yaml`에서 찾는다(`platform/wargames.py`; 필드는 `name`,
`description`, `image`, `public_url`, `objective_model`, `case_file`, 선택적으로
콘솔의 시나리오 카드에 쓰는 `category`, `difficulty`(easy, medium, hard), `minutes`, 그리고
`defense`와 `lessons`이며 뒤의 "WAF 레슨"에 설명한다). `image`는 아직 아무 코드도 읽지
않는다. 앱 이미지는 CI(`.github/workflows/images.yml`)가 빌드하고
`ghcr.io/nekonic/fsl-<name>:${FSL_IMAGE_TAG:-dev}`로 pull하거나, 로컬에서 그 이름으로
빌드한다. 세션은 그 이미지로 `--no-build` 기동한다. 플랫폼은 자기 `FSL_IMAGE_TAG`를
자신이 띄우는 세션 스택에 넘기고, 도구 케이스는 같은 태그의 `ghcr.io/nekonic/fsl-kali`를
실행한다(`redteam/tools.py`). 새 wargame에는 폴더 안의
`scenario.yaml`, `objectives.yaml`, `compose.yaml`, `redteam/cases/` 아래의 케이스 파일,
그리고 `session.yaml`의 `include:` 줄 하나가 필요하다.

`session.yaml`과 wargame 어디에도 `container_name` 고정이 없다. 세션의 컨테이너는
`fsl-<id>-<service>-1`이다. 고정 이름은 컨트롤 플레인(`fsl-platform`,
`fsl-elasticsearch`, `fsl-kibana`, `fsl-collector`, `fsl-gns3`)에만 남는다. 아래 첫 표는 세션
서비스를 선언된 호스트 이름으로 적으며, `platform/range/docker.py`가 컨테이너를 그
이름으로 되돌려 매핑한다.

레인지에 작용하는 엔드포인트(rules, validate, suppressions, `/api/attacker/`, origin,
label, canary)는 `session`을 쿼리나 본문에서 받는다. 없으면 쓰기는 가장 최근의 열린 세션으로
가고 열린 세션이 없으면 409를 답하며, 읽기는 가장 최근 세션을 쓴다. 닫힌 세션을 지정한 쓰기는
거부된다. 억제는 세션과 함께 저장된다(마이그레이션 0014). 레드 콘솔은 자기 세션 id를 보낸다. 각 세션의
센서는 실제 `local.rules`를 자기 컨테이너 안에 둔다. docker에서는 모든 세션의 센서를
열 때 그 defense의 규칙 파일로, 시나리오에 `defense`가 없으면(corp)
`deploy/suricata/rules/local.rules`로 채운다.
`deploy/suricata/rules`를 bind mount하는 곳은 없으므로 규칙 적용은 그 세션의 센서만
바꾼다. docker에서 남은 문제: 레인지 호스트의 요청을 거부하는 미들웨어는 가장 최근
세션의 `estate`만 다룬다.

| 서비스 | 파일 | 이미지 | 네트워크 | 호스트 포트 |
|---|---|---|---|---|
| `fsl-wg-board` | session | `wargames/board/app`의 `ghcr.io/nekonic/fsl-board` (gunicorn 아래 Django, 포트 8000) | estate | |
| `fsl-wg-board-db` | session | `mysql` | estate | |
| `fsl-wg-corp-wp` | session | `wargames/corp/app`의 `ghcr.io/nekonic/fsl-corp` (WordPress 6.6.2, 취약 버전으로 고정한 플러그인 셋; `Host` 헤더로 `corp.com`) | estate | |
| `fsl-wg-corp-db` | session | `wargames/corp/db`의 `ghcr.io/nekonic/fsl-corp-db` (MySQL 8.4, binlog `ROW`) | estate | |
| `fsl-waf` | session | `owasp/modsecurity-crs` (nginx), edge에서 별칭 `board.com`(공유되므로 플랫폼이 세션마다 프록시와 도구를 그 세션의 WAF로 향하게 함) | edge, edge-br, edge-hk, edge-us, estate | |
| `fsl-suricata` | session | `jasonish/suricata` | WAF의 네임스페이스 | |
| `fsl-filebeat` | session | `filebeat:8.15.0`, 세션의 `eve.json`과 audit log를 보냄 | mgmt | |
| `fsl-kali` | session | `deploy/kali`의 `ghcr.io/nekonic/fsl-kali`; `http_proxy`는 `http://fsl-<id>-proxy-1:8081` | edge | |
| `fsl-proxy` | session | `deploy/proxy`의 `ghcr.io/nekonic/fsl-proxy` (mitmdump); `/label`은 프로젝트의 named volume | 네 개 edge 네트워크 | |
| `fsl-elasticsearch` | control | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-collector` | control | `filebeat:8.15.0`, syslog 입력만(OpenStack 레인지) | mgmt | 5140/udp |
| `fsl-kibana` | control | `kibana:8.15.0`, `/kibana/`에서 제공 | mgmt | |
| `fsl-platform` | control | `platform/` (waitress 아래 Django, nginx 뒤; nginx는 `/kibana/`의 Kibana, `/terminal/<세션 id>/`의 세션별 Kali ttyd, `/waf-terminal/<세션 id>/`의 세션별 WAF 셸, `/vm-terminal/fsl-kali/`와 `/vm-terminal/fsl-waf/`의 VM 터미널도 제공한다); compose 플러그인을 갖고 `session.yaml`을 `/src/session.yaml`에 마운트 | edge 네트워크, mgmt, 열린 각 세션의 estate | 8000, 8002 |
| `fsl-gns3` | control | `deploy/gns3`에서 만든 `ghcr.io/nekonic/fsl-gns3` (gns3-server 3.1.0a6, qemu, uBridge 1.2.3; 읽기 전용으로 마운트한 `deploy/topology`의 프로젝트를 제공하고 열어 둔다; `CAP_NET_ADMIN`, `/dev/net/tun`, Docker 소켓) | mgmt | 3080 |

8000, 8002, 3080은 `FSL_PUBLISH`에, 5140/udp는 `FSL_SYSLOG_PUBLISH`에 바인딩되며 둘 다
기본값은 127.0.0.1이다. 9200은 loopback에만 바인딩된다.

| 네트워크 | 구간 | 서브넷 | 이름 | 출발지 |
|---|---|---|---|---|
| `edge` | `ru` | 5.188.10.0/24 | 인터넷 | 러시아 |
| `edge-br` | `br` | 177.54.144.0/24 | 인터넷 | 브라질 |
| `edge-hk` | `hk` | 103.152.220.0/24 | 인터넷 | 홍콩 |
| `edge-us` | `us` | 73.0.0.0/24 | 인터넷 | 미국 |
| `estate` | `estate` | 세션마다, Docker가 할당 | 애플리케이션 영역(estate) | |
| `mgmt` | `mgmt` | 172.31.0.0/24, 공유 | 관리 | |

edge 네트워크는 모든 세션이 공유하고 서브넷이 고정이다: Docker는 겹치는 서브넷을
거부하고, 서브넷이 GeoIP용 출발지를 나른다. `mgmt`도 공유한다. Elasticsearch, Kibana,
collector가 거기 있고 모든 세션의 Filebeat가 Elasticsearch에 닿아야 하기 때문이다
(`docs/DECISIONS.md`, 2026-10-10). Suricata의 `HOME_NET`은 WAF의 edge 서브넷 넷에
10/8, 172.16/12, 192.168/16을 더한 것이다. 떠다니는 `estate`가 Docker의 사설 풀에서
할당되기 때문이다.

선언은 하나의 인터넷 구간 위에 서른 개의 출발지를 나열한다. Cloudflare Radar의 HTTP
요청 점유율 상위 서른 개 국가이며, 각각 GeoIP가 그 국가로 판정하는 /24 하나와 약
100개의 공격 주소 중 그 몫을 갖는다. Docker는 그중 넷을 네트워크 하나씩으로 만든다.
브리지 하나는 IPv4 서브넷 하나만 담기 때문이다. OpenStack fabric은 서른 개 전부를
한 네트워크의 서브넷으로 만든다. `bin/pick-origins`가 이 표를 재현하고, 수용
테스트가 scoring이 읽는 파이프라인에 대해 모든 서브넷을 검사한다.

망 분리는 Docker 네트워크 소속만으로 이루어진다: 방화벽, iptables, ACL은 없다.
`test/test_segmentation.py`가 라이브 스택에서 이를 검사한다(Kali는 `board.com`에는
닿지만 `board:8000`에는 닿지 못한다). `test/test_concurrent_sessions.py`는 동시에 연 두
세션이 서로를 보지 못함을 검사한다. 고정된 것은 edge 서브넷뿐이고, 컨테이너 주소는
Docker가 할당하며 재생성 시 바뀐다. 뷰는 요청마다 새 어댑터를 만들어 주소를 읽는다.
레인지 호스트에서 온 요청을 거부하는 규칙은 그 주소를 30초 동안 캐시하고, substrate에
닿을 수 없으면 레인지를 비어 있는 것으로 보고 요청을 통과시킨다
(`docs/THREAT-MODEL.md`).

플랫폼, WAF, 프록시는 multi-homed다. 공격자의 트래픽은 WAF를 통해서만 내부망
(`estate`)으로 들어가지만, 플랫폼은 모든 edge 네트워크와 각 세션의 `estate`에 붙어 있으므로 API가 호출자를 직접
검사한다(`docs/THREAT-MODEL.md`).

```
 edge      kali --HTTP via http_proxy--> proxy:8081 --+
           kali --raw TCP (nmap, nc), no proxy--------+
           platform --console-fired case--------------+
 edge-br                                              |
 edge-hk   proxy, platform (no kali, no board.com)    |
 edge-us                                              v
         fsl-waf: nginx + ModSecurity CRS, SecRuleEngine On, port 80
         fsl-suricata in the same network namespace, af-packet on all five
         interfaces, so it sees client->WAF and WAF->target
                                                      |
 estate    board:8000 <--any Host, /internal/ 404-----+
           board --> board-db (MySQL)
           platform --GET /internal/auth-users--> board:8000, past the WAF
 mgmt      filebeat --> elasticsearch <-- platform

 Not network traffic:
   eve.json --volume suricatalogs--> filebeat
   ModSecurity audit.log --volume waflogs--> filebeat
   volume label (per session) --> proxy (read-write), kali (read-only)
   kali's shell --> /var/log/fsl/commands.log, each command with its marker
   platform --docker exec--> proxy (/label files), suricata (rules),
                             waf (CRS tuning, nginx reload),
                             kali (command log), corp-db (mysql, mysqlbinlog)
   platform --docker run--> throwaway fsl-kali for tool cases
   platform --> volume platformdata --> /data/db.sqlite3
```

`deploy/suricata/suricata.yaml`은 인터페이스를 eth0부터 eth4까지 지정하고, Docker가
`compose.yaml`에 설정된 우선순위대로 WAF의 네트워크를 붙인다는 데 의존한다. 이 매핑을
검사하는 것은 없다.

WAF는 `board.com`을 `board:8000`으로 보내고 `/internal/`에는 직접 404로 답한다
(`deploy/nginx/board.conf`). `corp.com`은 `corp-wp:80`으로 가는 두 번째 vhost다
(`deploy/nginx/corp.conf`). board는 첫 번째 wargame이다: gunicorn 아래 Django
3.2.4(알려진 `order_by` SQL 인젝션 취약점 CVE-2021-35042가 있는 미패치 버전)이며,
시작 시 스스로 마이그레이션과 시드를 수행하고, digest로 고정된 MySQL 위에서 돈다. 둘
다 publish되지 않는다. board는 탈취된 계정 정보로 채점한다: 세션이 시작될 때 플랫폼은
board의 `auth_user` 사용자 이름과 비밀번호 해시를 `/internal/auth-users`에서 읽어
세션의 스냅샷으로 보관한다. 플랫폼은 이 경로에 `estate` 네트워크로 직접 접근하며,
WAF는 이 경로를 전달하지 않는다. 이 읽기는 WAF를 거치지 않으므로 IDS도 WAF도 보지
못한다.

corp는 두 번째 wargame이다: WordPress 6.6.2(`fsl-wg-corp-wp`)에 세 플러그인을 미패치
버전으로 고정했다. Ultimate Member 2.6.6(CVE-2023-3460, 가입 요청에 `wp_capabilities`를
주입해 administrator 권한을 얻는 취약점), WP GDPR Compliance 1.4.2(CVE-2018-19207,
관리자 자가 가입을 여는 무인증 옵션 변경), Easy Post Submission 2.3.0(CVE-2026-4431,
무인증 글 덮어쓰기). 어느 것도 기본 OWASP CRS 탐지 규칙에 걸리지 않는다. DB인
`fsl-wg-corp-db`는 `--binlog-format=ROW`로 도는 MySQL 8.4이며, WordPress 자체에는
계측을 넣지 않았다. corp는 공격이 DB에 커밋한 변경으로 채점한다(아래).

## 선언과 substrate 이음매

Docker와 OpenStack은 둘 다 일급 substrate다(2026-10-11 결정). 플랫폼은 레인지의 의미를 Docker에
묻지 않고 `platform/range/declaration.yaml`에서 읽는다: 구간마다 id, 표시 이름, 공격
출발지; 역할 표(attacker, scorer, gateway, proxy, sensor, board, board-db, corp,
corp-db, 그리고 `openstack:` 아래에서 달라지는 edge, sensor, proxy 역할); sensor가
감시하는 호스트; 기본 출발지; 방어 대상 사이트(서울). 출발지를 선언한 구간만
외부 구간이다.

선언에는 서브넷, 게이트웨이, 주소가 없다. 이것들은 substrate에서 온다. Docker와
Neutron이 모두 직접 할당하며, 실제와 다른 서브넷을 선언하면 아무 호스트도 없는
서브넷 기준으로 경보를 분류하게 되기 때문이다. `compose.yaml`은 네트워크 라벨에 구간
식별 정보를 반복한다. `platform/tests/test_declaration.py`는 두 파일을 서로 대조하지만,
실행 중인 레인지는 검사하지 않는다.

구간은 라벨로 찾는다. docker에서는 호스트도 라벨로 찾는다: `declaration.yaml`의
`compose:` 절이 각 역할을 compose 서비스에 매핑하고, 어댑터는 세션 프로젝트에서 그
`com.docker.compose.service` 라벨을 가진 컨테이너를 고른다. 두 곳은 이 조회를 거치지 않고
세션의 WAF 컨테이너를 compose 이름 규칙으로 직접 지정한다: `platform/api/site.py`
(`http://fsl-<id>-waf-1`, 사이트 프록시)와 `platform/api/views.py`(`fsl-<id>-waf`, 레슨의
WAF 박스). 아래 예외 표에 적어 둔다. 각 구간은 `fsl.segment.id`를
Docker 라벨이나 Neutron 태그로 가지며, 어댑터는 라벨이 붙은 네트워크만 가져온다. 같은
구간 id라면 세션 소유 네트워크가 컨트롤 플레인 쪽보다 우선한다. 이름 매칭은 compose
접두사와 오버라이드, Heat 스택 접미사, 유일하지 않은 Neutron 이름에서 깨졌다.
OpenStack에서 역할은 여전히 선언이 지정한 서버 이름이다: OpenStack은 프로젝트의 모든 서버를 나열해 `server["name"]`을
맞추는데, Nova는 이 이름의 유일성을 보장하지 않는다. 이 문제는 `docs/STATE.md`에서
아직 미해결이다.

`platform/range/ports.py`가 인터페이스를 정의한다. 코어 코드와 플랫폼 대부분은 그 네
메서드만 쓴다:

- `describe()`는 구조를 반환한다: 구간, 그 노드와 주소, sensor;
- `segments()`는 sensor 검사 없이 어느 호스트가 어느 구간에 있는지를 반환한다;
- `runner(role, segment)`는 상주 호스트(sensor, proxy, 플랫폼이 명령 로그를 읽는
  attacker, corp-db)에서 명령을 실행한다;
- `launcher(segment)`는 한 구간에서 일회성 도구를 실행하고 그 출력을 반환한다.

`range.substrate()`는 `FSL_SUBSTRATE`가 지정하는 어댑터(기본값 `range.docker.Docker`)를,
`FSL_SUBSTRATE_OPTIONS`가 그 이름 아래 보관하는 옵션에 `declared=RANGE`를 더해 만든다.
Docker는 `FSL_PROJECT`(기본값 `fsl`)를 받는다. OpenStack은 `FSL_OPENSTACK_KEYSTONE`,
`_USER`, `_PASSWORD`, `_PROJECT`, `_SSH_USER`, `_SSH_KEY`, `_REGION`, `_INTERFACE`,
`_DOMAIN`을 받으며, 없으면 이름을 들어 거부한다. 레인지 모양을 정하는 `_BASE_IMAGE`,
`_FLAVOR`, `_BUILD_FLAVOR`, `_ROLE_FLAVORS`, `_AVAILABILITY_ZONE`, `_SUBNETS`, `_MTU`,
`FSL_OPNSENSE`, 그리고 `FSL_IMAGE_TAG`(wargame 호스트의 이미지; 부팅 시
`/opt/fsl/.env`에 쓰인다)는 쓰이는 곳에서 이름을 들어 거부한다. 코드에는 기본값이 없다. 모두
Heat 스택을 거쳐 `deploy/openstack/cloud.yaml`에서 온다(`platform/range/cloud.py`가 그
파일을 읽고 검사한다). `redteam/harness.py`에는 launcher가,
`platform/rules/suricata.py`에는 runner가 전달되므로, 둘 다 `subprocess`를 import하지
않고 substrate를 지정하지도 않는다.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| 구조 | `docker network ls/inspect`, 라벨 필터 | Keystone v3, `tags-any`를 쓰는 Neutron, Nova |
| sensor | 선언된 각 sensor가 선언된 gateway의 네트워크 네임스페이스를 공유하지 않으면 레인지 기술(describe)을 거부한다 (`docker ps`, `.HostConfig.NetworkMode`) | 이름이 지정된 두 서버가 모두 존재하면 sensor를 보고한다; 그것이 gateway의 트래픽을 보는지 확인하는 것은 없다 |
| runner | 세션 프로젝트에서 그 역할의 서비스 컨테이너로 `docker exec` | 인스턴스로 `ssh`; wargame 호스트가 맡고 `compose:`가 서비스에 대응시킨 역할은 그 컨테이너 안에서 실행된다(`sudo docker exec <service>`, `range/wargame_host.py`) |
| address | 세션 프로젝트에서 그 역할의 `estate` IP | 호스트의 `mgmt` 주소 |
| launcher | `docker run --rm --network <segment>`, 세션 WAF의 이름을 가리키는 `--add-host` 포함 | `runner("attacker")`: 선언된 attacker의 mgmt 주소로 ssh해 도구를 실행한다(origin은 attacker가 그 구간에 있는지만 확인하고, 출발 국가는 `fsl-origin` SNAT가 정한다); 다른 이미지는 거부되는데, Nova는 호스트를 부팅해 출력을 반환하고 삭제할 수 없기 때문이다 |
| 테스트 대상 | 라이브 스택 | 공개된 API 레퍼런스와 로컬 sshd로 만든 fake에 대한 유닛 테스트; `fsl-range` 클라우드에서는 플랫폼 VM이 `/api/range/`를 통해 fabric, 이미지, slot을 구축했고, `describe()`가 서른 개 출발지 위의 WAF와 estate 및 mgmt 위의 네 호스트를 되읽었으며, `runner()`가 각 호스트에서 mgmt 주소로 ssh를 통해 실행됐다; `launcher()`는 2026-10-08 `ru`와 `tw` 출발지에서 sqlmap을 실행했다 |

compose는 substrate와 무관하게 Docker 소켓을 플랫폼에 마운트하고, entrypoint는 플랫폼
사용자를 그 그룹에 추가한다. 이는 컨테이너 탈출 경로다. OpenStack 어댑터를 쓰면
제거할 수 있지만 아직 제거하지 않았다. 어댑터가 레인지를 구동하기 전에 남은 작업은
`docs/STATE.md`의 "The substrate seam"에 있다.

## 토폴로지

레인지 토폴로지는 GNS3 프로젝트 파일 두 개다: `deploy/topology/range-docker.gns3`와
`deploy/topology/range-openstack.gns3`. `revision` 9라서 GNS3 2.2가 열고 3.x는 불러올 때
올린다. 구간은 `ethernet_switch` 노드, Docker 컨테이너는 실제 이미지를 가진 `docker`
노드, OpenStack VM은 디스크 이미지 없는 `qemu` 노드(OPNsense 엣지는 vtnet 순서대로 NIC
셋)다. wargame 호스트의 컨테이너는 compose 프로젝트마다 스위치 하나(`board-default`,
`corp-default`)에 붙는다. 다른 컨테이너의 네트워크 네임스페이스나 호스트 네트워크를 쓰는
센서는 NIC가 없고, 옆의 메모가 누구의 네트워크를 지켜보는지 말한다(Docker 프로젝트에서는
점선이 `fsl-suricata`를 `fsl-waf`에 잇는다). 선언된 구간마다 그 스위치를 담은 제목 붙은
사각형이 있고(Internet, Application estate, Management and monitoring), 컨테이너와 VM마다
쉬운 말 메모가 붙는다(`attacker's machine (Kali)`, `web firewall (ModSecurity + CRS)`). GNS3
3.1은 노드 라벨을 이름으로 바꾸므로 노드 이름은 호스트 이름 그대로 둔다. 학습자 로그인 페이지는
포트 라벨을 숨긴다. `platform/tests/test_gns3_topology.py`가 `declaration.yaml`,
`compose.yaml`, `session.yaml`, wargame compose 파일에서 기대 노드와 링크를 유도해 비교하고
GNS3의 구조 규칙을 확인한다. `bin/check-topology`는 gns3-server 2.2.61과 3.1.0a6을
`~/.cache/fsl/check-topology` 아래 venv에 설치하고 각 버전의 `load_topology`를 각 파일의
사본에 돌린다.

`gns3` 서비스(`deploy/gns3`, MCP extra를 포함한 gns3-server 3.1.0a6)는 두 파일을
`/var/lib/fsl-gns3/projects` 아래 각자의 디렉터리로 복사하고(이 레포의 `:dev` 이미지 태그를
호스트가 실행하는 태그 `FSL_IMAGE_TAG`로 바꿔 쓴다), 컨트롤러 데이터베이스가 생기기 전에 admin
비밀번호를 정하며(`FSL_GNS3_ADMIN_PASSWORD`, 없으면 `/var/lib/fsl-gns3/admin-password`에 한 번 생성),
learner 사용자에게 `/`에 대한 내장 Auditor 역할을 주고(`FSL_GNS3_AUDITOR_PASSWORD`, 기본값
`fsl-auditor`, 플랫폼에도 전달), `/static/web-ui/fsl-auditor.html`을 쓴다. 이 페이지는
learner로 로그인해 번들 웹 UI가 컨트롤러를 읽는 자리(`localStorage`의 `controller-1`,
`controllerIds`)에 토큰을 둔다. 개발용 MCP(`/v3/mcp/`)에는 `docker exec fsl-gns3 python
/opt/fsl-gns3/provision.py api-key <이름>`이 API 키를 출력한다. 콘솔은 MCP를 노출하지 않는다.

GNS3는 모든 노드를 compute에 만들어야만 프로젝트를 열고, 읽기 전용 사용자는 프로젝트를 열 수
없다(`Project.Allocate`). 그래서 `provision.py`가 시작할 때 admin으로 두 프로젝트를 열어 두고,
Auditor는 열린 프로젝트를 본다. 만들기는 시작이 아니다: 어떤 노드도 시작하지 않는다. 만들기에
필요하고 서비스가 갖춘 것: `qemu` 노드에는 `qemu-system-x86`(디스크 이미지 없음),
`ethernet_switch` 노드에는 릴리스 태그에서 빌드하고 `cap_net_admin,cap_net_raw` 파일
capability를 준 uBridge 1.2.3과 `CAP_NET_ADMIN`, `/dev/net/tun`(3.1은 스위치마다 컨테이너 자기
네트워크 네임스페이스 안에 커널 브리지와 TAP을 만든다), `docker` 노드에는 호스트의 Docker
소켓(노드마다 호스트 데몬에 특권 컨테이너 `GNS3.<노드>.<프로젝트 id>`를 만들기만 하고 시작하지
않는다). 호스트 데몬은 그 컨테이너의 바인드 마운트를 호스트에서 찾으므로 데이터 디렉터리는 양쪽에서
같은 경로다(`/var/lib/fsl-gns3`). 서버는 `gns3` 사용자로 돌고, 플랫폼의 `fsl`처럼 시작할 때 소켓의
그룹에 들어간다. `GET /api/topology/`는 GNS3가 프로젝트를 `opened`로 보고할 때만 웹 UI(`web_ui`)를
내주고, 아니면 콘솔의 토폴로지 창이 같은 파일을 직접 그린다.

`GET /api/topology/`는 substrate의 프로젝트를 GNS3에서(`platform/gns3.py`) 또는 레포 파일에서
돌려준다. `GET /api/sessions/<id>/topology/`는 `project.nodes`를 더한다: 같은 레인지
읽기에서 얻은 호스트 노드별 선언 구간 주소와 `running` 또는 `not reported`.
`GET /api/sessions/<id>/topology/follow/?request=<웹사이트 창 요청 id>`(또는 `?marker=`)는
출발 주소의 노드에서 게이트웨이를 거쳐 대상까지 프로젝트 링크를 따라가되 스위치와 엣지,
게이트웨이, wargame 호스트만 통과하고, 센서 경보는 센서가 지켜보는 호스트에, WAF의 규칙 id와
판정은 게이트웨이에(403으로 응답했거나 CRS의 차단 평가 규칙 949110이 걸리면 차단), 상태 코드는
대상에 붙인다.

## 격리 경계(isolation seams)

각 관심사는 하나의 파일만 소유한다. 아래 예외는 현재 코드에 존재한다.

| 관심사 | 소유 파일 | 알려진 예외 |
|---|---|---|
| Elasticsearch | `platform/ingest/elastic.py` | `platform/register_pipeline.py`가 기동 시 `fsl-geoip` ingest 파이프라인을 PUT 한다 |
| Kibana HTTP API, saved object, Discover 링크 | `platform/kibana.py` | 없음 |
| GNS3 API | `platform/gns3.py` | GNS3 컨테이너 안의 `deploy/gns3/provision.py`가 admin으로 로그인해 learner를 만들고 프로젝트를 연다. 콘솔의 토폴로지 창은 `gns3.py`가 돌려준 포트와 경로의 웹 UI를 iframe으로 연다 |
| CRS 설정과 nginx 재적재 | `platform/rules/crs.py` | WAF 터미널(`waf-terminal.sh`)이 사람에게 `fsl-<id>-waf-1`의 셸을 열고(OpenStack에서는 `vm-terminal.sh fsl-waf`가 WAF VM에 ssh 셸을 연다), 실습의 WAF 화면 단계 문구가 읽을 제외 파일과 audit 로그 경로를 알려 준다. 그 명령의 파일 경로와 reload는 `wargames.lesson`이 선언(`settings.FSL_WAF`)에서 채운다. 플랫폼은 어느 것도 읽지 않는다 |
| 세션의 WAF 컨테이너(docker) | `platform/range/docker.py`, compose 라벨로 | `platform/api/site.py`는 `http://fsl-<id>-waf-1`을, `platform/api/views.py`는 `fsl-<id>-waf`를 compose 이름 규칙으로 직접 만든다 |
| Suricata 프로세스 | `platform/rules/suricata.py` | `platform/range/opnsense.py`와 `deploy/opnsense/`가 OPNsense 엣지의 Suricata를 설정하고 다시 시작한다(OpenStack). `declaration.yaml`의 각 센서 호스트(엣지, 그리고 `estate-sensor`의 wargame 호스트)가 `suricata.py`에 넘길 규칙 파일과 reload 명령을 정한다. `platform/range/wargame_host.py`(`deploy/wargame-host/sensor.yaml`과 함께)는 슬롯을 설정하거나 리셋할 때 wargame 호스트의 estate 센서 compose 서비스를 멈추고 다시 띄우며(OpenStack), 그 뒤 기준 규칙은 `suricata.py`를 거친다 |
| 공격자 박스 | `platform/attacker.py` | `platform/operator_log.py`가 `/var/log/fsl/commands.log`를 읽는다; 터미널 배선(`settings.py`, `nginx.conf`, `entrypoint.sh`)이 `fsl-kali`와 `fsl-<id>-kali-1`을 지정한다 |
| 대상 시스템 자체의 기록 | `platform/api/loot.py`(board), `platform/api/effect.py`(corp) | 없음; OpenStack에서도 같은 컨테이너에 닿는다. `loot.py`는 wargame 호스트의 publish된 포트로 HTTP, `effect.py`는 `corp-db`로 `docker exec`하는 runner를 거친다 |

## 요청이 어디서 오는가

| 경로 | 발신자 | 경보의 출발지 주소 | marker |
|---|---|---|---|
| 터미널, HTTP | Kali, `proxy:8081`을 거쳐 | 프록시, 선택된 출발지에서 | 프록시가 추가 |
| 터미널, raw TCP | Kali 직접 | Kali, `edge`에서만 | 없음 |
| 콘솔 케이스, HTTP | 플랫폼 | 플랫폼, 선택된 출발지에서 | harness가 추가 |
| 콘솔 케이스, 도구 | 일회용 `fsl-kali` 컨테이너 | 그 컨테이너, 선택된 출발지에서 | sqlmap `--headers=` |
| CLI 실행, HTTP | 플랫폼, `redteam/run.py` | 플랫폼, `edge`에서(`board.com`이 해석되는 곳) | harness가 추가 |
| CLI 실행, 도구 | 일회용 `fsl-kali` 컨테이너, `launcher(<선언된 기본 출발지>)`에서 | 그 컨테이너 | sqlmap `--headers=` |
| 사이트 브라우저 | 학습자의 브라우저, 플랫폼 nginx의 8002번 포트와 `platform/api/site.py`를 거쳐 | 플랫폼, `edge`에서(OpenStack에서는 `mgmt`에서) | 세션의 비밀값 `browse-<hex>`, `site.py`가 설정. API는 `browse`로 보여 줌 |

프록시는 `mitmdump` 스크립트다. `/label/active`에서 `X-FSL-Case`를 설정하고,
`/label/origin`에 주소가 있으면 원래 `Host`를 유지한 채 요청을 그 주소로 전달한다.
플랫폼은 두 파일을 `docker exec`로 쓴다. TLS 가로채기가 없으므로 프록시는 환경 변수일
뿐 아무것도 강제하지 않는다: `curl --noproxy '*'`는 프록시를 거치지 않는다.

터미널은 operator가 입력하는 명령도 기록한다. Kali의 셸은 각 명령을 현재
`/label/active` marker와 함께 `/var/log/fsl/commands.log`에 덧붙인다. 플랫폼은
`runner("attacker")`로 이를 읽어 `GET /api/sessions/<id>/commands/`로 제공한다. 레드
콘솔은 compose에서 `/terminal/<세션 id>/`를 프레임에 띄우고, nginx가 이를
`fsl-<id>-kali-1:7681`의 Kali 자체 ttyd로 넘긴다. OpenStack에서는 `/vm-terminal/fsl-kali/?arg=<세션 id>`를
띄운다. 이는 플랫폼 안의 ttyd로, 세션의 slot에 있는 호스트의 mgmt 주소로 ssh 접속한다. compose에서는 Kali와
WAF에 mgmt 주소가 없으므로 `/vm-terminal/`은 연결되지 않는다.

블루 콘솔의 WAF 창은 세션 API가 알려 주는 URL(`GET /api/sessions/<id>/`의 `waf_terminal`)을
프레임에 띄운다. compose에서는 `/waf-terminal/<세션 id>/`이다. nginx가 경로에서 세션을 꺼내고
클라이언트의 쿼리는 버린 뒤 플랫폼 안의 ttyd(`ttyd -a -b /waf-terminal -p 7693 /app/waf-terminal.sh`)로
`?arg=<세션 id>`를 붙여 넘긴다. ttyd의 `-a`가 이를 스크립트 인자로 주고, 스크립트는 숫자인지 확인한 뒤
`docker exec -it fsl-<id>-waf-1 bash`를 실행한다. WAF 이미지에는 ttyd가 없다. 같은
`auth_request /terminal-allowed`가 막는다. OpenStack에서는 `/vm-terminal/fsl-waf/?arg=<세션 id>`를 띄운다.

블루 콘솔의 웹사이트 창은 콘솔 안의 브라우저다: 뒤로, 앞으로, 새로고침, http에는 Chrome처럼 "주의 요함"
표시를 붙이고 전체 URL(`http://board.com/<경로>`)을 보여 주며 URL이나 경로와 Enter를 받는 주소창, iframe
안의 페이지, "개발자 도구" 토글. 대상 시스템은 공개되지 않으므로 8002의 nginx가 터미널과 같은
`auth_request /terminal-allowed` 뒤에서 `/site/<세션>/<호스트>/<경로>`를 플랫폼의 기록기
(`/site-proxy/<세션>/<호스트>/`, `platform/api/site.py`, 정확한 경로와 쿼리는 `X-Site-Uri`)로 넘기고,
기록기가 그 세션의 WAF(`fsl-<id>-waf-1:80`, 공유 `edge` 네트워크로 닿음)로 `Host: <호스트>`를 붙여,
리다이렉트를 따라가지 않고 압축 없이 보낸다. 넘기는 헤더는 `Accept`, `Accept-Language`, `Content-Type`,
`User-Agent`, `Referer`, `Origin`뿐이다. `X-Forwarded-For`는 넘기지 않으므로 대상과 그 audit log에는
학습자의 LAN 주소가 아니라 플랫폼이 보인다. 없는 세션에는 404, 닫힌 세션에는 409를 WAF를 부르지 않고
답한다. WAF가 연결 3초, 읽기 20초 안에 답하지 않으면 내부 호스트 이름 없이 평문 한 줄로 502를 답한다.
페이지는 도착하는 대로 브라우저에 흘려보낸다. 8000의 nginx는 `/site-proxy/`에 404를 주고, 플랫폼의 POST
같은 출처 검사는 그 경로를 건너뛰므로 대상의 폼도 제출된다. 모든 페이지를 WAF가 판정한다: 차단되면 WAF
자신의 403 페이지가 보이고 Kibana에 기록이 남는다. 경로와 쿼리는 브라우저가 보낸 그대로 넘어간다(`$request_uri`에 대한 `map`). nginx는 접두사를 벗어날
것들을 고쳐 쓴다: `Location` 헤더(`proxy_redirect`), HTML의 `href="/`, `src="/`, `action="/`,
`http://<호스트>/`, `http://<호스트>"`(`sub_filter`, 위쪽에는 압축하지 말라고 요청), WordPress가
이스케이프한 `http:\/\/corp.com\/`도. `Cookie`와 `Set-Cookie`를 지우므로 플랫폼의 쿠키는 대상에
가지 않고 대상의 `Set-Cookie` 헤더는 버려진다. 그래서 이 창에서는 대상에 로그인할 수 없다. 다만 대상
페이지의 스크립트는 막지 못한다: 그 스크립트는 플랫폼 호스트(8002번 포트)에서 돌고, 쿠키는 포트로
분리되지 않으므로 `document.cookie`로 8000의 콘솔이 보낼 쿠키를 심을 수 있다. 지금 콘솔은 쿠키를 쓰지
않는다. 나중에 쿠키를 쓰게 되면 이 경로로 닿는다. `</body>`
앞에 `location.pathname + search`를 부모 창에 postMessage하는 스크립트를 붙여, 페이지 안에서 링크를
눌러도 주소창과 기록이 따라간다.

이 경로는 콘솔의 8000과 다른 출처인 별도 포트 8002에서 서비스되고, 모든 응답에 `Content-Security-Policy:
sandbox allow-forms allow-scripts allow-same-origin`이 붙는다. 대상은 레드팀이 스크립트를 심을 수 있는
곳이다. 콘솔과 같은 출처라면 그 스크립트가 콘솔과 그 API를 읽고 조작할 수 있다. `allow-same-origin`
없는 sandbox(불투명 출처)로 8000에서만 막을 수도 있지만, Chromium 기반 내장 브라우저는 그런 프레임을
거부한다(Claude 데스크톱 브라우저에서 `ERR_BLOCKED_BY_CLIENT`). `SITE_PORT`는 모든 substrate에서
8002다. docker에서는 프록시가 세션의 WAF 컨테이너(`fsl-<id>-waf-1`)를 이름으로 부르고, OpenStack에서는
세션마다 한 번 substrate에 그 슬롯의 gateway `mgmt` 주소를 물어 그리로 넘긴다(플랫폼 포트는
`fsl-mgmt`를 거쳐 닿는다). 세션 API는 `site: {port, path}` 또는 `null`을 주고, 없으면 콘솔은 창을
숨긴다. 플랫폼 템플릿의 security group이 8002를 연다(`docs/OPENSTACK.md` §3.5).

기록기는 세션마다 마지막 요청 200개를 플랫폼 메모리에 둔다(재시작하면 사라짐): 메서드,
`http://<호스트><경로>`, 상태, WAF가 막았는지(403), 걸린 시간, 요청·응답 헤더, 각각 64 KB로 자른 본문
(응답은 흘려보내며 앞 64 KB만 남김). 세션이 닫히면 그 세션의 요청을 지운다.
`GET /api/sessions/<id>/site/requests/?after=<id>`가 목록을, `.../site/requests/<id>/`가 하나를 통째로
준다. 개발자 도구 패널은 페이지 아래에 붙고(위쪽 가장자리를 끌어 높이를 바꿈), 열려 있고 탭이 보이며 세션이 열려 있는 동안 2초마다(닫힌 세션은 409를 답하고 가져오기가 멈춤)
목록을 가져와 메서드, URL, 상태(403은 빨간색과 "WAF 차단"), 시간을 보여 준다. 행을 고르면 두 헤더와 요청
본문, 응답 본문(앞 2000자와 "더 보기")이 나온다. "소스 보기"는 주소창 페이지의 기록된 본문을 보여 준다.
패널은 쿠키를 보관하지 않는다고 알린다.

브라우징은 세션 자신의 비밀값(`Session.browse_marker`, `browse-`와 무작위 16진수 32자리, 세션을 만들 때
생성)으로 표시되고(브라우저가 보낸 `X-FSL-Case`는 기록기가 덮어씀), 요청은 플랫폼의 `edge` 주소에서
나간다. 그 경보는 다른 경보처럼 수집·목록화되어 학습자가 Kibana와 `/detections/`에서 찾을 수 있지만,
`/score/`는 레슨 자신의 재실행(시드, 검증, 확인, 재실행)처럼 그 세션의 비밀값이 붙은 탐지를 뺀다: 브라우징은 케이스가 아니므로
정탐·오탐도, 귀속되지 않은 경보도 아니다. 손으로 보낸 `X-FSL-Case: browse`는 모르는 marker일 뿐이라
점수에 들어가고, `POST /api/attacker/label/`은 `browse`로 시작하는 label을 거부한다. API는 비밀값을
보여 주지 않는다: `/detections/`, `/api/detections/<id>/`(`raw` 포함), 네트워크 패널은 그 자리에
`browse`를 보인다. Kibana에는 보이는데, Kibana는 블루팀의 도구다. 레드 콘솔에는 사이트 창이 없다.

콘솔 HTTP 케이스는 출발지 선택과 무관하게 세션 wargame의 `Host`인 `board.com`을
싣는다. 출발지를 선택하면 트래픽은 그 출발지 구간에 있는 WAF의 주소로 IP를 지정해
간다. 이름은 `edge` 네트워크에서 해석되며, 출발지가 없을 때 플랫폼은 이 네트워크를
쓴다. edge 네트워크는 공유되므로 거기서 `board.com`은 모든 세션의 WAF로 풀린다. 그래서
세션을 열 때 플랫폼은 세션의 프록시를 그 세션의 WAF로 향하게 하고, 실행하는 도구에는
그 WAF 주소를 가리키는 `--add-host board.com`, `corp.com`을 준다. `rotate`는 무작위
선택이 아니라 세션별 라운드 로빈이다.

콘솔 도구 케이스는 출발지의 대상 URL로, 출발지가 없으면 선언된 기본 출발지에서
`TARGET_URL`(`http://board.com`)로 향한다. 대상 시스템은 호스트에 publish되지 않으므로
명령줄 harness도 레인지 내부에서 접근한다: `redteam/run.py`는 플랫폼에서 실행되고(수용
테스트가 구동하는 방식), 출발지 옵션이 없으며, `--target`의 기본값은 `--cases` 파일이 속한
시나리오의 `public_url`(board는 `http://board.com`)로, 포트 80의 WAF로 해석된다.
`--tool-target`의 기본값은 `http://board.com`이다.

docker에서 세션 WAF는 CRS를 `SecRuleEngine On`, anomaly threshold 5로 돌린다
(`session.yaml`). Paranoia Level과 rule exclusion은 세션 자신의 것이며(`Session.waf`), 열 때
시나리오의 defense로 쓰고 `/api/sessions/<id>/waf/`로 바꾼다("WAF 레슨"). `GET`은 10초 timeout으로
파일을 읽으므로 폴링 하나가 서버 스레드를 그보다 오래 잡지 않는다. 모든 Suricata
규칙은 `alert`이므로 레인지에서 차단하는 것은 WAF뿐이다. OpenStack의 WAF VM도 같은 방식으로
차단한다(`deploy/waf/modsecurity.conf`의 `SecRuleEngine On`, CRS 기본값 threshold 5, Paranoia Level 1).

## 경보가 어디로 가는가

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, fsl-logs-<session>-<day>
                                     (fsl_source)   pipeline fsl-geoip
                                                          |
             POST /api/sessions/<id>/ingest/ (called by tests and by the session page's close)
                                                          |
             parse per fsl_source, copy the marker onto alerts, store
             as Detection rows in SQLite
```

`ingest/`는 `test/conftest.py`와 세션 페이지의 종료 확인이 호출하고, `redteam/run.py`는
curl 명령을 출력만 한다. 브라우저로 진행한 라운드는 종료 시점에 탐지 결과를 한 번
적재하며, 클릭 이후에 도착한 경보는 적재되지 않는다.

ModSecurity의 audit 로그는 요청 헤더를 담으므로 그 경보에는 marker가 바로 있다.
Suricata의 alert 이벤트에는 요청 헤더가 없고 `http` 이벤트에만 있다
(`dump-all-headers: request` 설정 시; `custom: [X-FSL-Case]`는 효과가 없다). ingest는
같은 `(flow_id, tx_id)`를 가진 `http` 이벤트의 marker를 alert로 복사한다. `flow_id`만으로
조인하면 keep-alive 연결의 모든 경보가 그 연결의 첫 케이스에 귀속되었다.

각 ingest 호출은:

- 먼저 만료된 규칙 억제(suppression)를 복원한다;
- docker에서는 `fsl-logs-<session>-*`를 읽고(`ELASTIC_SESSION_INDEX`; 세션마다 자기
  Filebeat가 자기 인덱스에 쓴다), OpenStack에서는 `fsl-logs-slot<N>-*`를 읽는다(공유
  collector가 syslog 줄마다 송신자 hostname이 가리키는 slot(도메인 앞의 `-N`, 없으면 slot 1)을
  붙여 그 slot의 인덱스에 쓴다);
- 세션 시작 1분 전부터 종료(또는 현재) 1분 후까지의 `@timestamp`를 Elasticsearch에
  요청한다. `fsl-geoip` 파이프라인은 `@timestamp`를 이벤트 자체의 시각(Suricata의
  `timestamp`, ModSecurity의 `transaction.time_stamp`)으로 설정하므로, 이 창은
  Filebeat가 읽은 시점이 아니라 이벤트가 발생한 시점으로 이벤트를 고른다;
- 오래된 것부터 한 번에 5000개의 hit를 읽고, 잘리면 받은 것 중 가장 새로운 `@timestamp`부터
  다시 묻는다(`api/views.py` `_fetched`, 최대 40번 더; 이미 읽은 문서는 `_id`로 건너뛴다). 그래도
  창을 다 읽지 못하거나 5000개가 한 시각을 공유하면 응답에 `truncated`가 실리고 세션은
  `read_of`를 기록하며, 점수에 `score.warning.truncated`가 추가된다. sqlmap 케이스 하나가
  5000개 넘는 기록을 남기므로, 한 번만 읽으면 그 뒤에 쏜 케이스가 모두 FN이 됐다;
- Suricata의 `alert` 이벤트를 유지하고, ModSecurity 레코드는 매칭된 규칙 메시지마다
  Detection 하나(id `<Elasticsearch _id>:<n>`)로 바꾼다;
- 이벤트 시각이 창 밖인 경보는 버리고 `stale`로 센다;
- 나중에 발견된 marker를 marker가 없던 저장 행에 기록한다;
- `src_host`와 `dest_host`를 substrate의 구간 정보로 채우며, substrate에 닿을 수
  없으면 비워 둔다. 수집과 `/detections/`는 레슨 폴링마다 `docker network ls`와 `inspect`를 돌리지
  않고 세션의 구간 정보를 30초 동안 재사용한다. `/top/`, `/map/`, `/topology/`는 매번 새로 읽는다.

Elasticsearch는 저장과 색인 시점의 GeoIP 보강에 쓰이며, 그래서 Logstash가 없다. 쿼리
엔진은 시간 범위 검색에만 쓴다: `GET /api/sessions/<id>/map/`과 `/top/`은 SQLite
사본을 대상으로 Python에서 계산하고, `src_geo.location`은 `geo_point`가 아니라 float
두 개로 매핑된다. `bin/worldmap`은 남위 60도에서 자른 Equal Earth 지도를 생성하지만,
블루 대시보드가 제거된 뒤로 이를 그리는 콘솔 페이지는 없다.

geoip 프로세서 둘(`src_ip`는 Suricata, `transaction.client_ip`는 ModSecurity)이
`src_geo`를 쓴다. compose는 관리형 다운로더를 끄고 `./config/ingest-geoip`를
bind-mount 하며, `bin/fetch-geoip`가 이 디렉터리를 채우므로 `GeoLite2-City.mmdb`는
컨테이너를 재생성해도 남는다. entrypoint가 기동 시 파이프라인을 등록한다
(`platform/register_pipeline.py`, `kibana.py`처럼 백그라운드에서 돌므로 Elasticsearch가 뜨는 중에도
플랫폼은 응답한다). waitress는 스레드 16개로 플랫폼을 서비스한다.

## WAF 레슨

세션은 `POST /api/sessions/` `{scenario, guidance, lesson, mode, defense}`로 열고, 세션에
저장된다(마이그레이션 0015, 0022, 0023). `defense`는 시나리오의 `defense` 항목 중 하나를
고르고(기본값 `full`), `guidance`(기본값 꺼짐, `lesson`을 주면 켜짐)는 시나리오에 `lessons`가 있어야
한다. 시나리오는 `scenario.yaml`에 `lessons:` 목록을 선언하고, 레슨마다 `id`, `order`와 선택적으로
`level`(easy, medium, hard), `minutes`, `prerequisites`(같은 시나리오의 다른 레슨 id)를 두며 발견 시
검증한다. 아직 단일 `lesson:`을 쓰는 descriptor는 거부한다. board에는 일곱 개가 있고 아래 "board의
과정"에 나열한다. `lesson`(기본값은 시나리오의 `default_lesson`, 없으면 `order`가 가장 앞선 레슨; board의
기본값은 `waf-exclusion`)은 `Session.lesson`에 남고 `lesson_id`로 보고된다. `mode`는
`guided`(기본값, 또는 레슨 자신의 `mode`) 또는 `self`(`Session.mode`)이고, 워게임에서는 거부되며, 열린 레슨에서
`PATCH /api/sessions/<id>/ {mode}`로 바꾼다. board는 `minimal`(CRS paranoia level 4, `local.rules`),
`full`(paranoia level 1, 같은 `local.rules`), `ids`(paranoia level 1, `no-uri-sqli.rules`: sid 9000001을
뺀 `local.rules`)를 선언한다. 레슨은 시작할 defense를 선언하고(`defense`,
board 레슨은 `minimal`, 발견 시 시나리오의 `defense`와 대조), defense를 밝히지 않은 guidance 세션은
그것을 쓴다. `GET /api/wargames/`는 시나리오마다 `lessons`를 `id`, `order`, `title`·`goal` 문자열 키,
`minutes`, `level`, `defense`, `prerequisites`, 단계 수와 함께 나열하고, 첫 레슨의 `lesson_defense`,
`lesson_text`, `lesson_steps`도 그대로 둔다. `GET /api/sessions/?ids=1,2`는 세션 목록을 주어진 id로
좁힌다. 모든 기반에서 스택이
뜬 뒤 여는 경로가 센서에 그 defense의 규칙 파일을, defense가 없으면 `local.rules`를
넣고(`suricata.seed`), defense가 있을 때 CRS 튜닝을 쓴다(`crs.apply`). guidance 세션은 이어서
lesson의 케이스를 한 번 재생하므로(`meta.seed`), 학습자가 들어왔을 때 ModSecurity와
Suricata 기록이 이미 Kibana에 있다. slot이 있는(OpenStack) 레인지에서 규칙 파일이
`local.rules`이면 센서 시드는 건너뛴다: 준비 확인이 모든 센서에 그 파일이 있을 때만 slot을
내주었기 때문이다. slot마다 센서가 자기 규칙 파일을 가지므로(2026-10-13 측정: slot 1에 적용한 sid가
slot 2에는 없었다) 다른 규칙 파일은 그 slot의 센서에만 들어간다. 열 때의 재생이
실행되지 못하면 503으로 답하고 세션을 닫는다. 그 스택은 남겨 두었다가 다음 세션을 열 때 내린다.

`platform/rules/crs.py`는 튜닝을 `REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`로
렌더한다. 이 파일은 `crs-setup.conf` 다음, 규칙보다 먼저 읽히는 CRS 훅이다:
`tx.blocking_paranoia_level`과 `tx.detection_paranoia_level`을 정하는 `SecAction`
하나와, 항목마다 런타임 제외 하나(`ctl:ruleRemoveTargetById=<id>;<target>` 또는
`ctl:ruleRemoveById=<id>`, 경로가 있으면 `SecRule REQUEST_FILENAME "@beginsWith
<path>"`로 범위를 좁힘). 파일은 `runner("gateway")`로 그 세션의 WAF에 쓰고, `nginx -t
&& nginx -s reload`를 실행하며, nginx가 거부하면 이전 파일로 되돌린다. 재적재 전에 없던
워커가 뜨면(`/proc`에서 부모 PID로 워커 PID를 읽음) 반환하므로, 새 연결은 새 튜닝을 만난다.
이전 워커는 느린 요청을 마저 처리할 수 있다. 5초 안에 새 워커가 뜨지 않으면 재적재가 일어나지
않은 것이므로 이전 파일을 되돌려 재적재하고 거부한다. 쓰기 전에 입력을
검증한다: paranoia 1-4, 규칙 id 900000-999999, target은 `ARGS`, `ARGS_GET`,
`ARGS_POST`, `ARGS_NAMES`, `REQUEST_COOKIES`, `REQUEST_HEADERS`에 선택적 `:이름`,
경로는 `[A-Za-z0-9_./-]`, 항목은 최대 20개. `PUT /api/sessions/<id>/waf/`가 이를
바꾸고(에이전트 경로), `GET`은 세션 WAF의 파일을 `crs.read`로 다시 읽는다. `crs.read`는 Paranoia
Level과 모든 `ctl:ruleRemove*` 줄을 파싱하므로(주석 줄은 건너뛰고 이어진 줄은 합침) WAF 터미널에서
고친 내용도 알려 준다. 검증마다, 그리고 닫을 때 slot을 다시 짓기 전에 `crs.read`가 읽은 것을
스냅샷으로 남긴다(`Session.waf_snapshots`, 마이그레이션 0021: `{at, run|closed, waf}`). 가장 최근
것이 `Session.waf`이기도 하므로 닫힌 세션은 학습자의 마지막 설정을 파일까지 알려 준다(한 번도 읽지
못했으면 `file: null`). 읽을 수 없는 WAF는 스냅샷을 남기지 않고 검증도 닫기도 막지 않는다. 학습자는
WAF 터미널에서 튜닝한다. `controls: [paranoia]`를 선언한 레슨은 노트에 같은 `PUT`을 부르는 레벨 조절도 보인다.

`POST /api/sessions/<id>/verify/`는 세션 레슨의 `cases`를 `/attacks/`와 같은
경로로 재생하고 `meta.verify=<run>`과 `meta.mode`(실행할 때의 모드)를 붙이며, 그 실행만 판정한다. sqlmap 케이스는
sqlmap이 덤프한 행(`redteam/tools.py`의 `dumped`)이 세션 스냅샷의 `(username, hash)`와
맞으면(`loot.matched`) 유출이다. 유출은 진단에 보고되고 목표로 인정되지 않는다(판정 D7,
2026-10-13): 학습자 자신의 확인은 잃은 목표가 아니다. 레드가 `/loot/`로 제출한 탈취물은 그대로
인정된다. 막힘은 긍정적 증거가
있을 때만이다: 맞는 행이 없고, sqlmap이 0으로 끝나 `[*] ending` 줄을 찍었으며 중단(트레이스백,
사용자 중단, 존재하지 않는 호스트)이 없고, "all tested parameters do not appear to be
injectable"이라는 sqlmap 자신의 결론이 있으며 덤프한 행이 하나도 없다
(`tools.found_not_injectable`). 스냅샷 계정과 하나도 맞지 않는 덤프는 유출도 막힘도 아닌 판정
불가다. 스냅샷이 없는 세션의 검증은 409로 답하고, 열 때 계정을 읽지 못한 docker board 세션은
503으로 거부하고 닫는다. sqlmap이
회복한 연결 오류는 결론을 무효로 하지 않는다. WAF 뒤에서 그것은 ModSecurity가 board의 500
응답을 끊은 것이다(nginx "header already sent"). 결론 전에 sqlmap을 멈춘 연결 오류는 결론
줄을 남기지 않으므로 판정 불가다. 그 밖은 판정 불가이며 검증에
실패한다. sqlmap 케이스는 `--disable-hashing`으로 돌아, `--batch`가 수락하고 끝나지 않는
pbkdf2 해시 크래킹을 하지 않고 덤프 칸에 원래 해시가 남는다. sqlmap이 보고한 403 횟수는 `meta.forbidden`에 남기고 판정에는 쓰지 않는다.
정상 케이스는 curl이 2xx `http_code`를 보고하면 응답받은 것이다. 통과는 모든 공격이
막히고 모든 정상 케이스가 응답받아야 한다(`platform/lesson.py`). 응답의 `diagnosis`
키는 콘솔이 `strings.html`로 표시하며, TP/FP 라벨은 보여주지 않는다. 응답에는 실행 전에 남긴
스냅샷 `waf`, `mode`, 그리고 그 스냅샷에서 읽은 학습자 조치의 종류 `fix`도 있다(`lesson.fix_class`,
판정 D1): Paranoia Level이 레슨 posture보다 낮으면 `level`(레벨이 없는 파일은 CRS 기본값 1로 본다),
아니면 posture에 없는 예외가 규칙 전체를 빼면 `rule`, 경로 없이 또는 레슨 `waf` 단계의 경로보다 넓은
경로에서 대상을 빼면 `target`, 더한 예외가 모두 그 경로 안의 대상이면 `path_target`, 더한 것이 없으면
null이다. 판정 옆에 알려 줄 뿐 판정을 바꾸지 않는다. `views.REPLAY_MARKS`(`seed`, `verify`, 단계 확인의 `check`, 검증 탭 재실행의
`replay`) 중 하나가 붙은 케이스는 `/score/`(TP/FP/FN/TN, 그것이 일으킨 경보, 게임)와, corp의 효과
관찰이 변화를 귀속시키는 창에서 빠진다. 검증 탭의 재실행은 `POST /attacks/ {case, lesson: true}`로,
guidance 세션에서 lesson의 케이스만 받고 그 케이스를 검증처럼 판정해 `diagnosis`와 `replay` 행을
답한다: 결과, sqlmap의 결론 줄(`tools.conclusions`: 주입 가능·불가 판정과 치명적 중단, 시각 제외, 최대
넷), 선언된 명령, "판정에 쓰지 않음"이라고 적은 403 횟수, 그 케이스의 marker로 좁힌 Kibana `discover`
링크(`kibana.marked`). board의 lesson은
`board-sqli-orderby-sqlmap`, `board-sqli-orderby-sqlmap-tamper`와 정상 케이스 넷을
재생한다. 그중 O'Brien 검색과, `sort` 인자를 과잉 차단하는 튜닝을 떨어뜨리는
`board-normal-sort`(`?sort=-created_at`)가 있다.

콘솔은 화면 다섯 개이고, 모두 `/api/`에서 데이터를 가져온다(사용자가 승인한 정적 시안에 사용자 결정
두 가지를 더했다. `docs/DECISIONS.md` 2026-10-11 콘솔 재설계). 색과 컴포넌트 클래스는
`base.html`과 `platform/console/components.css`에 있고, `bin/build-css`가 `tailwind.css`에
넣는다. 머리글에는 경로 표시, 레인지 상태, 언어 전환이 있다.

- 메인(`/`): 진행 중인 세션과 그 종류(`lesson`/`wargame`), 레슨이 도달한 단계, 열기가 끝났는지
  (`ready`, `Session.ready_at`에서. 그 전까지 "준비 중 n초 / 약 80초"). 시나리오 카드는
  `scenario.yaml`의 category, difficulty, minutes와 `GET /api/wargames/`의 공격 케이스·정상
  케이스·목표 수를 보여 주고, 카드 아래 레슨마다 목표, 난이도, 시간, 선수 레슨과 시작 버튼 셋을 둔다:
  레슨(안내), 연습(`mode: self`), 워게임(안내 없이 full defense). 레슨마다 이 브라우저가 연 세션
  (localStorage의 `fsl-opened-sessions`, 세션·블루 화면이 쓰고 최신순 최대 20개, `?ids=`로 읽음) 가운데
  가장 새 실행을 단계 종류와 PASS/FAIL, 진행 중, 검증 없이 닫음으로 보여 준다. 판정 옆의 단계 종류는 여기서도
  세션 화면에서도 마지막 검증이 돈 모드(`result.lesson.mode`)이고, 그 뒤에 바꾼 세션 모드가 아니다. 지난 세션은 `result`를 보여 준다: 마지막 검증의 PASS/FAIL,
  아니면 빼앗긴 목표 수와 그중 알아채지 못한 수. 결과는 한 번 채점해 그 입력과 함께 저장한다
  (`Session.result_cache`, migration 0018; 입력은 `ended_at`, 힌트 수, 탐지의 마지막 id·행 수·marker가
  있는 행 수, 케이스와 목표의 마지막 id·행 수). 목록은 세션마다 집계 셋만 읽고, 늦은 수집처럼 입력이
  바뀐 세션만 다시 채점한다. 시작이 거부되면 누른 버튼 아래에 이유를 쓰고, 409면
  "열린 세션 닫기"가 열린 세션을 나열해 각각 `ingest/` 뒤 `close/`로 닫는다.
  `GET /api/range/ready/`가 `max_sessions`를 알려 준다.
- 세션(`/session/<id>/`): 머리글 수치(레슨 단계, 빼앗긴 목표, 타깃), 블루·레드 콘솔 카드,
  `GET /api/sessions/<id>/cases/`의 최근 케이스. 종료 후에는 레슨 판정과 마지막 진단, 조치의 종류,
  통과했으면 결과 보고(아래), 그다음 주 점수
  (모든 목표의 빼앗김 여부, 알아챘는지, 감점 난이도 ×1 또는 ×2), 그다음 방어 판단을 평범한 문장으로
  보여 준다: "공격 8건 중 7건을 잡았습니다 · 1건을 놓쳤습니다 (이름)", "정상 요청 4건 중 3건은 통과 ·
  1건을 잘못 막았습니다 (O'Brien 검색)", 그리고 케이스 하나는 경보가 많아도 한 번으로 센다는 것.
  TP/FP/FN/TN과 게임 balance는 API에 남고, 사람이 읽는 문구에는 나오지 않는다(`test_strings.py`).
- 블루(`/blue/<id>/`): 레일(Kibana, WAF, 레드팀)과 창. WAF 창의 배너는 상자(`waf_box`,
  `fsl-<id>-waf`)와 CRS 규칙 폴더(`waf_rules`, `crs.EXCLUSIONS`에서 계산)만 보여 준다.
- 레드(`/red/<id>/`): 위쪽에 목표(한국어 이름은 `objective.<key>`)와 "탈취한 해시 제출", 공격과
  정상으로 묶은 케이스와 마지막 실행 결과, 나머지는 Kali 터미널. 좁은 화면에서는 패널이 세로로
  쌓이고, 레드·블루 화면은 옆으로 스크롤되지 않는다.

guidance 세션에서 레슨 노트는 창의 오른쪽 위에 떠 있고(사이트 툴바나 WAF 배너가 보이면 그 아래, 40 px에 8 px를 더한 위치), 기본은 알약 모양("레슨 노트 · 단계 n/N")으로
접혀 있다. 펼치면 너비 360px에 탭 다섯 개가 있다: 단계(현재 단계, 이전/다음, 건너뛸 수 있는 전체 단계
목록), 목표(요약, 완료 조건, 네 문단), 이론, 힌트, 검증. 목표 한 줄(`<lesson.text>.summary`)은 머리글
아래, 탭 위에 고정된다. 학습자가 펼치거나 단계가 노트 안 컨트롤을
가리킬 때만 펼쳐지고(그런 단계를 벗어나면 다시 접힘), 펼쳐져 있는 동안 탭은 단계를 따라간다(재생·검증은
검증 탭, 나머지는 단계 탭). 이 브라우저가 세션의 블루 콘솔을 처음 열 때(`fsl-lesson-landed-<id>`)는
노트가 목표 탭으로 펼쳐지고, 그 뒤로는 열 때마다 접힌 채로 시작하며, 탭만 보는 사람마다 localStorage
(`fsl-lesson-note`)에, 보고 있는 단계는 `fsl-lesson-step-<id>`에 남고, 메인과 세션 화면이 이것으로
"단계 n/N"을 보여 준다. 진행 자체는 세션의 것이다(`Session.lesson_steps`, 마이그레이션 0020): 단계마다
`reached`, `passed`, `skipped`(시각), `hint`(보인 단계, 0-4), `done_for_me`를 남기고
`GET /api/sessions/<id>/`와 모든 레슨 단계·힌트 응답의 `progress`로 알려 준다. 단계의 기록에는 얻은 것도
실린다: 단계에 도달하면 `command`(연습 모드에서는 없음), 힌트 단계가 3(`lesson.ANSWER`)에 이르면 `answer`,
통과하면 `line`이며 뒤의 둘은 `{en, ko}`이다. `POST /api/sessions/<id>/lesson/steps/<step>/
{state: reached|skipped}`는 단계에 도달했음(alert 확인이 넘어야 할 가장 새 탐지 id도 정함) 또는
통과하지 않고 떠났음을 남긴다. 콘솔은 통과하지 않은 단계에서 다음이나 목록으로 옮길 때 `skipped`를
보내고, 이전이나 통과로 옮길 때는 보내지 않는다. 단계 목록은 `progress`가 통과라고 할 때만 ✓를 붙이고,
통과하지 않고 떠난 단계는 빈 원과 "건너뜀"으로 표시하며, 위에 "N단계 중 n단계 통과"를 보인다. 이론 카드가
`shows`로 가리키는 단계에는 popover에 그 카드를 여는 "왜?" 링크가 있다.

목표 탭은 고객 문의로 시작한다(`<lesson.text>.ticket`). 둘째 줄은 `GET /waf/`에서 읽은 것(Paranoia
Level과 예외 수)만 말한다. 그다음 요약, 그다음 출발점 판정이다: `GET /api/sessions/<id>/`의 `start`가
seed 재생을 검증과 같은 규칙으로 판정한다(board에서는 PL4가 O'Brien 검색에서 실패하고, 그것이 유일한
빨간 줄이다). 목표 탭에는 안내 레슨과 연습 사이의 전환도 있다. 연습(`mode: self`)에서는 응답에 단계 명령이
없고, 힌트와 "대신 해 주기"는 409로 답하며, 콘솔은 단계·힌트 탭, 안내, "위치 보기"를 숨긴다. 목표, 이론,
검증 탭은 남고 학습자가 모든 명령을 직접 입력한다.

이론 탭에는 접힌 카드 다섯 장이 있다(`scenario.yaml`의 `lesson.theory`, 문구는
`<lesson.text>.theory.<card>.title|body`): Paranoia Level, Anomaly Scoring(403에 949110과
920273이 함께 찍히는 이유), 오탐(false positive)을 일으킨 규칙 찾기, PL 낮추기와 rule exclusion의 차이,
`ctl:ruleRemoveTargetById` 한 줄 읽기. 화면의 무언가를 가리키는 카드에는 "위치 보기"가 있어 안내를
그 단계로 옮긴다. 힌트 탭은 이유만 담아 하나씩 접어 둔다(왜 920273인지, 왜 ARGS:q만인지, 왜 900번
파일인지, `scenario.yaml`의 `lesson.hints`, 문구는 `<lesson.text>.hint.*`). 그 아래 접힌 풀이에는 모든 단계의 명령이 순서대로 있고 복사 버튼이
있다. 검증 탭은 케이스 하나를 다시 실행해 실행마다 `replay` 행(최근 다섯)을 Kibana 링크와 함께
보여 주고, 검증을 돌린다. 판정은 PASS 또는 FAIL이고, 막았거나 통과한 케이스는 초록 ✓로, 실패한 진단은
빨간 ✗로, 조치의 종류는 그 아래 회색으로 보여 준다. PASS 뒤에는 검증 탭에 결과 보고가 나온다. 노트에는
예외 입력란이 없다. 레벨 조절과 Suricata 규칙 편집기는 그것을 선언한 레슨에만 나온다.

결과 보고는 `GET /api/sessions/<id>/lesson/debrief/`(열렸든 닫혔든 레슨 세션)이고, Igloo/ASEC 보고서
순서를 따른다: `overview`(마지막 검증의 판정, 실행 횟수, 모드와 조치 종류, 전체 중 통과한 단계, 힌트를
쓴·건너뛴·대신 해 준 단계 수), `evidence`(marker가 seed나 마지막 검증 케이스인 세션 자신의 탐지 최대
20개, 규칙·요청·단계·케이스. Elasticsearch는 읽지 않음), `change`(선언된 시작 posture와 마지막 검증
스냅샷의 비교: 더하고 뺀 예외, 두 레벨, posture에 대해 `crs.rendered`가 쓰는 내용과 제외 파일의 줄 diff),
`cases`(레슨 케이스마다 시작 시와 마지막 검증의 결과), `risk`(조치 종류가 정하는 문자열 키와, 레슨의 공격
케이스만 다시 보냈다는 것). `at`에는 시작과 마지막 검증 시각이 에이전트용으로 있고 콘솔은 보여 주지 않는다.
`debrief_script.html`이 검증 탭과 닫힌 세션 화면에 그린다.

단계는 레슨 정의에 선언한다(`scenario.yaml`의 `lesson.steps`): `id`, `kind`가 `alert`, `click`,
`answer`, `choice`, `waf`, `served`, `replay`, `verify`, `level`, `rules`, `detect` 중 하나인
`check`(`wargames.CHECK_KINDS`, 발견 시 검증. `replay`는 레슨의 케이스와 `held`나 `served`인 `expect`를
밝힌다. 뒤의 셋은 "board의 과정"에 설명한다),
그리고 단계에 따라 `site` 경로, Kibana `query`, 터미널 `command`. 세션 API는 `query`가 있는 단계에
`discover` 링크를 더하고(`kibana.discover_path(..., narrowed)`), 확인은 `kind`만, 그리고 선택지의
`options`와 alert·served 확인이 기다리는 `path`, replay의 `case`만 보인다: `accept` 목록과 정답 규칙은
브라우저에 가지 않는다. 단계의 `command`는 `progress`가 그 단계에 도달했다고 남긴 뒤에만 응답에 있다.
정답 문구(`<lesson.text>.answer.<step>`)와 통과 때 하는 말(`<lesson.text>.line.<step>`)은 Django가
그리지 않는 `strings.html` 끝의 `{% comment %}` 구역에 있고, `console/strings.py`가 읽어 얻은 때에 단계의
`progress` 기록에 싣는다. 그래서 화면의 문자열 표에는 둘 다 없다. 이론·힌트 카드는 처음부터 화면에 있고
일부는 답을 말한다(board 레슨의 카드는 920273과 `ARGS:q`를 말한다): 이론·힌트 탭이 주는 도움이다. board는 여덟 단계이고, 각 단계는
그 확인으로 넘어간다. 이전/다음은 확인을 건너뛰는 길로 남는다:

| 단계 | 어디서 | 확인 |
|---|---|---|
| search: 고객이 되어 O'Brien 검색 | 웹사이트 창 | `alert`: 플랫폼이 최근 600초를 수집하고, 단계의 `reached`보다 새로운, 세션의 브라우징 비밀값이 붙고 경로에 `O'Brien`이 든 기록이면 통과 |
| find: Kibana에서 그 요청 찾기 | Kibana, 필터 버튼 `url : *Brien* and status : 403` | `click`: 그 행의 펼치기 버튼 |
| rule: 막은 규칙 번호 | 답 입력란 | `answer`: `920273`. `949110`이면 "점수 합계 규칙" 안내 |
| target: 무엇이 걸렸나 | 선택지 넷 | `choice`: `ARGS:q`(나머지는 주소, 쿠키, 헤더) |
| exclude: 예외 적용 | WAF 터미널, "터미널에서 실행" | `waf`: WAF 파일에 920273 `ARGS:q` `/search/`가 있고, `meta.check`를 붙여 다시 보낸 O'Brien 케이스가 2xx(reload가 적용됨). 폴링은 파일 버전마다 한 번만 다시 보냄 |
| retry: O'Brien 다시 검색 | 웹사이트 창 | `served`: 창에 O'Brien 검색이 보이면 같은 케이스를 `meta.check`를 붙여 다시 보내 2xx여야 함 |
| sqlmap: sqlmap은 여전히 막히나 | popover의 "board-sqli-orderby-sqlmap 다시 실행" | `replay`: 누를 때만(약 15초, 폴링하지 않음) 케이스를 `meta.check`를 붙여 다시 보내 막혔으면 통과. 유출은 실패이고, 결론 없는 실행은 따로 그렇다고 말함(`lesson.check.inconclusive`). 응답에 `replay` 행이 있음 |
| verify: 공격은 여전히 막히나 | 노트의 검증 탭 | `verify`: 검증 PASS |

모든 확인은 플랫폼이 판정한다: `POST /api/sessions/<id>/lesson/steps/<step>/check/`(답과 선택지는
`{answer}`, 배경 폴링은 `{poll: true}`)가 `passed`를 남기고 `{passed, reason, hint, hints, progress}`로
답한다(`waf` 확인은 `fix`, `replay` 확인은 `replay`도). `reason`은 값이 딸린 `strings.html` 키다. `click`은 콘솔의 말을 믿는다. 폴링이 아닌 실패한
확인은 틀린 것으로 세고, 두 번이면 그 단계의 힌트 단계를 올리고 힌트를 기록한다.

확인은 저절로 돈다. 확인 버튼은 없다. `alert`와 `waf`는 그 단계가 보이고 탭이 보이며 세션이 열려 있는
동안 5초마다(세션이 닫혔는지는 페이지가 30초마다 세션을 다시 읽어 안다), `served`는 웹사이트
창에 그 단계의 경로가 보일 때 확인한다. popover의 상태 줄이 "확인 중…", 그다음 아직 빠진 것("아직 920273
예외가 파일에 없습니다", "파일에는 있지만 불러오지 않았습니다"), 통과하면 "✓"와 찾은 것
(`<lesson.text>.ok.<step>`)을 말한다. 1.2초 뒤 다음 단계로 넘어가 그 단계의 한 줄(`<lesson.text>.line.<step>`)을
보이고, 마지막 단계에서는 "레슨을 마쳤습니다". 틀린 답은 무엇이 틀렸는지 말한다. 최근 수집(`within`)은 창의 가장 새 기록부터 읽고 잘림을 기록하지 않는다.
검증 한 번만으로도 기록이 5000개를 넘기 때문이다.

터미널 단계의 명령은 절대 경로만 쓴다. 다시 연 ttyd는 새 셸에서 시작하기 때문이다. 손으로 쓰는 규칙은
id 10100~10199를 쓴다. `crs.rendered`는 10000~10020(paranoia `SecAction`과 최대 20개의 예외)을 쓰므로
둘은 겹치지 않는다. 명령은 파일을 `.bak`으로 복사하고, 앞서 쓴 `"id:10100,` 줄을 빼고, id 10100으로
예외를 덧붙이고, 파일 마지막 줄을 보여 준 뒤, `nginx -t`가 통과할 때만 `nginx -s reload`를 실행한다.
통과하지 못하면 `.bak`을 되돌려 놓으므로 WAF가 nginx가 거부한 파일로 남지 않는다. 두 번 실행해도 한 줄만
남는다. 명령은
"명령 보기" 아래 접혀 있다. "터미널에서 실행"은 필요하면 WAF 창을 열고 ttyd의 `term`을 기다린 뒤
`term.paste(command + "\n")`, 이어서 `term.input("\r")`을 부른다. bash는 bracketed paste의 줄바꿈을
글자로 두기 때문이다.

도움은 단계마다 사다리를 오른다(화면의 `<lesson.text>.nudge.<step>`, 정답은 단계의 `progress.answer`): 귀띔, "빨간 상자가 있는 곳을 보세요",
정답, "대신 해 주기". 힌트 버튼이나 틀린 답·실패한 확인 두 번에 한 칸 오른다. 누를 때마다
`POST /api/sessions/<id>/lesson/hints/ {step, level: "hint"}`가 그 단계의 `hint`를 올리고, 처음 것은
`Session.hints`에 기록된다(migration 0017; 레슨에 없는 단계나 level은 400, 닫힌 세션은 409). 한 단계에서
60초가 지나면 힌트 버튼은 "힌트가 있습니다"라고만 말하고, 학습자가 누르기 전에는 아무것도 기록하지
않는다. "대신 해 주기"는 `POST /api/sessions/<id>/lesson/steps/<step>/do/`이며 `done_for_me`와 `hints`의
`{step, level: "do"}`로 기록된다: 플랫폼이 답을 넣거나, 현재 Paranoia Level로 `crs.apply`를 거쳐 예외를
더하거나, 케이스를 다시 보내거나, 클릭을 표시한 뒤 그 단계를 판정한다. 단계의 경로로 사이트 열기,
걸러 낸 Kibana를 열고 첫 행의 펼치기 누르기, 검증 실행은 콘솔이 한다. 대신 해 준 단계는
`GET /api/sessions/<id>/`의 `hints`와 `progress`로 단계 목록에 표시되고, `result.lesson.helped`(`["hint", "do"]` 중
있는 것)로 메인 화면과 닫힌 세션 화면의 PASS·FAIL 옆에 "힌트 사용" / "대신 해 주기 사용"이 붙는다.

"직접 해보기"(단계 목록 아래 체크박스, `fsl-lesson-stretch`)는 필터 버튼과 실행 버튼을 없애고 명령을
펼쳐 둔다: 학습자가 KQL을 쓰고 규칙을 직접 입력한다. 확인은 같다.

각 단계가 가리키는 곳은 `scenario.yaml`에 있는 그 단계의 `point`이고(`panel`, 대체용 `first`가 붙을 수
있는 `kibana`, 또는 `pane`; `opens`; `tab`), 그래서 콘솔은 board의 단계도 Kibana selector도 이름으로
알지 않는다. 빨간 상자는 모든 단계에서 처음부터 그려진다. 단계는
필요한 창을 밝힌다(`opens`: 사이트, Kibana, WAF). 그 창이 보이지 않는 동안 상자는 레일 버튼에 있고 popover는
"왼쪽 웹사이트를 여세요"(또는 Kibana, WAF)만 말한다. 창이 보이면: 사이트 주소창, 같은 출처 Kibana 프레임의
`data-test-subj`(`docTableExpandToggleColumn`, `field-rule`, `field-transaction.messages.details.data`와
대체로 `field-rule`), WAF 창 전체, 노트의 검증 버튼. 다른 출처인 사이트 프레임 안은 절대 찾지 않는다.
현재 단계의 말과 이전/다음은 popover 한 곳에만 있다. 노트의 단계 탭은 단계 목록과 현재 단계의 "진행 중"·상태만
보이고, popover를 닫은 뒤에만 "가이드 다시 보기"를 보인다. popover는 driver.js 방식이다: 대상에 화살표로 붙어 아래·위·왼쪽·오른쪽에 놓이고(주소창처럼 480 px보다 넓은 대상이면 그 오른쪽 끝 아래), 펼친
노트와는 겹치지 않으며, 터미널 단계에서는 창 오른쪽 아래에 놓인다. 상자는 `pointer-events: none`이고
매 애니메이션 프레임마다 다시 놓인다. 약 2초 동안 대상이 없으면 popover가 어디를 볼지 알려 준다. 이론
카드 다섯 장과 힌트(이유, 그다음 접힌 풀이)는 경로 밖, 노트에 남는다.

### board의 과정

`wargames/board/scenario.yaml`은 `docs/superpowers/specs/2026-10-13-blue-team-course-design.md`(판정
D1-D11)의 Package 2를 권장 경로 하나로 선언한다. 순서는 열려 있고 건너뛸 수 있다:

| order | 레슨 | defense | 판정 | 풀 것 |
|---|---|---|---|---|
| 0 | `console-tour` | `full` | 단계 | WAF가 막는 요청을 보내고, 기록을 찾아, 규칙을 말하기 |
| 1 | `read-the-block` | `minimal` | 단계 | O'Brien을 막은 규칙과 그 규칙이 걸린 파라미터 말하기 |
| 2 | `waf-exclusion` | `minimal` | 검증 | 좁은 예외(위) |
| 3 | `choose-the-level` | `minimal` | 검증과 레벨 | 예외 없이, 정상 요청을 모두 통과시키고 sqlmap 두 변형을 막는 가장 높은 Paranoia Level |
| 4 | `ids-signature` | `ids` | 탐지(D2) | sqlmap `?sort=` 두 변형에는 경보, `?sort=-created_at`에는 경보 없는 Suricata 규칙 |
| 5 | `ids-body-xss` | `full` | 탐지(D2) | 본문의 댓글 XSS에는 경보, 정상 댓글에는 경보 없음 |
| 7 | `assessment` | `minimal` | 검증 | 안내 없이(`mode: self`, 단계 없음) O'Brien·한국어 검색 통과, sqlmap 두 변형 차단 |

레슨 6(corp)은 만들지 않았다(`docs/STATE.md` backlog 0).

단계에 `verify`가 없는 레슨은 단계만으로 판정한다: `POST /verify/`는 400으로 답하고 세션 응답은
`verifies: false`라고 알려, 콘솔은 검증을 숨기고 목표에 "이 세션의 기록으로 답함"이라고 적는다. 단계가 없는
레슨(평가)은 검증으로 판정한다.

`answer` 확인은 `accept` 목록 대신 기록에서 정답을 읽을 수 있다: `of: rule` 또는 `of: target`과 그 요청의
`path`(학습자 자신의 요청이면 `marker: browse`). 플랫폼은 최근 600초를 수집하고, 그 요청에 대한 세션의
ModSecurity 탐지를 모아 CRS 합계 규칙(949, 959, 980으로 시작하는 id)을 빼고, 남은 `ruleId` 또는 각 규칙이
걸린 변수(`details.match`의 "against variable" 뒤, 또는 `details.data`의 "found within X:"나 "X=";
`lesson.read_from`)를 정답으로 받는다. 대소문자는 가리지 않는다. 기록이 없으면 사유는
`lesson.check.unrecorded`이고, "대신 해 주기"는 첫 정답을 넣는다.

`choose-the-level`은 `solved_at: {paranoia: 2}`(서버에만 둠)와 `controls: [paranoia]`를 선언한다. `level`
단계는 동작 중인 WAF가 posture보다 낮은 레벨이고 posture에 없는 예외가 없을 때 통과한다
(`lesson.level_refused`; 사유 `.unchanged`, `.excluded`). 대신 해 주기는 `solved_at`을 적용한다. 검증은 모든
케이스가 통과하고, 스냅샷에 더한 예외가 없고, 레벨이 `solved_at`보다 낮지 않을 때 통과한다
(`lesson.unsolved`: `lesson.diag.level_low`, `lesson.diag.excluded`). 모든 케이스를 통과하는 더 높은
레벨도 통과다. `board-normal-search-korean`이 레슨에 있을 때 측정한 답이 PL2다(`docs/DECISIONS.md` 2026-10-13).

`ids-signature`와 `ids-body-xss`는 `detected_by: suricata`와 `controls: [rules]`를 선언한다. 완료는
탐지다(판정 D2): 검증은 케이스를 모두 보낸 뒤, 모든 공격 케이스에 그 출처의 탐지가 생기거나
`FSL_LESSON_ALERT_WAIT`(30초, `FSL_LESSON_ALERT_POLL`마다 확인)가 끝날 때까지 세션의 탐지를 읽는다. 공격
케이스는 경보 하나가 케이스의 `expect`를 언급하면 `detected`(`scoreboard.corroborated`, 같은 실행의 정상
케이스에도 난 시그니처는 뺀다), 언급 없이 경보만 났으면 `uncorroborated`, 경보가 없으면 `missed`이고, 정상
케이스는 `quiet` 또는 `alerted`다. 케이스 행마다 `verdict`(TP, FN, FP, TN)도 붙는다. PASS는 모든 공격이
detected이고 모든 정상 케이스가 quiet일 때다. 재생은 `/score/`에 들어가지 않고 목표에도 표시하지 않으며,
ModSecurity 탐지는 세지 않는다. `rules` 단계는 센서 파일(`GET /api/rules/`)에 posture의 규칙 파일에 없는
sid가 생기면 통과한다(`suppress.sids`). 대신 해 주기는 단계의 `rule`(서버에만 둠)을 덧붙여 적용한다.
`detect` 단계 `{case, expect: alert|quiet}`는 케이스를 `meta.check`로 표시해 보내고, 검증처럼 기다린 뒤(`quiet`는
끝까지 기다린다) `detected` 행으로 답한다: 결과, 판정, 경보 시그니처, 그 표시가 붙은 경보로 좁힌 Kibana
링크(`kibana.sensed`). 실패 사유는 `lesson.check.missed|uncorroborated|alerted`다.

규칙 편집기(D3)는 `GET /api/rules/?session=<id>`로 읽고, `POST /api/rules/validate/`로 확인하고, 읽어 온
버전에 대해 `POST /api/rules/apply/`로 쓴다. 검사는 `errors`로 답한다: 거부한 모든 센서의 출력에서
Suricata `Error`가 든 줄들이고, `output`은 그 줄이 가장 많은 거부 센서의 출력이다. OPNsense edge의
Suricata는 syslog로만 로그를 남기므로(템플릿에 console 출력이 없다) `-T` 출력에 오류 줄이 없고, wargame
호스트의 estate 센서가 그 줄을 출력한다.

## 점수는 어떻게 계산되는가

목표. board는 `loot_verified` 대상이다. `wargames/board/objectives.yaml`이
비밀(`auth_user`의 사용자 이름과 비밀번호 컬럼, `/internal/auth-users`에서 읽음)과,
공격자가 그중 얼마를 가졌는지에 따른 세 단계를 정한다: 해시 하나(난이도 2), `admin`
계정의 해시(4), 모든 계정의 해시(5). 공격자는 해시를 탈취해
`POST /api/sessions/<id>/loot/`로, 레드 콘솔의 loot 제출 패널(`loot_verified`
시나리오에서만 표시)에서 제출한다. 플랫폼은 제출된 `(username, hash)` 쌍이
세션 시작 시점 스냅샷과 정확히 일치하고, 세션이 악성 케이스를 하나 이상 발사한 뒤에만
단계를 인정한다. 공격 결과에 대한 플랫폼 자신의 판단으로 목표를 인정하지 않는다.
ground truth는 대상 시스템 자체의 기록이며, 탐지 장비는 이를 보지 못한다.

인정된 단계는 제출 시각이 찍힌 Objective 행이 된다. 제출이 악성 케이스(`case_id`)를
지정하면 창은 그 케이스 시작 100ms 전부터 종료 100ms 후까지이고, 아니면 제출 2분
전부터 100ms 후까지다.

스냅샷은 세션 시작 시 한 번만 만든다. docker에서는 board 계정을 읽지 못하거나 비어 있으면
세션을 503으로 거부하고 닫는다. OpenStack에서는 세션이 스냅샷 없이 생성되고, 그 세션의 `POST /api/sessions/<id>/loot/`는 409로 답한다. 그 뒤로는 board를
읽지 않는다: `GET /api/wargames/<id>/objectives/`는 `objectives.yaml`의 단계를
나열하고, `GET /api/sessions/<id>/objectives/`는 저장된 행을 보고한다.
`POST /api/sessions/<id>/objectives/`는 관찰을 수행하며, `loot_verified` wargame에서는
아무것도 하지 않는다.

corp는 `effect_observed` 대상이다: 공격자의 제출 없이, 대상 시스템이 자체 DB에 커밋한
행으로 채점한다. `wargames/corp/objectives.yaml`이 읽기 경로(`estate://corp-db`,
scope `wp_state`)와 세 단계를 정한다: rogue administrator(`rogue_admin`, 난이도 5),
자가 가입이 열린 사이트(`option_flip`, 4), 무단 콘텐츠 작성(`content_write`, 3). 세션
시작 시 플랫폼은 기존 관리자, 감시 대상 `wp_options`, 공개된 글을 corp-db에 대한 읽기
전용 `mysql` SELECT로 스냅샷한다(`platform/api/effect.py`). 이 명령은 네트워크가 아니라
`runner("corp-db")`로 실행한다. `POST /api/sessions/<id>/objectives/` 때는 corp-db의
바이너리 로그를 `mysqlbinlog`로 읽어, 커밋된 변경(스냅샷에 없던 사용자에게 준
`wp_usermeta` 관리자 권한, `users_can_register`/`default_role`의 `wp_options` 변경,
새로 쓰거나 덮어쓴 `wp_posts` 행) 중 시각이 악성 케이스의 창 안에 드는 것마다 단계를
인정한다. board와 마찬가지로 탐지 장비는 이 읽기를 보지 못한다.

탈취된 목표는 실행 구간이 목표의 창과 겹치는 악성 케이스에 귀속되며, 여럿이면 가장
늦게 시작한 케이스에 귀속된다. 그 케이스가 탐지되었을 때만 목표도 탐지된 것으로 세고,
어떤 케이스와도 겹치지 않는 목표는 미탐으로 센다. 귀속은 시간만으로 이루어진다:
케이스의 `takes:` 필드는 레드 콘솔에 표시되지만 scoring은 읽지 않는다.

점수의 `objectives` 블록에서 `coverage`는 전체 난이도 대비 탐지된 난이도이며, 탈취된
것이 없으면 `null`이고, `false_positives`는 FP다. `damage`는 탐지되지 않은 난이도에
탐지된 난이도의 절반을 더한 값이며, 이것이 탐지되지 않은 손실을 두 배로 세는 방식이다.

탐지. 케이스는 케이스마다 선언된 두 전략 중 하나로 경보에 매칭된다:

- `marker`: 경보가 케이스의 `X-FSL-Case` 값을 담고 있다;
- `window`: 경보의 출발지 주소가 케이스와 일치하고, 경보 시각이 케이스의 시작과 끝
  사이(양쪽 2초 여유)에 있다.

한 전략에서 다른 전략으로의 폴백은 없다. marker를 잃은 marker 케이스는 window로
보완되지 않고 미탐으로 드러나야 한다. 터미널 케이스는 둘 다 싣는다. score
엔드포인트의 `?correlation=marker` 또는 `?correlation=window`는 전략을 강제하며, 다른
값은 400이다. 이 파라미터를 넘기는 콘솔 페이지는 없고(`session.html`은 파라미터 없이
`/score/`를 요청한다), 두 전략의 비교는 전략마다 엔드포인트를 한 번씩 호출해서 한다.
불일치는 방어가 아니라 채점 방법에 대한 정보다.

각 `per_case` 항목은 `expect`와 `corroborated`를 담는다. `corroborated`는 `expect`가
대소문자 무시로 매칭된 경보 중 하나의 시그니처에 나타나면 true다. 같은 세션에서 정상
케이스에도 매칭된 시그니처는 세지 않는다. 케이스에 `expect`가 없으면 `null`이며,
터미널 케이스는 항상 그렇다: 레드 콘솔은 `expect`를 보내지 않는다. 탐지되었으나
corroborated되지 않은 케이스는 `score.warning.wrong_reason`을 추가한다.

케이스의 `expect`는 발사 시 케이스와 함께 저장되므로, 케이스 파일을 수정해도 끝난
세션을 다시 판정하지 않는다. 마이그레이션 0009 이전에 기록된 행은 저장된 `expect`가
없어 현재 케이스 파일로 판정된다. 경보 심각도와 규칙 유형은 쓰지 않는다.

게임. 점수의 `game` 블록은 세션이 종료될 때까지 `{"revealed": false}`다. 종료 후에는
네 구성 요소와 그 가중치, 그리고 balance를 담는다:

- speed (0.25): 악성 케이스마다, 첫 매칭 경보가 시작 10초 이내면 1, 120초 이상이면
  0, 그 사이는 선형; 평균;
- accuracy (0.30): 재현율 빼기 오탐률, 하한 0;
- coverage (0.20): 공격받은 단계 대비 탐지된 악성 케이스가 있는 공격 단계
  (`platform/lifecycle.py`)이며, 공격받은 단계가 없으면 0. `objectives` 블록의
  `coverage`와는 다르다;
- response (0.25): 차단된 악성 케이스 비율에서 차단된 정상 케이스 비율을 뺀 값.
  어떤 케이스에 `meta["blocked"]`가 생기기 전까지는 `null`이고 나머지 가중치가
  재정규화된다. 아직 이 값을 설정하는 코드는 없다.

`attacker`는 탈취된 목표의 난이도 합이며, 탐지된 것은 절반으로 센다: `damage`와 같은
합이다. `defender`는 구성 요소의 가중 평균에 탈취된 난이도를 곱하고 FP마다 1을 뺀
값이다. `balance`는 `defender - attacker`다. 탈취된 것이 없으면 balance는 마이너스
FP다. 가중치와 체류 시간은 v1 기본값이다
(`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`).

score 엔드포인트는 읽기 전용이며 이력을 보관하지 않는다.

## 결정

- wargame마다 케이스 파일 하나에 공격과 정상 트래픽을 함께 둔다: board는
  `redteam/cases/board.yaml`, corp는 `redteam/cases/corp.yaml`. 파일을 나누면 정상
  케이스를 빠뜨리기 쉽다. CLI는 `--cases`가 다른 파일을 지정하지 않으면 `board.yaml`을
  읽고, 그 파일명과 `case_file`이 일치하는 시나리오의 세션을 연다(알 수 없는 파일이면 board).
- harness는 재작성된 경로를 보내지 않는다. `requests`는 `/static/../../etc/passwd`를
  `/etc/passwd`로 바꾼다. 그대로 보내면 실제로 나가지 않은 공격을 기록하고 harness의
  실패를 방어의 실패로 채점하게 된다. 퍼센트 인코딩 차이는 허용한다.
- 시작하지 못하는 도구는 예외를 던지고, 0이 아닌 값으로 종료한 도구는 센다. sqlmap은
  아무것도 찾지 못하면 0이 아닌 값으로 종료하지만 트래픽은 이미 나갔다.
- Suricata는 Docker 호스트마다 의미가 달라지는 호스트 네트워킹 대신 WAF의 네트워크
  네임스페이스를 공유한다(`network_mode: service:waf`). WAF의 인터페이스가 모든 요청의
  양쪽 구간을 실어 나른다.
- Kibana는 compose에 있으며, 읽기 전용 역할이 아닌 전체 권한으로 플랫폼이 적재하는
  같은 Elasticsearch를 읽는다. 플랫폼의 8000번 포트의 `/kibana/`로 접근하며 자체
  포트는 publish하지 않는다. 블루 콘솔이 이를 프레임에 띄운다. 기동 시
  `platform/kibana.py`가(백그라운드에서, Kibana에 닿지 않거나 502/503/504를 답하는 동안 재시도하고
  다른 HTTP 오류는 상태와 본문을 한 번 알리며)
  `deploy/kibana/objects.ndjson`을 overwrite로 가져온다: `@timestamp` 기준 data view
  `fsl-logs-*`(runtime field로 Suricata/ModSecurity의 같은 의미 필드 쌍을 한 열로 합침:
  `rule`, `rule_id`, `source_ip`, `destination`, `url`, `status`), "FSL alerts" 검색,
  "FSL overview" 대시보드. `defaultRoute`를 그 검색으로 정한다. data view가 있으면
  Kibana의 Welcome 화면이 나오지 않는다. `GET /api/sessions/<id>/`는 `discover`를
  돌려준다. `fsl-logs` data view 위의 저장되지 않은 Discover 상태로, alert 검색의 열,
  쿼리, 정렬을 쓰고 docker에서는 세션 인덱스(`_index : fsl-logs-<id>-*`)와 세션 구간으로
  좁힌다. ELK 창이 이를 연다. 저장된 검색에 쿼리를 덮어쓰면 Kibana가 "Unsaved changes"를
  붙이므로 그렇게 하지 않는다. 창이 로드되기 전에 블루 콘솔이 같은 출처의 localStorage에
  Kibana의 첫 방문 안내를 본 것으로 표시한다(`discover:docExplorerUpdateCalloutClosed`,
  `discover:docExplorerCalloutClosed`, `data.noDataPopover`).
- Elasticsearch는 512MB 힙의 단일 노드로, 전체 스택이 Docker 기본 메모리 한도에
  들어간다.
- 없는 데이터는 0이 아니라 오류로 처리하며, 예외를 명시한다. 닿을 수 없는
  Elasticsearch나 substrate, 읽을 수 없는 규칙 파일은 503으로 답한다. OpenStack의 세션 생성은
  대상 시스템에 닿지 못해도 진행한다(세션은 스냅샷 없이 시작하고 board의 `loot/`는
  409로 답한다. docker의 board 세션은 503으로 거부한다). 케이스 발사나 기록, 종료는 대상 시스템을 읽지 않는다(발사는 출발지나
  도구 때문에 substrate가 필요하면 503으로 답한다). ingest 내부의 억제 복원과 경보의
  구간·호스트 배치(빈 값으로 돌아옴)는 substrate에 닿지 못해도 진행하므로, 라운드는
  시작하고 멈출 수 있다. 분모가 0인 비율은 null이 아니라 0.0이다: 정밀도, 재현율, F1,
  FPR, 그리고 게임의 speed, coverage, accuracy. `objectives` 블록의 `coverage`만
  null이다.
- 점수는 보증할 수 없는 부분을 경고로 표시한다. 정상 케이스가 없거나(`no_benign`),
  marker 케이스가 있는데 어떤 경보에도 marker가 없거나(`no_marker`), 출발지 주소가 없는
  window 케이스가 있거나(`no_source_ip`), 탐지되었으나 corroborated되지 않은 케이스가
  있거나(`wrong_reason`), Elasticsearch의 hit가 ingest가 읽은 것보다 많으면
  (`truncated`) 경고를 담는다.
- 콘솔에서 발사한 케이스는 HTTP 연결마다 케이스 하나를 보내고, CLI는 한 실행 동안
  연결 하나를 유지한다. 당시의 케이스 세트(12개)로 측정했을 때 두 방식의 점수와
  케이스별 경보 수가 같았다. 수용 테스트는 CLI를 구동하므로 연결 공유 경로도 테스트된다.

## OpenStack

이 구축은 `docs/STATE.md` 백로그의 OpenStack 항목을 그 순서대로 따른다. 구축된 것은
아래에 설명하며 클라우드 또는 fake에서 실행해 확인했다. 남은 것은 이 절 끝에 있다. 근거는
`docs/STATE.md`("Decided on 2026-09-30"),
`docs/superpowers/specs/2026-09-30-openstack-range-placement.md`,
`docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`에 있고, 이 절은 구조만
기록한다.

클라우드는 ML2/Open vSwitch로 kolla-ansible 2026.1을 돌리는 KVM 컴퓨트 노드 하나(8
vCPU, 64 GB)다. 레인지는 프로젝트 `fsl-range`에 있고, member 역할 사용자 `fsl-range`가
구동한다. Horizon은 사용자에게 보이지 않는다.

클라우드마다 다른 값은 `deploy/openstack/cloud.yaml`에 있다(커밋된 `cloud.example.yaml`을
복사한 것으로, git이 무시하고 비밀은 없다): identity, 네트워크와 MTU, 베이스 이미지,
zone, flavor, 키, OPNsense 릴리스, 플랫폼의 스택과 ref. `platform/range/cloud.py`가
검사해 문제마다 키를 들어 보고하고, `bin/platform-rebuild`와 `bin/cloud`가 이 파일로
openstack CLI와 Heat 파라미터를 움직이며, 스택이 이를 플랫폼의 `openstack.env`에 쓴다.
`bin/cloud up`은 스택을 만들고 fabric, images, slot, configure를 부른 뒤
`/api/range/ready/`가 ready가 될 때까지 기다린다. `bin/cloud down`은 키를 보관하고
저장소를 백업한 뒤 slot, fabric, 남은 이미지 빌더, 스택을 지운다. `*_FAILED` 스택은
`up`이 (빌더부터) 지우고 다시 만들며, `down`이 지운다.

### 구축됨: 플랫폼 VM

`deploy/openstack/platform.yaml`은 Heat 템플릿이며 다음을 만든다:

- 네트워크와 서브넷 `fsl-platform`;
- 외부 네트워크로 가는 라우터와 floating IP(`network.address`가 있으면 프로젝트가
  이미 가진 floating IP를 연결만 하므로 스택을 지워도 남는다);
- 모든 주소에 tcp/22, tcp/8000, ICMP를 여는 보안 그룹;
- config drive를 가진 Nova 서버 `fsl-platform`.

기본값은 없다. 모든 파라미터는 `deploy/openstack/cloud.yaml`에서 온다(아래, 그리고
`docs/OPENSTACK.md` §4).

cloud-init은 `docker.io`, `docker-compose-v2`, `git`을 설치하고, 4GB 스왑을 추가하고,
Docker의 MTU를 기본 브리지(`mtu`)와 compose 것을 포함한 모든 새 브리지
네트워크(`default-network-opts`)에 대해 Neutron 네트워크 값으로 맞추고, `ref`의
`repository`를 `/opt/fsl`로 클론하고, `/opt/fsl/.env`에 `FSL_IMAGE_TAG=<체크아웃의
커밋>`을 쓰고, GeoIP 데이터베이스를 받고(`bin/fetch-geoip`, 자격 증명 불필요: Elastic의
GeoIP 엔드포인트는 URL로 약관에 동의하면 누구에게나 GeoLite2를 준다), `ubuntu`를
`docker` 그룹에 추가한다. systemd 유닛 `fsl-platform.service`는 부팅마다
`compose.yaml`과 `session.yaml`의 이미지를 pull하고 `docker compose -f
/opt/fsl/compose.yaml up -d`를 실행한다. 빌드는 하지 않는다. pull이 실패해도 유닛은
멈추지 않으며(`ExecStartPre=-`), 그때 `up`이 없는 이미지를 체크아웃에서 빌드한다.
`bin/platform-rebuild`는 먼저 ghcr.io를 확인해 이를 피한다.

따라서 compose 컨트롤 플레인만 Nova VM 하나 안에서 돈다. OpenStack substrate에서는 그 안에 세션 스택이 뜨지 않고, board의 ground truth는 wargame 호스트의 관리망 주소에서 읽는다. cloud-init이 `FSL_PUBLISH`를
VM의 고정 주소로 설정하므로 8000이 그 주소에 publish되고 보안 그룹에서도
열려, 브라우저가 floating IP로 콘솔에 접근한다. `FSL_SYSLOG_PUBLISH=0.0.0.0`은
엣지의 syslog를 받기 위해 5140/udp를 모든 주소에 publish한다. 9200은 loopback에
남는다.

템플릿의 파라미터는 모두 `deploy/openstack/cloud.yaml`에서 온다(`bin/platform-rebuild`,
`bin/cloud`). 템플릿에는 기본값이 없다. cloud-init은 그 값들을 `FSL_OPENSTACK_*`와
`FSL_OPNSENSE`로, 그리고 `_PROJECT`(스택 자신의 프로젝트), `_SSH_USER=ubuntu`,
`_SSH_KEY=/data/ssh/id_ed25519`를 모드 0600으로
`/root/openstack.env`에 쓰고, git이 무시하는 `/opt/fsl/openstack.env`로 옮긴다.
비밀번호는 템플릿에 없다: Nova가 user data를 보관하고 메타데이터 서비스가 레인지
컨테이너를 포함해 VM에서 도는 모든 것에 이를 제공하기 때문이다. `bin/platform-rebuild`가
VM이 뜬 뒤 ssh로 `FSL_OPENSTACK_PASSWORD`를 덧붙이고, 레인지 ssh 키도 같은 방식으로
플랫폼 데이터 볼륨에 쓴다(`README.md`). 플랫폼 서비스는 이 파일을
`env_file`(`required: false`, `format: raw`)로 읽으므로, compose는 보간이나 따옴표
제거 없이 그대로 전달한다.

VM 위의 플랫폼은 OpenStack 어댑터(cloud-init이 쓴
`FSL_SUBSTRATE=range.openstack.connect`)를 쓰고, `range/fabric.py`가 계획한
`/api/range/fabric/`로 레인지 네트워크를 직접 만든다: 선언된 출발지마다 서브넷 하나를
가진 `internet` 네트워크(DHCP 끔), `cloud.yaml`이 정한 CIDR의 `estate`와 게이트웨이
없는 `mgmt`(서로, 플랫폼 네트워크, Docker 기본 로컬 주소 풀(172.17.0.0/16~172.31.0.0/16,
192.168.0.0/16; moby `daemon/libnetwork/ipamutils/utils.go`), `compose.yaml`의 네트워크,
선언된 출발지와 겹치면 로더가 거부한다), 그리고
`/data/ssh/id_ed25519`의 키로 만든 키페어 `fsl-platform`. 플랫폼은 첫 fabric POST 때
그 키가 없을 때만 만든다. `bin/platform-rebuild`는 운영자 컴퓨터에 사본을 두고 새
플랫폼 VM마다 써 넣으므로, 교체된 VM도 키페어와 레인지 VM들이 신뢰하는 키를 유지한다. `describe()`는 각
출발지를 인터넷 네트워크의 해당 서브넷에 CIDR로 연결한다. VM의 라우터는 자신의
서브넷만 붙이며, 플랫폼은 `mgmt` 포트(아래)로 레인지 호스트에 접근한다.

호스트는 골든 이미지로 부팅하며, 골든 이미지는 `/api/range/images/`로 만들고
`range/images.py`가 계획한다. `declaration.yaml`의 `hosts:`가 VM마다 설정 스크립트와
필요한 파일을 정한다. 플랫폼은 이를 빌더의 user data에 담아, 빌더를 자신의
네트워크(라우터가 있는 쪽)에서 부팅하고, 설정이 끝날 때 출력하는 줄을 빌더 콘솔에서
읽은 뒤 빌더를 멈추고 스냅샷한다. 이미지는 번들의 digest를 담으므로, 스크립트를
수정하면 조용히 낡은 이미지가 아니라 다른 번들의 이미지로 드러난다. 클라우드에 올려 둔
이미지는 손대지 않은 Ubuntu 24.04 클라우드 이미지 하나(`compute.base_image`)이고,
모든 빌더가 이것으로 부팅한다. `uploads`가 있는 호스트(엣지)는 다르다. 빌더는
자격 증명을 받지 않는다. 디스크를 만들어 플랫폼 네트워크에 HTTP로 내놓고, 디스크의
SHA256을 콘솔에 출력한다. 플랫폼이 디스크를 가져와 SHA256을 확인한 뒤 Glance 레코드를
만들고 자신의 토큰으로 올린다. Glance가 active라고 하면 빌더는 스냅샷 없이 지워진다.
엣지 빌더는 OPNsense nano 이미지를 내려받아 그 SHA256과 릴리스 키의 SHA256을
`cloud.yaml`과 대조하고, 서명을 확인하고, QEMU로 한 번 부팅해 설정 가져오기 프롬프트에
답해 `deploy/opnsense/config.xml`로 시작하게 한 뒤, `qemu-img`로 바꿔 내놓으면
플랫폼이 `fsl-opnsense-<version>`으로 올린다(`deploy/opnsense/build.sh`, `importer.py`).

wargame마다 이미지를 두지 않는다. 호스트 이미지 하나, `fsl-wargame-host`
(`deploy/wargame-host/setup.sh`)가 기본 이미지에 `docker.io`와 `docker-compose-v2`를
더한 것이고, 선언 항목이 나열한 모든 wargame(`wargames: [board, corp]`)을 docker
substrate가 돌리는 GHCR 컨테이너로 돌린다. `range/wargame_host.py`가 각
`wargames/<id>/compose.yaml`을 호스트용으로 렌더링해 번들에 넣는다: `build:`와 세션
네트워크를 빼고, 컨테이너 이름을 서비스 이름으로 하고, 이미지 참조에 플랫폼의
`FSL_IMAGE_TAG`를 쓰고, WAF가 프록시하는 포트(`publish: {board: 8000, corp-wp: 80}`)를
publish한다. `daemon.json`은 Docker 브리지에 테넌트 MTU를 준다. 인터넷이 있는 빌더가
이미지를 받아 이미지 안에 넣는다. 레인지에는 인터넷이 없다. 태그가 번들 digest에
들어가므로, 새 태그의 플랫폼은 새 호스트 이미지를 계획한다. wargame이 늘어도 이미지
수는 그대로다: 기본 이미지, 엣지, WAF, Kali, wargame 호스트.

fabric은 보안 그룹을 셋 만든다: `mgmt` 밖의 모든 레인지 포트가 속하고 모든 IPv4를
허용하는 `fsl-range`(레인지를 지키는 것은 Neutron이 아니라 WAF다; anti-spoofing은 유지),
아무것도 허용하지 않는 `fsl-reach`, 그리고 모든 레인지 호스트의 `mgmt` 포트가 속하고
`fsl-reach` 구성원만 허용하는 `fsl-mgmt`. 플랫폼은 자신의 서버 id(부팅 시 쓰는
`FSL_OPENSTACK_PLATFORM`)로 찾은 `fsl-reach`의 포트로 `mgmt`에 붙으므로, 모든 호스트로
ssh할 수 있지만 어떤 호스트도 플랫폼으로 연결을 열 수 없고, Kali의 `mgmt` 포트는 다른
호스트에 닿지 않는다. runner는 호출자가 구간을 지정하지 않으면 호스트의 `mgmt` 주소로
접근한다.

slot은 레인지 호스트의 집합으로, `/api/range/slot/`로 관리하고 `range/slot.py`가
계획한다. 각 호스트는 선언된 구간마다 `<host>.<segment>` 이름의 포트를 가지며,
`fsl-range`에, `mgmt`에서는 `fsl-mgmt`에 속한다(다른 그룹에 있는 기존 `mgmt` 포트는
옮긴다). `gateway` 역할의 호스트는 모든 출발지의 게이트웨이 주소를 인터넷
포트 하나에 갖고, cloud-init은 첫 번째만 구성하므로 user data가 부팅마다 나머지를
추가한다. 모든 호스트의 user data는 `estate` 이름(WAF의 `board.com`과 `corp.com`,
wargame 호스트의 `board`와 `corp-wp`)을 `/etc/hosts`에 덧붙이며, WAF는 이것으로 각
wargame의 publish된 포트를 찾는다. 각 DB는 호스트의 자기 compose 프로젝트 안에서만 답한다.

레인지 slot. `cloud.yaml`의 `compute.slots`(기본 1, 플랫폼에서는 `FSL_OPENSTACK_SLOTS`)가
레인지 사본을 몇 벌 동시에 세울지 정하고, `max_sessions`가 그 수다. slot 1은 위 이름을 그대로
쓰고, slot N>1은 서버와 포트를 `<host>-N`(`fsl-edge-2`, `fsl-waf-2.mgmt`)으로 이름 짓고 서버에
`fsl_host`와 함께 `fsl_slot=N`을 단다. 첫 slot 밖의 slot마다 internet과 estate 네트워크의
사본(`fsl-internet-N`, `fsl-estate-N`, `fsl.slot=N` 태그)을 같은 subnet으로 가지므로, 모든 엣지가
같은 출발지 게이트웨이 30개를, 모든 Kali가 같은 출발지 주소를 갖고, 경보의 출발지는 어느 slot에서나
같은 나라로 분류된다. Neutron은 라우터를 공유하지 않는 두 네트워크에 같은 CIDR을 허용한다. `mgmt`는
공유한다. slot마다 호스트가 거기서 자기 DHCP 주소를 받고, `fsl-mgmt`가 전과 같이 막는다. slot 어댑터
(`OpenStack.in_slot(n)`)는 자기 slot의 서버만, 선언된 호스트 이름으로 읽으므로 역할, runner,
토폴로지, 엣지의 렌더링 설정이 모든 slot에서 같다. slot N의 엣지는 hostname을 `fsl-edge-N`으로
렌더링한다. 한 slot의 collector를 열 때 다른 slot의 송신자 규칙은 남긴다. 플랫폼은 세션을 열 때
slot에 묶는다(`Session.slot`, unique 제약으로 slot당 열린 세션 하나): 잠금 아래에서 고른, READY인
첫 빈 slot이다. 세션별 레인지 호출은 모두 그 slot으로 가고, 닫기는 그 slot만 초기화하며 그 slot의
억제만 복원된 것으로 표시하고, 초기화 상태도 slot마다 따로다(`api/reset.py`). 규칙 변경은 그 slot의
차례(lock)를 잡으므로 한 slot의 초기화가 다른 slot의 세션을 붙잡지 않는다. `run_on_role`은
`--session`이나 `--slot`을 받고, slot이 둘 이상인데 둘 다 없으면 거부한다. 콘솔의 VM 터미널은
세션을 `?arg=<id>`(ttyd `-a`)로 받아 그 slot의 호스트를 연다.

OPNsense 엣지 `fsl-edge`(vtnet0 internet이 WAN, vtnet1 estate가 LAN, vtnet2 mgmt가
opt1)가 slot에서 부팅한다. `POST /api/range/configure/`는 slot에 맞춰
`deploy/opnsense/config.xml`을 만들고(`range/opnsense.py`), Suricata include
`deploy/opnsense/suricata.yaml`과 시작 규칙과 함께 관리 ssh로 root로 올려 설치한 뒤
엣지를 재부팅한다. 새 부팅 시각이 보일 때까지 기다린 다음, 엣지가 30개 출발지
게이트웨이 주소를 갖고(하나는 static, 나머지는 IP alias), WAN에서 estate와 mgmt를
`HOME_NET`으로 하여 IDS 모드로 Suricata를 돌리며 EVE 경보와 HTTP 기록을 syslog로
보내고, syslog를 수집기로 보내고, pf에 WAN pass 규칙이 있는지 확인한다. 이 규칙은
WAF의 estate 주소로 가는 tcp 80만 통과시킨다. 규칙 편집기는
include가 가리키는 파일에 쓰고, include가 여는 소켓으로 `suricatasc`를 불러 다시
읽힌다. 엣지의 syslog와 WAF의 ModSecurity audit 로그는 GeoIP 보강과 함께 플랫폼의
Elasticsearch로 간다. Kali 이미지 하나가 모든 출발지를 맡는다: 인터넷
포트 하나가 국가별 약 100개 주소를 갖고(slot의 `bootcmd`가 NIC에 추가)
`/usr/local/sbin/fsl-origin`이 나가는 출발지 주소를 국가별로 SNAT하므로, 모든 도구가
선택된 국가에서 나간다. marker를 붙이는 프록시와 ttyd 터미널은 Kali 박스에서 돈다.
`GET /api/range/console/<host>/`는 그 호스트를 맡은 서버의 Nova 콘솔 URL을 반환한다.

`rebuild_slot()`(`POST /api/range/slot/rebuild/`)은 상주 slot VM 전부를 각자의
골든 이미지로 재구축하되 서버 id, flavour, 포트, 고정 IP는 유지한다.
`POST /api/sessions/<id>/close/`는 대신 `reset_slot()`을 호출한다. 이것은 셸을 내주는
VM(Kali, WAF)만 재구축하고 엣지와 wargame 호스트는 제자리에서 초기화하므로
(`docs/OPENSTACK.md` §6.1), 한 세션이 다음 세션에 수정된 규칙이나 심어 둔 데이터를
남기지 않는다. 재구축은 디스크를 지우므로 VM이 ACTIVE가 된 뒤 configure를 해야 한다.
wargame 호스트의 제자리 초기화(`clear_wargames()`)는 wargame마다, 그리고 estate 센서에
`docker compose down -v`를 실행하고, 센서의 eve 로그와 rsyslog의 imfile 상태를 지워서, 이미지만 남고 컨테이너나 볼륨은 없게 한다. configure의 마지막 단계 `start_wargames()`가 `wargames` 역할로
wargame마다 `sudo docker compose -p <id> -f /opt/fsl/wargames/<id>.yaml up -d --wait
--pull never`를 실행하므로, 세션마다 새로 시드된 대상에서 시작한다. 그다음 estate
센서를 띄운다: docker의 Suricata 이미지와 `deploy/suricata/suricata.yaml`을
`deploy/wargame-host/sensor.yaml`로 host 네트워킹으로 띄우고, 호스트의 estate 주소를 가진
인터페이스를 본다. 그래서 docker의 센서 하나가 WAF 네임스페이스에서 보는 WAF→대상 구간을
본다. 센서가 응답하면 `start_sensor()`가 호스트 항목이 정한 규칙 파일과 reload로
`rules/suricata.py`를 거쳐 기준선 규칙을 시드한다. 역할 `estate-sensor`는 compose 서비스 `suricata`에 매핑되어 runner가 그 안에서
실행하고, 호스트 항목이 규칙 파일과 reload 명령을 정하며(`settings.FSL_EXTRA_SENSORS`),
규칙 시드·검증·변경·기준선 검사는 두 센서 모두에 간다. 호스트의 `logs:` 항목에 따라
rsyslog가 `eve.json`을 `suricata` 태그로 수집기에 보내고(`range/waf.py`의 태그별 전달),
`fsl-reach`는 엣지·WAF와 같이 이 호스트를 듣는다. 종료 뒤에는 플랫폼이 직접 한다:
`platform/api/reset.py`가 백그라운드 스레드를 띄워, 규칙 잠금을 한 번 잡은 채 두 쪽을 동시에
돌린다. 한쪽은 `reset_in_place()`다: 엣지의 제자리 초기화(`reset_edge()`: 기준선
`fsl.rules`를 되돌리고, 설치된 파일을 엣지가 마지막 설치·부팅 뒤 기록한 해시와 sha256으로
비교하고, 레인지 pf 상태를 지우고, 필터를 다시 읽히고, Suricata를 재시작한다. 하나라도
다르면 `configure_edge()`의 설치와 재부팅으로 넘어간다), 수집기 보안 그룹, wargame
호스트(비우기, 그다음 wargame, 센서, 로그 전달 순서). 다른 쪽은 재구축한 VM 각각이 ACTIVE를
벗어났다가 다시 ACTIVE가 되는 것을 `plan_slot()`으로 확인한 뒤, 클라우드를 새로 읽어
`configure_rebuilt()`(WAF의 로그 전달)를 실행한다. 둘 다 VM이 ssh에 답하지 않는 동안
재시도하고(최대 30분), 첫 실패가 초기화를 실패시킨다. `configure_slot()`(수동 configure)은
호스트마다 스레드 하나로 단계를 나란히 돌린다: 엣지(설정과 재부팅), WAF, 수집기 보안 그룹,
wargame 호스트. 모두 끝나기를 기다린 뒤 그 순서에서 첫 실패로 실패한다. close는 바로 응답하고, 초기화
상태(idle, running, failed와 그 이유)는 플랫폼 프로세스가 들고 있다.
`POST /api/range/configure/`는 수동 재시도로 남고, 실패한 초기화 상태를 지운다.

OpenStack에서 세션 생성은 모든 slot이 차 있거나 준비된 빈 slot이 없으면 409로
답한다. `GET /api/range/ready/`는 `slots` 아래에 slot마다 번호, 그 slot을 잡은 세션, 단계(세션이
잡고 있으면 `IN_USE`, 초기화가 도는 동안 `RESETTING`, 실패했으면 그 이유와 함께 `RESET_FAILED`,
그 밖에는 `NOT_STANDING`, `REBUILDING`, `CHECKING`, `READY`), 초기화 상태, 세 가지 검사(모든 VM
ACTIVE, board의 ground truth 읽기 가능, sensor 규칙이 기준선이고 그 slot에 적용 중인 억제 없음)를
보고한다. 최상위 `ready`와 `slot`은 다음 세션 열기가 잡을 slot이다. `/api/range/slot/`,
`slot/rebuild/`, `configure/`는 `?slot=N`을 받고, 없으면 모든 slot에 적용한다. `POST /api/range/canary/`는
marker를 붙인 케이스 하나를 발사해 Suricata와 ModSecurity가 모두 경보를 냈는지와 두
엔진의 시각 차이를 보고하며, ready 검사에는 포함되지 않는다. 랜딩 페이지가 둘 다
호출한다.

### OpenStack 위의 레인지: 목표 구조

2026-09-30에 사용자가 결정했고, 2026-10-08의 변경을 표시했다. 대부분 구축되었다(위
참고).

```
 OpenStack project fsl-range.

 platform VM: Ubuntu 24.04, floating IP, docker compose up
   console and /api/, scoring, Elasticsearch, Filebeat, Kibana
   landing page /: start and stop a session, the scoreboard after close
   sidebar, panes inside the page:
     pfSense   web GUI pane (built; dropped from scope and removed 2026-10-08)
               (the edge is OPNsense since 2026-10-11)
     Kibana    framed directly, reading the same Elasticsearch (full)
     terminal  ttyd in the platform, ssh to the Kali VM on mgmt
     |
     +--OpenStack API, as member fsl-range--> networks, VMs, consoles
     +--management network, ssh-------------> Kali VM, WAF VM, wargame host

 Internet network: one subnet per origin country (30), no Neutron router
   Kali VM: one port holds every attack address; the source is rewritten
            to the chosen country's address as packets leave
     |
     v
 OPNsense VM: edge router; its WAN holds each subnet's gateway address
              and routes on without NAT, so country sources survive
   Suricata (OPNsense IDS): detects; no firewall lesson, per 2026-10-08
     |
     v
 WAF VM: nginx + ModSecurity v3 + CRS
         (planned: SecRuleEngine On, blue tunes CRS to block)
     |
     v
 estate network
   wargame host VM (Docker): board + board-db, corp-wp + corp-db,
                             the GHCR images docker runs (2026-10-11)
     Suricata on the estate NIC: the WAF-to-target leg (2026-10-12)

 Evidence:
   OPNsense: Suricata EVE, syslog-ng, UDP-------> Filebeat --+
   WAF VM: ModSecurity audit log --------------------------------+
   wargame host: Suricata EVE, rsyslog imfile, UDP --------------+
                                                                 v
   Elasticsearch --> platform ingest --> scoring
   Elasticsearch ----------------> Kibana --> blue team
```

남은 작업:

- 세션 수명 주기: WAF 모드와 시각 차이를 준비 상태 검사에 포함(종료 시 재구축 뒤
  `configure` 재실행은 2026-10-11부터 자동).
- 차단(계획, 2026-10-08 스펙): WAF는 `SecRuleEngine On`으로 돌고, 블루팀은 CRS를
  튜닝(paranoia level, 규칙 제외)해 공격은 차단하고 정상 트래픽은 통과시킨다.
  Suricata는 탐지를 맡는다. 시작 상태는 2026-10-10에 측정했다(`docs/DECISIONS.md`):
  PL1은 이미 게시판 SQLi를 차단하고 O'Brien을 통과시키므로, 학습은 O'Brien을 과차단하는
  PL4에서 시작하고 학습자가 튜닝한다(PL 낮추기 또는 규칙 제외). 케이스의 차단 여부는 대상 시스템 쪽에서
  `meta["blocked"]`로 읽는다. pfSense GUI에서 Suricata drop 규칙을 전환하던 이전 계획은
  대체되었다.

사람이 결정해야 할 열린 사항은 `docs/STATE.md`("Decisions left for a person")에 있다.

구축된 것: WAF VM은 ModSecurity audit 로그를 rsyslog imfile로 UDP 5140에 보내고
(`platform/range/waf.py`), OPNsense 엣지의 Suricata는 IDS(pcap) 모드로 돈다
(`deploy/opnsense/`, 아직 클라우드에서 만들어 보지 않았다). 구축 전에 이 클라우드에서
테스트할 것은 placement 스펙의 "To test on this cloud before building"에 있다.
