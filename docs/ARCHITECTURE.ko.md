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
`fsl`, 하나만 오래 떠 있음): 플랫폼, Elasticsearch, Kibana, `collector`, 그리고 네트워크
여섯 개. `session.yaml`은 세션 하나의 데이터 플레인이다: WAF, Suricata, Filebeat, Kali,
프록시, wargame. 이 파일은 네트워크 여섯 개에 `external`(`fsl_<network>`)로 붙고 자기
볼륨만 갖는다. 세션을 열면(`POST /api/sessions/`, `platform/range/docker.py`의
`open_session`) 플랫폼 안에서 `docker compose -p fsl-<세션 id> -f session.yaml up -d
--wait --no-build`를 실행한다. 이때 `FSL_HOST_DIR`은 compose가 플랫폼을 띄운 호스트
디렉터리(플랫폼 컨테이너의 `com.docker.compose.project.working_dir` 라벨)로 두어, 스택의
bind mount가 호스트에서 풀리게 한다. baseline은 `--wait`가 돌아온 뒤 읽는다. 컨테이너
이름 고정이 없어지기 전(빌드 4단계)까지 스택은 한 번에 하나만 돈다: 세션을 열면 먼저
다른 `fsl-<n>` 프로젝트를 모두 `down -v`하고, 세션을 닫아도 그 스택은 다음 세션이 열릴
때까지 남는다. OpenStack substrate에는 `open_session`이 없다. 그 레인지는 Nova VM이라
세션 스택이 뜨지 않는다. 준비 상태 점검과 세션 baseline은 어댑터의 `address("board")`,
즉 board VM의 관리망 주소로 board VM을 읽는다. `loot.ground_truth`가 `BOARD_API_URL`의
호스트를 그 주소로 바꾼다.

대상 시스템 하나가 wargame 하나이고, `wargames/` 아래 폴더 하나다. `session.yaml`이 그
폴더의 `compose.yaml`을 include 한다: `board`(Django와 MySQL, `loot_verified`)와
`corp`(WordPress와 MySQL, `effect_observed`). 플랫폼은 각 wargame을
`wargames/<id>/scenario.yaml`에서 찾는다(`platform/wargames.py`; 필드는 `name`,
`description`, `image`, `public_url`, `objective_model`, `case_file`). `image`는 아직
아무 코드도 읽지 않는다. 앱 이미지는 한 번 빌드해 태그를 붙이고(`docker compose -f
session.yaml build`), 세션은 그 태그로 `--no-build` 기동한다. 새 wargame에는 폴더 안의
`scenario.yaml`, `objectives.yaml`, `compose.yaml`, `redteam/cases/` 아래의 케이스 파일,
그리고 `session.yaml`의 `include:` 줄 하나가 필요하다.

| 서비스 | 파일 | 이미지 | 네트워크 | 호스트 포트 |
|---|---|---|---|---|
| `fsl-wg-board` | session | `wargames/board/app`의 `fsl/board:mvp` (gunicorn 아래 Django, 포트 8000) | estate | |
| `fsl-wg-board-db` | session | `mysql` | estate | |
| `fsl-wg-corp-wp` | session | `wargames/corp/app`의 `fsl/corp:mvp` (WordPress 6.6.2, 취약 버전으로 고정한 플러그인 셋; `Host` 헤더로 `corp.com`) | estate | |
| `fsl-wg-corp-db` | session | `wargames/corp/db`의 `fsl/corp-db:mvp` (MySQL 8.4, binlog `ROW`) | estate | |
| `fsl-waf` | session | `owasp/modsecurity-crs` (nginx), edge에서 별칭 `board.com` | edge, edge-br, edge-hk, edge-us, estate | |
| `fsl-suricata` | session | `jasonish/suricata` | WAF의 네임스페이스 | |
| `fsl-filebeat` | session | `filebeat:8.15.0`, 세션의 `eve.json`과 감사 로그를 보냄 | mgmt | |
| `fsl-kali` | session | `deploy/kali`의 `fsl/kali:mvp` | edge | |
| `fsl-proxy` | session | `deploy/proxy`의 `fsl/proxy:mvp` (mitmdump) | 네 개 edge 네트워크 | |
| `fsl-elasticsearch` | control | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-collector` | control | `filebeat:8.15.0`, syslog 입력만(OpenStack 레인지) | mgmt | 5140/udp |
| `fsl-kibana` | control | `kibana:8.15.0`, `/kibana/`에서 제공 | mgmt | |
| `fsl-platform` | control | `platform/` (waitress 아래 Django, nginx 뒤; nginx는 `/kibana/`의 Kibana, `/terminal/`의 Kali 자체 ttyd, `/vm-terminal/fsl-kali/`와 `/vm-terminal/fsl-waf/`의 VM 터미널도 제공한다); compose 플러그인을 갖고 `session.yaml`을 `/src/session.yaml`에 마운트 | 여섯 개 모두 | 8000 |

8000은 `FSL_PUBLISH`에, 5140/udp는 `FSL_SYSLOG_PUBLISH`에 바인딩되며 둘 다
기본값은 127.0.0.1이다. 9200은 loopback에만 바인딩된다.

| 네트워크 | 구간 | 서브넷 | 이름 | 출발지 |
|---|---|---|---|---|
| `edge` | `ru` | 5.188.10.0/24 | 인터넷 | 러시아 |
| `edge-br` | `br` | 177.54.144.0/24 | 인터넷 | 브라질 |
| `edge-hk` | `hk` | 103.152.220.0/24 | 인터넷 | 홍콩 |
| `edge-us` | `us` | 73.0.0.0/24 | 인터넷 | 미국 |
| `estate` | `estate` | 172.30.0.0/24 | 애플리케이션 영역(estate) | |
| `mgmt` | `mgmt` | 172.31.0.0/24 | 관리 | |

선언은 하나의 인터넷 구간 위에 서른 개의 출발지를 나열한다. Cloudflare Radar의 HTTP
요청 점유율 상위 서른 개 국가이며, 각각 GeoIP가 그 국가로 판정하는 /24 하나와 약
100개의 공격 주소 중 그 몫을 갖는다. Docker는 그중 넷을 네트워크 하나씩으로 만든다.
브리지 하나는 IPv4 서브넷 하나만 담기 때문이다. OpenStack fabric은 서른 개 전부를
한 네트워크의 서브넷으로 만든다. `bin/pick-origins`가 이 표를 재현하고, 수용
테스트가 scoring이 읽는 파이프라인에 대해 모든 서브넷을 검사한다.

망 분리는 Docker 네트워크 소속만으로 이루어진다: 방화벽, iptables, ACL은 없다.
`test/test_segmentation.py`가 라이브 스택에서 이를 검사한다(Kali는 `board.com`에는
닿지만 `board:8000`에는 닿지 못한다). 고정된 것은 서브넷뿐이고, 컨테이너 주소는
Docker가 할당하며 재생성 시 바뀐다. 뷰는 요청마다 새 어댑터를 만들어 주소를 읽는다.
레인지 호스트에서 온 요청을 거부하는 규칙은 그 주소를 30초 동안 캐시하고, substrate에
닿을 수 없으면 레인지를 비어 있는 것으로 보고 요청을 통과시킨다
(`docs/THREAT-MODEL.md`).

플랫폼, WAF, 프록시는 multi-homed다. 공격자의 트래픽은 WAF를 통해서만 내부망
(`estate`)으로 들어가지만, 플랫폼은 모든 구간에 붙어 있으므로 API가 호출자를 직접
검사한다(`docs/THREAT-MODEL.md`).

```
 edge      kali --HTTP via http_proxy--> proxy:8081 --+
           kali --raw TCP (nmap, nc), no proxy--------+
           platform --console-fired case--------------+
 edge-br                                              |
 edge-hk   proxy, platform (no kali, no board.com)    |
 edge-us                                              v
         fsl-waf: nginx + ModSecurity CRS, DetectionOnly, port 80
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
   ./data/label --bind mount--> proxy (read-write), kali (read-only)
   kali's shell --> /var/log/fsl/commands.log, each command with its marker
   platform --docker exec--> proxy (/label files), suricata (rules),
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
무인증 글 덮어쓰기). 어느 것도 기본 OWASP CRS 탐지 룰에 걸리지 않는다. DB인
`fsl-wg-corp-db`는 `--binlog-format=ROW`로 도는 MySQL 8.4이며, WordPress 자체에는
계측을 넣지 않았다. corp는 공격이 DB에 커밋한 변경으로 채점한다(아래).

## 선언과 substrate 이음매

Docker는 MVP의 substrate이고, OpenStack은 목표다. 플랫폼은 레인지의 의미를 Docker에
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

구간은 라벨로 찾고, 호스트는 아직 이름으로 찾는다. 각 구간은 `fsl.segment.id`를
Docker 라벨이나 Neutron 태그로 가지며, 어댑터는 라벨이 붙은 네트워크만 가져온다. 이름
매칭은 compose 접두사와 오버라이드, Heat 스택 접미사, 유일하지 않은 Neutron 이름에서
깨졌다. 역할은 선언이 지정한 컨테이너 또는 서버 이름이다: Docker는 `docker exec
<name>`을 실행하고, OpenStack은 프로젝트의 모든 서버를 나열해 `server["name"]`을
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
`_USER`, `_PASSWORD`, `_PROJECT`, `_SSH_USER`, `_SSH_KEY`를 받으며, 없으면 이름을 들어
거부한다. `_REGION`은 기본값이 `RegionOne`, `_INTERFACE`는 `public`이다. `redteam/harness.py`에는 launcher가,
`platform/rules/suricata.py`에는 runner가 전달되므로, 둘 다 `subprocess`를 import하지
않고 substrate를 지정하지도 않는다.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| 구조 | `docker network ls/inspect`, 라벨 필터 | Keystone v3, `tags-any`를 쓰는 Neutron, Nova |
| sensor | 선언된 각 sensor가 선언된 gateway의 네트워크 네임스페이스를 공유하지 않으면 레인지 기술(describe)을 거부한다 (`docker ps`, `.HostConfig.NetworkMode`) | 이름이 지정된 두 서버가 모두 존재하면 sensor를 보고한다; 그것이 gateway의 트래픽을 보는지 확인하는 것은 없다 |
| runner | `docker exec` | 인스턴스로 `ssh` |
| launcher | `docker run --rm --network <segment>` | `runner("attacker")`: 선언된 attacker의 mgmt 주소로 ssh해 도구를 실행한다(origin은 attacker가 그 구간에 있는지만 확인하고, 출발 국가는 `fsl-origin` SNAT가 정한다); 다른 이미지는 거부되는데, Nova는 호스트를 부팅해 출력을 반환하고 삭제할 수 없기 때문이다 |
| 테스트 대상 | 라이브 스택 | 공개된 API 레퍼런스와 로컬 sshd로 만든 fake에 대한 유닛 테스트; `fsl-range` 클라우드에서는 플랫폼 VM이 `/api/range/`를 통해 fabric, 이미지, slot을 구축했고, `describe()`가 서른 개 출발지 위의 WAF와 estate 및 mgmt 위의 네 호스트를 되읽었으며, `runner()`가 각 호스트에서 mgmt 주소로 ssh를 통해 실행됐다; `launcher()`는 2026-10-08 `ru`와 `tw` 출발지에서 sqlmap을 실행했다 |

compose는 substrate와 무관하게 Docker 소켓을 플랫폼에 마운트하고, entrypoint는 플랫폼
사용자를 그 그룹에 추가한다. 이는 컨테이너 탈출 경로다. OpenStack 어댑터를 쓰면
제거할 수 있지만 아직 제거하지 않았다. 어댑터가 레인지를 구동하기 전에 남은 작업은
`docs/STATE.md`의 "The substrate seam"에 있다.

## 격리 경계(isolation seams)

각 관심사는 하나의 파일만 소유한다. 아래 예외는 현재 코드에 존재한다.

| 관심사 | 소유 파일 | 알려진 예외 |
|---|---|---|
| Elasticsearch | `platform/ingest/elastic.py` | `platform/register_pipeline.py`가 기동 시 `fsl-geoip` ingest 파이프라인을 PUT 한다 |
| Suricata 프로세스 | `platform/rules/suricata.py` | `platform/range/pfsense.py`와 `deploy/pfsense/configure.php`가 pfSense의 Suricata를 정지·시작한다(OpenStack) |
| 공격자 박스 | `platform/attacker.py` | `platform/operator_log.py`가 `/var/log/fsl/commands.log`를 읽는다; 터미널 배선(`settings.py`, `nginx.conf`, `entrypoint.sh`)이 `fsl-kali`를 지정한다 |
| 대상 시스템 자체의 기록 | `platform/api/loot.py`(board), `platform/api/effect.py`(corp) | 없음 |

## 요청이 어디서 오는가

| 경로 | 발신자 | 경보의 출발지 주소 | marker |
|---|---|---|---|
| 터미널, HTTP | Kali, `proxy:8081`을 거쳐 | 프록시, 선택된 출발지에서 | 프록시가 추가 |
| 터미널, raw TCP | Kali 직접 | Kali, `edge`에서만 | 없음 |
| 콘솔 케이스, HTTP | 플랫폼 | 플랫폼, 선택된 출발지에서 | harness가 추가 |
| 콘솔 케이스, 도구 | 일회용 `fsl-kali` 컨테이너 | 그 컨테이너, 선택된 출발지에서 | sqlmap `--headers=` |
| CLI 실행, HTTP | 플랫폼, `redteam/run.py` | 플랫폼, `edge`에서(`board.com`이 해석되는 곳) | harness가 추가 |
| CLI 실행, 도구 | 일회용 `fsl-kali` 컨테이너, `launcher(<선언된 기본 출발지>)`에서 | 그 컨테이너 | sqlmap `--headers=` |

프록시는 `mitmdump` 스크립트다. `/label/active`에서 `X-FSL-Case`를 설정하고,
`/label/origin`에 주소가 있으면 원래 `Host`를 유지한 채 요청을 그 주소로 전달한다.
플랫폼은 두 파일을 `docker exec`로 쓴다. TLS 가로채기가 없으므로 프록시는 환경 변수일
뿐 아무것도 강제하지 않는다: `curl --noproxy '*'`는 프록시를 거치지 않는다.

터미널은 operator가 입력하는 명령도 기록한다. Kali의 셸은 각 명령을 현재
`/label/active` marker와 함께 `/var/log/fsl/commands.log`에 덧붙인다. 플랫폼은
`runner("attacker")`로 이를 읽어 `GET /api/sessions/<id>/commands/`로 제공한다. 레드
콘솔은 `/vm-terminal/fsl-kali/`를 프레임에 띄운다. 이는 플랫폼 안의 ttyd로, 호스트의
mgmt 주소로 ssh 접속한다. compose에서는 Kali와 WAF에 mgmt 주소가 없으므로, 레드
콘솔의 터미널과 블루 콘솔의 WAF 터미널은 연결되지 않는다.

콘솔 HTTP 케이스는 출발지 선택과 무관하게 세션 wargame의 `Host`인 `board.com`을
싣는다. 출발지를 선택하면 트래픽은 그 출발지 구간에 있는 WAF의 주소로 IP를 지정해
간다. 이름은 `edge` 네트워크에서 해석되며, 출발지가 없을 때 플랫폼은 이 네트워크를
쓴다. `rotate`는 무작위 선택이 아니라 세션별 라운드 로빈이다.

콘솔 도구 케이스는 출발지의 대상 URL로, 출발지가 없으면 선언된 기본 출발지에서
`TARGET_URL`(`http://board.com`)로 향한다. 대상 시스템은 호스트에 publish되지 않으므로
명령줄 harness도 레인지 내부에서 접근한다: `redteam/run.py`는 플랫폼에서 실행되고(수용
테스트가 구동하는 방식), 출발지 옵션이 없으며, `--target`의 기본값은 `--cases` 파일이 속한
시나리오의 `public_url`(board는 `http://board.com`)로, 포트 80의 WAF로 해석된다.
`--tool-target`의 기본값은 `http://board.com`이다.

WAF는 CRS를 paranoia level 1, anomaly threshold 5, `DetectionOnly`로 돌리고
(`deploy/waf/modsecurity.conf`), 모든 Suricata 룰은 `alert`다. 레인지의 어떤 구성
요소도 요청을 차단하지 않는다.

## 경보가 어디로 가는가

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, fsl-logs-<day>
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

- 먼저 만료된 룰 억제(suppression)를 복원한다;
- 세션 시작 1분 전부터 종료(또는 현재) 1분 후까지의 `@timestamp`를 Elasticsearch에
  요청한다. `fsl-geoip` 파이프라인은 `@timestamp`를 이벤트 자체의 시각(Suricata의
  `timestamp`, ModSecurity의 `transaction.time_stamp`)으로 설정하므로, 이 창은
  Filebeat가 읽은 시점이 아니라 이벤트가 발생한 시점으로 이벤트를 고른다;
- 오래된 것부터 최대 5000개의 hit를 읽는다. 이를 넘으면 응답에 `truncated`가 실리고
  세션은 `read_of`를 기록하며, 점수에 `score.warning.truncated`가 추가된다;
- Suricata의 `alert` 이벤트를 유지하고, ModSecurity 레코드는 매칭된 룰 메시지마다
  Detection 하나(id `<Elasticsearch _id>:<n>`)로 바꾼다;
- 이벤트 시각이 창 밖인 경보는 버리고 `stale`로 센다;
- 나중에 발견된 marker를 marker가 없던 저장 행에 기록한다;
- `src_host`와 `dest_host`를 substrate의 구간 정보로 채우며, substrate에 닿을 수
  없으면 비워 둔다.

Elasticsearch는 저장과 색인 시점의 GeoIP 보강에 쓰이며, 그래서 Logstash가 없다. 쿼리
엔진은 시간 범위 검색에만 쓴다: `GET /api/sessions/<id>/map/`과 `/top/`은 SQLite
사본을 대상으로 Python에서 계산하고, `src_geo.location`은 `geo_point`가 아니라 float
두 개로 매핑된다. `bin/worldmap`은 남위 60도에서 자른 Equal Earth 지도를 생성하지만,
블루 대시보드가 제거된 뒤로 이를 그리는 콘솔 페이지는 없다.

geoip 프로세서 둘(`src_ip`는 Suricata, `transaction.client_ip`는 ModSecurity)이
`src_geo`를 쓴다. compose는 관리형 다운로더를 끄고 `./config/ingest-geoip`를
bind-mount 하며, `bin/fetch-geoip`가 이 디렉터리를 채우므로 `GeoLite2-City.mmdb`는
컨테이너를 재생성해도 남는다. entrypoint가 기동 시 파이프라인을 등록한다
(`platform/register_pipeline.py`).

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

스냅샷은 세션 시작 시 한 번만 만든다. 그때 board를 읽을 수 없으면 세션은 스냅샷 없이
생성되고, 그 세션의 `POST /api/sessions/<id>/loot/`는 409로 답한다. 그 뒤로는 board를
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
없어 현재 케이스 파일로 판정된다. 경보 심각도와 룰 유형은 쓰지 않는다.

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
  포트는 publish하지 않는다. 블루 콘솔이 이를 프레임에 띄운다.
- Elasticsearch는 512MB 힙의 단일 노드로, 전체 스택이 Docker 기본 메모리 한도에
  들어간다.
- 없는 데이터는 0이 아니라 오류로 처리하며, 예외를 명시한다. 닿을 수 없는
  Elasticsearch나 substrate, 읽을 수 없는 룰 파일은 503으로 답한다. 세션 생성은
  대상 시스템에 닿지 못해도 진행한다(세션은 스냅샷 없이 시작하고 board의 `loot/`는
  409로 답한다). 케이스 발사나 기록, 종료는 대상 시스템을 읽지 않는다(발사는 출발지나
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

### 구축됨: 플랫폼 VM

`deploy/openstack/platform.yaml`은 Heat 템플릿이며 다음을 만든다:

- 네트워크와 서브넷 `fsl-platform`;
- 외부 네트워크로 가는 라우터와 floating IP;
- 모든 주소에 tcp/22, tcp/8000, ICMP를 여는 보안 그룹;
- config drive를 가진 Nova 서버 `fsl-platform`.

파라미터와 기본값은 `README.md`에 있다.

cloud-init은 `docker.io`, `docker-compose-v2`, `git`을 설치하고, 4GB 스왑을 추가하고,
Docker의 MTU를 기본 브리지(`mtu`)와 compose 것을 포함한 모든 새 브리지
네트워크(`default-network-opts`)에 대해 Neutron 네트워크 값으로 맞추고, `ref`의
`repository`를 `/opt/fsl`로 클론하고, `ubuntu`를 `docker` 그룹에 추가한다. systemd
유닛 `fsl-platform.service`가 부팅마다 `docker compose -f /opt/fsl/compose.yaml up -d --build`를
실행한다.

따라서 compose 컨트롤 플레인만 Nova VM 하나 안에서 돈다. OpenStack substrate에서는 그 안에 세션 스택이 뜨지 않고, board의 ground truth는 board VM의 관리망 주소에서 읽는다. cloud-init이 `FSL_PUBLISH`를
VM의 고정 주소로 설정하므로 8000이 그 주소에 publish되고 보안 그룹에서도
열려, 브라우저가 floating IP로 콘솔에 접근한다. `FSL_SYSLOG_PUBLISH=0.0.0.0`은
pfSense의 syslog를 받기 위해 5140/udp를 모든 주소에 publish한다. 9200은 loopback에
남는다.

cloud-init은 `FSL_OPENSTACK_KEYSTONE`, `_USER`, `_PROJECT`(스택 자신의 프로젝트),
`_SSH_USER=ubuntu`, `_SSH_KEY=/data/ssh/id_ed25519`를 모드 0600으로
`/root/openstack.env`에 쓰고, git이 무시하는 `/opt/fsl/openstack.env`로 옮긴다.
비밀번호는 템플릿에 없다: Nova가 user data를 보관하고 메타데이터 서비스가 레인지
컨테이너를 포함해 VM에서 도는 모든 것에 이를 제공하기 때문이다. operator는 VM이 뜬
뒤 ssh로 `FSL_OPENSTACK_PASSWORD`를 덧붙인다(`README.md`). 플랫폼 서비스는 이 파일을
`env_file`(`required: false`, `format: raw`)로 읽으므로, compose는 보간이나 따옴표
제거 없이 그대로 전달한다.

VM 위의 플랫폼은 OpenStack 어댑터(cloud-init이 쓴
`FSL_SUBSTRATE=range.openstack.connect`)를 쓰고, `range/fabric.py`가 계획한
`/api/range/fabric/`로 레인지 네트워크를 직접 만든다: 선언된 출발지마다 서브넷 하나를
가진 `internet` 네트워크(DHCP 끔), 10.30.0.0/24의 `estate`와 게이트웨이 없는
10.31.0.0/24의 `mgmt`(모든 compose 및 플랫폼 VM 서브넷과 겹치지 않음), 그리고 플랫폼이
`/data/ssh/id_ed25519`에 만든 키로 만든 키페어 `fsl-platform`. `describe()`는 각
출발지를 인터넷 네트워크의 해당 서브넷에 CIDR로 연결한다. VM의 라우터는 자신의
서브넷만 붙이며, 플랫폼은 `mgmt` 포트(아래)로 레인지 호스트에 접근한다.

호스트는 골든 이미지로 부팅하며, 골든 이미지는 `/api/range/images/`로 만들고
`range/images.py`가 계획한다. `declaration.yaml`의 `hosts:`가 VM마다 설정 스크립트와
필요한 파일을 정한다. 플랫폼은 이를 빌더의 user data에 담아, 빌더를 자신의
네트워크(라우터가 있는 쪽)에서 부팅하고, 설정이 끝날 때 출력하는 줄을 빌더 콘솔에서
읽은 뒤 빌더를 멈추고 스냅샷한다. 이미지는 번들의 digest를 담으므로, 스크립트를
수정하면 조용히 낡은 이미지가 아니라 다른 번들의 이미지로 드러난다.

fabric은 보안 그룹도 둘 만든다: 모든 레인지 포트가 속하고 모든 IPv4를 허용하는
`fsl-range`(레인지를 지키는 것은 Neutron이 아니라 WAF다; anti-spoofing은 유지), 그리고
아무것도 허용하지 않는 `fsl-reach`. 플랫폼은 자신의 서버 id(부팅 시 쓰는
`FSL_OPENSTACK_PLATFORM`)로 찾은 `fsl-reach`의 포트로 `mgmt`에 붙으므로, 모든 호스트로
ssh할 수 있지만 어떤 호스트도 플랫폼으로 연결을 열 수 없다. runner는 호출자가 구간을
지정하지 않으면 호스트의 `mgmt` 주소로 접근한다.

slot은 레인지 호스트의 집합으로, `/api/range/slot/`로 관리하고 `range/slot.py`가
계획한다. 각 호스트는 선언된 구간마다 `<host>.<segment>` 이름의 포트를 가지며, 모두
`fsl-range`에 속한다. `gateway` 역할의 호스트는 모든 출발지의 게이트웨이 주소를 인터넷
포트 하나에 갖고, cloud-init은 첫 번째만 구성하므로 user data가 부팅마다 나머지를
추가한다. 모든 호스트의 user data는 `estate` 이름(`board`, `board-db`)을
`/etc/hosts`에 덧붙이며, WAF는 이것으로 board를, board는 자신의 DB를 찾는다.

pfSense CE 엣지(골든 이미지 `fsl-pfsense-edge`: 베이스 + Suricata 8.0.5 + sshd + OPT1
관리 NIC)가 slot에서 부팅한다. `POST /api/range/configure/`는 관리 ssh로
`deploy/pfsense/configure.php`를 재실행해, pfSense가 30개 출발지 게이트웨이 주소를
갖고(하나는 static, 나머지는 IP-alias VIP), WAN에서 레인지를 `HOME_NET`으로 하여
Suricata를 돌리며 EVE를 syslog로 보내고, Suricata 패키지의 필터 재로드 후에도 남는 WAN
pass 룰 하나를 유지하고, syslog와 WAF의 ModSecurity audit 로그를 GeoIP 보강과 함께
플랫폼의 Elasticsearch로 보내게 한다. Kali 이미지 하나가 모든 출발지를 맡는다: 인터넷
포트 하나가 국가별 약 100개 주소를 갖고(slot의 `bootcmd`가 NIC에 추가)
`/usr/local/sbin/fsl-origin`이 나가는 출발지 주소를 국가별로 SNAT하므로, 모든 도구가
선택된 국가에서 나간다. marker를 붙이는 프록시와 ttyd 터미널은 Kali 박스에서 돈다.
`GET /api/range/console/<host>/`는 그 호스트를 맡은 서버의 Nova 콘솔 URL을 반환한다.

`rebuild_slot()`(`POST /api/range/slot/rebuild/`)은 slot을 초기화한다: Nova가 상주
slot VM을 각자의 골든 이미지로 재구축하되 서버 id, flavour, 포트, 고정 IP는 유지하므로,
한 세션이 다음 세션에 수정된 룰이나 심어 둔 데이터를 남기지 않는다.
`POST /api/sessions/<id>/close/`가 이를 호출한다. 재구축은 디스크를 지우므로 VM이
ACTIVE가 된 뒤 `POST /api/range/configure/`를 실행해야 하며, 이를 자동으로 호출하는
것은 없다.

OpenStack에서 세션 생성은 다른 세션이 열려 있거나 레인지가 준비되지 않았으면 409로
답한다. `GET /api/range/ready/`는 slot의 단계(`NOT_STANDING`, `REBUILDING`,
`CHECKING`, `READY`)와 세 가지 검사(모든 VM ACTIVE, board의 ground truth 읽기 가능,
sensor 룰이 기준선이고 적용 중인 억제 없음)를 보고한다. `POST /api/range/canary/`는
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
     Kibana    framed directly, reading the same Elasticsearch (full)
     terminal  ttyd in the platform, ssh to the Kali VM on mgmt
     |
     +--OpenStack API, as member fsl-range--> networks, VMs, consoles
     +--management network, ssh-------------> Kali VM, target VMs

 Internet network: one subnet per origin country (30), no Neutron router
   Kali VM: one port holds every attack address; the source is rewritten
            to the chosen country's address as packets leave
     |
     v
 pfSense CE VM: edge router; its WAN holds each subnet's gateway address
                and routes on without NAT, so country sources survive
   Suricata package: IDS (detects; no firewall lesson, per 2026-10-08)
     |
     v
 WAF VM: nginx + ModSecurity v3 + CRS
         (planned: SecRuleEngine On, blue tunes CRS to block)
     |
     v
 estate network
   board VM (Django on MySQL)

 Evidence:
   pfSense: Suricata EVE, filterlog --syslog, UDP--> Filebeat --+
   WAF VM: ModSecurity audit log --------------------------------+
                                                                 v
   Elasticsearch --> platform ingest --> scoring
   Elasticsearch ----------------> Kibana --> blue team
```

남은 작업:

- 세션 수명 주기: 재구축 후 `configure` 재실행, WAF 모드와 시각 차이를 준비 상태
  검사에 포함, 수작업 없이 READY일 때만 다음 세션 시작.
- 차단(계획, 2026-10-08 스펙): WAF는 `SecRuleEngine On`으로 돌고, 블루팀은 CRS를
  튜닝(paranoia level, 룰 예외 처리)해 공격은 차단하고 정상 트래픽은 통과시킨다.
  Suricata는 탐지를 맡는다. 케이스의 차단 여부는 대상 시스템 쪽에서
  `meta["blocked"]`로 읽는다. pfSense GUI에서 Suricata drop 룰을 전환하던 이전 계획은
  대체되었다.

사람이 결정해야 할 열린 사항은 `docs/STATE.md`("Decisions left for a person")에 있다.

구축된 것: WAF VM은 ModSecurity audit 로그를 rsyslog imfile로 UDP 5140에 보내고
(`platform/range/waf.py`), pfSense의 Suricata는 legacy 모드로 돈다
(`deploy/pfsense/configure.php`). 구축 전에 이 클라우드에서
테스트할 것은 placement 스펙의 "To test on this cloud before building"에 있다.
