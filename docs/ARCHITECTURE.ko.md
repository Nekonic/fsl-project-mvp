# 아키텍처

레인지가 어떻게 만들어져 있는지, 트래픽과 증거가 그 안에서 어떻게 흐르는지,
그리고 그 뒤에 있는 설계 결정을 설명합니다. 점수의 정의는 `CLAUDE.md`에, 아직
풀지 못한 문제와 측정으로 확인한 특이 동작은 `docs/STATE.md`에 있습니다.

"결정 사항" 절까지는 지금 실제로 도는 것, 즉 Docker compose 레인지를 설명합니다.
제품은 OpenStack으로 옮겨 가는 중입니다. 그중 이미 있는 것과 결정만 된 것은
마지막 절 "OpenStack"에 따로 나눠 적었습니다.

이 저장소의 출발점이 된 가설은 이렇습니다. 레드팀 공격에는 정답(ground truth)
라벨을 붙일 수 있고, Suricata와 ModSecurity의 경보를 그 라벨에 자동으로 매칭할 수
있으므로, 오탐과 미탐을 기계적으로 채점할 수 있다는 것입니다. 이 가설이 성립한
뒤에 그 위에 목표 점수를 더했습니다.

## 레인지

compose 서비스 11개가 Docker 네트워크 6개 위에 있습니다. 대상 시스템은 워게임별로
묶여 있습니다. 워게임마다 `wargames/` 아래에 폴더가 하나 있고, 최상위
`compose.yaml`이 그 폴더의 `compose.yaml`을 포함합니다. `juice-shop`(Juice Shop과
그 SSRF가 닿는 wiki)과 `board`(게시판과 그 MySQL)입니다. 새 워게임은 새 폴더 하나와
`include:` 한 줄이면 되고, 측정 지표는 그 워게임이 추가하는 서비스도 셉니다.

| 서비스 | 이미지 | 네트워크 | 호스트 포트 |
|---|---|---|---|
| `fsl-juice-shop` | `bkimminich/juice-shop` | estate | |
| `fsl-board` | `wargames/board/app` (gunicorn에서 도는 Django, 포트 8000) | estate | |
| `fsl-board-db` | `mysql` | estate | |
| `fsl-wiki` | `nginx`, 별칭 `wiki.internal` | estate | |
| `fsl-waf` | `owasp/modsecurity-crs` (nginx), edge에서는 별칭 `shop.com`, edge 네트워크 네 개 모두에서는 `board.com` | edge, edge-br, edge-hk, edge-us, estate | 8080 |
| `fsl-suricata` | `jasonish/suricata` | 웹방화벽의 네임스페이스 | |
| `fsl-elasticsearch` | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-filebeat` | `filebeat:8.15.0` | mgmt | |
| `fsl-kali` | `deploy/kali` | edge | |
| `fsl-proxy` | `deploy/proxy` (mitmdump) | edge 네트워크 네 개 | |
| `fsl-platform` | `platform/` (waitress에서 도는 Django, 앞단에 nginx가 있고 이 nginx가 Kali의 터미널도 `/terminal/`에서 제공) | 여섯 개 모두 | 8000 |

| 네트워크 | 구간 | 서브넷 | 이름 | 출발지 |
|---|---|---|---|---|
| `edge` | `ru` | 5.188.10.0/24 | Internet | Russia |
| `edge-br` | `br` | 177.54.144.0/24 | Internet | Brazil |
| `edge-hk` | `hk` | 103.152.220.0/24 | Internet | Hong Kong |
| `edge-us` | `us` | 73.0.0.0/24 | Internet | United States |
| `estate` | `estate` | 172.30.0.0/24 | Application estate | |
| `mgmt` | `mgmt` | 172.31.0.0/24 | Management | |

선언은 인터넷망 하나에 출발지 30개를 나열합니다. Cloudflare Radar의 HTTP 요청
점유율 상위 30개 국가이고, 국가마다 GeoIP가 그 나라에 있다고 판정하는 /24 하나와,
약 100개인 공격 주소 중 그 나라의 몫이 있습니다. Docker 브리지 하나는 IPv4 서브넷을
하나만 가지므로, Docker는 그중 네 개만 각각 네트워크 하나로 만듭니다. OpenStack
패브릭은 30개 모두를 네트워크 하나의 서브넷으로 만듭니다. `bin/pick-origins`가 이
표를 다시 만들어 내고, 인수 테스트 하나가 모든 서브넷을 점수 계산이 읽는 pipeline에
대조해 확인합니다.

망 분리는 Docker 네트워크 소속만으로 이뤄집니다. 방화벽도, iptables도, ACL도
없습니다. `test/test_segmentation.py`가 실행 중인 스택을 대상으로 이를 검증합니다
(Kali는 `shop.com`에는 닿지만 `juice-shop:3000`에는 닿지 않습니다). 고정된 것은
서브넷뿐이고, 컨테이너 주소는 Docker가 할당하므로 다시 만들면 바뀝니다. 뷰는
요청마다 어댑터를 새로 만들어 주소를 읽습니다. 레인지 호스트에서 온 요청을 거부하는
규칙은 그 주소를 30초 동안 캐시하고, 기반 계층에 연결할 수 없으면 레인지가 비어
있다고 보고 요청을 통과시킵니다(`docs/THREAT-MODEL.md`).

플랫폼, 웹방화벽, 프록시는 여러 네트워크에 동시에 붙어 있습니다(multi-homed).
공격자의 트래픽은 웹방화벽에서만 estate로 넘어가지만, 플랫폼은 모든 구간에 걸쳐
있습니다. 그래서 API가 스스로를 지킵니다(`docs/THREAT-MODEL.md`).

```
 edge      kali --HTTP via http_proxy--> proxy:8081 --+
           kali --raw TCP (nmap, nc), no proxy--------+
           platform --console-fired case--------------+
 edge-br                                              |
 edge-hk   proxy, platform (no kali, no shop.com)     |
 edge-us                                              v
         fsl-waf: nginx + ModSecurity CRS, DetectionOnly, port 80
         fsl-suricata in the same network namespace, af-packet on all five
         interfaces, so it sees client->WAF and WAF->target
                                                      |
 estate    juice-shop:3000 <--any other Host----------+
           board:8000 <--Host: board.com--------------+
           juice-shop --SSRF--> wiki.internal
           board --> board-db (MySQL)
 mgmt      filebeat --> elasticsearch <-- platform

 Not network traffic:
   eve.json --bind mount--> filebeat
   ModSecurity audit.log --volume waflogs--> filebeat
   ./data/label --bind mount--> proxy (read-write), kali (read-only)
   kali's shell --> /var/log/fsl/commands.log, each command with its marker
   platform --docker exec--> wiki (read log), proxy (/label files),
                             suricata (rules), kali (command log)
   platform --docker run--> throwaway fsl-kali for tool cases
   platform --> volume platformdata --> /data/db.sqlite3
```

`deploy/suricata/suricata.yaml`은 인터페이스를 eth0부터 eth4까지 이름으로 지정하고,
Docker가 `compose.yaml`에 정한 우선순위 순서대로 웹방화벽의 네트워크를 붙인다는
데 기댑니다. 이 대응이 맞는지 확인하는 것은 없습니다.

웹방화벽은 `Host: board.com`을 `board:8000`으로 보내고(`deploy/nginx/board.conf`),
나머지는 모두 자기 `BACKEND`인 `juice-shop:3000`으로 보냅니다. 게시판은 두 번째
워게임입니다. gunicorn에서 도는 Django 5.2이고, 시작할 때 스스로 마이그레이션하고
초기 데이터를 넣으며, digest로 고정한 MySQL 위에서 돕니다. 둘 다 포트를 공개하지
않습니다. 게시판은 판정 대상이 아닙니다. 게시판에는 목표가 없고, 세션은 판정 대상
워게임에 대해서만 기준선 스냅샷을 찍으므로, 게시판 세션은 방어만 채점합니다.

## 선언과 기반 계층 경계

Docker는 MVP의 기반 계층이고, 최종적으로 옮겨 갈 곳은 OpenStack입니다. 플랫폼은
레인지가 무엇을 뜻하는지 Docker에게 묻지 않습니다. `platform/range/declaration.yaml`이
알려 줍니다. 구간마다 id, 표시 이름, 공격 출발지가 있고, 역할 표(attacker, scorer,
gateway, proxy, sensor, target, wiki, board, board-db), 센서가 감시하는 호스트, 기본
출발지, 지도가 선을 긋는 방어 대상 지점(서울)이 있습니다. 출발지를 선언한 구간이 곧
외부 구간이고, 그 밖의 구간은 외부가 아닙니다.

**식별 정보는 선언하고, 할당은 보고받습니다.** 선언에는 서브넷, 게이트웨이, 주소가
없습니다. 이것들은 기반 계층에서 옵니다. Docker와 Neutron이 모두 직접 나눠 주는
값이고, 선언한 서브넷이 실제와 다르면 아무것도 없는 서브넷을 기준으로 경보를
분류하게 되기 때문입니다. `compose.yaml`은 같은 식별 정보를 네트워크 라벨에 한 번 더
적습니다. `platform/tests/test_declaration.py`는 두 파일이 서로 맞는지 확인하지만,
실행 중인 레인지는 확인하지 않습니다.

**구간은 표식으로 연결하고, 호스트는 아직 이름으로 연결합니다.** 구간마다
`fsl.segment.id`를 Docker 라벨이나 Neutron 태그로 달고, 어댑터는 표식이 있는
네트워크만 가져옵니다. 이름 규칙은 compose의 접두사와 override, Heat 스택의 접미사,
유일하지 않은 Neutron 이름 때문에 깨졌습니다. 역할은 선언이 정한 컨테이너 이름이나
서버 이름입니다. Docker는 `docker exec <name>`을 실행하고, OpenStack은 프로젝트의
서버를 모두 나열해 `server["name"]`과 맞춥니다. Nova는 이 이름의 유일성을 보장하지 않습니다. 이 문제는 `docs/STATE.md`에
아직 열려 있습니다.

`platform/range/ports.py`가 포트(port)입니다. 핵심 코드와 플랫폼의 대부분은 이
포트의 동작 네 가지만 봅니다.

- `describe()`는 구조를 돌려줍니다. 구간, 그 노드와 주소, 센서입니다.
- `segments()`는 누가 어디에 있는지를 돌려주며, 센서에 대해서는 묻지 않습니다.
- `runner(role, segment)`는 상시 떠 있는 호스트(센서, wiki, 프록시, 그리고 플랫폼이
  명령 로그를 읽는 공격자)에서 명령을 실행합니다.
- `launcher(segment)`는 구간 위에서 일회성 도구를 실행하고 그 출력을 돌려줍니다.

`range.substrate()`는 `FSL_SUBSTRATE`가 가리키는 어댑터(기본값
`range.docker.Docker`)를 만듭니다. 옵션은 `FSL_SUBSTRATE_OPTIONS`에 그 이름으로 들어
있는 값에 `declared=RANGE`를 더한 것입니다. Docker는 `FSL_PROJECT`(기본값 `fsl`)를
받습니다. OpenStack은 `FSL_OPENSTACK_KEYSTONE`, `_USER`, `_PASSWORD`, `_PROJECT`,
`_SSH_USER`, `_SSH_KEY`를 받으며, 하나라도 없으면 그 이름을 대며 거부합니다.
`_SSH_CONFIG`는 선택이지만 지정했다면 그 경로가 존재해야 합니다. `_REGION`의
기본값은 `RegionOne`, `_INTERFACE`의 기본값은 `public`입니다. `redteam/harness.py`는
launcher를, `platform/rules/suricata.py`는 runner를 넘겨받으므로, 둘 다
`subprocess`를 import하지 않고 특정 기반 계층을 가리키지도 않습니다.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| 구조 | `docker network ls/inspect`, 라벨 필터 | Keystone v3, `tags-any`를 쓰는 Neutron, Nova |
| 센서 | 선언된 센서 중 하나라도 선언된 게이트웨이의 네트워크 네임스페이스를 공유하지 않으면 `describe()`가 레인지 구조를 돌려주지 않고 거부함(`docker ps`, `.HostConfig.NetworkMode`) | 이름이 지정된 두 서버가 모두 있으면 언제나 센서를 보고함. 센서가 게이트웨이의 트래픽을 보는지는 아무것도 확인하지 않음 |
| runner | `docker exec` | 인스턴스로 `ssh` |
| launcher | `docker run --rm --network <segment>` | `runner("attacker")`: 선언된 공격자에서 ssh로 도구를 실행함. 다른 이미지는 거부함. Nova로는 호스트를 띄우고, 그 출력을 돌려받고, 지우는 일을 한 번에 할 수 없기 때문 |
| 검증한 환경 | 실행 중인 스택 | 공개된 API 레퍼런스로 만든 가짜 객체와 로컬 sshd에 대한 단위 테스트. `fsl-range` 클라우드에서는 플랫폼 VM이 `/api/range/fabric/`로 패브릭을 만들었고, `describe()`가 이를 출발지 30개, estate, mgmt로 다시 읽어 냄. `runner()`와 `launcher()`는 클라우드에서 실행된 적 없음 |

compose는 기반 계층이 무엇이든 플랫폼에 Docker 소켓을 마운트하고, entrypoint가
플랫폼 사용자를 그 소켓의 그룹에 추가합니다. 이것은 컨테이너 탈출 경로입니다.
OpenStack 어댑터를 쓰면 이를 없앨 수 있게 되지만, 아직은 그대로 남아 있습니다.
어댑터가 레인지를 구동할 수 있게 되기까지 남은 일(이름 해석, `watches`를 확인하는
대신 pfSense 패키지로 도는 센서를 읽는 것, 출발지 서브넷이 여러 개인 인터넷망
하나와 그 위의 Kali VM 하나, 서버 이름으로 정하는 역할, 라우터를 거칠 때 운영자의
주소가 어떻게 보이는지, SNAT)은 `docs/STATE.md`의 "The substrate seam"에 있습니다.

## 요청이 오는 곳

| 경로 | 보내는 쪽 | 경보에 찍히는 출발지 주소 | 마커 |
|---|---|---|---|
| 터미널, HTTP | Kali, `proxy:8081` 경유 | 선택한 출발지에 있는 프록시 | 프록시가 붙임 |
| 터미널, raw TCP | Kali가 직접 | Kali, `edge`에서만 | 없음 |
| 콘솔 시나리오, HTTP | 플랫폼 | 선택한 출발지에 있는 플랫폼 | 하네스가 붙임 |
| 콘솔 시나리오, 도구 | 일회용 `fsl-kali` 컨테이너 | 선택한 출발지에 있는 그 컨테이너 | sqlmap `--headers=` |
| CLI 실행 또는 브라우저, HTTP | 호스트, 8080 포트 경유 | `edge` 브리지 게이트웨이 | 하네스가 붙임. 브라우저에서는 없음 |
| CLI 실행, 도구 | 일회용 `fsl-kali` 컨테이너, `launcher(--origin or the declared default)`에서 실행 | 그 컨테이너 | sqlmap `--headers=` |

프록시는 `mitmdump` 스크립트입니다. `/label/active`에서 읽은 값으로 `X-FSL-Case`를
설정하고, `/label/origin`에 주소가 적혀 있으면 원래의 `Host`를 유지한 채 요청을 그
주소로 전달합니다. 두 파일은 플랫폼이 `docker exec`로 씁니다. TLS 가로채기는
없으므로, 프록시는 통제 지점이 아니라 환경 변수 하나일 뿐입니다.
`curl --noproxy '*'`이면 프록시를 건너뜁니다.

터미널은 운영자가 입력하는 것도 기록합니다. Kali의 셸은 명령마다 현재
`/label/active`의 마커를 붙여 `/var/log/fsl/commands.log`에 덧붙입니다. 플랫폼은 이
파일을 `runner("attacker")`로 읽어 `GET /api/sessions/<id>/commands/`로 제공합니다.

콘솔 HTTP 시나리오는 출발지를 골랐든 아니든 세션 워게임의 `Host`, 즉 `shop.com`이나
`board.com`을 담습니다. 출발지를 고르면 트래픽은 그 구간에 있는 웹방화벽의 주소로
향합니다. `board.com`은 edge 네트워크 네 개 모두에서 이름이 해석되고, `shop.com`은
`edge`에서만 해석됩니다. `rotate`는 무작위 선택이 아니라 세션별 라운드 로빈입니다.

콘솔 도구 시나리오는 출발지의 대상 URL을 향합니다. 출발지를 고르지 않았으면 선언된
기본 출발지에서 `TARGET_URL`(`http://shop.com`)을 향합니다. CLI의 `--tool-target`
기본값은 `http://waf:8080`이지만, 레인지 안에서 웹방화벽은 80번(과 8443번) 포트에서
요청을 받습니다. 8080은 호스트 쪽에 공개한 포트일 뿐입니다.

웹방화벽은 CRS를 paranoia level 1, 이상 점수 임계치(anomaly threshold) 5, `DetectionOnly`로 돌리고, Suricata
룰은 모두 `alert`입니다. 레인지 안의 어떤 것도 요청을 차단하지 않습니다.

wiki에는 애플리케이션을 거쳐 SSRF로만 닿을 수 있습니다. Juice Shop은
`/profile/image/url`에 POST된 `imageUrl`을 가져옵니다. 이것을 하는 스크립트
시나리오는 없습니다.

## 경보가 가는 곳

```
WAF (ModSecurity) -> audit.log --+
Suricata ---------> eve.json ----+-> Filebeat -> Elasticsearch, fsl-logs-<day>
                                     (fsl_source)   pipeline fsl-geoip
                                                          |
             blue console timer -> POST /api/sessions/<id>/ingest/
                                                          |
             parse per fsl_source, lift the marker onto alerts, store
             as Detection rows in SQLite
```

ModSecurity의 감사 로그에는 요청 헤더가 들어 있어서, 그 경보에는 마커가 바로
실립니다. Suricata의 `alert` 이벤트에는 요청 헤더가 없고, `http` 이벤트에만
있습니다(`dump-all-headers: request` 설정 시. `custom: [X-FSL-Case]`는 효과가
없습니다). 수집 단계는 같은 `(flow_id, tx_id)`를 가진 `http` 이벤트에서 마커를
복사해 경보에 붙입니다. `flow_id`만으로 조인했을 때는 keep-alive 연결 위의 모든
경보가 그 연결의 첫 시나리오에 귀속됐습니다.

수집 호출은 한 번마다 다음을 합니다.

- 먼저 기한이 지난 룰 억제를 원래대로 되돌립니다.
- Elasticsearch에 세션 시작 1분 전부터 세션 종료(또는 현재) 1분 후까지의
  `@timestamp`를 요청합니다. `@timestamp`는 Filebeat가 읽은 시각입니다.
  `filebeat.yml`도 pipeline도 이 값을 이벤트에서 가져와 설정하지 않습니다.
- 최대 5000건을 오래된 것부터 읽습니다. 그보다 많으면 응답에 `truncated`가 실리고,
  세션에 그 표시가 계속 남아 `score.warning.truncated`가 붙습니다.
- Suricata의 `alert` 이벤트는 남기고, ModSecurity의 기록은 매칭된 룰 메시지마다
  Detection 하나로 바꿉니다. 그 id는 `<Elasticsearch _id>:<n>`입니다.
- 경보 자체의 이벤트 시각이 시간 창 밖에 있으면 버리고, `stale`로 셉니다.
- 나중에 찾은 마커를, 저장된 행 중 마커가 없던 행에 써 넣습니다.
- 기반 계층의 구간 정보로 `src_host`와 `dest_host`를 채웁니다. 기반 계층에 연결할
  수 없으면 빈 값으로 둡니다.

Elasticsearch는 저장과 색인 시점의 geoip에 쓰며, 그래서 Logstash가 없습니다. 시간
범위 검색 외에는 쿼리 엔진을 쓰는 곳이 없습니다. 지도와 상위 N개 표는 SQLite에 복사한
데이터를 Python으로 계산하고, `src_geo.location`은 `geo_point`가 아니라 float 두
개로 매핑합니다. 세계 지도는 남위 60도에서 자른 Equal Earth 도법이며
`bin/worldmap`이 생성합니다.

pipeline에는 geoip 프로세서가 두 개 있습니다. `src_ip`(Suricata)와
`transaction.client_ip`(ModSecurity)이고, 둘 다 `src_geo`에 씁니다. 저장소는
GeoLite2 데이터베이스를 준비하지 않습니다. compose는 `config/ingest-geoip`에 아무것도
마운트하지 않고, downloader 옵션도 설정하지 않습니다. 실행 중인 노드에서 downloader는
한 번도 성공한 적이 없습니다. 데이터베이스는 손으로 복사해 넣었고, 컨테이너를 다시
만들면 사라집니다.

## 점수 계산 방식

**목표.** 플랫폼은 대상 시스템의 `/api/Challenges/`를 읽고 각 `solved` 플래그를
그대로 받아들입니다. 시각은 Juice Shop의 `updatedAt`인데, 세션 시작 5초 전부터 관찰
시점 사이에 있을 때만 믿습니다. 그렇지 않으면 목표는 관찰한 시각으로 기록됩니다.
신뢰한 타임스탬프는 Objective 행에 저장되는 시간 창이 됩니다. 그 타임스탬프 100 ms
전부터, 타임스탬프에 해상도(소수부가 있으면 1 ms, 없으면 1초)와 100 ms를 더한
시각까지입니다. Juice Shop이 다음 요청이 올 때에야 확인하는 문제 13개
(`stamped_late`)는 시간 창이 100 ms가 아니라 2분 전까지 거슬러 올라갑니다.

플랫폼이 직접 판정하는 목표는 `internalRunbookRead` 하나뿐입니다. wiki 자신의 접근
로그에 비밀 wiki 페이지를 성공적으로 읽은 기록이 있으면 성립합니다. 난이도 6에는
기록된 근거가 없습니다. 인수 테스트 말고는 wiki 로그를 지우는 것이 없으므로, SSRF가
한 번 성공하고 나면 이후 세션은 런북을 이미 읽은 상태로 시작합니다.

세션은 시작할 때 이미 풀린 목표를 스냅샷으로 남기고, 그 목표는 점수로 인정하지
않습니다. 그 시점에 대상 시스템이나 wiki를 읽을 수 없어도 세션은 기준선 없이
만들어지고, 스냅샷은 처음으로 관찰에 성공한 시점에 찍힙니다. 그 사이에 풀린 것은
끝내 인정되지 않습니다. 스냅샷과 목표가 있는 것은 판정 대상 워게임뿐이고, 게시판을
관찰하면 0개 중 0개가 나옵니다.

대상 시스템에 연결할 수 없을 때 503이 되는 것은 목표 엔드포인트 두 개,
`GET /api/wargames/<id>/objectives/`와 `POST /api/sessions/<id>/objectives/`뿐입니다.
세션 생성, 시나리오 실행이나 기록(`POST .../cases/`는 `objectives: null`로
응답합니다), 세션 종료(응답에 `unobserved`가 실립니다)는 이를 흡수합니다. 기준선이
생긴 뒤에는 wiki 로그를 읽을 수 없어도 503이 아닙니다. 관찰 결과에 `unreadable`이
실리고, 목표 목록은 런북을 `solved: null`로 보여 줍니다.

빼앗긴 목표는 실행 구간이 그 목표의 시간 창과 겹치는 공격 시나리오에 귀속됩니다.
그런 시나리오가 여럿이면 가장 늦게 시작한 것에 귀속됩니다. 신뢰할 타임스탬프가
없으면 시간 창은 관찰 2분 전부터 100 ms 후까지입니다. 목표는 그 시나리오가 탐지됐을
때만 탐지된 것으로 세고, 겹치는 시나리오가 없는 목표는 탐지되지 않은 것으로 셉니다.
귀속은 시간만으로 정합니다. 시나리오의 `takes:` 필드는 레드 콘솔에 보이지만 점수
계산은 이를 읽지 않습니다.

점수의 `objectives` 블록에서 `coverage`는 탐지된 난이도를 전체 난이도로 나눈 값이고,
빼앗긴 것이 없으면 `null`입니다. `false_positives`는 FP입니다. `damage`는 탐지되지
않은 난이도에 탐지된 난이도의 절반을 더한 값입니다. "탐지되지 않은 손실은 두 배로
센다"는 원칙은 바로 이 비율에 들어 있습니다.

**탐지.** 시나리오는 두 전략 중 하나로 경보와 매칭됩니다. 전략은 시나리오마다
선언합니다.

- `marker`: 경보에 시나리오의 `X-FSL-Case` 값이 실려 있습니다.
- `window`: 경보의 출발지 주소가 시나리오의 주소와 같고, 경보 시각이 시나리오의
  시작과 끝 사이에 있습니다. 양쪽에 2초씩 여유를 둡니다.

한 전략이 실패했다고 다른 전략으로 넘어가지 않습니다. 마커를 잃어버린 marker
시나리오는 미탐으로 드러나야 하고, window가 이를 덮어 주어서는 안 됩니다. 터미널
시나리오는 둘 다 가집니다. 점수 엔드포인트에 `?correlation=marker`나
`?correlation=window`를 붙이면 전략을 강제하며, 다른 값은 400입니다. 블루 콘솔은
전략마다 한 번씩 요청해 둘을 비교합니다. 둘이 다르면 그것은 방어가 아니라 채점
방식에 대한 발견입니다.

`per_case`의 각 항목에는 `expect`와 `corroborated`가 있습니다. `corroborated`는
매칭된 경보 중 하나의 시그니처에 `expect`가 대소문자 구분 없이 들어 있으면 참입니다.
같은 세션에서 정상 시나리오와도 매칭된 시그니처는 세지 않습니다. 시나리오에
`expect`가 없으면 `null`이며, 터미널 시나리오는 늘 그렇습니다. 레드 콘솔이
`expect`를 보내지 않기 때문입니다. 탐지됐지만 corroborated가 아닌 시나리오는
`score.warning.wrong_reason`을 더합니다.

시나리오의 `expect`는 실행할 때 시나리오와 함께 저장되므로, 시나리오 파일을 고쳐도
끝난 세션이 다시 판정되지 않습니다. 마이그레이션 0009 이전에 기록된 행에는 저장된
`expect`가 없어서, 여전히 현재 시나리오 파일을 기준으로 판정됩니다. 경보의 심각도와
룰 유형은 쓰지 않습니다.

**게임.** 점수의 `game` 블록은 세션이 종료될 때까지 `{"revealed": false}`입니다.
종료되면 네 항목과 그 가중치, 그리고 balance를 담습니다.

- 속도(speed, 0.25): 공격 시나리오마다, 처음 매칭된 경보가 시작 후 10초 안에 왔으면
  1, 120초 이후면 0, 그 사이는 선형으로 매기고, 이를 평균합니다.
- 정확도(accuracy, 0.30): 재현율에서 오탐률을 뺀 값이며, 0 아래로 내려가지 않습니다.
- 적용 범위(coverage, 0.20): 공격받은 단계 중 탐지된 공격 시나리오가 있는 공격
  단계(`platform/lifecycle.py`)의 비율이며, 공격받은 단계가 없으면 0입니다. `objectives`
  블록의 `coverage`와는 다릅니다.
- 대응(response, 0.25): 차단된 공격 시나리오의 비율에서 차단된 정상 시나리오의
  비율을 뺀 값입니다. 어떤 시나리오에 `meta["blocked"]`가 생길 때까지는 `null`이고,
  그동안 나머지 가중치를 다시 정규화합니다. 아직 이 값을 설정하는 것은 없습니다.

`attacker`는 빼앗긴 목표의 난이도 합이며, 탐지된 목표는 절반으로 셉니다. `damage`와
같은 합입니다. `defender`는 항목들의 가중 평균에 빼앗긴 난이도를 곱하고 FP 하나당
1을 뺀 값입니다. `balance`는 `defender - attacker`입니다. 게시판에서는 빼앗기는 것이
없으므로 balance는 FP의 음수입니다. 가중치와 체류 시간은 v1 기본값입니다
(`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`).

점수 엔드포인트는 읽기 전용이고 이력을 남기지 않습니다.

## 결정 사항

- **워게임마다 시나리오 파일 하나, 공격과 정상 트래픽을 함께**: Juice Shop용
  `redteam/cases/default.yaml`(공격 10개, 정상 6개)과 게시판용 `board.yaml`(6개와
  3개). 파일을 나누면 정상 쪽 절반을 잊기 쉽습니다. CLI는 `--cases`로 다른 파일을
  지정하지 않으면 `default.yaml`을 읽고, 언제나 Juice Shop 세션을 엽니다.
- **하네스는 경로가 바뀐 요청은 보내기를 거부합니다.** `requests`는
  `/ftp/../../etc/passwd`를 `/etc/passwd`로 바꿉니다. 그대로 보내면 실제로는 나가지
  않은 공격이 기록되고, 하네스의 실패가 방어의 실패로 채점됩니다. 퍼센트 인코딩
  차이는 허용합니다.
- **시작하지 못한 도구는 예외를 던지고, 0이 아닌 코드로 끝난 도구는 셉니다.**
  sqlmap은 아무것도 찾지 못하면 0이 아닌 코드로 끝나지만, 트래픽은 이미 나갔습니다.
- **Suricata는 웹방화벽의 네트워크 네임스페이스를 공유합니다.** 호스트 네트워킹은
  Docker 호스트에 따라 의미가 달라지므로 쓰지 않습니다. 웹방화벽의 인터페이스에는
  요청마다 들어오는 쪽과 나가는 쪽이 모두 지나갑니다.
- **compose 레인지에는 아직 Kibana가 없습니다.** 블루 콘솔이 탐지 목록을 보여 주고,
  Elasticsearch는 여전히 임시 쿼리에 응답합니다. Kibana는 블루팀을 위해 읽기 전용으로
  돌아올 예정입니다("OpenStack" 절 참고).
- **Elasticsearch는 힙 512 MB의 단일 노드입니다.** 스택 전체가 Docker의 기본 메모리
  할당 안에 들어가게 하기 위해서입니다.
- **빠진 데이터는 0이 아니라 오류입니다.** 예외는 명시합니다. Elasticsearch나 기반
  계층에 연결할 수 없을 때, 룰 파일을 읽을 수 없을 때, 그리고 위에서 말한 목표
  엔드포인트는 503으로 응답합니다. 세션 생성, 시나리오 실행이나 기록, 세션 종료는
  대상 시스템이나 wiki 로그에 연결할 수 없는 상황을 흡수합니다(다만 시나리오 실행은
  출발지나 도구 때문에 기반 계층이 필요하면 여전히 503으로 응답합니다). 수집 중의
  억제 복원과, 경보를 구간과 호스트에 배치하는 일(빈 값으로 돌아옵니다)은 기반 계층에
  연결할 수 없는 상황을 흡수하므로, 라운드는 여전히 시작하고 끝낼 수 있습니다.
  분모가 0인 비율은 null이 아니라 0.0입니다. 정밀도, 재현율, F1, FPR, 그리고 게임의
  속도, 적용 범위, 정확도가 그렇습니다. null이 되는 것은 `objectives` 블록의
  `coverage`뿐입니다.
- **점수는 스스로 보증할 수 없는 것을 밝힙니다.** 정상 시나리오가 없을 때
  (`no_benign`), marker 시나리오가 있는데 어느 경보에도 마커가 없을 때(`no_marker`),
  출발지 주소가 없는 window 시나리오가 있을 때(`no_source_ip`), 탐지됐지만
  corroborated가 아닌 시나리오가 있을 때(`wrong_reason`), Elasticsearch에 있는 건수가
  수집이 읽은 건수보다 많을 때(`truncated`) 경고를 붙입니다.
- **콘솔에서 실행한 시나리오는 HTTP 연결 하나에 시나리오 하나를 보내고**, CLI는 실행
  전체에 연결 하나를 유지합니다. 같은 12개 시나리오로 측정했을 때 두 방식의 점수와
  시나리오별 경보 건수는 같았습니다. 인수 테스트는 CLI로 돌리므로, 연결을 공유하는
  경우도 계속 테스트됩니다.

## OpenStack

구축은 `docs/STATE.md` 백로그의 OpenStack 항목을 그 순서대로 따릅니다. 지금 있는
것은 첫 단계인 플랫폼 VM뿐입니다. 아래 각 선택의 근거는 `docs/STATE.md`("Decided on
2026-09-30"), `docs/superpowers/specs/2026-09-30-openstack-range-placement.md`,
`docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`에 있고, 이 절은
구조만 기록합니다.

클라우드는 KVM 컴퓨트 노드 하나(8 vCPU, 64 GB)이고, kolla-ansible 2026.1과
ML2/Open vSwitch로 돕니다. 레인지는 `fsl-range` 프로젝트에 있고, member 역할 사용자
`fsl-range`가 다룹니다. Horizon은 사용자에게 절대 보여 주지 않습니다.

### 만든 것: 플랫폼 VM

`deploy/openstack/platform.yaml`은 Heat 템플릿입니다. 이 템플릿은 다음을 만듭니다.

- 네트워크와 서브넷 `fsl-platform`
- 외부 네트워크로 가는 라우터와 floating IP
- 모든 주소에 tcp/22, tcp/8000, ICMP를 여는 보안 그룹
- config drive를 쓰는 Nova 서버 `fsl-platform`

파라미터와 기본값은 `README.md`에 있습니다.

cloud-init은 `docker.io`, `docker-compose-v2`, `git`을 설치하고, 4 GB 스왑을
추가하고, Docker의 MTU를 Neutron 네트워크의 MTU로 맞춥니다. 기본 브리지에는
`mtu`로, compose가 만드는 것을 포함한 모든 새 브리지 네트워크에는
`default-network-opts`로 맞춥니다. 그리고 `repository`의 `ref`를 `/opt/fsl`에
clone하고, `ubuntu`를 `docker` 그룹에 추가합니다. systemd 유닛
`fsl-platform.service`가 부팅할 때마다
`docker compose -f /opt/fsl/compose.yaml up -d --build`를 실행합니다.

그래서 지금은 위의 compose 레인지 전체, 서비스 11개가 모두 Nova VM 하나 안에서
돕니다. 8000은 VM 자기 주소에 공개되고 보안 그룹에서도 열려 있으므로, 브라우저는
floating IP로 콘솔에 접속합니다. 나머지 포트는 VM의 loopback에만 있습니다.

cloud-init은 `FSL_OPENSTACK_KEYSTONE`, `_USER`, `_PROJECT`(스택 자신의 프로젝트),
`_SSH_USER=ubuntu`, `_SSH_KEY=/data/ssh/id_ed25519`를 모드 0600으로
`/root/openstack.env`에 쓴 뒤, git이 무시하는 `/opt/fsl/openstack.env`로 옮깁니다.
비밀번호는 템플릿에 없습니다. Nova는 user data를 보관하고, 메타데이터 서비스는 이를
VM에서 도는 모든 것에 내주기 때문입니다. 레인지의 컨테이너도 예외가 아닙니다.
운영자는 VM이 뜬 뒤 ssh로 `FSL_OPENSTACK_PASSWORD`를 덧붙입니다(`README.md`).
플랫폼 서비스는 이 파일을 `env_file`(`required: false`, `format: raw`)로 읽으므로,
compose는 변수 치환이나 따옴표 제거 없이 값을 그대로 넘깁니다.

VM의 플랫폼은 OpenStack 어댑터(cloud-init이 쓴 `FSL_SUBSTRATE`)를 쓰고,
`range/fabric.py`가 계획한 대로 `/api/range/fabric/`을 통해 레인지의 네트워크를 직접
만듭니다. 선언된 출발지마다 서브넷이 하나씩 있는 `internet` 네트워크 하나(DHCP
꺼짐), 10.30.0.0/24의 `estate`와 게이트웨이 없는 10.31.0.0/24의 `mgmt`(둘 다
compose와 플랫폼 VM의 어느 서브넷과도 겹치지 않음), 그리고 플랫폼이 `/data/ssh/id_ed25519`에
만드는 키로 만든 키페어 `fsl-platform`입니다. `describe()`는 각 출발지를 CIDR로 그
하나뿐인 인터넷 네트워크의 해당 서브넷에 연결합니다. VM의 라우터에는 VM 자신의
서브넷만 붙어 있으므로, 플랫폼은 API로 레인지를 읽을 뿐 아직 레인지의 어느
호스트에도 닿지 않습니다. 이후 단계에서 그곳에 호스트를 두고 플랫폼을 `mgmt`에
연결합니다.


### 결정했지만 아직 만들지 않은 것: OpenStack 위의 레인지

2026-09-30에 사용자가 결정했습니다.

```
 OpenStack project fsl-range.

 platform VM: Ubuntu 24.04, floating IP, docker compose up
   console and /api/, scoring, Elasticsearch, Filebeat, Kibana
   landing page /: start and stop a session, the scoreboard after close
   sidebar, three panes inside the page:
     pfSense   noVNC console of a kiosk browser VM showing pfSense's GUI
     Kibana    framed directly, on a read-only Elasticsearch role
     terminal  ttyd on the Kali VM, reverse-proxied by the platform
     |
     +--OpenStack API, as member fsl-range--> networks, VMs, consoles
     +--management network, ssh-------------> Kali VM, target VMs

 Internet network: one subnet per origin country (30), no Neutron router
   Kali VM: one port holds every attack address; the source is rewritten
            to the chosen country's address as packets leave
     |
     v
 pfSense CE VM: edge firewall; its WAN holds each subnet's gateway address
                and routes on without NAT, so country sources survive
   Suricata package: IDS/IPS, drop rules switched by blue in the pfSense GUI
     |
     v
 WAF VM: nginx + ModSecurity v3 + CRS, blocking mode switched by blue
     |
     v
 estate network
   Juice Shop VM     board VM (Django on MySQL)     wiki VM
   Juice Shop --SSRF--> wiki, inside the estate, past no gateway

 Evidence:
   pfSense: Suricata EVE, filterlog --syslog, UDP--> Filebeat --+
   WAF VM: ModSecurity audit log --------------------------------+
                                                                 v
   Elasticsearch --> platform ingest --> scoring
   Elasticsearch --read-only role--> Kibana --> blue team
```

그림에 없는 내용은 다음과 같습니다.

- **출발지**: 토큰 없이 받을 수 있는 공개 인터넷 트래픽 순위에서 고른 30개
  국가입니다. GeoIP로 위치를 정하고, 주소 약 100개를 트래픽에 따라 가중해 국가마다
  적어도 하나씩 나눕니다. 선언에는 출발지 서브넷이 여러 개인 구간 하나가 생깁니다.
  지금 어댑터는 IPv4 서브넷이 둘 이상인 구간을 거부합니다.
- **공격자**: 마커를 찍는 프록시는 Kali VM으로 옮겨 가고, Nova 콘솔은 터미널의 대체
  수단이 됩니다.
- **차단은 실무에서처럼 동작합니다**: 블루팀이 웹방화벽의 모드와 Suricata의 drop
  룰을 직접 전환합니다. 시나리오가 차단됐는지는 대상 시스템 쪽에서 읽어
  `meta["blocked"]`에 넣으며, 대응 항목에 이 값이 필요합니다.
- **목표**는 게시판 쪽으로 옮겨 갑니다. 게시판의 `auth_user` 테이블이 레드팀이
  빼앗을 수 있는 대상이 되고, 판정은 게시판 자신의 쪽에서 합니다.
- **이벤트 시각 기준의 증거**: `@timestamp`를 Suricata의 `timestamp`와 ModSecurity
  자신의 시각에서 가져오고, 레인지의 모든 VM 시계는 chrony로 맞춥니다. GeoIP는
  `config/ingest-geoip`용 영구 바인드 마운트에 한 번 넣어 두고, downloader는 끕니다.
- **Kibana**는 Elasticsearch 보안을 켜고 읽기 전용 블루 역할을 둔 채 compose로
  돌아옵니다. 블루 대시보드는 대부분 없어지고, 실시간 대시보드와 룰 편집기는
  없어집니다.
- **이미지**: 저장소에 둔 설정 스크립트로 VM마다 한 번 만들고, 그 스냅샷을 이미지로
  씁니다.
- **수명 주기**(첫 시도): 패브릭(네트워크, 보안 그룹, 키페어, 이미지)은 운영자의
  조작으로만 만들고 없애며, REST가 먼저입니다. 슬롯마다 Heat 스택 하나이고, 역할은
  그 스택의 리소스 목록으로 찾습니다. 프로비저닝은 슬롯을 만들고 시험 실행합니다.
  시작은 준비된 슬롯을 가져올 뿐 아무것도 만들지 않습니다. 중지는 어느 팀이든 바꿀
  수 있는 VM을 모두 한꺼번에 다시 만듭니다. 슬롯은 레인지가 스스로 상태를 증명할
  때만 준비된 것입니다. 풀린 것이 없고, 룰과 웹방화벽 모드가 기준 상태이며, 시계가
  맞고, Elasticsearch에 카나리 경보가 있어야 합니다.

사람이 내려야 할 남은 결정은 `docs/STATE.md`("Decisions left for a person")에
있습니다.

아직 어떤 출처로도 정해지지 않은 것: 게시판이 `auth_user`를 빼앗겼다는 것을 자기
쪽에서 어떻게 판정할지, 웹방화벽 VM의 감사 로그가 어떻게 Elasticsearch에 닿을지,
블루팀이 어느 인터페이스에서 웹방화벽의 모드를 바꿀지, pfSense에서 Suricata를 inline
모드로 쓸지 legacy 모드로 쓸지, 어느 토큰 없는 순위가 국가 목록을 줄지. 구축 전에 이
클라우드에서 시험해야 할 것은 배치 스펙의 "To test on this cloud before building"에
있습니다.
