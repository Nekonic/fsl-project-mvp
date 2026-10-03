# 아키텍처

레인지가 어떻게 구성되는지, 트래픽과 증거가 그 안에서 어떻게 움직이는지, 그리고
그 뒤에 있는 설계 결정을 다룬다. 점수의 정의는 `CLAUDE.md`에 있고, 미해결 문제와
측정된 특이점은 `docs/STATE.md`에 있다.

"결정"까지는 오늘 실행되는 것을 설명한다: Docker compose 레인지다. 제품은
OpenStack으로 옮겨 가는 중이다. 그중 무엇이 존재하고 무엇이 결정되었는지는 마지막
절 "OpenStack"에 따로 둔다.

이 저장소가 출발점으로 삼은 가설: 레드팀 공격에 ground truth 라벨을 붙일 수 있고,
Suricata와 ModSecurity 경보를 그 라벨에 자동으로 맞출 수 있어서, 오탐과 미탐을
기계적으로 채점할 수 있다. 목표 점수는 그것이 성립한 뒤에 그 위에 얹었다.

## 레인지

여섯 개의 Docker 네트워크 위에 열한 개의 compose 서비스. 대상 시스템은
wargame별로 묶이며, `wargames/` 아래에 폴더 하나씩이고, 그 `compose.yaml`을 최상위
`compose.yaml`이 include 한다: `juice-shop`(Juice Shop과 그 SSRF가 닿는 wiki)과
`board`(board와 그 MySQL). 새 wargame은 새 폴더 하나와 `include:` 줄 하나다.
measure는 그것이 추가하는 서비스를 센다.

| 서비스 | 이미지 | 네트워크 | 호스트 포트 |
|---|---|---|---|
| `fsl-juice-shop` | `bkimminich/juice-shop` | estate | |
| `fsl-board` | `wargames/board/app` (gunicorn 아래 Django, 포트 8000) | estate | |
| `fsl-board-db` | `mysql` | estate | |
| `fsl-wiki` | `nginx`, 별칭 `wiki.internal` | estate | |
| `fsl-waf` | `owasp/modsecurity-crs` (nginx), edge에서 별칭 `shop.com`, 네 개 edge 네트워크 모두에서 `board.com` | edge, edge-br, edge-hk, edge-us, estate | 8080 |
| `fsl-suricata` | `jasonish/suricata` | WAF의 네임스페이스 | |
| `fsl-elasticsearch` | `elasticsearch:8.15.0` | mgmt | 9200 |
| `fsl-filebeat` | `filebeat:8.15.0` | mgmt | |
| `fsl-kali` | `deploy/kali` | edge | |
| `fsl-proxy` | `deploy/proxy` (mitmdump) | 네 개 edge 네트워크 | |
| `fsl-platform` | `platform/` (waitress 아래 Django, nginx 뒤에 있으며, nginx는 `/terminal/`에서 Kali의 터미널도 제공한다) | 여섯 개 모두 | 8000 |

| 네트워크 | 구간 | 서브넷 | 이름 | 출발지 |
|---|---|---|---|---|
| `edge` | `ru` | 5.188.10.0/24 | 인터넷 | 러시아 |
| `edge-br` | `br` | 177.54.144.0/24 | 인터넷 | 브라질 |
| `edge-hk` | `hk` | 103.152.220.0/24 | 인터넷 | 홍콩 |
| `edge-us` | `us` | 73.0.0.0/24 | 인터넷 | 미국 |
| `estate` | `estate` | 172.30.0.0/24 | 애플리케이션 자산 | |
| `mgmt` | `mgmt` | 172.31.0.0/24 | 관리 | |

선언은 하나의 인터넷망 위에 서른 개의 출발지를 나열한다. Cloudflare Radar의 HTTP
요청 점유율 기준 상위 서른 개 국가이며, 각각은 GeoIP가 그 국가로 판정하는 /24
하나와 약 100개의 공격 주소 몫을 갖는다. Docker는 그중 넷을 네트워크 하나씩으로
구축한다. 브리지 하나는 IPv4 서브넷 하나만 담기 때문이다. OpenStack fabric은 서른
개 전부를 하나의 네트워크의 서브넷으로 구축한다. `bin/pick-origins`가 이 표를
재현하고, 수용 테스트가 scoring이 읽는 파이프라인에 대해 모든 서브넷을 검사한다.

망 분리는 Docker 네트워크 소속만으로 이루어진다: 방화벽도, iptables도, ACL도 없다.
`test/test_segmentation.py`가 이것을 라이브 스택에 대해 단언한다(Kali는 `shop.com`에는
닿지만 `juice-shop:3000`에는 닿지 못한다). 고정된 것은 서브넷뿐이다. 컨테이너 주소는
Docker가 할당하며 재생성 시 바뀐다. 뷰는 매 요청마다 새 어댑터를 만들어 그것을 읽는다.
레인지 호스트에서 온 요청을 거부하는 규칙은 그 주소를 30초 동안 캐시하고, substrate에
닿을 수 없으면 레인지를 비어 있는 것으로 취급해 요청을 통과시킨다
(`docs/THREAT-MODEL.md`).

플랫폼, WAF, 프록시는 multi-homed다. 공격자의 트래픽은 WAF에서만 estate로 넘어가지만,
플랫폼은 모든 구간에 서 있으며, 그래서 API가 스스로를 지킨다(`docs/THREAT-MODEL.md`).

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

`deploy/suricata/suricata.yaml`은 인터페이스를 eth0부터 eth4까지 이름 붙이고, Docker가
`compose.yaml`에 설정된 우선순위대로 WAF의 네트워크를 붙여 준다는 데 의존한다. 그
매핑을 검사하는 것은 아무것도 없다.

WAF는 `Host: board.com`을 `board:8000`으로 보내고(`deploy/nginx/board.conf`), 나머지
전부를 자신의 `BACKEND`인 `juice-shop:3000`으로 보낸다. board는 두 번째 wargame이다:
gunicorn 아래 Django 3.2.4(알려진 `order_by` SQL 인젝션 결함 CVE-2021-35042이 있는
미패치 버전)이며, 시작 시 스스로 마이그레이션하고 시드를 넣고, digest로 고정된 MySQL
위에서 돈다. 둘 다 publish되지 않는다. board는 채점되지 않는다: 목표가
없고, 세션은 채점되는 wargame에 대해서만 기준선을 스냅샷하므로, board 세션은 방어만
채점한다.

## 선언과 substrate 이음매

Docker는 MVP의 substrate이고, OpenStack은 목표다. 플랫폼은 레인지가 무엇을 뜻하는지
Docker에 결코 묻지 않는다. 그것은 `platform/range/declaration.yaml`이 알려 준다:
구간마다 id, 표시 이름, 공격 출발지 하나씩; 역할 표(attacker, scorer, gateway, proxy,
sensor, target, wiki, board, board-db); 어느 호스트를 sensor가 지켜보는지; 기본 출발지;
그리고 지도가 선을 긋는 방어 대상 사이트(서울). 구간은 출발지를 선언할 때만, 그리고
오직 그때만 외부다.

**정체성은 선언되고, 할당은 보고된다.** 선언은 서브넷도, 게이트웨이도, 주소도 담지
않는다. 그것들은 substrate에서 온다. Docker와 Neutron이 둘 다 그것들을 나눠 주기
때문이고, 실제와 어긋나는 선언된 서브넷은 아무도 살지 않는 서브넷 기준으로 경보를
분류해 버릴 것이기 때문이다. `compose.yaml`은 네트워크 라벨에 그 정체성을 되풀이한다.
`platform/tests/test_declaration.py`는 두 파일을 서로 맞춰 보지만, 실행 중인 레인지는
결코 검사하지 않는다.

**구간은 표식으로 묶이지만, 호스트는 여전히 이름으로 묶인다.** 각 구간은
`fsl.segment.id`를 Docker 라벨이나 Neutron 태그로 지니며, 어댑터는 표식이 붙은
네트워크만 가져온다. 이름 규칙은 compose 접두사와 오버라이드, Heat 스택 접미사,
그리고 유일하지 않은 Neutron 이름에서 깨졌다. 역할은 선언이 주는 컨테이너 또는 서버
이름이다: Docker는 `docker exec <name>`을 실행하고, OpenStack은 프로젝트의 모든 서버를
나열해 `server["name"]`을 맞추는데, Nova는 이 이름을 유일하게 유지하지 않는다. 이는
`docs/STATE.md`에서 아직 미해결이다.

`platform/range/ports.py`가 그 포트(port)다. 코어 코드와 플랫폼 대부분은 그 네 개의
동사만 본다:

- `describe()`는 형태를 반환한다: 구간, 그 노드와 주소, sensor;
- `segments()`는 sensor에 대해 묻지 않고 누가 어디에 서 있는지를 반환한다;
- `runner(role, segment)`는 상주 호스트(sensor, wiki, proxy, 그리고 플랫폼이 명령
  로그를 읽는 attacker)에서 명령을 실행한다;
- `launcher(segment)`는 한 구간에서 일회성 도구를 실행하고 그 출력을 반환한다.

`range.substrate()`는 `FSL_SUBSTRATE`가 지정하는 어댑터(기본값 `range.docker.Docker`)를,
`FSL_SUBSTRATE_OPTIONS`가 그 이름 아래 보관하는 옵션에 `declared=RANGE`를 더해 만든다.
Docker는 `FSL_PROJECT`(기본값 `fsl`)를 받는다. OpenStack은 `FSL_OPENSTACK_KEYSTONE`,
`_USER`, `_PASSWORD`, `_PROJECT`, `_SSH_USER`, `_SSH_KEY`를 받으며, 각각 없으면 이름을
들어 거부한다. `_SSH_CONFIG`는 선택이며 주어지면 반드시 존재해야 한다. `_REGION`은
기본값이 `RegionOne`, `_INTERFACE`는 `public`이다. `redteam/harness.py`에는 launcher가,
`platform/rules/suricata.py`에는 runner가 건네지므로, 둘 다 `subprocess`를 import하지도
substrate를 지목하지도 않는다.

| | Docker (`range.docker.Docker`) | OpenStack (`range.openstack.connect`) |
|---|---|---|
| 형태 | `docker network ls/inspect`, 라벨 필터 | Keystone v3, `tags-any`를 쓰는 Neutron, Nova |
| sensor | 선언된 각 sensor가 선언된 gateway의 네트워크 네임스페이스를 공유하지 않으면 레인지 기술(describe)을 거부한다 (`docker ps`, `.HostConfig.NetworkMode`) | 이름이 지정된 두 서버가 모두 존재하면 언제든 sensor를 보고한다; 그것이 gateway의 트래픽을 본다는 것을 확인하는 것은 없다 |
| runner | `docker exec` | 인스턴스로 `ssh` |
| launcher | `docker run --rm --network <segment>` | `runner("attacker")`: 선언된 attacker에서 ssh로 도구를 실행한다; 다른 이미지는 거부되는데, Nova는 호스트를 부팅해 그 출력을 반환하고 삭제할 수 없기 때문이다 |
| 테스트 대상 | 라이브 스택 | 공개된 API 레퍼런스와 로컬 sshd로 만든 fake에 대한 유닛 테스트; `fsl-range` 클라우드에서는 플랫폼 VM이 `/api/range/`를 통해 fabric, 이미지, slot을 구축했고, `describe()`가 서른 개 출발지 위의 WAF와 estate 및 mgmt 위의 네 호스트를 되읽었으며, `runner()`가 각 호스트에서 그 mgmt 주소로 ssh를 통해 실행됐다; `launcher()`는 클라우드에서 아직 실행된 적이 없다 |

Compose는 substrate가 무엇이든 Docker 소켓을 플랫폼 안으로 마운트하고, entrypoint는
플랫폼 사용자를 그 그룹에 추가한다. 이는 컨테이너 탈출 경로다. OpenStack 어댑터라면
그것을 제거 가능하게 만들겠지만, 아직 아무것도 그것을 제거하지 않는다. 어댑터가
레인지를 구동할 수 있게 되기 전에 남은 것(이름 해석, `watches`를 확인하는 대신
pfSense 패키지로 도는 sensor를 읽기, 여러 출발지 서브넷과 그 위의 Kali VM 하나를 가진
하나의 인터넷망, 서버 이름 기준 역할, operator의 주소가 라우터를 거쳐 어떻게
나타나는지, SNAT)은 `docs/STATE.md`의 "The substrate seam"에 나열되어 있다.

## 요청이 어디서 오는가

| 경로 | 발신자 | 경보의 출발지 주소 | marker |
|---|---|---|---|
| 터미널, HTTP | Kali, `proxy:8081`을 거쳐 | 프록시, 선택된 출발지에서 | 프록시가 추가 |
| 터미널, raw TCP | Kali 직접 | Kali, `edge`에서만 | 없음 |
| 콘솔 케이스, HTTP | 플랫폼 | 플랫폼, 선택된 출발지에서 | harness가 추가 |
| 콘솔 케이스, 도구 | 일회용 `fsl-kali` 컨테이너 | 그 컨테이너, 선택된 출발지에서 | sqlmap `--headers=` |
| CLI 실행 또는 브라우저, HTTP | 호스트, 포트 8080을 거쳐 | `edge` 브리지 게이트웨이 | harness가 추가; 브라우저에서는 없음 |
| CLI 실행, 도구 | 일회용 `fsl-kali` 컨테이너, `launcher(--origin 또는 선언된 기본값)`에서 | 그 컨테이너 | sqlmap `--headers=` |

프록시는 `mitmdump` 스크립트다. `/label/active`에서 `X-FSL-Case`를 설정하고,
`/label/origin`이 주소를 지정하면 원래 `Host`를 유지한 채 요청을 그리로 전달한다.
플랫폼은 두 파일을 모두 `docker exec`로 쓴다. TLS 가로채기가 없으므로, 프록시는 강제
지점이 아니라 환경 변수일 뿐이다: `curl --noproxy '*'`는 그것을 건너뛴다.

터미널은 operator가 입력하는 것도 기록한다. Kali의 셸은 각 명령을 현재
`/label/active` marker와 함께 `/var/log/fsl/commands.log`에 덧붙인다. 플랫폼은
`runner("attacker")`를 통해 그것을 읽어 `GET /api/sessions/<id>/commands/`에서 제공한다.

콘솔 HTTP 케이스는 출발지가 선택되었든 아니든 세션 wargame의 `Host`, 즉 `shop.com`
또는 `board.com`을 싣는다. 출발지를 선택하면 트래픽을 그 출발지 구간에 있는 WAF의
주소로, IP로 겨냥한다. 두 이름 모두 `edge` 네트워크에서 해석되며, 플랫폼은 출발지가
설정되지 않았을 때 그 네트워크를 쓴다. `rotate`는 무작위 선택이 아니라 세션별 라운드
로빈이다.

콘솔 도구 케이스는 출발지의 대상 URL로 겨냥되거나, 출발지가 선택되지 않았으면 선언된
기본 출발지의 `TARGET_URL`(`http://shop.com`)로 겨냥된다. 대상 시스템은 호스트로
공개되지 않으므로, 명령줄 harness도 레인지 내부에서 그것에 닿는다: `redteam/run.py`는
플랫폼에서 실행되며(수용 스위트가 그것을 구동하는 방식), `--target`/`--tool-target`은
기본값이 `http://shop.com`으로, 포트 80의 WAF로 해석된다.

WAF는 CRS를 paranoia 1, anomaly threshold 5, `DetectionOnly`로 돌리고, 모든 Suricata
룰은 `alert`다. 레인지의 그 무엇도 요청을 차단하지 않는다.

wiki는 오직 애플리케이션을 통해, SSRF로만 닿는다: Juice Shop이 `/profile/image/url`로
POST된 `imageUrl`을 가져온다. 스크립트로 된 케이스 중 이것을 하는 것은 없다.

## 경보가 어디로 가는가

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

ModSecurity의 audit 로그는 요청 헤더를 싣고 있으므로, 그 경보는 marker를 직접 싣는다.
Suricata의 alert 이벤트는 요청 헤더를 싣지 않는다. 그 `http` 이벤트만이 싣는다
(`dump-all-headers: request`와 함께; `custom: [X-FSL-Case]`는 효과가 없다). Ingest는
같은 `(flow_id, tx_id)`를 가진 `http` 이벤트의 marker를 그 alert로 복사한다.
`flow_id`만으로 조인하면 keep-alive 연결의 모든 경보가 그 연결의 첫 케이스에
귀속되었다.

각 ingest 호출은:

- 먼저 만료된 룰 억제를 복원한다;
- 세션 시작 1분 전부터 종료(또는 현재) 1분 후까지의 `@timestamp`를 Elasticsearch에
  요청한다. `fsl-geoip` 파이프라인은 `@timestamp`를 이벤트 자체의 시계(Suricata의
  `timestamp`, ModSecurity의 `transaction.time_stamp`)로부터 설정하므로, 이 창은
  Filebeat가 읽은 시점이 아니라 일이 일어난 시점으로 증거를 선택한다;
- 오래된 것부터, 최대 5000개의 hit를 읽는다. 그것을 넘으면 응답이 `truncated`를 싣고
  세션은 `read_of`를 기록하며, 이는 점수에 `score.warning.truncated`를 추가한다;
- Suricata의 `alert` 이벤트는 그대로 두고, ModSecurity의 레코드는 매칭된 룰
  메시지마다 하나의 Detection으로, id `<Elasticsearch _id>:<n>`으로 바꾼다;
- 자신의 이벤트 시각이 창 밖에 떨어지는 경보는 버리고, `stale`로 센다;
- 나중에 발견된 marker를, marker가 없던 저장된 행에 쓴다;
- `src_host`와 `dest_host`를 substrate의 구간으로부터 채우며, substrate에 닿을 수
  없으면 비운다.

Elasticsearch는 저장과 색인 시점의 geoip에 쓰이며, 그래서 Logstash가 없다. 그 쿼리
엔진은 시간 범위 검색 외에는 아무것도 쓰지 않는다: 지도와 상위 N개 표는 SQLite 사본
위에서 Python으로 계산되고, `src_geo.location`은 `geo_point`가 아니라 두 개의 float로
매핑된다. 세계 지도는 남위 60도에서 잘린 Equal Earth 투영이며, `bin/worldmap`이
생성한다.

파이프라인에는 geoip 프로세서가 둘 있다. `src_ip`(Suricata)와
`transaction.client_ip`(ModSecurity)이며, 둘 다 `src_geo`를 쓴다. 저장소는 GeoLite2
데이터베이스를 프로비저닝하지 않는다: compose는 `config/ingest-geoip`에 아무것도
마운트하지 않고 다운로더 옵션도 설정하지 않는다. 라이브 노드에서 다운로더는 한 번도
성공한 적이 없다. 데이터베이스는 손으로 복사해 넣었고 컨테이너가 재생성되면 사라진다.

## 점수는 어떻게 계산되는가

**목표.** 플랫폼은 대상 시스템의 `/api/Challenges/`를 읽어 각 `solved` 플래그를 있는
그대로 받아들인다. 시각은 Juice Shop의 `updatedAt`이며, 세션 시작 5초 전부터 관측
시점 사이에서만 신뢰된다; 그 밖에는 목표를 관측된 시점으로 날짜 매긴다. 신뢰되는
스탬프는 Objective 행에 저장되는 창이 된다: 그 100ms 전부터 그 분해능(소수가 있으면
1ms, 없으면 1s)에 100ms 후를 더한 지점까지. Juice Shop이 나중 요청에서만 검사하는
13개 문제(`stamped_late`)에 대해서는, 창이 100ms가 아니라 2분을 거슬러 올라간다.

플랫폼이 스스로 판정하는 유일한 목표는 `internalRunbookRead`다: wiki 자체의 access
로그에서 비밀 wiki 페이지를 성공적으로 읽은 것. 그 난이도 6에는 기록된 이유가 없다.
수용 테스트 외에는 wiki 로그를 비우는 것이 없으므로, 한 번 SSRF가 성공한 뒤에는 이후
세션이 runbook을 이미 읽은 상태로 시작한다.

세션은 시작할 때 이미 풀려 있는 목표를 스냅샷하고 그것들을 결코 인정하지 않는다.
그때 대상 시스템이나 wiki를 읽을 수 없으면, 세션은 기준선 없이 그래도 생성되고,
스냅샷은 첫 성공적 관측에서 찍힌다: 그 사이에 풀린 것은 무엇이든 결코 인정되지 않는다.
채점되는 wargame만이 스냅샷과 목표를 가진다; board를 관측하면 0 중 0을 반환한다.

닿을 수 없는 대상 시스템은 두 개의 목표 엔드포인트,
`GET /api/wargames/<id>/objectives/`와 `POST /api/sessions/<id>/objectives/`에서만
503이다. 세션 생성, 케이스 발사 또는 기록(`POST .../cases/`는 `objectives: null`로
응답), 세션 종료(응답이 `unobserved`를 싣는다)는 그것을 흡수한다. 기준선이 일단
존재하면 읽을 수 없는 wiki 로그도 503이 아니다: 관측이 `unreadable`을 싣고, 목표
목록은 runbook을 `solved: null`로 보여 준다.

탈취된 목표는 그 실행이 목표의 창과 겹치는 악성 케이스로 귀속된다; 여럿이면 가장 늦게
시작한 것으로. 신뢰되는 스탬프가 없으면 창은 관측 2분 전부터 100ms 후까지다. 목표는
그 케이스가 탐지된 경우에만 탐지된 것으로 세며, 어떤 케이스와도 겹치지 않는 목표는
미탐지로 센다. 귀속은 오직 시간으로만 이루어진다: 케이스의 `takes:` 필드는 레드
콘솔에 표시되지만 scoring이 읽지는 않는다.

점수의 `objectives` 블록에서 `coverage`는 전체 난이도 대비 탐지된 난이도이며, 아무것도
탈취되지 않았으면 `null`이고, `false_positives`는 FP다. `damage`는 미탐지 난이도에
탐지된 난이도의 절반을 더한 것이다; "탐지되지 않은 손실은 두 배로 센다"가 사는 곳이
바로 그 비율이다.

**탐지.** 케이스는 두 전략 중 하나로 경보에 매칭되며, 케이스마다 선언된다:

- `marker`: 경보가 케이스의 `X-FSL-Case` 값을 싣는다;
- `window`: 경보의 출발지 주소가 케이스의 것과 일치하고 그 시각이 케이스의 시작과 끝
  사이, 양쪽으로 2초의 여유를 두고 떨어진다.

한쪽에서 다른 쪽으로 넘어가는 폴백은 없다. marker가 사라진 marker 케이스는 window로
가려지는 것이 아니라 놓침(miss)으로 드러나야 한다. 터미널 케이스는 둘 다 싣는다.
score 엔드포인트의 `?correlation=marker` 또는 `?correlation=window`는 전략을 강제한다;
다른 값은 400이다. 블루 콘솔은 전략마다 한 번씩 물어 둘을 비교한다. 불일치는 방어가
아니라 채점 방법에 대한 발견이다.

각 `per_case` 항목은 `expect`와 `corroborated`를 싣는다. `corroborated`는 `expect`가
대소문자를 무시하고 어떤 매칭된 경보의 시그니처에 나타날 때 true다; 같은 세션에서 정상
케이스에도 매칭된 시그니처는 세지 않는다. 케이스에 `expect`가 없으면 `null`이며,
터미널 케이스는 항상 그러하다: 레드 콘솔은 아무것도 보내지 않는다. 탐지되었으나
corroborated되지 않은 케이스는 `score.warning.wrong_reason`을 추가한다.

케이스의 `expect`는 발사될 때 케이스와 함께 저장되므로, 케이스 파일을 편집해도 끝난
세션을 다시 판정하지 않는다. 마이그레이션 0009 이전에 기록된 행은 저장된 `expect`가
없어 현재 케이스 파일에 대해 판정된다. 경보 심각도와 룰 유형은 쓰이지 않는다.

**게임.** 점수의 `game` 블록은 세션이 종료될 때까지 `{"revealed": false}`다. 그 뒤에는
네 개의 기둥, 그 가중치, 그리고 균형을 싣는다:

- speed (0.25): 악성 케이스마다, 첫 매칭된 경보가 시작 10초 이내에 오면 1, 120초
  이상이면 0, 그 사이는 선형; 평균 냄;
- accuracy (0.30): 재현율 빼기 오탐률, 0으로 하한;
- coverage (0.20): 공격받은 단계 대비 탐지된 악성 케이스가 있는 공격 단계
  (`platform/lifecycle.py`)이며, 아무것도 공격받지 않았으면 0. 이것은 `objectives`
  블록의 `coverage`가 아니다;
- response (0.25): 차단된 악성 케이스의 비율에서 차단된 정상 케이스의 비율을 뺀 값.
  어떤 케이스가 `meta["blocked"]`를 가질 때까지는 `null`이고, 나머지 가중치가
  재정규화된다. 아직 그것을 설정하는 것은 없다.

`attacker`는 탈취된 목표의 난이도이며, 탐지되면 절반으로 줄인다: `damage`와 같은
합이다. `defender`는 기둥들의 가중 평균에 탈취된 난이도를 곱하고, FP마다 1을 뺀 값이다.
`balance`는 `defender - attacker`다. board에서는 아무것도 탈취되지 않으므로, 균형은
마이너스 FP다. 가중치와 체류 시간은 v1 기본값이다
(`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`).

score 엔드포인트는 읽기 전용이며 이력을 보관하지 않는다.

## 결정

- **wargame마다 케이스 파일 하나, 공격과 정상 트래픽을 함께**: Juice Shop용
  `redteam/cases/default.yaml`(공격 10개, 정상 6개)과 board용 `board.yaml`(6개와 3개).
  파일을 분리하면 정상 쪽 절반을 잊기 쉽다. CLI는 `--cases`가 다른 파일을 지정하지
  않는 한 `default.yaml`을 읽고, 항상 Juice Shop 세션을 연다.
- **harness는 재작성된 경로를 보내기를 거부한다.** `requests`는
  `/ftp/../../etc/passwd`를 `/etc/passwd`로 바꾼다; 그것을 보내면 결코 나가지 않은
  공격을 기록하고 harness의 실패를 방어의 실패로 채점하게 된다. 퍼센트 인코딩 차이는
  허용된다.
- **시작하지 못하는 도구는 예외를 던지고; 0이 아닌 값으로 종료하는 도구는 센다.**
  sqlmap은 아무것도 찾지 못하면 0이 아닌 값으로 종료하지만, 그 트래픽은 나갔다.
- **Suricata는 WAF의 네트워크 네임스페이스를 공유한다**, Docker 호스트에 따라 의미가
  달라지는 호스트 네트워킹을 쓰는 대신. WAF의 인터페이스가 모든 요청의 양쪽 구간을
  실어 나른다.
- **아직 compose 레인지에 Kibana는 없다.** 블루 콘솔이 탐지를 나열하고 Elasticsearch가
  여전히 임시(ad-hoc) 쿼리에 답한다. Kibana는 블루팀을 위해 읽기 전용으로 돌아올
  예정이다("OpenStack" 참고).
- **Elasticsearch는 512MB 힙을 가진 단일 노드다** 그래서 전체 스택이 기본 Docker
  메모리 허용치에 들어맞는다.
- **없는 데이터는 0이 아니라 오류다**, 명시된 예외와 함께. 닿을 수 없는 Elasticsearch나
  substrate, 읽을 수 없는 룰 파일, 그리고 위의 목표 엔드포인트는 503으로 답한다. 세션
  생성, 케이스 발사 또는 기록, 종료는 닿을 수 없는 대상 시스템이나 wiki 로그를
  흡수한다(발사는 출발지나 도구를 위해 substrate가 필요하면 여전히 503으로 답한다).
  ingest 내부의 억제 복원과 경보를 구간 및 호스트에 배치하는 것(이는 비어서 돌아온다)은
  닿을 수 없는 substrate를 흡수하므로, 라운드는 그래도 시작하고 멈출 수 있다. 분모가
  0인 비율은 null이 아니라 0.0이다: 정밀도, 재현율, F1, FPR, 그리고 게임의 speed,
  coverage, accuracy. `objectives` 블록의 `coverage`만이 null이다.
- **점수는 자신이 보증할 수 없는 것을 말한다.** 정상 케이스가 없거나(`no_benign`),
  marker 케이스가 있는데 어떤 경보에도 marker가 없거나(`no_marker`), 출발지 주소가 없는
  window 케이스가 있거나(`no_source_ip`), 탐지되었으나 corroborated되지 않은 케이스가
  있거나(`wrong_reason`), Elasticsearch의 hit가 ingest가 읽은 것보다 많으면
  (`truncated`) 경고를 싣는다.
- **콘솔에서 발사된 케이스는 HTTP 연결마다 케이스 하나를 보낸다**, 반면 CLI는 한 실행
  전체 동안 연결 하나를 유지한다. 같은 12개 케이스로 측정했을 때, 둘 다 동일한 점수와
  케이스별 경보 수를 냈다. 수용 테스트는 CLI를 구동하므로, 연결 공유 케이스는 테스트된
  상태로 남는다.

## OpenStack

이 구축은 `docs/STATE.md`에 있는 백로그의 OpenStack 항목을, 그 순서대로 따른다;
1단계부터 7단계까지는 대체로 구축되었고(플랫폼 VM, fabric, 골든 이미지, slot, pfSense
엣지, Kali 공격자, 이벤트 시각 기준 증거, GeoIP의 영속적 보금자리, 그리고 slot의 Stop
재구축), 클라우드에서 그리고 fake에 대해 입증되었다. 남은 것은 좁고 이 절의 끝에
나열되어 있다. 아래 모든 선택의 근거는 `docs/STATE.md`("Decided on 2026-09-30"),
`docs/superpowers/specs/2026-09-30-openstack-range-placement.md`,
`docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`에 있다; 이 절은 형태만
기록한다.

클라우드는 ML2/Open vSwitch로 kolla-ansible 2026.1을 돌리는 하나의 KVM 컴퓨트
노드(8 vCPU, 64 GB)다. 레인지는 프로젝트 `fsl-range`에 살며, member 역할 사용자
`fsl-range`가 구동한다. Horizon은 사용자에게 결코 보이지 않는다.

### 구축됨: 플랫폼 VM

`deploy/openstack/platform.yaml`은 Heat 템플릿이다. 그것은 다음을 만든다:

- 네트워크와 서브넷 `fsl-platform`;
- 외부 네트워크로 가는 라우터, 그리고 floating IP 하나;
- 임의의 주소에 tcp/22, tcp/8000, ICMP를 여는 보안 그룹 하나;
- config drive를 가진 Nova 서버 `fsl-platform`.

그 파라미터와 기본값은 `README.md`에 있다.

cloud-init은 `docker.io`, `docker-compose-v2`, `git`을 설치하고, 4GB의 스왑을 추가하고,
Docker의 MTU를 기본 브리지에 대해(`mtu`) 그리고 모든 새 브리지 네트워크(compose가
포함하는 것도)에 대해(`default-network-opts`) Neutron 네트워크의 값으로 설정하고,
`ref`의 `repository`를 `/opt/fsl`로 클론하고, `ubuntu`를 `docker` 그룹에 추가한다.
systemd 유닛 `fsl-platform.service`가 매 부팅마다
`docker compose -f /opt/fsl/compose.yaml up -d --build`를 실행한다.

그래서 오늘 위의 compose 레인지 전체, 열한 개 서비스 전부가 하나의 Nova VM 안에서
돈다. 8000은 VM 자신의 주소에 publish되고 그 보안 그룹에서 열리므로, 브라우저가
floating IP에서 콘솔에 닿는다; 다른 포트는 VM의 loopback에 머문다.

cloud-init은 `FSL_OPENSTACK_KEYSTONE`, `_USER`, `_PROJECT`(스택 자신의 프로젝트),
`_SSH_USER=ubuntu`, `_SSH_KEY=/data/ssh/id_ed25519`를 모드 0600으로 `/root/openstack.env`에
쓰고, 그 다음 그것을 git이 무시하는 `/opt/fsl/openstack.env`로 옮긴다. 비밀번호는
템플릿에 없다: Nova가 user data를 보관하고 그 메타데이터 서비스가 VM에서 도는 무엇에게든,
레인지의 컨테이너를 포함해, 그것을 제공한다. operator는 VM이 뜬 뒤 ssh로
`FSL_OPENSTACK_PASSWORD`를 덧붙인다(`README.md`). 플랫폼 서비스는 그 파일을
`env_file`(`required: false`, `format: raw`)로 읽으므로, compose는 보간이나 따옴표 제거
없이 그것을 통과시킨다.

VM 위의 플랫폼은 OpenStack 어댑터(cloud-init이 쓴 `FSL_SUBSTRATE`)를 쓰고,
`range/fabric.py`가 계획한 `/api/range/fabric/`를 통해 레인지의 네트워크를 스스로
구축한다: 선언된 출발지마다 서브넷 하나를 가진 `internet` 네트워크 하나(DHCP 끔),
10.30.0.0/24의 `estate`와 게이트웨이 없는 10.31.0.0/24의 `mgmt`, 모든 compose 및 플랫폼
VM 서브넷을 벗어난 것, 그리고 플랫폼이 `/data/ssh/id_ed25519`에 만드는 키로부터의 키페어
`fsl-platform`. `describe()`는 각 출발지를 하나의 인터넷 네트워크에서의 그 서브넷에
CIDR로 묶는다. VM의 라우터는 자신의 서브넷만 붙이므로, 플랫폼은 API를 통해 레인지를 읽고
아직 어떤 레인지 호스트에도 닿지 않는다; 이후 단계가 거기에 호스트를 두고 플랫폼을
`mgmt`에 붙인다.

호스트는 골든 이미지에서 부팅하며, 골든 이미지는 `/api/range/images/`를 통해 구축되고
`range/images.py`가 계획한다. `declaration.yaml`의 `hosts:`는 각 VM에 설정 스크립트와
그것이 필요로 하는 파일을 준다; 플랫폼은 그것들을 빌더의 user data에 담고, 빌더를 자신의
네트워크(라우터가 있는 쪽)에서 부팅하고, 설정이 끝날 때 출력하는 줄을 빌더의 콘솔에서
읽은 뒤, 그것을 멈추고 스냅샷한다. 이미지는 번들의 digest를 실으므로, 편집된 스크립트는
조용히 낡은 이미지가 아니라 다른 번들의 이미지로 드러난다.

fabric은 보안 그룹 두 개도 만든다: 모든 레인지 포트가 합류하고 임의의 IPv4를 들여보내는
`fsl-range`(레인지를 지키는 것은 Neutron이 아니라 WAF다; anti-spoofing은 켜진 채로
둔다), 그리고 아무것도 들여보내지 않는 `fsl-reach`. 플랫폼은 자신의 서버 id(부팅 시
쓰이는 `FSL_OPENSTACK_PLATFORM`)로 찾은 `fsl-reach`의 포트를 통해 자신을 `mgmt`에
붙이므로, 어떤 호스트도 플랫폼으로 연결을 열 수 없는 동안 플랫폼은 모든 호스트로 ssh할
수 있다. runner는 호출자가 구간을 지정하지 않는 한 호스트의 `mgmt` 주소로 닿는다.

slot은 호스트 그 자체이며, `/api/range/slot/`를 통하고 `range/slot.py`가 계획한다. 각
호스트는 선언된 구간마다 포트 하나를 가지며, `<host>.<segment>`로 이름 붙고, 모두
`fsl-range`에 있다. `gateway`를 채우는 호스트는 모든 출발지의 게이트웨이 주소를 하나의
인터넷 포트에 지니며, cloud-init은 첫 번째만 구성하므로 그 user data가 매 부팅마다
나머지를 추가한다. 모든 호스트의 user data는 estate 이름(`juice-shop`, `wiki.internal`,
`board`)을 `/etc/hosts`에 덧붙이며, 이것이 WAF가 업스트림을, Juice Shop이 wiki를 찾는
방식이다.

pfSense CE 엣지(골든 이미지 `fsl-pfsense-edge`: 베이스 + Suricata 8.0.5 + sshd + OPT1
관리 NIC)가 slot에서 부팅한다. `POST /api/range/configure/`는 관리 ssh로
`deploy/pfsense/configure.php`를 재생하여, pfSense가 30개 출발지 게이트웨이 주소를
지니고(하나는 static, 나머지는 IP-alias VIP로), WAN에서 레인지를 `HOME_NET`으로 삼아
Suricata를 돌리고 EVE를 syslog로 보내며, Suricata 패키지의 필터 재로드에서 살아남는
WAN pass 룰 하나를 유지하고, 그 syslog와 WAF의 ModSecurity audit 로그를 지오로케이션된
채로 플랫폼의 Elasticsearch로 보내도록 한다. 하나의 Kali 이미지가 어떤 출발지든 걸친다:
그 단일 인터넷 포트가 국가별 ~100개 주소를 지니고(slot의 `bootcmd`가 그것들을 NIC에
펼친다) `/usr/local/sbin/fsl-origin`이 박스의 나가는 출발지를 국가별로 SNAT하므로, 모든
도구가 선택된 국가로 나간다. 스탬핑 프록시와 ttyd 터미널이 Kali 박스에서 돈다.

증거는 이벤트 시각으로 선택된다: `fsl-geoip` ingest 파이프라인은 `@timestamp`를
Suricata의 `timestamp`와 ModSecurity의 `transaction.time_stamp`(Filebeat의 읽은 시각이
아니라)로부터 설정한다. GeoIP는 영속적 보금자리를 가진다: 관리형 다운로더는 꺼져 있고
Elasticsearch는 `bin/fetch-geoip`가 채우는 bind-mount된 `config/ingest-geoip`에서
`GeoLite2-City.mmdb`를 읽으므로, 컨테이너 재생성에서 살아남는다.
`rebuild_slot()`(`POST /api/range/slot/rebuild/`)은 slot의 Stop 리셋이다: Nova가 상주
slot VM을 각각 그 골든 이미지에서 재구축하며, 각 서버의 id, flavour, 포트, 고정 IP를
유지하므로, 한 세션은 다음 세션에 풀린 플래그도, 편집된 룰도, 심어진 데이터도 남기지
않는다. 재구축은 디스크를 지우므로, VM이 ACTIVE가 되면 `POST /api/range/configure/`가
뒤따라야 한다.


### OpenStack 위의 레인지: 목표 형태

2026-09-30에 사용자가 결정; 아래 형태가 전체 그림이며, 그 대부분이 이제 구축되었다(위
참고).

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

구축되었으나, 다이어그램의 선에는 나타나지 않는 것:

- **출발지**: 공개된, 토큰이 필요 없는 랭킹(Cloudflare Radar의 HTTP 점유율)에서 뽑은
  30개 국가, GeoIP로 배치, 트래픽으로 가중된 ~100개 주소, 각각 최소 하나씩. `internet`
  구간은 출발지마다 서브넷 하나로 평탄화된다.
- **공격자**: 스탬핑 프록시와 터미널이 Kali VM에서 돈다; 그 출발지는 선택된 국가로
  SNAT된다.
- **이미지**: 저장소의 설정 스크립트가 각 VM을 한 번 구축한다; 번들 digest로 태그된 그
  스냅샷이 이미지다.
- **이벤트 시각 기준 증거**와 **GeoIP의 영속적 보금자리**: 완료(위 구축됨 절 참고).
- **slot의 Stop 재구축**: operator 동작으로서는 완료; 그것을 세션 Stop에 배선하는 것과
  준비 상태 게이트는 아직 남아 있다(아래).

구축할 것으로 남은 것:

- **두 개의 블루 화면 창(pane)**, 사용자가 이 백로그에서 빼 둔 것: Kibana(프레임에
  담긴, 읽기 전용 Elasticsearch 역할로)와 pfSense GUI(키오스크 브라우저 VM의 noVNC
  콘솔). 터미널 창은 완료되었다.
- **세션 수명 주기 배선**: Start는 READY slot을 취하고 아무것도 만들지 않는다; Stop은
  재구축을 발사하고, ACTIVE를 기다리고, 엣지와 WAF를 재구성하고, slot이 스스로
  응답하는지 확인한다(풀린 것 없음, 룰과 WAF 모드가 기준선, 시계가 동기화, 카나리아
  경보 하나). 재구축 메커니즘은 존재한다; 트리거와 READY 게이트는 미뤄진 세션 설계다.
- **차단과 board 목표**: 블루팀이 WAF의 모드와 Suricata의 drop 룰을 스스로 전환하고,
  케이스가 차단되었는지는 대상 시스템 쪽에서 `meta["blocked"]`로 읽힌다; board의
  `auth_user`는 board 자신의 쪽에서 판정되는 목표가 된다. 둘 다 결정되었으나, 구축되지는
  않았다.

사람이 결정해야 할 것으로 아직 열려 있는 결정은 `docs/STATE.md`("Decisions left for
a person")에 있다.

아직 어떤 출처로도 확정되지 않은 것: board가 자신의 쪽에서 `auth_user`가 탈취되었는지를
어떻게 판정하는지; WAF VM의 audit 로그가 어떻게 Elasticsearch에 닿는지; 블루팀이 어느
인터페이스에서 WAF의 모드를 전환하는지; pfSense에서 Suricata의 inline 모드인지 legacy
모드인지; 어느 토큰 없는 랭킹이 국가를 공급하는지. 구축 전에 이 클라우드에서 테스트해야
할 것은 placement 스펙의 "To test on this cloud before building"에 있다.
