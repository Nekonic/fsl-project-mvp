# 아키텍처

훈련 환경을 어떻게 구성하는지, 트래픽과 증거가 그 안에서 어떻게 이동하는지, 그리고 그
뒤에 있는 설계 결정을 다룹니다. 점수의 정의는 `CLAUDE.md`에, 미해결 문제와 측정으로
확인한 특이 사항은 `docs/STATE.md`에 있습니다.

"결정" 절까지는 지금 실제로 동작하는 것을 설명합니다. Docker compose 훈련 환경이
기준이고, OpenStack 훈련 환경은 다른 부분만 적습니다. 마지막 절 "OpenStack"은 OpenStack
훈련 환경을 설명하며, 그곳에 구축된 것과 계획된 것
(`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`)을 구분합니다.

이 레포가 출발한 가설은 다음과 같습니다. 레드팀 공격에 정답 데이터(ground truth) 라벨을
붙일 수 있고, Suricata와 ModSecurity 경보를 그 라벨에 자동으로 매칭할 수 있으므로, 오탐과
미탐을 기계적으로 채점할 수 있다는 것입니다. 목표 점수는 이 가설이 성립한 뒤에
추가했습니다.

## 훈련 환경

compose 서비스와 네트워크는 아래 표와 같으며, `bin/measure`가 그 수를 셉니다. 두 compose
파일이 이를 나눠 정의합니다. `compose.yaml`은 컨트롤 플레인입니다(프로젝트 `fsl`, 오래
떠 있는 사본 하나): 플랫폼, Elasticsearch, Kibana, `collector`, GNS3 서버, edge 네트워크 네
개와 `mgmt`. `session.yaml`은 세션 하나의 데이터 플레인입니다: WAF, Suricata, Filebeat,
Kali, 프록시, 워게임. 이 파일은 edge 네트워크와 `mgmt`에 `external`(`fsl_<network>`)로
참여하고, 자기 `estate` 네트워크(고정 서브넷 없음, Docker가 사설 풀에서 할당)와 볼륨을
소유합니다. 세션을 열면(`POST /api/sessions/`, `platform/range/docker.py`의 `open_session`)
플랫폼 안에서 `docker compose -p fsl-<session id> -f session.yaml up -d --wait
--no-build`를 실행합니다. 이때 `FSL_HOST_DIR`은 compose가 플랫폼을 띄운 호스트
디렉터리(플랫폼의 `com.docker.compose.project.working_dir` 라벨)로 설정해 스택의 bind
mount가 호스트 기준으로 해석되게 하고, `FSL_SESSION`은 세션 id로 설정합니다. 이어서
플랫폼은 세션의 `estate`에 참여하고(`docker network connect`, 별칭 `platform`; 기본
게이트웨이는 `gw_priority: 1`로 플랫폼 자신의 `edge`에 남습니다) 세션의 프록시가 그 세션
자신의 WAF를 향하게 합니다(`/label/origin`). baseline은 그다음에 읽습니다. 세션은 동시에
실행됩니다. 세션을 열 때는 끝난 지 3분이 넘은 세션의 `fsl-<n>` 프로젝트에만 `down -v`를
실행하며(먼저 그 `estate`에서 빠집니다), 어느 프로젝트를 내릴지는 잠금 하나 아래에서
정하므로 동시에 열리는 두 세션이 서로의 새 스택을 내리지 않습니다. Docker는 세션을 최대
`FSL_MAX_SESSIONS`개(기본 2, `platform/fsl/settings.py`)까지 열고 그 이상은 409로
응답합니다. OpenStack은 훈련 환경 슬롯마다 세션 하나를 엽니다. 세션을 닫아도 그 스택은
3분 이상 지나 다른 세션이 열릴 때까지 남고, 그동안 해당 세션의 Filebeat가 마지막 경보를
전송합니다. 저장소는 닫힌 세션을 `FSL_RETAIN_CLOSED_MINUTES`분(기본 60, `compose.yaml`에서
설정) 동안 보관합니다. `platform/api/retention.py`는 시작할 때(`fsl/wsgi.py`)와 세션을
닫을 때마다 그보다 오래된 닫힌 세션을 거기에 속한 모든 데이터와 함께 삭제합니다. 세션의
탐지 기록과 고객 요청을 트랜잭션당 2,000행씩 지운 다음 세션을 지우므로, 대량으로 정리할
때도 저장소의 쓰기 잠금을 오래 잡지 않습니다. 저장소는 `transaction_mode: IMMEDIATE`
(`fsl/settings.py`)로 설정한 SQLite입니다. 읽은 뒤 쓰는 트랜잭션은 시작할 때 쓰기 잠금을
잡고, `database is locked`로 바로 실패하는 대신 30초 busy timeout 동안 기다립니다.
`bin/backup`은 `VACUUM INTO`로 저장소의 스냅숏을 만들고 가장 최근 사본 `--keep`개를
남깁니다(기본 1; `bin/platform-rebuild`와 `bin/cloud down`에서는 `cloud.yaml`의
`backups: {keep}`). OpenStack substrate에는 `open_session`이 없습니다. 그 훈련 환경은 Nova
VM이므로 세션 스택을 띄우지 않으며, 워게임은 VM 하나(`fsl-wargame-host`)에서 같은 GHCR
컨테이너로 실행됩니다. 준비 상태 점검과 세션 baseline은 어댑터의 `address("board")`, 즉
board의 8000 포트가 publish된 워게임 호스트의 관리망 주소로 board를 읽으며,
`loot.ground_truth`가 `BOARD_API_URL`의 호스트를 이 주소로 바꿉니다.

대상 시스템 하나는 워게임 하나이며, `wargames/` 아래 폴더 하나입니다. `session.yaml`은 그
폴더의 `compose.yaml`을 include합니다: `board`(Django와 MySQL, `loot_verified`)와
`corp`(WordPress와 MySQL, `effect_observed`). 플랫폼은 각 워게임을
`wargames/<id>/scenario.yaml`에서 찾습니다(`platform/wargames.py`; 필드는 `name`,
`description`, `image`, `public_url`, `objective_model`, `case_file`, 선택 필드로 콘솔의
시나리오 카드에 쓰는 `category`, `difficulty`(easy, medium, hard), `minutes`, 그리고 "세션,
WAF 설정 조정, 단계 엔진"과 "시나리오"에서 설명하는 `defense`, `foundations`,
`scenarios`). `image`는 아직 읽는 곳이 없습니다. 앱 이미지는 CI
(`.github/workflows/images.yml`)가 빌드하며,
`ghcr.io/nekonic/fsl-<name>:${FSL_IMAGE_TAG:-dev}`로 pull하거나 로컬에서 같은 이름으로
빌드합니다. 세션은 이 이미지로 `--no-build` 기동합니다. 플랫폼은 자신의 `FSL_IMAGE_TAG`를
자신이 띄우는 세션 스택에 넘기고, 도구 케이스는 같은 태그의 `ghcr.io/nekonic/fsl-kali`를
실행합니다(`redteam/tools.py`). 새 워게임을 추가하려면 폴더 안의 `scenario.yaml`,
`objectives.yaml`, `compose.yaml`, `redteam/cases/` 아래의 케이스 파일, 그리고
`session.yaml`의 `include:` 줄 하나가 필요합니다.

`session.yaml`과 워게임 어디에서도 `container_name`을 고정하지 않으며, 세션의 컨테이너
이름은 `fsl-<id>-<service>-1`입니다. 고정 이름은 컨트롤 플레인(`fsl-platform`,
`fsl-elasticsearch`, `fsl-kibana`, `fsl-collector`, `fsl-gns3`)에만 있습니다. 아래 첫 번째
표는 세션 서비스를 선언된 호스트 이름으로 적으며, `platform/range/docker.py`가 컨테이너를
이 이름에 다시 매핑합니다.

훈련 환경에 작용하는 엔드포인트(rules, validate, suppressions, `/api/attacker/`, origin,
label, canary)는 쿼리나 본문에서 `session`을 받습니다. 지정하지 않으면 쓰기는 가장 최근에
열린 세션으로 가고 열린 세션이 없으면 409로 응답하며, 읽기는 가장 최근 세션을 사용합니다.
닫힌 세션을 지정한 쓰기는 거부합니다. 예외 처리는 세션과 함께 저장합니다(마이그레이션
0014). 레드팀 콘솔은 자기 세션 id를 보냅니다. 각 세션의 센서는 실제로 적용 중인
`local.rules`를 자기 컨테이너 안에 둡니다. Docker에서는 세션을 열 때 모든 세션의 센서에 그
`defense`의 룰 파일을 넣고, 시나리오가 `defense`를 선언하지 않으면(corp)
`deploy/suricata/rules/local.rules`를 넣습니다. `deploy/suricata/rules`를 bind mount하는
곳이 없으므로 룰을 적용하면 해당 세션의 센서만 바뀝니다. Docker에서 남은 문제: 훈련 환경
호스트에서 온 요청을 거부하는 미들웨어는 가장 최근 세션의 `estate`만 다룹니다.

| 서비스 | 파일 | 이미지 | 네트워크 | 호스트 포트 |
|---|---|---|---|---|
| `fsl-wg-board` | session | `wargames/board/app`에서 빌드한 `ghcr.io/nekonic/fsl-board` (gunicorn 위의 Django, 포트 8000) | estate | |
| `fsl-wg-board-db` | session | `mysql` | estate | |
| `fsl-wg-corp-wp` | session | `wargames/corp/app`에서 빌드한 `ghcr.io/nekonic/fsl-corp` (WordPress 6.6.2, 취약 버전으로 고정한 플러그인 세 개; `Host` 헤더로 `corp.com`) | estate | |
| `fsl-wg-corp-db` | session | `wargames/corp/db`에서 빌드한 `ghcr.io/nekonic/fsl-corp-db` (MySQL 8.4, binlog `ROW`) | estate | |
| `fsl-waf` | session | `owasp/modsecurity-crs` (nginx), edge에서 별칭 `board.com` (edge는 공유하므로 플랫폼이 세션마다 프록시와 도구가 그 세션의 WAF를 향하게 함) | edge, edge-br, edge-hk, edge-us, estate | |
| `fsl-suricata` | session | `jasonish/suricata` | WAF의 네트워크 네임스페이스 | |
| `fsl-filebeat` | session | `filebeat:8.15.0`, 세션의 `eve.json`과 audit log 전송 | mgmt | |
| `fsl-kali` | session | `deploy/kali`에서 빌드한 `ghcr.io/nekonic/fsl-kali`; `http_proxy`는 `http://fsl-<id>-proxy-1:8081` | edge | |
| `fsl-proxy` | session | `deploy/proxy`에서 빌드한 `ghcr.io/nekonic/fsl-proxy` (mitmdump); `/label`은 프로젝트의 named volume | edge 네트워크 네 개 | |
| `fsl-elasticsearch` | control | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-collector` | control | `filebeat:8.15.0`, syslog 입력만 사용 (OpenStack 훈련 환경용) | mgmt | 5140/udp |
| `fsl-kibana` | control | `kibana:8.15.0`, `/kibana/`에서 제공 | mgmt | |
| `fsl-platform` | control | `platform/` (waitress 위의 Django, nginx 뒤에서 동작; nginx는 `/kibana/`의 Kibana, `/terminal/<session id>/`의 세션별 Kali ttyd, `/waf-terminal/<session id>/`의 세션별 WAF 쉘, `/vm-terminal/fsl-kali/`와 `/vm-terminal/fsl-waf/`의 VM 터미널도 제공); compose 플러그인을 포함하고 `session.yaml`을 `/src/session.yaml`에 마운트 | edge 네트워크, mgmt, 열린 각 세션의 estate | 8000, 8002 |
| `fsl-gns3` | control | `deploy/gns3`에서 빌드한 `ghcr.io/nekonic/fsl-gns3` (gns3-server 3.1.0a6, qemu, uBridge 1.2.3, busybox-static, docker-cli; 플랫폼이 올린 학습자 구성도를 열어 두고 그 표시용 노드를 시작; `CAP_NET_ADMIN`, `/dev/net/tun`, Docker 소켓, 호스트의 pid 네임스페이스) | mgmt | 3080 |

8000, 8002, 3080은 `FSL_PUBLISH`에, 5140/udp는 `FSL_SYSLOG_PUBLISH`에 바인딩하며 둘 다
기본값은 127.0.0.1입니다. 9200은 loopback에만 바인딩합니다.

| 네트워크 | 구간 | 서브넷 | 이름 | 출발지 |
|---|---|---|---|---|
| `edge` | `ru` | 5.188.10.0/24 | 인터넷 | 러시아 |
| `edge-br` | `br` | 177.54.144.0/24 | 인터넷 | 브라질 |
| `edge-hk` | `hk` | 103.152.220.0/24 | 인터넷 | 홍콩 |
| `edge-us` | `us` | 73.0.0.0/24 | 인터넷 | 미국 |
| `estate` | `estate` | 세션마다, Docker가 할당 | 애플리케이션 estate (서비스망) | |
| `mgmt` | `mgmt` | 172.31.0.0/24, 공유 | 관리망 | |

edge 네트워크는 모든 세션이 공유하며 서브넷이 고정되어 있습니다. Docker는 겹치는 서브넷을
거부하고, GeoIP용 출발지 정보가 서브넷에 담기기 때문입니다. `mgmt`도 공유합니다.
Elasticsearch, Kibana, collector가 이 네트워크에 있고 모든 세션의 Filebeat가
Elasticsearch에 접속해야 하기 때문입니다(`docs/DECISIONS.md`, 2026-10-10). Suricata의
`HOME_NET`은 WAF의 edge 서브넷 네 개에 10/8, 172.16/12, 192.168/16을 더한 것입니다. 고정되지
않은 `estate`가 Docker의 사설 풀에서 할당되기 때문입니다.

선언은 인터넷 구간 하나에 출발지 서른 개를 나열합니다. Cloudflare Radar 기준 HTTP 요청
점유율 상위 서른 개 국가이며, 각 출발지는 GeoIP가 그 국가로 판정하는 /24 하나와 약 100개의
공격 주소 중 일부를 할당받습니다. Docker는 브리지 하나에 IPv4 서브넷 하나만 둘 수 있으므로
그중 네 개만 네트워크 하나씩으로 만들고, OpenStack fabric은 서른 개 모두를 한 네트워크의
서브넷으로 만듭니다. `bin/pick-origins`로 이 표를 다시 만들 수 있고, acceptance 테스트가
모든 서브넷을 점수 계산이 읽는 파이프라인과 대조합니다.

Docker에서 망 분리는 네트워크 소속만으로 이루어집니다. 방화벽, iptables, ACL은 없습니다.
OpenStack에서는 fabric의 네트워크와 보안 그룹이 망을 분리합니다.
`test/test_attacker_reach.py`가 두 substrate의 실제 훈련 환경에서 이를 검증하고(Kali는
`board:8000`에도 `corp-wp`에도 직접 접근하지 못하며, 나가는 경로 밖의 어떤 서비스에도
접근하지 못합니다. `test/test_board_exfil.py`는 `board.com`을 거쳐 board에 접근합니다),
`test/test_concurrent_sessions.py`는 동시에 연 두 세션이 서로를 보지 못함을 검증합니다.
고정된 것은 edge 서브넷뿐이고, 컨테이너 주소는 Docker가 할당하며 재생성하면 바뀝니다. 뷰는
요청마다 새 어댑터를 만들어 주소를 읽습니다. 훈련 환경 호스트에서 온 요청을 거부하는 검사는
그 주소를 30초 동안 캐시하고, substrate에 연결할 수 없으면 훈련 환경이 비어 있다고 보고
요청을 허용합니다(`docs/THREAT-MODEL.md`).

플랫폼, WAF, 프록시는 multi-homed입니다. 공격자의 트래픽은 WAF를 거쳐서만
내부망(`estate`)으로 유입되지만, 플랫폼은 모든 edge 네트워크와 각 세션의 `estate`에 연결되어
있으므로 API가 호출자를 직접 검사합니다(`docs/THREAT-MODEL.md`).

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

`deploy/suricata/suricata.yaml`은 인터페이스를 eth0부터 eth4까지 지정하며, Docker가
`compose.yaml`에 설정한 우선순위대로 WAF의 네트워크를 연결한다는 점에 의존합니다. 이 대응
관계를 검사하는 곳은 없습니다. 이 파일의 `default` 항목은 그 밖의 인터페이스(OpenStack에서는
estate 센서의 `ens3`)에도 같은 캡처 설정을 적용합니다.

WAF는 `board.com`을 `board:8000`으로 보내고 `/internal/`에는 직접 404로
응답합니다(`deploy/nginx/board.conf`). `corp.com`은 `corp-wp:80`으로 가는 두 번째
vhost입니다(`deploy/nginx/corp.conf`). board는 첫 번째 워게임입니다. gunicorn 위에서 도는
Django 3.2.4(알려진 `order_by` SQL Injection 취약점 CVE-2021-35042가 있는 미패치 버전)로,
시작할 때 스스로 마이그레이션과 시드 데이터 입력을 수행하며 digest로 고정한 MySQL을 씁니다.
둘 다 외부에 publish하지 않습니다. board는 탈취된 계정 정보로 채점합니다. 세션이 시작되면
플랫폼은 `/internal/auth-users`에서 board의 `auth_user` 사용자 이름과 비밀번호 해시를 읽어
세션의 스냅숏으로 보관합니다. 플랫폼은 이 경로에 `estate` 네트워크로 직접 접근하며, WAF는
이 경로를 전달하지 않습니다. 이 읽기는 WAF를 거치지 않으므로 IDS도 WAF도 이를 보지
못합니다.

corp 워게임은 두 번째 워게임입니다. WordPress 6.6.2(`fsl-wg-corp-wp`)에 플러그인 세 개를
미패치 버전으로 고정했습니다. Ultimate Member 2.6.6(CVE-2023-3460, 가입 요청에
`wp_capabilities`를 주입해 administrator 권한을 얻는 취약점), WP GDPR Compliance
1.4.2(CVE-2018-19207, 인증 없이 옵션을 바꿔 관리자 자가 가입을 여는 취약점), Easy Post
Submission 2.3.0(CVE-2026-4431, 인증 없이 글을 덮어쓰는 취약점)입니다. 어느 것도 기본 OWASP
CRS에서 탐지되지 않습니다. DB인 `fsl-wg-corp-db`는 `--binlog-format=ROW`로 실행하는 MySQL
8.4이며, WordPress 자체에는 계측 코드를 넣지 않았습니다. corp는 공격이 DB에 커밋한 변경으로
채점합니다(아래 참고).

## 선언과 substrate 경계

Docker와 OpenStack은 둘 다 일급(first-class) substrate입니다(2026-10-11 결정). 플랫폼은
훈련 환경의 의미를 Docker에 묻지 않고 `platform/range/declaration.yaml`에서 읽습니다. 이
파일에는 구간마다 id, 표시 이름, 공격 출발지; 역할 표(attacker, scorer, gateway, proxy,
sensor, board, board-db, corp, corp-db, 그리고 `openstack:` 아래에 OpenStack에서 달라지는
edge, sensor, proxy 역할); 센서가 감시하는 호스트; 기본 출발지; 방어 대상 사이트(서울)가
있습니다. 구간은 출발지를 선언했을 때, 그리고 그때에만 외부 구간입니다.

선언에는 서브넷, 게이트웨이, 주소가 없습니다. 이 값들은 Docker와 Neutron이 모두 직접
할당하므로 substrate에서 가져옵니다. 선언한 서브넷이 실제와 다르면 아무 호스트도 없는
서브넷 기준으로 경보를 분류하게 됩니다. `compose.yaml`은 구간 식별 정보를 네트워크 라벨에
반복해 적습니다. `platform/tests/test_declaration.py`는 두 파일을 서로 대조하지만 실행 중인
훈련 환경은 검사하지 않습니다.

구간은 라벨로 찾습니다. Docker에서는 어댑터가 호스트도 라벨로 찾습니다.
`declaration.yaml`의 `compose:` 절이 각 역할을 compose 서비스에 대응시키고, 어댑터는 세션
프로젝트에서 그 `com.docker.compose.service` 라벨을 가진 컨테이너를 고릅니다. 두 곳은 이
조회를 거치지 않고 compose 이름 규칙으로 세션의 WAF 컨테이너를 직접 지정합니다:
`platform/api/site.py`(`http://fsl-<id>-waf-1`, 사이트 프록시)와
`platform/api/views.py`(`fsl-<id>-waf`, 블루팀 콘솔이 알려 주는 WAF 박스)이며, 아래 예외
표에 기록해 두었습니다. 각 구간은 `fsl.segment.id`를 Docker 라벨이나 Neutron 태그로 가지며,
어댑터는 라벨이 붙은 네트워크만 가져옵니다. 구간 id가 같으면 세션이 소유한 네트워크가
컨트롤 플레인 네트워크보다 우선합니다. 이름으로 매칭하는 방식은 compose 접두사와
오버라이드, Heat 스택 접미사, 유일하지 않은 Neutron 이름 때문에 깨졌습니다. OpenStack에서는
역할이 여전히 선언이 지정한 서버 이름입니다. OpenStack은 프로젝트의 모든 서버를 나열해
`server["name"]`을 맞춰 보는데, Nova는 이 이름의 유일성을 보장하지 않습니다. 이 문제는
`docs/STATE.md`에 아직 미해결로 남아 있습니다.

`platform/range/ports.py`가 인터페이스를 정의합니다. 코어 코드와 플랫폼 대부분은 그 네
메서드만 씁니다.

- `describe()`는 구조를 반환합니다: 구간, 각 구간의 노드와 주소, 센서.
- `segments()`는 센서 검사 없이 어느 호스트가 어느 구간에 있는지 반환합니다.
- `runner(role, segment)`는 상주 호스트(센서, 프록시, 플랫폼이 명령 로그를 읽는 공격 박스,
  corp-db)에서 명령을 실행합니다.
- `launcher(segment)`는 한 구간에서 일회성 도구를 실행하고 그 출력을 반환합니다.

`range.substrate()`는 `FSL_SUBSTRATE`가 지정한 어댑터(기본값 `range.docker.Docker`)를
만들며, `FSL_SUBSTRATE_OPTIONS`가 그 이름 아래에 둔 옵션에 `declared=RANGE`를 더해 넘깁니다.
Docker는 `FSL_PROJECT`(기본값 `fsl`)를 받습니다. OpenStack은 `FSL_OPENSTACK_KEYSTONE`,
`_USER`, `_PASSWORD`, `_PROJECT`, `_SSH_USER`, `_SSH_KEY`, `_REGION`, `_INTERFACE`,
`_DOMAIN`을 받으며 하나라도 없으면 그 이름을 밝혀 거부합니다. 훈련 환경의 모양을 정하는 값
`_BASE_IMAGE`, `_FLAVOR`, `_BUILD_FLAVOR`, `_ROLE_FLAVORS`, `_AVAILABILITY_ZONE`,
`_SUBNETS`, `_MTU`, `FSL_OPNSENSE`도 받으며 이 값들은 쓰이는 곳에서 이름을 밝혀 거부합니다.
`FSL_IMAGE_TAG`(워게임 호스트의 이미지; 부팅할 때 `/opt/fsl/.env`에 기록)도 받습니다. 코드에
기본값이 있는 값은 없습니다. 모두 Heat 스택을 거쳐 `deploy/openstack/cloud.yaml`에서
옵니다(`platform/range/cloud.py`가 그 파일을 읽고 검증합니다). `redteam/harness.py`는
launcher를, `platform/rules/suricata.py`는 runner를 전달받으므로 둘 다 `subprocess`를
import하지 않고 substrate 이름도 쓰지 않습니다.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| 구조 | `docker network ls/inspect`, 라벨 필터 | Keystone v3, `tags-any`를 쓰는 Neutron, Nova |
| 센서 | 선언된 각 센서가 선언된 gateway의 네트워크 네임스페이스를 공유하지 않으면 훈련 환경 기술(describe)을 거부 (`docker ps`, `.HostConfig.NetworkMode`) | 이름이 지정된 두 서버가 모두 있으면 센서를 보고함; 센서가 gateway의 트래픽을 실제로 보는지는 확인하지 않음 |
| runner | 세션 프로젝트에서 해당 역할의 서비스 컨테이너로 `docker exec` | 인스턴스로 `ssh`; 워게임 호스트가 맡고 `compose:`가 서비스에 대응시킨 역할은 그 컨테이너 안에서 실행 (`sudo docker exec <service>`, `range/wargame_host.py`) |
| address | 세션 프로젝트에서 해당 역할의 `estate` IP | 호스트의 `mgmt` 주소 |
| launcher | `docker run --rm --network <segment>`, 세션 WAF의 이름에 대한 `--add-host` 포함 | `runner("attacker")`: 선언된 공격 박스의 mgmt 주소로 ssh해 도구를 실행 (origin은 공격 박스가 그 구간에 있는지만 확인하며, 출발 국가는 `fsl-origin` SNAT가 정함); 다른 이미지는 거부함. Nova로는 호스트를 부팅해 출력을 받고 삭제할 수 없기 때문 |
| 검증 대상 | 실제 스택 | 공개 API 레퍼런스와 로컬 sshd로 만든 fake에 대한 유닛 테스트; `fsl-range` 클라우드에서 플랫폼 VM이 `/api/range/`로 fabric, 이미지, 슬롯을 구축했고, `describe()`가 출발지 서른 개 위의 WAF와 estate·mgmt 위의 호스트 네 대를 다시 읽었으며, `runner()`가 각 호스트에서 mgmt 주소로 ssh해 실행됨; `launcher()`는 2026-10-08에 `ru`와 `tw` 출발지에서 sqlmap을 실행함 |

compose는 substrate와 관계없이 Docker 소켓을 플랫폼에 마운트하고, entrypoint가 플랫폼
사용자를 그 소켓의 그룹에 추가합니다. 이는 컨테이너 탈출 경로입니다. OpenStack 어댑터를
쓰면 이를 제거할 수 있지만 아직 제거하지 않았습니다. 어댑터가 훈련 환경을 구동하기 전에
남은 작업은 `docs/STATE.md`의 "The substrate seam" 항목에 있습니다.

## 네트워크 구성도

훈련 환경의 네트워크 구성은 GNS3 프로젝트 파일로 작성합니다. `revision` 9이므로 GNS3 2.2가
열 수 있고, 3.x는 불러올 때 업그레이드합니다. substrate마다 두 종류가 있습니다.

- **시스템 구성도**, `deploy/topology/system/range-{docker,openstack}.gns3`: 선언의 전체
  배선(관리 구간, `fsl-platform`, 컨트롤 플레인 컨테이너, 출발지 라벨을 찍는 프록시)입니다.
  영어로만 있으며 개발과 GNS3의 MCP용입니다. GNS3 서비스는 레포의 구성도를 보지 않으므로
  학습자에게는 제공되지 않습니다.
- **학습자 구성도**, `deploy/topology/range-{docker,openstack}.gns3`와 그 한국어 짝: 학습자가
  방어하는 회사 웹 서비스 네트워크를, 실습 토폴로지를 그리는 방식(Cisco NetAcad lab
  topology, NSRC 워크숍 logical diagram)의 논리 구성도로 그립니다. 역할 호스트 이름, 링크
  끝마다 인터페이스와 프리픽스를 붙인 주소(`kali`와 `customers`는 인터페이스만), 영역마다 그
  네트워크를 적은 캡션(인터넷은 이름만)만 있고, 그 밖에는 아무것도 없습니다(제목, 범례, 메모,
  기계 자체의 이름, `fsl-`, 관리 구간, Docker 브리지 이름 모두 없음). 노드는 다음과 같습니다.
  `internet` 스위치의 `customers`와 `kali`(공격자의 Kali 박스), `firewall`(OpenStack의
  OPNsense 에지로, 에지의 Suricata를 이 노드에 합쳐 그림), `waf`와 사이트(`board.com` 또는
  `corp.com`, WAF 호스트의 선언된 이름)가 붙는 `sw1`(서비스 구간), OpenStack에서는 사이트
  뒤에서 데이터베이스(`board-db`)가 붙는 `sw2`(데이터베이스 구간), Docker에서는 `sw1`에 붙는
  데이터베이스(Docker 훈련 환경에는 에지가 없고 사이트와 데이터베이스를 estate에 두므로
  구성도도 그렇게 그리며 `sw2`가 없습니다), 그리고 `log-server`(Elasticsearch)를 기록을
  보내는 호스트와 잇는 `sw3`(관제)입니다. 기록을 보내는 호스트는 OpenStack에서는 방화벽,
  WAF, 사이트(estate 센서가 사이트의 호스트에서 실행되며 자기 eve.json을 직접 전송합니다)이고,
  Docker에서는 WAF 하나입니다(세션의 로그 전송기가 WAF의 audit log와, WAF의 네임스페이스에서
  실행되는 Suricata의 볼륨을 읽습니다). 스위치 번호는 실습 토폴로지가 붙이는 방식(`sw1`,
  `sw2`, `sw3`, NSRC의 `sw1`)을 따르며, 순서는 서비스, 데이터베이스, 관제로 고정합니다. 각
  스위치가 어느 구간인지는 영역 캡션이 알려 줍니다. 템플릿은 두 워게임의 사이트와
  데이터베이스를 한곳에, 둘 다 하나의 `sw2`에 그리고, `topology.for_wargame`이 세션의 워게임
  것만 남깁니다. 고객을 선언하지 않은 워게임(`corp`, `traffic.yaml` 없음)에는 `customers`
  노드가 없습니다. `topology.learner(declaration, wargame)`는 훈련 환경의 이름을 구성도의
  이름으로 옮기는 매핑입니다. 대상은 호스트(`fsl-kali`는 `kali`이며, 고객 트래픽을 그
  호스트에서 생성하는 경우 `customers`이기도 합니다. `fsl-edge`는 `firewall`, 워게임 호스트와
  그 사이트 컨테이너는 사이트, `fsl-elasticsearch`는 `log-server`), 역할, 구간에서 스위치로의
  대응(출발지는 `internet`, estate는 `sw1`, 워게임의 compose 네트워크는 `sw2`, 관리 구간은
  NIC 이름만 쓰는 `sw3`), 그리고 각 센서에서 그 센서가 NIC를 쓰는 노드로의 대응입니다.
  오버레이, 레슨의 훈련 환경 질문, 인터페이스 읽기는 모두 이 매핑을 거칩니다. 모든 링크는
  직선 하나(수평, 수직, 대각선)이며 다른 링크나 노드를 가로지르지 않습니다. 링크가 바로
  위에서 들어오는 노드는 이름을 옆에 둡니다. 모든 호스트는 크기와 선 굵기가 같은 정사각형 틀
  하나입니다(`host-*.svg`, GNS3 이미지를 빌드할 때 `deploy/gns3/symbols.py`가 만들고
  `provision.py`가 업로드합니다). 틀 안에는 GNS3에 번들된 affinity 글리프가 들어가고, 틀 색은
  공격자 빨강, 방어 초록, 사이트 파랑, 고객과 로그 서버 회색입니다. 스위치와 인터넷은 GNS3
  번들의 정사각형 스위치와 지구본 아이콘을 그대로 씁니다. `kali`의 틀에는 OffSec의 Kali
  드래곤이 들어갑니다(프레스 팩의 `kali-dragon-black.svg`를 고정 커밋에서 가져와 sha256으로
  확인하고, 수정하지 않은 채 틀 안에 배치합니다. `host-kali.txt`와 구성도 창에 누구의
  상표인지 표시합니다).
- **학습자 구성도의 호스트는 모두 표시용 컨테이너입니다.** GNS3는 링크 끝을 노드 상태에 따라
  칠하므로, 멈춘 노드는 모든 링크 끝이 빨강으로 그려집니다. 각 호스트는 고정한 이미지
  하나(`busybox`, `topology.DISPLAY_IMAGE`)의 `docker` 노드로, `sleep`만 실행하고 콘솔이
  없습니다. 실제 기계는 훈련 환경에서 실행되고 구성도의 노드는 이를 표시만 합니다. 플랫폼
  VM에서 슬롯 1에 board 구성도, 슬롯 2에 corp 구성도를 두 언어로 올려 측정한 값: 표시용
  컨테이너 26개, 그 프로세스와 runc shim의 PSS 115MB, uBridge 프로세스 12MB
  (`docs/DECISIONS.md`).

구간은 `ethernet_switch` 노드입니다. 시스템 구성도에서 Docker 컨테이너는 실제 이미지를
지정했지만 시작하지 않는 `docker` 노드이고, OpenStack VM은 디스크 이미지 없는 `qemu`
노드입니다(OPNsense 에지는 vtnet 순서대로 NIC 세 개). 워게임 호스트의 컨테이너는 compose
프로젝트마다 스위치 하나(`board-default`, `corp-default`)에 연결됩니다. 다른 컨테이너의
네트워크 네임스페이스나 호스트 네트워크를 공유하는 센서는 NIC가 없고, 옆의 메모가 어느
노드의 네트워크를 감시하는지 알려 줍니다(Docker 프로젝트에서는 점선이 `fsl-suricata`와
`fsl-waf`를 잇습니다). 시스템 구성도에서는 선언된 구간마다 그 스위치를 담은 제목 붙은
사각형이 있고(Internet, Application estate, Management and monitoring), 컨테이너와 VM마다
쉬운 말로 쓴 메모가 붙습니다. GNS3 3.1에서는 노드의 라벨이 곧 노드 이름입니다.
`platform/tests/test_gns3_topology.py`는 `declaration.yaml`, `compose.yaml`, `session.yaml`,
워게임 compose 파일에서 시스템 구성도의 기대 노드와 링크를 도출하고 GNS3의 구조 규칙을
검사합니다. 각 워게임의 학습자 구성도는 위의 투영으로 검사합니다: 노드,
`topology.learner`를 거쳐 시스템 구성도의 배선과 대조한 링크, 로그 링크, 배치, 표시용 노드.
`bin/check-topology`는 gns3-server 2.2.61과 3.1.0a6을 `~/.cache/fsl/check-topology` 아래
venv에 설치하고, 각 릴리스의 `load_topology`를 각 파일의 사본과, 각 학습자 구성도에서 픽스처
훈련 환경으로 워게임마다 생성한 훈련 환경 구성도에 대해 실행하며, 노드가 지정한 번들
심볼이 해당 릴리스에 모두 있는지 확인합니다.

### 훈련 환경 자체의 구성도

학습자는 자기 훈련 환경의 주소를 봅니다. `api/maps.py`는 학습자 구성도에서 OpenStack 슬롯
또는 Docker 세션과 그 세션의 워게임마다(`slot 1 board`, `session <id> corp`), 언어마다
프로젝트 하나를 만듭니다(`topology.labelled`). 실습 토폴로지처럼 모든 링크의 양 끝에 라벨을
붙입니다. 스위치 쪽 끝(`internet` 스위치 포함)에는 링크가 쓰는 포트를 짧게
적습니다(`Ethernet2`는 `e2`). 호스트 쪽 끝에는 그 스위치 구간의 실제 인터페이스와
프리픽스를 붙인 주소를 적으며(`ens3 10.30.0.102/24`, `vtnet0 5.188.10.1/24`), 이 값은
`topology.learner`를 거쳐 훈련 환경에서 읽습니다. 공격자는 기본 출발지의 인터페이스, 고객은
가장 많이 쓰는 출발지의 인터페이스(`traffic.yaml`의 가중치 기준이며 `attacker.customer_origins`와
같이 기본 출발지는 제외합니다. Docker처럼 고객 트래픽과 함께 시작하는 고객 박스에 그런
인터페이스가 없으면 라벨을 붙이지 않습니다)를 적되, 둘 다 주소는 적지 않습니다
(`topology.ADDRESS_VARIES`). 요청마다 출발지에 따라 출발지 주소가 바뀌기 때문입니다(출발지
SNAT, 여러 출발지). 사이트는 `sw1`에서는 호스트의 주소(WAF가 이 주소로 사이트에 접속합니다),
`sw2`에서는 사이트 컨테이너의 주소를 적습니다(이중 연결(dual-homed) 서버이므로 자기 링크
끝마다 라벨이 하나씩 붙습니다). `sw3` 쪽 끝에는 NIC 이름만 적습니다(`ens4`, `vtnet2`). 그
주소는 학습자에게 보이지 않는 관리 네트워크에 있기 때문입니다. `log-server`의 끝에는 로그
저장소가 그 네트워크에 자기 NIC를 가진 경우 그 NIC를(Docker), 그렇지 않으면 플랫폼 VM의
NIC를 적습니다(OpenStack, `ens7`). Docker 브리지(`br-`) 이름을 적는 라벨은 없습니다. 비어
있을 수 있는 끝은 Docker의 `customers` 하나뿐이며, 이 박스는 고객 트래픽이 실행되는 동안만
떠 있습니다. 각 영역 캡션에는 그 스위치에 붙은 라벨의 네트워크를 덧붙입니다(`Services
10.30.0.0/24`, `Internal DB 172.18.0.0/16`; 스위치의 캡션은 그 스위치를 담은 가장 작은
상자의 텍스트이며, `topology.captions`가 이를 찾습니다). 인터넷(Internet)과
관제(Monitoring) 캡션은 이름만 둡니다. 라벨은 링크가 나가는 쪽의 노드 옆에 수평으로
놓습니다(`topology.leaving`). 수평이거나 완만한 링크에서는 노드의 다른 링크가 더 많은 공간을
남기는 쪽, 즉 선의 위나 아래에, 글자 밑으로 선이 지나지 않는 위치에 둡니다. 가파른
링크에서는 노드 아래에, 또는 노드 이름이 옆에 있으면 노드 위에 두고, 같은 규칙으로 선의
왼쪽이나 오른쪽에 둡니다(이름이 위에 있는 노드는 노드 오른쪽). 라벨은 모든 선, GNS3의 상태
표시(3.1 웹 UI에서 6 단위 크기의 원형, 노드 중심에서 선을 따라 60 단위 위치), 노드 이름, 영역
테두리와 그 캡션을 피하며, 글자 폭은 한 글자에 7 단위로 어림합니다(웹 UI는 `font-size:
10.0`을 13.3px로 렌더링합니다). 완만한 링크의 라벨이 자기 노드 이름과 겹치면 선의 반대쪽으로
옮깁니다. 왼쪽에 놓는 라벨은 `text-anchor: end`로 오른쪽 정렬합니다. 모든 id는
`uuid5(<learner id>, "slot-<n>-<wargame>")`(또는 `session-<id>-<wargame>`)이고, 프로젝트
이름에는 키가 붙으며, `show_interface_labels`를 켭니다. 인터페이스는 어댑터가
읽습니다(`interfaces()`). OpenStack에서는 슬롯의 각 호스트에서, 그 호스트 자체에서 실행되는
runner로 `ip -o -4 addr`(OPNsense에서는 `ifconfig`)를 실행합니다. 워게임 호스트에서는 compose
컨테이너의 주소를 `nsenter`로, 브리지는 Docker 네트워크 id로 읽으며, 플랫폼 VM 자신의 NIC는
호스트 네트워크의 `busybox` 컨테이너에서 같은 `ip`로 읽습니다(`interfaces.on_this_host`;
플랫폼에는 SSH를 쓰지 않습니다). Docker에서는 세션 엔드포인트마다 MAC을 그 컨테이너 안의
`/sys/class/net`과 맞춰 봅니다.

`gns3.publish`는 GNS3 admin으로 로그인합니다(비밀번호는 `FSL_GNS3_ADMIN_PASSWORD` 또는
`/run/fsl-gns3/admin-password`에서 읽습니다. GNS3 데이터 디렉터리를 읽기 전용으로 마운트하며,
이 파일의 권한은 Docker 소켓 그룹에 대해 0640입니다). 이어서 GNS3가 해당 프로젝트를 목록에
갖고 있으면 삭제하고(GNS3가 가진 적 없는 프로젝트를 DELETE하면 ERROR 로그가 남습니다), URL의
프로젝트 id를 그대로 담은 `project.gns3`로 portable 프로젝트를 가져오고(그러면 GNS3는
스냅숏처럼 모든 id를 유지합니다), `auto_close`를 끄고(가져온 프로젝트는 파일 내용과 관계없이
이 값이 켜진 채 만들어지며, 마지막 웹 클라이언트가 떠날 때 닫힌 프로젝트는 노드를 멈춥니다),
프로젝트를 연 뒤 노드를 시작합니다. 구성도는 세션을 열 때, 슬롯 초기화 후, 그리고 구성도
창이 요청했는데(`GET /api/topology/?language=&session=`) GNS3가 그 구성도를 열어 두지 않았을
때 올립니다. 바뀌지 않은 구성도는 다시 올리지 않습니다. 남겨 두는 구성도는 슬롯마다 가장
최근 세션의 것과, Docker에서는 열린 세션들의 것이며, 나머지는 삭제합니다. 생성한 구성도는
커밋하지 않습니다. GNS3가 구성도를 불러오지 못하면 엔드포인트는 세션 워게임의 학습자
구성도를 파일에서 제공하고 그 이유를 `detail`에 적습니다.

각 프로젝트에는 한국어 학습자를 위한 한국어 짝이 있습니다:
`deploy/topology/range-docker.ko.gns3`와 `range-openstack.ko.gns3`. 노드, 링크, 포트,
위치는 같고 영역 캡션만 `docs/vocabulary.md`의 용어를 써서 한국어로 적습니다. 노드 이름은
역할 이름 그대로 둡니다. GNS3의 compute는 노드를 노드 id만으로 관리하므로 열린 두 프로젝트가
같은 id를 공유할 수 없습니다. 그래서 짝 파일의 모든 id는 `uuid5(<English id>, "ko")`이고
프로젝트 이름에는 한국어 접미사가 붙습니다. 영어 파일이 기준입니다. 테스트가 영어 파일에서
한국어 파일의 구조를 다시 만들어, 문구 외의 차이가 있으면 실패합니다.

`gns3` 서비스(`deploy/gns3`, MCP extra를 포함한 gns3-server 3.1.0a6)는 플랫폼이 올린
구성도만 갖습니다(템플릿 하나가 모든 워게임을 그리므로 복사해 넣는 구성도는 없습니다).
컨트롤러 데이터베이스가 생기기 전에 admin 비밀번호를 설정하고(`FSL_GNS3_ADMIN_PASSWORD`,
없으면 `/var/lib/fsl-gns3/admin-password`에 한 번 생성), learner 사용자에게 `/`에 대한 내장
Auditor 역할을 부여하며(`FSL_GNS3_AUDITOR_PASSWORD`, 기본값 `fsl-auditor`, 플랫폼에도
전달), `/static/web-ui/fsl-auditor.html`을 작성합니다. 이 페이지는 learner로 로그인해 번들
웹 UI가 컨트롤러를 읽는 위치(`localStorage`의 `controller-1`, `controllerIds`)에 토큰을
저장합니다. 또 링크 끝 라벨을 프로젝트가 지정한 위치에 그리도록 `showInterfaceLabels`를 켜고
`integrateLinkLabelsToLinks`를 끄며, `statistics_command`를 `false`로 설정해 웹 UI가
학습자의 브라우저에서 사용 통계를 보내지 않게 합니다. 페이지 제목은 Map입니다. 이 페이지는
같은 출처(same-origin) 프레임 안에서 프로젝트를 열고, 구성도가 그려지기 전에 보기 전용으로
만듭니다. 스타일시트가 편집용 화면 요소(제목 표시줄, 도구 열, 컨텍스트 메뉴, 토폴로지 요약,
대화 상자, Angular CDK 오버레이)를 모두 숨기고 `svg.map` 안의 모든 요소에서 포인터 이벤트를
제거합니다. 프레임 window의 캡처 단계 리스너는 신뢰된(trusted) 클릭, 더블클릭, 컨텍스트
메뉴, 키 입력, 드롭을 모두 삼키고, `svg.map` 자체를 왼쪽 버튼으로 누른 경우를 제외한 모든
mousedown도 삼킵니다. 페이지가 직접 만든 합성 이벤트는 신뢰된 이벤트가 아니므로, 숨긴
컨트롤에 대한 페이지 자신의 클릭은 그대로 동작합니다. 구성도가 그려지면 토폴로지 요약을
닫고(3.1.0a6 번들에서 이 창의 표시 여부는 상수입니다), 웹 UI의 이동 모드를 계속 켜
두고(구성도를 끌면 이동, 휠은 확대·축소), 확대 비율을 초기화한 뒤 그림이 화면에 들어올 때까지
웹 UI 자체의 축소 버튼을 누르고(한 번에 0.1; 웹 UI는 프로젝트의 `zoom`을 읽지 않습니다),
mousemove 한 번으로 그림을 가운데로 옮깁니다(웹 UI는 `movementX`/`movementY`만큼
이동합니다). 창의 "화면에 맞추기" 버튼은 프레임에 `fsl-fit`을 보내 같은 초기화와 맞춤을
실행합니다. 서버에서는 여전히 Auditor 역할이 모든 쓰기를 거부합니다. 개발용
MCP(`/v3/mcp/`)를 쓰려면 `docker exec fsl-gns3 python /opt/fsl-gns3/provision.py api-key
<name>`으로 API 키를 출력하세요. 콘솔에는 MCP를 노출하는 곳이 없습니다. 콘솔의 해당 탭
이름은 구성도(`blue.pane.topology`, 영어로는 Map)이며, 학습자가 읽는 문구 어디에도 GNS3라는 이름은 나오지 않습니다.

읽기 전용 사용자는 프로젝트를 열 수 없으므로(`Project.Allocate`) `provision.py`가 시작할 때
admin으로 모든 프로젝트를 열고 멈춰 있는 표시용 노드를 모두 시작합니다(고정 이미지만
해당하며, 다른 이미지의 노드는 절대 실행하지 않습니다). 그래서 Auditor에게는 프로젝트가 열려
있고 초록으로 보입니다. 서비스에 필요한 것은 다음과 같습니다. 릴리스 태그에서 빌드하고
`cap_net_admin,cap_net_raw` 파일 capability를 준 uBridge 1.2.3, `ethernet_switch` 노드를 위한
`CAP_NET_ADMIN`과 `/dev/net/tun`(3.1은 스위치마다 컨테이너 자신의 네트워크 네임스페이스 안에
커널 브리지와 TAP을 만듭니다), `docker` 노드를 위한 호스트의 Docker 소켓(노드마다 호스트
데몬의 컨테이너 `GNS3.<node>.<project id>`가 됩니다), Debian의 `docker-cli`(GNS3는 `docker
exec`로 docker 노드를 닫습니다), `busybox-static`(GNS3가 시작하는 docker 노드마다 복사해
넣습니다), 호스트의 pid 네임스페이스(`pid: host`: uBridge가 시작된 노드의 인터페이스를
컨테이너의 호스트 pid 네임스페이스로 옮깁니다). `qemu-system-x86`은 시스템 구성도의 `qemu`
노드를 위해 남겨 둡니다. `[ai-features]` extra가 없으면 3.1.0a6이 시작하지 않는데, 이
extra는 시작할 때 skills 레포를 clone하는 copilot을 함께 가져옵니다. 이미지는
`skills_config.py`에서 그 `enabled`를 `False`로 설정하며, 그 줄이 없어지면 이미지 빌드가
실패합니다. 호스트 데몬은 컨테이너의 bind mount를 호스트 기준으로 해석하므로 데이터
디렉터리는 양쪽에서 같은 경로(`/var/lib/fsl-gns3`)입니다. 서버는 `gns3` 사용자로 실행되며,
플랫폼의 `fsl`처럼 시작할 때 소켓의 그룹에 참여합니다. `GET /api/topology/`는 GNS3가
프로젝트를 `opened`로 보고하는 동안에만 웹 UI(`web_ui`)를 제공하고, 그렇지 않으면 콘솔의
구성도 창에 구성도가 열려 있지 않다고 표시합니다.

`GET /api/topology/?language=en|ko`는 그 언어로 그린 substrate의 학습자
구성도(`&session=<id>`가 있으면 위에서 설명한, 그 세션 워게임의 구성도)를
GNS3(`platform/gns3.py`)나 레포 파일에서 반환합니다(값이 없으면 `en`, 그 밖의 값이면 400).
콘솔은 자기 표시 언어를 보내고, `web_ui`는 GNS3 웹 UI의 해당 프로젝트 id로 바로 연결합니다.
구성도 창은 이 구성도 하나만 보여 줍니다: 프레임 안의 GNS3 웹 UI와 맞추기 버튼.
`GET /api/sessions/<id>/topology/`는 세션 워게임의 영어 구성도를 읽고(짝 파일은 노드 이름과
링크가 같습니다) `project.nodes`를 더합니다. 여기에는 같은 훈련 환경 읽기에서 얻은 호스트
노드별, 스위치별 주소와 `running` 또는 `not reported` 상태가 들어갑니다. 세션 오버레이는
구성도에 있는 호스트와, 구성도에 있는 스위치 위의 주소만 나열합니다. 오버레이는 훈련 환경이
보고하는 이름으로 호스트를 배치합니다. OpenStack은 슬롯의 서버를 선언된
이름(`slot.known_as`)으로 보고하며, syslog 기록에 실리는 VM 자체의 hostname에만 슬롯
접미사가 붙습니다.

## 격리 경계

관심사마다 담당 파일이 하나씩 있습니다. 아래 예외는 현재 코드에 있는 것입니다.

| 관심사 | 담당 파일 | 알려진 예외 |
|---|---|---|
| Elasticsearch | `platform/ingest/elastic.py` | `platform/register_pipeline.py`가 기동 시 `fsl-geoip` ingest 파이프라인을 PUT 합니다 |
| Kibana HTTP API, saved object, Discover 링크 | `platform/kibana.py` | 없음 |
| GNS3 API | `platform/gns3.py` | GNS3 컨테이너 안의 `deploy/gns3/provision.py`가 admin으로 로그인해 학습자 계정을 만들고 프로젝트를 엽니다. 콘솔의 구성도 창은 `gns3.py`가 돌려주는 포트와 경로의 웹 UI를 프레임으로 띄웁니다 |
| CRS 설정과 nginx reload | `platform/rules/crs.py` | WAF 터미널(`waf-terminal.sh`)이 사용자에게 `fsl-<id>-waf-1`의 쉘을 열어 줍니다(OpenStack에서는 `vm-terminal.sh fsl-waf`가 WAF VM의 ssh 쉘을 엽니다). f6의 WAF 창 단계는 사용자가 읽을 예외 파일을 알려 주며, 그 명령(`cat {waf_rules}`)은 `wargames.lesson`이 선언된 예외 파일(`settings.FSL_WAF`)로 채웁니다. 플랫폼은 터미널을 조작하지 않습니다 |
| 세션의 WAF 컨테이너(docker) | `platform/range/docker.py`, compose 라벨로 찾음 | `platform/api/site.py`는 `http://fsl-<id>-waf-1`을, `platform/api/views.py`는 `fsl-<id>-waf`를 compose 이름 규칙으로 만듭니다 |
| Suricata 프로세스 | `platform/rules/suricata.py` | `platform/range/opnsense.py`와 `deploy/opnsense/`가 OPNsense 에지의 Suricata를 설정하고 재시작합니다(OpenStack). `declaration.yaml`의 각 센서 호스트(에지, 그리고 `estate-sensor`를 맡는 워게임 호스트)가 `suricata.py`에 넘길 룰 파일과 reload 명령을 지정합니다. `platform/range/wargame_host.py`(`deploy/wargame-host/sensor.yaml`과 함께)는 슬롯을 설정하거나 리셋할 때 워게임 호스트의 estate 센서 compose 서비스를 멈췄다가 다시 시작하며(OpenStack), 그 뒤 기본 룰은 `suricata.py`를 거쳐 적용됩니다 |
| 공격 박스 | `platform/attacker.py` | `platform/operator_log.py`가 `/var/log/fsl/commands.log`를 읽습니다. 터미널 연결 설정(`settings.py`, `nginx.conf`, `entrypoint.sh`)에 `fsl-kali`와 `fsl-<id>-kali-1`이 적혀 있습니다 |
| 대상 시스템 자체의 기록 | `platform/api/loot.py`(board), `platform/api/effect.py`(corp) | 없음. OpenStack에서도 같은 컨테이너에 접근합니다. `loot.py`는 워게임 호스트의 publish된 포트로 HTTP 요청을 보내고, `effect.py`는 `corp-db`에 `docker exec`하는 runner를 거칩니다 |

## 요청의 출처

| 경로 | 발신자 | 경보에 찍히는 출발지 주소 | 마커 |
|---|---|---|---|
| 터미널, HTTP | Kali, `proxy:8081`을 거침 | 프록시, 선택한 출발지에서 | 프록시가 추가 |
| 터미널, raw TCP | Kali가 직접 | Kali, `edge`에서만 | 없음 |
| 콘솔 케이스, HTTP | 플랫폼 | 플랫폼, 선택한 출발지에서 | harness가 추가 |
| 콘솔 케이스, 도구 | 일회용 `fsl-kali` 컨테이너 | 그 컨테이너, 선택한 출발지에서 | sqlmap `--headers=` |
| CLI 실행, HTTP | 플랫폼, `redteam/run.py` | 플랫폼, `edge`에서(`board.com`이 해석되는 네트워크) | harness가 추가 |
| CLI 실행, 도구 | 일회용 `fsl-kali` 컨테이너, `launcher(<선언된 기본 출발지>)`에서 | 그 컨테이너 | sqlmap `--headers=` |
| 사이트 브라우저 | 학습자의 브라우저, 플랫폼 nginx의 8002번 포트와 `platform/api/site.py`를 거침 | 플랫폼, `edge`에서(OpenStack에서는 `mgmt`에서) | 세션의 비밀값 `browse-<hex>`, `site.py`가 설정. API에는 `browse`로 표시 |
| 고객 | `deploy/traffic/users.py`, `fsl-<id>-users` 안에서(docker) 또는 Kali VM의 `fsl-users`로(OpenStack) | 기본이 아닌 출발지에 있는 페르소나 자신의 주소. 공격자가 요청을 보내는 주소는 쓰지 않음 | 요청마다 새 UUID |

프록시는 `mitmdump` 스크립트입니다. `/label/active`의 값으로 `X-FSL-Case`를
설정하고, `/label/origin`에 주소가 있으면 원래 `Host`를 유지한 채 요청을 그
주소로 전달합니다. 두 파일은 플랫폼이 `docker exec`로 씁니다. TLS 가로채기를
하지 않으므로 프록시는 환경 변수로 지정될 뿐 아무것도 강제하지 않습니다.
`curl --noproxy '*'`로 보내면 프록시를 거치지 않습니다.

터미널은 사용자가 입력한 명령도 기록합니다. Kali의 쉘은 명령마다 현재
`/label/active` 마커를 붙여 `/var/log/fsl/commands.log`에 덧붙입니다. 플랫폼은
이 파일을 `runner("attacker")`로 읽어 `GET /api/sessions/<id>/commands/`로
제공합니다. compose에서 레드팀 콘솔은 `/terminal/<세션 id>/`를 프레임으로 띄우고,
nginx가 이를 `fsl-<id>-kali-1:7681`에 있는 Kali 자체 ttyd로 프록시합니다.
OpenStack에서는 `/vm-terminal/fsl-kali/?arg=<세션 id>`를 띄웁니다. 이는 플랫폼
안의 ttyd로, 세션 슬롯에 있는 호스트의 mgmt 주소로 ssh 접속합니다. compose에서는
Kali와 WAF에 mgmt 주소가 없으므로 `/vm-terminal/`은 연결되지 않습니다.

블루팀 콘솔의 WAF 창은 세션 API가 알려 주는 URL(`GET /api/sessions/<id>/`의
`waf_terminal`)을 프레임으로 띄웁니다. compose에서는 `/waf-terminal/<세션 id>/`입니다.
nginx가 경로에서 세션을 꺼내고 클라이언트가 보낸 쿼리는 버린 뒤, 플랫폼 안의 ttyd
(`ttyd -W -a -b /waf-terminal -i 127.0.0.1 -p 7693 /app/waf-terminal.sh`)로
`?arg=<세션 id>`를 붙여 프록시합니다. ttyd의 `-a`가 이 값을 스크립트 인자로 넘기고,
스크립트는 숫자인지 확인한 뒤 `docker exec -it fsl-<id>-waf-1 bash`를 실행합니다.
WAF 이미지에는 자체 ttyd가 없습니다. 이 경로도 같은 `auth_request /terminal-allowed`로
보호합니다. OpenStack에서는 이 창이 `/vm-terminal/fsl-waf/?arg=<세션 id>`를 띄웁니다.

블루팀 콘솔의 웹사이트 창은 콘솔 안의 브라우저입니다. 뒤로, 앞으로, 새로 고침,
전체 URL(`http://board.com/<경로>`)을 보여 주고 http에는 Chrome처럼 "주의 요함"
표시를 붙이며 URL이나 경로를 입력하고 Enter를 누를 수 있는 주소창, iframe 안의
페이지, "개발자 도구" 토글로 구성됩니다. 대상 시스템은 외부에 공개되지 않으므로
8002의 nginx가 터미널과 같은 `auth_request /terminal-allowed` 뒤에서
`/site/<세션>/<호스트>/<경로>`를 플랫폼의 기록기(`/site-proxy/<세션>/<호스트>/`,
`platform/api/site.py`, 정확한 경로와 쿼리는 `X-Site-Uri`에 담음)로 넘깁니다.
기록기는 이를 그 세션의 WAF(`fsl-<id>-waf-1:80`, 공유 `edge` 네트워크로 연결)에
`Host: <호스트>`를 붙여 보내며, 리다이렉트는 따라가지 않고 압축도 요청하지 않습니다.
넘기는 헤더는 `Accept`, `Accept-Language`, `Content-Type`, `User-Agent`, `Referer`,
`Origin`뿐입니다. `X-Forwarded-For`는 넘기지 않으므로 대상 시스템과 그 audit log에는
학습자의 LAN 주소가 아니라 플랫폼 주소가 남습니다. 존재하지 않는 세션에는 404를,
닫힌 세션에는 409를 WAF를 호출하지 않고 응답합니다. WAF가 연결 3초, 읽기 20초 안에
응답하지 않으면 내부 호스트 이름이 들어가지 않은 평문 한 문장으로 502를 응답합니다.
페이지는 도착하는 대로 브라우저에 스트리밍합니다. 8000의 nginx는 `/site-proxy/`에
404를 응답하고, 플랫폼의 POST 동일 출처 검사는 이 경로를 건너뛰므로 대상 시스템의
폼도 제출할 수 있습니다. 모든 페이지는 WAF가 판정합니다. 차단되면 WAF 자체의 403
페이지가 보이고 그 기록이 Kibana에 남습니다. 경로와 쿼리는 브라우저가 보낸 그대로
전달합니다(`$request_uri`에 대한 `map`). nginx는 접두사를 벗어나게 될 값을 고쳐
씁니다. `Location` 헤더(`proxy_redirect`), HTML 안의 `href="/`, `src="/`,
`action="/`, `http://<호스트>/`, `http://<호스트>"`(`sub_filter`, 이를 위해 업스트림에
압축하지 말라고 요청), 그리고 WordPress가 이스케이프한 `http:\/\/corp.com\/`도
고칩니다. `Cookie`와 `Set-Cookie`는 지우므로 플랫폼의 쿠키는 대상 시스템으로 가지
않고 대상 시스템의 `Set-Cookie` 헤더는 버려집니다. 따라서 이 창에서는 대상 시스템에
로그인할 수 없습니다. 다만 대상 페이지의 스크립트까지 막지는 못합니다. 그 스크립트는
플랫폼 호스트(8002번 포트)에서 실행되고 쿠키는 포트별로 분리되지 않으므로,
`document.cookie`로 8000의 콘솔이 보낼 쿠키를 설정할 수 있습니다. 현재 콘솔은 쿠키를
쓰지 않지만, 나중에 쿠키를 추가하면 이 방법으로 접근할 수 있게 됩니다. nginx는
`</body>` 앞에 `location.pathname + search`를 부모 창에 post하는 스크립트를 붙입니다.
페이지 안에서 링크를 눌렀을 때 주소창과 방문 기록이 따라가는 것은 이 스크립트 덕분입니다.

이 경로는 콘솔의 8000과 출처가 다른 별도 포트 8002에서 서비스하며, 모든 응답에
`Content-Security-Policy: sandbox allow-forms allow-scripts allow-same-origin`을
붙입니다. 대상 시스템은 레드팀이 스크립트를 심는 곳이고, 콘솔과 같은 출처라면 그
스크립트가 콘솔과 그 API를 읽고 조작할 수 있습니다. `allow-same-origin` 없는
sandbox(불투명 출처)라면 8000 하나로도 이를 막을 수 있지만, Chromium 기반 내장
브라우저는 그런 프레임을 거부합니다(Claude 데스크톱 브라우저에서
`ERR_BLOCKED_BY_CLIENT`). `SITE_PORT`는 모든 substrate에서 8002입니다. docker에서는
프록시가 세션의 WAF 컨테이너(`fsl-<id>-waf-1`)를 이름으로 지정하고, OpenStack에서는
세션마다 한 번 substrate에 그 슬롯의 `mgmt` 게이트웨이 주소를 묻습니다. 플랫폼 포트는
`fsl-mgmt`를 거쳐 이 주소에 연결됩니다. 세션 API는 `site: {port, path}` 또는
`null`을 주며, 이 값이 없으면 콘솔은 창을 숨깁니다. 플랫폼 템플릿의 security group이
8002를 엽니다(`docs/OPENSTACK.md` §3.5).

기록기는 세션마다 마지막 요청 200개를 플랫폼 메모리에 보관합니다(재시작하면
사라집니다). 메서드, `http://<호스트><경로>`, 상태 코드, WAF 차단 여부(403), 소요 시간,
요청·응답 헤더, 그리고 각각 64 KB로 자른 본문입니다(응답은 스트리밍하면서 앞 64 KB만
남깁니다). 세션이 닫히면 그 세션의 요청을 지웁니다.
`GET /api/sessions/<id>/site/requests/?after=<id>`가 목록을, `.../site/requests/<id>/`가
요청 하나의 전체 내용을 줍니다. 개발자 도구 패널은 페이지 아래에 붙어 있고(위쪽
가장자리를 끌어 높이를 조절합니다), 패널이 열려 있고 탭이 보이며 세션이 열려 있는
동안 2초마다 목록을 가져옵니다(닫힌 세션은 409를 응답하고 폴링이 멈춥니다). 목록에는
메서드, URL, 상태 코드(403은 빨간색과 "WAF 차단"), 시간이 나옵니다. 행을 선택하면
양쪽 헤더, 요청 본문, 응답 본문이 앞 2000자까지 "더 보기"와 함께 나옵니다.
"소스 보기"는 주소창에 있는 페이지의 기록된 본문을 보여 줍니다. 패널에는 쿠키를
보관하지 않는다는 안내가 있습니다.

브라우징 요청에는 세션 자신의 비밀값(`Session.browse_marker`, `browse-`와 무작위
16진수 32자리, 세션을 만들 때 생성)이 마커로 붙고(브라우저가 보낸 `X-FSL-Case`는
기록기가 덮어씁니다), 요청은 플랫폼의 `edge` 주소에서 발생합니다. 이 요청의 경보도
다른 경보와 똑같이 수집되고 목록에 나오므로 학습자는 Kibana와 `/detections/`에서
찾을 수 있습니다. 그러나 `/score/`는 재실행(`views.REPLAY_MARKS`)을 빼는 것과 같은
방식으로 그 세션의 비밀값이 붙은 탐지 기록을 뺍니다. 브라우징은 케이스가 아니므로
정탐도 오탐도 아니고, 출처를 알 수 없는 경보도 아닙니다. 손으로 보낸
`X-FSL-Case: browse`는 알 수 없는 마커일 뿐이어서 점수에 들어가며,
`POST /api/attacker/label/`은 `browse`로 시작하는 label을 거부합니다. API는 비밀값을
보여 주지 않습니다. `/detections/`, `/api/detections/<id>/`(`raw` 포함), 네트워크
패널에는 그 자리에 `browse`가 나옵니다. Kibana에는 비밀값이 보이는데, Kibana는
블루팀의 도구입니다. 레드팀 콘솔에는 사이트 창이 없습니다.

콘솔 HTTP 케이스는 출발지를 선택했는지와 관계없이 세션 워게임의 `Host`인
`board.com`을 싣습니다. 출발지를 선택하면 트래픽은 그 출발지 네트워크에 있는 WAF
주소로 IP를 지정해 보냅니다. 이름은 `edge` 네트워크에서 해석되며, 출발지가 없으면
플랫폼은 이 네트워크를 씁니다. 에지 네트워크는 공유되므로 그 안에서 `board.com`은
모든 세션의 WAF로 해석됩니다. 그래서 세션을 열 때 플랫폼은 세션의 프록시가 그
세션의 WAF를 향하게 하고, 실행하는 도구에는 그 WAF 주소를 가리키는
`--add-host board.com`과 `corp.com`을 줍니다. `rotate`는 무작위 선택이 아니라
세션별 라운드 로빈입니다.

콘솔 도구 케이스는 출발지의 대상 URL을 향하고, 출발지를 선택하지 않았으면 선언된
기본 출발지에서 `TARGET_URL`(`http://board.com`)을 향합니다. 대상 시스템은 호스트에
publish되지 않으므로 명령줄 harness도 훈련 환경 내부에서 접근합니다.
`redteam/run.py`는 플랫폼에서 실행되고(acceptance 테스트가 구동하는 방식과 같습니다),
출발지 옵션이 없으며, `--target`의 기본값은 `--cases` 파일이 속한 시나리오의
`public_url`(board는 `http://board.com`)입니다. 이 주소는 포트 80의 WAF로 해석됩니다.
`--tool-target`의 기본값은 `http://board.com`입니다.

docker에서 세션 WAF는 CRS를 `SecRuleEngine On`, anomaly 임계치 5로 실행합니다
(`session.yaml`). Paranoia Level과 룰 예외는 세션마다 따로 두며(`Session.waf`), 세션을
열 때 시나리오의 defense로 쓰고 `/api/sessions/<id>/waf/`로 바꿉니다("세션, WAF 설정
조정, 단계 엔진"). `GET`은 10초 timeout으로 파일을 읽으므로 폴링 한 번이 서버 스레드를
그보다 오래 잡고 있지 않습니다. Suricata 룰은 모두 `alert`이므로 훈련 환경에서 차단하는
것은 WAF뿐입니다. OpenStack의 WAF VM도 같은 방식으로 차단합니다
(`deploy/waf/modsecurity.conf`의 `SecRuleEngine On`, CRS 기본 임계치 5, Paranoia Level 1).

## 경보의 경로

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

`ingest/`는 `test/conftest.py`와 세션 화면의 종료 확인이 호출하고, `redteam/run.py`는
curl 명령을 출력합니다. 브라우저로 진행한 라운드는 종료 시점에 탐지 기록을 한 번
수집하며, 클릭 이후에 들어온 경보는 수집하지 않습니다.

ModSecurity의 audit log에는 요청 헤더가 있으므로 그 경보에는 마커가 바로 붙어
있습니다. Suricata의 alert 이벤트에는 요청 헤더가 없고 `http` 이벤트에만 있습니다
(`dump-all-headers: request` 설정 시. `custom: [X-FSL-Case]`는 효과가 없습니다).
수집(ingest)은 `(flow_id, tx_id)`가 같은 `http` 이벤트의 마커를 alert로 복사합니다.
`flow_id`만으로 조인했을 때는 keep-alive 연결의 모든 경보가 그 연결의 첫 케이스로
귀속되었습니다.

ingest 호출마다 다음을 수행합니다.

- 먼저 만료된 룰 예외 처리를 원래대로 되돌립니다.
- docker에서는 `fsl-logs-<session>-*`를 읽고(`ELASTIC_SESSION_INDEX`. 세션마다 자기
  Filebeat가 자기 인덱스에 씁니다), OpenStack에서는 `fsl-logs-slot<N>-*`를 읽습니다.
  OpenStack에서는 공유 수집기가 syslog 줄마다 송신자 hostname이 가리키는 슬롯(도메인
  앞의 `-N`, 없으면 슬롯 1)을 태그로 붙여 그 슬롯의 인덱스에 씁니다.
- 세션 시작 1분 전부터 종료 시각(또는 현재) 1분 후까지의 `@timestamp`를
  Elasticsearch에 요청합니다. `fsl-geoip` 파이프라인은 `@timestamp`를 이벤트 자체의
  시각(Suricata의 `timestamp`, ModSecurity의 `transaction.time_stamp`)으로 설정하므로,
  이 조회 기간은 Filebeat가 읽은 시점이 아니라 이벤트가 발생한 시점으로 이벤트를
  고릅니다.
- 오래된 것부터 한 번에 5000건씩 읽고, 결과가 잘리면 받은 것 중 가장 새로운
  `@timestamp`부터 다시 요청합니다(`api/views.py` `_fetched`, 최대 40번 더. 이미 읽은
  문서는 `_id`로 건너뜁니다). 그래도 조회 기간을 다 읽지 못하거나 5000건이 모두 같은
  시각이면 응답에 `truncated`가 실리고 세션에 `read_of`가 기록되며, 점수에
  `score.warning.truncated`가 추가됩니다. sqlmap 케이스 하나가 5000건 넘는 기록을
  남기므로, 한 번만 읽던 때는 그 뒤에 실행한 케이스가 모두 FN이 되었습니다.
- Suricata의 `alert` 이벤트는 그대로 두고, ModSecurity 기록은 매칭된 룰 메시지마다
  `Detection` 하나(id `<Elasticsearch _id>:<n>`)로 바꿉니다.
- 이벤트 자체의 시각이 조회 기간 밖인 경보는 버리고 `stale`로 셉니다.
- 나중에 찾은 마커를 마커가 없던 저장된 행에 기록합니다.
- `src_host`와 `dest_host`를 substrate의 네트워크 정보로 채우며, substrate에 접근할
  수 없으면 비워 둡니다. ingest와 `/detections/`는 단계 폴링 때마다 `docker network ls`와
  `inspect`를 실행하지 않고 세션의 네트워크 정보를 30초 동안 재사용합니다. `/top/`,
  `/map/`, `/topology/`는 매번 새로 읽습니다.

Elasticsearch는 저장과 색인 시점의 GeoIP 보강에 쓰며, 그래서 Logstash가 없습니다.
조회 기간 검색 외에는 쿼리 엔진을 쓰지 않습니다. `GET /api/sessions/<id>/map/`과
`/top/`은 SQLite 사본을 대상으로 Python에서 계산하고, `src_geo.location`은
`geo_point`가 아니라 float 두 개로 매핑합니다. `bin/worldmap`은 남위 60도에서 자른
Equal Earth 도법의 월드맵을 생성하지만, 블루팀 대시보드를 없앤 뒤로 이를 그리는 콘솔
화면은 없습니다.

geoip 프로세서 두 개(`src_ip`는 Suricata, `transaction.client_ip`는 ModSecurity)가
`src_geo`를 씁니다. compose는 관리형 다운로더를 끄고 `./config/ingest-geoip`를
bind-mount 하며, 이 디렉터리는 `bin/fetch-geoip`가 채우므로 `GeoLite2-City.mmdb`는
컨테이너를 다시 만들어도 남습니다. entrypoint가 기동 시 파이프라인을 등록합니다
(`platform/register_pipeline.py`. `kibana.py`처럼 백그라운드에서 실행하므로
Elasticsearch가 아직 올라오는 중에도 플랫폼은 서비스합니다). waitress가 스레드 16개로
127.0.0.1:8001에서 플랫폼을 서비스합니다. entrypoint는 nginx 설정을 검사하고, 그 포트가
연결을 받은 뒤에야 nginx를 시작하므로 nginx가 아직 시작 중인 플랫폼 때문에 502를
응답하는 일은 없습니다. nginx는 모든 location에 `proxy_max_temp_file_size 0`과 1 MB
요청 본문 버퍼를 설정하므로, 프록시한 응답이나 요청 본문을 임시 파일로 쓰지 않습니다.

## 세션, WAF 설정 조정, 단계 엔진

세션은 `POST /api/sessions/` `{scenario, guidance, lesson, defense}`로 열고, 이 값은
세션에 저장됩니다(마이그레이션 0015, 0022). `scenario`는 워게임(기본값 `board`)이나
시나리오 id를 가리키며, 시나리오로 열 때는 `lesson`, `guidance`, `defense`를 거부합니다
("시나리오"). 워게임에서 `defense`는 그 워게임의 `defense` 항목 중 하나를
가리키고(기본값 `full`), `guidance`(기본값 꺼짐, `lesson`을 주면 켜짐)는 워게임이
`foundations`를 선언해야 쓸 수 있으며, `guidance: false`와 함께 준 `lesson`은
거부합니다. `{"lesson": "f1"}`부터 `"f6"`까지는 해당 기초 레슨을 열고,
`{"guidance": true}`만 주면 `order`가 첫 번째인 레슨(f1)을 엽니다. 레슨은
`Session.lesson`에 저장되고 `lesson_id`로 보고됩니다. defense를 지정하지 않은 가이드
세션은 레슨에 선언된 `defense`를 씁니다. 세션의 `kind`는 `scenario`, `lesson`(가이드),
`wargame` 중 하나입니다. 저장된 레슨 id가 더는 어떤 레슨도 가리키지 않는 세션(이전
과정의 세션, `docs/DECISIONS.md` 2026-10-14)은 `lesson: null`, `lesson_id: null`로
읽히고 kind는 `lesson`으로 남습니다. 마이그레이션 0026은 `Session.mode`를 지우고
`Session.result_cache`를 비웠으므로, 저장된 결과는 레슨 판정 없이 다시 채점됩니다.
요청 본문의 `mode`는 무시합니다. board는 `minimal`(CRS paranoia level 4,
`local.rules`), `full`(paranoia level 1, 같은 `local.rules`), `ids`(paranoia level 1,
`no-uri-sqli.rules`: sid 9000001을 뺀 `local.rules`), `missed`("기초 레슨 F1-F6"),
그리고 시나리오용 방어 설정 `level2`, `level3`, `inherited`, `untuned`, `broken-rule`,
`spelled`("시나리오")를 선언합니다. 레슨마다 `defense`는 discovery 시점에 이 목록과
대조합니다. 어떤 레슨이나 시나리오도 `minimal`에서 시작하지 않으므로 `minimal`은
이름을 지정해야만 쓸 수 있습니다. `GET /api/sessions/?ids=1,2`는 세션 목록을 주어진
id로 좁힙니다. 모든 substrate에서 스택이 올라온 뒤, 세션을 여는 경로는 센서에 그
defense의 룰 파일을, defense가 없으면 `local.rules`를 넣고(`suricata.seed`), defense가
있으면 CRS 설정을 씁니다(`crs.apply`). 가이드 세션은 이어서 레슨의 `cases`를 한 번
재실행하므로(`meta.seed`, curl이 보고한 상태 코드를 기록하고 403이면 `blocked`),
학습자가 들어왔을 때 ModSecurity와 Suricata 기록이 이미 Kibana에 있습니다. 단계형
시나리오는 재실행하지 않습니다. 슬롯이 있는(OpenStack) 훈련 환경에서는 룰 파일이
`local.rules`이면 센서에 넣는 과정을 건너뜁니다. 준비 확인(readiness)이 모든 센서가 그
파일을 갖춘 뒤에야 슬롯을 내주기 때문입니다. 슬롯마다 센서가 자기 룰 파일을 따로
가지므로(2026-10-13 측정: 슬롯 1에 적용한 sid가 슬롯 2에는 없었습니다), 다른 룰 파일은
그 슬롯의 센서에만 넣습니다. 세션을 열 때 재실행을 할 수 없으면 503을 응답하고 세션을
닫습니다. 그 스택은 그대로 두었다가 다음에 세션을 열 때 내립니다.

`platform/rules/crs.py`는 설정을 `REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`로
생성합니다. 이 파일은 `crs-setup.conf` 다음, 룰보다 먼저 로드되는 CRS hook입니다.
내용은 `tx.blocking_paranoia_level`과 `tx.detection_paranoia_level`을 설정하는
`SecAction` 하나와, 항목마다 런타임 예외 규칙 하나(`ctl:ruleRemoveTargetById=<id>;<target>`
또는 `ctl:ruleRemoveById=<id>`, 경로가 있으면 `SecRule REQUEST_FILENAME "@beginsWith
<path>"`로 범위를 좁힘)이며, id는 10000~10020을 씁니다. 파일은 `runner("gateway")`로
세션의 WAF에 쓰고, `nginx -t && nginx -s reload`를 실행하며, nginx가 거부하면 이전
파일로 되돌립니다. reload 전에 없던 워커가 올라오면 반환하므로(워커 PID는 `/proc`에서
부모 PID로 찾습니다) 새 연결에는 새 설정이 적용됩니다. 이전 워커는 느린 요청을 마저
처리할 수 있습니다. 5초 안에 새 워커가 나타나지 않으면 reload가 일어나지 않은
것이므로, 이전 파일로 되돌리고 다시 reload한 뒤 요청을 거부합니다. 입력은 무엇이든
쓰기 전에 검증합니다. paranoia는 1-4, 룰 id는 900000-999999, target은 `ARGS`,
`ARGS_GET`, `ARGS_POST`, `ARGS_NAMES`, `REQUEST_COOKIES`, `REQUEST_HEADERS`(선택적으로
`:이름`을 붙임) 또는 `REQUEST_URI_RAW`(PL3에서는 한글 검색어가 이 대상에서도 920272에
매칭됩니다), 경로는 `[A-Za-z0-9_./-]`, 항목은 최대 20개입니다. 선택 항목인
`thresholds` `{inbound, outbound}`(1-100000)는 레벨과 같은 `SecAction`에
`tx.inbound_anomaly_score_threshold`와 `tx.outbound_anomaly_score_threshold`로 설정하고
다시 읽어 확인합니다. `thresholds`를 뺀 `PUT`은 현재 적용 중인 값을 유지하고,
`"thresholds": null`은 값을 지웁니다. 설정은 `PUT /api/sessions/<id>/waf/`로
바꿉니다(에이전트용 경로이며, 이를 호출하는 콘솔 화면은 없습니다). `GET`은 세션 WAF의
파일을 `crs.read`로 다시 읽습니다. `crs.read`는 Paranoia Level과 모든
`ctl:ruleRemove*` 줄을 파싱하므로(주석 처리된 줄은 건너뛰고 이어지는 줄은 합칩니다),
학습자가 설정을 조정하는 곳인 WAF 터미널에서 고친 내용도 보고합니다. 시나리오 최종
점검마다 그 구간을 판정할 때, 그리고 세션을 닫을 때마다 슬롯을 재구축하기 전에
`crs.read`가 읽은 내용을 스냅샷으로 남깁니다(`Session.waf_snapshots`, 마이그레이션 0021:
`{at, scenario_window|closed, waf}`. 이전 과정의 세션에는 VERIFY 실행에서 남은
`{at, run, waf}`도 있습니다). 가장 최근 스냅샷이 `Session.waf`이기도 하므로, 닫힌 세션은
파일을 포함해 학습자의 마지막 설정을 보고합니다(한 번도 읽지 못했으면 `file: null`).
WAF를 읽을 수 없으면 스냅샷을 남기지 않으며, 최종 점검도 세션 종료도 막지 않습니다.

조치 유형(`lesson.fix_class(waf, posture)`, 결정 D1)은 학습자가 세션에 선언된 방어
설정과 비교해 무엇을 바꿨는지를 나타냅니다. Paranoia Level이 방어 설정보다 낮으면
`level`(레벨이 없는 파일은 CRS 기본값 1로 봅니다), 그렇지 않고 anomaly 임계치가 방어
설정보다 높으면 `threshold`(설정하지 않았으면 CRS 기본값 inbound 5, outbound 4), 그렇지
않으면 방어 설정에 없던 예외 규칙이 룰 전체를 빼면 `rule`, 경로 없이 target을 빼면
`target`, 추가한 예외 규칙이 모두 경로를 지정해 target을 빼면 `path_target`, 추가한
것이 없으면 null입니다. 시나리오 최종 점검은 이 값을 판정 옆에 보고하며
(`result.fix`, `result.scenario.fix`), 이 값이 판정을 바꾸지는 않습니다.
`platform/lesson.py`에는 이 함수와 함께 단계 답을 다루는 함수(`answered`,
`rules_named`, `added_rules`, `pasted_rows`, `within`), 도움 사용 횟수, 그리고 시나리오
디브리핑에 나오는 추가·삭제한 예외 규칙과 파일 diff(`exclusions_changed`,
`config_diff`)가 있습니다.

`views.REPLAY_MARKS`(`seed`, `verify`, `check`, `replay`) 중 하나가 마커로 붙은 케이스는
`/score/`(TP/FP/FN/TN, 그 케이스가 일으킨 경보, 게임)에서 빠지고, corp의 효과 관찰이
변화를 귀속시키는 시간 구간에서도 빠집니다. 지금도 쓰는 것은 `seed`뿐이며, `verify`,
`check`, `replay`는 이전 세션에 남은 재실행이 두 점수 모두에서 계속 빠질 수 있게 목록에
남겨 둡니다.

콘솔은 화면 네 개로 구성되며, 모든 화면은 `/api/`에서 데이터를 가져옵니다(사용자가
승인한 정적 시안에 사용자 결정 두 가지를 더했습니다. `docs/DECISIONS.md` 2026-10-11,
콘솔 재설계). 색상 팔레트와 컴포넌트 클래스는 `base.html`과
`platform/console/components.css`에 있고, `bin/build-css`가 이를 `tailwind.css`에
넣습니다. 머리글에는 경로 표시(breadcrumb), 훈련 환경 상태, 언어 전환이 있습니다.

- 메인(`/`): 진행 중인 세션과 그 종류(`scenario`, `lesson`, `wargame`), 기초 레슨 세션이
  진행 중인 단계, 세션 열기가 끝났는지(`ready`, `Session.ready_at` 기준. 그 전까지는
  "준비 중 n초 / 약 80초"), `scenario.yaml`의 category, difficulty, minutes와
  `GET /api/wargames/`의 공격 케이스·정상 케이스·목표 수를 보여 주는 워게임 카드.
  카드마다 아래에 기초 레슨 묶음(레슨마다 소요 시간, 학습 내용, 시작 버튼. 시작은 레슨에
  선언된 defense로 `{scenario, guidance: true, lesson, defense}`를 보냅니다), 시나리오
  묶음("시나리오"), 그리고 일반 "워게임 시작" 버튼 하나(`[data-wargame-start]`,
  `{scenario}`를 보냄: 가이드 없이 `full` defense)가 있습니다. 기초 레슨과 시나리오마다
  이 브라우저가 연 세션(localStorage의 `fsl-opened-sessions`. 세션 화면과 블루팀 화면이
  최신순으로 최대 20개를 쓰고, `?ids=`로 읽습니다) 가운데 가장 최근 실행을 보여 줍니다.
  기초 레슨은 진행 중 또는 종료, 시나리오는 PASS/FAIL, 진행 중, 또는 최종 점검 없이
  종료입니다. 끝난 세션은 `result`를 보여 줍니다. 시나리오의 마지막 최종 점검 결과인
  PASS/FAIL(`result.scenario`), 아니면 전체 목표 중 빼앗긴 목표 수와 그중 알아채지 못한
  수입니다. 결과는 한 번 채점해 채점에 쓴 입력과 함께 저장합니다(`Session.result_cache`,
  마이그레이션 0018). 입력은 `ended_at`, 힌트 수, 탐지 기록(마지막 id, 행 수, 마커가 있는
  행 수), 케이스와 목표(각각 마지막 id, 행 수), 그리고 최종 점검마다의 판정입니다.
  목록은 세션마다 집계값 세 개만 읽고, 늦은 수집처럼 입력이 바뀐 세션만 다시 채점합니다.
  시작이 거부되면 누른 버튼 아래에 그 사실을 표시합니다. 409이면 "열린 세션 종료"가 열린
  세션을 나열하고, 각각 `ingest/` 다음 `close/`로 닫습니다. `GET /api/range/ready/`가
  `max_sessions`를 알려 줍니다.
- 세션(`/session/<id>/`): 머리글 수치(가이드 세션이 진행 중인 단계, 빼앗긴 목표, 대상
  시스템), 블루팀·레드팀 콘솔 카드, `GET /api/sessions/<id>/cases/`의 최근 케이스. 세션이
  닫히면 시나리오의 판정 배너와 디브리핑("시나리오"), 그다음 주 점수(모든 등급의 목표에
  대해 빼앗겼는지, 알아챘는지, 감점 난이도 ×1 또는 ×2), 그다음 방어 판단을 평범한
  문장으로 보여 줍니다. "공격 8건 중 7건 탐지 · 1건 미탐 (이름)", "정상 요청 4건 중 3건
  통과 · 1건 잘못 차단 (O'Brien 검색)", 그리고 케이스 하나는 경보가 몇 건이든 한 번으로
  센다는 문장입니다. TP/FP/FN/TN과 게임 밸런스는 API에만 있고, 사람이 읽는 문구에는
  나오지 않습니다(`test_strings.py`). "같은 시나리오 다시 시작"(레슨에서는 "같은 레슨 다시
  시작")은 같은 시나리오, 같은 레슨(`lesson_id`가 있으면
  `{scenario, guidance: true, lesson, defense}`), 또는 같은 워게임을 다시 엽니다.
- 블루팀(`/blue/<id>/`): 왼쪽 메뉴(Kibana, 웹사이트, 구성도, `judgement` 시나리오의
  경보, `detection`·`unknown` 시나리오의 IDS 룰, WAF, 레드팀 화면으로 가는 링크)와 창.
  WAF 창의 배너에는 WAF 박스(`waf_box`, `fsl-<id>-waf`)와 CRS 룰 디렉터리(`waf_rules`,
  `crs.EXCLUSIONS`에서 계산)만 나옵니다.
- 레드팀(`/red/<id>/`): 위쪽에 목표(한국어 이름은 `objective.<key>`)와 "탈취한 해시
  제출", 공격과 정상으로 묶고 마지막 실행 결과를 붙인 케이스 목록, 나머지 영역은 Kali
  터미널입니다. 화면 폭이 좁으면 패널이 세로로 쌓이며, 레드팀·블루팀 화면은 가로로
  스크롤되지 않습니다.

가이드 세션(기초 레슨이나 단계형 시나리오)에서 레슨 노트는 창의 오른쪽 위에 떠
있습니다(사이트 툴바나 WAF 배너가 보이면 그 아래, 40 px에 8 px를 더한 위치). 기본은
알약 모양("레슨 노트 · 단계 n/N")으로 접혀 있고, 펼치면 너비 360 px에 탭 네 개가
있습니다. 단계(현재 단계, 이전/다음, 바로 이동할 수 있는 전체 단계 목록), 목표(요약,
완료 조건, 즉 단계 목록 또는 시나리오의 목표와 측정 방법, 그리고 네 문단), 이론,
힌트입니다. 목표 한 줄(`<text>.summary`)은 머리글 아래, 탭 위에 고정됩니다. 노트는
학습자가 펼칠 때만 펼쳐지며, 펼친 상태에서 다른 단계로 이동하면 단계 탭을 보여 줍니다.
브라우저가 세션의 블루팀 콘솔에서 한 레슨을 처음 열 때(`fsl-lesson-landed-<id>-<lesson>`)는
노트가 목표 탭으로 펼쳐지고, 기초 레슨이면 카드가 펼쳐진 이론 탭으로 펼쳐집니다. 그
뒤로는 화면을 불러올 때마다 접힌 상태로 시작합니다. 사용자별로 localStorage에 남는
것은 탭(`fsl-lesson-note`)과 보고 있던 단계(`fsl-lesson-step-<id>-<lesson>`)뿐이며,
메인과 세션 화면은 이 값을 읽어 "단계 n/N"을 표시합니다. 진행 상황 자체는 세션에
레슨별로 저장합니다(`Session.lesson_steps[<lesson>][<step>]`, 마이그레이션 0020과
0027). 단계마다 `reached`, `passed`, `skipped`(시각), `hint`(보여 준 힌트 단계, 0-4)를
남기고, 세션의 현재 레슨 것을 `GET /api/sessions/<id>/`와 모든 단계·힌트 응답의
`progress`로 보고합니다. 단계 기록에는 그 단계에서 얻은 것도
실립니다. 단계에 진입하면 `command`, 힌트 단계가 3(`lesson.ANSWER`)이 되면 `answer`,
통과하면 `line`이며, 뒤의 둘은 `{en, ko}` 형태입니다.
`POST /api/sessions/<id>/lesson/steps/<step>/ {state: reached|skipped}`는 단계에
진입했음(`kali` 단계는 이때 마커도 받습니다) 또는 통과하지 않고 넘어갔음을 기록합니다.
콘솔은 통과하지 않은 단계에서 다음을 누르거나 목록으로 이동할 때 `skipped`를 보내고,
이전을 누르거나 통과했을 때는 보내지 않습니다. 단계 목록은 `progress`가 통과라고 할
때만 체크 표시를 하고, 통과하지 않고 넘어간 단계는 빈 원과 "건너뜀"으로 표시하며, 목록
위에 "N단계 중 n단계 통과"를 보여 줍니다. 이론 카드가 `shows`로 가리키는 단계는
팝오버에 그 카드를 여는 "설명 보기" 링크가 붙습니다.

이론 탭에는 레슨의 접힌 카드가 있습니다(`scenario.yaml`의 `theory`, 문구는
`<text>.theory.<card>.title|body`). 화면의 요소를 가리키는 카드에는 "화면에서 위치
보기"가 있어 가이드를 그 단계로 옮깁니다. 힌트 탭은 추론 과정만 담아 하나씩 접어
둡니다(`hints`, 문구는 `<text>.hint.*`. 단계형 시나리오의 목록은 비어 있는데, 그 힌트는
시나리오가 제안하기 때문입니다). 그 아래에는 접힌 풀이가 있고, 모든 단계의 명령이
순서대로 복사 버튼과 함께 들어 있습니다.

단계는 레슨에 선언합니다(`scenario.yaml`에서 기초 레슨이나 단계형 시나리오의 `steps`).
`id`, `kind`가 `click`, `answer`, `choice`, `rules`, `sent`, `kali`, `loot`, `triage` 중
하나인 `check`(`wargames.CHECK_KINDS`, discovery 시점에 검증), 그리고 단계에 따라
Kibana `query`나 터미널 `command`를 둡니다. `command`의 `{waf_rules}`는
`wargames.lesson`이 선언된 예외 파일(`settings.FSL_WAF`)로 바꿉니다. 세션 API는
`query`가 있는 단계에 `discover` 링크를 더하고(`kibana.discover_path(..., narrowed)`),
check는 `kind`만 보여 주며, 그 외에는 choice의 `options`, `sent` 단계의 `match`,
`kali` 단계의 `case`만 보여 줍니다. `accept` 목록이나 정답 규칙은 브라우저로 가지
않습니다. 단계의 `command`는 `progress`에 그 단계 진입이 기록된 뒤에야 응답에 들어갑니다.
정답 문구(`<text>.answer.<step>`)와 통과할 때 보여 주는 문장(`<text>.line.<step>`)은
`strings.html` 끝의 `{% comment %}` 구역에 있어 Django가 렌더링하지 않습니다.
`console/strings.py`가 이를 읽고, 학습자가 얻은 시점에 단계의 `progress` 기록에
실으므로 화면의 문자열 표에는 둘 다 없습니다. 이론 카드와 힌트 카드는 처음부터 화면에
있고 일부는 답을 알려 줍니다. 이것이 이론 탭과 힌트 탭이 주는 도움입니다. 각 단계는
check를 통과하면 넘어가며, 이전/다음은 check를 거치지 않고 이동하는 방법으로 남아
있습니다.

`answer`나 `choice`는 입력한 텍스트가 허용 값 중 하나와 대소문자 구분 없이 같으면
통과합니다(`lesson.answered`. `known`에 있는 값에는 따로
`<text>.wrong.<step>.<value>` 사유가 있습니다). 허용 값은 `accept` 목록이거나 `of:`로
세션의 기록에서 읽습니다("기초 레슨 F1-F6"). `of: rule`(`wargames.ANSWERS_OF`)은 요청의
`path`를 받고, 학습자 자신의 요청이면 `marker: browse`도 받습니다. 플랫폼은 최근
600초를 수집하고, 그 요청에 대한 세션의 ModSecurity 탐지 기록을 모은 뒤 CRS 합계 룰
(949, 959, 980으로 시작하는 id)을 빼고, 남은 `ruleId`를 모두 허용 값으로 받습니다
(`lesson.rules_named`). 기록된 것이 없으면 사유는 `lesson.check.unrecorded`입니다.
`rules` 단계는 완료 조건이 `detected_by`인 레슨(3.1)에 있으며, 센서의 룰 파일
(`GET /api/rules/`)에 방어 설정의 룰 파일에 없는 sid나 내용이 다른 sid가 생기면
통과하고(`lesson.added_rules`, `suppress.sids`) `added`로 응답합니다. `triage`
(`judged: customer | attack | all`)는 학습자가 옳게 판정하면 통과합니다("시나리오").
`click`은 콘솔이 보내는 대로 인정합니다.

모든 check는 플랫폼이 판정합니다.
`POST /api/sessions/<id>/lesson/steps/<step>/check/`(답, 선택지, 붙여 넣은 표는
`{answer}`, 백그라운드 폴링은 `{poll: true}`)가 `passed`를 기록하고
`{passed, reason, hint, hints, progress}`로 응답합니다(`rules` check는 `added`, `kali`
check는 `kali`, `loot` check는 `loot`도 함께 응답합니다). `reason`은 값이 딸린
`strings.html` 키입니다. 폴링이 아닌 check가 실패하면 오답으로 세고, 오답이 두 번이면
그 단계의 힌트 단계를 올리고 힌트를 기록합니다. 단계형 시나리오에서는 그 대신
시나리오의 다음 힌트를 제안합니다(`scenario_run.stuck`).

check는 자동으로 실행되며, `kali` 단계의 "실행 결과 확인" 버튼만 예외입니다. `sent`와
`triage`는 그 단계가 보이고 탭이 보이며 세션이 열려 있는 동안 5초마다 폴링합니다(세션이
닫혔는지는 화면이 30초마다 세션을 다시 읽어 알아챕니다). `sent`는 웹사이트 창에 단계의
`match`와 맞는 경로가 나타나고 1.5초 뒤에도 실행되고, `rules`는 룰 편집기가 파일을 적용할
때 실행됩니다. 팝오버의 상태 줄은 "확인 중…", 그다음 아직 빠진 것(`<text>.fail.<step>`)을
보여 주고, 통과하면 "✓"와 찾은 것(`<text>.ok.<step>`)을 보여 줍니다. 1.2초 뒤 가이드가
다음 단계로 넘어가며 통과한 단계의 한 줄을 보여 줍니다. `kali` 단계도 마찬가지이며,
그다음 단계가 Kali 단계의 결과 행(센서별로 기록한 요청 수와 Kibana 링크)을 보여
줍니다. 화면을 다시 불러온 뒤에는 Kali check를 폴링해 다시 읽으므로, F5의 다음
단계가 그 수를 묻는 동안 숫자가 화면에 남아 있습니다. 마지막 단계에서 기초 레슨은
"레슨을 완료했습니다. 다음 레슨: <제목>"을 보여 주고 다음 레슨으로 넘어가며("한
세션에서 F1부터 F6까지"), 단계형 시나리오는 "레슨을 완료했습니다."를 보여 줍니다. 틀린 답에는 무엇이 틀렸는지 알려 줍니다. 최근 수집
(`within`)은 조회 기간의 가장 새로운 기록부터 읽고 잘림을 기록하지 않습니다. sqlmap
케이스 하나만으로도 기록이 5000건을 넘기 때문입니다.

단계의 터미널 명령은 절대 경로만 씁니다. 다시 연 ttyd는 새 쉘에서 시작하기
때문입니다(f6의 명령은 `cat {waf_rules}`). 명령 텍스트는 "명령 보기" 아래에 접혀
있습니다. "터미널에서 실행"은 필요하면 WAF 창을 열고, ttyd의 `term`과 쉘 프롬프트(마지막
줄이 `$`나 `#`로 끝남, 최대 30초)를 기다린 뒤 `term.paste(command + "\n")`, 이어서 `term.input("\r")`을 호출합니다. bash는 bracketed
paste의 줄바꿈을 텍스트로 남겨 두기 때문입니다. OpenStack의 WAF 창은 ssh 로그인이라
프롬프트가 `term`보다 10초쯤 늦게 나오고, 그 전에 붙여 넣은 명령은 사라집니다. `kali` 단계의 명령은 학습자가 레드팀
콘솔의 Kali 터미널에 직접 입력하며, 실행 버튼이 없습니다.

도움은 단계마다 힌트 단계를 따라 올라갑니다(`<text>.nudge.<step>`은 화면에서,
정답은 단계의 `progress.answer`에서 가져옵니다). 첫 귀띔(nudge), "빨간 상자로 표시한
곳을 확인해 보세요.", 정답, "건너뛰기" 순서입니다. "힌트 보기" 버튼을 누르거나 오답 또는
check 실패가 두 번 쌓이면 한 단계 올라갑니다. 누를 때마다
`POST /api/sessions/<id>/lesson/hints/ {step, level: "hint"}`가 그 단계의 `hint`
레벨을 올리고, 첫 번째 것은 레슨과 함께 `Session.hints`에 기록됩니다(`{lesson, step,
level}`, 마이그레이션 0017과 0027. 가이드
세션이 아니거나 레슨에 없는 단계·레벨이면 400, 닫힌 세션이면 409). 한 단계에서 60초가
지나면 버튼이 "새 힌트 보기"로 바뀔 뿐이며, 학습자가 누르기 전에는 아무것도 기록하지
않습니다. "건너뛰기"(`lesson.SKIP_OFFERED`, 힌트 단계의 마지막 칸)는 다음과 같습니다.
`POST /api/sessions/<id>/lesson/steps/<step>/ {state: skipped}`를 보내고 다음 단계에
진입하며, 마지막 단계에서는 건너뜀을 기록한 뒤 기초 레슨이면 통과했을 때처럼 다음
레슨으로 넘어가고, 단계형 시나리오면 팝오버를 닫습니다. 플랫폼이 학습자를
위해 자동으로 입력하거나 실행하거나 적용하거나 통과로 인정하는 것은 없습니다. 그래서
건너뛴 단계의 기록을 읽는 뒤 단계(보내지 않은 요청에 대한 답, 하지 않은 실행의 탈취
데이터)는 학습자가 그 단계를 하거나 그 단계도 건너뛸 때까지 답할 수 없습니다. 건너뛴
단계는 `progress`를 보고 단계 목록에 표시되며, `result.scenario.helped`(`["hint"]` 또는
없음)에 따라 메인 화면과 닫힌 세션 화면의 PASS·FAIL 옆에 "힌트 사용"이 붙습니다.

"직접 해 보기"(단계 목록 아래 체크박스, `fsl-lesson-stretch`)를 켜면 필터 버튼과 실행
버튼이 사라지고 명령이 펼쳐집니다. 학습자가 KQL을 직접 쓰고 명령을 직접 입력합니다.
check는 같습니다. 필터 버튼은 단계의 `discover` 링크를 Kibana 프레임에 열고, 같은
링크에서 다시 누르면 프레임을 새로 고칩니다(`showInKibana`). 같은 주소로 이동하는 것은
fragment 이동이라 Discover가 데이터를 다시 가져오지 않고, WAF 기록은 요청 후 약 6초가
지나야 검색되기 때문입니다.

각 단계가 가리키는 위치는 `scenario.yaml`에 있는 그 단계의 `point`입니다(`panel`,
대체용 `first`를 붙일 수 있는 `kibana`, 또는 `pane`; `opens`). 그래서 콘솔 코드에는
특정 레슨의 단계도 Kibana selector도 들어 있지 않으며, 빨간 상자는 모든 단계에서
처음부터 그려집니다. 단계는 필요한 창을 지정합니다(`opens`: site, Kibana, topology,
triage, rules, WAF). 그 창이 보이지 않는 동안 상자는 왼쪽 메뉴의 버튼에 있고, 팝오버는
"왼쪽 메뉴에서 웹사이트를 여세요."(또는 해당 창 이름)만 보여 줍니다. 창이 보이면 상자는
콘솔 요소(`panel`: 사이트 주소창, 사이트의 개발자 도구 토글, 경보 목록, 룰 편집기, 최종
점검 시작 버튼), 같은 출처 Kibana 프레임 안의 `data-test-subj`
(`docTableExpandToggleColumn`, `field-status`, `field-source_ip`, `field-rule_id`, 그리고
`first`로 지정한 행 펼치기 토글), 또는 창 전체(`#pane-body`, 어느 창이 열려 있든 창이
그려지는 영역: Kibana와 WAF 프레임, 사이트 프레임, GNS3 구성도, 판정 목록, 룰 편집기)를
가리킵니다. `kibana`와 `first`는 유일한 같은 출처 프레임인 Kibana 프레임에서만 찾으므로,
이를 쓰는 단계는 `opens: elk`를 지정합니다. 사이트 프레임과 GNS3 웹 UI 프레임은 각각
다른 출처(자기 포트)이므로 그 안은 찾지 않으며, 그 창의 단계는 창 전체를 가리킵니다.
`test_every_point_a_foundation_or_scenario_step_names_resolves_on_the_blue_console`이
모든 기초 레슨과 단계형 시나리오의 모든 `point`를 렌더링된 콘솔에 맞춰 검사합니다.
현재 단계의 설명과 이전/다음은 팝오버 한 곳에만 있습니다. 레슨 노트의 단계 탭은 단계
목록을 보여 주면서 현재 단계에 "진행 중"과 상태를 표시하고, 팝오버를 닫은 뒤에만
"가이드 다시 보기"를 보여 줍니다. 팝오버는 driver.js 방식입니다. 대상에 화살표로
붙어 대상의 아래, 위, 왼쪽, 오른쪽에 놓이며(주소창처럼 480 px보다 넓은 대상이면 그
오른쪽 끝 아래), 펼친 레슨 노트와는 겹치지 않고, 터미널 단계에서는 창의 오른쪽 아래에
놓입니다. 상자는 `pointer-events: none`이며 애니메이션 프레임마다 위치를 다시 잡습니다.
약 2초 동안 대상이 없으면 팝오버가 어디를 봐야 하는지 알려 주고 그 단계가 쓰는 창의
이름을 보여 줍니다(`lesson.coach.missing`, `{0}`은 그 창의 왼쪽 메뉴 이름). 이론과
힌트는 이 흐름 밖에, 레슨 노트 안에 남아 있습니다.

룰 편집기(`#lesson-rules`, 결정 D3)는 블루팀 콘솔의 IDS 룰 창에 있으며, `rulesPane()`이
`detection`이나 `unknown` 유형의 시나리오에서 이 창을 보여 줍니다.
`GET /api/rules/?session=<id>`로 읽고, `POST /api/rules/validate/`로 검사하며, 불러온
버전을 기준으로 `POST /api/rules/apply/`로 씁니다. 룰 검사는 `errors`로 응답합니다.
거부한 모든 센서의 출력에서 Suricata `Error`가 들어 있는 줄들이며, `output`은 그런 줄이
가장 많은 거부 센서의 출력입니다. OPNsense 에지의 Suricata는 syslog로만 로그를 남기므로
(템플릿에 콘솔 출력이 없습니다) `-T` 출력에 오류 줄이 없고, 워게임 호스트의 estate
센서는 오류 줄을 출력합니다.

### 기초 레슨 F1-F6

`docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`의
P2 단계입니다. board의 `scenario.yaml`은 `foundations:` 목록을 선언하고, 이 목록은
discovery 시점에 검사합니다(id는 기초 레슨과 시나리오 전체에서 유일해야 함,
`wargames.checked_groups`). 가르치는 레슨은 기초 레슨이고, 단계형 시나리오 1.1과
3.1도 같은 엔진에서 단계를 실행합니다. `wargames.foundations()`는 기초 레슨을
`order` 순으로 나열합니다. `wargames.lesson(lesson_id=...)`은 기초 레슨이나 단계가
있는 시나리오를 찾고, 그 밖의 id는 거부하며, 기초 레슨에는 `group: foundations`를
붙입니다. `GET /api/wargames/`는 `foundations`를 나열합니다
(`wargames._foundation_card`: `id`, `order`, `title`과 `goal` 문자열 키, `minutes`,
`level`, `defense`, `prerequisites`, 단계 수, 그리고 레슨이 가르치는 내용의 문자열
키인 `learns`). 메인 페이지는 기초 레슨을 "기초" 아래 맨 앞에 소요 시간, 학습 내용,
시작 버튼(해당 레슨을 안내와 함께 엽니다)과 함께 보여 줍니다. 모든 레슨은 열 때
`board-normal-search`를 시드로 재생합니다. 첫 방문 때 기초 레슨의 레슨 노트는 그
레슨의 하나뿐인 설명 카드(이론, 펼친 상태)에 놓입니다.

| 레슨 | defense | 학습자가 하는 일 | 답을 읽는 곳 |
|---|---|---|---|
| f1 실습용 네트워크 구성도 읽기 | `full` | 구성도 창을 열고, 고객 요청을 가장 먼저 받는 호스트, 로그를 저장하는 호스트, 데이터베이스가 연결된 스위치를 답합니다 | 세션 워게임에 대한 substrate의 학습자용 구성도와 선언(`topology.facts`, `topology.learner`를 거쳐 구성도에 표시되는 이름으로): `internet` 스위치에 링크된 첫 `edge`, `gateway` 또는 `wargames` 호스트(OpenStack은 `firewall`, Docker는 `waf`), `log-server` 노드, 워게임의 데이터베이스 노드가 링크된 스위치(OpenStack은 `sw2`, Docker는 `sw1`) |
| f2 웹 요청 보내고 상태 코드 확인하기 | `full` | 웹사이트 창에서 한국어로 검색하고, 개발자 도구에서 상태 코드를 읽습니다(구성도상의 홉은 이론 탭에서 설명하며, 이를 확인하는 단계는 없습니다) | 학습자가 웹사이트 창에서 보낸 요청: 상태 코드 |
| f3 HTTP 요청 읽기 | `full` | 같은 요청의 메서드, 경로, 파라미터, 상태 코드 분류 | 같은 요청 기록 |
| f4 Kibana에서 로그 찾기 | `full` | Kibana에서 한국어 검색 요청을 찾고(경보만이 아니라 모든 기록에서) 어느 엔진이 기록했는지 답합니다. `<script>alert(1)</script>`를 보내고 WAF의 기록을 찾아 `status`와 `source_ip`를 읽습니다 | 요청을 기록한 엔진(http 기록, 탐지 기록), 요청의 상태 코드, WAF 탐지 기록의 `src_ip` |
| f5 SQL 인젝션 공격 로그 분석 | `full` | `' OR 1=1--`를 보내고, 요청을 막은 호스트는 개발자 도구의 차단 배지로, 요청을 탐지한 룰은 Kibana의 WAF 기록으로 찾아 답합니다. 레드팀 콘솔의 Kali 터미널에서 sqlmap을 실행하고 보낸 요청 수를 답합니다 | 요청 기록의 차단 표시(구성도의 게이트웨이, `waf`), 요청의 ModSecurity 규칙 ID(949110은 따로 설명), 실행 마커가 붙은 센서의 http 기록(10% 이내) |
| f6 계정 유출 확인 | `missed` | WAF의 예외 파일을 읽고, 같은 sqlmap을 실행하고, 덤프한 테이블을 붙여 넣은 뒤, 유출된 계정 수와 첫 번째 점수가 잃은 것으로 센 목표 수를 답합니다 | 적용 중인 WAF 파일, 세션 스냅샷과 대조한 탈취 데이터, `result.objectives.lost` |

`missed`는 CRS paranoia level 1에 `ruleRemoveById` 949110과 959100, 그리고
`local.rules`입니다. 레슨 질문 중 `accept` 목록을 가진 것은 없습니다.

한 세션에서 F1부터 F6까지. `POST /api/sessions/<id>/lesson/ {"lesson": "<id>"}`는
열려 있는 가이드 세션을 그 자리에서 다른 기초 레슨으로 옮깁니다. 그 레슨이 선언한
방어 설정이 `Session.defense`와 다르면 레슨의 CRS 설정을 쓰고(`PUT /waf/`처럼
`crs.apply`), 센서 룰 파일은 방어 설정의 룰 파일이 바뀔 때만 다시 넣습니다. 그다음
`Session.lesson`과 `Session.defense`를 바꾸고, `Session.lessons`에 `{id,
started_at}`를 덧붙인 뒤(마이그레이션 0027. 기초 레슨을 열 때 첫 항목을 씁니다),
세션을 열 때처럼 레슨의 `cases`를 재생하고 세션 상세를 응답합니다. 닫힌 세션,
시나리오 세션, 가이드가 없는 세션은 409로, 기초 레슨이 아닌 id는 400으로
거부합니다. 상세에는 `lessons`와 `next_lesson`(`order` 순서로 다음 기초 레슨의
`{id, text}`, 없으면 null)이 실립니다. 콘솔은 다음 레슨만 제안합니다. 기초 레슨의
마지막 단계를 통과하거나 건너뛰면 코치가 "레슨을 완료했습니다. 다음 레슨: <제목>"과
"다음 레슨" 버튼을 보여 주고, 2초 뒤 전환을 요청한 다음 화면을 다시 불러와 새 레슨을
엽니다. F6 뒤에는 "기초 레슨을 모두 마쳤습니다."를 보여 주고, 수집한 뒤
`POST /close/`로 세션을 종료하고 세션 화면을 엽니다. 레슨 사이에는 아무것도
초기화하지 않습니다. 게시판의 목표 계층은 유출만 다루므로(세션을 열 때 찍은
스냅샷과 탈취 데이터를 대조) 레슨이 정답 데이터를 바꾸지 않고, 방어 설정을 바꾸는
것은 F6뿐이며 그 자리에서 적용하기 때문입니다.

레슨은 시작한 뒤에 일어난 일만 판정합니다(`views._lesson_started`, 항목이 둘 이상일
때 `Session.lessons`의 마지막 항목). `sent` check는 그 뒤 웹사이트 창에서 보낸
요청만, `rule` 답은 그 뒤 ModSecurity 기록만 셉니다. `kali` check는 단계의
`reached`와 레슨 시작 중 늦은 시각부터 센서를 읽고, `of: lost`는 그 뒤에 빼앗긴
목표만 세며, 단계의 Kibana 링크(`query`와 Kali 결과 행의 링크)도 그 시각부터
엽니다. 단계 기록은 레슨마다 따로 두므로 F2의 `search` 통과가 F3의 `search`를
통과시키지 않습니다.

학습자 자신의 행동을 따라가는 점검 종류는 세 가지입니다. `sent`는 세션의 웹사이트 창이 보관한 요청 중
디코딩한 URL이 단계의 `match` 정규식과 일치하는 요청이 있으면 통과합니다(콘솔은
창에 일치하는 경로가 표시되고 1.5초 뒤에 확인하며, 폴링도 합니다). `kali`는 케이스
파일의 도구 케이스를 지정합니다. 학습자가 해당 단계에 들어서면 마커가 생성되고, 단계의
`command`는 시나리오의 `public_url`에 대한 케이스 argv 끝에
`--headers=X-FSL-Case: <marker>`를 붙인 것입니다(`tools.tool_argv`, 하네스 자체의
표시 방식). 센서의 http 기록에 마커와 도구의 user agent가 함께 있으면 통과하고, 이
실행을 일반 악성 케이스로 기록한 뒤(`meta.kali`, 재생 표시 없음. 그래서 다른 레드팀
행동처럼 두 점수에 모두 들어갑니다) 세션을 수집(ingest)합니다. 마커를 프록시 라벨이
아니라 명령에 넣는 이유는 레드팀 콘솔을 열면 라벨이 지워지기 때문입니다. `loot`는 붙여 넣은 테이블(`tools.dumped`,
또는 `name:hash` 줄과 `| name | hash |` 줄)을 받아 `POST /loot/`와 같은 방식으로
인정하고 kali 케이스에 귀속합니다. `_credit_loot`는 일치한 계정을 귀속된 케이스에
남깁니다(`meta.loot`).

답은 `of:`로 다음 중 하나를 읽습니다. 훈련 환경 사실인 `entry`, `logs`, `segment`,
`lost`, `excluded`; `about:`이 `sent` 단계를 가리키는 `status`, `method`, `path`,
`parameter`, `status_class`, `engine`, `sensor_source`, `waf_source`, `stopped_at`(그 단계와 일치하는 가장 최근
웹사이트 창 요청); `about:`이 `kali` 단계를 가리키는 `requests` 또는 `leaked`; 또는
요청의 `path`(위)와 함께 쓰는 `rule`. 그 밖의 값은 `wargames.read_from_record`가
discovery 시점에 거부합니다. 단계는 모든 기록에 대한 Kibana 링크를 요청할 수
있습니다(`records: all`, `kibana.discover_path(..., everything=True)`).

## 점수 계산 방식

목표. board는 `loot_verified` 대상입니다. board의
`wargames/board/objectives.yaml`은 비밀(`auth_user`의 사용자 이름과 비밀번호 컬럼,
`/internal/auth-users`에서 읽음)과, 공격자가 그중 얼마나 손에 넣었는지에 따른 세
등급을 정합니다: 해시 하나(난이도 2), `admin` 계정의 해시(4), 모든 계정의 해시(5).
공격자는 해시를 빼낸 뒤 레드팀 콘솔의 '탈취한 해시 제출' 패널(`loot_verified`
시나리오에서만 표시)에서 `POST /api/sessions/<id>/loot/`로 제출합니다. 플랫폼은
제출된 `(username, hash)` 쌍이 세션 시작 시점 스냅샷과 정확히 일치할 때만, 그리고
세션이 악성 케이스를 한 번 이상 실행한 뒤에만 등급을 인정합니다. 공격이 무엇을
했는지에 대한 플랫폼 자신의 판단으로 목표를 인정하는 일은 없습니다. 정답 데이터(ground
truth)는 대상 시스템 자체의 기록이며, 탐지 장비는 이 기록을 보지 못합니다.

인정된 등급은 제출 시각이 찍힌 Objective 행이 됩니다. 제출이 악성 케이스(`case_id`)를
지정하면 그 행의 시간 범위는 해당 케이스 시작 100ms 전부터 종료 100ms 후까지이고,
지정하지 않으면 제출 2분 전부터 제출 100ms 후까지입니다.

스냅샷은 세션이 시작될 때 한 번만 만듭니다. docker에서는 계정을 읽을 수 없거나 읽은
결과가 비어 있는 board 세션을 503으로 거부하고 닫습니다. OpenStack에서는 스냅샷 없이
세션을 그대로 생성하며, 이 세션의 `POST /api/sessions/<id>/loot/`는 409로
응답합니다. 그 뒤로 board를 읽는 곳은 없습니다. `GET /api/wargames/<id>/objectives/`는
`objectives.yaml`의 등급을 나열하고, `GET /api/sessions/<id>/objectives/`는 저장된
행을 보고합니다. `POST /api/sessions/<id>/objectives/`는 관찰을 수행하며,
`loot_verified` 워게임에서는 아무 일도 하지 않습니다.

corp 워게임은 `effect_observed` 대상입니다. 공격자가 제출하는 것 없이, 대상 시스템이
자체 데이터베이스에 커밋한 행으로 채점합니다. `wargames/corp/objectives.yaml`은 읽기
채널(`estate://corp-db`, scope `wp_state`)과 세 등급을 선언합니다: 무단 관리자
계정(`rogue_admin`, 난이도 5), 자가 가입이 열린 사이트(`option_flip`, 4), 무단
콘텐츠 작성(`content_write`, 3). 세션이 시작되면 플랫폼은 기존 관리자, 감시 대상
`wp_options`, 게시된 글을 corp-db에 대한 읽기 전용 `mysql` SELECT로
스냅샷합니다(`platform/api/effect.py`). 이 명령은 네트워크가 아니라
`runner("corp-db")`로 실행합니다. `POST /api/sessions/<id>/objectives/`가 호출되면
corp-db의 바이너리 로그를 `mysqlbinlog`로 읽고, 커밋된 변경(스냅샷에 없던 사용자에게
준 `wp_usermeta` 관리자 권한, `users_can_register`/`default_role`의 `wp_options`
변경, 새로 쓰거나 덮어쓴 `wp_posts` 행) 가운데 타임스탬프가 악성 케이스의 시간 범위
안에 드는 것마다 등급을 인정합니다. board와 마찬가지로 탐지 장비는 이 읽기를 보지
못합니다.

탈취된 목표는 실행 구간이 목표의 시간 범위와 겹치는 악성 케이스에 귀속하며, 그런
케이스가 여럿이면 가장 늦게 시작한 케이스에 귀속합니다. 그 케이스가 탐지되었을 때만
목표도 탐지된 것으로 세고, 겹치는 케이스가 없는 목표는 탐지되지 않은 것으로 셉니다.
귀속은 시간만으로 정합니다. 케이스의 `takes:` 필드는 레드팀 콘솔에 표시되지만 채점에서는
읽지 않습니다.

점수의 `objectives` 블록에서 `coverage`는 전체 난이도 대비 탐지된 난이도이며, 탈취된
것이 없으면 `null`입니다. `false_positives`는 FP입니다. `damage`는 탐지되지 않은
난이도에 탐지된 난이도의 절반을 더한 값이며, 탐지되지 않은 손실이 두 배로 계산되는
방식이 바로 이것입니다.

탐지. 케이스는 케이스마다 선언한 두 전략 중 하나로 경보와 매칭합니다.

- `marker`: 경보에 케이스의 `X-FSL-Case` 값이 들어 있습니다.
- `window`: 경보의 출발지 주소가 케이스의 출발지 주소와 일치하고, 경보 시각이
  케이스의 시작과 끝 사이(앞뒤로 2초 여유)에 있습니다.

한 전략에서 다른 전략으로 대체(fallback)하지 않습니다. 마커가 유실된 marker 케이스는
window로 메워지지 않고 미탐으로 드러나야 합니다. 터미널 케이스는 둘 다 갖습니다. 점수
엔드포인트에 `?correlation=marker` 또는 `?correlation=window`를 붙이면 전략을
강제하고, 그 밖의 값은 400입니다. 이 파라미터를 넘기는 콘솔 페이지는 없으며
(`session.html`은 파라미터 없이 `/score/`를 요청합니다), 두 전략을 비교하려면
전략마다 엔드포인트를 한 번씩 호출합니다. 두 결과가 다르다면 이는 방어가 아니라 채점
방식에 대해 알려 주는 것입니다.

각 `per_case` 항목에는 `expect`와 `corroborated`가 있습니다. `corroborated`는 매칭된
경보 중 하나의 시그니처에 `expect`가 대소문자 구분 없이 나타나면 true입니다. 같은
세션에서 정상 케이스에도 매칭된 시그니처는 세지 않습니다. 케이스에 `expect`가 없으면
`null`이며, 터미널 케이스는 항상 그렇습니다. 레드팀 콘솔이 `expect`를 보내지 않기
때문입니다. 탐지되었지만 corroborated가 아닌 케이스는 `score.warning.wrong_reason`을
추가합니다.

케이스의 `expect`는 케이스를 실행할 때 케이스와 함께 저장하므로, 케이스 파일을 수정해도
끝난 세션을 다시 판정하지 않습니다. 마이그레이션 0009 이전에 기록된 행에는 저장된
`expect`가 없어 지금의 케이스 파일로 판정합니다. 경보 위험도와 룰 유형은 쓰지 않습니다.

게임. 점수의 `game` 블록은 세션이 닫힐 때까지 `{"revealed": false}`입니다. 닫힌
뒤에는 네 구성 요소와 각 가중치, 그리고 balance를 담습니다.

- speed (0.25): 악성 케이스마다 첫 번째 매칭 경보가 케이스 시작 10초 이내에 나오면 1,
  120초 이후면 0, 그 사이는 선형으로 계산하고 평균을 냅니다.
- accuracy (0.30): 재현율에서 오탐률을 뺀 값이며, 하한은 0입니다.
- coverage (0.20): 공격받은 공격 단계 중 탐지된 악성 케이스가 있는 공격
  단계(`platform/lifecycle.py`)의 비율이며, 공격받은 단계가 없으면 0입니다. `objectives`
  블록의 `coverage`와는 다릅니다.
- response (0.25): 차단된 악성 케이스 비율에서 차단된 정상 케이스 비율을 뺀 값입니다.
  어떤 케이스에 `meta["blocked"]`가 생기기 전까지는 `null`이고, 나머지 가중치를
  재정규화합니다. 아직 이 값을 설정하는 곳은 없습니다.

`attacker`는 탈취된 목표의 난이도 합이며, 탐지된 목표는 절반으로 셉니다. `damage`와
같은 합입니다. `defender`는 구성 요소의 가중 평균에 탈취된 난이도를 곱하고 FP 하나마다
1을 뺀 값입니다. `balance`는 `defender - attacker`입니다. 탈취된 것이 없으면
balance는 FP의 음수입니다. 가중치와 체류 시간은 v1 기본값입니다
(`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`).

고객. 점수의 `customers` 블록은 세션이 기록한 고객 요청(아래)을 셉니다: `sent`,
`served`(2xx와 3xx), `blocked`(403. 단, Django 자체의 CSRF 거부는 생성기가
`refused_by: "app"`으로 표시하므로 제외), `unanswered`(10초 안에 응답 없음, status 0),
`other`(그 밖의 4xx, 5xx), `alerted`(어떤 경보에 그 마커가 들어 있는 고객 요청),
`blocked_actions`. 요청 하나는 한 번만 세며, 어느 요청도 케이스가 아닙니다. 그래서
`per_case` 목록과 TP/FP/FN/TN은 바뀌지 않고, 고객 요청이 일으킨 경보는
`unattributed`에 세지 않습니다. 콘솔의 두 번째 점수는 케이스 문장 옆에 "차단된 고객
요청: M건 중 N건"을 표시합니다.

점수 엔드포인트는 읽기 전용이며 이력을 보관하지 않습니다.

## 고객 트래픽

board 세션에는 고객을 둘 수 있습니다. 세션 내내 둘러보고, 검색하고, 로그인하고, 댓글을
다는 한국 커뮤니티 사용자들입니다. 구성은 `wargames/board/traffic.yaml`에
선언합니다(사용자 수, 출발지 가중치, 시드 계정, 글 1-3, 브라우저 User-Agent, 검색어,
댓글 내용, 행동 가중치 프로필). `platform/traffic.py`가 이를 렌더링합니다. 선언된
가중치에 따라 출발지에 배분한(최대 잉여 방식) 페르소나 12명은 각자 출발지 주소, 브라우저,
언어를 갖고, 박스는 단계로 이루어진 흐름 2,000개를 순환하며 실행합니다. 로그인과 댓글은
폼 POST입니다. 흐름은 먼저 페이지를 GET하고, 박스가 그 페이지에서
`csrfmiddlewaretoken`을 꺼내 `csrftoken` 쿠키와 함께 보낸 뒤 302를 따라갑니다.
페이지에 토큰이 없으면(GET이 차단되었으면) 그 흐름은 브라우저와 마찬가지로 거기서
멈춥니다.

`deploy/traffic/users.py`가 생성기입니다. Python 표준 라이브러리만 쓰고, 여러
스레드로 계획의 속도에 맞춰 요청을 보내며, 요청마다 새 UUID 하나를 `X-FSL-Case`에
넣습니다(케이스 마커와 같은 형태라 학습자는 이 값으로 고객과 공격을 구분할 수
없습니다). 요청마다 JSON 한 줄을 `records.jsonl`에 씁니다. 계획 파일이 바뀌면 다시
읽고, 파일이 삭제되거나 SIGTERM을 받으면 멈춥니다.

| | Docker | OpenStack |
|---|---|---|
| 실행 위치 | `fsl-<id>-users`: `Docker.users_box`가 Kali 이미지로 페르소나의 출발지 네트워크에 띄우는 컨테이너이며, 라벨은 `fsl.customers=<id>`입니다. compose 서비스가 아닙니다 | 슬롯의 `fsl-kali` VM에서 시스템 계정 `fsl-users`로 실행 |
| 출발지 주소 | 출발지 네트워크마다 컨테이너 자신의 주소 | 페르소나마다 VM의 출발지 주소 중 하나에 바인딩 |
| 공격자와 분리 | 선언된 기본 출발지는 쓰지 않으며, 컨테이너의 주소는 컨테이너 자신의 것입니다 | 기본 출발지를 쓰지 않고, 공격자가 쓰는 어떤 출발지의 `source_ip`나 VM의 바인딩되지 않은 출발 주소(대상으로 `ip route get`)도 쓰지 않습니다. `POSTROUTING -m owner --uid-owner fsl-users -j RETURN`을 `FSL-ORIGIN` SNAT 점프 앞에 넣으므로 공격자의 출발지 변환은 고객에게 적용되지 않습니다 |

`platform/attacker.py`가 박스에서 실행하는 모든 명령을 담습니다: `place_customers`
(계정, NAT 예외, 프로그램 배치. OpenStack에서는 `sudo`로), `run_customers`(계획을
쓰고, 프로그램이 실행 중이 아니면 `setsid`와 `setpriv`로 시작), `stop_customers`,
`customer_records`. 프로그램은 Kali 이미지에 넣어 두지 않고 시작할 때마다 플랫폼에서
보냅니다. VM은 닫힐 때마다 골든 이미지로 재구축되는데, `deploy/kali/` 아래에 파일을 두면
그 이미지의 다이제스트가 바뀌어 이미지를 다시 빌드할 때까지 다음 재구축이 멈추기
때문입니다.

API(`platform/api/customers.py`, `views.session_traffic`):

- `PUT /api/sessions/<id>/traffic/ {rate, profile}`은 고객을 시작하거나, 실행 중인
  생성기의 속도와 프로필을 바꿉니다(페르소나는 그대로). `rate`는 초당 요청 수로 기본값
  1, 최대 50입니다. `profile`은 워게임이 선언한 프로필 중 하나입니다. board에는
  `community`(기본값), `plain`(특이한 검색 없음), `readers`(댓글을 뺀 `plain`),
  `club`(`community`에 댓글 속 코드 질문을 더함)이 있습니다. `traffic.yaml`이 없는
  워게임은 404, 닫힌 세션은 409, 박스나 출발지가 없으면 503입니다.
- `GET`은 새 기록을 먼저 읽은 뒤 `declared`, `profiles`, `running`, `rate`,
  `profile`, `started_at`, `stopped_at`, `error`, 건수 `sent`, `served`,
  `blocked`(앱이 아니라 방어 설정이 낸 403), `unanswered`, `other`, `sources`
  (출발지, 주소, 요청 수), `by_action`(행동별 보낸 수와 차단된 수)을 돌려줍니다.
- `DELETE`는 생성기를 멈추고 마지막으로 보낸 기록까지 읽습니다. 세션을 닫을 때도 슬롯을
  재구축하기 전에 같은 일을 합니다. 박스에 연결할 수 없으면 닫기는 계속 진행하고 오류를
  `traffic.error`에 남깁니다.

기록은 바이트 오프셋 기준으로 가져와(`tail -c`, 호출당 최대 1 MiB, 완전한 줄만) 호출마다
`bulk_create` 한 번으로 `CustomerRequest` 행에 넣습니다. 오프셋은 `Session.traffic`에
둡니다. 세션 페이지는 테스트용으로 URL에 `?traffic`이 있을 때만 스위치를 보여 주며,
시나리오는 고객을 스스로 시작합니다.

생성기는 board 자체의 CSRF 거부(`refused_by: "app"`, 차단으로 세지 않음)를 영어
문장뿐 아니라 Django 실패 페이지의 `<span>(403)</span></h1>`로도 구분합니다. board는
고객의 언어로 응답하므로, 한국어 사용 고객이 받는 거부(한 페르소나의 두 흐름이 로그인 시
토큰 교체와 경합한 경우)는 한국어로 옵니다.

## 시나리오

시나리오는 훈련 환경에서 시간을 정해 진행하는 실습입니다. 고객과 공격자가 board를 쓰는
동안 학습자는 실제 도구로 방어하고, 플랫폼은 마지막의 최종 점검 구간(final verification
window)으로 결과를 판정합니다. 설계는
`docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`(P4
단계)에, 결정은 `docs/DECISIONS.md`의 2026-10-13 "scenario course" 항목에 있습니다.

**기술자(descriptor).** 워게임 `scenario.yaml`의 `scenarios:`이며,
`wargames.checked_scenarios`가 검증합니다.

| 필드 | 의미 |
|---|---|
| `id`, `order` | `1.1`, `2.1`, ...; id는 기초 레슨과 같은 네임스페이스를 씁니다 |
| `task_class` | `judgement`, `availability`, `detection`, `unknown` 중 하나 |
| `guidance` | `worked`(`steps`를 선언할 수 있으며 단계 엔진에서 실행), `faded`, `none` |
| `text`, `briefing` | 문자열 키 접두어. `briefing`은 `situation`, `goal`, `measured_by`를 문자열 키에 연결합니다 |
| `minutes`, `window_minutes` | 시나리오 길이와 최종 점검 구간 길이 |
| `defense` | 워게임 `defense:` 맵에 있는 방어 설정 하나(CRS 수준, 예외 규칙, 임계치; Suricata 룰셋) |
| `traffic` | 고객용 `{profile, rate}`(`traffic.yaml`) |
| `red` | `schedule`(기본값) 또는 `person`: 사람이 레드팀 콘솔을 쓰며, 시나리오에 공격을 하나도 선언하지 않아도 됩니다 |
| `attacks` | `[{at, case, origin}]`: 연 뒤 몇 초(`minutes` 이내), 악성 케이스, 선택 사항인 출발지. 학습자에게는 보이지 않습니다 |
| `completion` | 종류별: judgement `{judged: all}`, 선택으로 `pattern: judged`; availability `{served: all, held: all}`, 선택으로 `thresholds: {inbound, outbound}`; unknown `{served: all, held: all}`; detection `{detected_by: suricata}` |
| `cards` | `[{id, when}]`, `when`은 `start`, `alert`, `blocked`, `window` 중 하나 |
| `hints` | 한 번에 하나씩 제안하는 힌트 id |

`GET /api/wargames/`는 각 시나리오의 카드(`wargames.scenario_card`)를 `attacks` 없이
나열합니다. `GET /api/sessions/<id>/`는 단계형 시나리오의 `lesson`에서 `attacks`와
`completion`을 빼고 `cases`를 비웁니다.

**열기.** `POST /api/sessions/ {"scenario": "2.1"}`은 시나리오 id로 워게임을 찾고,
`lesson`, `guidance`, `defense`는 거부하며, 다른 세션과 마찬가지로 선언된 방어 설정을
적용합니다. 그다음 `scenario_run.begin`이 고객을 시작하고 `Session.scenario_state`
(마이그레이션 0025, `Session.course_scenario` 옆)를 씁니다. 여기에는 공격마다 절대 예정
시각을 붙인 일정, 점검 구간, 판정 결과, 힌트 제안, 지금까지 확인한 WAF 버전이
들어갑니다. 단계형 시나리오는 `guidance`를 true로, `lesson`을 자기 id로 설정하므로
단계는 재생 시드 없이 `/lesson/steps/`에서 실행됩니다. 고객을 시작하지 못하면 세션을
닫고 503을 돌려줍니다.

**엔진**(`platform/api/scenario_run.py`, 순수 규칙은 `platform/scenarios.py`)은 플랫폼
프로세스 안의 스레드 하나입니다. 첫 시나리오가 열릴 때, 그리고 부팅할 때 `fsl/wsgi.py`가
시작합니다(`resume`: 실행 도중 중단된 공격을 다시 예정 상태로 돌립니다). 틱 하나나 그
뒤의 연결 정리가 실패하면 따로 로그를 남기며, 스레드는 끝나지 않습니다.
`FSL_SCENARIO_TICK`(2초)마다 열린 시나리오 세션 각각에 대해 다음을 합니다.

- 학습자가 점검 구간을 열지 않았으면 예정 시각(연 뒤 `minutes - window_minutes`)에
  엽니다.
- 예정 시각이 된 공격을 하나씩 가져와 워커 4개짜리 풀에서 `views._fire`로 실행하고,
  `meta.scheduled`로 표시합니다(재생 표시가 아니므로 두 점수에 모두 들어갑니다). sqlmap
  덤프는 해당 케이스에 귀속해 `views._credit_loot`를 거치므로, 첫 번째 점수는 board
  자체의 계정과 일치할 때만 손실로 셉니다. 일정 항목에는 `outcome` held 또는 leaked가
  남습니다. 케이스에는 sqlmap의 결론 줄과 403 횟수가 남고(`meta.conclusions`,
  `meta.forbidden`, 판정에는 쓰지 않음), `meta.blocked`는 403이 있었거나, 덤프한 행
  없이 정상 종료한 sqlmap이 스스로 주입 불가로 결론 낸 경우
  (`tools.found_not_injectable`)에 설정합니다. sqlmap 케이스는 해시를 크랙하겠느냐는
  sqlmap의 제안을 거절하므로(`--answers=crack=N`), 덤프한 칸에는 `loot.matched`가
  비교하는 원래 해시가 그대로 남습니다.
- `FSL_SCENARIO_OBSERVE`(15초)마다 고객 기록을 가져와 최근 180초를 수집(ingest)하고,
  `FSL_SCENARIO_WAF_POLL`(20초)마다 WAF 파일을 읽어 터미널에서 한 변경을 알아챕니다.
- 열린 점검 구간이 끝났고 그 안에 예정된 공격이 모두 실행되었거나 실패했으면 그 구간을
  판정합니다.

세션을 닫으면 아직 예정 상태인 공격은 취소합니다. 이미 실행 중인 공격은 끝까지 진행하고
기록합니다.

**최종 점검 구간.** `POST .../scenario/verify-window/`("최종 점검 시작") 또는 일정이
이 구간을 `window_minutes` 동안 엽니다. 엔진은 일정에 있는 공격 케이스 중 구간 안에 아직
예정되지 않은 케이스마다 하나씩 구간 안에 항목을 추가합니다. 판정 기준은 시나리오 종류의
`completion`입니다. `served`는 구간 안에서 방어 설정이 차단한 고객 요청(앱이 아닌 403)이
없어야 합니다. `held`는 구간 안의 모든 공격이 실행되었고 막혔어야 합니다(탈취 데이터 일치
없음, 영향 없음). `judged`는 구간이 열릴 때 목록에 있던 모든 항목을 맞게 판정해야
합니다(목록은 구간과 함께 보관하고, 구간 중에 내린 판정도 인정하며, 나중에 더 이른
시각으로 기록에 들어온 항목은 추가하지 않습니다). `detected_by`는 구간 안의 모든 공격이
corroborated인 Suricata 경보를 일으키고, 고객 요청은 경보를 일으키지 않아야 합니다.
`thresholds`는 구간의 WAF 스냅샷 시점에 적용 중인 CRS 이상 점수 임계치가 지정한 값
이하여야 합니다(임계치를 지정하지 않은 설정은 CRS 기본값인 인바운드 5, 아웃바운드 4로
동작합니다). `red: person`이면 구간 안에서 그 사람이 실행한, 재생이 아닌 악성 케이스도
예정된 공격과 똑같이 판정합니다. judgement 시나리오는 설계의 종류 표에 따라 판정 결과만으로
판정하므로, 구간 중에 차단된 고객은 결과 옆에 보고할 뿐 실패로 세지 않습니다. 결과에는
조치 종류가 표시됩니다(그때 찍은 WAF 스냅샷에 대한 `lesson.fix_class`: `level`,
`threshold`, `rule`, `target`, `path_target`; "세션, WAF 설정 조정, 단계 엔진" 참고).
실패한 구간 뒤에 새 구간을 열 수 있습니다.

**경보 판단**(`GET/POST /api/sessions/<id>/triage/`). 경보를 일으킨 마커마다 항목이
하나입니다. 고객 요청은 요청마다 하나, 공격 케이스는 요청을 몇 개 보냈든 케이스마다
하나입니다(케이스 하나는 판정 하나). 항목 id는 마커를 세션의 browse 마커와 함께 해시한
값이므로 `/cases/`와 대조할 수 없습니다. 항목에는 첫 경보와 마지막 경보, 경보 수, 출발지
주소, 요청 하나, WAF 판정(949/959 합계 룰이 동작했으면 `blocked`, `logged`, `none`),
상태 코드, 엔진·ID·메시지·건수가 붙은 룰 최대 12개가 표시되며, 케이스 이름이나 라벨은
절대 표시하지 않습니다. 재생 요청과 학습자 자신의 웹사이트 창 요청은 제외합니다. 판정
`{item, verdict: attack|customer, succeeded}`는 기록(케이스의 `malicious` 또는 고객
행)과 대조하고, `succeeded`는 대상 시스템(케이스에 일치한 탈취 데이터, 또는 시간 범위
안의 목표)과 대조합니다. completion에 `pattern: judged`가 있는 시나리오는 공격의
`pattern`도 묻습니다. 케이스 파일 악성 케이스의 CAPEC id 중 하나이며(시나리오 카드의
`patterns`에 나열), 케이스 자신의 `pattern`과 대조합니다. 이 값은 판정과 함께 보관하고 항목에는 표시하지 않습니다. 단계 점검 종류 `triage`(`judged: customer |
attack | all`)는 학습자의 맞는 판정으로 통과합니다.

**상태, 힌트, 결과 보고(debrief).** `GET .../scenario/`는 시나리오 카드,
`phase`(running, window, passed, failed, closed), `time_left`, 직전 1분 동안 차단된
고객과 경보가 발생한 요청(`alerted_per_minute`: 경보를 일으킨 서로 다른 마커 수. 고객
요청은 요청마다, 공격 케이스는 요청을 몇 개 보냈든 한 번), 잃은 목표, 점검 구간, 완료
조건, 표시할 카드, 힌트 제안을 돌려줍니다. 힌트는 단계 점검이 두 번 실패하거나, 같은
항목을 두 번 틀리게 판정하거나, `PUT /waf/`가 이미 적용 중인 파일을 그대로 쓰거나, 고객이
차단되는 동안 5분 동안 WAF 변경이 없으면 제안합니다(기록하지는 않습니다).
`POST .../scenario/hints/`는 다음 힌트를 열고 `Session.hints`에 기록합니다.
`GET .../scenario/debrief/`는(점검 구간이 판정되거나 세션이 닫히기 전에는 409를
돌려주므로 일정이 드러나지 않습니다) Igloo/ASEC 보고서 순서로 다음을 돌려줍니다:
`overview`(마지막 최종 점검의 판정, 조치 종류와 사유, 판정한 점검 수, 전체 단계 중 통과한
단계 수, 사용한 힌트), `evidence`(예정된 공격에서 나온 세션 자체의 탐지 기록 최대 20개.
완료 조건이 탐지기를 지정하면 그 탐지기의 기록이며, 룰·요청·케이스를 포함합니다.
Elasticsearch는 읽지 않음), `change`(선언된 방어 설정과 마지막 WAF 스냅샷의 비교: 추가·
삭제된 예외 규칙, 양쪽의 수준, 그리고 해당 방어 설정에 대해 `crs.rendered`가 생성하는
내용과 예외 파일의 줄 단위 diff), `cases`(예정된 각 케이스의 판정된 구간 이전과 구간 안
결과, held 또는 leaked), `risk`(조치 종류가 정하는 문자열 키), `customers`, 공격
`timeline`, `triage`. `at`에는 에이전트용으로 시작 시각과 마지막 판정 시각이 들어
있습니다. 콘솔은 이를 `debrief_script.html`로 블루팀 콘솔과 닫힌 세션 페이지에
렌더링합니다.

**콘솔.** 홈 페이지는 워게임마다 시나리오를 나열하고, 시작을 누르면 블루팀 콘솔이 상황
설명 화면으로 열립니다. 창 위의 띠에는 남은 시간, 분당 차단된 고객과 경보가 발생한 요청,
잃은 목표, 힌트 제안, 최종 점검 시작 버튼이 표시됩니다. judgement 시나리오에는 경보 창이 추가되며,
이 창은 목록을 가리지 않습니다. 레슨 노트의 열은 비워 두고, 카드와 연 힌트, 창 안을
가리키는 코치 말풍선은 목록 위에 붙입니다. detection 또는 unknown 시나리오에는 IDS 룰
창(`/api/rules/`를 쓰는 룰 편집기)이 추가됩니다. 카드는 정해진 때가 되면 나타나고, 구간이 판정되면 결과 보고가 열립니다. 단계형
시나리오의 단계는 레슨 노트에서 실행되며 힌트 목록은 비어 있습니다. 힌트는 시나리오의 힌트
제안으로 받습니다.

**board의 시나리오.** 시나리오 열한 개를 홈 페이지에 기초 레슨 다음으로, 과제 종류
순서대로 나열합니다(`order`).

| Id | 제목 | 종류, 안내 방식 | 방어 설정 | 고객 | 공격(비공개) |
|---|---|---|---|---|---|
| 1.1 | 고객 요청과 공격 구분하기 | judgement, worked | `level2`: PL2 | `community` 초당 2건 | 150초에 sqlmap(`ru`) |
| 1.2 | 차단되지 않은 WAF 경보 판단 | judgement, faded | `inherited`: PL2, 949110과 959100 제거 | `community` 초당 2건 | 120초에 sqlmap, 300초에 검색 인젝션(`ru`) |
| 1.3 | 공격 유형 구분하기 | judgement, none; 공격 패턴도 판정 | `inherited` | `community` 초당 4건 | 90초부터 660초까지 케이스 8개, 모두 `kr`에서: sqlmap 기본과 tamper, 검색·union·로그인 인젝션, XSS 2개, 경로 순회(path traversal) |
| 2.1 | 한글 검색 오탐 해결 | availability, faded | `level3`: PL3 | `readers` 초당 2건 | 240초에 sqlmap(`ru`) |
| 2.2 | 태그·링크 검색 오탐 해결 | availability, faded | `level2` | `community` 초당 2건 | 240초에 sqlmap(`ru`) |
| 2.3 | 이상 점수 임계치 낮추기 | availability, none; 최종 점검은 임계치 5/4 | `untuned`: PL3, 임계치 10,000/10,000 | `plain` 초당 2건 | 600초에 sqlmap(`ru`) |
| 3.1 | 탐지 룰 수정하기 | detection, worked | `broken-rule`: PL1, `broken-sort.rules`(sid 9000101이 `http.request_body`를 읽음) | `plain` 초당 2건 | 120초에 sqlmap(`ru`) |
| 3.2 | sort 공격 탐지 룰 작성하기 | detection, faded | `ids`: PL1, `no-uri-sqli.rules` | `plain` 초당 2건 | 120초에 sqlmap(`ru`) |
| 3.3 | 변형된 공격 탐지하기 | detection, faded | `spelled`: PL1, `spaced-sort.rules`(앞뒤가 공백인 SQL 단어) | `plain` 초당 2건 | 120초에 sqlmap, 300초에 tamper 변형(`ru`) |
| 3.4 | 댓글 XSS 탐지 룰 작성하기 | detection, none | `full`: PL1, `local.rules` | `plain` 초당 2건 | 120초에 댓글 XSS, 240초에 검색 XSS(`ru`) |
| 4.1 | 종합 실습 | unknown, none(카드·힌트 없음) | `full` | `club` 초당 2건(댓글에 코드 질문 추가) | 300초에 `board-sqli-orderby-sqlmap-versioned`, 600초에 sqlmap(`us`) |

PL3에서 한글 검색은 `ARGS:q`에 대한 920272와 942460에 차단되고(이 둘을 예외 처리하면
`REQUEST_URI_RAW`에 대한 920272에 차단), 한글 검색을 한 번 한 뒤 고객이 여는 모든 페이지는
`REQUEST_HEADERS:Referer`에 대한 920272에 차단됩니다. 한글 댓글은 `REQUEST_BODY`에
대한 920272와 `ARGS:body`에 대한 942460에 차단됩니다. PL2에서는 `<b>` 검색이 941320에,
유튜브 링크가 931130에 차단되며, 둘 다 `ARGS:q`에서입니다. PL1에서는 동아리의 코드
질문이 `ARGS:body`에 대한 942100, 942190, 941100, 941110, 941160에 차단됩니다.
시나리오 4.2(레드팀 콘솔을 쓰는 사람과 학습자의 대결)는 선언되어 있지 않습니다. 두 번째
사람이 필요하기 때문이며, 엔진은 `red: person`을 받습니다.

## 결정

- 워게임마다 케이스 파일 하나에 공격과 정상 트래픽을 함께 둡니다: board는
  `redteam/cases/board.yaml`, corp는 `redteam/cases/corp.yaml`. 파일을 나누면 정상
  케이스를 빠뜨리기 쉽습니다. CLI는 `--cases`로 다른 파일을 지정하지 않으면
  `board.yaml`을 읽고, `case_file`이 그 파일의 basename과 일치하는 시나리오의 세션을
  엽니다(알 수 없는 파일이면 board).
- 하네스는 재작성된 경로를 보내지 않고 거부합니다. `requests`는
  `/static/../../etc/passwd`를 `/etc/passwd`로 바꿉니다. 이대로 보내면 실제로는 나가지
  않은 공격을 기록하고, 하네스의 실패를 방어의 실패로 채점하게 됩니다. 퍼센트 인코딩
  차이는 허용합니다.
- 시작하지 못하는 도구는 예외를 발생시키고, 0이 아닌 코드로 종료한 도구는 실행으로
  셉니다. sqlmap은 아무것도 찾지 못하면 0이 아닌 코드로 종료하지만, 트래픽은 이미
  나갔습니다.
- Suricata는 Docker 호스트에 따라 의미가 달라지는 호스트 네트워킹 대신 WAF의 네트워크
  네임스페이스를 공유합니다(`network_mode: service:waf`). WAF의 인터페이스로 모든
  요청의 양쪽 구간이 지나갑니다.
- Kibana는 compose에 들어 있으며, 읽기 전용 역할이 아닌 전체 권한으로, 플랫폼이
  수집하는 것과 같은 Elasticsearch를 읽습니다. 플랫폼의 8000번 포트 `/kibana/`로
  접속하며, 자체 포트는 공개하지 않습니다. 블루팀 콘솔이 이를 프레임으로 띄웁니다. 기동 시
  `platform/kibana.py`가 `deploy/kibana/objects.ndjson`을 overwrite로 가져옵니다
  (백그라운드에서 실행하며, 먼저 `/api/status`를 확인해 응답이 온 뒤에 한 번만
  가져옵니다. Kibana에 연결할 수 없거나 502/503/504로 응답하는 동안은 재시도하고, 그 밖의
  HTTP 오류는 상태와 본문을 한 번 보고합니다. 기동 중인 Kibana는 multipart 가져오기에
  415로 응답합니다). 가져오는 객체는 `@timestamp` 기준 data view `fsl-logs-*`(runtime
  field로 Suricata/ModSecurity 필드 쌍을 각각 한 열로 합칩니다: `rule`, `rule_id`,
  `source_ip`, `destination`, `url`, `status`), "FSL alerts" 검색, "FSL overview"
  대시보드입니다. `defaultRoute`는 그 검색으로 설정합니다. data view가 있어야 Kibana의
  Welcome 화면이 나오지 않습니다. `GET /api/sessions/<id>/`는 `discover`를 담습니다.
  이는 `fsl-logs` data view 위의 저장되지 않은 Discover 상태로, 경보 검색의 열·쿼리·
  정렬을 쓰며 docker에서는 세션 인덱스(`_index : fsl-logs-<id>-*`)로, 그리고 세션의
  시간 범위로 좁힙니다. ELK 창이 이 상태를 엽니다. 이는 저장된 검색에 쿼리를 덮어쓴 형태가
  아닙니다. 그런 형태에는 Kibana가 "Unsaved changes" 배지를 붙입니다. 창이 로드되기 전에
  블루팀 콘솔은 같은 출처(same-origin)로 공유하는 localStorage에 Kibana의 첫 방문 안내를
  이미 본 것으로 표시합니다(`discover:docExplorerUpdateCalloutClosed`,
  `discover:docExplorerCalloutClosed`, `data.noDataPopover`).
- Elasticsearch는 512 MB 힙의 단일 노드이므로 전체 스택이 Docker 기본 메모리 한도 안에
  들어갑니다.
- 누락된 데이터는 0이 아니라 오류로 처리하며, 예외는 명시합니다. Elasticsearch나
  substrate에 연결할 수 없거나 룰 파일을 읽을 수 없으면 503으로 응답합니다. OpenStack의
  세션 생성은 대상 시스템에 연결할 수 없어도 진행합니다(세션은 스냅샷 없이 시작하고
  board의 `loot/`는 409로 응답합니다. docker에서는 board 세션을 503으로 거부합니다).
  케이스 실행이나 기록, 세션 닫기는 대상 시스템을 읽지 않습니다(단, 실행에 출발지나 도구
  때문에 substrate가 필요하면 503으로 응답합니다). ingest 안의 예외 처리 복원과, 경보를
  구간(segment)·호스트에 배치하는 작업(빈 결과가 나옴)은 substrate에 연결할 수 없어도
  진행하므로, 라운드는 시작하고 멈출 수 있습니다. 분모가 0인 비율은 null이 아니라
  0.0입니다: 정밀도, 재현율, F1, FPR, 그리고 게임의 speed, coverage, accuracy.
  `objectives` 블록의 `coverage`만 null입니다.
- 점수는 보증할 수 없는 부분을 밝힙니다. 정상 케이스가 없거나(`no_benign`), marker
  케이스가 있는데 마커가 붙은 경보가 하나도 없거나(`no_marker`), 출발지 주소가 없는 window
  케이스가 있거나(`no_source_ip`), 탐지되었지만 corroborated가 아닌 케이스가
  있거나(`wrong_reason`), Elasticsearch의 hit가 ingest가 읽은 것보다 많으면
  (`truncated`) 경고를 담습니다.
- 콘솔에서 실행한 케이스는 HTTP 연결 하나에 케이스 하나를 보내고, CLI는 한 번 실행하는
  동안 연결 하나를 유지합니다. 당시의 케이스 세트(케이스 12개)로 측정했을 때 두 방식의
  점수와 케이스별 경보 수가 같았습니다. acceptance 테스트는 CLI를 구동하므로 연결을
  공유하는 경로도 계속 테스트됩니다.

## OpenStack

OpenStack 구축은 `docs/STATE.md` 백로그의 OpenStack 항목을 그 순서대로 따릅니다. 아래에는
구축한 것을 설명하며, 각 항목은 클라우드에서 또는 fake를 상대로 실행해 확인했습니다. 남은
작업은 이 절 끝에 있습니다. 근거는 `docs/STATE.md`("Decided on 2026-09-30"),
`docs/superpowers/specs/2026-09-30-openstack-range-placement.md`,
`docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`에 있고, 이 절은 구조만
기록합니다.

클라우드는 ML2/Open vSwitch 위에서 kolla-ansible 2026.1을 운영하는 KVM 컴퓨트 노드 한
대(8 vCPU, 64 GB)입니다. 훈련 환경은 프로젝트 `fsl-range`에 있고, member 역할 사용자
`fsl-range`가 이를 조작합니다. 사용자에게 Horizon은 보여 주지 않습니다.

클라우드마다 달라지는 값은 모두 `deploy/openstack/cloud.yaml`에 있습니다(커밋된
`cloud.example.yaml`을 복사한 파일로, git이 무시하며 비밀 값은 없습니다): identity, 네트워크와
MTU, 베이스 이미지, zone, flavor, 키, OPNsense 릴리스, 플랫폼의 스택과 ref.
`platform/range/cloud.py`가 이 파일을 검사해 문제를 키별로 모두 보고합니다.
`bin/platform-rebuild`와 `bin/cloud`는 이 파일의 값으로 openstack CLI와 Heat 파라미터를
구동하고, 스택은 이 값을 플랫폼의 `openstack.env`에 씁니다. `bin/cloud up`은 스택을 만든 뒤
`/api/range/ready/`가 준비 상태가 될 때까지 fabric, images, slot, configure를 호출합니다.
`bin/cloud down`은 키는 남겨 두고, 저장소를 백업한 뒤(`bin/backup`, 사본은 `backups.keep`개까지
보관) slot, fabric, 남아 있는 이미지 빌더, 스택을 지웁니다. `*_FAILED` 상태의 스택은 `up`이
(빌더부터) 지우고 다시 만들며, `down`은 지웁니다.

### 구축됨: 플랫폼 VM

`deploy/openstack/platform.yaml`은 Heat 템플릿이며 다음을 만듭니다.

- 네트워크와 서브넷 `fsl-platform`
- 외부 네트워크로 나가는 라우터와 floating IP(`network.address`를 지정하면 프로젝트가 이미
  가진 floating IP를 연결만 하며, 스택을 지워도 이 floating IP는 그대로 남습니다)
- 모든 주소에 tcp/22, tcp/8000, tcp/8002, tcp/3080, ICMP를 여는 보안 그룹
- config drive를 붙인 Nova 서버 `fsl-platform`

템플릿에는 기본값이 없습니다. 모든 파라미터는 `deploy/openstack/cloud.yaml`에서 옵니다(아래,
그리고 `docs/OPENSTACK.md` §4).

cloud-init은 `docker.io`, `docker-compose-v2`, `git`을 설치하고, 4 GB 스왑을 추가하고,
Docker의 MTU를 Neutron 네트워크의 MTU에 맞춥니다. 기본 브리지는 `mtu`로, compose가 만드는
것을 포함한 모든 새 브리지 네트워크는 `default-network-opts`로 맞춥니다. 이어서 `repository`의
`ref`를 `/opt/fsl`에 클론하고, `/opt/fsl/.env`에 `FSL_IMAGE_TAG=<체크아웃의 커밋>`을 쓰고,
GeoIP 데이터베이스를 받고(`bin/fetch-geoip`; 자격 증명이 필요 없습니다. Elastic의 GeoIP
엔드포인트는 URL에 약관 동의를 담으면 누구에게나 GeoLite2를 제공합니다), `ubuntu`를 `docker`
그룹에 추가합니다. systemd 유닛 `fsl-platform.service`는 부팅할 때마다 `compose.yaml`과
`session.yaml`의 이미지를 pull하고 `docker compose -f /opt/fsl/compose.yaml up -d`를
실행합니다. 이 유닛은 아무것도 빌드하지 않습니다. pull이 실패해도 유닛은 멈추지
않으며(`ExecStartPre=-`), 이때는 `up`이 없는 이미지를 체크아웃에서 빌드합니다.
`bin/platform-rebuild`는 ghcr.io를 먼저 확인해 이런 빌드를 피합니다.

즉 Nova VM 하나 안에서 도는 것은 compose 컨트롤 플레인뿐입니다. OpenStack substrate에서는 이
VM에서 세션 스택이 뜨지 않고, board의 정답 데이터(ground truth)는 워게임 호스트의 관리망
주소에서 읽습니다. cloud-init이 `FSL_PUBLISH`를 VM의 고정 주소로 설정하므로 8000, 8002,
3080이 그 주소에 publish되고 보안 그룹에서도 열려 있어, 브라우저는 floating IP로 콘솔에
접속합니다. `FSL_SYSLOG_PUBLISH=0.0.0.0`은 에지 방화벽의 syslog를 받기 위해 5140/udp를 모든
주소에 publish합니다. 9200은 loopback에만 둡니다.

템플릿의 파라미터는 모두 `deploy/openstack/cloud.yaml`에서 옵니다(`bin/platform-rebuild`,
`bin/cloud`). 템플릿에는 기본값이 없습니다. cloud-init은 그 값을 `FSL_OPENSTACK_*`와
`FSL_OPNSENSE`로, 그리고 `_PROJECT`(스택 자신의 프로젝트), `_SSH_USER=ubuntu`,
`_SSH_KEY=/data/ssh/id_ed25519`를 모드 0600으로 `/root/openstack.env`에 쓴 뒤, git이 무시하는
`/opt/fsl/openstack.env`로 옮깁니다. 비밀번호는 템플릿에 넣지 않습니다. Nova가 user data를
보관하고, 메타데이터 서비스가 훈련 환경의 컨테이너를 포함해 VM에서 실행되는 모든 것에 이를
제공하기 때문입니다. `bin/platform-rebuild`는 VM이 뜬 뒤 ssh로 `FSL_OPENSTACK_PASSWORD`를
덧붙이고, 훈련 환경용 ssh 키도 같은 방식으로 플랫폼의 데이터 볼륨에 씁니다(`README.md`).
플랫폼 서비스는 이 파일을 `env_file`(`required: false`, `format: raw`)로 읽으므로, compose는
변수 치환이나 따옴표 제거 없이 값을 그대로 전달합니다.

VM 위의 플랫폼은 OpenStack 어댑터(cloud-init이 쓴 `FSL_SUBSTRATE=range.openstack.connect`)를
쓰며, 훈련 환경의 네트워크를 `/api/range/fabric/`으로 직접 만듭니다. 계획은
`range/fabric.py`가 세웁니다. 만드는 것은 선언된 출발지마다 서브넷을 하나씩 둔 `internet`
네트워크 하나(DHCP 끔), `cloud.yaml`이 정한 CIDR의 `estate`(서비스망)와 `mgmt`(게이트웨이
없음), 그리고 `/data/ssh/id_ed25519`의 키로 만든 키페어 `fsl-platform`입니다. `cloud.yaml`
로더는 이 CIDR이 서로 겹치거나, 플랫폼 네트워크, Docker의 기본 로컬 주소 풀(172.17.0.0/16부터
172.31.0.0/16까지와 192.168.0.0/16; moby `daemon/libnetwork/ipamutils/utils.go`),
`compose.yaml`이 선언한 네트워크, 선언된 출발지와 겹치면 거부합니다. 플랫폼은 첫 fabric POST
시점에 그 키가 없을 때만 키를 만듭니다. `bin/platform-rebuild`는 운영자 컴퓨터에 사본을 두고
새 플랫폼 VM마다 써 넣으므로, VM을 교체해도 키페어와 훈련 환경의 VM이 신뢰하는 키가 그대로
유지됩니다. `describe()`는 각 출발지를 하나뿐인 인터넷 네트워크의 해당 서브넷에 CIDR로
연결합니다. VM의 라우터에는 플랫폼 자신의 서브넷만 붙으며, 플랫폼은 `mgmt` 포트(아래)를 통해
훈련 환경 호스트에 접속합니다.

호스트는 골든 이미지로 부팅합니다. 골든 이미지는 `/api/range/images/`로 만들고, 계획은
`range/images.py`가 세웁니다. 클라우드에 업로드해 둔 이미지는 손대지 않은 Ubuntu 24.04
클라우드 이미지(`compute.base_image`) 하나뿐이며, 모든 빌더가 이 이미지로 부팅합니다.
`declaration.yaml`의 `hosts:`가 VM마다 설정 스크립트와 필요한 파일을 정합니다. 플랫폼은 이를
빌더의 user data에 담아 빌더를 플랫폼 자신의 네트워크(라우터가 있는 네트워크)에서 부팅하고,
설정 스크립트가 끝날 때 출력하는 줄을 빌더 콘솔에서 확인한 뒤 빌더를 멈추고 스냅샷합니다.
이미지에는 번들의 digest가 들어 있으므로, 스크립트를 수정하면 낡은 이미지가 조용히 쓰이는
대신 다른 번들의 이미지로 드러납니다. `uploads`가 있는 호스트(에지 방화벽)는 다르게 처리합니다.
이 빌더는 자격 증명을 받지 않습니다. 빌더는 디스크를 만들어 플랫폼 네트워크에 HTTP로 제공하고,
디스크의 SHA256을 콘솔에 출력합니다. 플랫폼이 디스크를 받아 SHA256을 확인하고 Glance 레코드를
만든 뒤 자신의 토큰으로 업로드합니다. 빌더는 Glance가 active를 알리면 스냅샷 없이 삭제합니다.
에지 방화벽의 빌더는 OPNsense nano 이미지를 내려받아 그 SHA256과 릴리스 키의 SHA256을
`cloud.yaml`과 대조하고, 서명을 검증하고, QEMU로 한 번 부팅해 설정 가져오기(importer)
프롬프트에 응답함으로써 `deploy/opnsense/config.xml`로 시작하게 합니다. 그 뒤 `qemu-img`로
변환해 제공하면 플랫폼이 이를 `fsl-opnsense-<version>`으로 업로드합니다
(`deploy/opnsense/build.sh`, `importer.py`).

워게임마다 이미지를 따로 두지 않습니다. 호스트 이미지 하나, `fsl-wargame-host`
(`deploy/wargame-host/setup.sh`)는 베이스 이미지에 `docker.io`와 `docker-compose-v2`를 더한
것이며, 선언 항목에 나열된 모든 워게임(`wargames: [board, corp]`)을 docker substrate가 실행하는
것과 같은 GHCR 컨테이너로 실행합니다. `range/wargame_host.py`는 각
`wargames/<id>/compose.yaml`을 호스트용으로 렌더링해 번들에 넣습니다. `build:`와 세션
네트워크를 빼고, 각 컨테이너 이름을 서비스 이름으로 정하고, 이미지 참조에 플랫폼의
`FSL_IMAGE_TAG`를 쓰고, WAF가 프록시하는 포트(`publish: {board: 8000, corp-wp: 80}`)를
publish합니다. `daemon.json`은 Docker 브리지에 테넌트 네트워크의 MTU를 지정합니다. 인터넷에
연결된 빌더가 컨테이너 이미지를 받아 호스트 이미지 안에 넣어 두며, 훈련 환경에는 인터넷이
없습니다. 태그가 번들의 digest에 들어가므로, 새 태그로 올라간 플랫폼은 새 호스트 이미지를
계획합니다. 워게임이 늘어도 이미지 수는 그대로입니다: 베이스, 에지 방화벽, WAF, Kali, 워게임
호스트.

fabric은 보안 그룹 세 개도 만듭니다. `fsl-range`는 `mgmt`가 아닌 모든 훈련 환경 포트가 속하며
모든 IPv4 유입을 허용합니다(훈련 환경을 방어하는 것은 Neutron이 아니라 WAF이며, anti-spoofing은
켜 둡니다). `fsl-reach`는 `fsl-mgmt` 구성원에서 오는 NTP(udp 123)만 허용합니다. `fsl-mgmt`는
모든 훈련 환경 호스트의 `mgmt` 포트가 속하며 `fsl-reach` 구성원에서 오는 연결만 허용합니다.
플랫폼은 자신의 서버 id(`FSL_OPENSTACK_PLATFORM`, 부팅 시 기록)로 찾은 `fsl-reach` 포트를 통해
`mgmt`에 붙습니다. 그래서 플랫폼은 모든 호스트에 ssh로 접속할 수 있지만, 어떤 호스트도 NTP
말고는 플랫폼으로 연결을 열 수 없고, Kali의 `mgmt` 포트에서는 다른 호스트로 연결할 수
없습니다. runner는 호출자가 네트워크를 지정하지 않으면 호스트의 `mgmt` 주소로 접속합니다.

훈련 환경에는 인터넷이 없어 자체 시간 동기화 서버가 없고, 채점기는 대상 시스템과 센서의 시각을
플랫폼 시계 기준의 케이스 시간 구간과 비교합니다. 플랫폼 VM은 chrony를 실행하고(cloud-init:
`allow <network.mgmt>`, `local stratum 10`), 모든 훈련 환경 호스트는 플랫폼의 `mgmt` 주소로
시간을 맞춥니다. `range/clock.py`는 Ubuntu 호스트에 `systemd-timesyncd` drop-in을 쓰고 첫
응답을 기다리며(`keep_time()`; 모든 호스트의 configure 체인 안에서, 그리고 워게임이 시작되기
전에 실행), 에지 방화벽의 렌더링된 `config.xml`은 `system/timeservers`에 이 주소를 지정하고
ntpd를 `opt1`에 바인딩합니다. docker에서는 모든 컨테이너가 호스트 커널의 시계를 읽으므로 따로
할 일이 없습니다.

슬롯은 훈련 환경 호스트의 집합으로, `/api/range/slot/`으로 관리하고 계획은 `range/slot.py`가
세웁니다. 각 호스트는 선언된 네트워크마다 `<host>.<segment>` 이름의 포트를 가지며, 이 포트는
`fsl-range`에, `mgmt`에서는 `fsl-mgmt`에 속합니다(다른 그룹에 있던 기존 `mgmt` 포트는
`fsl-mgmt`로 옮깁니다). `gateway` 역할을 맡은 호스트는 모든 출발지의 게이트웨이 주소를 인터넷
포트 하나에 갖습니다. cloud-init은 첫 번째 주소만 설정하므로, 나머지는 user data가 부팅할
때마다 추가합니다. 모든 호스트의 user data는 `estate` 이름(WAF의 `board.com`과 `corp.com`,
워게임 호스트의 `board`와 `corp-wp`)을 `/etc/hosts`에 덧붙이며, WAF는 이것으로 각 워게임의
publish된 포트를 찾습니다. 각 데이터베이스는 호스트 안의 자기 compose 프로젝트 안에서만
응답합니다.

훈련 환경 슬롯. `cloud.yaml`의 `compute.slots`(기본값 1, 플랫폼에서는
`FSL_OPENSTACK_SLOTS`)는 훈련 환경을 몇 벌 동시에 세울지 정하며, `max_sessions`가 바로 이
수입니다. 슬롯 1은 위의 이름을 그대로 쓰고, 슬롯 N>1은 서버와 포트 이름을 `<host>-N`
(`fsl-edge-2`, `fsl-waf-2.mgmt`)으로 짓고 서버에 `fsl_host`와 함께 `fsl_slot=N` 태그를 답니다.
첫 슬롯을 제외한 슬롯마다 internet과 estate 네트워크의 사본(`fsl-internet-N`,
`fsl-estate-N`, `fsl.slot=N` 태그)을 같은 서브넷으로 따로 둡니다. 그래서 모든 에지 방화벽이 같은
출발지 게이트웨이 30개를, 모든 Kali가 같은 출발지 주소를 가지며, 경보의 출발지는 어느 슬롯에서나
같은 국가로 분류됩니다. Neutron은 라우터를 공유하지 않는 두 네트워크에 같은 CIDR을 허용합니다.
`mgmt`는 모든 슬롯이 공유합니다. 슬롯마다 호스트가 여기서 각자의 DHCP 주소를 받고, 이전과 같이
`fsl-mgmt`가 이들을 격리합니다. 슬롯 어댑터(`OpenStack.in_slot(n)`)는 자기 슬롯의 서버만,
선언된 호스트 이름으로 읽습니다. 그래서 역할, runner, 구성도, 에지 방화벽의 렌더링된 설정이
모든 슬롯에서 같습니다. 슬롯 N의 에지 방화벽은 hostname을 `fsl-edge-N`으로 렌더링합니다. 한
슬롯의 수집기를 열 때 다른 슬롯의 송신자 룰은 그대로 둡니다. 플랫폼은 세션을 열 때 세션을
슬롯에 묶습니다(`Session.slot`; unique 제약으로 슬롯당 열린 세션은 하나). 잠금을 잡은 상태에서
READY인 첫 번째 빈 슬롯을 고릅니다. 세션별 훈련 환경 호출은 모두 그 슬롯으로 가고, 세션 종료는 그
슬롯만 초기화하며 그 슬롯의 예외 처리만 복원된 것으로 표시합니다. 초기화 상태도 슬롯마다
따로이며(`api/reset.py`), 룰 변경은 그 슬롯의 차례를 잡습니다. 따라서 한 슬롯의 초기화가 다른
슬롯의 세션을 붙잡지 않습니다. `run_on_role`은 `--session`이나 `--slot`을 받으며, 슬롯이 둘
이상인데 둘 다 없으면 거부합니다. 콘솔의 VM 터미널은 세션을 `?arg=<id>`(ttyd `-a`)로 받아 그
슬롯의 호스트를 엽니다.

OPNsense 에지 `fsl-edge`(vtnet0 internet이 WAN, vtnet1 estate가 LAN, vtnet2 mgmt가 opt1)는
슬롯 안에서 부팅합니다. `POST /api/range/configure/`는 슬롯에 맞춰
`deploy/opnsense/config.xml`을 렌더링합니다(`range/opnsense.py`). 이 파일에는 `dnsmasq`,
`Syslog`, `unboundplus` 모델의 기본값이 들어 있는데, OPNsense의 마이그레이션이 실행되기 전에
초기 부팅 단계의 템플릿 렌더링에 이 값이 필요하기 때문입니다. 렌더링한 파일은 Suricata include
`deploy/opnsense/suricata.yaml`, 시작 룰과 함께 관리망 ssh로 root 권한으로 올려 설치한 뒤
에지를 재부팅합니다. 그런 다음 새 부팅 시각이 확인될 때까지 기다리고, 다음을 확인합니다. 에지가
출발지 게이트웨이 주소 30개를 갖고 있는지(하나는 static, 나머지는 IP alias), WAN에서 Suricata를
IDS 모드로 실행하며 estate와 mgmt를 `HOME_NET`으로 두고 EVE 경보와 HTTP 기록을 syslog로
보내는지, syslog를 수집기로 보내는지, pf에 WAN pass 룰이 있는지입니다. 이 pass 룰은 WAF의
estate 주소로 가는 tcp 80만 허용하고 나머지는 허용하지 않습니다. 룰 편집기는 include가 가리키는
파일에 쓰고, include가 여는 소켓에서 `suricatasc`로 룰을 다시 읽힙니다. 에지의 syslog와 WAF의
ModSecurity audit 로그는 GeoIP 정보가 붙은 채 플랫폼의 Elasticsearch로 수집됩니다. Kali 이미지
하나가 모든 출발지를 맡습니다. 인터넷 포트 하나에 국가별 주소 약 100개를 두고(슬롯의
`bootcmd`가 NIC에 추가), `/usr/local/sbin/fsl-origin`이 박스에서 나가는 트래픽의 출발지 주소를
국가별로 SNAT하므로, 어떤 도구를 쓰든 선택한 국가에서 나가는 트래픽이 됩니다. marker를 붙이는
프록시와 ttyd 터미널은 Kali 박스에서 실행됩니다.

`rebuild_slot()`(`POST /api/range/slot/rebuild/`)은 떠 있는 슬롯 VM 전부를 각자의 골든
이미지로 재구축하되, 각 서버의 id, flavour, 포트, 고정 IP는 유지합니다.
`POST /api/sessions/<id>/close/`는 이 함수 대신 `reset_slot()`을 호출합니다. `reset_slot()`은
쉘을 내주는 VM(Kali, WAF)만 재구축하고, 에지 방화벽과 워게임 호스트는 제자리에서
초기화합니다(`docs/OPENSTACK.md` §6.1). 그래서 한 세션이 수정한 룰이나 심어 둔 데이터가 다음
세션에 남지 않습니다. 재구축은 디스크를 지우므로, VM이 ACTIVE가 된 뒤 반드시 configure를 다시
실행해야 합니다. 워게임 호스트의 제자리 초기화(`clear_wargames()`)는 각 워게임과 estate 센서에
`docker compose down -v`를 실행하고, 센서의 eve 로그와 rsyslog의 imfile 상태를 지웁니다. 그
결과 이미지만 남고 컨테이너나 볼륨은 남지 않습니다. configure의 마지막 단계인
`start_wargames()`는 `wargames` 역할을 통해 워게임마다 `sudo docker compose -p <id> -f
/opt/fsl/wargames/<id>.yaml up -d --wait --pull never`를 실행하므로, 모든 세션은 새로 시드된
대상 시스템에서 시작합니다. 그다음 estate 센서를 띄웁니다. docker의 Suricata 이미지와
`deploy/suricata/suricata.yaml`(띄울 때마다 플랫폼의 사본을 호스트에 씁니다)을
`deploy/wargame-host/sensor.yaml`로 host 네트워킹 모드로 띄우고, 호스트의 estate 주소가 있는
인터페이스를 감시합니다. 그래서 docker에서 센서 하나가 WAF의 네임스페이스 안에서 보는 WAF→대상
시스템 구간을 이 센서가 봅니다. 센서가 응답하면 `start_sensor()`가 호스트 항목에 지정된 룰 파일과
reload 명령으로 `rules/suricata.py`를 통해 기준선 룰을 시드합니다. 이 센서의 역할
`estate-sensor`는 compose 서비스 `suricata`에 매핑되므로 runner는 그 컨테이너 안에서 명령을
실행합니다. 호스트 항목이 룰 파일과 reload 명령을 지정하며(`settings.FSL_EXTRA_SENSORS`), 룰
시드, 검증, 변경, 기준선 검사는 모두 두 센서에 함께 적용됩니다. 호스트의 `logs:` 항목에 따라
rsyslog가 `eve.json`을 `suricata` 태그로 수집기에 전달하고(`range/waf.py`의 태그별 전달),
`fsl-reach`는 에지 방화벽, WAF와 마찬가지로 이 호스트에서 오는 로그를 받아들입니다.
세션 종료 뒤에는 플랫폼이 이 작업을 직접 합니다. `platform/api/reset.py`가 백그라운드 스레드를
띄우고, 이 스레드는 룰 잠금을 한 번 잡은 채 두 갈래를 동시에 실행합니다. 한 갈래는
`reset_in_place()`입니다. 에지 방화벽의 제자리 초기화(`reset_edge()`: 기준선 `fsl.rules`를
되돌리고, 설치된 파일을 에지가 마지막 설치와 부팅 뒤 기록한 해시와 sha256으로 대조하고, 훈련
환경의 pf 상태를 지우고, 필터를 다시 읽히고, Suricata를 재시작합니다. 하나라도 일치하지 않으면
`configure_edge()`의 설치와 재부팅으로 넘어갑니다), 수집기 보안 그룹, 워게임 호스트(비운 다음
시간 동기화, 워게임, 센서, 로그 전달 순서)를 처리합니다. 다른 갈래는 재구축한 VM 각각이 ACTIVE를
벗어났다가 다시 ACTIVE가 되는 것을 `plan_slot()`으로 폴링해 확인한 뒤, 클라우드를 새로 읽어
`configure_rebuilt()`(재구축한 호스트마다 시간 동기화, 그리고 WAF의 로그 전달)를 실행합니다. 두
갈래 모두 VM이 ssh에 응답하지 않는 동안 재시도하며(최대 30분), 처음 발생한 실패가 초기화를
실패로 만듭니다. `configure_slot()`(수동 configure)은 호스트마다 스레드 하나씩 두고 각 호스트의
단계를 나란히 실행합니다: 에지 방화벽(설정과 재부팅), WAF, Kali, 워게임 호스트, 수집기 보안
그룹. 모든 Ubuntu 호스트의 체인은 시간 동기화로 시작합니다. 모두 끝날 때까지 기다린 뒤, 위
순서에서 첫 번째 실패를 결과로 반환합니다. close는 즉시 응답하고, 초기화 상태(idle, running,
failed와 그 이유)는 플랫폼 프로세스가 보관합니다. `POST /api/range/configure/`는 수동 재시도
수단으로 남아 있으며, 실패한 초기화 상태를 지웁니다.

OpenStack에서는 모든 슬롯이 사용 중이거나 준비된 빈 슬롯이 없으면 세션 생성이 409로 응답합니다.
`GET /api/range/ready/`는 `slots` 아래에 슬롯마다 다음을 보고합니다: 번호, 그 슬롯을 잡은 세션,
단계(세션이 잡고 있으면 `IN_USE`, 초기화가 진행 중이면 `RESETTING`, 초기화가 실패했으면 그
이유와 함께 `RESET_FAILED`, 그 밖에는 `NOT_STANDING`, `REBUILDING`, `CHECKING`, `READY`),
초기화 상태, 그리고 세 가지 검사(모든 VM이 ACTIVE, board의 정답 데이터를 읽을 수 있음, 센서
룰이 기준선이며 그 슬롯에 적용 중인 예외 처리가 없음). 최상위의 `ready`와 `slot`은 다음 세션
열기가 잡게 될 슬롯을 가리킵니다. `/api/range/slot/`, `slot/rebuild/`, `configure/`는
`?slot=N`을 받으며, 없으면 모든 슬롯에 적용합니다. `POST /api/range/canary/`는 marker를 붙인
케이스 하나를 발사해 Suricata와 ModSecurity가 모두 경보를 냈는지와 두 시계의 차이가 얼마인지를
보고합니다. 이 검사는 ready 검사에 포함되지 않습니다. 랜딩 페이지는 둘 다 호출합니다.

### OpenStack 훈련 환경: 목표 구조

2026-09-30에 사용자가 결정했으며, 2026-10-08의 변경 사항을 표시했습니다. 대부분은 구축되어
있습니다(위 참고).

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

- 세션 수명 주기: WAF 모드와 시계 차이를 준비 상태 검사에 포함하기(종료 시 재구축 뒤
  `configure`를 다시 실행하는 것은 2026-10-11부터 자동입니다).
- 차단(계획, 2026-10-08 스펙): WAF는 `SecRuleEngine On`으로 동작하고, 블루팀은 CRS 설정을
  조정해(paranoia level, 예외 규칙(rule exclusion)) 공격은 차단하고 정상 트래픽은 통과시킵니다.
  Suricata는 탐지를 맡습니다. 시작 paranoia level은 2026-10-10에 측정했습니다
  (`docs/DECISIONS.md`). PL1만으로도 board의 SQLi는 차단되고 O'Brien은 통과하므로, 과차단하도록
  만든 방어 설정은 그보다 높은 단계에서 시작하고(시나리오의 `level2`, `level3`), 학습자가 설정을
  조정합니다(더 낮은 PL, 임계치, 예외 규칙). 케이스가 차단되었는지는 대상 시스템 쪽에서 읽어
  `meta["blocked"]`에 넣습니다. pfSense GUI에서 Suricata drop 룰을 전환하던 이전 계획은
  이 계획으로 대체되었습니다.

사람이 결정해야 할 남은 사항은 `docs/STATE.md`("Decisions left for a person")에 있습니다.

구축됨: WAF VM은 ModSecurity audit 로그를 rsyslog imfile로 UDP 5140에 전달하고
(`platform/range/waf.py`), OPNsense 에지의 Suricata는 IDS(pcap) 모드로 동작합니다
(`deploy/opnsense/`). 다만 아직 클라우드에서 실제로 구축해 보지는 않았습니다. 구축 전에 이
클라우드에서 테스트할 항목은 placement 스펙의 "To test on this cloud before building"에
있습니다.
