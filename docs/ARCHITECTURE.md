# 아키텍처

이 문서는 훈련 환경의 구성, 트래픽과 증거의 경로, 설계 이유를 다룹니다. 점수 정의는 `CLAUDE.md`에 있습니다. 미해결 문제와 측정 결과는 `docs/STATE.md`에 있습니다.

점수는 두 가지입니다.

- 주 점수: 레드팀의 공격 성공. 성공 여부는 대상 시스템의 데이터로 판정
- board: 레드팀이 탈취한 계정 해시(loot)를 증거로 제출(`POST /api/sessions/<id>/loot/`). 세션 시작 시점의 계정 해시와 같으면 성공
- corp: 공격으로 DB에 커밋된 변경이 있으면 성공
- 블루팀이 탐지하지 못한 목표는 2배로 계산
- 탐지 결과: 케이스마다 정탐, 미탐, 오탐, 정상 통과 중 하나. 주 점수에 합치지 않고 옆에 따로 보고
- 케이스 하나는 경보가 몇 건 나오든 1건

탐지 결과 채점이 먼저 있었고, 주 점수는 그 뒤에 추가했습니다. 출발점은 가설 하나였습니다. 케이스에 공격·정상 라벨을 붙이고 Suricata와 ModSecurity 경보를 라벨에 자동으로 매칭하면, 정탐과 오탐을 기계적으로 채점할 수 있다는 가설입니다.

훈련 환경은 OpenStack에서만 돌립니다. docker substrate는 2026-10-21에 삭제했습니다(`docs/DECISIONS.md`). Docker는 계속 씁니다.

- 플랫폼 VM: 플랫폼 서비스
- 훈련 환경 호스트: 모든 슬롯의 컨테이너

로컬 개발 환경에서는 유닛 테스트만 돌립니다. OpenStack 구성은 마지막 "OpenStack" 절에 있고, 구축한 부분과 계획 단계인 부분을 나눠 적었습니다(`docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`).

용어:

- **훈련 환경**(`range`): 네트워크, 호스트, 대상 앱 전체
- **세션**: 레드팀과 블루팀이 훈련 환경을 함께 쓰는 훈련 1회
- **워게임**: 대상 앱과 그 목표, 케이스. `board`와 `corp` 두 개
- **케이스**: harness가 보내는 공격 요청이나 정상 요청 묶음. 경보가 몇 건 나오든 판정은 1건
- **마커**: 케이스 요청에 붙는 `X-Request-ID` 값. 경보와 케이스를 이 값으로 매칭
- **대상 시스템 데이터**: 대상 앱이 직접 저장한 데이터. 공격 성공 판정의 기준. board는 계정 정보, corp는 DB binlog
- **substrate**: 훈련 환경을 올리는 기반. `CR_SUBSTRATE`로 고르며 OpenStack만 지원
- **`estate`**: 에지와 WAF가 있는 DMZ
- **`web`**: WAF와 대상 앱만 붙는 망. 에지에서 가는 경로가 없음
- **슬롯**: 훈련 환경 호스트의 docker compose 프로젝트 `sN`. 세션 하나가 슬롯 하나를 씀
- **방어 설정**(`posture`): 세션 시작 시점의 WAF 설정과 IDS 룰 파일. 워게임이 `defense:` 맵에 선언하고 세션은 그중 하나로 시작
- **코치**(`coach`): 레슨 단계가 다루는 화면 요소에 원을 두르고 한 줄 안내를 붙이는 기능
- **격리 경계**: 관심사 하나를 파일 하나에서만 다루는 규칙. 목록은 "격리 경계" 절
- **플랫폼 DB**: 플랫폼의 SQLite DB `/data/db.sqlite3`
- **유닛**(`unit`): 단계 엔진이 실행하는 기초 레슨이나 시나리오. 본문에서는 주로 "레슨"
- **박스**: 역할 하나를 맡는 컨테이너. 예: 공격 박스(Kali)
- **훈련 환경 호스트**: 모든 슬롯의 컨테이너를 돌리는 VM `cr-range`

## 훈련 환경

플랫폼 VM은 컨트롤 플레인 `compose.yaml`(프로젝트 `cr`)을 돌립니다. 이 프로젝트는 항상 하나만 떠 있습니다. 서비스는 플랫폼, Elasticsearch, Kibana, `collector` 4개이고 모두 `mgmt` 네트워크에 붙습니다. `bin/measure`는 이 파일로 서비스 수를 계산합니다.

훈련 환경은 별도 VM인 훈련 환경 호스트 `cr-range`에서 슬롯마다 compose 프로젝트로 띄웁니다("OpenStack" 절).

세션을 열 때(`POST /api/sessions/`) 스택을 새로 띄우지 않습니다. 하는 일:

- 준비된 빈 슬롯 중 첫 번째에 세션 할당
- 센서에 룰 적재, 세션 defense에 맞는 WAF 설정 작성
- baseline 읽기. baseline은 채점 때 비교 기준이 되는 대상 시스템 데이터 스냅숏

세션은 슬롯마다 하나씩 동시에 돕니다. `max_sessions`는 슬롯 수와 같습니다. 그보다 많이 열면 409를 반환합니다. 세션을 닫으면 그 슬롯만 리셋합니다.

닫힌 세션은 플랫폼 DB에 `CR_RETAIN_CLOSED_MINUTES`분 동안 남깁니다. 기본값은 60이고 `compose.yaml`에서 정합니다.

- 기간이 지난 세션은 `platform/api/retention.py`에서 딸린 데이터와 함께 삭제. 플랫폼 시작 시(`cr/wsgi.py`)와 세션을 닫을 때마다 실행
- 탐지 기록과 고객 요청을 트랜잭션당 2,000행씩 지운 뒤 세션을 지움. 세션 여러 개를 정리해도 쓰기 잠금을 오래 잡지 않음
- 플랫폼 DB는 `transaction_mode: IMMEDIATE`(`cr/settings.py`)인 SQLite. 읽고 쓰는 트랜잭션은 시작할 때 쓰기 잠금을 잡음
- 잠금이 걸려 있으면 `database is locked`로 바로 실패하지 않고 busy timeout 30초까지 기다림
- `bin/backup`: `VACUUM INTO`로 플랫폼 DB 스냅숏을 만들고 최근 `--keep`개(기본 1)만 남김. `bin/platform-rebuild`와 `bin/cloud down`은 `cloud.yaml`의 `backups: {keep}` 값을 씀

워게임은 슬롯마다 GHCR 이미지 컨테이너로 돕니다.

- 준비 상태 점검과 baseline 읽기는 board 컨테이너 안에서 실행. `board` 역할 runner(`sudo docker exec sN-board`)를 씀
- `loot.ground_truth`는 컨테이너 안에서 `127.0.0.1`의 `BOARD_API_URL` 포트로 요청. board 포트는 어디에도 publish하지 않음

워게임마다 `wargames/` 아래에 폴더가 있습니다. 슬롯은 그 폴더의 `compose.yaml`을 실행합니다.

- `board`: Django, MySQL. `objective_model: loot_verified`
- `corp`: WordPress, MySQL. `objective_model: effect_observed`

워게임 목록은 `platform/wargames.py`에서 `wargames/<id>/scenario.yaml`을 읽어 만듭니다.

- 필수 필드: `name`, `description`, `image`, `public_url`, `objective_model`, `case_file`
- 선택 필드 `category`, `difficulty`(easy, medium, hard), `minutes`: API 응답에만 있고 콘솔에는 표시하지 않음(2026-11-14)
- 선택 필드 `defense`, `foundations`, `scenarios`: "세션, WAF 설정 조정, 단계 엔진"과 "시나리오" 절 참고
- `image`: 아직 쓰는 곳 없음

이미지:

- 앱 이미지와 훈련 환경 이미지는 CI(`.github/workflows/images.yml`)에서 빌드
- 훈련 환경 이미지: Kali(`deploy/kali/Dockerfile`), WAF(`deploy/waf/Dockerfile`), 에지(`deploy/edge/Dockerfile`)
- 훈련 환경 호스트는 `ghcr.io/nekonic/cr-<name>:<CR_RANGE_IMAGE_TAG>`를 pull. 이 태그는 플랫폼 커밋이 아니라 훈련 환경 이미지 여섯 개의 빌드 컨텍스트(`images.yml`의 `sources`, 없으면 `context`)를 마지막으로 바꾼 커밋이고, 그 커밋 이미지가 GHCR에 없으면 그 뒤 컨텍스트가 같은 커밋 중 GHCR에 다 있는 첫 커밋(`bin/range-image-tag`). 호스트 설치 번들과 슬롯 compose 파일에 들어감. 플랫폼 쪽만 바꾼 커밋으로 플랫폼 VM을 다시 만들면 태그와 번들 digest가 그대로라 훈련 환경 호스트와 슬롯이 남음
- 도구 케이스는 공격 컨테이너에서 실행(`redteam/tools.py`, `TOOL_IMAGE` 기본값 `cr-kali`)

새 워게임 추가 요구 사항:

- `wargames/<id>/`의 `scenario.yaml`, `objectives.yaml`, `compose.yaml`, `redteam/cases/`의 케이스 파일
- `declaration.yaml`: 훈련 환경 호스트의 `wargames:` 목록에 워게임 이름, `cr-waf`의 `names:` 목록에 사이트 이름
- `deploy/range-host/slot.yaml`의 `x-wargames.fronts`: WAF가 프록시하는 서비스별 web 주소 마지막 옥텟
- `deploy/range-host/slot.yaml`의 `x-wargames.limits`: 서비스별 `cap_add`와 자원 제한
- `deploy/range-host/slot.yaml`의 `waf` 서비스 `extra_hosts`에 서비스 이름과 web 주소, `kali` 서비스 `extra_hosts`에 사이트 이름
- `platform/tests/test_containment.py`의 `LEARNER_FACING`과 `CAPABILITIES`에 서비스
- `deploy/waf/board.com.conf`에 `server` 블록

`fronts`와 `limits`는 `rangehost.compose`에서 슬롯을 렌더링할 때 읽습니다.

워게임 `compose.yaml`에는 `container_name`을 쓰지 않습니다. 컨테이너 이름은 슬롯에서 `sN-<service>`로 붙습니다(`s1-board`, `s2-corp-wp`). 호스트 이름은 서비스 이름 그대로입니다. 고정 이름은 컨트롤 플레인의 `cr-platform`, `cr-elasticsearch`, `cr-kibana`, `cr-collector`뿐입니다. 아래 서비스 표도 이 이름을 씁니다.

모든 콘솔 페이지와 `/api/` 엔드포인트는 로그인을 요구합니다(`api/signin.py`의 `SignedInOnly`). 로그인 없이 열리는 것은 로그인 페이지 `/login/`, 회원가입 페이지 `/signup/`, `GET /api/auth/`(현재 사용자, 관리자 여부, CSRF 토큰), `POST /api/auth/login/`, `POST /api/auth/signup/`뿐입니다. 로그인하지 않은 API 요청은 401, 페이지 요청은 로그인 페이지로 갑니다. POST, PUT, DELETE는 `X-CSRFToken` 헤더가 있어야 합니다. 토큰은 쿠키가 아니라 세션에 둡니다(`CSRF_USE_SESSIONS`). 첫 시작 때 `admin` / `123456` 계정을 만듭니다(마이그레이션 0030). 에이전트도 같은 REST로 로그인합니다(`redteam/signin.py`, `CR_ADMIN_USER`, `CR_ADMIN_PASSWORD`).

회원가입(`username`, `password`, `password_confirm`)은 Django `UserCreationForm`과 기본 비밀번호 검사기 넷으로 확인한 뒤 `is_active=False`, 비관리자 계정을 만들고 201 `{"pending": true}`를 돌려줍니다. 거부 사유는 `errors[].code`(Django 오류 코드)로 오고, 화면은 이 코드로 문구를 찾습니다. 승인 전 계정이 맞는 비밀번호로 로그인하면 403 `{"pending": true}`입니다. 비활성 계정은 세션이 있어도 `/auth-check/`에서 401입니다. 관리자(`is_staff`)는 `/users/`(계정 관리, 상단 링크)에서 `GET /api/users/`, `POST /api/users/<id>/approve/`, `POST /api/users/<id>/reject/`(승인 대기 계정만, 삭제), `POST /api/users/<id>/delete/`(승인된 학습자 계정 삭제)를 씁니다. 삭제는 그 학습자의 열린 세션을 세션 종료 경로(`close_session`)로 먼저 닫아 슬롯을 재구축에 돌려준 뒤 계정을 지우고, 지난 세션은 소유자 없이 남습니다. 세션을 닫느라 응답이 몇 초 걸릴 수 있어, 화면은 응답이 올 때까지 그 행을 흐리게 하고 버튼을 "삭제 중…"으로 바꿉니다. 승인·거절도 같은 방식으로 "승인 중…", "거절 중…"을 보이고, 응답이 올 때까지 그 행의 두 버튼을 모두 막습니다. 관리자가 아니면 403, 사용 중인 계정 거절과 관리자 계정·자기 계정 삭제는 409라서 관리자가 자기 계정을 없앨 수 없습니다.

남용 제한은 nginx와 Django에 있습니다.

- nginx(`platform/nginx.conf`)
  - `POST /api/auth/login/` IP당 5r/m(버스트 5), `POST /api/auth/signup/` IP당 1r/m(버스트 3)
  - `/api/` 세션 쿠키당 20r/s(버스트 40), IP당 100r/s(버스트 200)
  - 터미널과 8002 사이트는 세션 쿠키당 동시 연결 10개
  - 넘으면 429
  - 플랫폼 VM 자신(loopback, Docker 게이트웨이 172.31.0.1, `entrypoint.sh`가 `DJANGO_ALLOWED_HOSTS`의 IP로 만드는 `/tmp/nginx-platform-addresses.conf`)은 제외
- 로그인 실패 차단(`api/blocks.py`). 계정이 아니라 시도한 쪽을 막음
  - 관리자(`is_staff`) 계정에 한 시간 안에 3번 틀린 IP는 1시간 동안 로그인 불가
  - 다른 아이디(없는 아이디 포함)에 10번 틀린 IP는 15분 동안 로그인 불가
  - 브라우저 헤더(User-Agent, Accept, Accept-Language, Accept-Encoding, `Sec-CH-UA` 계열)의 해시도 같은 횟수로 셈. 그 지문이 두 IP 이상에서 틀렸으면 지문을 막음
  - 막힌 쪽은 맞는 비밀번호도 429(`blocked_until`, `blocked_by`, `Retry-After`)
  - 차단은 DB의 `SignInBlock`(마이그레이션 0032)에 남음. 관리자가 계정 관리에서 `GET /api/users/blocks/`로 보고 `POST /api/users/blocks/<id>/unblock/`으로 풂
  - 실패 횟수는 기본 로컬 메모리 캐시에 둠. 플랫폼 VM 자신은 세지도 막지도 않음
- 가입 제한(`api/signin.py`). 같은 주소의 가입은 시간당 5개, 승인 대기 계정은 50개까지. 넘으면 503 `{"closed": true}`
- 세션 소유. 학습자 계정은 열린 세션을 하나만 가짐. 두 번째 `POST /api/sessions/`는 409 `{"open_session": <id>}`(`Session.owner`, 마이그레이션 0031). 관리자는 제한이 없어 수락 테스트가 세션 여럿을 엶

학습자는 자기 세션만 보고 움직입니다(`api/accounts.py`의 `OwnSessionsOnly`). URL에 세션이나 탐지 id가 있는 API와 콘솔 페이지(목록, 상세, 점수, 구성도, 종료, 레드·블루 콘솔)는 남의 것이면 404입니다. `session`을 주지 않은 요청은 자기 세션 중 열린 것, 없으면 가장 최근 것에 적용하고, 세션이 하나도 없으면 409입니다. `/api/range/` 쓰기 요청은 관리자만 할 수 있습니다(학습자는 403). 관리자는 모든 세션을 봅니다.

Kibana도 슬롯별로 나뉩니다. 슬롯마다 space `soc-logs-N`이 있고 그 data view는 `logs-N-*`입니다. Elasticsearch와 Kibana에 보안을 켜지 않았으므로 space 자체는 경계가 아닙니다. 경계는 플랫폼의 게이트입니다. nginx는 `/kibana/s/<space>/api/`와 `/internal/` 호출을 원래 URI 그대로 Django `/kibana-gate/`(`api/views.py`의 `kibana_gate`)로 넘기고, `kibana.refusal`이 다음을 모두 만족할 때만 Kibana로 전달합니다(`kibana.forward`).

- space가 학습자가 연 세션의 슬롯 것. 관리자는 아무 space
- Discover가 쓰는 호출 목록에 있음. `bsearch`, `es`·`esql`·`sql`·`eql` 검색, 개발 도구 콘솔, saved object·data view·고급 설정 쓰기, `resolve_index`는 403
- 호출이 지정하는 인덱스가 정확히 그 슬롯 패턴. 검색의 `params.index`, 필드 목록의 `pattern`, 값 추천 경로의 인덱스. 관리자는 아무 인덱스
- 본문과 쿼리 문자열 어디에도 `index`, `_index`, `indices`, `namespace(s)` 키가 없음. terms lookup이나 다른 space 조회를 막음. 예외는 문서 하나를 읽는 검색의 필터 절 `{"term": {"_index": X}}` 하나뿐이고, X가 그 슬롯 패턴이나 그 백킹 인덱스(`.ds-logs-N-…`)일 때만 통과. Document 창의 JSON 탭이 이 검색을 씀

이 문서 검색은 `kibana.shown_as_the_view_shows`가 고쳐서 넘깁니다. `_source`에서 `HIDDEN_FIELDS`를 빼고, `fields`는 data view의 runtime field만 요청합니다. 그래서 JSON 탭에도 표와 같은 필드만 나옵니다.

다른 space를 열면 거부 화면이 한국어로 나옵니다. 학습자가 `/kibana/s/<space>/…` 문서를 열 때 `/auth-check/`가 그 space를 학습자의 열린 세션 space와 비교하고, 아니면 403입니다. nginx는 이 403과 Default space 등 `/kibana/` 아래의 다른 403을 콘솔의 `/kibana-refused/` 화면(`kibana.refused.*` 문구)으로 바꿉니다. 게이트 API도 다른 space 요청에는 `strings.html`의 `kibana.refused.space` 문구를 `message`로 돌려줍니다. 캐시 키의 `$session_asked`에 space가 들어가서 한 space의 허용이 다른 space에 쓰이지 않습니다.

세션 space에서는 `bfetch:disable`로 요청 묶음을 끕니다. 검색 한 번이 요청 한 건이라 게이트가 본문 전체를 봅니다.

훈련 환경을 바꾸는 엔드포인트는 쿼리나 본문으로 `session`을 받습니다. rules, validate, 룰 비활성화, `/api/attacker/`, origin, label, canary가 해당합니다.

- `session`이 없는 쓰기 요청: 가장 최근에 연 세션에 적용. 열린 세션이 없으면 409
- `session`이 없는 읽기 요청: 가장 최근 세션 기준
- 닫힌 세션에 대한 쓰기 요청: 거부
- 비활성화한 룰은 세션별로 저장(마이그레이션 0014). 0028에서 모델 이름 `Suppression`을 `DisabledRule`로, `restored_at`을 `enabled_at`으로 바꿈. 기존 행은 유지

적용 중인 룰 파일은 슬롯의 센서마다 따로 있습니다.

- 세션을 열 때 defense의 룰 파일을 슬롯 센서에 넣음. 룰 파일이 `local.rules`면 넣지 않음("세션, WAF 설정 조정, 단계 엔진" 절)
- 한 슬롯에 넣은 룰은 다른 슬롯에 반영되지 않음(2026-10-13 측정)

| 서비스 | 실행 위치 | 이미지 | 네트워크 | 호스트 포트 |
|---|---|---|---|---|
| `kali` | 훈련 환경 호스트, 슬롯 N | `ghcr.io/nekonic/cr-kali`(`deploy/kali/Dockerfile`). Ubuntu 24.04, 공격 도구, 마커 프록시 | internet | |
| `edge` | 훈련 환경 호스트, 슬롯 N | `ghcr.io/nekonic/cr-edge`(`deploy/edge/Dockerfile`). Alpine, nftables 라우터 | internet, estate | |
| `waf` | 훈련 환경 호스트, 슬롯 N | `ghcr.io/nekonic/cr-waf`(`deploy/waf/Dockerfile`). nginx 1.24, ModSecurity v3, CRS | estate, web | |
| `sensor` | 훈련 환경 호스트, 슬롯 N | digest 고정 `jasonish/suricata`. WAF 뒤 웹 서버 구간 감시(`deploy/suricata/suricata.yaml`) | web(`web`, 주소 없음), 관제망 .11 | |
| `log-server` | 훈련 환경 호스트, 슬롯 N | digest 고정 `rsyslog/rsyslog-minimal`. 514/tcp로 받아 collector 5140/udp로 전달 | 관제망 .10 | |
| `sensor-shipper` | 훈련 환경 호스트, 슬롯 N | 같은 rsyslog 이미지. 센서의 `eve.json`을 읽어 log-server로 보냄 | 센서의 네트워크 네임스페이스 | |
| `waf-shipper` | 훈련 환경 호스트, 슬롯 N | 같은 rsyslog 이미지. WAF audit 로그와 nginx 거부 로그를 읽기 전용으로 읽어 log-server로 보냄 | WAF의 네트워크 네임스페이스 | |
| `board` | 훈련 환경 호스트, 슬롯 N | `ghcr.io/nekonic/cr-board`(`wargames/board/app`). gunicorn, Django, 포트 8000 | web, `board-default` | |
| `board-db` | 훈련 환경 호스트, 슬롯 N | digest 고정 `mysql` | `board-default` | |
| `corp-wp` | 훈련 환경 호스트, 슬롯 N | `ghcr.io/nekonic/cr-corp`(`wargames/corp/app`). WordPress 6.6.2, 취약 버전 고정 플러그인 3개, `Host` 헤더 `corp.com` | web, `corp-default` | |
| `corp-db` | 훈련 환경 호스트, 슬롯 N | `ghcr.io/nekonic/cr-corp-db`(`wargames/corp/db`). MySQL 8.4, binlog `ROW` | `corp-default` | |
| `cr-elasticsearch` | 플랫폼 VM | `elasticsearch:8.15.0` | mgmt | 9200 |
| `cr-collector` | 플랫폼 VM | `filebeat:8.15.0`. syslog 입력만 사용. 시작 전에 entrypoint가 `fields.yml`에서 `ecs`, `beat`, `cloud`, `docker`, `host`, `kubernetes`, `process`, `log` 그룹만 남겨 `data/fields-lean.yml`을 만듦 | mgmt | 5140/udp |
| `cr-kibana` | 플랫폼 VM | `kibana:8.15.0`. `/kibana/` 경로로 제공 | mgmt | 5601 |
| `cr-platform` | 플랫폼 VM | `platform/`. waitress, Django, 앞단 nginx. nginx가 `/kibana/`의 Kibana, `/vm-terminal/kali/`와 `/vm-terminal/waf/`의 VM 터미널도 제공 | mgmt | 8000, 8002 |

포트 바인딩:

- 8000, 8002: `CR_PUBLISH`. 기본값 127.0.0.1
- 5140/udp: `CR_SYSLOG_PUBLISH`. 기본값 127.0.0.1
- 9200, 5601: loopback에만 바인딩
- 훈련 환경 호스트: publish하는 포트 없음

슬롯 컨테이너 이름은 `sN-<service>`(`s1-kali`)입니다. 슬롯 네트워크는 관제망 `sN_mgmt`만 빼고 모두 internal입니다.

| 구간 | 서브넷 | 이름 |
|---|---|---|
| `internet` | 출발지마다 /24, 총 30개(`declaration.yaml`). 예: `ru` 5.188.10.0/24, `us` 73.0.0.0/24. 슬롯 브리지 `sN-inet` | 인터넷 |
| `estate` | `cloud.yaml`의 `estate` /16에서 슬롯 N에 준 /24(10.30.N.0/24). 슬롯 브리지 `sN-estate` | DMZ |
| `web` | 같은 /16에서 estate보다 128 위의 /24(10.30.N+128.0/24). 슬롯 브리지 `sN-web`. 그래서 슬롯 번호는 1~127 | 웹 서버 구간 |
| 슬롯 `mgmt` | 172.29.N.0/24. 슬롯 브리지 `sN-mgmt`. 센서, shipper, log-server | 관제망 |
| `mgmt` | `cloud.yaml`의 `mgmt` CIDR. fabric이 만드는 Neutron 네트워크는 이것뿐 | 관리망 |

출발지 국가는 서브넷의 GeoIP 정보로 정해집니다. 그래서 출발지 서브넷은 `declaration.yaml`에 고정합니다.

`mgmt`는 모든 슬롯이 공유합니다. 플랫폼은 이 망으로 훈련 환경 호스트에 접속합니다. 슬롯 log-server의 syslog는 훈련 환경 호스트의 NAT를 거쳐 이 망으로 collector에 갑니다(`docs/DECISIONS.md`, 2026-10-10, 2026-11-15).

플랫폼 VM의 compose 네트워크 이름도 `mgmt`입니다. 별개의 Docker 브리지이며, `cloud.yaml`의 CIDR과 겹치면 안 됩니다.

인터넷 구간의 출발지는 30개입니다.

- Cloudflare Radar 기준 HTTP 요청 점유율 상위 30개국
- 출발지마다 GeoIP상 그 나라로 나오는 /24 하나. 공격 주소 약 100개를 나눠 받음
- 30개 모두 슬롯의 `internet` 브리지 하나에 올라감
- `deploy/range-host/slot.sh`에서 Kali에 출발지별 주소를 붙임(`nsenter`로 `ip -batch` 실행). Kali는 라우터 바깥의 인터넷 역할
- 주소를 바꾼 뒤 그 컨테이너의 `/etc/hosts`(Docker의 `HostsPath`)에서 Docker가 처음 준 주소를 새 주소로 바꿈. Kali는 기본 출발지 주소(5.188.10.10), 에지는 `wan`의 공인 IP. 센서의 `web` 주소는 지움. 그래서 `hostname -i`가 구성도와 `ip addr`의 주소를 말함
- 라우터(에지) `wan`의 공인 IP는 121.134.88.42/29 하나(`rangehost.ROUTER_WAN`). KT 회선(KORNET, 121.128.0.0/11)에서 기업 회선에 주는 크기의 블록이고, Kali의 30개 /24 어느 것과도 겹치지 않음
- 공인 IP와 출발지 대역이 서로 다른 블록이라 같은 브리지 위에서 onlink 경로로 닿음. 라우터는 `default via 5.188.10.10 dev wan onlink`(Kali가 라우터 바깥의 인터넷 역할), Kali는 `default via 121.134.88.42 dev eth0 onlink src 5.188.10.10`(`rangehost.edge_addresses`, `kali_addresses`). `kali_addresses`는 기본 출발지 대역(ru)의 주소부터 추가해서 Kali `ip addr`의 첫 주소(primary)가 구성도와 `hostname -i`에 나오는 5.188.10.10과 같음. 경로에도 `src`를 박아 둠. 다른 주소가 출발지로 잡히면 출발지 SNAT가 nmap SYN 스캔의 raw 패킷 출발지를 바꿔 nmap이 응답을 못 알아봄
- 라우터는 공인 IP의 80번 포트를 WAF의 estate 주소로 포트포워딩(DNAT, `rangehost.edge_rules`가 만드는 `edge.nft`의 `table ip nat`). 출발지는 바꾸지 않음(SNAT 없음)
- 같은 `edge.nft`의 `table ip inbound` forward 체인: `wan`에서 들어오는 패킷은 이미 맺어진 연결의 응답(`ct state established,related`)과 포트포워딩된 연결(`ct status dnat`)만 통과하고 나머지는 drop. Kali에서 WAF의 사설 주소(10.30.N.247)로는 연결이 안 됨(nmap에서 filtered). `lan`에서 나가는 연결은 막지 않음
- 브리지 서브넷 172.30.N.0/24는 쓰지 않음
- 출발지 표는 `bin/pick-origins`로 다시 만듦. acceptance 테스트에서 모든 서브넷을 점수 파이프라인과 대조

망 분리는 슬롯의 docker 네트워크로 합니다. 훈련 환경 호스트 바깥은 fabric의 보안 그룹으로 막습니다.

- 관제망을 뺀 슬롯 네트워크는 모두 `internal`, `gateway_mode_ipv4: isolated`. 훈련 환경 호스트는 그 브리지에 주소가 없고 외부 경로나 NAT도 없음
- 관제망 `sN_mgmt`만 예외. 호스트가 게이트웨이 .254를 갖고 NAT로 collector에 보냄. 허용하는 길은 log-server→collector 5140/udp 하나("훈련 환경 슬롯" 절의 관제망 필터)
- Kali는 `internet`에만 붙음. 아는 이름은 `board.com`, `corp.com`뿐이고 둘 다 라우터의 공인 IP를 가리킴
- 에지는 공인 IP 80번 포트를 WAF로 DNAT하고, 출발지는 NAT 없이 그대로 넘김. `web`으로 가는 경로는 없음
- board와 corp-wp는 `web`과 자기 DB 망에만 붙음. Kali에서 대상 시스템으로 가는 길은 WAF뿐
- DB는 자기 워게임의 `<wargame>-default` 네트워크에만 붙음

격리 검사:

- `test/test_board_exfil.py`: `board.com`을 거쳐 board에 접근
- `test/test_range_isolation.py`: Kali, WAF, board, 센서, log-server 각각에서 격리 확인. 훈련 환경 호스트 sshd, 플랫폼, 인터넷, 메타데이터 서비스, 다른 슬롯에 닿지 않아야 함
- 같은 테스트에서 Kali는 WAF 80번에 닿고, WAF가 프록시하는 board와 corp-wp 주소에는 닿지 않음. `board`, `corp-wp`, `board-db`, `corp-db`는 Kali에서 이름이 풀리지 않음. SYN 스캔은 동작
- 같은 테스트에서 Kali로 훈련 환경 호스트, 플랫폼, 훈련 환경 호스트의 `mgmt` 망을 포트 스캔
- `platform/tests/test_containment.py`: 렌더링한 슬롯 compose 파일이 격리 조건을 어기면 `bin/verify` 실패("OpenStack" 절)
- `test/test_concurrent_sessions.py`: 동시에 연 두 세션이 서로 보이지 않는지 확인

주소와 출처 검사:

- 출발지 서브넷과 슬롯 내부 주소는 선언, `cloud.yaml`, `deploy/range-host/slot.yaml`에서 정함
- 훈련 환경 호스트의 `mgmt` 주소는 Neutron이 할당. 그래서 요청마다 어댑터를 새로 만들어 주소를 읽음
- 훈련 환경 내부 주소에서 온 요청은 거부. 대상은 슬롯이 보고하는 모든 주소(채점 서버 제외, 훈련 환경 호스트 `mgmt` 주소 포함)
- 이 주소 목록은 30초간 캐시. substrate에 연결하지 못하면 훈련 환경이 비었다고 보고 요청을 허용(`docs/THREAT-MODEL.md`)

플랫폼과 훈련 환경 사이는 `mgmt`로만 통합니다.

- 공격자 트래픽은 에지를 거쳐 `estate`의 WAF로 들어오고, WAF를 거쳐 `web`의 대상 시스템으로 감
- 플랫폼은 `cr-reach` 포트로 훈련 환경 호스트에 접속
- 훈련 환경 호스트에서 플랫폼으로 여는 연결은 NTP와 5140/udp syslog뿐("OpenStack" 절). 그래도 API에서 호출자를 직접 검사(`docs/THREAT-MODEL.md`)

전체 경로 그림은 끝부분 "OpenStack 훈련 환경: 목표 구조"에 있습니다.

`deploy/suricata/suricata.yaml`은 센서 설정입니다.

- `rangehost.sensor_config`에서 af-packet 항목을 주소 없는 감시 인터페이스마다 하나씩 넣음. 지금은 `web`(`sN-web`) 하나
- EVE 출력에 `xff`를 켬: `mode: extra-data`, `deployment: reverse`, `header: X-Forwarded-For`. http 기록의 `xff`에 클라이언트 주소가 남고, `src_ip`는 WAF 그대로
- 인터페이스마다 스레드 1개, `cluster_flow`. BPF 필터 없음
- `HOME_NET`은 10/8, 172.16/12, 192.168/16. 센서가 보는 출발지는 WAF의 web 주소라 HOME_NET 안임. `EXTERNAL_NET`은 `any`라 WAF가 board로 보내는 요청도 룰에 걸림. `HTTP_PORTS`는 80, 8000

WAF는 `board.com`을 `board:8000`으로, `corp.com`을 `corp-wp:80`으로 넘깁니다. 설정은 `deploy/waf/board.com.conf`이고 corp는 두 번째 vhost입니다.

- `board`와 `corp-wp`의 web 주소 .59, .60은 WAF의 `extra_hosts`에 있음
- `/internal/`은 board에 없는 경로로 보냄. board의 404가 그대로 나감

첫 번째 워게임은 board입니다.

- gunicorn, Django 3.2.4, digest 고정 MySQL
- 패치 안 된 Django라 `order_by` SQL Injection(CVE-2021-35042)이 있음
- 시작할 때 마이그레이션과 시드 입력
- board와 DB 모두 포트를 publish하지 않음. 훈련 환경 밖에서는 접근 불가
- 탈취 목표는 계정 정보. 세션을 열 때 `/internal/auth-users`로 `auth_user`의 사용자 이름과 비밀번호 해시를 읽어 세션 스냅숏으로 저장
- 이 경로는 `board` 역할 runner로 board 컨테이너 안에서 `127.0.0.1`로 읽음. WAF는 이 경로를 넘기지 않음
- 슬롯 브리지를 지나지 않는 읽기라 WAF와 IDS에 보이지 않음

두 번째 워게임은 corp입니다. WordPress 6.6.2(`corp-wp`)에 플러그인 세 개를 패치 전 버전으로 고정했습니다.

- Ultimate Member 2.6.6(CVE-2023-3460): 가입 요청에 `wp_capabilities`를 넣어 administrator 권한 획득
- WP GDPR Compliance 1.4.2(CVE-2018-19207): 인증 없이 옵션을 바꿔 관리자 가입 허용
- Easy Post Submission 2.3.0(CVE-2026-4431): 인증 없이 글 덮어쓰기

세 취약점 모두 기본 OWASP CRS로는 탐지되지 않습니다. `corp-db`는 `--binlog-format=ROW`로 띄운 MySQL 8.4입니다. WordPress에는 계측 코드를 넣지 않았습니다. corp 목표는 공격으로 DB에 커밋된 변경으로 판정합니다("점수 계산 방식" 절).

## 선언과 substrate 경계

substrate 경계는 플랫폼과 OpenStack 어댑터 사이 인터페이스입니다. `platform/range/ports.py`에 정의돼 있습니다. 지원 substrate는 OpenStack뿐입니다(2026-10-20 결정, 2026-10-11 결정 대체).

훈련 환경 구성은 OpenStack에 묻지 않고 `platform/range/declaration.yaml`에서 읽습니다. 들어 있는 항목:

- 구간별 id, 표시 이름, 공격 출발지
- 역할 표: attacker, scorer(플랫폼), gateway, proxy, sensor, edge, wargames, board, board-db, corp, corp-db, log-server
- 호스트별 구간(`hosts:`): 훈련 환경 호스트 `cr-range`, 슬롯의 `cr-waf`, `cr-edge`, `cr-kali`. 설치 스크립트(`setup`)와 `wargames`를 가진 호스트는 `cr-range`뿐
- 역할별 슬롯 compose 서비스(`compose:`)
- 센서별 감시 대상 호스트(`watches:`)
- 기본 출발지
- 방어 대상 사이트(서울)

출발지가 선언된 구간만 외부 구간입니다.

선언에는 `estate`, `mgmt`, 호스트 주소를 적지 않습니다. 플랫폼은 이 값을 substrate에서 읽습니다.

- estate /16, `mgmt`: `cloud.yaml`
- 슬롯 내부 주소: 슬롯 템플릿
- 훈련 환경 호스트의 `mgmt` 주소: Neutron

선언의 서브넷이 클라우드가 할당한 서브넷과 다르면, 경보가 호스트 없는 서브넷에 묶입니다.

구간은 태그로 찾습니다.

- Neutron 네트워크는 `cr.segment.id=mgmt` 태그가 붙은 `mgmt` 하나뿐. 어댑터는 태그가 붙은 네트워크만 가져옴
- 슬롯의 `internet` 구간은 선언된 출발지마다 하나(30개). 서브넷과 Kali 주소(서브넷의 10번째 호스트부터 `addresses`개, `rangehost.origin_addresses`)는 선언에서, 게이트웨이는 라우터 공인 IP(`rangehost.router_address`)에서 정함
- 슬롯의 `estate` 구간의 노드와 주소는 렌더링한 슬롯 compose 파일에서 읽음(`platform/range/openstack.py`의 `_read`)
- 이름 매칭은 쓰지 않음. Heat 스택 접미사와 Neutron 이름이 겹쳐 깨졌음
- 역할은 선언에서 지정한 호스트를 가리킴. 메타데이터 `cr_host`가 `cr-range`인 서버가 훈련 환경 호스트(`slot.host_of`). 나머지 호스트는 슬롯 컨테이너
- `compose:`로 서비스를 지정한 역할은 그 슬롯 컨테이너 안에서 실행(훈련 환경 호스트에서 `sudo docker exec sN-<service>`). `wargames` 역할은 훈련 환경 호스트에서 실행

코어 코드와 플랫폼 대부분은 이 인터페이스의 메서드 네 개만 씁니다.

- `describe()`: 구간, 구간별 노드와 주소, 센서 구조를 반환
- `segments()`: 센서 검사 없이 호스트별 구간을 반환
- `runner(role, segment)`: 떠 있는 컨테이너나 훈련 환경 호스트에서 명령 실행. 대상 역할은 센서, 프록시, 공격 박스(명령 로그 읽기), WAF(`gateway`, CRS 설정 읽기와 적용), board, corp-db
- `launcher(segment)`: 구간에서 일회성 도구를 실행하고 출력을 반환

`range.substrate()`는 `CR_SUBSTRATE`의 어댑터(기본값 `range.openstack.connect`)를 생성합니다. 옵션은 `CR_SUBSTRATE_OPTIONS`에서 그 이름 아래 값에 `declared=RANGE`를 더해 넘깁니다.

- 접속 값: `CR_OPENSTACK_KEYSTONE`, `_USER`, `_PASSWORD_FILE`(비밀번호 파일, 기본 `/run/secrets/openstack_password`), `_PROJECT`, `_SSH_USER`, `_SSH_KEY`, `_REGION`, `_INTERFACE`, `_DOMAIN`. 하나라도 없으면 빠진 이름을 밝히고 거부
- 구성 값: `_BASE_IMAGE`, `_FLAVOR`(훈련 환경 호스트 flavor), `_AVAILABILITY_ZONE`, `_SUBNETS`, `_BUILD_NETWORK`(훈련 환경 호스트가 이미지를 받는 플랫폼 네트워크), `_PLATFORM`. 실제로 쓰는 시점에 없으면 이름을 밝히고 거부
- `CR_RANGE_IMAGE_TAG`: 훈련 환경 호스트 이미지 태그. 부팅 때 `/opt/cr/.env`에 기록
- 코드 기본값은 `_SLOTS`(비면 1)와 `_MTU`(비면 렌더링 때 1500)뿐. 나머지 값은 Heat 스택을 거쳐 `deploy/openstack/cloud.yaml`에서 옴. 이 파일은 `platform/range/cloud.py`에서 읽고 검증
- `redteam/harness.py`는 launcher를, `platform/rules/suricata.py`는 runner를 받음. 둘 다 `subprocess`를 import하지 않고 substrate 이름도 모름

어댑터의 호출별 동작:

- 구조: `mgmt`는 Keystone v3, Neutron(`tags-any`), Nova, 이미지는 Glance에서 읽음. 슬롯의 `internet`은 선언에서, `estate`와 그 노드, 주소는 렌더링한 슬롯 compose 파일(`rangehost.compose`)에서 읽음
- 센서: 훈련 환경 호스트가 떠 있으면 센서를 보고. 센서가 gateway 트래픽을 실제로 보는지는 확인하지 않음
- runner: 훈련 환경 호스트의 `mgmt` 주소로 `ssh`. 호스트마다 연결 공유(`ControlMaster auto`, `ControlPersist 60`). `compose:` 역할은 슬롯 컨테이너 안에서 실행(`sudo docker exec sN-<service>`, `range/rangehost.exec_in`)
- address: 훈련 환경 역할마다 훈련 환경 호스트의 `mgmt` 주소
- launcher: `runner("attacker")`로 슬롯의 Kali 컨테이너에서 도구 실행. 넘겨받은 구간은 거부 메시지에만 씀. 출발 국가는 `set-origin` SNAT로 정해짐. 다른 이미지는 거부
- 테스트: 공개 API 레퍼런스와 로컬 sshd로 만든 fake를 대상으로 한 유닛 테스트

플랫폼 컨테이너에는 Docker 소켓이 없고 이미지에 Docker 클라이언트도 없습니다. 플랫폼 VM의 주소는 OpenStack API(Neutron 서브넷, Nova 서버 주소)에서 읽습니다(`describe`). 슬롯 컨테이너는 훈련 환경 호스트에 ssh로 접속해 `sudo docker`로 다룹니다. 2026-11-15까지는 플랫폼 VM의 NIC를 읽으려고 소켓을 마운트했고 GNS3도 같은 소켓으로 표시용 노드를 띄웠습니다.

## 네트워크 구성도

학습자용 구성도는 세션 슬롯에서 지금 돌고 있는 컨테이너와 Docker 네트워크를 읽어 그립니다. 구성도 파일은 없습니다. 2026-11-15에 GNS3 표시용 구성도를 대체했습니다(`docs/DECISIONS.md`, "The learner map is the slot's live wiring").

**읽기.** `rangehost.WIRING`은 훈련 환경 호스트에서 `sudo sh -c`로 도는 셸 스크립트입니다. `OpenStack.wiring()`이 ssh 한 번으로 실행합니다.

- 슬롯 compose 프로젝트의 Docker 네트워크마다 `@network <이름> <id> <브리지 이름> <서브넷>`. 브리지 이름은 `com.docker.network.bridge.name` 옵션(`sN-inet`, `sN-estate`, `sN-web`)이고, 없으면 Docker 규칙대로 `br-<id 12자>`
- 실행 중인 컨테이너마다 `@container <서비스> <NetworkMode>`, `@args`(`docker inspect`의 `Args`), 붙은 망마다 `@leg <망> <MAC>`. 호스트 네트워크가 아니면 `nsenter -t <pid> -n`으로 읽은 `ip -o link show`와 `ip -o -4 addr show` 출력. 다른 컨테이너의 네트워크 네임스페이스를 쓰는 컨테이너(shipper)는 따로 읽지 않음
- rsyslog 설정은 읽지 않음. 로그 경로, 포트, 수집기 주소는 구성도에 나오지 않음

`interfaces.wiring`이 이 출력을 `Wiring`으로 풉니다.

- 인터페이스의 망: 먼저 `@leg`의 MAC이 같은 Docker 네트워크(`Wiring.legs`), MAC으로 못 찾으면 그 인터페이스 주소 중 하나를 품은 Docker 네트워크. 주소 없는 센서의 `web` 인터페이스는 MAC으로만 찾음. 망은 인터페이스 단위라서 kali `eth0`에 함께 붙은 출발지 주소(5.188.10.10, 고객 주소)도 인터넷 구간에 속함
- 센서: `Args`에 `--af-packet`(`rangehost.SNIFFS`)이 있는 컨테이너. 감시하는 망은 주소 없는 인터페이스가 붙은 망(`--af-packet=<이름>`이면 그 브리지나 인터페이스). 센서의 인터페이스도 돌려주되 `sensor=True`로 표시(`Wiring.interfaces`). 선의 주소를 고르는 `link_heads`만 센서 인터페이스를 뺌
- `OpenStack.wiring()`은 서비스 이름을 선언된 호스트 이름(`cr-kali`, `board`)으로 바꿔 붙임. 훈련 환경 호스트가 답하지 않으면 `RangeUnavailable`

**그리기.** `topology.graph(learner, wiring)`가 콘솔이 그릴 그래프를 만듭니다.

- 영역(`zones`): 슬롯 워게임의 장비가 하나라도 붙은 Docker 네트워크. 캡션은 망으로 먼저 정하고, 그 밖의 망은 붙은 장비로 정함(`topology.captions`). `internet` 망이나 kali가 있으면 `internet`, `estate` 망이나 라우터가 있으면 `dmz`, `mgmt` 망이나 log-server가 있으면 `mgmt`(관제망), `-default`로 끝나는 망이나 워게임 DB가 있고 WAF가 없는 망은 `database`, 나머지는 `web`. 컨테이너 하나가 멈춰도 그 망의 캡션은 그대로임. 한국어는 `strings.html`의 `topology.zone.*`. 캡션은 영역 이름과 대역이고, 인터넷 구간에는 대역을 붙이지 않음. DB존에는 `owner`로 워게임 이름이 붙어 "board DB존", "corp DB존"으로 나옴
- 스위치: 영역마다 하나(`switch:<망>`). 리눅스 브리지는 L2 스위치. 이름은 붙이지 않음
- 장비: 브리지에 인터페이스가 있는 컨테이너. 이름은 `topology.learner`의 학습자 이름(`kali`, `router`, `waf`, `board.com`, `board-db`, `corp.com`, `corp-db`, `log-server`). 세션을 열면 슬롯에는 그 세션 워게임의 서버와 DB만 돌고 있으므로 그 둘만 그려짐. `kind`로 아이콘을 고름
- 선(`link`): 장비가 그 브리지에 가진 인터페이스마다 하나. `address`는 그 인터페이스에서 고른 주소(`link_heads`. kali와 라우터 wan은 기본 출발지 대역의 주소, 나머지는 망의 주소)
- 센서(`sensor:<서비스>`): 감시하는 브리지마다 그 스위치에 `mirror` 선, 관제망 스위치에 `link` 선(관제망 주소). 지금은 웹 서버 구간 스위치 하나
- 로그 서버(`log-server`): 관제망의 장비. 로그가 가는 선은 따로 그리지 않음
- 그리지 않는 것: 훈련 환경 호스트, 플랫폼 VM, 수집기, 고객, 관리망, 컨테이너·브리지의 실제 이름. 실행 중이 아닌 컨테이너는 읽히지 않으므로 그리지 않음. 상태는 표시하지 않음
- 단계의 답과 보기(`topology.addresses`, `topology.hosts`)에서는 다른 워게임의 장비를 여전히 뺌
- 주소 표(`topology.addresses`, `GET .../lesson/addresses/`): 행마다 `host`, `kind`, `zone`, `address`, `network`, `more`(같은 인터페이스의 다른 주소 수), DB존이면 `owner`. 고객은 따로 행을 두지 않고 kali 행의 `more`에 들어감. 센서는 관제망 주소로 `kind: sensor` 행. 주소를 묻는 단계에서 다른 장비의 주소를 답하면 그 주소가 누구 것인지 알려 줌(`views._whose_address`). IDS 주소도 여기에 포함

**API.** `GET /api/sessions/<id>/topology/`의 `map`이 이 그래프입니다. 훈련 환경 호스트를 읽지 못하면 `map`은 빈 그래프와 `detail`입니다. 같은 응답의 `segments`, `sensors`, `unplaced`는 그대로입니다. 읽은 인터페이스는 세션이 끝날 때까지 보관해 주소를 묻는 단계의 답으로 씁니다(`views._map_found`, `_found_kept`).

**페이지.** 블루팀 콘솔의 구성도 창은 `/map/<세션 id>/`(`console/templates/console/map.html`, `X-Frame-Options: SAMEORIGIN`)를 iframe으로 띄웁니다.

- 창을 열 때 `/api/sessions/<id>/topology/`를 한 번 읽음. 주기적으로 다시 읽지 않음
- cytoscape.js 3.34.4(`platform/console/static/map/cytoscape.min.js`, SHA-256 `081591ab735b2b6a3b31a3c60f8f3a3e2fee8c92939e0c7820ad1208571b6cd8`, MIT)로 그림. nginx가 `/static/map/`을 `/app/console/static/map/`에서 직접 줌
- 배치: 위치는 `topology.laid_out`이 정해 그래프에 실음(장비 `x`, `y`, 글자 쪽 `label`, 영역 `box`와 캡션 위치 `shift`, 꺾이는 선의 `route`, 시작점 `start`, 끝점 `end`). 주소 글자도 `kind: address` 노드로 실음. 페이지는 그 위치를 그대로 씀(`preset`). 붙은 장비만으로 정하므로 같은 배선이면 어느 슬롯에서 몇 번 읽어도 같은 그림
  - 영역 상자 하나가 서브넷 하나. 장비는 주소가 있는 서브넷의 상자 안에 둠. 선은 다른 상자로 나갈 수 있음
  - 영역마다 상자. 캡션은 상자 위 가운데이고, 그 자리를 선이 지나면 선과 `CAPTION_CLEAR`만큼 떨어진 가장 가까운 자리로 비켜 놓음. 비킬 자리가 없으면 다른 상자와 겹치지 않는 쪽으로 상자를 넓힘(`_captioned`). 캡션 폭은 `_caption_width`로 어림함
  - 윗줄은 왼쪽부터 Kali와 인터넷 구간 스위치, 라우터, DMZ 스위치와 WAF. 라우터는 두 상자 사이에 따로 놓고, 라우터의 주소 두 개는 어느 상자에도 넣지 않으며 상자와 `CLEAR`만큼 띄움. WAF는 DMZ 상자 안
  - 가운뎃줄은 웹 서버 구간과 그 오른쪽의 DB존. 웹 서버 구간 스위치 오른쪽에 board.com, board.com에서 DB 스위치까지는 한 줄 직선이고 주소는 board.com 오른쪽. board-db는 DB 스위치 아래에 매달고 주소는 board-db 위, 선 오른쪽
  - 관제망은 아랫줄 왼쪽, 웹 서버 구간 아래. IDS는 주소(172.29.N.11)가 관제망에만 있으므로 관제망 상자 안, 오른쪽 끝에 두고 웹 서버 구간 스위치 바로 아래에 맞춤. 관제망 스위치는 IDS 왼쪽, 로그 서버는 그 왼쪽
  - IDS의 관리 인터페이스 선은 왼쪽으로 관제망 스위치에 들어가고, 172.29.N.11은 선 위가 아니라 IDS 옆, 그 선이 나가는 왼쪽에 씀. 미러 선(`mirror`)은 IDS 위로 곧게 올라가 관제망 상자를 나와 웹 서버 구간 스위치 아래로 들어가며 주소가 없음. 두 선이 IDS에서 직각으로 갈리므로 IDS가 두 스위치 사이에 끼인 장비로 읽히지 않음. 미러링 점선이나 문구는 없음
  - WAF에서 아래로 가는 선(관제망, 웹 서버 구간)은 WAF 아래에서 좌우로 나뉘어 내려와 DMZ 상자와 가운뎃줄 사이를 층을 달리해 지나 각 스위치 위로 들어감. 더 왼쪽으로 가는 선이 위층이라 서로 교차하지 않음(`_dropping`)
  - 서버가 둘 이상이면(슬롯이 두 워게임을 다 돌릴 때) 서버를 위아래로 벌리고, 아래 서버의 선은 스위치 오른쪽으로 들어감. DB존은 서버마다 오른쪽에 두고 DB를 스위치 오른쪽에 놓음
  - 주소: 인터페이스마다 전체 주소를 장비 옆, 선이 나가는 쪽에 씀(`_sided`). 주소 글자는 그 장비가 속한 영역에 두고, 영역 상자는 그 글자를 `LABEL_PAD`만큼 띄워 품음(`_boxed`). 선 위에는 주소를 쓰지 않음
  - 같은 인터페이스에 주소가 더 있으면 "외 N개"를 붙임(`topology.extra_addresses`가 선과 주소 노드의 `more`로 실음, `map.html`의 `named`). kali `eth0`의 출발지·고객 주소가 그 예
  - 장비 이름은 아이콘 아래. `strings.html`의 `topology.name.<이름>`이 있으면 그것을 씀. 라우터와 로그 서버는 한국어 역할 이름, Kali, WAF, IDS는 고유 이름 그대로
  - 포트, 범례는 그리지 않음
- 아이콘: GNS3 affinity 글리프를 정사각형 틀에 넣은 `host-*.svg`와 스위치 아이콘. 아이콘은 `console/static/map/symbols/`에 있음. 출처와 라이선스는 한 단계 위 `console/static/map/`의 `SOURCES`, Kali 드래곤 로고의 상표 고지는 `symbols/host-kali.txt`
- 읽기 전용: `autoungrabify`, `autounselectify`, 상자 선택 끔. 이동과 확대·축소만 됨
- 아이콘은 cytoscape.js를 읽기 전에 요청하고, 다 받거나 5초가 지난 뒤에 그림. 콘솔은 `drawn`을 받을 때 창을 보여 주므로 아이콘 없는 첫 그림이 보이지 않음. 토폴로지 API도 cytoscape.js를 읽기 전에 요청함
- 콘솔과의 메시지: 첫 맞춤 뒤 `{map: "drawn"}`, 이후 `{fit}`를 받아 맞출 때마다 `{map: "fitted"}`. `{locate: {node|zone|label}}`에는 사각형, 영역 사각형(`zones`), 글자 사각형(`text`)으로 답함. 같은 origin의 메시지만 받음

## 격리 경계

격리 경계는 관심사 하나를 파일 하나에서만 다루는 규칙입니다. 예를 들어 Elasticsearch와 통신하는 파일은 `platform/ingest/elastic.py`뿐입니다. 아래 표는 관심사별 담당 파일과, 이 규칙을 벗어나는 현재 코드(알려진 예외)입니다.

| 관심사 | 담당 파일 | 알려진 예외 |
|---|---|---|
| Elasticsearch | `platform/ingest/elastic.py` | `platform/register_pipeline.py`: 시작 시 `geoip` ingest 파이프라인 PUT |
| Kibana HTTP API, saved object, Discover 링크 | `platform/kibana.py` | `platform/nginx.conf`: Kibana API 경로를 앎. Default space, space 안의 space, space 접두어 없는 API 경로, `%`·역슬래시·점 세그먼트가 든 경로, `?namespaces=` 거부. space 안의 API 호출은 `/kibana-gate/`로 넘김(호출 목록과 인덱스 검사는 `kibana.py`). `GET /kibana/s/<space>/api/spaces/space`에는 SOC space만 담은 응답을 직접 반환. `console/templates/console/blue.html`: Kibana의 localStorage 키를 미리 채움 |
| 슬롯 배선 읽기 | `platform/range/rangehost.py`(`WIRING`) | 없음. 출력 해석은 `platform/range/interfaces.py`, 학습자 이름과 그래프는 `platform/topology.py` |
| CRS 설정과 nginx reload | `platform/rules/crs.py` | `declaration.yaml`의 `cr-waf` 호스트: `crs.py`에 넘길 예외 파일(`rules`), reload 명령(`reload`), nginx pid 파일(`pid`) 지정. `entrypoint.sh`: `vm-terminal.sh cr-waf`로 슬롯 WAF 컨테이너 쉘 제공(훈련 환경 호스트로 ssh 후 `sudo docker exec -it sN-waf bash -l`). `range/rangehost.forwarding`: 슬롯의 WAF shipper와 log-server 설정 작성(audit 로그와 nginx 거부 로그 경로). `deploy/range-host/slot.yaml`: `rangehost.LOGS` 경로로 WAF audit 로그 파일과 거부 로그 파일 마운트. audit 로그는 둘 다 `deploy/waf/modsecurity.conf`의 `SecAuditLog`와 맞는지 `platform/tests/test_range_host.py`의 `test_the_waf_s_audit_log_is_forwarded_from_where_modsecurity_writes_it`로 확인. F6의 WAF 창 단계 명령(`grep -n ruleRemove {waf_rules}`, `{sudo}nano {waf_rules} && {waf_reload}`): `wargames.lesson`에서 선언된 예외 파일과 reload 명령(`settings.CR_WAF`)으로 채움. 플랫폼은 터미널을 조작하지 않음 |
| Suricata 프로세스 | `platform/rules/suricata.py` | `declaration.yaml`의 센서 호스트(`sensor`는 `cr-range`): `suricata.py`에 넘길 룰 파일과 reload 명령 지정. `platform/range/rangehost.py`: 센서 설정(`deploy/suricata/suricata.yaml`)과 compose 서비스 렌더링. `deploy/range-host/slot.sh`: 슬롯과 함께 센서 시작·정지, 초기화 때 센서 로그 파일 다시 열기, 에지 라우터 설정. 이후 기본 룰 적용은 `suricata.py` |
| 공격 박스 | `platform/attacker.py` | `platform/operator_log.py`: `/var/log/commands.log` 읽기. 터미널 연결 설정에 `cr-kali` 지정, `entrypoint.sh`에서 `vm-terminal.sh cr-kali` 실행. 웹사이트 창(`platform/api/site.py`)은 예외가 아님. `redteam/tools.py`의 `TOOL_IMAGE`(`CR_TOOL_IMAGE`, 기본 `cr-kali`): 도구 케이스를 공격 박스에서 실행. 박스 접근은 `attacker.py`(`customer_origins`, `unbound_source`, 명령을 담은 `as_customer`)와 substrate의 `opened`(훈련 환경 호스트 ssh 스트림으로 슬롯 Kali 컨테이너 접속)로만 함. 발사한 sqlmap 케이스가 쓰는 박스 안 출력 디렉터리(`SQLMAP_RUNS`, `/tmp/sqlmap-runs/<케이스 id>`)도 `attacker.py`가 정해 `harness.fire`에 넘김(`views._fire`, `redteam/run.py`) |
| 대상 시스템 데이터 | `platform/api/loot.py`(board), `platform/api/effect.py`(corp) | 없음. `loot.py`는 `board` 역할 runner로 board 컨테이너 안 `127.0.0.1`에 HTTP 요청. `effect.py`는 `corp-db`에 `docker exec`하는 runner로 접근 |

`platform/tests/test_isolation_seams.py`가 `platform/` 코드를 관심사별 문자열로 훑어, 담당 파일과 알려진 예외 밖에서 그 관심사를 다루는 파일이 있으면 실패합니다. 담당 파일이 없어지면 담당 파일이 그 관심사를 아는지는 검사하지 않습니다. 다른 파일이 그 관심사를 알면 여전히 실패합니다. 슬롯 배선 읽기 행은 이 테스트에 없어서 검사하지 않습니다.

## 파일

본문에서 따로 다루지 않는 주요 파일입니다.

| 파일 | 하는 일 |
|---|---|
| `deploy/filebeat/filebeat.yml` | collector의 Filebeat 설정. `event.module`과 슬롯(`cr_slot`) 태그를 붙여 `logs-<slot>-sensors` 인덱스에 기록. 인덱스 템플릿은 `fields-lean.yml`로 만들어 기존 템플릿을 덮어씀(`setup.template.overwrite`), refresh 1초. 이미 있는 data stream은 rollover 전까지 예전 매핑을 유지 |
| `deploy/elastic/ingest-pipeline.json` | `geoip` ingest 파이프라인. 이벤트 시각을 `@timestamp`로 옮기고, `src_ip`와 `transaction.client_ip`의 GeoIP를 `src_geo`에 붙이고, `cr_slot` 삭제 |
| `deploy/proxy/stamp.py` | `X-Request-ID`를 붙이는 mitmdump 스크립트. Kali 이미지에 `/usr/local/lib/web-proxy.py`로 설치 |
| `deploy/kali/operator-log.sh` | Kali 쉘 훅. 입력한 명령을 마커와 함께 `/var/log/commands.log`에 추가 |
| `deploy/kali/Dockerfile`, `deploy/waf/Dockerfile`, `deploy/edge/Dockerfile` | 슬롯의 Kali, WAF, 에지 이미지. `.github/workflows/images.yml`로 빌드, GHCR에서 pull |
| `deploy/edge/edge.nft` | 에지 이미지의 기본 nftables 룰. loopback 외 input은 drop. 슬롯을 올릴 때 `slot.sh`가 `rangehost.edge_rules`로 만든 슬롯별 `edge.nft`(포트포워딩과 `wan` forward 필터)를 더 넣음 |
| `deploy/range-host/setup.sh` | 훈련 환경 호스트 설치 스크립트. Nova user data로 한 번 실행. 패키지, Docker `daemon.json`, sshd와 inotify 한도, 이미지, pristine 볼륨 |
| `deploy/range-host/slot.yaml` | 슬롯 compose 프로젝트 템플릿. `range/rangehost.py`에서 값을 채워 워게임별 `compose.yaml`과 합침 |
| `deploy/range-host/slot.sh` | 훈련 환경 호스트에서 슬롯 N의 `up`, `reset`, `down`, `play` 실행 |
| `platform/range/rangehost.py` | 훈련 환경 호스트 설치 번들과 user data, 슬롯별 compose 파일과 부속 파일, 실행 명령 생성 |
| `platform/tests/test_containment.py` | 렌더링한 슬롯 compose 파일이 격리 조건을 어기면 `bin/verify` 실패 |
| `test/test_range_isolation.py` | Kali, WAF, board, 센서, log-server에서 격리를 확인하는 실환경 검사 |
| `platform/scoring/` | `correlate.py`: 마커나 시간 창으로 탐지를 케이스에 매칭. `metrics.py`: 케이스별 탐지 결과 집계. `types.py`: 케이스·탐지 레코드와 매칭 방식 이름 |
| `platform/scoreboard.py` | 목표 점수. 탐지를 시도에 귀속, `corroborated` 판정, 탈취된 목표 집계 |
| `platform/game.py` | 게임 점수(speed, accuracy, coverage, response). 점수의 `game` 블록 |
| `platform/disable.py` | Suricata 룰을 정해진 시각까지 주석 처리해 비활성화하고 다시 활성화(`# cr-disabled`) |
| `platform/api/models.py` | Django 모델: `Session`, `Case`, `CustomerRequest`, `Detection`, `Objective`, `RuleSet`, `DisabledRule`, `SignInBlock` |
| `platform/api/maps.py` | 워게임의 고객 출발지 비중을 더해 `topology.learner`를 부름. 구성도와 주소 단계는 이것을 씀 |
| `platform/cr/urls.py` | 전체 엔드포인트 라우트 표 |
| `platform/api/refusals.py` | 예외를 HTTP 상태 코드로 변환(`/api/` 아래 404는 JSON). 변경 요청(POST 등)의 동일 출처 검사, JSON이 아닌 본문은 415 |
| `platform/api/reachability.py` | 슬롯이 보고하는 모든 주소(채점 서버 제외)에서 온 요청을 거부하는 미들웨어. 주소 목록은 30초 캐시하고, 만료되면 슬롯들의 구성을 동시에 읽음 |
| `platform/api/signin.py` | 로그인, 로그아웃, 회원가입, nginx `auth_request`가 묻는 세션 확인 |
| `platform/api/blocks.py` | 로그인 실패를 IP와 브라우저 헤더 지문별로 세고 차단 |
| `platform/api/accounts.py` | 계정 관리 API(계정 목록, 승인, 거절. 관리자 전용). 학습자가 남의 세션과 훈련 환경 변경에 닿지 못하게 막는 미들웨어 |
| `platform/range/declared.py` | `declaration.yaml`을 읽어 `Declaration`으로 변환 |
| `platform/range/openstack.py` | OpenStack 어댑터(`connect`): Keystone, Neutron, Nova, Glance, ssh |
| `deploy/openstack/network.yaml` | 실제 클라우드의 주소 배치를 사람이 읽도록 적은 그림. 설정 값은 `cloud.yaml` |
| `deploy/range-host/proto/` | 훈련 환경 호스트 구조를 정하기 전 시제품 스크립트와 측정 결과. 제품 경로에서 쓰지 않음 |
| `bin/prune` | 플랫폼 DB의 세션 정리(`--keep`, `--ids`, `--newest`, `--apply`). `bin/verify`가 acceptance에서 만든 세션을 지움 |
| `bin/verify` | ratchet 검사(게이트 대상 수치가 커지는 변경 거부, `CLAUDE.md`)와 변경이 닿는 테스트 실행(`--changed`, `--fast`. 테스트 선택은 `bin/select-tests`) |

## 요청의 출처

| 경로 | 발신자 | 경보에 찍히는 출발지 주소 | 마커 |
|---|---|---|---|
| 터미널, HTTP | Kali. 자체 프록시(8081) 경유 | Kali, 선택한 출발지 | 프록시가 추가 |
| 터미널, raw TCP | Kali에서 직접. 프록시 미경유 | Kali, 선택한 출발지 | 없음 |
| API로 실행한 케이스, HTTP | 공격 박스. 플랫폼이 launcher로 박스에서 `curl` 실행(`views._fire`: 시나리오 일정, 레슨 시드, `POST /api/sessions/<id>/attacks/`) | 공격 박스, 선택한 출발지 | harness가 추가 |
| API로 실행한 케이스, 도구 | 공격 박스. 플랫폼이 launcher로 박스에서 도구 실행 | 공격 박스, 선택한 출발지 | sqlmap `--headers=` |
| CLI 실행, HTTP | 공격 박스. `redteam/run.py`가 `launcher(<선언된 기본 출발지>)`로 박스에서 `curl` 실행 | 공격 박스, 기본 출발지 | harness가 추가 |
| CLI 실행, 도구 | 공격 박스. `launcher(<선언된 기본 출발지>)` | 공격 박스, 기본 출발지 | sqlmap `--headers=` |
| 사이트 브라우저 | 학습자 브라우저. 플랫폼 nginx 8002번 포트와 `platform/api/site.py` 경유 | 고객 주소. Kali에 있는 주소이고, `cr-users` 계정으로 보내 에지를 통과 | 세션 비밀값 `browse-<hex>`(`site.py`에서 설정). API에는 `browse`로 표시 |
| 고객 | `deploy/traffic/users.py`. Kali 컨테이너의 `cr-users`로 실행 | 기본이 아닌 출발지에 있는 페르소나 자신의 주소. 공격자 주소는 쓰지 않음 | 요청마다 새 UUID |

프록시는 `mitmdump` 스크립트입니다.

- Kali 컨테이너의 메인 프로세스. 이미지 `CMD`에서 `/usr/local/lib/web-proxy.py`로 8081 포트(모든 인터페이스)에 `mitmdump`를 띄움. 셸의 `http_proxy`는 `127.0.0.1:8081`(`/etc/profile.d/proxy.sh`)
- `X-Request-ID`가 없는 요청에 `/var/lib/session/active`의 값을 그 헤더로 넣음
- 플랫폼은 `runner("proxy")`로 훈련 환경 호스트에 ssh한 뒤 Kali에 `docker exec`해서 `active` 파일을 씀
- `/var/lib/session/active`와 `/var/log/commands.log`는 root 전용 0600. 컨테이너 안에서는 플랫폼 명령도 학습자 셸도 root로 돎
- TLS는 가로채지 않음
- 프록시는 환경 변수로 지정만 하고 강제하지 않음. `curl --noproxy '*'`로 보내면 프록시를 거치지 않음
- 로그인 셸의 `http_proxy`와 `HTTP_PROXY`는 `/etc/profile.d/proxy.sh`에서 지정

터미널에 입력한 명령도 기록합니다.

- Kali 쉘이 명령마다 현재 `/var/lib/session/active` 마커를 붙여 `/var/log/commands.log`에 추가
- 플랫폼은 `runner("attacker")`로 이 파일을 읽어 `GET /api/sessions/<id>/commands/`로 제공

Kali 창은 세션 API의 `kali_terminal` URL(`GET /api/sessions/<id>/`)을 프레임으로 띄웁니다. 레드팀 콘솔의 창이고, 레슨·시나리오 세션에서는 블루팀 콘솔의 창입니다.

- URL은 `/vm-terminal/kali/?arg=<세션 id>`. 플랫폼 안의 ttyd가 `platform/vm-terminal.sh`를 실행
- ttyd는 `-t disableLeaveAlert=true`로 띄움. 다음 레슨으로 넘어가거나 세션을 끝낼 때 브라우저의 "사이트에서 나가시겠습니까?" 창이 뜨지 않음
- 스크립트는 훈련 환경 호스트의 mgmt 주소로 ssh 접속해 세션 슬롯의 `sudo docker exec -it ... sN-kali bash -l`을 실행

`entrypoint.sh`는 두 ttyd를 `TERMINAL_KEEP=1`로 띄웁니다. 그러면 스크립트가 자신을 `tmux new-session -A -s <host>-<세션 id>` 안에서 다시 실행합니다.

- `platform/tmux.conf`: 상태 줄 없음, 대체 화면 없음. 출력은 xterm 스크롤백에 남음
- 세션 이름의 호스트에는 `cr-`를 붙이지 않음(예: `kali-12`)
- 새로고침해도 같은 셸에 다시 붙음. 실행 중인 sqlmap과 그 출력이 그대로 남음
- 세션 id가 숫자일 때만 tmux 세션 이름으로 씀
- tmux가 없으면 일반 셸로 열림. 새로고침하면 셸이 유지되지 않음

`vm-terminal.sh`는 호스트 키를 별칭 `cr-<server id>-<launch time>`(`OpenStack.host_key_alias`)으로 확인합니다. 플랫폼 runner와 같은 별칭이고, `StrictHostKeyChecking=accept-new`를 씁니다.

- 훈련 환경 호스트를 재부팅하거나 새로 만들면 별칭이 바뀜. "REMOTE HOST IDENTIFICATION HAS CHANGED" 경고 없이 새 키가 등록됨
- 이미 아는 별칭인데 키가 바뀌었으면 접속 거부

터미널별 로그인:

- Kali: `/root`에서 root 로그인 셸. 호스트 이름 `kali`, Kali 기본 두 줄 프롬프트(`deploy/kali/bashrc`), motd 없음
- Kali는 `no-new-privileges`라 `sudo`로 얻을 권한이 없음. 그래서 처음부터 root 셸
- Kali 로그인 때 `/etc/profile.d/proxy.sh`(`http_proxy`)와 명령 훅(`/usr/local/lib/shell-hook.sh`의 `__log_command`, `/etc/bash.bashrc`에서 로드)이 적용됨
- WAF: 슬롯 WAF 컨테이너의 root 로그인 셸. 호스트 이름 `waf`. 그래서 레슨의 reload 명령에 `sudo`가 없음(`nginx -t && nginx -s reload`)
- 두 셸 모두 `TERM=xterm-256color`, `TZ=KST-9`(POSIX 시간대 문자열). WAF 이미지에 tzdata가 없어 `TZ=Asia/Seoul`은 "Asia"라는 이름의 UTC로 읽힘
- WAF의 nginx와 ModSecurity는 UTC. 수집 파이프라인이 audit 로그의 시간대 없는 `time_stamp`를 UTC로 읽음
- syslog 송신자 이름은 슬롯 log-server의 rsyslog 템플릿에서 슬롯마다 고정(`cr-waf`, `cr-waf-2`). Filebeat는 송신자 이름으로 슬롯을 구분

블루팀 콘솔의 WAF 창은 세션 API의 `waf_terminal` URL(`GET /api/sessions/<id>/`)을 프레임으로 띄웁니다. URL은 `/vm-terminal/waf/?arg=<세션 id>`이고, 같은 `auth_request /signed-in`로 보호합니다. 이 검사는 플랫폼의 `/auth-check/`에 원래 URL(`X-Original-URI`)을 넘겨 묻습니다. 로그인하지 않았으면 401이고 로그인 페이지로 보냅니다. 훈련 환경 호스트 주소에서 온 요청은 거부합니다. 학습자 계정은 자기 세션만 열 수 있습니다. 터미널 URL의 `arg`나 `/site/<세션 id>/`가 남의 세션이면 403이고, 터미널에 `arg`가 없거나 둘 이상이어도 403입니다. 관리자는 모든 세션을 엽니다. nginx는 이 답(204, 401)을 5초 동안 캐시합니다. 키는 세션 쿠키, 클라이언트 주소, URL이 가리키는 세션(`$session_asked`)이라서, 캐시된 허용이 다른 주소나 다른 세션에 쓰이지 않습니다.

블루팀 콘솔의 웹사이트 창은 콘솔 안의 브라우저입니다.

- 뒤로, 앞으로, 새로 고침. 불러오는 동안 중지 버튼과 얇은 진행 막대
- 주소창: 전체 URL(`http://board.com/<경로>`). http에는 Chrome처럼 "주의 요함" 표시. URL이나 경로를 입력하고 Enter로 이동
- iframe 안의 페이지
- "개발자 도구" 토글. F12로도 열림. 페이지 안에 포커스가 있어도 동작

다른 호스트 주소를 입력하면 Chrome의 "사이트에 연결할 수 없음" 페이지가 나옵니다.

board.com과 corp.com은 훈련 환경 안에서만 응답합니다. 학습자 브라우저는 플랫폼의 8002번 포트 nginx를 거쳐 접근합니다.

- 경로: `/site/<세션>/<호스트>/<경로>`
- nginx는 터미널과 같은 `auth_request /signed-in`를 거친 뒤 플랫폼의 기록기로 넘김. 로그인하지 않았으면 8000의 로그인 페이지로 보냄
- 쿠키는 포트가 아니라 호스트 단위라 8000의 세션 쿠키가 8002에도 실림. nginx는 검사에만 쓰고 기록기로 넘기기 전에 `Cookie`를 지움. 대상의 `Set-Cookie`는 브라우저로 보내지 않음
- 세션 쿠키는 HttpOnly이고 CSRF 토큰은 쿠키가 아니라 세션에 있음. 그래서 8002에서 도는 XSS 스크립트는 둘 다 읽지 못함. 플랫폼은 CORS 헤더를 보내지 않아 8002의 스크립트가 8000 응답을 읽지 못하고, 쓰기 요청은 CSRF 토큰과 같은 출처(`Origin`)가 없으면 403
- 기록기 경로는 `/site-proxy/<세션>/<호스트>/`(`platform/api/site.py`). 원래 경로와 쿼리는 `X-Site-Uri`에 담김

기록기는 훈련 환경의 고객 주소에서(아래 참고) Chrome처럼 요청을 보냅니다.

- `Host: <호스트>`, `Connection: keep-alive`, `Accept-Encoding: gzip, deflate`를 보냄. 응답은 압축을 풀어 넘김
- 세션이 그 호스트에서 받은 쿠키를 경로에 맞게 붙임. 페이지 이동이면 `Upgrade-Insecure-Requests: 1`도 붙임
- 헤더 순서는 Chrome을 따름(`CHROME_ORDER`). 리다이렉트는 따라가지 않음
- 브라우저 헤더 중 `Accept`, `Accept-Language`, `Content-Type`, `User-Agent`, `Referer`, `Origin`만 넘김
- `Referer`, `Origin`은 `http://<호스트>/`에 접속한 브라우저가 보낼 값으로 고쳐 씀(`as_browsed`)
- `X-Forwarded-For`는 넘기지 않음. 고객 주소는 WAF에서 붙고, 대상 시스템에 학습자의 LAN 주소가 남지 않음

기록기의 응답:

- 없는 세션: 404, 닫힌 세션: 409. WAF를 호출하지 않음
- 요청 대상으로 쓸 수 없는 경로: 400
- Kali 안의 중계가 10초 안에 연결하지 못하거나 20초 안에 응답이 없으면 502("board.com did not answer")
- 페이지는 도착하는 대로 브라우저로 스트리밍

이 경로의 기타 사항:

- 8000의 nginx는 `/site-proxy/`에 404
- 플랫폼의 POST 동일 출처 검사에서 이 경로는 제외. 대상 시스템의 폼도 제출됨
- 모든 페이지는 WAF를 거침. 차단되면 WAF 자체의 403 페이지가 보이고 Kibana에 기록이 남음
- 경로와 쿼리는 브라우저가 보낸 그대로 전달(`$request_uri`에 대한 `map`)

접두사를 벗어나는 값은 nginx에서 고쳐 씁니다.

- `Location` 헤더(`proxy_redirect`)
- HTML의 `href="/`, `src="/`, `action="/`, `http://<호스트>/`, `http://<호스트>"`(`sub_filter`. 이를 위해 업스트림에 비압축 응답 요청). WordPress가 이스케이프한 `http:\/\/corp.com\/`도 포함

쿠키:

- nginx에서 브라우저의 `Cookie`와 응답의 `Set-Cookie`를 지움. 플랫폼 쿠키는 대상 시스템에 가지 않고, 대상 시스템 쿠키는 브라우저에 닿지 않음
- 대상 시스템 쿠키는 기록기가 세션·호스트별로 보관(`site._keep_cookies`). `Secure` 쿠키는 버림. 만료된 쿠키는 지움. 세션을 닫으면 모두 지움
- 보관한 쿠키는 이후 요청에 `Cookie`로 붙음. 이 창에서 로그인하면 세션 동안 유지
- 대상 페이지의 스크립트는 막지 못함. 스크립트는 플랫폼 호스트 8002번 포트에서 돌고, 쿠키는 포트로 분리되지 않음. `document.cookie`로 8000의 콘솔이 보낼 쿠키를 설정할 수 있음
- 지금 콘솔은 쿠키를 쓰지 않음. 나중에 쿠키를 추가하면 이 경로로 접근 가능해짐

nginx는 `</body>` 앞에 스크립트를 넣습니다.

- `location.pathname + search`를 부모 창에 post. 페이지 안 링크를 누르면 주소창과 방문 기록이 함께 바뀜
- F12를 부모 창으로 넘김
- 코치의 `{locate: <selector>}`에 그 요소의 사각형으로 답함. 스크롤하거나 크기가 바뀌어도 다시 답함. 출처가 콘솔 호스트인 부모 창 메시지에만 답함
- 따로 요청을 보내지 않음
- 링크를 `http://<site>/...` 주소로 보이게 바꿈. 마크업에는 프록시 경로가 남지만, 마우스를 올리면 고객이 볼 주소가 나옴. 일반 클릭은 프록시 경로로 보냄

웹사이트 창의 출구(`site.found_egress`, 세션마다 한 번 결정)는 고객 주소입니다. 창의 요청은 고객과 같은 경로를 지나고, 센서에도 고객 요청과 똑같이 보입니다. 출발지는 `attacker.customer_origins` 중 시나리오 고객 트래픽 비중이 가장 큰 곳입니다(`customers.declared`. 없으면 id 순 첫 번째).

- 기록기가 Kali로 ssh stdio 스트림을 열고(`OpenStack.opened`) 그 안에서 `attacker.as_customer` 실행
- `as_customer`는 Python 브리지. Kali의 출발지 SNAT가 적용되지 않는 `cr-users` 계정으로 돎. 그 슬롯에서 고객 트래픽을 돌린 적이 없으면 계정과 예외 규칙을 만듦
- 브리지는 그 출발지의 첫 주소에 바인드해 라우터의 공인 IP 80번 포트로 연결(그 출발지 구간의 `gateway`). 개발자 도구의 원격 주소도 이 주소
- 에지가 목적지만 WAF로 바꾸고(DNAT) 출발지는 그대로 둠. 센서에는 `waf`가 `X-Forwarded-For`에 고객 주소를 담아 `board.com`으로 보내는 요청이 보임. 에지와 WAF 사이는 센서가 보지 않음
- 컨테이너 이름이나 `mgmt` 주소는 쓰지 않음

이 경로는 콘솔(8000)과 출처가 다른 8002번 포트에서 서비스합니다. 모든 응답에 `Content-Security-Policy: sandbox allow-forms allow-scripts allow-same-origin`을 붙입니다.

- 대상 시스템에는 레드팀이 스크립트를 심을 수 있음. 콘솔과 출처가 같으면 그 스크립트로 콘솔과 콘솔 API를 읽고 조작할 수 있음
- `allow-same-origin` 없는 sandbox(불투명 출처)면 8000번 포트로도 막을 수 있음. 하지만 Chromium 기반 내장 브라우저는 그런 프레임을 거부함(Claude 데스크톱 브라우저에서 `ERR_BLOCKED_BY_CLIENT`). 그래서 포트를 분리함
- `SITE_PORT`는 8002
- 세션 API는 `site: {port, path}`나 `null`을 줌. 값이 없으면 콘솔에서 창을 숨김
- 8002는 플랫폼 템플릿의 security group에서 엶([보안 그룹](OPENSTACK.md#35-security-groups))

기록기는 세션마다 최근 요청 200개를 플랫폼 메모리에 둡니다. 재시작하면 사라지고, 세션이 닫히면 지웁니다. 요청마다 남기는 것:

- 메서드, `http://<호스트><경로>`, 상태 코드와 상태 문구
- 유형과 분류(`Sec-Fetch-Dest` 기준, 없으면 content type)
- 개시자, 전송 크기, 시간
- 출구 주소, 원격 주소, 페이지의 리퍼러 정책
- 보낸 그대로의 요청 헤더(마커 제외)
- 받은 그대로의 응답 헤더(Chrome 패널처럼 `Set-Cookie` 포함)
- 압축을 푼 본문. 각각 64 KB로 자름. 응답은 스트리밍하면서 앞 64 KB만 남김

목록에는 학습자 요청 외에 두 종류의 행이 더 나옵니다.

- `/favicon.ico`: 첫 페이지 이후 세션·호스트마다 한 번
- `disk cache` 행(`cache: "disk"`, 크기 0): 페이지가 참조하는 같은 호스트의 스타일시트·스크립트·이미지 중 예전에 200으로 받았고 1.5초 안에 다시 요청되지 않은 항목마다

목록은 `GET /api/sessions/<id>/site/requests/?after=<id>`, 요청 하나의 전체 내용은 `.../site/requests/<id>/`로 가져옵니다.

개발자 도구 패널은 Chrome 네트워크 패널을 본떴습니다. 페이지 아래에 붙고, 위쪽 가장자리를 끌어 높이를 조절합니다.

- 패널이 열려 있고, 탭이 보이고, 세션이 열려 있는 동안 2초마다 목록을 가져옴. 닫힌 세션은 409를 주고, 그러면 폴링을 멈춤
- 열: 이름(경로 마지막 부분과 쿼리, 마우스를 올리면 전체 URL), 상태(4xx와 5xx는 빨강), 유형, 개시자, 크기, 시간
- 도구 모음: 지우기, 필터, 로그 보관(끄면 페이지 이동 때 목록을 지움), 유형 칩(모두, Fetch/XHR, 문서, CSS, JS, 이미지)
- 행을 고르면 헤더, 페이로드, 미리보기, 응답 탭
- 헤더 탭: 일반(요청 URL, 요청 메서드, 상태 코드, 원격 주소, 리퍼러 정책), 응답 헤더, 요청 헤더. 항목마다 원본 보기
- 페이로드 탭: 디코딩한 쿼리 문자열 매개변수(소스 보기, 인코딩된 URL 보기), 폼 본문
- 행, 탭, 줄에 코치용 `data-coach`
- 라벨은 Chrome의 한국어 문구(`front_end/core/i18n/locales/ko.json`) 그대로. 패널 어디에도 "WAF"라는 말은 없음

브라우징 요청에는 세션 고유 비밀값을 마커로 붙입니다.

- 비밀값은 `Session.browse_marker`. `browse-` 뒤에 무작위 16진수 32자리. 세션을 만들 때 생성
- 브라우저가 보낸 `X-Request-ID`는 기록기에서 덮어씀
- 요청은 고객 주소에서 나감(위 참고)
- 이 요청의 경보도 다른 경보처럼 수집됨. 학습자는 Kibana와 `/detections/`에서 볼 수 있음
- `/score/`에서는 이 비밀값이 붙은 탐지 기록을 뺌. 재실행(`views.REPLAY_MARKS`)을 빼는 방식과 같음
- 브라우징은 케이스가 아님. 탐지 결과에 들어가지 않고, 출처를 알 수 없는 경보로도 치지 않음
- 예외: 레슨 단계의 확인(`sent`, `answer`, `choice`, `rules`의 `match`, `replay`의 `attack.sent`)에 `case:`가 있으면, 그 단계를 통과할 때 단계에 도달한 뒤 그 패턴에 맞게 보낸 요청을 그 케이스의 공격 하나로 기록(`views._record_sent`, `meta.site`에 단계 id, `meta.sent`에 요청 시각과 URL). 같은 URL이고 요청 시각 ±5초 안의 브라우징 탐지 기록은 `/score/`에서 그 케이스의 것으로 셈(`views._sent_by_site`). F4의 XSS 단계 다섯 곳이 `board-xss-script-tag-in-search`를 씀
- 손으로 보낸 `X-Request-ID: browse`는 알 수 없는 마커로 점수에 들어감
- `POST /api/attacker/label/`은 `browse`로 시작하는 label을 거부
- API에는 비밀값이 나오지 않음. `/detections/`, `/api/detections/<id>/`(`raw` 포함), 네트워크 패널에는 그 자리에 `browse`가 나옴
- Kibana는 블루팀의 도구라 비밀값이 그대로 보임
- 레드팀 콘솔의 웹사이트 창도 같은 세션의 같은 창. 워게임에서는 공격자의 브라우징에도 세션 비밀값이 붙음. 그래서 `/score/`에서 빠지고 방어자의 네트워크 패널에 나옴
- 미해결: 사람 대 사람 워게임 4.2는 아직 만들지 않음

API로 실행한 HTTP 케이스는 출발지 선택과 상관없이 세션 워게임의 `Host`인 `board.com`을 싣습니다.

- 출발지를 고르면 공격 박스에서 `set-origin`을 실행해 출발 주소를 그 출발지 주소로 바꿈(SNAT)
- 대상 URL은 출발지와 상관없이 같음(`ATTACKER_TARGET_URL`)
- `rotate`는 무작위가 아니라 세션별 라운드 로빈

API로 실행한 도구 케이스는 출발지의 대상 URL로 보냅니다. 출발지를 고르지 않았으면 선언된 기본 출발지에서 `TARGET_URL`(`http://board.com`)로 보냅니다.

명령줄 harness도 훈련 환경 안에서 대상 시스템에 접근합니다.

- `redteam/run.py`는 플랫폼에서 실행. acceptance 테스트도 같은 방식
- 출발지 옵션 없음
- HTTP 케이스와 도구 케이스 모두 `--tool-target`(기본 `http://board.com`)으로 보냄. corp 케이스 파일은 `--tool-target http://corp.com`을 줘야 corp로 감. 이 이름은 라우터 공인 IP로 풀리고 80번 포트가 WAF로 포트포워딩됨

WAF 컨테이너는 `deploy/waf/modsecurity.conf`의 `SecRuleEngine On`, CRS 기본 임계치 5, Paranoia Level 1로 CRS를 돌립니다.

- Paranoia Level과 룰 예외는 세션마다 따로 둠(`Session.waf`). 세션을 열 때 시나리오의 defense 값으로 쓰고, 이후에는 `/api/sessions/<id>/waf/`로 바꿈("세션, WAF 설정 조정, 단계 엔진" 절)
- `GET`은 10초 timeout으로 파일을 읽음. 폴링 한 번이 서버 스레드를 10초 넘게 잡지 않음
- Suricata 룰은 모두 `alert`. 훈련 환경에서 차단은 WAF에서만 일어남

## 경보의 경로

```
WAF (ModSecurity) -> audit.log ---+
WAF (nginx, 400) --> refused.log -+
Suricata ----------> eve.json ----+-> Filebeat -> Elasticsearch, logs-<slot>-sensors
                                      (event.module) pipeline geoip
                                                          |
             POST /api/sessions/<id>/ingest/ (called by tests, before close/, by the scenario engine and by lesson checks)
                                                          |
             parse per event.module, copy the marker onto alerts, store
             as Detection rows in SQLite
```

`ingest/` 호출 시점:

- `test/conftest.py`가 호출. 콘솔은 `close/` 직전에 호출(세션 화면의 종료 확인, 메인 화면의 열린 세션 종료, 레슨 과정 끝, 시나리오 끝). `close/`는 수집하지 않으므로 `close/`만 부르는 에이전트는 마지막 수집을 받지 못함
- `redteam/run.py`는 호출하지 않고 curl 명령만 출력
- 워게임 세션은 콘솔이 종료 직전에 한 번 수집
- 레슨과 시나리오는 진행 중에도 수집. 시나리오 엔진은 15초마다 최근 180초, 기록을 읽는 단계 점검은 점검할 때마다 최근 600초
- 종료 뒤에는 수집하지 않음. 이벤트 시각이 종료 1분 뒤보다 늦은 경보는 `ingest/`를 다시 호출해도 조회 기간 밖이라 들어오지 않음

경보에 마커가 붙는 방식:

- ModSecurity audit log에는 요청 헤더가 남음. 경보에 마커가 처음부터 들어 있음
- Suricata alert 이벤트에는 요청 헤더가 없고 `http` 이벤트에만 있음(`dump-all-headers: request`일 때. `custom: [X-Request-ID]`로는 남지 않음)
- 그래서 ingest에서 `(flow_id, tx_id)`가 같은 `http` 이벤트의 마커를 alert로 복사
- `flow_id`만으로 조인하던 때는 keep-alive 연결의 경보가 모두 그 연결의 첫 케이스로 잡혔음

경보의 출발지 주소:

- 센서는 WAF 뒤에 있어 Suricata 이벤트의 `src_ip`는 언제나 WAF
- http 기록의 `xff`에는 WAF가 붙인 `X-Forwarded-For`의 클라이언트 주소가 있음. Suricata는 헤더를 읽기 전에 URI 경보를 내므로 alert 이벤트에는 `xff`가 없을 수 있음
- 그래서 ingest(`elastic.normalize_all`)에서 `(flow_id, tx_id)`가 같은 `http` 기록의 `xff`를 Suricata 경보의 `src_ip`로 씀
- 탐지 기록, window 매칭, 공격 출발지 지도, 레슨 답이 모두 공격자 주소를 씀
- nginx 거부 기록에는 `X-Request-ID`가 없음. ModSecurity가 돌기 전이고 헤더도 읽기 전이기 때문. 이런 요청은 출발지 주소와 시각으로 매칭함

ingest를 호출할 때마다 하는 일:

- 비활성화 시간이 지난 룰부터 다시 활성화
- `logs-<N>-*` 읽기(`ELASTIC_SESSION_INDEX`, N은 세션의 슬롯)
- Elasticsearch는 세션 시작 1분 전부터 종료 시각(또는 현재) 1분 뒤까지의 `@timestamp`로 조회
- 오래된 순으로 5000건씩 읽음
- Suricata `alert` 이벤트는 그대로 씀. ModSecurity 기록은 매칭된 룰 메시지마다 `Detection`(id `<Elasticsearch _id>:<n>`)으로 나눔
- nginx 거부 기록 하나는 WAF 탐지 하나. `source`는 `nginx`, 시그니처는 `<상태 코드> <요청 줄>`, `src_ip`는 클라이언트 주소
- 이벤트 시각이 조회 기간을 벗어난 경보는 버리고 `stale`로 셈
- 마커 없이 저장된 행에 나중에 찾은 마커를 채움
- `src_host`와 `dest_host`는 substrate의 구간 정보로 채움. substrate에 접근할 수 없으면 비워 둠

인덱스와 슬롯:

- 공유 수집기는 syslog 줄마다 송신자 hostname으로 슬롯을 판별(도메인 앞의 `-N`, 없으면 슬롯 1). 태그를 붙여 그 슬롯의 인덱스에 씀. 태그는 ingest 파이프라인에서 저장 전에 지움
- Filebeat는 syslog 태그로 `event.module`(`suricata`, `modsecurity`, `nginx`)을 붙임. 셋 다 아닌 syslog 줄은 버림
- 인덱스에는 두 엔진의 이벤트와 nginx 거부 기록만 남음. 학습자가 Kibana에서 보는 필드·인덱스·헤더 어디에도 플랫폼 이름이 없음. 케이스 마커는 `X-Request-ID` 헤더에 실림

조회 기간:

- `geoip` 파이프라인은 `@timestamp`를 이벤트 발생 시각(Suricata의 `timestamp`, ModSecurity의 `transaction.time_stamp`)으로 덮어씀. nginx 거부 기록은 Filebeat가 받은 시각 그대로
- 조회 기간은 Filebeat가 읽은 시점이 아니라 이벤트 발생 시점 기준

5000건 단위 읽기:

- 결과가 잘리면 받은 문서 중 가장 최근 `@timestamp`부터 다시 조회(`api/views.py` `_fetched`, 최대 40회 추가). 이미 읽은 문서는 `_id`로 건너뜀
- 그래도 조회 기간을 다 못 읽었거나 5000건이 전부 같은 시각이면 응답에 `truncated`를 싣고 세션에 `read_of`를 기록. 점수에 `score.warning.truncated`가 붙음
- sqlmap 케이스 하나만으로 5000건을 넘김. 한 번만 읽던 때는 그 뒤에 실행한 공격 케이스가 모두 미탐으로 처리됐음

구간 정보 캐시:

- 단계 폴링과 답 확인마다 클라우드를 조회하지 않도록, ingest와 `/detections/`는 열린 세션의 구간 정보를 세션이 닫힐 때까지 재사용
- `/top/`, `/topology/`는 매번 새로 조회. `/map/`은 구간 정보를 쓰지 않음

Elasticsearch는 저장과 색인 시점 GeoIP 보강에만 씁니다. 그래서 Logstash는 두지 않았습니다.

- 조회 기간 검색 외에 쿼리 엔진은 쓰지 않음
- `GET /api/sessions/<id>/map/`과 `/top/`은 SQLite 사본으로 Python에서 계산
- `src_geo.location`은 `geo_point`가 아니라 float 두 개로 매핑
- `bin/worldmap`은 남위 60도에서 자른 Equal Earth 도법 월드맵을 만듦. 블루팀 대시보드를 없앤 뒤로 이 지도를 그리는 화면은 없음

`src_geo`는 geoip 프로세서 두 개가 씁니다. 대상은 `src_ip`(Suricata)와 `transaction.client_ip`(ModSecurity)입니다. Suricata의 `src_ip`는 WAF 주소라 국가가 붙지 않고, nginx 거부 기록의 `client_ip`는 대상이 아닙니다.

- compose에서 관리형 다운로더를 끄고, `bin/fetch-geoip`로 채운 `./config/ingest-geoip`를 bind-mount. 컨테이너를 다시 만들어도 `GeoLite2-City.mmdb`가 남음
- 파이프라인은 시작 시 entrypoint에서 등록(`platform/register_pipeline.py`). `kibana.py`처럼 백그라운드로 돌아, Elasticsearch가 올라오는 중에도 플랫폼은 서비스를 시작함

플랫폼 서비스:

- waitress(스레드 16개)로 127.0.0.1:8001에서 서비스
- entrypoint는 nginx 설정을 검사하고, 이 포트가 연결을 받기 시작한 뒤에 nginx를 띄움. 플랫폼 시작 중에 nginx가 502를 내지 않음
- nginx는 모든 location에 `proxy_max_temp_file_size 0`과 1 MB 요청 본문 버퍼를 적용. 프록시 응답과 요청 본문을 임시 파일로 쓰지 않음

Django는 `DJANGO_DEBUG=1`이 아니면 `DEBUG`를 끄고 돕니다.

- `DJANGO_SECRET_KEY`가 없으면 entrypoint에서 `/data/secret-key`(모드 600)에 키를 한 번 생성
- `DEBUG`가 꺼져 있는데 키가 없으면 `cr/wsgi.py`에서 서비스 거부
- `/api/` 아래 404는 JSON `{detail}`(`api/refusals.py`)

## 세션, WAF 설정 조정, 단계 엔진

세션은 `POST /api/sessions/` `{scenario, guidance, lesson, defense}`로 엽니다. 네 값은 세션에 저장합니다(마이그레이션 0015, 0022).

- `scenario`: 워게임(기본값 `board`)이나 시나리오 id. 시나리오로 열 때는 `lesson`, `guidance`, `defense`를 받지 않음("시나리오" 절)
- `defense`: 워게임 세션에서는 그 워게임에 선언된 `defense` 항목 중 하나. 기본값 `full`
- `guidance`: 기본값은 꺼짐. `lesson`을 주면 켜짐. 워게임에 `foundations`가 선언돼 있어야 씀. `guidance: false`와 `lesson`을 함께 주면 거부
- `{"lesson": "f1"}`~`"f6"`: 그 기초 레슨을 엶. `{"guidance": true}`만 주면 `order`가 가장 앞인 레슨(f1)
- 레슨은 `Session.lesson`에 저장하고 `lesson_id`로 보고. 가이드 세션에서 defense를 지정하지 않으면 레슨에 선언된 `defense`를 씀
- 세션 `kind`: `scenario`, `lesson`(가이드), `wargame` 중 하나
- 저장된 레슨 id의 레슨이 없어지면 `lesson: null`, `lesson_id: null`로 읽힘. kind는 `lesson`으로 남음. 이전 과정의 세션이 해당(`docs/DECISIONS.md` 2026-10-14)
- 마이그레이션 0026에서 `Session.mode`를 지우고 `Session.result_cache`를 비움. 저장된 결과는 레슨 판정 없이 다시 채점됨. 요청 본문의 `mode`는 무시
- `GET /api/sessions/?ids=1,2`: 세션 목록을 id로 좁힘

board에 선언된 defense:

| defense | 설정 |
|---|---|
| `minimal` | CRS paranoia level 4, `local.rules` |
| `full` | paranoia level 1, 같은 `local.rules` |
| `ids` | paranoia level 1, `no-uri-sqli.rules`(sid 9000001을 뺀 `local.rules`) |
| `xss-watched` | paranoia level 1 DetectionOnly(차단하지 않고 기록만), `local.rules`. 시나리오 3.4 |
| `xss-gap`, `overbroad` | "기초 레슨 F1-F6" 절. `xss-gap`도 DetectionOnly |
| `level2`, `level3`, `inherited`, `untuned`, `broken-rule`, `spelled` | 시나리오용. "시나리오" 절 |

레슨의 `defense`가 이 목록에 있는지는 discovery 시점에 대조합니다. `minimal`로 시작하는 레슨이나 시나리오는 없습니다. `minimal`은 이름을 직접 지정할 때만 씁니다.

세션을 열 때의 처리:

- defense의 룰 파일을 센서에 넣음. defense가 없으면 `local.rules`(`suricata.seed`)
- defense가 있으면 CRS 설정 작성(`crs.apply`)
- 가이드 세션은 레슨의 `cases`를 한 번 재실행(`meta.seed`). curl이 보고한 상태 코드를 기록하고, 403이면 `blocked`
- 그래서 학습자가 들어올 때 Kibana에 이미 ModSecurity와 Suricata 기록이 있음. 단계형 시나리오는 재실행하지 않음
- 재실행에 실패하면 503으로 응답하고 세션을 닫음
- Kibana space 준비, 공격 출발지 지정, baseline 읽기, WAF 설정, 센서 룰 적재는 서로 기다리지 않고 함께 돌림. 레슨 기록 재실행만 WAF·센서·출발지가 끝난 뒤. 준비 확인의 ground truth 읽기와 센서 룰 읽기도 함께 돌림

룰 파일이 `local.rules`이면 센서에 넣지 않습니다. 준비 확인(readiness)이 모든 센서에 이 파일이 들어간 뒤에야 슬롯을 내주기 때문입니다. 룰 파일은 슬롯의 센서마다 따로 있습니다(2026-10-13 측정: 슬롯 1에 넣은 sid가 슬롯 2에는 없었음). 그래서 다른 룰 파일은 그 슬롯의 센서에만 넣습니다.

`platform/rules/crs.py`는 설정을 `REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`로 생성합니다. `crs-setup.conf` 다음, 룰보다 먼저 로드되는 CRS hook입니다.

- `tx.blocking_paranoia_level`과 `tx.detection_paranoia_level`을 설정하는 `SecAction`(id 10000). `detection_only: true`면 같은 `SecAction`에 `ctl:ruleEngine=DetectionOnly`를 붙여 기록만 하고 차단하지 않음
- 항목별 런타임 예외 규칙(id 10001~10020)
- 예외 형식: `ctl:ruleRemoveTargetById=<id>;<target>`, `ctl:ruleRemoveById=<id>`. CRS `tag`와 target을 지정한 항목(예: `OWASP_CRS`)은 `ctl:ruleRemoveTargetByTag=<tag>;<target>`
- 경로가 있으면 `SecRule REQUEST_FILENAME "@beginsWith <path>"`로 범위를 좁힘

파일 적용 순서:

1. `runner("gateway")`로 세션 WAF에 파일을 씁니다.
2. `nginx -t && nginx -s reload`를 실행합니다. nginx가 거부하면 이전 파일로 되돌립니다.
3. reload 전에 없던 워커가 뜨면 반환합니다. 워커 PID는 `/proc`에서 부모 PID로 찾습니다. 새 설정은 새 연결부터 적용되고, 이전 워커는 처리 중인 느린 요청을 마저 끝냅니다.
4. 5초 안에 새 워커가 보이지 않으면 reload 실패로 봅니다. 이전 파일로 되돌려 다시 reload하고 요청을 거부합니다.

입력은 쓰기 전에 검증합니다.

- paranoia: 1-4
- 룰 id: 900000-999999. 또는 영문자·`_`·`-`로 된 tag와 target
- target: `ARGS`, `ARGS_GET`, `ARGS_POST`, `ARGS_NAMES`, `REQUEST_COOKIES`, `REQUEST_HEADERS`(이 여섯은 `:이름` 선택), `REQUEST_URI_RAW`, `REQUEST_BODY` 중 하나. PL3에서는 한글 검색어가 `REQUEST_URI_RAW`로도 920272에 매칭됨
- 경로: `/`로 시작하고 `[A-Za-z0-9_./-]`로 된 값
- 항목: 최대 20개
- `thresholds` `{inbound, outbound}`(1-100000): 선택. 레벨과 같은 `SecAction`에 `tx.inbound_anomaly_score_threshold`, `tx.outbound_anomaly_score_threshold`로 넣고 다시 읽어 확인
- `PUT`에서 `thresholds`를 빼면 현재 값 유지. `"thresholds": null`이면 값을 지움
- `detection_only`(true/false): 선택. `thresholds`와 달리 `PUT`에서 빼면 유지하지 않음. `xss-watched`·`xss-gap` 세션에 이 값 없이 `PUT`하면 WAF가 다시 차단함
- 닫힌 세션에 `PUT`하면 409

설정 변경은 `PUT /api/sessions/<id>/waf/`로 합니다. 에이전트용 경로이고, 이를 호출하는 콘솔 화면은 없습니다.

`GET`은 세션 WAF의 파일을 `crs.read`로 다시 읽습니다. `crs.read`는 Paranoia Level, 임계치, `DetectionOnly`, `ctl:ruleRemove*` 줄을 모두 파싱합니다. 주석 줄은 건너뛰고 이어지는 줄은 합칩니다. 학습자가 WAF 터미널에서 직접 고친 내용도 보고에 반영됩니다.

WAF 상태 스냅숏:

- 시나리오 최종 점검에서 구간을 판정할 때마다, 세션을 닫을 때마다(슬롯 초기화 전) `crs.read` 결과를 스냅숏으로 남김
- 레슨을 옮길 때도 옮기기 전의 WAF를 스냅숏으로 남김
- 스냅숏은 `Session.waf_snapshots`에 쌓임(마이그레이션 0021): `{at, scenario_window|closed|lesson, waf}`. 이전 과정의 세션에는 VERIFY 실행 때 남은 `{at, run, waf}`도 있음
- 가장 최근 스냅숏은 `Session.waf`. 닫힌 세션도 파일을 포함한 학습자의 마지막 설정을 보고함. 한 번도 읽지 못했으면 `file: null`
- WAF를 읽지 못하면 스냅숏은 남기지 않음. 최종 점검이나 세션 종료는 막히지 않음

조치 유형(`lesson.fix_class(waf, posture)`, 결정 D1)은 학습자가 세션 시작 때의 방어 설정에서 무엇을 바꿨는지입니다. 위에서부터 차례로 확인합니다.

1. `level`: Paranoia Level을 방어 설정보다 낮춤. 레벨이 없는 파일은 CRS 기본값 1로 봄
2. `threshold`: anomaly 임계치를 방어 설정보다 높임. 설정하지 않았으면 CRS 기본값 inbound 5, outbound 4로 봄
3. `rule`: 방어 설정에 없던 예외 규칙으로 룰 전체를 뺌
4. `target`: 추가한 예외 규칙으로 모든 경로에서 target을 뺌
5. `path_target`: 추가한 예외 규칙이 모두 특정 경로 하나에서만 target을 뺌
6. null: 추가한 것 없음

시나리오 최종 점검은 조치 유형을 판정 옆에 보고합니다(`result.fix`, `result.scenario.fix`). 판정에는 영향이 없습니다.

`platform/lesson.py`에는 조치 유형 함수 외에 다음이 있습니다.

- 단계 답 처리 함수: `answered`, `status_said`, `an_address`, `alerts_on`, `rules_named`, `added_rules`, `raised_rev`, `pasted_rows`, `server_errors`, `server_error_sources`, `alerted_by`, `detected_penalty`, `objective_outcome`
- 도움 사용 횟수
- 시나리오 디브리핑의 추가·삭제된 예외 규칙과 파일 diff(`exclusions_changed`, `config_diff`)

마커가 `views.REPLAY_MARKS`(`seed`, `verify`, `check`, `replay`) 중 하나인 케이스는 `/score/`에서 뺍니다. 탐지 결과, 케이스가 일으킨 경보, 게임 점수 모두 해당합니다. corp 효과 관찰에서 변경을 귀속시키는 시간 구간에서도 뺍니다.

- 예외: 정상 `seed` 케이스. 레슨의 seed 재실행을 정상 케이스로 채점함(2026-10-18). 그래서 레슨 세션에도 정상 통과가 생김
- 지금 쓰는 마커는 `seed`뿐. `verify`, `check`, `replay`는 이전 세션에 남은 재실행이 계속 두 점수에서 빠지도록 남겨 둠

콘솔은 화면 네 개이고, 모든 화면은 `/api/`에서 데이터를 가져옵니다. 사용자가 승인한 정적 시안에 사용자 결정 두 가지를 반영했습니다(`docs/DECISIONS.md` 2026-10-11, 콘솔 재설계).

- 색상 팔레트와 컴포넌트 클래스: `base.html`, `platform/console/components.css`. `bin/build-css`로 `tailwind.css`에 넣음
- 머리글: 경로 표시(breadcrumb), 훈련 환경 상태
- 콘솔은 한국어 전용. 언어 전환 없음

**메인**(`/`):

- 진행 중인 세션: 진행 내용과 기초 레슨 세션의 현재 단계. 진행 내용은 과정 이름, 과정 밖 레슨이면 레슨 이름, 시나리오 번호와 제목, 또는 워게임과 대상 시스템
- "준비 중 n초": 세션을 여는 중일 때만 표시(`ready`, `Session.ready_at` 기준)
- "대상 시스템" 아래에 워게임 카드(이름, 한 줄 설명)
- `GET /api/wargames/`의 공격 케이스·정상 케이스·목표 수는 운영자에게만 보임
- 페이지 제목, 예상 소요 시간, 분류, 난이도, 시나리오 유형·안내 수준 칩은 없음(2026-11-14)
- 카드 아래에 기초 레슨 묶음, 시나리오 묶음("시나리오" 절), 워게임 묶음. 행마다 버튼은 "시작"
- 기초 레슨 행: "레슨 n"과 제목. 시작하면 레슨의 defense로 `{scenario, guidance: true, lesson, defense}`를 보내고 블루팀 콘솔로 감(2026-11-15)
- 시나리오 행: 번호와 제목만(2026-11-15)
- 워게임 행(`[data-wargame-start]`): 제목과 시작 버튼. `{scenario}`만 보내므로 가이드 없이 defense `full`로 열림
- 카드 그리드는 위쪽 정렬. 짧은 카드가 긴 카드 높이로 늘어나지 않음
- `cr-opened-sessions`(localStorage): 이 브라우저에서 연 세션. 세션 화면과 블루팀 화면이 씀
- 끝난 레슨 세션 행: 과정 이름(과정 밖이면 레슨 이름). 결과 칸은 과정 카드의 `scored`가 켜져 있을 때만 목표를 보여 줌(`wargames._course_scored`: `kali`나 `replay` check가 있는 과정). 과정 1은 "—"
- 끝난 세션 목록: 진행 내용과 `result`. 시나리오면 마지막 최종 점검의 통과·미통과(`result.scenario`, 문구 `scenario.phase.passed`, `scenario.phase.failed`). 아니면 전체 목표 중 탈취된 목표 수(`result.objectives.lost`, `.total`)
- 결과는 한 번 채점해 채점 입력과 함께 저장(`Session.result_cache`, 마이그레이션 0018)
- 채점 입력: `ended_at`, 힌트 수, 최종 점검별 판정. 탐지 기록·케이스·목표는 각각 마지막 id와 행 수. 탐지 기록은 마커가 있는 행 수도 포함
- 목록을 그릴 때는 세션마다 집계값 세 개만 읽음. 늦은 수집처럼 입력이 바뀐 세션만 다시 채점
- 시작이 거부되면 누른 버튼 아래에 알림. 훈련 환경이 가득 차 409면 "열린 세션 종료"에서 열린 세션을 나열하고 하나씩 `ingest/` 후 `close/`로 닫음. `max_sessions`는 `GET /api/range/ready/`로 받음. 학습자가 이미 세션을 가지고 있어 409(`open_session`)면 그 세션으로 가는 링크를 보여 줌
- 하단: Kali 상표 고지(`topology.trademark`)
- 훈련 환경 관리 항목(경보 수집 확인, 열린 세션 수, 훈련 환경 상태, 워게임 카드의 개수)은 `?operator`일 때만 보임

**세션**(`/session/<id>/`):

- 머리글: 가이드 세션의 현재 단계(`main.step`. 라벨이나 레슨 번호 없음). 진행 중이면 탈취된 목표(결과 화면에서는 주 점수에 나오므로 생략)
- 세션 종류는 쓰지 않음. 경로 표시에 있는 대상 시스템은 반복하지 않음. 상태는 세션을 여는 중일 때만
- 경로 표시: 메인 / 워게임 · 그 아래 줄과 같은 이름(시나리오 번호와 제목, 과정 이름, 레슨 이름) / 결과(닫힌 세션). 이름은 `base.html`의 `playedName`이 세션 응답과 `GET /api/wargames/`로 정함. 블루팀·레드팀 콘솔도 같은 두 응답으로 같은 이름을 쓰므로, 시작 버튼으로 콘솔부터 열어도 이름이 나옴. 콘솔은 카탈로그를 기다리지 않고 세션 응답으로 시작하며, 카탈로그 응답이 오면 경로 표시만 다시 그림. 그 전에는 시나리오 번호만 보임. 블루팀 콘솔은 이름이 있으면 "블루팀 콘솔"로 끝나고, 카탈로그를 읽지 못해 이름이 없을 때만 세션 종류(시나리오, 레슨)를 마지막에 붙임. `cr-session-name-<id>`(localStorage)는 응답이 오기 전 첫 표시에만 씀
- 그 아래 줄: 과정이나 레슨 이름, 시각
- 진행 중인 시나리오는 시작 시각만 보여 줌. 시나리오 시계는 세션을 열 때가 아니라 상황 설명에서 시작을 누를 때 돌기 시작함
- "블루팀 콘솔 열기" 버튼. "레드팀 콘솔 열기"는 워게임 세션에만 있음
- 워게임 세션: `GET /api/sessions/<id>/cases/`로 최근 케이스 표시
- 레슨과 시나리오에는 최근 활동 패널이 없음. 레슨은 자동 요청을, 시나리오는 예정된 공격을 숨김

세션이 닫히면 아래 순서로 보여 줍니다.

1. 시나리오의 판정 배너와 디브리핑("시나리오" 절)
2. 주 점수: 모든 등급의 목표별 결과 열(지킴, 탈취됨 · 탐지, 탈취됨 · 미탐), 감점(난이도 ×1 또는 ×2), 탈취 판정 방법 한 줄. 걸린 목표가 없으면 이 카드를 숨김
3. "탐지 결과": 예를 들면 "공격 8건 중 7건 정탐", "정상 요청 4건 중 3건 경보 없이 통과". 틀린 항목은 그 아래에 한 번만 나열

탐지 결과 화면의 세부:

- 실행 한 번을 1건으로 센다는 설명 줄은 없음
- 탐지가 공격 기법을 짚었는지 보여 주는 열은 없음. `corroborated`는 API에만 있음
- 시나리오 결과: 차단된 고객 요청은 결과 보고에만 둠. 실행된 공격이 없으면 없다고 밝힘. 요청별 표가 비면 숨김
- 탐지 시나리오(`detected_by`): 탐지 결과에 "고객 요청 N건 중 M건 경보 없이 통과"와 경보가 난 고객 요청(시각, 메서드, 경로, `customers.alerted_requests`, 최대 20건), 요청별 표 끝에 고객 요청 한 줄(통과 또는 오탐). 표 머리에 그 탐지기의 경보만 센다는 한 줄
- 요청별 결과는 배지 대신 색 글자. 열은 요청, 종류, 결과. 경보 건수는 결과 아래 보조 글자("경보 N건")이고 따로 열을 두지 않음. 목표 결과는 "탈취됨, 탐지"나 "탈취됨, 미탐"
- 시나리오 결과 보고에서 빼는 것: 빈 항목(기록된 공격 로그, 적용 전·후로 판정한 요청, 남은 위험이 없을 때), 0회인 최종 점검 횟수
- 공격 출발지는 나라 이름(`scenario.origin.<code>`)
- 시나리오에 맞는 문구를 씀(예: "웹방화벽 설정을 바꾸지 않았습니다")
- 탐지 결과의 집계 필드와 게임 점수는 API에만 있음. 사람이 읽는 문구에는 나오지 않음(`test_strings.py`)

세션 화면의 나머지:

- 레슨 세션: 실행마다 케이스 이름으로 부름. Kali 실행과 F4에서 웹사이트 창으로 보낸 XSS 케이스는 케이스 id 대신 "레슨 n · m단계"(`per_case[].lesson`, `.step`, `.seed`. `step`은 `meta.kali`나 `meta.site`)
- 시나리오 세션: 같은 케이스가 여러 번 실행되면 이름 아래 실행 시각으로 구분(`per_case[].started_at`). 공격 타임라인도 같은 시:분 시각(`at.opened` + `timeline[].at`)
- 닫힌 레슨 세션(점수가 있는 코스): 레슨 카드 아래 "적용한 조치". 세션 상세 API의 `changes`(`views.lesson_changes`)는 레슨마다 하나씩, 그 레슨을 시작할 때의 상태와 끝날 때의 상태를 비교함. 시작 상태는 레슨을 옮기며 방어 설정이 다시 깔렸으면 그 레슨의 방어 설정, 아니면 앞 레슨이 끝난 상태. 끝 상태는 그 레슨 안에서 마지막으로 적용한 룰 파일과, 레슨을 옮길 때(`waf_snapshots[].lesson`)나 세션을 닫을 때 읽은 WAF. 레슨 사이 기본 룰 파일의 차이는 학습자의 조치로 나오지 않음. 아무것도 바꾸지 않은 레슨은 화면에서 빠지고, 레슨이 둘 이상이면 레슨 이름 아래에 보여 줌
- 진행 중인 시나리오 세션: 구간이 판정됐으면 종료 버튼 아래에 판정과 결과 보고를 보여 줌
- 탐지 결과는 "공격 N건 중 M건 정탐" 같은 문장 하나. 같은 숫자를 큰 글씨로 한 번 더 쓰지 않음
- 레슨 카드: 수강한 레슨마다 통과한 단계. 건너뛴 수는 없음
- "다시 시작": 같은 시나리오, 같은 워게임을 다시 엶. 레슨 세션은 그 세션에서 처음 시작한 레슨부터 다시 엶(`{scenario, guidance: true, lesson, defense}`. F3에서 끝난 과정 세션도 F1부터). `defense`는 그 레슨이 `lesson_id`면 세션의 것, 아니면 레슨 카드의 것. 레슨과 시나리오는 블루팀 콘솔로 열림
- 이미 닫힌 세션을 종료하면(두 번 누름, 다른 탭에서 닫음) 세션을 다시 읽음. `ended_at`이 있으면 409 영어 메시지 대신 종료됐다고 알리고 결과를 보여 줌(`base.html`의 `alreadyClosed`). 메인 화면과 레슨 끝에서도 같음

**블루팀**(`/blue/<id>/`):

- 왼쪽 메뉴와 창. 메뉴 순서는 Kibana, 웹사이트, 구성도, `judgement` 시나리오의 경보, IDS 룰, WAF, 참고. 구분선 아래에 Kali
- IDS 룰 창: `detection`·`unknown` 시나리오, 그리고 단계가 룰 창을 열거나 `rules` check를 쓰는 레슨(F4)에서 쓸 수 있음. 단계가 있는 다른 가이드 세션에서는 메뉴에 보이되 비활성
- Kali: 세션 `kind`가 `lesson`이나 `scenario`일 때만. `wargame` 세션에서는 사람이 레드팀 콘솔에서 공격하므로 방어자에게 공격자 쉘을 주지 않음
- Kali 창은 한 번만 로드하는 별도 프레임. 다른 창으로 옮겨도 돌던 sqlmap이 끊기지 않음
- WAF 창 배너: WAF 박스(`waf_box`, `waf`)와 CRS 룰 디렉터리(`waf_rules`)만. 이 디렉터리는 선언된 예외 파일 `settings.CR_WAF.rules`가 있는 곳

**레드팀**(`/red/<id>/`):

- 위쪽: 세션과 워게임 이름, 목표(한국어 이름은 `objective.<key>`), "탈취한 해시 제출"
- 왼쪽 메뉴의 창 두 개: 세션의 Kali 터미널, 웹사이트 창(주소 표시줄, 개발자 도구, 블루팀 콘솔과 같은 스크립트)
- 미리 준비한 공격은 실행하지 않음. 케이스 목록, 실행 버튼, 기록 창, 출발지 선택이 없음(2026-10-18)
- 화면 폭이 좁으면 메뉴가 창 위로 올라감. 레드팀·블루팀 화면 모두 가로 스크롤 없음

가이드 세션(기초 레슨, 단계형 시나리오)의 레슨 노트는 창을 덮지 않고 창 옆에 열로 붙습니다.

- 너비 340 px(1280 px 이하에서 300 px). 접으면 44 px 띠("단계 n/N"). 1024 px 미만에서는 창 아래 패널
- 머리글: 레슨이면 "레슨 노트", 시나리오면 "시나리오 노트". 부제 없음

노트 구성(위에서부터):

- 단계 카드: 단계 n/N, 단계 제목, 할 일, 단계 진입 후 입력할 명령, 단계의 창이 안 보일 때의 "<창> 열기" 버튼, 질문과 입력란, 상태 줄, 도움말, 이전, 다음 버튼
- 다음 버튼(`step-next`): 통과한 단계에서는 `lesson.coach.next`, 아니면 `lesson.skip`
- F6의 목표 카드(`lesson_objectives`): 단계 카드와 직접 해 보기 카드 뒤. 모든 목표를 난이도와 함께 나열. 레슨 시작 후 목표별 탈취 여부와 그 탈취의 탐지 여부. 탈취되지 않은 목표의 탐지 여부는 "해당 없음", 어느 장비가 경보를 냈는지 묻는 단계를 통과하기 전에는 "확인 전". 감점 열과 합계 없음
- 이론 카드는 없음(2026-11-13). 이론 내용은 참고 열과 과정 안내에 있음
- 단계형 시나리오의 카드와 힌트
- F4와 F6의 채점하지 않는 "직접 해보기" 카드
- 접힌 단계 목록

노트 상태:

- 단계 목록의 체크 표시는 `progress`에서 통과로 판정한 단계에만 붙음. 통과하지 않고 넘어간 단계는 "건너뜀"
- 노트 접힘 상태는 브라우저에 하나로 저장(`cr-lesson-note`, localStorage). 세션·레슨마다 처음 들어올 때는 접힘 상태와 관계없이 노트를 엶(`cr-lesson-landed-<세션>-<레슨>`)
- 보던 단계는 `cr-lesson-step-<id>-<lesson>`에 남음. 메인과 세션 화면이 이 값으로 "단계 n/N"을 표시
- 이 기록이 없는 브라우저(새 브라우저, 저장소를 지운 경우)에서는 서버에 `reached`로 기록된 가장 뒤 단계부터 엶(2026-11-14)

진행 상황은 세션에 레슨별로 저장합니다(`Session.lesson_steps[<lesson>][<step>]`, 마이그레이션 0020, 0027).

- 단계마다 `reached`, `passed`, `skipped`(시각), `hint`(보여 준 힌트 단계), `tries`(틀린 답 수, 초기화 안 함)
- 틀린 뒤 통과한 단계는 세션 `course` 행의 `retried`에 집계
- 현재 레슨 기록은 `GET /api/sessions/<id>/`와 모든 단계·힌트 응답의 `progress`에 담김
- 단계 기록에는 그 단계에서 얻은 것도 남음. 진입하면 `command`, 통과하면 `ok`(통과 문장), 단계형 시나리오에서 힌트 단계가 3(`lesson.ANSWER`)이 되면 `answer`
- `POST /api/sessions/<id>/lesson/steps/<step>/ {state: reached|skipped}`: 단계 진입이나 통과하지 않고 넘어간 것을 기록
- check가 Kali 케이스를 가리키는 단계에 진입하면 마커를 발급. 플랫폼은 이 마커를 스탬프 프록시의 `/var/lib/session/active`에 씀
- 통과하지 않은 단계에서 다음을 누르거나 목록으로 이동하면 `skipped`를 보냄. 이전을 누르거나 통과한 경우에는 보내지 않음
- 통과 문장은 통과한 단계에만 보임. 다음 단계는 빈 카드로 시작

단계는 레슨에 선언합니다(`scenario.yaml`에서 기초 레슨이나 단계형 시나리오의 `steps`).

- `id`
- `check`: `kind`는 `click`, `answer`, `choice`, `rules`, `sent`, `kali`, `loot`, `triage`, `waf_changed`, `replay` 중 하나(`wargames.CHECK_KINDS`, discovery 시점에 검증)
- `point`
- `command`: 학습자가 입력할 터미널 명령. 안의 `{waf_rules}`, `{waf_reload}`, `{sudo}`는 `wargames.lesson`이 선언된 WAF 구성(`settings.CR_WAF`)으로 채움

기초 레슨 단계에는 Kibana `query`가 없습니다. Kibana 대상에 `kql:`을 붙일 수 있습니다.

- 학습자가 제출한 쿼리(Discover URL의 `query`, 없으면 쿼리 입력창)가 이 정규식에 맞을 때까지(대소문자 무시) 강조는 쿼리 입력창에만 머묾(단계 `write`. 말풍선 없이 테두리만)
- 그래서 학습자가 쿼리를 쓰기 전에는 어떤 강조도 답을 드러내지 않음

세션 API는 단계 정보 중 아래 값만 브라우저로 보냅니다.

- 보내는 것: 단계에 `command`가 있는지(`has_command`), check의 `kind`, `form`, `leg`, `options`(`form: order`면 학습자 워게임의 장비 이름. customers는 빠짐), 단계 자신의 `match`나 `about`으로 가리킨 단계의 `match`, check에 `dev`가 있을 때 `dev: true`(정규식은 안 보냄), 기초 레슨 마지막 단계의 `solo`
- `accept` 목록이나 정답 규칙은 브라우저로 나가지 않음
- 단계의 `command`는 `progress`에 그 단계 진입이 기록된 뒤에야 응답에 들어감. 실행 버튼은 없고, 명령 아래에 복사 버튼(`lesson.command.copy`)이 있음
- 통과 문장(기초 레슨은 `<text>.ok.<step>`, 선택형 단계에서 답에 따라 다르면 `<text>.ok.<step>.<option>`. 단계형 시나리오는 `<text>.line.<step>`이고 기록의 `line`에 들어감)과 단계형 시나리오의 정답은 `strings.html` 끝의 `{% comment %}` 구역에 둠. Django가 렌더링하지 않음
- 이 구역은 `console/strings.py`가 읽어, 학습자가 얻은 시점에 단계의 `progress` 기록에 넣음
- check를 통과해도 단계가 넘어가지 않음. 학습자가 '다음'을 눌러야 함. 마지막 단계만 레슨 끝 카드로 자동 전환
- 이전/다음은 check 없이도 이동 가능

check 종류별 통과 조건:

`answer`, `choice`: 입력이 허용 값 중 하나와 대소문자·공백 구분 없이 같으면 통과(`lesson.answered`).

- `form: order`: 입력 순서대로 호스트(공백, 쉼표, `>`, `→`로 구분)를 비교. 호스트는 맞고 순서만 틀리면 `<text>.wrong.<step>.order`
- `wrong_if` 규칙의 `match`가 답에 맞으면 `<text>.wrong.<step>.<says>`
- `known`에 있는 값을 입력하면 `<text>.wrong.<step>.<value>`
- 허용 값은 `accept` 목록이거나, `of:`로 세션 기록에서 읽음("기초 레슨 F1-F6" 절)
- 구성도 주소 단계(`of: address`): 틀린 IPv4 주소가 학습자 구성도의 다른 장비 주소면 `lesson.check.wrong.address_of`로 "다른 장비의 주소"라고만 알림(`views._whose_address`). 묻는 장비의 다른 구간 쪽 주소면 `lesson.check.wrong.address_side`로 장비는 맞고 구간이 다르다고 알리고, 틀린 횟수에 넣지 않음. 선이 둘 이상인 장비(board.com, WAF)를 묻는 질문은 구간 이름을 적음. waf 주소가 F1 마지막 단계의 답이라 장비 이름과 주소는 되풀이하지 않음. 다른 단계는 각자의 문장을 씀
- `status`: 코드만 입력해도, 개발자 도구에 보이는 대로 사유 문구를 붙여도(`200 OK`) 인정(`lesson.status_said`)
- `of: rule`(`wargames.ANSWERS_OF`): 학습자 자신의 요청이면 요청의 `path`와 `marker: browse`, Kali 단계 실행이면 `marker: step:<id>`를 받음. 룰 `family`로 범위를 좁힐 수 있음
- `of: rule` 판정: 최근 600초를 수집해 그 요청이나 실행의 ModSecurity 탐지 기록을 모음. CRS 합계 룰(id가 949, 959, 980으로 시작)을 뺀 `ruleId`를 모두 허용 값으로 인정(`lesson.rules_named`). 기록이 없으면 사유 `lesson.check.unrecorded`
- `of: rule_matched`(`rule: <id>`): 같은 탐지 기록에서 그 룰 하나만 보고 `present`나 `absent`를 허용 값으로 정함. 기록된 실행에 탐지가 하나도 없으면 `absent`
- 기록 전 확인의 `kali`에 `settling: true`가 붙음. 도구가 끝났고(`ended`나 `ps`) 마지막 요청 뒤 3초가 안 됐으면 `ending: true`도 붙고, 콘솔은 그동안 5초가 아니라 1초마다 확인
- 기록된 Kali 실행의 탐지 기록이 세션에 이미 있으면 다시 수집하지 않음. 실행은 로그가 `RUN_SETTLED`(15초) 동안 조용해진 뒤에 기록하고, 기록 시점의 수집이 이미 그 로그를 읽었음. 터미널에 그 단계 명령의 종료 줄(`done`)이 보이면 콘솔이 바로, 그 뒤 1초마다 `ended: true`로 확인하고 서버는 `RUN_ENDED_SETTLED`(3초)만 기다림. 종료 줄 없이 온 확인도 Kali 박스에 터미널에 붙은 그 도구 프로세스가 더는 없으면 3초만 기다림(`attacker.typed_tool_running`이 `ps`로 확인). 플랫폼이 띄운 도구는 터미널이 없어 세지 않음
- Kali 확인은 실행 중에는 최근 `RUN_SETTLED`+여유 5초씩 앞뒤(25초)의 기록만 읽고, 그 구간이 조용할 때만 실행 전체를 읽음. 기록한 뒤의 수집과 다시 실행 단계의 수집은 세션 전체나 최근 10분이 아니라 실행의 첫 요청부터 읽음(`_ingest(since=)`)
- `kali` 단계는 기록된 실행이 없어 통과하지 못한 확인을 틀린 시도로 세지 않음

`rules`: 센서의 룰 파일(`GET /api/rules/`)에 방어 설정의 룰 파일에 없는 sid나 내용이 바뀐 sid가 생기면 통과(`lesson.added_rules`, `disable.sids`). 응답에 `added`가 붙습니다.

- `needs: nocase`: 그 룰에 `nocase`나 `i` 플래그를 단 pcre도 있어야 함(`lesson.ignores_case`)
- `match`가 있으면 그 룰이 실제로 경보를 내야 함. 이 세션의 마지막 적용(세션 `RuleSet`의 `applied_at`) 이후 웹사이트 창에서 보낸 요청 중 `match`에 맞는 요청에 그 sid 경보가 있어야 통과
- 실패 사유: `<fail>.unsent`(해당 요청 없음), `lesson.check.unrecorded`(센서가 아직 그 요청을 기록하지 않음), `<fail>.silent`(sid 포함), `<fail>.elsewhere`(sid와 대신 경보가 난 URL 포함)
- 가장 늦은 요청이 끝난 지 `ALERT_ARRIVES`(10초)가 안 됐는데 경보가 없으면 판정하지 않고 `lesson.check.alert_pending`으로 답함. 틀린 시도로 세지 않고, 콘솔이 2초 뒤 같은 방식으로 다시 확인. 10초가 지나도 경보가 없을 때만 위 사유로 실패
- `quiet_on:`은 평범한 요청 URI 목록. 룰의 URI content가 이 중 한 URI에 모두 들어가면(`lesson.alerts_on`) 평범한 검색마다 경보를 낼 룰로 봄. 경보를 읽기 전에 `<fail>.broad`(sid와 처음 걸린 URI 포함)로 바로 실패
- pcre가 있는 룰과 URI content가 없는 룰(`http.header`만 쓰는 룰 등)은 넓은 룰로 판정하지 않음

sid를 읽을 수 없는 룰 줄:

- 활성 줄 중 플랫폼이 읽을 수 있는 `sid:<숫자>`(뒤에 `;`나 `)`)가 없는 줄이 있으면 문법 검사와 적용 모두 그 룰 파일을 거부(`disable.unread`)
- Suricata 8은 `sid:9100001 rev:1;`도 불러옴(2026-11-15 라이브 센서에서 `suricata -T`로 확인). 플랫폼은 이 sid를 인식하지 못해, 확인 단계에서 룰을 추가하지 않았다고 판정하게 됨
- 이때 문법 검사는 Suricata가 파일을 통과시킨 뒤 `{ok: false, unread_sid: true, errors: [해당 줄]}`로 응답

나머지 check:

- `triage`(`judged: customer | attack | all`): 학습자가 옳게 판정하면 통과("시나리오" 절). `judged: verified`는 시나리오 최종 점검이 시작되면 통과
- `sent`: 웹사이트 창에서 보낸 요청이 `match`에 맞으면 통과. `wrong_if` 규칙의 `match`에 걸리면 통과 대신 `loud: true`와 `<text>.wrong.<step>.<says>`(카드의 예시 단어로 검색한 F3 검색 단계)
- `waf_changed`(`removed_target`): 방어 설정이 선언한 예외의 target을 WAF 파일의 어떤 예외도 가리키지 않고, Paranoia Level 줄이 여전히 방어 설정의 단계면 통과
- `waf_changed`에서 Level 줄을 지우거나 바꾸면 `<fail>.paranoia`로 실패. 되살릴 줄(예외를 뺀 방어 설정의 `crs.rendered`)을 담음
- 파일에서 예외가 빠져도 nginx가 그 파일을 다시 읽어야 통과. nginx 워커 중 하나가 파일을 마지막으로 저장한 뒤에 시작됐어야 함(`crs.reloaded_since_written`: 파일 수정 시각과 마스터의 자식 프로세스 시작 시각 비교). `nginx -t`가 실패하면 `&&` 뒤의 reload가 돌지 않아 통과하지 않음. 그동안은 `<fail>.reload`(`loud: true`)
- `click`: check를 호출하면 바로 통과. 따로 확인하는 조건 없음

`replay`: `after`로 지정한 단계를 통과한 뒤 두 조건이 모두 맞으면 통과합니다.

- 공격: `sent` 정규식이면 학습자가 추가한 sid의 경보가 있어야 함. `kali` 케이스면 그 실행의 탐지 기록에 949110이 있고 탈취 데이터가 없어야 함. 공격 쪽 `expect`는 읽지 않음
- `kali` 공격의 실행이 아직 기록 전이면 `lesson.check.kali_settling`과 `kali`를 응답하고 틀린 시도로 세지 않음. 실행을 기록할 때 이미 수집했으므로 949110이 세션에 없을 때만 다시 수집
- 같은 시각 이후의 정상 요청 중 하나 이상이 `expect`의 조건을 모두 만족. `status_class`가 맞고, `alerted_sid: none`이면 추가한 sid의 경보가 없고, `waf_logged: false`면 WAF 기록이 없어야 함
- 사유에 어느 쪽이 빠졌는지 나옴(`lesson.check.replay_attack`, `lesson.check.replay_benign`)
- 정상 요청이 맞지 않으면 그 요청과 어긋난 내용을 함께 알림. 사유는 `lesson.check.replay_benign.status`(2xx 아님), `.alerted`(추가한 sid가 경보를 냄), `.waf_logged`(`views._benign_fault`)

check 판정은 모두 플랫폼에서 `POST /api/sessions/<id>/lesson/steps/<step>/check/`로 합니다.

- 본문: 답, 선택지, 붙여 넣은 표는 `{answer}`. 백그라운드 폴링은 `{poll: true}`
- 이 호출로 `passed`를 기록하고 `{passed, reason, hint, hints, progress}`를 응답
- 추가 필드: `rules` check는 `added`, `kali` check는 `kali`, `loot` check는 `loot`
- 폴링에서 확실한 잘못(정상 replay 요청 실패, 지워진 Paranoia Level 줄, 일부만 붙여 넣은 loot, `wrong_if`에 걸린 `sent`)이 나오면 `loud: true`
- `reason`은 값이 딸린 `strings.html` 키
- 폴링이 아닌 check가 실패하면 오답으로 집계. 오답이 두 번이면 그 단계의 힌트 단계를 올리고 힌트를 기록. 단계형 시나리오에서는 그 대신 시나리오의 다음 힌트를 제안(`scenario_run.stuck`)
- `triage` check는 예외. 학습자가 낸 답이 아니므로 실패해도 오답으로 세지 않음. 실패하면 그 단계의 `passed`를 지움. 통과 표시는 지금 상태를 따름

check는 학습자가 누르지 않아도 실행됩니다.

- `sent`, `triage`, `kali`, `replay`, `waf_changed`: 단계와 탭이 보이고 세션이 열려 있는 동안 5초마다 조용히 폴링
- `triage`는 통과한 뒤에도 현재 단계면 계속 폴링. 실패하면 통과 표시를 거두고 단계를 다시 그림. 경보 판단 하나를 내릴 때마다 도는 check도 조용한 폴링
- 답을 확인하는 동안에도 제출 버튼은 그대로. 그사이 다른 답을 내면 확인이 끝난 뒤 이어서 확인함. 확인하는 동안 입력란을 고쳤거나 다음 답이 기다리면 앞 답의 판정 줄은 띄우지 않음
- 폴링(`{poll: true}`)은 기본 90초(`PATIENCE`)만 기다림. 응답 없는 폴링이 단계를 붙잡지 않음
- 화면은 세션 종료를 확인하려고 30초마다 세션을 다시 읽음
- 응답에 `loud`가 없으면 폴링 결과는 화면에 아무것도 남기지 않음. `loud`가 있으면 오답처럼 사유를 띄우고, replay의 정상 요청 줄은 "확인 중"에서 "문제 있음"으로 바뀜
- `sent`와 `replay`는 웹사이트 창에 단계의 `match`(`replay`는 정상 요청의 `sent`)에 맞는 경로가 나타나고 1.5초가 지났을 때도 실행
- `rules`는 룰 편집기에서 파일을 적용할 때도 실행. `match`가 있는 `rules` 단계는 이때 조용히 실행되고 별도 확인 버튼을 띄움. 학습자는 요청을 보낸 뒤 이 버튼을 누름

통과와 이동:

- 통과하면 그 단계에 `ok` 문장을 띄우고 '다음'을 강조한 채 머묾. '다음'을 누르라는 통과 문장은 없음
- 마지막 단계를 통과하면 레슨 끝 카드로 넘어감. 이 카드는 버튼을 누를 때까지 기다림
- 웹사이트 창 열기 버튼은 창에 다른 페이지(XSS 검색 뒤 남은 403 페이지 등)가 있으면 게시판 첫 화면도 다시 엶. 이후 단계들이 게시판 검색창에서 검색함
- 대상 창이 이미 열려 있는 `click` 단계는 도달하면 바로 통과
- 시나리오 1.1에는 경보 창을 여는 단계가 없음. 경보 창이 열린 채 시작하고, 첫 단계부터 고객 요청을 판정

Kali 단계 카드:

- 실행은 테두리도 케이스 이름도 없는 한 줄. 실행 중 문장과 "Kibana에서 이 실행 시간대 열기"만 있음. "기록된 실행" 라벨 없음
- 단계 문구와 실행 중 문장에 "실행이 끝나면 확인한다"는 말은 없음
- 다음 단계에서는 이 행을 되풀이하지 않음. 이어지는 Kibana 단계의 열기 버튼으로 실행 시간대를 엶. 이 링크는 실행 시간대를 빈 쿼리로 엶
- 화면을 다시 불러오거나 행에 시간대가 없으면(기록을 모으는 중에 '다음'을 누른 경우) Kali check를 폴링해 행을 다시 읽음. 넘어간 뒤 도착한 결과도 반영
- Kali 단계는 실행이 끝나면 폴링으로 자동 통과. 확인 버튼은 더 빨리 확인하고 싶을 때만 씀

Kibana 쿼리와 개발자 도구 답:

- 대상이 Kibana이거나 이후 단계가 Kibana를 여는 단계에서는 답과 함께 Kibana의 쿼리 `query`를 보냄
- `kql`이 있는 check는 그 쿼리가 정규식에 맞지 않으면 통과하지 않음(`<text>.wrong.<step>.kql`)
- 따옴표 안에 와일드카드를 넣은 쿼리(`: "...*..."`, `views.QUOTED_WILDCARD`)는 그보다 먼저 `lesson.check.wrong.kql_quoted`로 실패
- Kibana에서 읽는 기초 레슨 답에는 모두 `kql`이 있음. 구성도·참고·앞 카드에서 짐작한 값으로는 통과할 수 없음
- `leg: upstream` check에서 `not destination : <주소>`에 board.com 자신의 주소를 넣은 쿼리도 `kql` 사유로 실패(`views._excludes_the_site`). 남겨야 할 구간을 빼 버리기 때문
- `dev`(정규식)가 있는 check는 개발자 도구에서 읽는 답. 개발자 도구가 열려 있으면 선택된 요청 행 id를 `dev_request`로 보냄(아니면 `null`). 선택한 행이 없으면 목록에 보이는 행 id들을 `dev_listed`로 함께 보냄
- `dev` 통과 조건: 그 행이 세션에 기록된 요청이고 경로가 `dev`에 맞음. 상태 코드 단계(`of: status`)는 목록의 상태 열에서 읽을 수 있으므로 `dev_listed`의 행이 맞아도 통과. 아니면 `lesson.check.wrong.dev`(`views._dev_read`). 이 거절은 틀린 횟수에 넣지 않음
- `dev` 적용 단계: F2의 메서드, 경로, 상태 코드, 파라미터, 없는 글 단계(정렬 단계는 `match`만). F4의 인코딩 단계. F5의 정렬·오류 단계
- 숫자 뒤에 한두 글자 단위("20점", "1973건")가 붙은 답은 숫자로 읽음(`lesson._unit_dropped`). `%`는 단위로 보지 않음

레슨 끝과 입력 표시:

- 기초 레슨 마지막 단계: "레슨이 끝났습니다."를 띄우고 "다음 레슨: <제목>" 버튼을 누를 때까지 기다림("과정마다 세션 하나")
- 과정의 마지막 레슨(과정 1은 F3, 과정 2는 F6) 뒤: 들은 레슨을 레슨별 통과 단계 수와 함께 카드에 나열. "세션 종료" 버튼으로 세션을 닫음. 점수는 결과 화면에 있으니 싣지 않음
- 단계형 시나리오 마지막 단계: 안내 단계를 마쳤다고 알림(`scenario.note.done`)
- 통과 문장은 마지막 단계에서도 질문 아래 남음
- 오답 문장은 다시 입력하거나 다른 선택지를 누르면 사라짐. Kibana를 읽는 단계의 오답 문장은 Kibana 쿼리가 바뀌면 사라짐
- 순서 고르기는 누른 버튼에 번호를 매겨 표시. 다시 누르면 빠진다는 안내는 질문에 있음
- 참고 칸 열림 상태는 세션·레슨별로 저장(`cr-lesson-reference-<session>-<lesson>`). 새 레슨은 참고가 닫힌 채 열림
- 룰 편집기의 적용 안 한 수정은 localStorage(`cr-rules-draft-<session>`, 기준 버전 포함)에 보관. 다시 불러올 때 복원하고 알림. 적용하면 지움. 기준 버전이 다른 초안은 복원하지 않음
- 오답이면 무엇이 틀렸는지 알림
- 최근 수집(`within`)은 구간의 최신 기록부터 읽고 잘림을 기록하지 않음. sqlmap 케이스 하나만으로 5000건을 넘김

도움말은 단계마다 정해진 순서로 열립니다. "힌트 보기"를 누르거나 오답·실패한 check가 두 번 나오면 다음 수준이 열립니다.

- 기초 레슨: 넛지(`<text>.nudge.<step>`, 어디를 볼지), 그다음 힌트(`<text>.hint.<step>`, 어떻게 읽는지. 정답은 말하지 않음). 3단계(`lesson.SKIP_OFFERED_IN_FOUNDATIONS`)에 이르면 힌트 버튼이 사라짐
- 단계형 시나리오: 정답 단계를 유지(`lesson.ANSWER`, `lesson.SKIP_OFFERED`)
- 누를 때마다 `POST /api/sessions/<id>/lesson/hints/ {step, level: "hint"}`로 단계의 `hint` 단계를 올림
- 처음 한 번은 레슨 정보와 함께 `Session.hints`에 기록(`{lesson, step, level}`, 마이그레이션 0017, 0027)
- 가이드 세션이 아니거나 레슨에 없는 단계·단계값이면 400. 닫힌 세션이면 409
- 한 단계에서 60초가 지나면 힌트 버튼을 강조함(`btn-blue`). 문구는 그대로. 누르기 전에는 아무것도 기록하지 않음
- 기초 레슨 마지막 단계는 혼자 푸는 단계. 강조 표시, 넛지, 힌트 없음
- `result.scenario.helped`(`["hint"]` 또는 없음)가 있으면 메인 화면과 닫힌 세션 화면의 통과·미통과 옆에 "힌트 사용"

건너뛰기:

- 도움말 단계 다음에 붙어 있지 않음. 통과하지 않은 단계에서는 다음 버튼 하나가 `lesson.skip`으로 표시됨
- 누르면 `POST /api/sessions/<id>/lesson/steps/<step>/ {state: skipped}`를 보내고 다음 단계로 진입
- 마지막 단계에서는 건너뜀을 기록하고 레슨 끝 카드를 띄움. 이 카드도 버튼을 누를 때까지 기다림. 단계형 시나리오면 단계를 닫음
- 학습자 대신 입력, 실행, 적용, 인정해 주는 동작은 없음
- 그래서 건너뛴 단계의 기록을 읽는 뒤 단계는 학습자가 그 단계를 수행하거나 함께 건너뛸 때까지 답할 수 없음. 보내지 않은 요청에 관한 답, 실행하지 않은 공격의 탈취 데이터가 그런 경우

레슨은 첫 단계가 지정한 창(`opens`)으로 열립니다. 콘솔 코드에는 레슨 단계 이름도 CSS 선택자도 없습니다. 단계가 가리킬 곳은 `scenario.yaml`의 `point`에 로케이터로 적고, 필요한 창은 `opens`로 적습니다. 이 강조 표시가 코치입니다.

로케이터 종류:

- `panel`: 콘솔 요소. 사이트 주소창, 룰 편집기, 목표 행 등
- `map`: `node`, `label: [host, 망]`, `zone`. `zone`의 `service`, `database`, `internet`은 서버에서 그 세션의 망 이름으로 풂
- `map`의 `{locate}`에는 `console/templates/console/map.html`이 `postMessage`로 답함. `node`는 장비 아이콘과 그 아래 글자. 링크의 주소 라벨은 선의 장비 쪽 끝에 있어 테두리 밖
- `map`의 답: 사각형, 모든 영역 도형 사각형(`zones`), 노드·인터페이스 라벨·영역 캡션 사각형(`text`. 말풍선이 이들을 가리지 않게 함)
- 이 페이지는 `{fit}`를 받으면 다시 맞춤. 첫 맞춤 뒤 `{map: "drawn"}`, 이후 맞출 때마다 `{map: "fitted"}`
- `site`: 출처가 다른 사이트 프레임 안의 선택자. nginx가 주입한 스크립트가 응답
- `dev`: 개발자 도구의 `data-coach` 이름. 토글, 매칭된 행, 탭, 줄 등
- `kibana`: 출처가 같은 Kibana 프레임 안의 대상. 형태는 아래 목록
- `term`: `{pane: kali | waf, match}`. xterm 버퍼에서 맞는 줄을 가리킴

`kibana` 로케이터 형태:

- `query`
- `hits`: 결과가 없으면 대신 `discoverNoResults`를 가리킴(그 경우용 단계). 테두리는 건수에만
- `doc: <field>`: 문서 플라이아웃의 필드 행. 플라이아웃의 필드 필터로 행을 화면에 띄움
- `sidebar: <field>`: 필드 팝오버가 열려 있으면 팝오버의 "N개 레코드에서 계산" 줄(`dscFieldStats-statsFooter`), 없으면 Top values
- 어느 형태에든 `kql: <pattern>`을 붙이면 학습자 쿼리가 맞을 때까지 쿼리 입력창을 가리킴
- 단계 check에 `leg`이 있으면 그 구간 행의 펼치기 버튼을 가리킴. 다른 이벤트가 열려 있으면 플라이아웃의 화살표도 가리킴
- 구간 행: 출발지가 다른 행의 목적지인 행, 또는 그 반대
- 구간 행을 찾지 못하거나 열린 문서의 순서를 모르면 값 대신 필드 필터를 가리킴
- `point`에 `keep: true`가 있으면 도착한 뒤에도 플라이아웃을 열어 둠

`term` 로케이터:

- 선택 항목 `done` 패턴이 마지막 입력 명령 뒤에 출력되면 테두리가 단계의 확인 버튼으로 옮겨 감
- 단, 그 명령에 단계 명령의 낱말이 따옴표를 빼고 모두 들어 있을 때만. 앞 단계에서 끝난 실행을 이 단계 완료로 표시하지 않음
- 단계 명령이 실행되는 동안에는 실행 카드의 "아직 실행 중" 줄만 보임. "기록을 모으는 중" 상태 줄과 앞서 나온 빨간 "실행 기록 없음"은 지움
- 빈 프롬프트를 가리키는 말풍선은 프롬프트 줄 아래에 둠. 명령 입력 자리를 가리지 않음

두 단계 로케이터:

- `until: sent`: 첫 대상을 가리키다가 요청을 보내면 `then`으로 넘어감(정렬 선택 상자, 그다음 페이로드 줄)
- `until: applied`: 단계에서 추가한 룰이 적용되고 편집기에 미적용 변경이 없을 때까지 첫 대상
- `until: dev_open`: 개발자 도구가 열릴 때까지 첫 대상. F4 탐색 단계는 카드가 검색 전에 개발자 도구를 열라고 하므로 개발자 도구 버튼, 그다음 검색창
- 적용하면 콘솔이 새로 쓴 줄의 sid를 바로 추가된 것으로 표시. 테두리는 check 응답을 기다리지 않고 적용 버튼을 떠남
- `then` 안에 `until`과 `then`을 중첩할 수 있음. F4 룰 단계는 룰 편집기, 사이트 검색창, 확인 버튼(`#step-act`) 순

강조 표시 렌더링:

- 창만 어둡게 하고(`pointer-events: none`) 대상에 기본 색 테두리를 두름. 옆에 한 줄 콜아웃(`<text>.callout.<step>`, 두 번째 대상 `.callout.<step>.then`, 세 번째 `.then.then`)
- 2026-11-15부터 레슨 단계의 콜아웃은 테두리만으로 할 일이 드러나지 않는 곳에만 있음: 구간 행 펼치기 버튼, 플라이아웃의 필드, 열린 문서 플라이아웃 닫기(`covered`), 다음 문서로 넘기기(`other`), 구간별로 확인할 이벤트(`verify.<leg>`), Kali 확인 버튼
- 콜아웃 없는 곳: 개발자 도구 열기, 행 고르기, 개발자 도구 탭, 쿼리 작성·실행, 구간 없는 행 펼치기, 추가할 룰 줄, 적용 누르기. 이런 단계는 테두리만 그림
- 강조한 대상의 이름만 말하는 콜아웃(검색창, kali, DMZ)은 쓰지 않음
- 콜아웃은 창 안에서 뒤집거나 밀어서 배치. 대상, 왼쪽 메뉴, 툴바, 노트를 덮지 않음
- 사이트 프레임이나 Kibana 프레임이 알려 주는 대상 주변 글자와 컨트롤도 덮지 않음. Kibana는 테두리에서 220px 안의 글자와 컨트롤(문서 플라이아웃에 가려진 것 제외)
- 한 줄로 놓을 자리가 없으면 두세 줄로 줄바꿈
- 플라이아웃 단계(다음 이벤트 화살표)는 플라이아웃 안부터 찾음
- 대상이 노트 카드 안에 있으면 콜아웃은 카드 옆 창에 둠
- 지시선은 글자를 가로지르지 않음. 콜아웃이 테두리에서 48px 안에 있으면 그리지 않음
- 구성도 위 테두리는 노드 옆 구성도 글자에 닿지 않을 때까지 여백을 줄임(`clearOfText`). 가장 작으면 노드 자체의 사각형
- 기초 레슨의 힌트는 늘 레슨 자신의 `<text>.nudge.<step>`, `.hint.<step>`. 단계형 시나리오에서 그 문구가 없고 로케이터가 있는 단계는 "표시한 곳을 확인해 보세요."(`lesson.hint.point`)
- 단계의 창이 안 보이면 단계 카드에 "<창> 열기" 버튼(`lesson.open.<pane>`). 버튼 이름에 대상이 드러나므로 강조만 하고 콜아웃은 없음. 마지막 단계에는 강조도 없음
- 약 2초(120프레임) 동안 대상을 찾지 못하면 브라우저 콘솔에만 기록. 카드 문구는 웹사이트 창 대상이 홈으로 돌아간 경우의 `lesson.site.missing` 하나
- 구성도는 창 크기가 마지막으로 맞춘 크기와 다를 때만 다시 맞춤(창을 열 때, 크기가 바뀔 때). 단계가 바뀌거나 마지막 단계에 이르는 것만으로는 다시 그리지 않음

모든 기초 레슨과 단계형 시나리오 단계의 `point`가 렌더링된 콘솔에서 찾아지는지는 `test_every_point_a_foundation_or_scenario_step_names_resolves_on_the_blue_console`로 확인합니다.

룰 편집기(`#lesson-rules`, 결정 D3)는 블루팀 콘솔의 IDS 룰 창에 있습니다. `detection`이나 `unknown` 유형 시나리오, 그리고 단계가 룰 창을 열거나 `rules` check를 쓰는 레슨에서 `rulesPane()`으로 띄웁니다.

- 읽기: `GET /api/rules/?session=<id>`
- 검사: `POST /api/rules/validate/`. 쓰기: 불러온 버전을 기준으로 `POST /api/rules/apply/`
- 검사 응답의 `errors`: 거부한 모든 센서의 출력에서 Suricata `Error`가 든 줄. `output`: 그런 줄이 가장 많은 거부 센서의 출력
- 거부한 센서는 없지만 sid를 읽을 수 없는 룰이 있으면 `unread_sid: true`. `errors`에는 해당 룰 줄, `output`은 빈 문자열
- 센서는 콘솔 로그를 켠 Suricata 이미지라 `-T` 오류 줄을 출력

### 기초 레슨 F1-F6과 두 과정

설계는 `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`의 P2 단계입니다. 2026-10-18에 공격과 방어를 함께 다루는 레슨으로 다시 만들었습니다(`docs/DECISIONS.md`, "Foundations rebuilt as integrated attack and defence lessons").

board의 `scenario.yaml`에 `foundations:` 목록을 선언합니다. discovery 시점에 검사하며, id는 기초 레슨과 시나리오를 통틀어 유일해야 합니다(`wargames.checked_groups`). 가르치는 일은 기초 레슨이 맡습니다. 단계형 시나리오 1.1과 3.1도 같은 엔진으로 단계를 실행합니다.

`courses:`도 선언합니다(`wargames.checked_courses`). 모든 기초 레슨은 정확히 한 과정에 속합니다. 과정마다 `id`, 문자열 키 `text`, `reference` 카드가 있습니다.

- 과정 `c1` "로그 분석 기초": f1-f3. 훈련 환경을 읽기만 함(defense `full`, 룰·Kali·WAF 변경 없음)
- 과정 `c2` "공격 탐지 실습": f4-f6. 훈련 환경을 바꿈(`docs/DECISIONS.md`, "The six foundations become two courses")
- 과정 1의 단계는 학습자 자신의 검색어나 마커로 자기 요청을 찾음. 훈련 환경이 새것이거나 다른 트래픽이 없다는 전제에 기대지 않음

과정 API와 화면:

- `GET /api/wargames/`: `courses`(`id`, `title`, `lessons`, `scored`) 나열. 메인 페이지는 과정마다 구역을 나눠 레슨을 보여 줌
- `scored`(`wargames._course_scored`): `kali`나 `replay` check가 있는 과정에서 true. 그 과정 레슨 세션의 점수 표시 여부를 정함
- `GET /api/sessions/<id>/`: `lesson_course`(`id`, `text`, `lessons`, `reference`)
- 과정의 첫 레슨은 어느 단계에도 진입하지 않은 동안 창 위에 과정 안내(`<course>.brief`와 접힌 참고 카드)를 띄움
- 시작을 누르면 첫 단계에 진입(`POST .../steps/<id>/ {state: reached}`). 에이전트는 이 요청을 바로 보냄
- 과정 2 안내에는 주소가 세션마다 다를 수 있다는 말이 있음
- 레일의 참고 버튼을 누르면 왼쪽 열이 열림. 과정 카드와 레슨의 `reference:` 카드(`lesson.ref.<id>.title`, `.body`, `.rows`)가 보임
- `addresses` 카드는 `GET .../lesson/addresses/`로 채움. F1은 주소를 묻는 레슨이라 주소 카드가 없음

기초 레슨 함수와 카드:

- `wargames.foundations()`: 기초 레슨을 `order` 순으로 나열
- `wargames.lesson(lesson_id=...)`: 기초 레슨이나 단계가 있는 시나리오를 찾음. 그 밖의 id는 거부. 기초 레슨에는 `group: foundations`를 붙임
- `GET /api/wargames/`의 `foundations`(`wargames._foundation_card`): `id`, `order`, `title` 문자열 키, `minutes`, `level`, `defense`, `prerequisites`, 단계 수, `step_ids`, `changes_waf`
- 메인 페이지는 기초 레슨을 레슨 목록 맨 앞에 과정별로 묶어 두고, 레슨마다 번호, 제목, 시작 버튼(그 레슨을 안내와 함께 엶)만 보여 줌. `minutes`, `level`은 API에만 있음

시드 재생:

- 모든 레슨은 `board-normal-search`를 시드로 재생
- 첫 레슨은 열 때 재생. 뒤의 레슨은 학습자가 그 레슨에서 처음 통과하거나, 건너뛰거나, 힌트를 볼 때 재생(`views._seed_once_worked`, 결과 화면의 `begun()`과 같은 기준)
- 콘솔이 넘긴 뒤 학습자가 손대지 않은 레슨에는 정상 케이스가 추가되지 않음
- 이 시드는 정상 케이스로 탐지 결과에 들어감(`views._replayed`가 정상 `meta.seed` 케이스를 남김). 닫힌 레슨 세션에 정상 통과가 생김
- 레슨 세션에서는 `no_benign`과 `no_marker`를 표시하지 않음

아래는 레슨별 defense, 시작 창, 학습자가 하는 일, 답을 읽는 곳입니다.

**f1 구성도 읽기**(`lesson.map`). defense `full`, 구성도 창에서 시작.

- kali와 board.com의 주소를 읽음
- 웹 요청이 거치는 호스트를 순서대로 고름(`path`, 출발지 `kali`. 고객 주소도 kali에 붙어 있음)
- DMZ 네트워크를 읽고, 로그 서버의 IP 주소를 답함
- 혼자 푸는 단계: waf의 주소. 호스트가 어느 영역에 있는지는 묻지 않음
- 답은 세션의 학습자용 구성도에서 읽음(`views._range_fact`: `topology.learner`를 거친 `topology.address`, `topology.subnet`, `topology.route`)
  - `address`: 링크 라벨의 주소. 프리픽스 길이는 있어도 없어도 됨. 고르는 망은 `subnet`과 같음. board.com은 waf와 함께 붙은 망의 주소, log-server는 관제망 주소
  - `subnet`: 단계의 `zone`(`service`는 `estate`)에 호스트가 붙어 있으면 그 망, 아니면 호스트가 붙은 첫 영역(인터넷 구간, DMZ, 웹 서버 구간, DB존 순)의 네트워크. F1 `dmz`는 waf의 `estate` 대역
  - `path`: 단계의 `from`(기본 `kali`), 구성도에 있는 경유 역할, 사이트 순(`kali > router > waf > board.com`)

**f2 개발자 도구로 HTTP 요청 읽기**(`lesson.http`). defense `full`, 웹사이트 창에서 시작.

- 게시판 검색창으로 검색한 뒤 네트워크 패널에서 메서드, 파라미터, 경로, 상태 코드를 읽음
- 게시판 정렬 기능이 쓰는 파라미터를 찾음
- 혼자 푸는 단계: `/posts/9999/`의 상태 코드. 카드와 HTTP 참고 어디에도 그 글이 없다거나 404의 뜻은 나오지 않음
- 답은 웹사이트 창에서 보낸 요청 기록에서 읽음: `method`, `parameter`, `path`, `status`
- `path`는 요청 URL에 적힌 그대로. 답에 호스트나 쿼리가 들어가거나 끝의 /가 빠지면 `wrong_if`로 안내

**f3 Kibana에서 내 요청 찾기**(`lesson.logs`). defense `full`, 웹사이트 창에서 시작.

- 영문자와 숫자 4자 이상으로 된 자기만의 단어로 검색. 예시 단어 `kim0413`은 검색 단계에서 인정하지 않음
- Kibana에 `url : *단어*`를 입력. 카드마다 쿼리를 다시 적어 주고, 화면의 열 이름을 그대로 써서 묻는 것:
  - Kibana에 나오는 건수. 센서가 WAF 뒤만 보므로 그 단어로 한 검색 가운데 waf가 board.com에 넘긴 요청 수
  - 주소창으로 그 단어를 글 번호 자리에 넣어 없는 글(`/posts/<단어>/`)을 요청(`missing`, `sent` check). 이 요청도 url에 단어가 들어가 404로 기록됨
  - `and`와 `not`으로 작성한 쿼리(`url`에 내 단어가 있고 `not status : 404`)의 건수(`upstream`)
  - 그 쿼리로 남은 행의 `source_ip`(waf 자신의 주소)
- 건수 단계의 check에는 Kibana 쿼리가 맞아야 하는 정규식 `kql`이 있음. 쿼리가 맞지 않으면 숫자와 상관없이 오답(`lesson.logs.wrong.upstream.kql`)
- 앞 건수 단계의 통과 문장은 url 쿼리로 내 로그를 찾았다는 말만 함. 구간마다 몇 줄이 남는지는 말하지 않음
- 첫 건수 단계 check에도 `kql`(`url` 조건)이 있음. 답이 참고의 주소 표에 있는 출발지 단계에도 있음
- X-Forwarded-For 단계의 `kql`은 url 조건에 더해 `request_header.x_forwarded_for : *` 조건을 요구. 이 조건이 없으면 앞 단계의 url 쿼리만으로 통과해 버림
- 혼자 푸는 단계: 그 행의 `request_header.x_forwarded_for`(customers 주소)를 Document 창에서 읽음. 웹사이트 창이 customers 자리에서 접속한다는 사실은 이 단계의 통과 문장에서 처음 나옴
- 답은 기록된 센서 http 이벤트에서 구간별로 읽음(`sensor_source`, `forwarded_for`)
  - `dest_ip`가 board.com 주소면 `upstream`(waf가 넘긴 요청), 아니면 `inbound`(waf에 도착한 요청). `leg: both`는 두 구간 모두. 센서가 WAF 뒤만 보므로 F3의 단계는 모두 `leg: upstream`
  - `hits`: 레슨(또는 세션) 시작 이후, 학습자의 가장 최근 검색 단어가 url에 든 해당 구간 http 이벤트 수. check에 `unless_status`가 있으면 그 상태 코드의 이벤트는 세지 않음(`upstream`은 `unless_status: 404`)

**f4 XSS 요청 차단과 IDS 룰 작성**(`lesson.xss`). defense `xss-gap`, 웹사이트 창에서 시작.

학습자가 하는 일:

1. 첫 카드에서 개발자 도구를 엶. 네트워크 패널은 열려 있는 동안 받은 요청만 보여 줌
2. `<script>alert(1)</script>`를 보내고, 개발자 도구의 요청 URL에서 `<`가 무엇으로 바뀌었는지(`%3C`) 읽음. 주소창에는 `<`로 보임. WAF가 기록만 하고 통과시키므로 화면에는 검색 결과가 뜨고, 상태 코드는 묻지 않음
3. 탐지한 룰 하나와 Total Score를 읽음
4. 대소문자를 섞은 요청을 보내 Kibana에서 그 Total Score를 읽음. CRS 참고에는 CRS가 대소문자를 가리지 않는다는 설명이 없음
5. 두 요청에 IDS 경보가 있었는지 답함
6. URI의 `<script`를 잡는 룰을 작성·적용하고, `<script>alert(1)</script>`를 검색한 뒤 확인 버튼을 누름. 그 룰이 이 검색에 경보를 냈을 때만 통과
7. Kibana에서 그 경보의 `destination`을 읽음. 답은 board.com의 web 주소. 센서는 WAF 뒤에서 WAF가 넘긴 요청만 봄
8. 대소문자를 섞은 요청이 빠져나가는 것을 확인하고, `nocase`를 붙이고 `rev`를 올림
9. 혼자 푸는 단계: 대소문자를 섞은 요청과 일반 검색을 다시 보냄. 일반 검색에 내 룰이 경보를 내면 바로 알림(`lesson.check.replay_benign.alerted`)

레슨 장치:

- Suricata 참고 카드는 완성된 룰 대신 대괄호로 빈칸을 둔 룰 형태만 보여 줌. Kibana url의 `%3C`를 어떤 문자열로 찾는지는 알려 주지 않음
- Kibana 단계는 학습자 쿼리가 WAF 로그와 script(또는 alert)를 지정할 때까지 쿼리 입력창만 가리킴. 그 check에도 같은 `kql`이 걸려 있음
- `match: '<script'`가 붙은 `rules` 단계와 `nocase` 단계에는 `quiet_on`(평범한 검색 두 개)이 있음. `content:"/search/"`처럼 모든 검색에 경보를 내는 룰은 사유와 함께 실패

답을 읽는 곳:

- `escaped`(`char: "<"`): 기록된 쿼리에 그 문자의 퍼센트 인코딩(`%3C`)이 있으면 그 값
- `rule`: 요청의 ModSecurity 룰 id. 949·959·980으로 시작하는 판정 룰은 제외(`lesson.rules_named`)
- `anomaly_total`: 요청 시간대 ModSecurity 메시지의 `Total Score: N`. 답은 `N`, `Total Score: N`, `(Total Score: N)` 모두 인정
- `alerted`: 기록 시간대의 Suricata 경보 중 url이 그 기록의 url과 같은 것이 있는지
- `alerted_destination`(학습자가 추가한 룰이 낸 경보의 `dest_ip`), `alerted_sid_present`: 같은 경보를 `lesson.added_rules`와 대조(`views._alerts_for`)
- url이 없는 경보는 browse 마커가 있을 때 셈. 마커만으로 맞추면 공격 몇 초 뒤 보낸 일반 검색이 공격 경보를 뒤집어써서 replay의 일반 검색이 통과하지 못함
- `match: '<script'`가 붙은 `rules`, `needs: nocase`가 붙은 `rules`
- `needs: nocase` 단계는 세션에서 마지막으로 적용한, 대소문자를 구분하던 판보다 룰의 `rev`가 커야 통과(`lesson.raised_rev`, 아니면 `lesson.xss.fail.nocase.rev`). 처음부터 `nocase`로 쓴 룰은 올릴 판이 없음
- `replay`

**f5 sort 파라미터 SQL Injection 분석**(`lesson.sqli`). defense `full`, 웹사이트 창에서 시작.

학습자가 하는 일:

1. sort 값을 읽음
2. 주소창에서 `)`를 붙여 상태 코드를 확인하고, WAF 룰이 탐지했는지 답함
3. Kali 창에 sqlmap을 입력하고 판정 결과를 읽음
4. 실행이 남긴 WAF 기록 수를 읽음. source_ip Top values의 "Calculated from N records"나 Documents 건수. 출발지 자체는 구성도에 있는 kali 주소
5. 스캐너를 식별한 룰을 읽음
6. `--random-agent`를 붙여 다시 실행
7. 혼자 푸는 단계: 재실행 기록의 WAF 로그에 913100이 있는지

레슨 장치:

- 기록 수 단계의 `kql`은 WAF 조건과 `source_ip` 조건을 함께 요구. 앞 단계의 쿼리로는 안 되고 이 단계의 쿼리를 직접 작성해야 함
- 스캐너 룰의 답을 미리 보여 주지 않도록 CRS 참고에서 913 계열 줄을, 혼자 푸는 단계 제목에서 913100을 뺌
- Kibana에서 읽는 답에는 모두 `kql`이 있음

답을 읽는 곳:

- `param_value`, `status`
- `waf_detected`: 요청의 ModSecurity 탐지 기록. 500은 룰 없이 기록되므로 탐지가 아님
- `sqlmap_found`: `attacker.sqlmap_found`로 박스의 `<home>/.local/share/sqlmap/output/<host>/log`에 `Parameter:` 줄이 있는지 확인
- `run_records`: 실행의 Kibana 조회 기간에 든 ModSecurity 기록 수, 또는 실행 마커가 붙은 기록 수. 주소나 비율을 입력하면 wrong_if로 건수를 입력하라고 안내
- `rule`(`marker: step:<id>`, `family: "913"`): 스캐너 룰
- `rule_matched`(`rule: "913100"`): 재실행 기록 기준. 새 User-Agent에 더는 매칭되지 않으면 `absent`

**f6 넓은 예외 처리로 미탐 확인하기**(`lesson.miss`). defense `overbroad`, WAF 창에서 시작.

학습자가 하는 일:

1. 예외 파일을 grep해 빠진 파라미터를 찾음
2. sqlmap으로 계정을 덤프해 표를 붙여 넣음
3. 어느 엔진이 경보를 냈는지 답함
4. 실행이 WAF 로그에 남긴 status 500 기록 수를 답함. 이 기록의 rule_id는 `-`(기록은 됐지만 매칭된 룰 없음)
5. 관리자 목표가 탐지됐을 때의 감점을 답함
6. 예외를 지우고 nginx를 reload
7. 혼자 푸는 단계: 덤프를 다시 실행하고 정렬을 한 번 바꿈

답을 읽는 곳:

- `excluded_target`: 적용 중인 WAF 파일의 파라미터 이름(`sort`). `ARGS:sort`로 답하면 `lesson.miss.wrong.excluded.prefix`
- `loot`: 세션 스냅숏과 대조
- `alerted_by`: 실행의 탐지 기록으로 없음, IDS만, WAF만, 둘 다를 구분
- `server_errors`: Kibana가 여는 조회 기간의 WAF(ModSecurity) 로그 중 status 500 기록 수(`lesson.server_errors`). sqlmap도 실행 끝에 같은 수를 출력하고, 통과 문장에서 두 값을 맞춰 보라고 함
- 출발지 IP는 묻지 않음. kali 주소라 구성도에 있고 F5에서 이미 물었음. rule_id도 앞 단계에서 `-`의 뜻을 알려 줬으므로 묻지 않음
- `detected_penalty`(`objective:`): 그 목표가 탐지됐을 때의 감점(난이도 ×1). 값은 `wargames.objectives`의 등급에서 읽음. 채점하지 않는 시나리오에서는 비어 있음
- `detected_penalty`의 통과 문장은 통과 시점의 목표 행에 따라 다름(`lesson.miss.ok.cost.undetected`, `.detected`, `.kept`, `views._outcome`). 관리자 계정이 탈취되지 않았는데 8점이 감점됐다고 말하지 않음
- `waf_changed`: Paranoia Level 줄도 그대로 남아 있어야 함. 카드에서 그 줄은 두라고 안내
- `replay`: 재실행의 탐지 기록에 949110이 있고 탈취 데이터가 없는지, 일반 정렬이 2xx이면서 WAF 기록이 없는지

방어 설정 `xss-gap`과 `overbroad`:

- `xss-gap`: CRS paranoia level 1, DetectionOnly(기록만 하고 차단하지 않음) + `no-xss.rules`(`local.rules`에서 sid 9000003을 뺀 파일)
- `overbroad`: level 1 + `no-uri-sqli.rules` + 예외 `{tag: OWASP_CRS, target: "ARGS:sort"}`
- `overbroad`의 예외는 WAF 파일에 `SecAction "id:10001,phase:1,pass,nolog,ctl:ruleRemoveTargetByTag=OWASP_CRS;ARGS:sort"`로 들어감. 그래서 CRS 룰 전체가 `sort`를 검사하지 않음

F6의 sqlmap 명령에는 `--skip-waf`를 붙입니다. 없으면 sqlmap이 WAF 존재를 확인하려고 보내는 요청 하나가 IDS 9000003, 9000004와 CRS 룰 하나에 걸립니다. 그러면 실행이 탐지된 것으로 집계됩니다.

기초 레슨 질문에는 `accept` 목록이 없습니다. 단계형 시나리오 3.1의 선택형 단계 하나만 `accept` 목록을 씁니다.

**과정마다 세션 하나.** `POST /api/sessions/<id>/lesson/ {"lesson": "<id>"}`는 열린 가이드 세션을 그 자리에서 다른 기초 레슨으로 바꿉니다.

- 콘솔의 다음 레슨은 세션의 과정 안에서만 이어짐(`views._next_lesson`). 과정 요약에도 그 과정의 레슨만 나옴
- 과정 1은 `course.logs.done`, 과정 2는 `course.attack.done`으로 끝남. 둘 다 마지막 레슨이 끝났다고 알림. 과정 1 문구는 과정 2도 소개
- 과정 2의 점수는 결과 화면에서 봄

전환 시 동작:

- 요청한 레슨이 지금 레슨이면 아무것도 하지 않음
- 옮기기 전의 WAF를 스냅숏으로 남김(`waf_snapshots[].lesson`)
- 레슨이 선언한 방어 설정이 `Session.defense`와 다르면 레슨의 CRS 설정을 씀(`PUT /waf/`와 같은 `crs.apply`). 센서 룰 파일은 방어 설정의 룰 파일이 바뀔 때만 다시 넣음
- `Session.lesson`과 `Session.defense` 갱신
- `Session.lessons`에 `{id, started_at}` 추가(마이그레이션 0027). 첫 항목은 기초 레슨을 열 때 씀
- 스탬프 프록시의 라벨을 지움
- 레슨의 `cases`는 이 시점에 재생하지 않음. 학습자가 그 레슨에서 처음 통과하거나, 건너뛰거나, 힌트를 볼 때 재생
- 세션 상세를 응답

닫힌 세션, 시나리오 세션, 가이드 없는 세션은 409, 기초 레슨이 아닌 id는 400으로 거부합니다.

상세에 들어가는 항목:

- `lessons`
- `next_lesson`: 세션 과정 안에서 `order` 순으로 다음 기초 레슨의 `{id, text}`. 과정의 마지막 레슨 뒤에는 null
- `course`: 들은 레슨별 `[{id, text, steps, passed, skipped, hints, retried}]`. `retried`는 틀린 뒤 통과한 단계 수. 둘 중 하나를 고르는 문항에서 다른 쪽을 다시 고른 경우도 결과 화면에 남음

콘솔은 다음 레슨을 제안만 합니다.

- 기초 레슨의 마지막 단계를 통과하거나 건너뛰면 카드에 "레슨이 끝났습니다."와 "다음 레슨: <제목>" 버튼이 나옴
- 자동으로 넘어가지 않음. 버튼을 누르면 전환을 요청하고 화면을 다시 불러와 새 레슨을 엶
- 과정의 마지막 레슨 뒤에는 들은 레슨을 세션의 `course` 행에서 읽어 "N개 단계 중 n개 통과"와 함께 카드에 나열(`/api/wargames/`는 읽지 않음). 체크 표시 없음. 단계를 모두 건너뛴 레슨은 0
- 그 과정의 레슨을 모두 들었으면 카드 제목은 과정 제목, 문장은 과정 마침 문장(`<course>.done`). 아니면 "레슨이 끝났습니다."
- "직접 해 보기" 카드는 단계 카드 바로 아래
- "세션 종료" 버튼은 세션 화면과 같은 종료 확인(`session.close.consequence`)을 거친 뒤 수집하고 `POST /close/`로 닫고 세션 화면을 엶
- `scored`가 아닌 과정(훈련 환경을 읽기만 하는 과정 1)의 레슨 세션은 점수를 표시하지 않음. 목표, 탐지, 요청별 표, 탈취된 목표 수가 없고, 어떤 검색이 탐지 결과에서 빠지는지 설명하는 문장도 없음
- 세션 화면의 레슨 카드: 레슨별로 통과한 단계(와 다시 시도한 단계). Kali 실행과 F4의 웹사이트 창 XSS 케이스마다 "레슨 n · m단계"
- "다시 시작": 학습자가 손댄 첫 레슨(화면의 `begun()`: 통과, 건너뜀, 힌트가 있거나 세션을 연 레슨)을 그 레슨의 방어 설정으로 엶

레슨 사이에 대상 시스템 데이터는 초기화하지 않습니다. board 목표는 유출만 판정합니다(세션 시작 스냅숏과 탈취 데이터 대조). 레슨은 대상 시스템 데이터를 바꾸지 않습니다. 방어 설정은 다음 레슨의 것이 다르면 바뀝니다(F1~F3 `full`, F4 `xss-gap`, F5 `full`, F6 `overbroad`). CRS 설정을 다시 쓰고, 룰 파일이 다르면 센서 룰 파일도 다시 넣으므로 F4에서 학습자가 쓴 IDS 룰은 F5로 옮기면 사라집니다.

레슨은 시작 이후에 일어난 일만 판정합니다(`views._lesson_started`. 항목이 둘 이상이면 `Session.lessons`의 마지막 항목).

- `sent` check: 시작 이후 웹사이트 창에서 보낸 요청만 집계
- `rule` 답: 시작 이후 ModSecurity 기록만 집계
- `kali` check: 단계의 `reached`와 레슨 시작 중 늦은 시각부터 센서와 WAF 기록을 읽음
- `lost_points`: 시작 이후 탈취된 목표만 집계
- Kibana 링크도 시작 시각부터 엶
- 단계 기록은 레슨별로 따로 둠. F2의 `search`를 통과해도 F3의 `search`는 통과되지 않음

학습자 자신의 행동을 추적하는 check는 세 가지입니다.

`sent`: 웹사이트 창이 보관한 요청 중 디코딩한 경로와 쿼리가 단계의 `match` 정규식에 맞는 요청이 있으면 통과.

`kali`: 케이스 파일의 도구 케이스를 지정합니다.

- 학습자가 단계에 진입하면 마커를 만들어 스탬프 프록시의 `/var/lib/session/active`에 씀. 레슨 전환과 세션 종료 때 삭제
- 학습자가 Kali 창에 입력한 명령은 Kali의 `http_proxy`를 거치며 마커가 붙어 나감
- 단계의 `command`는 입력할 문구일 뿐
- 센서의 http 이벤트나 ModSecurity 기록에 마커와 도구의 user agent가 함께 있으면 통과(`views._sent_by`). ModSecurity 기록은 트랜잭션 요청 헤더의 `X-Request-ID`로 마커를, `User-Agent`로 user agent를 읽음. WAF가 막아 센서까지 가지 않은 요청도 셈. `--random-agent`용으로 `ua: any`를 주면 user agent는 보지 않음
- 통과하면 이 실행을 일반 악성 케이스로 기록(`meta.kali`, `meta.lesson`, 재생 표시 없음). 다른 레드팀 행동처럼 두 점수에 모두 반영. 이어서 세션을 수집(ingest)
- 학습자가 `http_proxy`를 지우면 요청이 마커 없이 나가 통과하지 못함

`loot`: 붙여 넣은 표(`tools.dumped`, 또는 `name:hash` 줄과 `| name | hash |` 줄)를 `POST /loot/`와 같은 방식으로 인정하고 kali 케이스에 귀속합니다.

- 일치한 계정은 `_credit_loot`가 귀속 케이스에 남김(`meta.loot`)
- 일치한 계정이 세션 스냅숏의 계정을 모두 덮어야 통과
- 모자라면 일치 수와 전체 수를 담은 `<fail>.partial`로 실패. 입력 칸은 열어 두므로 나머지를 다시 붙여 넣으면 됨
- 일부만 붙여 넣어도 일치한 만큼은 인정. 목표 판정은 대상 시스템 데이터를 따르고, 이 단계는 표 전체를 요구할 뿐

답으로 읽을 수 있는 값입니다. 그 밖의 값은 discovery 시점에 `wargames.read_from_record`에서 거부합니다.

- `of:`가 훈련 환경 사실: `address`, `subnet`, `path`, `excluded_target`, `lost_points`, `detected_penalty`. `lost_points`는 지금 쓰는 단계가 없음
- `of:`가 요청 사실이고, `about:`이 `match`가 있는 단계를 가리키거나 단계 자체에 `match`가 있음(그 단계와 맞는 가장 최근 웹사이트 창 기록을 읽음): `status`, `method`, `path`, `parameter`, `param_value`, `escaped`, `sensor_source`, `forwarded_for`, `waf_detected`, `anomaly_total`, `alerted`, `alerted_destination`, `alerted_sid_present`, `hits`
- `of:`가 Kali 사실이고 `about:`이 `kali` 단계를 가리킴: `sqlmap_found`, `run_records`(실행의 WAF 기록 수), `alerted_by`, `server_errors`(실행의 500 기록)
- 요청의 `path`나 `step:` 마커와 함께 쓰는 `rule`(위)
- `rule_matched`: `rule:`과 `step:` 마커가 있어야 함

## 점수 계산 방식

주 점수는 레드팀의 공격 성공입니다. 성공 여부는 대상 시스템의 데이터로 판정합니다. 이 데이터는 탐지 장비에 보이지 않는 경로로 읽습니다.

**board 목표.** `loot_verified` 방식입니다. 레드팀이 탈취한 해시를 증거로 제출합니다. 세션 시작 시점의 계정 해시와 같으면 성공입니다.

- 비밀은 `wargames/board/objectives.yaml`에 정의. `/internal/auth-users`로 읽는 `auth_user`의 사용자 이름·비밀번호 컬럼
- 등급: 아무 해시 1개(난이도 2), `admin` 계정의 해시(4), 전체 계정의 해시(5)
- 제출: 레드팀 콘솔의 '탈취한 해시 제출' 패널에서 `POST /api/sessions/<id>/loot/`. 이 패널은 `loot_verified` 시나리오에만 있음
- 인정 조건: 제출한 `(username, hash)` 쌍이 세션 시작 시점 스냅숏과 정확히 일치하고, 세션에서 악성 케이스를 한 번 이상 실행한 뒤

인정된 등급은 Objective 행으로 남습니다. 행에는 제출 시각과 시간 범위가 붙습니다.

- 제출에 악성 케이스(`case_id`)를 지정했으면 그 케이스 시작 100ms 전부터 종료 100ms 후까지
- 지정하지 않았으면 제출 2분 전부터 제출 100ms 후까지

스냅숏은 세션 시작 때 한 번만 만듭니다.

- 계정을 읽지 못해도 세션은 스냅숏 없이 생성됨. 이 세션에서 `POST /api/sessions/<id>/loot/`를 호출하면 409
- 이후 이 세션 때문에 board를 다시 읽지 않음. 슬롯 준비 점검의 `ground_truth`는 세션이 잡지 않은 슬롯에서만 board를 읽음
- `GET /api/wargames/<id>/objectives/`: `objectives.yaml`의 등급 목록. `?scenario=<id>`를 붙이면 그 시나리오가 노리는 등급만(`wargames.at_stake`). `loot_verified` 워게임에서는 시나리오의 공격 중 하나라도 계정을 덤프(`--dump`)하거나 레드팀이 사람(`red: person`)일 때만 전체 등급, 아니면 빈 목록(3.1, 3.2, 3.4). 결과 화면은 이 목록에 대상이 실제로 잃은 등급을 더해 보여 줌
- `GET /api/sessions/<id>/objectives/`: 저장된 행
- `POST /api/sessions/<id>/objectives/`: 관찰 수행. `loot_verified` 워게임에서는 아무 동작도 하지 않음

**corp 목표.** `effect_observed` 방식입니다. 레드팀은 따로 제출하지 않습니다. corp DB에 커밋된 행으로 판정합니다.

- `wargames/corp/objectives.yaml`: 읽기 채널(`estate://corp-db`, scope `wp_state`)과 등급 세 개
  - 무단 관리자 계정(`rogue_admin`, 난이도 5)
  - 자가 가입이 열린 사이트(`option_flip`, 4)
  - 무단 콘텐츠 작성(`content_write`, 3)
- 세션을 시작하면 기존 관리자, 감시 대상 `wp_options`, 게시된 글의 스냅숏을 저장
- 스냅숏은 corp-db에 읽기 전용 `mysql` SELECT로 읽음(`platform/api/effect.py`). 네트워크를 거치지 않고 `runner("corp-db")`로 실행
- `POST /api/sessions/<id>/objectives/`: corp-db의 바이너리 로그를 `mysqlbinlog`로 읽음. 세션 시작 1분 전부터(`--start-datetime`, UTC) 읽고, 세션 시작 전 변경은 버림. 커밋된 변경 중 타임스탬프가 악성 케이스의 시간 범위에 드는 것마다 등급을 인정
- 대상 변경:
  - 스냅숏에 없던 사용자에게 준 `wp_usermeta` 관리자 권한
  - `wp_options`의 `users_can_register=1`이나 `default_role=administrator`. 스냅숏과 값이 같으면 인정하지 않음
  - 새로 쓰거나 덮어쓴 `wp_posts` 행
- 이 읽기도 탐지 장비에 보이지 않음

성공한 목표는 실행 구간이 목표의 시간 범위와 겹치는 악성 케이스에 귀속합니다. 겹치는 케이스가 여럿이면 가장 늦게 시작한 케이스입니다.

- 목표는 그 케이스가 탐지됐을 때만 탐지된 것으로 침
- 겹치는 케이스가 없으면 미탐
- 귀속은 시간으로만 판단. 케이스의 `takes:` 필드는 채점에 쓰지 않음

점수의 `objectives` 블록:

- `coverage`: 전체 난이도 대비 탐지된 난이도. 성공한 목표가 없으면 `null`
- `false_positives`: 오탐 건수
- `damage`: 미탐 목표의 난이도 + 탐지된 목표 난이도의 절반. 탐지하지 못한 목표를 2배로 계산하는 부분

**탐지 결과.** 주 점수 옆에 따로 보고합니다. 주 점수에 합치지 않습니다.

- 케이스마다 정탐, 미탐, 오탐, 정상 통과 중 하나로 판정
- 케이스 하나는 경보가 몇 건이든 1건. `board-sqli-orderby-sqlmap`은 WAF로 요청 약 2,000개를 보내고 경보도 많이 내지만 1건으로 셈
- 경보 단위로 세면 방어가 아니라 경보 임계치를 재게 됨
- 응답의 집계 필드는 `tp`(정탐 건수), `fp`(오탐 건수), `fn`(미탐 건수), `tn`(정상 통과 건수). 에이전트용이고 콘솔 문구에는 나오지 않음

경보와 케이스는 케이스마다 선언한 두 전략 중 하나로 매칭합니다.

- `marker`: 경보에 케이스의 `X-Request-ID` 값이 있으면 매칭
- `window`: 경보의 출발지 주소가 케이스와 같고, 경보 시각이 케이스 시작~종료 사이(앞뒤 2초 여유)이고, 경보에 다른 마커가 붙어 있지 않으면 매칭. 다른 케이스나 고객 요청의 마커가 붙은 경보는 가져오지 않음

전략 간 fallback은 없습니다. 마커가 유실된 marker 케이스는 window로 메우지 않고 미탐으로 드러나야 합니다. 터미널 케이스에는 마커와 시간 구간이 모두 있습니다.

- `board-path-traversal-static`은 window 케이스. nginx가 ModSecurity 전에 400으로 거부하므로 그 기록에 `X-Request-ID`가 없음
- `POST /api/sessions/<id>/cases/`로 기록하는 window 케이스에 `source_ip`가 없으면 공격자의 기본 출발지 주소로 채움

- 점수 엔드포인트에 `?correlation=marker`나 `?correlation=window`를 붙이면 전략을 강제. 그 밖의 값은 400
- 이 파라미터를 넘기는 콘솔 페이지는 없음(`session.html`은 `correlation` 없이 `/score/` 요청)
- 두 전략을 비교하려면 전략별로 한 번씩 호출. 결과가 갈리면 방어가 아니라 채점 방식의 문제

`per_case` 항목마다 `expect`와 `corroborated`가 있습니다.

- `expect`: 케이스의 시그니처에 들어 있어야 할 부분 문자열
- `corroborated`: 매칭된 경보 중 하나의 시그니처에 `expect`가 대소문자 구분 없이 들어 있으면 true. 같은 세션에서 정상 케이스에도 매칭된 시그니처는 제외
- 정탐도 `expect`를 통과해야 함. 공격 기법을 짚지 않은 경보만 있으면 `corroborated: false`
- 케이스에 `expect`가 없으면 `corroborated`는 `null`(`per_case[].expect`는 `""`). `POST /api/sessions/<id>/cases/`로 기록한 window 케이스는 요청 본문에 `expect`를 넣지 않으면 `null`
- 탐지됐지만 corroborated가 아닌 케이스에는 `score.warning.wrong_reason`

`expect`는 케이스를 실행할 때 함께 저장합니다. 케이스 파일을 고쳐도 끝난 세션은 다시 판정되지 않습니다. 마이그레이션 0009 이전 행은 저장된 `expect`가 없어 현재 케이스 파일로 판정합니다. 경보 위험도와 룰 유형은 쓰지 않습니다.

**게임.** 점수의 `game` 블록은 세션이 닫히기 전까지 `{"revealed": false}`입니다. 닫힌 뒤에는 구성 요소 네 개와 각 가중치, balance가 들어갑니다.

- speed (0.25): 악성 케이스별로 첫 매칭 경보가 케이스 시작 10초 이내면 1, 120초 이후면 0, 그 사이는 선형. 케이스별 값의 평균
- accuracy (0.30): 재현율 - 오탐률. 하한 0
- coverage (0.20): 공격받은 공격 단계(`platform/lifecycle.py`) 중 탐지된 악성 케이스가 있는 단계의 비율. 공격받은 단계가 없으면 0. `objectives` 블록의 `coverage`와는 다른 값
- response (0.25): 차단된 악성 케이스 비율 - 차단된 정상 케이스 비율
- response는 `meta["blocked"]`가 붙은 케이스가 하나도 없으면 `null`. 나머지 가중치를 재정규화
- `meta["blocked"]`는 예정된 공격(403, 또는 sqlmap이 스스로 내린 주입 불가 결론)과 레슨의 시드 재실행(403)에서만 설정. 그 밖의 케이스에는 설정하지 않음

`game`의 나머지 값:

- `attacker`: 성공한 목표의 난이도 합(탐지된 목표는 절반). `damage`와 같은 값
- `defender`: 구성 요소의 가중 평균 × 성공한 목표 난이도 − 오탐 1건당 1
- `balance`: `defender - attacker`. 성공한 목표가 없으면 오탐 건수의 음수
- 가중치와 체류 시간은 v1 기본값(`docs/superpowers/specs/2026-09-29-zero-sum-scoring-design.md`)

**고객.** 점수의 `customers` 블록은 세션에 기록된 고객 요청을 집계합니다("고객 트래픽" 절). 최종 점검이 판정된 시나리오는 결과 보고의 `customers`와 같은 범위, 곧 마지막 최종 점검이 끝난 시각까지 보낸 요청만 셉니다(`scenario_run.served_until_verified`).

- `sent`
- `served`(2xx, 3xx)
- `blocked`(403. Django 자체 CSRF 거부는 생성기가 `refused_by: "app"`으로 표시하므로 제외)
- `unanswered`(10초 안에 응답 없음, status 0)
- `other`(그 밖의 4xx, 5xx)
- `alerted`(마커가 경보에 찍힌 고객 요청)
- `blocked_actions`
- `alerted_requests`(경보가 난 고객 요청의 시각, 동작, 메서드, 경로. 최대 20건)

요청은 한 번씩만 집계합니다. 고객 요청은 케이스가 아닙니다. `per_case` 목록에 들어가지 않고, 고객 요청이 낸 경보도 `unattributed`에 넣지 않습니다. 워게임과 레슨 세션의 탐지 결과에는 케이스 문장 옆에 "차단된 고객 요청: M건 중 N건"이 나옵니다. `detected_by` 시나리오는 그 대신 경보 없이 통과한 고객 요청 수(`score.customers_alerted`)와 케이스 표의 고객 행을 보여 주고, 다른 시나리오는 둘 다 보여 주지 않습니다.

완료 조건에 탐지기가 지정된 시나리오 세션(`detected_by`)은 그 탐지기의 경보만 셉니다(`scenario_run.sensed`). `per_case`, 목표의 탐지 여부, `customers.alerted`, 최종 점검 판정, 결과 보고의 타임라인이 모두 같은 정의를 쓰므로, 웹방화벽만 경보를 낸 공격은 점수와 판정에서 미탐입니다. 점수 응답의 `detected_by`가 그 탐지기를 밝힙니다. 진행 중 카드의 `when: alert`와 `live.alerted_per_minute`는 모든 탐지기의 경보를 셉니다. 이 규칙은 시나리오 세션에만 적용합니다. 레슨 F4의 `detected_by: suricata`는 `rules` 단계를 허용하는 데만 쓰고, F4의 점수는 두 탐지기의 경보를 모두 셉니다.

점수 엔드포인트는 읽기 전용이고 이력을 남기지 않습니다.

## 고객 트래픽

board 세션에는 고객을 붙일 수 있습니다. 세션 내내 글을 둘러보고, 검색하고, 로그인하고, 댓글을 다는 국내 커뮤니티 사용자입니다.

구성은 `wargames/board/traffic.yaml`에 선언합니다. 사용자 수, 출발지 가중치, 시드 계정, 글 1-15, 브라우저 User-Agent, 검색어, 댓글 내용, 행동 가중치 프로필이 들어갑니다.

`platform/traffic.py`는 이 선언을 아래 형태로 렌더링합니다.

- 페르소나 12명. 선언된 가중치대로 출발지에 배분(최대 잉여 방식). 페르소나마다 출발지 주소, 브라우저, 언어가 따로 있음
- 박스가 돌아가며 실행하는 단계별 흐름 2,000개

로그인과 댓글은 폼 POST입니다. 흐름은 먼저 페이지를 GET합니다. 박스는 그 페이지에서 `csrfmiddlewaretoken`을 꺼내 `csrftoken` 쿠키와 함께 보내고 302를 따라갑니다. 페이지에 토큰이 없으면(GET이 차단됐으면) 브라우저처럼 흐름이 거기서 멈춥니다.

생성기는 `deploy/traffic/users.py`입니다.

- Python 표준 라이브러리만 사용
- 여러 스레드로 계획된 속도에 맞춰 요청 전송
- 요청마다 새 UUID를 `X-Request-ID`에 넣음. 케이스 마커와 형태가 같아 학습자는 이 값으로 고객과 공격을 가려낼 수 없음
- 요청마다 JSON 한 줄을 `records.jsonl`에 기록
- 계획 파일이 바뀌면 다시 읽음. 파일이 삭제되거나 SIGTERM을 받으면 종료
- board 자체의 CSRF 거부(`refused_by: "app"`, 차단으로 세지 않음)는 영어 문구와 Django 실패 페이지의 `<span>(403)</span></h1>`로 식별. board는 고객의 언어로 응답하므로 한국어 고객에게는 거부 메시지도 한국어
- 한 페르소나의 흐름은 차례로 돎(`Customers.turns`). Django는 로그인할 때 CSRF 토큰을 바꾸므로, 같은 페르소나의 다른 흐름이 받아 둔 폼 토큰은 그 순간 무효가 되어 board가 403으로 거부했음(라운드 24: 3.2 댓글 2건, 3.3 로그인 1건)

생성기는 슬롯의 Kali 컨테이너에서 시스템 계정 `cr-users`로 돕니다.

- 페르소나마다 컨테이너의 출발지 주소 하나에 바인딩. 요청의 출발지 주소는 그 출발지의 주소
- 공격자와 분리함. 기본 출발지, 공격자가 쓰는 출발지의 `source_ip`, 컨테이너의 바인딩되지 않은 출발 주소(대상으로 `ip route get`)를 쓰지 않음
- `POSTROUTING -m owner --uid-owner cr-users -j RETURN`이 `ORIGIN-SNAT` SNAT 점프 앞에 있음. 공격자의 출발지 변환은 고객에게 적용되지 않음

박스에서 실행하는 명령은 모두 `platform/attacker.py`에 있습니다.

- `place_customers`: 계정, 프로그램 배치. 컨테이너 안에서 `sudo`로 실행
- `run_customers`: 계획을 쓰고, 프로그램이 떠 있지 않으면 `setsid`와 `setpriv`로 시작
- `stop_customers`
- `customer_records`

프로그램은 Kali 이미지에 넣지 않고 시작할 때마다 플랫폼에서 내려보냅니다. 컨테이너는 닫힐 때마다 이미지로 다시 만들어집니다. 이미지에 넣으면 프로그램을 고칠 때마다 새 이미지를 기다려야 합니다.

API는 `platform/api/customers.py`와 `views.session_traffic`에 있습니다.

- `PUT /api/sessions/<id>/traffic/ {rate, profile}`: 고객 시작, 또는 실행 중인 생성기의 속도와 프로필 변경(페르소나 유지)
  - `rate`: 초당 요청 수. 기본값 1, 최대 50
  - `profile`: 워게임이 선언한 프로필 중 하나. board는 `community`(기본값), `plain`(특이한 검색 없음), `readers`(`plain`에서 댓글 제외), `club`(`community`에 댓글 속 코드 질문 추가)
  - `traffic.yaml`이 없는 워게임은 404, 닫힌 세션은 409, 박스나 출발지가 없으면 503
- `GET`: 새 기록부터 읽은 뒤 아래 값을 반환
  - `declared`, `profiles`, `running`, `rate`, `profile`, `started_at`, `stopped_at`, `error`
  - 건수 `sent`, `served`, `blocked`(앱이 아니라 방어 설정이 낸 403), `unanswered`, `other`
  - `sources`(출발지, 주소, 요청 수)
  - `by_action`(행동별 전송 수와 차단 수)
- `DELETE`: 생성기를 멈추고 마지막 기록까지 읽음. 세션을 닫을 때도 슬롯 초기화 전에 같은 처리. 박스에 연결되지 않으면 닫기는 진행하고 오류를 `traffic.error`에 남김

기록은 바이트 오프셋 기준으로 가져옵니다(`tail -c`, 한 번에 최대 1 MiB, 완전한 줄만). 1 MiB보다 짧은 덩어리가 올 때까지 이어 읽고, 덩어리마다 `bulk_create`(`batch_size=500`)로 `CustomerRequest` 행에 넣고, 오프셋은 `Session.traffic`에 둡니다.

고객 트래픽 스위치는 테스트용이라 세션 페이지 URL에 `?traffic`이 있을 때만 보입니다. 시나리오에서는 고객을 자동으로 시작합니다.

## 시나리오

시나리오는 제한 시간이 있는 실습입니다. 고객과 공격자가 board를 쓰는 동안 학습자가 실제 도구로 방어합니다. 결과는 마지막 최종 점검 구간에서 판정합니다.

설계는 `docs/superpowers/specs/2026-10-13-scenario-course-and-topology-design.md`의 P4 단계입니다. 결정 사항은 `docs/DECISIONS.md`의 2026-10-13 "scenario course" 항목에 있습니다.

**기술자.** 워게임 `scenario.yaml`의 `scenarios:`에 두고, `wargames.checked_scenarios`로 검증합니다.

| 필드 | 의미 |
|---|---|
| `id`, `order` | `1.1`, `2.1`, ... id는 기초 레슨과 같은 네임스페이스 |
| `task_class` | `judgement`, `availability`, `detection`, `unknown` 중 하나 |
| `guidance` | `worked`(`steps` 선언 가능, 단계 엔진에서 실행), `faded`, `none` |
| `text`, `briefing` | `text`는 문자열 키 접두어. `briefing`은 `situation`, `goal`, `measured_by`를 문자열 키에 연결 |
| `minutes`, `window_minutes` | 시나리오 길이, 최종 점검 구간 길이 |
| `defense` | 워게임 `defense:` 맵의 방어 설정 중 하나(CRS 수준, 예외 규칙, 임계치, Suricata 룰셋) |
| `traffic` | 고객용 `{profile, rate}`(`traffic.yaml`) |
| `red` | `schedule`(기본값) 또는 `person`. `person`이면 사람이 레드팀 콘솔을 쓰고 공격 선언이 없어도 됨 |
| `attacks` | `[{at, case, origin}]`: 연 뒤 몇 초(`minutes` 이내), 악성 케이스, 선택 출발지. 학습자에게 비공개 |
| `completion` | 종류별. judgement: `{judged: all}`, 선택 `pattern: judged`. availability: `{served: all, held: all}`, 선택 `thresholds: {inbound, outbound}`. unknown: `{served: all, held: all}`. detection: `{detected_by: suricata}` |
| `cards` | `[{id, when}]`. `when`은 `start`, `alert`, `blocked`, `window` 중 하나. 노트에는 아직 확인하지 않은 카드 하나가 맨 위에 펼쳐지고, 확인한 카드는 제목만 보이게 접혀 남음. 맨 아래에는 브리핑의 목표가 늘 남고, 처음 그릴 때 다른 카드가 없으면 펼쳐져 있음 |
| `hints` | 하나씩 차례로 제안하는 힌트 id |

`GET /api/wargames/`는 시나리오별 카드(`wargames.scenario_card`)를 `attacks` 없이 나열합니다. `GET /api/sessions/<id>/`는 단계형 시나리오의 `lesson`에서 `attacks`와 `completion`을 빼고 `cases`를 비워서 돌려줍니다.

**열기.** `POST /api/sessions/ {"scenario": "2.1"}`의 처리 순서입니다.

1. 시나리오 id로 워게임을 찾습니다.
2. `lesson`, `guidance`, `defense`가 오면 거부합니다.
3. 다른 세션과 같은 방식으로 선언된 방어 설정을 적용합니다.
4. `scenario_run.begin`에서 고객을 시작하고 `Session.scenario_state`(마이그레이션 0025, `Session.course_scenario` 옆)를 씁니다.

`scenario_state`에는 공격별 절대 예정 시각을 붙인 일정, 점검 구간, 판정 결과, 힌트 제안, 지금까지 확인한 WAF 버전이 들어갑니다.

단계형 시나리오는 `guidance`를 true로, `lesson`을 자기 id로 설정합니다. 단계는 재생 시드 없이 `/lesson/steps/`에서 돕니다. 고객을 시작하지 못하면 세션을 닫고 503을 돌려줍니다.

**엔진.** `platform/api/scenario_run.py`이고, 순수 규칙은 `platform/scenarios.py`에 있습니다.

- 플랫폼 프로세스 안의 스레드. 첫 시나리오를 열 때와 부팅할 때 `cr/wsgi.py`에서 시작
- `resume`: 실행 도중 끊긴 공격을 예정 상태로 되돌림
- 틱이나 그 뒤의 연결 정리가 실패하면 로그만 남기고 스레드는 계속 돎

엔진은 `CR_SCENARIO_TICK`(2초)마다 열린 시나리오 세션별로 아래를 합니다.

- 시계가 시작되지 않은 세션은 건너뜀. 그동안 `time_left`는 `minutes` 전체
- 시계: `begin`은 `started: false`를 씀. 상황 설명 화면에서 시작을 눌러 `POST .../scenario/start/`가 오면 그 시점 기준으로 `opened_at`, 점검 구간 시각, 종료 시각, 공격 일정을 한 번 정함(2026-11-14). `verify-window`는 시계가 멈춰 있으면 먼저 시계를 시작
- 학습자가 점검 구간을 열지 않았으면 예정 시각(시계 시작 후 `minutes - window_minutes`)에 엶
- 예정 시각이 된 공격을 하나씩 가져와 워커 4개짜리 풀에서 `views._fire`로 실행하고 `meta.scheduled`를 붙임. 재생 표시가 아니므로 두 점수 모두에 반영
- `CR_SCENARIO_OBSERVE`(15초)마다 고객 기록을 가져오고 최근 180초를 수집(ingest)
- `CR_SCENARIO_WAF_POLL`(20초)마다 WAF 파일을 읽어 터미널에서 바꾼 내용을 잡음
- 열린 점검 구간이 끝났고, 구간 안에 예정된 공격이 모두 실행됐거나 실패했으면 그 구간을 판정. 판정은 같은 틱의 고객 기록·수집·WAF 읽기보다 먼저 함

예정된 공격의 기록:

- sqlmap 덤프는 해당 케이스에 귀속해 `views._credit_loot`로 넘김. 주 점수는 board 자체의 계정과 일치할 때만 손실로 침
- 일정 항목에 `outcome`(held 또는 leaked)
- 케이스에 sqlmap의 결론 줄과 403 횟수(`meta.conclusions`, `meta.forbidden`. 판정에는 미사용)
- `meta.blocked`: 403이 났거나, 덤프한 행 없이 정상 종료한 sqlmap이 스스로 주입 불가로 결론 낸 경우(`tools.found_not_injectable`)
- sqlmap 케이스는 해시 크랙 질문에 거절로 답함(`--answers=crack=N`). 덤프한 칸에는 `loot.matched`가 비교하는 원래 해시가 남음

세션을 닫으면 예정 상태인 공격은 취소합니다. 실행 중인 공격은 끝까지 돌려 기록합니다.

**최종 점검 구간.** `POST .../scenario/verify-window/`("최종 점검 시작")나 일정에 따라 `window_minutes` 동안 열립니다.

- judgement 시나리오에서 판정하지 않은 항목이 있으면 학습자 요청에 409와 남은 개수 `unjudged`로 응답(`scenario_run.unjudged`). 콘솔은 항목을 다시 불러와 남은 개수를 보여 줌
- 일정에 따른 구간은 이와 상관없이 열림
- 엔진은 일정의 공격 케이스 중 구간 안에 예정되지 않은 케이스마다 항목을 하나씩 구간 안에 추가

구간에서는 시나리오 종류별 `completion`을 판정합니다.

- `served`: 구간 안에서 방어 설정에 차단된 고객 요청(앱이 아닌 403)이 없어야 함
- `held`: 구간 안의 공격이 모두 실행됐고 모두 막혔어야 함(탈취 데이터 일치 없음, 영향 없음). 실행되지 않은 공격이 있으면 `scenario.fail.unfired`
- `judged`: 구간이 열릴 때 목록에 있던 항목을 모두 맞게 판정해야 함. 목록은 구간과 함께 저장. 구간 중에 내린 판정도 인정. 나중에 더 이른 시각으로 기록에 들어온 항목은 추가하지 않음
- `detected_by`: 구간 안의 공격이 모두 실행됐고(아니면 `scenario.fail.unfired`), 공격마다 corroborated인 Suricata 경보가 있어야 함. 고객 요청에는 Suricata 경보가 없어야 함(`scenario_run.sensed`). 케이스에 `expect`가 없으면 Suricata 경보 하나로 충분하지만, 지금 쓰는 케이스에는 모두 `expect`가 있음
- `thresholds`: 구간의 WAF 스냅숏 시점에 적용 중인 CRS 이상 점수 임계치가 지정값 이하여야 함. 임계치를 지정하지 않은 설정은 CRS 기본값(인바운드 5, 아웃바운드 4)

구간의 기타 규칙:

- `red: person`이면 구간 안에서 그 사람이 실행한 악성 케이스(재생 제외)도 예정된 공격과 똑같이 판정
- judgement 시나리오는 판정 결과만 봄(설계 문서의 종류 표). 구간 중 차단된 고객은 결과 옆에 보고만 하고 실패로 치지 않음
- 결과에 조치 유형 표시. 그 시점 WAF 스냅숏에 대한 `lesson.fix_class`(`level`, `threshold`, `rule`, `target`, `path_target`. "세션, WAF 설정 조정, 단계 엔진" 절)
- 실패한 구간 뒤에 새 구간을 열 수 있음. 통과한 뒤에는 409
- 구간을 통과하면 고객 트래픽을 멈춤(`scenario_run._shift_over`). 새 항목이 더 쌓이지 않음

**경보 판단**(`GET/POST /api/sessions/<id>/triage/`). 학습자는 경보를 항목 단위로 하나씩 판정합니다.

- 항목은 경보를 일으킨 마커마다 하나. 고객 요청은 요청마다, 공격 케이스는 요청 수와 관계없이 케이스마다 하나
- 항목 id는 마커를 세션의 browse 마커와 함께 해시한 값. `/cases/`와 대조할 수 없음
- 항목 내용: 첫 경보·마지막 경보 시각, 경보 수, 출발지 주소, 요청 하나, WAF 판정, 상태 코드, 엔진·ID·메시지·건수를 붙인 룰 최대 12개
- WAF 판정: 949/959 합계 룰이 동작했으면 `blocked`, 아니면 `logged`나 `none`
- 케이스 이름이나 라벨은 표시하지 않음
- 재생 요청과 학습자 자신의 웹사이트 창 요청은 제외
- 판정 형식: `{item, verdict: attack|customer, succeeded}`
- `verdict`는 기록(케이스의 `malicious` 또는 고객 행)과 대조. `succeeded`는 대상 시스템(케이스에 일치한 탈취 데이터, 또는 시간 범위 안의 목표)과 대조
- 응답의 `right_so_far`로 콘솔의 맞힌 판정 수를 갱신
- completion에 `pattern: judged`가 있으면 공격의 `pattern`도 물음. 케이스 파일에 있는 악성 케이스의 CAPEC id 중 하나이고, 시나리오 카드의 `patterns`에 나열
- `pattern` 답은 케이스 자신의 `pattern`과 대조해 판정과 함께 저장. 정답 `pattern`은 항목에 표시하지 않음. 항목의 `judged`에는 학습자가 고른 값만 돌려줌
- 단계 check `triage`(`judged: customer | attack | all`): 학습자가 맞게 판정하면 통과. `judged: verified`는 구간이 열리면 통과. "최종 점검 시작" 안내 단계는 버튼 클릭이 아니라 점검이 실제로 시작돼야 통과
- 판정 창이 열려 있고 판정 중인 항목이 없으면 15초마다 항목을 다시 읽음. 공격으로 판정한 뒤에는 후속 질문 버튼을 닫으므로 다시 읽기가 멈추지 않음
- 결과 보고의 판정 줄은 마지막으로 판정된 구간에 나열된 항목만 셈. 맨 위 결과와 합계가 같음. 판정된 구간이 없으면 전체 항목

**상태, 힌트, 결과 보고.** `GET .../scenario/`의 응답 항목입니다.

- 시나리오 카드
- `phase`(running, window, passed, failed, closed)와 `time_left`
- `started`: 상황 설명 화면이 떠 있고 시계가 시작되지 않았으면 false(이때 `time_left`는 실행 시간 전체)
- 직전 1분 동안 차단된 고객과 경보가 난 요청. `alerted_per_minute`는 경보를 일으킨 서로 다른 마커 수(고객 요청은 요청마다, 공격 케이스는 한 번)
- 탈취된 목표, 점검 구간, 완료 조건
- 표시할 카드와 힌트 제안

힌트는 아래 중 하나가 일어나면 제안만 합니다. `Session.hints`에는 기록하지 않습니다.

- 단계 check가 두 번 실패
- 같은 항목을 두 번 틀리게 판정
- `PUT /waf/`로 적용 중인 파일을 그대로 다시 씀
- 고객이 차단되고 있는데 5분 동안 WAF 변경이 없음

`POST .../scenario/hints/`를 호출하면 다음 힌트를 열고 `Session.hints`에 기록합니다.

`GET .../scenario/debrief/`는 점검 구간이 판정되거나 세션이 닫히기 전까지 409입니다. 일정이 드러나지 않게 하기 위해서입니다. 그 뒤에는 Igloo/ASEC 보고서 순서로 아래를 돌려줍니다.

- `overview`: 마지막 최종 점검의 판정, 조치 유형과 사유, 판정한 점검 수, 전체 단계 중 통과한 단계 수, 사용한 힌트
- `evidence`: 예정된 공격에서 나온 세션의 탐지 기록 최대 20건. 완료 조건에 탐지기가 지정돼 있으면 그 탐지기의 기록. 룰·요청·케이스 포함. Elasticsearch는 조회하지 않음. `evidence_total`은 잘리기 전 전체 건수이고, 결과 보고는 20건을 넘으면 목록 아래에 "외 N건"을 붙임
- `change`: 선언된 방어 설정과 마지막 WAF 스냅숏의 비교. 추가·삭제된 예외 규칙, 양쪽 수준, 그 방어 설정으로 `crs.rendered`가 만드는 내용과 예외 파일의 줄 단위 diff. `ids`는 방어 설정의 Suricata 룰과 마지막으로 적용한 룰 파일의 줄 단위 diff(`views._ids_change`). WAF 스냅숏이 없어도 `ids`는 있고, 결과 보고는 비어 있지 않을 때만 보여 줌
- `cases`: 예정된 케이스별로 판정된 구간 이전과 구간 안의 결과(held 또는 leaked)와 경보 여부(`alerted_before`, `alerted_after`. 실행되지 않았으면 `null`). 결과 보고의 적용 전·후 표는 그 구간에 실행되지 않은 칸에 "실행 안 함", 실행이 실패한 칸에 "실행 실패"를 씀
- `risk`: 조치 유형에 따라 정해지는 문자열 키
- `customers`: 마지막 최종 점검이 끝난 시각까지 보낸 고객 요청의 집계(`sent`, `served`, `blocked`, 응답이 없던 `unanswered`, 그 밖의 4xx·5xx인 `other`). 점검이 끝난 뒤 고객 트래픽을 멈추기까지 몇 초 더 간 요청은 세지 않아, 콘솔에서 읽어도 닫힌 세션에서 읽어도 같은 수
- 공격 `timeline`. `outcome`은 계정을 덤프하는 공격에만 있고, `loot_verified` 워게임에서 덤프하지 않는 공격은 `null`(`scenario_run._taking_the_secret`)
- `triage`
- `at`: 에이전트용. 시작 시각과 마지막 판정 시각

결과 보고는 `debrief_script.html`로 블루팀 콘솔과 닫힌 세션 페이지에 렌더링합니다.

**콘솔.** 홈 페이지에는 워게임별로 시나리오가 나열됩니다. 시작을 누르면 블루팀 콘솔이 상황 설명 화면(제목, 상황, 목표, 평가 방법, 시간)으로 열립니다. 유형·안내 수준 칩은 없습니다. 시계는 이 화면에서 시작을 눌러야 돌기 시작합니다. 시계가 이미 돌고 있으면(`started: true`) 다른 브라우저에서 열어도 상황 설명 없이 바로 콘솔이 열립니다.

- 창 위쪽 띠: 진행 상태(색 글자), 남은 시간, 분당 차단된 고객과 경보가 난 요청, 탈취된 목표, 힌트 제안, 최종 점검 시작 버튼
- 구간이 판정되면 띠에 "세션 종료"가 나옴. 누르면 띠 아래에 종료 안내(`session.close.consequence`)와 확인 버튼. 종료하면 세션 페이지의 결과로 이동
- 통과하면 띠에서 남은 시간, 힌트 제안, 최종 점검 시작 버튼을 숨김
- 최종 점검 거부 사유는 띠 아래 한 줄에 줄임 없이 표시
- 띠는 5초마다 상태를 다시 읽음. 점검 구간의 남은 시간이 0이 되면 판정이 나올 때까지 1초마다 읽고, 버튼 글자는 `scenario.done.judging`
- 경보 항목과 결과 보고는 배지·알약 대신 글자. 판정한 항목에는 판정 줄 하나만 남김(새로 읽으면 `triage.said.right` 또는 `triage.said.wrong`). 다시 읽기 버튼은 없음. 목록은 15초마다 저절로 다시 읽음
- judgement 시나리오: 경보 창 추가. 목록을 가리지 않도록 카드와 연 힌트는 창 옆 레슨 노트 열에 둠. 강조 표시의 콜아웃은 창 안에만
- detection·unknown 시나리오: IDS 룰 창(`/api/rules/`를 쓰는 룰 편집기) 추가
- 카드는 정해진 시점에 나타남. 구간이 판정되면 결과 보고가 열림
- 단계형 시나리오의 단계는 레슨 노트에서 진행. 힌트 목록은 비어 있고, 힌트는 시나리오의 힌트 제안으로만 받음

**board의 시나리오.** 열한 개이고, 홈 페이지에서 기초 레슨 다음에 과제 종류 순(`order`)으로 나열됩니다. "방어 설정"은 시나리오 시작 때의 defense입니다.

| Id | 제목 | 종류, 안내 방식 | 방어 설정 | 고객 | 공격(비공개) |
|---|---|---|---|---|---|
| 1.1 | 고객 요청과 공격 구분하기 | judgement, worked | `level2`: PL2 | `community` 초당 2건 | 150초에 sqlmap(`ru`) |
| 1.2 | 차단되지 않은 WAF 경보 판단 | judgement, faded | `inherited`: PL2, 949110과 959100 제거 | `community` 초당 2건 | 120초에 sqlmap, 300초에 검색 인젝션(`ru`) |
| 1.3 | 공격 유형 구분하기 | judgement, none. 공격 패턴도 판정 | `inherited` | `community` 초당 4건 | 90초부터 660초까지 케이스 8개, 모두 `kr`: sqlmap 기본과 tamper, 검색·union·로그인 인젝션, XSS 2개, 경로 순회 |
| 2.1 | 한글 검색 오탐 해결 | availability, faded | `level3`: PL3 | `readers` 초당 2건 | 240초에 sqlmap(`ru`) |
| 2.2 | 태그·링크 검색 오탐 해결 | availability, faded | `level2` | `community` 초당 2건 | 240초에 sqlmap(`ru`) |
| 2.3 | 이상 점수 임계치 낮추기 | availability, none. 최종 점검은 임계치 5/4 | `untuned`: PL3, 임계치 10,000/10,000 | `plain` 초당 2건 | 600초에 sqlmap(`ru`) |
| 3.1 | 탐지 룰 수정하기 | detection, worked | `broken-rule`: PL1, `broken-sort.rules`(sid 9000101이 `http.request_body`를 읽음) | `plain` 초당 2건 | 120초에 sqlmap `--random-agent`(`ru`) |
| 3.2 | sort 공격 탐지 룰 작성하기 | detection, faded | `ids`: PL1, `no-uri-sqli.rules` | `plain` 초당 2건 | 120초에 sqlmap `--random-agent`(`ru`) |
| 3.3 | 변형된 공격 탐지하기 | detection, faded | `spelled`: PL1, `spaced-sort.rules`(앞뒤가 공백인 SQL 단어) | `plain` 초당 2건 | 45초에 sqlmap `--random-agent`, 120초에 tamper 변형(`ru`). 최종 점검이 둘을 다시 보냄 |
| 3.4 | 댓글 XSS 탐지 룰 작성하기 | detection, none | `xss-watched`: PL1 DetectionOnly, `local.rules` | `plain` 초당 2건 | 120초에 댓글 XSS, 240초에 검색 XSS(`ru`) |
| 4.1 | 종합 실습 | unknown, none(카드·힌트 없음) | `full` | `club` 초당 2건(댓글에 코드 질문 추가) | 300초에 `board-sqli-orderby-sqlmap-versioned`, 600초에 sqlmap(`us`) |

고객 요청을 차단하는 CRS 룰:

- PL3: 한글 검색이 `ARGS:q` 대상 920272와 942460에 걸림. 이 둘을 예외 처리하면 `REQUEST_URI_RAW` 대상 920272에 걸림
- PL3: 한글 검색을 한 번 하면 이후 고객이 여는 모든 페이지가 `REQUEST_HEADERS:Referer` 대상 920272에 막힘
- PL3: 한글 댓글은 `REQUEST_BODY` 대상 920272와 `ARGS:body` 대상 942460에 걸림
- PL2: `<b>` 검색이 941320에, 유튜브 링크가 931130에 걸림. 둘 다 `ARGS:q` 대상
- PL1: `club` 프로필 댓글의 코드 질문이 `ARGS:body` 대상 942100, 942190, 941100, 941110, 941160에 걸림

시나리오 4.2(레드팀 콘솔을 쓰는 사람 대 학습자)는 두 번째 사람이 있어야 해서 선언하지 않았습니다. 엔진은 `red: person`을 지원합니다.

## 결정

**케이스 파일은 워게임마다 하나**이고, 공격과 정상 트래픽을 같은 파일에 둡니다.

- board는 `redteam/cases/board.yaml`, corp는 `redteam/cases/corp.yaml`
- 파일을 나누면 정상 케이스를 빠뜨리기 쉬움
- CLI는 `--cases`로 다른 파일을 지정하지 않으면 `board.yaml`을 읽음. `case_file`이 그 파일 basename과 같은 시나리오로 세션을 엶(모르는 파일이면 board)

**harness는 경로가 바뀐 요청을 보내지 않고 거부합니다.**

- `requests`는 `/static/../../etc/passwd`를 `/etc/passwd`로 바꿈
- 그대로 보내면 실제로 나가지 않은 공격이 기록되고, harness의 실패가 방어의 실패로 채점됨
- 퍼센트 인코딩 차이는 허용

**시작하지 못한 도구는 예외로 처리합니다. 도구 케이스에서 0이 아닌 코드로 끝난 도구는 실행한 것으로 봅니다.**

- sqlmap은 아무것도 찾지 못하면 0이 아닌 코드로 끝나지만, 트래픽은 이미 나간 뒤임
- HTTP 케이스의 curl이 0이 아닌 코드로 끝나면 요청이 대상에 닿지 않은 것으로 보고 예외 처리

**Kibana는 compose에 들어 있고 Elasticsearch 보안 기능 없이 돕니다.** 9200, 5601은 플랫폼 VM의 루프백에만 열려 있고, 훈련 환경에서는 경로가 없습니다. 학습자는 콘솔 로그인으로 `/kibana/`에 들어옵니다.

- 접속: 플랫폼 8000번 포트의 `/kibana/`. 로그인 세션이 없으면 로그인 페이지로. Discover 밖의 요청은 앞단 nginx에서 거부(아래)
- 운영자: 플랫폼 호스트의 루프백 127.0.0.1:5601에 ssh 터널로 접속
- 블루팀 콘솔: Kibana를 프레임으로 띄움

시작 시 가져오기:

- `platform/kibana.py`는 시작할 때 백그라운드로 돎. `/api/status`로 Kibana 응답을 확인한 뒤 가져옴
- Kibana에 연결되지 않거나 502/503/504가 오는 동안은 재시도. 그 밖의 HTTP 오류는 상태와 본문을 한 번만 보고
- 시작 중인 Kibana는 multipart 가져오기에 415를 줌
- 가져오는 파일: `deploy/kibana/objects.ndjson`(overwrite)
- `@timestamp` 기준 data view `logs-*`. runtime field로 Suricata/ModSecurity 필드 쌍을 한 열로 합침(`rule`, `rule_id`, `source_ip`, `destination`, `url`, `status`)
- "Alerts" 검색과 "Overview" 대시보드. 제목에도, data view의 `sourceFilters`에도 플랫폼 이름이 없음
- 경보 검색어는 `event_type : "alert" or event.module : "modsecurity" or event.module : "nginx"`(`kibana.ALERTS_QUERY`). nginx가 거부한 요청도 경보로 보임
- `defaultRoute`는 `kibana.py`에서 이 검색으로 지정. data view가 있어야 Kibana의 Welcome 화면이 뜨지 않음
- Kibana `metaFields`에서 `_index`를 뺌
- 가져오기가 거부되면 로그만 남기고 세션은 계속 진행

세션별 space:

- 세션을 열면 `kibana.py`가 그 세션 전용 Kibana space를 만들고 data view를 가져옴(`ensure_session_view`. `compose.yaml`의 `KIBANA_URL` 필요)
- space와 data view의 id는 둘 다 `soc-<pattern>`
- space에서는 Discover를 뺀 모든 기능(대시보드, visualize, dev tools 등)을 끔
- space 설정에서 ES|QL을 끔(`enableESQL`). ES|QL은 data view의 패턴과 숨긴 필드를 무시하고 모든 인덱스를 읽음
- `defaultColumns`는 세션 열
- `defaultRoute`는 그 space의 저장된 검색 "Events"(세션 열, 최신순). 학습자가 default space의 운영자 객체에 닿지 못함

차단:

Kibana를 보안 기능 없이 돌리므로, 관리 API는 막을 목록을 두지 않고 허용 목록으로 거릅니다. space 안의 `api`, `internal` 호출은 nginx가 모두 `/kibana-gate/`로 넘기고, `kibana.refusal`은 Discover가 부르는 호출(`DISCOVER_READS`, 검색, 필드 목록, 값 추천)만 통과시킵니다. 나머지는 403입니다(위 "Kibana도 슬롯별로 나뉩니다" 참고).

nginx(`platform/nginx.conf`)에 남은 것:

- Default space(`s/default/...`), space 접두어가 없는 `app`, `spaces`, `api`, `internal` 경로, space 안에 다시 `s/`를 넣은 경로는 403
- `api/spaces/space`는 GET만 받고, nginx가 그 세션 space 하나로 직접 응답
- `app/management`, `app/dev_tools`, `app/home`, `app/observability`, `app/security`, `app/kibana_overview`는 같은 space의 Discover로 리다이렉트
- 플랫폼 자체 설정(`KIBANA_URL`)은 Kibana에 직접 붙음

학습자 화면:

- space 이름은 "SOC"
- data view는 세션의 인덱스 패턴에 걸려 있지만 이름은 `logs-*`로 보임
- 공유 runtime field에 추가하는 필드:
  - `log_source`: `suricata`, `modsecurity`, `nginx` 중 하나
  - `sensor`: 기록을 남긴 쪽. Suricata 기록이면 센서가 본 구간(`in_iface`. 센서가 WAF 뒤만 보므로 언제나 `web`), ModSecurity와 nginx 기록이면 `waf`
  - `request_headers`: 요청 헤더별 `Name: value`. `X-Request-ID`는 제외
  - `request_header`: 자주 쓰는 헤더별 keyword composite field(`request_header.host`, `.user_agent`, `.referer`, `.cookie`, `.x_forwarded_for` 등 `kibana.REQUEST_HEADERS_SHOWN`). Suricata의 `http.request_headers`나 ModSecurity의 `transaction.request.headers`에서 읽음
- `sensor` 계산: Suricata 이벤트의 `in_iface` 값을 그대로 씀. 스크립트에 `cr` 호스트 이름이 드러나지 않음
- `sourceFilters`로 숨기는 필드(`kibana.HIDDEN_FIELDS`): `_index`, `event.*`, `log.*`, `message`, `agent.*`, `ecs.*`, `host`, `host.*`, `input.*`, `error.*`, `http.*`, `transaction.*`, `metadata.*`, `data_stream.*`, `flow_id`, `tx_id`, `pcap_cnt`, `in_iface`, `pkt_src`, `community_id`, `src_ip`, `dest_ip`, `alert.signature`, `alert.signature_id`. KQL 검색은 그대로 됨

Discover 링크:

- `GET /api/sessions/<id>/` 응답의 `discover`: `/kibana/s/<space>/app/discover`에서 그 data view를 쓰는, 저장하지 않은 Discover 상태
- 범위는 현재 레슨 시작 시점부터
- 열: `event_type, source_ip, destination, url, status, rule_id, rule`(`kibana.SESSION_COLUMNS`, 열 너비 고정)
- 필터는 없음. 훈련 환경 호스트 자체의 syslog 줄은 Filebeat 단계에서 인덱스에 들어가지 않음
- 레슨은 빈 쿼리로, 시나리오와 워게임은 경보 쿼리로 엶
- space나 data view가 준비되지 않았거나 `KIBANA_URL`이 없으면 `discover`는 null. 공유 운영자 data view로 대신하지 않음
- 이때 ELK 창에는 준비 중 문구가 뜨고, 링크가 생길 때까지 세션을 다시 읽음. 가져오기는 10초마다 재시도
- ELK 창은 이 링크로 엶. 저장된 검색에 쿼리를 덮어쓰지 않음. 그러면 Kibana가 "Unsaved changes" 배지를 붙임

블루팀 콘솔의 Kibana localStorage 처리:

- 창을 로드하기 전에, same-origin으로 공유하는 localStorage에 Kibana 첫 방문 안내를 본 것으로 표시(`discover:docExplorerUpdateCalloutClosed`, `discover:docExplorerCalloutClosed`, `data.noDataPopover`)
- 콘솔을 불러올 때마다(세션을 열거나 레슨을 바꿀 때) `discover:searchText`를 지움. Document 창의 필드 검색어이고, 지우지 않으면 앞 레슨에서 입력한 단어가 그대로 남음

**Elasticsearch는 단일 노드, 힙 512 MB**입니다.

**없는 데이터는 0으로 두지 않고 오류로 처리합니다.**

- Elasticsearch나 substrate에 연결되지 않거나 룰 파일을 읽지 못하면 503
- 대상 시스템에 연결되지 않아도 세션은 만듦. 스냅숏 없이 시작하고, board의 `loot/`는 409
- 케이스 실행·기록과 세션 닫기에서는 대상 시스템을 읽지 않음. 출발지나 도구 때문에 실행에 substrate가 필요하면 503
- ingest 중 시간이 지난 룰의 재활성화와 경보의 구간·호스트 배치는 substrate에 연결되지 않아도 진행. 배치 결과는 비어 있음. 세션은 그대로 시작하고 멈출 수 있음
- 분모가 0인 비율은 null이 아니라 0.0. 정밀도, 재현율, F1, 오탐률과 게임의 speed, coverage, accuracy가 해당. null이 되는 것은 `objectives` 블록의 `coverage`뿐

**점수가 보증하지 못하는 부분은 경고로 붙입니다.**

- `no_benign`: 정상 케이스 없음. 세션의 고객이 요청을 보냈으면 이 경고를 뺌. 고객 요청은 케이스로 기록되지 않는 정상 트래픽
- `no_marker`: marker 케이스는 있는데 마커가 붙은 경보가 하나도 없음
- 레슨 세션(시나리오가 아닌 가이드 세션)에서는 `no_benign`과 `no_marker`를 빼고 보냄
- `no_source_ip`: 출발지 주소가 없는 window 케이스가 있음
- `wrong_reason`: 탐지됐지만 corroborated가 아닌 케이스가 있음
- `truncated`: Elasticsearch hit가 ingest에서 읽은 것보다 많음

**케이스 발사.** API(`views._fire`)와 CLI(`redteam/run.py`) 모두 `harness.fire`를 거쳐 HTTP 케이스마다 공격 박스에서 `curl`을 따로 실행합니다. CLI의 `requests.Session`은 플랫폼 API에만 씁니다.

## OpenStack

이 절에는 구축을 마친 것만 적었고, 항목마다 클라우드나 fake 환경에서 돌려 확인했습니다. 남은 작업은 절 끝에 있습니다. 근거는 `docs/DECISIONS.md`, `docs/superpowers/specs/2026-09-30-openstack-range-placement.md`, `docs/superpowers/specs/2026-09-30-waf-console-and-tutorial.md`에 있습니다.

지금 클라우드는 노드 세 대, Kolla 2025.2, ML2/OVN입니다. 제품이 지원하는 버전은 Kolla-Ansible 2025.1 이상입니다([클라우드 요구 사항](OPENSTACK.md#2-what-the-cloud-needs-kolla-ansible-20251-or-later)).

훈련 환경은 프로젝트 `fsl-range`에 두고, member 역할 사용자 `fsl-range`로 조작합니다. 사용자에게 Horizon은 노출하지 않습니다.

클라우드별 값은 `deploy/openstack/cloud.yaml`에 둡니다. 관리자 권한으로 `uv run bin/cloud init`을 실행하면 `cloud.example.yaml`에서 이 파일을 만듭니다. 파일이 있으면 init이 맡은 키(`cloud`, `network.external`, `network.allowed`, `compute.base_image`, `compute.flavors`)만 줄 단위로 바꾸고 다른 값과 주석은 그대로 둡니다.

키:

- `cloud`: 인증 정보가 든 `clouds.yaml` 항목 이름(`fsl-range`)
- `network`: `external`, `address`, `allowed`(선택, ssh·8000·8002를 열 CIDR, 기본 `[0.0.0.0/0]`), `dns`, `mtu`, `platform`, `estate`, `mgmt`
- `compute`: `base_image`, `availability_zone`, `slots`, `flavors.platform`, `flavors.range`
- `keys`: `key_name`(플랫폼 VM의 Nova 키페어 이름), `key_file`(그 개인키 경로), `range`
- `platform`: `stack`, `repository`, `ref`
- `backups`: `keep`

인증 정보는 이 파일에 없습니다. OpenStack 클라이언트 표준 설정 파일 `~/.config/openstack/clouds.yaml`에서 `cloud`가 가리키는 항목을 읽습니다(`cloud.signed_in`). init이 이 항목을 모드 0600으로 쓰고, 파일의 다른 항목은 건드리지 않습니다. 비밀번호는 무작위로 만들고 출력하지 않습니다. 항목으로 이미 로그인되면 그대로 둡니다. 사용자는 있는데 그 비밀번호를 가진 항목이 없으면 거부하고, `--reset-password`를 주면 새 비밀번호를 정합니다. 떠 있는 플랫폼은 `up --replace` 전까지 옛 비밀번호를 씁니다. 항목이 없으면 `up`, `down`, `platform-rebuild`는 아무것도 바꾸기 전에 멈추고 `bin/cloud init`을 실행하라고 출력합니다. 셸의 `OS_*` 변수는 지우고 `OS_CLOUD`, `OS_CLIENT_CONFIG_FILE`만 openstack CLI에 넘깁니다. 플랫폼 VM은 항목의 `user_domain_name` 도메인으로 로그인합니다.

init이 하는 일(`bin/cloud`의 `init`, 관리자 인증은 `/etc/kolla/clouds.yaml`의 `kolla-admin` 항목 또는 셸의 `OS_*`):

- `router:external` 외부 네트워크 하나를 찾음. 없으면 멈추고, 여럿이면 `network.external`이 그중 하나를 가리킬 때만 그것을 쓰고 아니면 목록을 출력하고 멈춤
- 프로젝트 `fsl-range`, member 사용자 `fsl-range`가 없으면 만듦
- flavor는 만들지 않음. 조건(플랫폼 2 vCPU·8 GB·40 GB, 훈련 환경 호스트 6 vCPU·16 GB·40 GB 이상)에 맞는 것 중 가장 작은 것을 고름. private flavor는 프로젝트에 접근 권한을 줌
- quota가 인스턴스 2, 두 flavor의 vCPU·RAM, floating IP 1을 담지 못하면 모자란 항목을 출력하고 멈춤
- `compute.base_image`(기본 `ubuntu-24.04`) 이미지가 없으면 noble amd64 클라우드 이미지를 받아 `SHA256SUMS`와 대조한 뒤 public으로 올림. 같은 이름이 여럿이거나 `active`가 아니면 거부. 프로젝트 소유가 아닌 기존 이미지는 public으로 바꿈
- `keys.key_file`이 없으면 `ssh-keygen`으로 만듦

저장소는 uv 프로젝트입니다. 루트의 `pyproject.toml`에 플랫폼 의존성과 그룹 `dev`(pytest), `cloud`(`bin/cloud`가 쓰는 openstacksdk, python-openstackclient, python-heatclient)을 적고 `uv.lock`으로 고정합니다. `uv run`은 실행 전에 `.venv`를 lock에 맞추므로 `uv sync`를 따로 하지 않습니다. `bin/verify`, 플랫폼 VM의 `cr-venv`, sideload, platform 이미지는 같은 lock으로 `uv sync --frozen`을 씁니다.

이 파일을 쓰는 곳:

- `platform/range/cloud.py`: 파일 검사. 문제는 키별로 모두 보고. `clouds.yaml` 항목 읽기와 병합, init의 외부 네트워크·flavor 선택도 여기 있음
- `bin/platform-rebuild`, `bin/cloud`: 이 값과 `clouds.yaml` 항목으로 openstack CLI와 Heat 파라미터를 채워 실행. 스택을 배포하면 값이 플랫폼의 `openstack.env`에 기록됨. `bin/cloud`는 출력하는 줄마다 앞에 `HH:MM:SS`를 붙이고, API는 5초마다 물음

`bin/cloud up`은 스택이 정상이고 `--replace`가 없으면 플랫폼 VM을 그대로 씁니다(`resume`: ssh 대기, 인계가 안 됐으면 인계, API 대기). 스택이 없거나 `*_FAILED`거나 `--replace`면 플랫폼 VM을 새로 만듭니다(`rebuild`): ref 커밋의 이미지 일곱 개가 GHCR에 있는지 먼저 확인하고, 옛 VM의 DB를 백업하고 훈련 환경 키를 받아 둔 뒤 스택을 교체합니다. 훈련 환경 호스트는 스택에 속하지 않아 남습니다. 새 플랫폼은 훈련 환경 이미지 태그(`bin/range-image-tag`)와 번들 digest가 같으면 그 호스트와 슬롯을 그대로 쓰고, 새 `cr-reach` 포트를 붙이고 수집기와 시간 소스를 다시 맞춥니다. 다르면 `stale`로 보고 다시 부팅합니다.

새로 만들 때의 순서:

1. `keys.key_name`의 Nova 키페어 확인. 없으면 `<key_file>.pub`로 `openstack keypair create --public-key` 실행. 같은 이름의 키페어에 다른 공개키가 있으면 덮어쓰지 않고 키페어 이름을 출력한 뒤 중단(`bin/platform-rebuild`의 `ensure_keypair`)
2. 스택 생성

그다음은 두 경우 모두 같습니다(`converge`).

3. `POST /api/range/fabric/`. fabric이 어긋나 있으면 멈춤
4. `POST /api/range/slot/`: 훈련 환경 호스트 부팅 또는 교체. 슬롯이 blocked면 멈춤
5. 호스트가 뜨고 설치가 끝나면 `POST /api/range/configure/`. 설치가 `SETUP_FAILED`면 멈춤. configure가 503이면 5초 간격으로 최대 60번 다시 시도
6. `/api/range/ready/`에서 모든 슬롯이 READY가 될 때까지 대기
7. `DELETE /api/range/leftovers/`

`bin/cloud down`은 키를 남기고, 플랫폼 DB를 백업한 뒤(`bin/backup`, 사본은 `backups.keep`개까지) 슬롯, 훈련 환경 호스트, fabric, 스택을 지웁니다. 물어볼 플랫폼이 없으면(스택이 `*_FAILED`거나 VM에 플랫폼 DB 파일이 없음) 스택만 지우고 훈련 환경 호스트와 fabric은 프로젝트에 남깁니다.

`up`과 `down`의 예외 처리:

- 스택이 `*_FAILED`면 `up`은 지우고 다시 만듦(남은 빌더 서버부터). `down`은 스택만 지움
- VM에 플랫폼 DB 파일이 없으면 `down`과 `up --replace`에서 백업을 건너뜀
- VM에 ssh가 닿지 않거나 `docker ps`가 실패하면 거부
- 플랫폼 DB는 있고 `cr-platform` 컨테이너만 멈춰 있으면 `down`은 컨테이너를 시작해 백업함(`docker exec`로 실행). 그다음 API 응답을 기다렸다가 훈련 환경을 지움
- `up`은 API 응답과 상관없이 매번 VM 인계 여부를 확인. 인계 전 VM(`/opt/cr/openstack-password`가 없거나 비어 있음)이면 그 자리에서 인계
- 인계: 비밀번호와 훈련 환경 키를 넣음. 키가 없고 VM에 플랫폼 DB도 없으면 키를 새로 생성. VM에 플랫폼 DB가 없으면 행이 있는 가장 최근 백업을 복원

### 구축됨: 플랫폼 VM

Heat 템플릿 `deploy/openstack/platform.yaml`이 만드는 리소스:

- 네트워크와 서브넷 `cr-platform`
- 외부 네트워크로 나가는 라우터와 floating IP. `network.address`를 지정하면 프로젝트에 있는 floating IP를 연결만 함. 스택을 지워도 이 floating IP는 남음
- 보안 그룹: tcp/22, tcp/8000, tcp/8002는 `network.allowed`에서만, ICMP는 모든 주소에서 받음
- config drive를 붙인 Nova 서버 `cr-platform`

템플릿에는 기본값이 없습니다. 파라미터는 모두 `deploy/openstack/cloud.yaml`에서 받습니다([cloud.yaml](OPENSTACK.md#4-cloudyaml)).

플랫폼 VM의 cloud-init 작업:

- `docker.io`, `docker-compose-v2`, `git`, `nodejs`, `chrony`를 카카오 미러(`mirror.kakao.com`)에서 설치. `apt-get update`와 설치를 15초 간격으로 최대 10번 시도하고, 성공 여부는 설치 결과로 판단
- 스왑 4 GB 추가
- Docker MTU를 Neutron 네트워크 MTU에 맞춤. 기본 브리지는 `mtu`, compose가 만드는 것을 포함한 새 브리지 네트워크는 `default-network-opts`
- `repository`의 `ref`를 `/opt/cr`에 클론
- `/opt/cr/.env`에 `CR_IMAGE_TAG=<체크아웃의 커밋>`(플랫폼 이미지 태그)과 `CR_RANGE_IMAGE_TAG=<bin/range-image-tag 출력>`(훈련 환경 이미지 태그) 기록
- GeoIP DB 다운로드(`bin/fetch-geoip`). 자격 증명 불필요. Elastic GeoIP 엔드포인트는 URL에 약관 동의를 담으면 GeoLite2를 내려 줌
- `ubuntu`를 `docker` 그룹에 추가
- uv 0.13.8 설치. GitHub 릴리스 tarball을 받아 공개된 SHA-256과 대조한 뒤 `/usr/local/bin/uv`에 풀어 놓음
- 백그라운드 유닛 `cr-venv`에서 `/opt/cr/.venv` 생성. `uv sync --frozen --project /opt/cr --python /usr/bin/python3`. sideload 체크아웃 뒤에는 `bin/platform-rebuild`에서 같은 명령을 다시 실행

systemd 유닛 `cr-platform.service`는 부팅할 때마다 `compose.yaml`의 이미지를 pull하고 `docker compose -f /opt/cr/compose.yaml up -d`를 실행합니다.

- 유닛에 빌드 단계는 없음
- pull이 실패해도 유닛은 멈추지 않음(`ExecStartPre=-`). 이때 `up`은 없는 이미지를 체크아웃으로 빌드
- `bin/platform-rebuild`는 이런 빌드를 피하려고 ghcr.io를 먼저 확인

플랫폼 VM에서는 플랫폼 컨테이너(`compose.yaml`)만 돌립니다. board의 대상 시스템 데이터는 훈련 환경 호스트의 board 컨테이너 안에서 읽습니다.

포트:

- cloud-init에서 `CR_PUBLISH`를 VM 고정 주소로 설정. 8000, 8002가 그 주소에 publish되고 보안 그룹에서도 열림. 브라우저는 floating IP로 콘솔에 접속
- 보안 그룹 `cr-platform`은 ssh, 8000, 8002를 `cloud.yaml`의 `network.allowed`에 적은 네트워크에서만 받음. 기본은 `[0.0.0.0/0]`이고 `init`이 이 값을 씀
- `CR_SYSLOG_PUBLISH=0.0.0.0`: 훈련 환경 호스트의 syslog를 받으려고 5140/udp를 모든 주소에 publish
- 9200, 5601: loopback에만. Elasticsearch는 보안 기능 없이 돎

`openstack.env`:

- 템플릿 파라미터는 모두 `deploy/openstack/cloud.yaml`에서 받음(`bin/platform-rebuild`, `bin/cloud`)
- cloud-init이 그 값을 `CR_OPENSTACK_*`로 쓰고 `_PROJECT`(스택이 속한 프로젝트), `_SSH_USER=ubuntu`, `_SSH_KEY=/data/ssh/id_ed25519`를 더해 모드 0600의 `/root/openstack.env`로 저장. 그다음 git이 무시하는 `/opt/cr/openstack.env`로 옮김
- 비밀번호는 템플릿에 넣지 않음. Nova가 user data를 보관하고, 메타데이터 서비스는 플랫폼 컨테이너를 포함해 VM에서 도는 모든 것에 이를 내줌
- 프로젝트 비밀번호는 이 파일에 없음. cloud-init이 빈 `/opt/cr/openstack-password`(0600, uid 10001)를 만들고, VM이 뜬 뒤 `bin/platform-rebuild`가 ssh 표준 입력으로 그 파일을 채움. compose가 이 파일을 secret `openstack_password`로 플랫폼에 읽기 전용 마운트하고(`/run/secrets/openstack_password`), 플랫폼은 시작할 때 읽음. 컨테이너 환경 변수에는 없음. 훈련 환경용 ssh 키도 ssh로 플랫폼 데이터 볼륨에 씀(`README.md`)
- 플랫폼 서비스는 이 파일을 `env_file`(`required: false`, `format: raw`)로 읽음. compose는 변수 치환이나 따옴표 제거 없이 값을 그대로 넘김

VM 위의 플랫폼은 OpenStack 어댑터를 씁니다(cloud-init의 `CR_SUBSTRATE=range.openstack.connect`). 훈련 환경 네트워크는 `/api/range/fabric/`으로 만들고, 계획은 `range/fabric.py`에서 세웁니다.

- `mgmt`: DHCP 켬, 게이트웨이 없음. CIDR은 `cloud.yaml`
- `/data/ssh/id_ed25519` 키로 만드는 키페어 `cr-platform`
- 아래 보안 그룹 세 개

로더가 거부하는 CIDR:

- 서로 겹치는 CIDR
- 플랫폼 네트워크와 겹치는 CIDR
- Docker 기본 로컬 주소 풀(172.17.0.0/16~172.31.0.0/16, 192.168.0.0/16. moby `daemon/libnetwork/ipamutils/utils.go`)과 겹치는 CIDR
- `compose.yaml`에 선언된 네트워크, 선언된 출발지와 겹치는 CIDR
- 훈련 환경 호스트의 Docker 주소 풀 10.40.0.0/16(`cloud.RANGE_HOST_POOL`)과 겹치는 CIDR
- /16보다 좁은 `estate`

fabric이 만드는 네트워크는 `mgmt`뿐입니다. 슬롯의 `internet`과 `estate`는 Neutron 네트워크가 아니라 훈련 환경 호스트 위의 docker 네트워크입니다.

키는 첫 fabric POST 때 없을 경우에만 플랫폼에서 만듭니다. `bin/platform-rebuild`는 운영자 PC에 사본을 두고 새 플랫폼 VM마다 넣습니다. VM을 교체해도 키페어와 훈련 환경 호스트가 신뢰하는 키가 그대로입니다.

보안 그룹 세 개:

- `cr-reach`: 플랫폼 자신의 `mgmt` 포트. `cr-mgmt` 멤버의 NTP(udp 123)와 훈련 환경 호스트 `mgmt` 주소의 syslog(udp 5140)만 허용
- `cr-mgmt`: 훈련 환경 호스트의 `mgmt` 포트. `cr-reach` 멤버만 허용
- `cr-egress`: 훈련 환경 호스트가 이미지를 받을 때 쓰는 플랫폼 네트워크 쪽 포트. 인바운드 룰 없음. 설치하는 동안에만 있고, 설치가 ready를 알리면 플랫폼이 떼어 냄(`_close_egress`)

플랫폼은 자기 서버 id(부팅 때 기록하는 `CR_OPENSTACK_PLATFORM`)로 찾은 `cr-reach` 포트로 `mgmt`에 붙습니다. 플랫폼에서 훈련 환경 호스트로는 ssh할 수 있습니다. 반대 방향 연결은 NTP와 syslog뿐입니다.

훈련 환경에는 인터넷이 없어 시간 소스도 없습니다. 채점은 대상 시스템과 센서의 시각을 플랫폼 시계 기준의 케이스 시간 구간과 비교합니다. 그래서 시간은 플랫폼이 제공합니다.

- 플랫폼 VM에서 chrony 실행(cloud-init: `allow <network.mgmt>`, `local stratum 10`)
- 훈련 환경 호스트는 플랫폼의 `mgmt` 주소로 시간을 맞춤. `range/clock.py`에서 `systemd-timesyncd` drop-in을 쓰고 첫 응답을 기다림(`keep_time()`)
- 이 설정과 수집기 룰 열기는 훈련 환경 호스트 세대와 수집기 주소 조합마다 한 번만 함(`_heard_and_timed`). 재구축으로 수집기 주소가 바뀌면 다음 configure에서 둘 다 다시 적용
- 컨테이너는 호스트 시계를 그대로 씀

**훈련 환경 호스트.** VM `cr-range` 한 대에서 모든 슬롯을 돌립니다. 관리는 `/api/range/slot/`으로 하고, 계획은 `range/slot.py`에서 세웁니다.

`POST /api/range/slot/`은 이 VM이 없으면 부팅합니다.

- 이미지: 손대지 않은 Ubuntu 이미지(`compute.base_image`)
- flavor: `compute.flavors.range`(`CR_OPENSTACK_FLAVOR`)
- config drive, 키페어 `cr-platform`
- 포트 두 개: `mgmt` 위 `cr-mgmt` 소속의 `cr-range.mgmt`, 플랫폼 네트워크(`CR_OPENSTACK_BUILD_NETWORK`) 위 `cr-egress` 소속 포트
- 두 번째 포트는 설치가 ready를 알리면 떼어 냄. 설치가 끝난 호스트에는 `cr-range.mgmt`만 남고, 인터넷 경로도 DNS 리졸버도 없음

설치 번들은 Nova user data에 담습니다(`rangehost.bundle()`, `rangehost.user_data()`).

- 내용: `deploy/range-host/setup.sh`, 이미지 목록, Docker `daemon.json`, pristine 워게임의 compose 파일과 목록
- 인코딩한 user data는 Nova 한도 65,535바이트를 넘으면 안 됨

`setup.sh`의 작업:

- apt 소스를 카카오 미러(`mirror.kakao.com`)의 `main restricted universe`로 바꾸고, `snapd`와 `modemmanager`를 지운 뒤 다시 설치되지 않게 고정. dpkg 잠금은 600초까지 기다림
- `docker.io`, `docker-compose-v2`, `ethtool`을 설치. `apt-get update`와 설치를 15초 간격으로 최대 10번 시도하고, 성공 여부는 설치 결과로 판단
- sshd의 `MaxSessions`, `MaxStartups`와 inotify 한도를 올림
- `CR_RANGE_IMAGE_TAG`로 GHCR에서 이미지를 모두 pull
- 대상 시스템의 pristine 볼륨을 `/opt/cr/pristine`에 저장
- 끝나면 `setup.sh`를 호출한 user-data 스크립트가 `/var/lib/cr/ready`를 남김. 실패하면 `/var/lib/cr/failed`를 남기고 로그 끝부분을 콘솔에 찍음(`rangehost.user_data`)

설치 상태:

- 설치가 끝나기 전에는 플랫폼이 호스트 상태를 Nova의 `ACTIVE`가 아니라 `SETTING_UP`이나 `SETUP_FAILED`로 보고
- 설치가 실패하면 `/api/range/ready/`의 슬롯 단계가 `SETUP_FAILED`가 되고 호스트의 `/var/log/cr-setup.log`를 가리킴. `bin/cloud up`은 이유를 출력하고 멈춤
- 다음 `POST /api/range/slot/`에서 열린 세션이 없으면 설치에 실패한 호스트를 지우고 다시 부팅(`ensure_slot`)

Docker와 메타데이터:

- `daemon.json`: 테넌트 MTU(`mtu`, `default-network-opts`), /28 단위 주소 풀 10.40.0.0/16, `local` 로그 드라이버(`max-size` 10m, `max-file` 2), `userns-remap: default`
- 서버 메타데이터: `cr_host`, `cr_tag`(이미지 태그), `cr_bundle`(번들 digest). digest는 파일별 이름과 내용의 해시
- 태그나 digest가 플랫폼과 다르면 그 호스트는 `stale`. 열린 세션이 없으면 `POST /api/range/slot/`에서 VM을 지우고 다시 부팅. 세션이 열려 있으면 슬롯을 blocked로 보고
- Glance 이미지는 만들지 않음. 훈련 환경 호스트의 이미지는 GHCR에서만 pull

초기 데이터 사본은 `setup.sh`에서 한 번 만듭니다. 모든 워게임을 compose 프로젝트 `pristine`으로 띄우고, healthy가 되면 멈춥니다. 컨테이너별 볼륨을 `/opt/cr/pristine/<service><path>`로 복사한 뒤 `down -v`로 지웁니다.

**훈련 환경 슬롯.** 동시에 띄울 슬롯 수는 `cloud.yaml`의 `compute.slots`(기본 1, 플랫폼에서는 `CR_OPENSTACK_SLOTS`)입니다. `max_sessions`도 이 값입니다.

- 슬롯 N은 훈련 환경 호스트의 docker compose 프로젝트 `sN`. `platform/range/rangehost.py`에서 `deploy/range-host/slot.yaml`과 워게임별 `wargames/<w>/compose.yaml`로 렌더링
- 컨테이너: `sN-kali`, `sN-edge`, `sN-waf`, `sN-sensor`, `sN-board`, `sN-board-db`, `sN-corp-wp`, `sN-corp-db`, 관제용 `sN-log-server`, `sN-sensor-shipper`, `sN-waf-shipper`
- 네트워크: `sN_internet`(브리지 `sN-inet`. Docker 서브넷은 172.30.N.0/24지만 쓰지 않음. Kali는 출발지 주소 100개, 에지 `wan`은 121.134.88.42/29), `sN_estate`(브리지 `sN-estate`, 10.30.N.0/24: 에지 .1, WAF .247), `sN_web`(브리지 `sN-web`, 10.30.N+128.0/24: WAF .247, board .59, corp-wp .60), 워게임별 DB용 `<wargame>-default`, 관제망 `sN_mgmt`(브리지 `sN-mgmt`, 172.29.N.0/24: log-server .10, 센서 .11, WAF .12)
- 관제망을 뺀 모든 네트워크: `internal`, `gateway_mode_ipv4: isolated`, 테넌트 MTU. publish한 포트도 NAT도 없음
- 관제망만 밖으로 나가는 길이 있음. log-server가 훈련 환경 호스트의 NAT로 플랫폼 수집기에 보내기 때문. `slot.sh`가 네트워크를 만들기 전에 필터를 넣음: `INPUT`에서 `sN-mgmt`발 전부 drop(호스트에 닿지 않음), `DOCKER-USER`에서 `sN-mgmt` 안끼리와 log-server→수집기 5140/udp만 허용하고 나머지 drop. `down`이 이 룰을 지움
- 대상 시스템과 센서의 healthcheck: 평소 60초, 시작 구간 1초 간격(`slot.yaml`의 `x-wargames.healthcheck`가 워게임 자체 주기를 덮어씀). 쉬는 슬롯이 바쁜 슬롯에 CPU를 양보하게 하는 값
- 슬롯마다 `internet` 브리지에 같은 출발지 서브넷 30개가 올라감. 어느 슬롯에서든 경보 출발지가 같은 국가로 분류됨
- 슬롯 어댑터(`OpenStack.in_slot(n)`)는 자기 compose 프로젝트만 다룸. 역할, runner, 구성도는 모든 슬롯이 같음

세션과 슬롯:

- 세션을 열 때 세션을 슬롯 하나에 묶음(`Session.slot`, unique 제약으로 슬롯당 열린 세션 하나). 잠금을 잡고 비어 있으며 READY인 첫 슬롯을 고름
- 세션별 훈련 환경 호출은 모두 그 슬롯으로 감
- close 때는 그 슬롯만 초기화하고, 그 슬롯에서 비활성화한 룰만 다시 활성화. 초기화 상태도 슬롯별(`api/reset.py`)
- 룰 변경은 슬롯별 차례로 처리. 한 슬롯의 초기화가 다른 슬롯의 세션을 붙잡지 않음
- `run_on_role`은 `--session`이나 `--slot`을 받음. 슬롯이 둘 이상인데 둘 다 없으면 실행하지 않음
- `run_on_role`은 명령마다 새 프로세스라서 Django 시스템 체크를 건너뜀. 어댑터는 클라우드에 처음 물을 때 Keystone에 로그인하고, 클라우드를 읽을 때마다 훈련 환경 호스트의 관리망 주소와 호스트 키 별칭을 `CR_RANGE_HOST_SEEN`(`/data/range-host.json`)에 남김. 60초 안의 기록이 있으면 클라우드를 다시 읽지 않고 그 주소로 접속하고, 명령이 끝났다는 보고 없이 끊기면 기록을 지움
- 콘솔의 VM 터미널은 `?arg=<id>`(ttyd `-a`)로 세션을 받아 그 슬롯의 컨테이너를 엶

**configure.** `POST /api/range/configure/`(`configure_slot()`)의 처리:

- 수집기 룰 열기와 훈련 환경 호스트의 시간 소스 설정을 병렬로 처리. 둘 다 호스트 세대와 수집기 주소 조합마다 한 번만
- 슬롯 파일을 훈련 환경 호스트의 `slot.sh up N`에 넘김. compose 파일, 센서 설정, Kali와 에지의 주소, log-server와 shipper의 rsyslog 설정(`rsyslog/`), 관제망 출구(`uplink`), 기본 룰, 스크립트 자체

`slot.sh up`의 처리 순서:

1. 호스트 이름을 `/etc/hosts`에 넣고, `sensor-rules`, 센서·WAF 로그 디렉터리를 만듭니다. `sensor.yaml`, `sensor-rules`, 센서 로그 디렉터리는 remap된 root(dockremap) 소유, WAF 로그 디렉터리는 호스트 root 소유로 둡니다.
2. WAF 로그 디렉터리 `/var/log/cr/sN/waf`에서 일반 파일 `audit.log`와 `refused.log`만 남기고 모두 지웁니다. 없는 파일은 remap된 범위의 `www-data`·`adm` 소유(`0644`)로 만듭니다. 컨테이너 안에서 root로 도는 nginx 마스터가 파일을 열고, WAF shipper가 읽기 전용 마운트로 읽습니다.
3. 관제망 필터를 넣습니다(위 "관제망만 밖으로"). 그다음 컨테이너를 만들고(`up --no-start --pull never`), 한 번도 실행하지 않은 대상 시스템의 빈 볼륨마다 초기 데이터를 복사합니다.
4. 컨테이너를 띄웁니다(`up -d --wait`). 그다음 센서, log-server, shipper를 `--force-recreate`로 다시 만들어 방금 쓴 설정을 읽게 합니다. Suricata는 출력 설정을 시작할 때만 읽습니다.
5. Kali에 출발지 주소들과 라우터 공인 IP로 가는 onlink default route(출발지는 기본 출발지 주소 5.188.10.10)를 붙입니다. 에지의 `wan`에는 공인 IP 하나와 Kali의 기본 출발지 주소(5.188.10.10)로 가는 onlink default route를 붙이고(`nsenter`로 `ip -batch`), 포트포워딩과 인바운드 필터 룰 `edge.nft`를 에지 안의 `nft -f`로 넣습니다. 출발지 대역으로 가는 응답은 모두 이 default route로 Kali에 갑니다.
6. WAF가 에지의 estate 주소로 라우팅하게 합니다. 대상 시스템에는 default route가 없고 WAF에만 응답합니다.
7. `sN-inet`, `sN-estate`, `sN-web` 브리지와 그 포트, Kali·에지·WAF·대상 시스템의 인터페이스에서 TSO, GSO, GRO를 끕니다(관제망은 제외). 센서가 실제로 오간 그대로의 패킷을 보게 합니다.
8. `DOCKER-USER`에 브리지별로 같은 브리지로의 forward 허용 룰을 넣습니다.
9. 센서 미러링(SPAN)을 겁니다(`mirrored`). 먼저 `sN-inet`, `sN-estate` 포트에 남은 `tc` 설정을 지웁니다. 센서의 `web` 주소를 지우고, `sN-web`의 다른 포트마다 ingress `tc` `matchall` → `mirred egress mirror dev <센서 포트>`. 센서 포트는 learning, flood를 끄고 ingress를 drop해 받기만 함. 초기화 때 새로 만든 컨테이너의 포트에도 다시 겁니다.

그 뒤 플랫폼이 `rules/suricata.py`로 센서에 기본 룰을 넣습니다.

**에지.** `sN-edge`(`deploy/edge/`)는 nftables를 넣은 Alpine 컨테이너입니다.

- capability는 `NET_ADMIN`뿐
- `wan`은 `sN-inet`, `lan`은 `sN-estate`에 붙음
- `wan` 주소는 공인 IP 121.134.88.42/29 하나. default route는 Kali의 5.188.10.10(onlink)
- 공인 IP 80번 포트를 WAF estate 주소로 DNAT. `rp_filter`를 끄고 출발지 NAT 없이 forward. 출발 국가 주소가 그대로 WAF까지 감
- `wan`에서 새로 들어오는 연결은 DNAT된 것만 forward. 사설 주소로 가는 연결은 drop(슬롯의 `edge.nft`)
- `deploy/edge/edge.nft`: input은 loopback 외 drop, forward는 accept. 슬롯의 `edge.nft`가 별도 테이블에서 `wan` 인바운드를 거름

**Kali.** 모든 출발지를 Kali 이미지 하나로 처리합니다.

- `slot.sh`에서 국가별 주소 약 100개를 `eth0`에 붙임
- `/usr/local/sbin/set-origin`이 컨테이너의 출발 주소를 국가별로 SNAT. 어떤 도구든 고른 국가에서 나감
- 마커를 붙이는 프록시가 컨테이너의 메인 프로세스
- 등록된 이름은 `board.com`과 `corp.com`. 둘 다 라우터의 공인 IP(`slot.yaml`의 `@router@`, `rangehost.ROUTER_WAN`으로 채움)

**센서.** 슬롯마다 Suricata 하나(`sN-sensor`, digest 고정 `jasonish/suricata`)가 WAF 뒤 웹 서버 구간을 봅니다. `NET_ADMIN`, `NET_RAW`, `SYS_NICE`로 돕니다(다른 컨테이너처럼 `userns-remap`). 인터페이스는 둘: 감시용 `web`(`sN-web`, WAF↔웹 서버, 주소 없음), 관리용 `mgmt`(관제망 .11). 에지와 WAF 사이 `sN-estate`와 인터넷 쪽 `sN-inet`에는 센서가 없음. WAF가 막은 요청은 센서에 닿지 않고 WAF 로그에 남음.

- 설정은 `deploy/suricata/suricata.yaml`. `--af-packet`이면 설정의 af-packet 항목을 모두 엶. 이벤트의 `in_iface`가 본 구간이고, 언제나 `web`
- 센서가 보는 요청의 출발지는 WAF. http 기록의 `xff`에 클라이언트 주소가 남고, ingest가 이 주소를 경보의 출발지로 씀("경보의 경로" 절)
- `/var/lib/suricata/rules/local.rules`에서 룰을 읽고 `suricatasc -c reload-rules`로 reload. 이 경로와 명령은 호스트 항목 `cr-range`에 있음
- 룰 파일 하나, reload 하나. 룰 넣기, 검증, 변경, 기준선 검사도 이 센서 하나에 함
- EVE 경보와 HTTP 기록: `/var/log/cr/sN/sensor/eve.json`

**로그.** WAF는 훈련 환경 호스트의 `/var/log/cr/sN/waf`에 두 파일을 씁니다.

- `audit.log`: ModSecurity audit 로그
- `refused.log`: nginx가 400으로 거부한 요청. ModSecurity가 돌기 전, 헤더를 읽기 전에 거부한 요청이 남음. 예: `/static/..%2F..%2F..%2F..%2Fetc/passwd`처럼 잘못된 경로. `deploy/waf/board.com.conf`의 `map $status $refused`와 `log_format refused`로 JSON 한 줄씩(`time`, `client_ip`, `request`, `status`)
- WAF의 호스트 경로 마운트는 이 두 파일이고, 마운트 대상도 이 파일뿐
- 디렉터리가 root 소유라, WAF 안의 root는 호스트 root 프로세스가 따라갈 링크를 그 안에 만들 수 없음(`docs/THREAT-MODEL.md`)
- 로그 서버 `sN-log-server`(digest 고정 `rsyslog/rsyslog-minimal`)가 관제망에서 514/tcp로 받아 플랫폼 `mgmt` 주소의 5140으로 UDP 전달(`rangehost.forwarding`, `/opt/cr/sN/rsyslog/log-server.conf`)
- 장비마다 shipper(같은 이미지, `imfile`)가 그 장비의 로그 파일을 읽어 log-server로 보냄. shipper는 로그를 쓴 장비의 네트워크 네임스페이스를 같이 씀(`network_mode: service:sensor`, `service:waf`). 그래서 로그는 센서와 WAF 자신의 관제망 인터페이스로 나감. WAF는 관제망 .12
- WAF shipper는 두 파일을 각자의 태그로 읽음: `audit.log`는 `modsecurity`, `refused.log`는 `nginx`. 센서 shipper의 태그는 `suricata`
- log-server는 보낸 주소(`$fromhost-ip`)와 태그(`$programname`)가 둘 다 맞는 줄만 넘김. 송신자마다 자기 로그의 태그만 통과하므로 WAF 안의 root가 Suricata 기록인 척 줄을 보낼 수 없음
- 넘길 때 송신자 이름과 태그는 log-server가 정한 값으로 씀. 슬롯 1은 `cr-range`(센서), `cr-waf`. 슬롯 N은 `cr-range-N`, `cr-waf-N`. Filebeat의 슬롯 정규식이 이 이름으로 슬롯을 읽음
- shipper와 log-server는 capability 없음(`cap_drop: ALL`), 마운트는 모두 읽기 전용

**격리.** 학습자가 만지는 컨테이너(Kali, WAF, 에지, 대상 시스템)는 `cap_drop: ALL`에 필요한 capability만 더해 돌립니다.

| 컨테이너 | capability |
|---|---|
| `kali` | `NET_RAW`, `NET_ADMIN`, `SETUID`, `SETGID`, `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `AUDIT_WRITE` |
| `waf` | `NET_BIND_SERVICE`, `SETUID`, `SETGID`, `CHOWN`, `DAC_OVERRIDE` |
| `edge` | `NET_ADMIN` |
| `board`, `board-db`, `corp-db` | `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETUID`, `SETGID` |
| `corp-wp` | 위와 같고 `NET_BIND_SERVICE` 추가 |

- 모두 `no-new-privileges`, Docker 기본 seccomp·AppArmor 프로파일, 메모리·pids 한도
- privileged 컨테이너, Docker 소켓 마운트, 호스트 network·pid·ipc 네임스페이스 공유는 없음. 호스트 경로 마운트는 WAF의 로그 파일 두 개(`audit.log`, `refused.log`)
- dockerd는 `userns-remap`. 컨테이너 안의 root는 호스트에서 권한 없는 사용자. 호스트 user namespace를 쓰는 컨테이너는 없음
- 센서, 로그 서버와 shipper, 에지에는 학습자 셸이 없음
- 학습자가 만지는 컨테이너 중 관제망에 붙는 것은 WAF뿐. `NET_RAW`, `NET_ADMIN`이 없어 다른 주소로 보낼 수 없고, log-server는 보낸 주소로 송신자를 정함
- 렌더링한 슬롯 compose 파일이 이 중 하나라도 어기면 `platform/tests/test_containment.py`에서 `bin/verify` 실패
- 실환경 검사는 `test/test_range_isolation.py`

**초기화.** `POST /api/sessions/<id>/close/`는 슬롯을 그 자리에서 초기화합니다. VM은 재구축하지 않습니다.

- `reset_in_place()`에서 `slot.sh reset N` 실행. reset은 모든 워게임을 다시 띄워 어느 워게임 세션이든 받을 수 있게 함
- 세션을 열 때 `play(<워게임>)`이 `slot.sh play N <서비스...>`를 실행해 그 워게임의 서버와 DB만 남기고 다른 워게임 컨테이너를 멈춤(`compose kill`. 초기화 때 볼륨째 지우므로 정상 종료를 기다리지 않음)
- Kali와 WAF는 이미지에서 새로 만듦. 동시에 대상 시스템은 볼륨째 지우고 초기 데이터로 다시 띄움
- 에지의 neighbour 테이블을 비우고, 슬롯 로그 파일(센서 `eve.json`, WAF `audit.log`와 `refused.log`)을 그 자리에서 비우고, 센서가 로그 파일을 다시 열게 함. shipper는 비워진 파일을 처음부터 다시 읽음(`reopenOnTruncate`). WAF shipper는 WAF와 함께 새로 만듦
- 새로 만든 컨테이너의 브리지 포트에 미러링을 다시 검
- 그 뒤 플랫폼이 센서에 기본 룰을 다시 넣음
- 에지, 센서, 로그 서버, 센서 shipper는 내리지 않음
- 슬롯 파일이 훈련 환경 호스트에서 사라졌으면(`/opt/cr/sN/compose.yaml` 없음) 초기화 대신 슬롯을 configure
- 앞 세션에서 수정한 룰이나 심어 둔 데이터는 다음 세션에 남지 않음

슬롯 내리기:

- `POST /api/range/slot/rebuild/`(`rebuild_slot()`): `slot.sh down N`. `compose down -v`를 하고 관제망 필터, 슬롯 파일, 로그를 지움. 다시 올리는 것은 `POST /api/range/configure/`
- `DELETE /api/range/slot/`: 모든 슬롯을 내림. `?slot` 없이 부르면 훈련 환경 호스트와 그 `mgmt` 포트까지 지움

모든 세션은 같은 초기 데이터에서 시작하지만 비밀 값은 새로 만듭니다.

- board의 `seed`는 시작할 때마다 시드 계정의 비밀번호를 다시 설정. 세션마다 해시의 salt가 바뀌어, 한 세션에서 훔친 해시는 다음 세션의 대상 시스템 데이터와 맞지 않음
- board의 `seed`는 시드 글의 날짜도 오늘로 옮김
- corp의 entrypoint는 이미지 entrypoint가 돌기 전에 `wp-config.php`를 지움. 이미지가 무작위 키와 salt로 새 파일을 씀
- corp는 복원한 데이터에서 관리자 비밀번호도 다시 설정해 해시를 새로 만듦. 설치와 플러그인 설정은 복원한 DB에 있으므로 건너뜀

세션을 닫으면 플랫폼이 초기화합니다.

- `platform/api/reset.py`가 백그라운드 스레드를 띄우고, 룰 잠금을 한 번 잡은 채 초기화 실행
- 훈련 환경 호스트가 ssh에 응답하지 않는 동안은 최대 30분까지 재시도. 처음 발생한 실패가 초기화 실패
- close는 즉시 응답. 초기화 상태(idle, running, failed와 이유)는 플랫폼 프로세스에 보관
- 초기화를 시작한 때부터 성공할 때까지 `CR_RESET_OWED_DIR`(`/data/reset-owed`)에 `slot-N` 파일이 남음
- 부팅할 때 `cr/wsgi.py`가 이 파일이 남은 슬롯마다 close와 똑같이 초기화를 다시 함. 재시작해도 슬롯이 세션을 거부하는 상태로 남지 않음
- 초기화가 실패하면 파일은 그대로 둠
- 수동 재시도는 `POST /api/range/configure/`. 실패한 초기화 상태도 이것으로 지워짐

**준비 상태.** 모든 슬롯이 사용 중이거나 빈 슬롯 중 준비된 것이 없으면 세션 생성은 409입니다.

`GET /api/range/ready/`는 `slots` 아래에 슬롯별로 다음을 보고합니다.

- 번호와 그 슬롯을 잡은 세션
- 단계: 세션이 잡고 있으면 `IN_USE`, 초기화 중이면 `RESETTING`, 초기화가 실패했으면 이유와 함께 `RESET_FAILED`
- 그 밖의 단계: `NOT_STANDING`, `STALE`(플랫폼보다 오래된 이미지나 슬롯 파일로 도는 호스트), `SETUP_FAILED`(호스트 설치 실패. 이유는 그 호스트의 `/var/log/cr-setup.log`), `REBUILDING`(호스트가 아직 `ACTIVE`가 아니거나 설치가 안 끝남), `CHECKING`, `READY`
- 초기화 상태
- 검사 세 가지: 호스트가 ACTIVE이고 설치가 끝났는지, board의 대상 시스템 데이터를 읽을 수 있는지, 센서 룰이 기준선이고 그 슬롯에 비활성화한 룰이 없는지

최상위의 `ready`와 `slot`은 다음 세션에 배정될 슬롯입니다. 슬롯이 둘 이상이면 슬롯 검사를 병렬로 돌립니다.

`/api/range/slot/`, `slot/rebuild/`, `configure/`는 `?slot=N`을 받습니다. 없으면 모든 슬롯에 적용합니다.

`POST /api/range/canary/`는 마커를 붙인 요청 두 개를 보냅니다. 먼저 WAF가 막는 SQLi 요청, 바로 뒤에 WAF가 통과시키는 `/search/?q=canary`입니다. ModSecurity가 첫 요청에 경보를 내고 Suricata가 둘째 요청의 http 기록을 남겼는지, 둘의 시계 차이가 기준 안인지 보고합니다. 센서는 WAF 뒤에 있어 막힌 요청을 보지 못하기 때문입니다. 준비 상태 검사에는 들어가지 않습니다. 첫 화면에서 둘 다 호출합니다.

**남은 자원.** `GET /api/range/leftovers/`는 훈련 환경 호스트 도입 전의 VM 훈련 환경이 프로젝트에 남긴 자원을 나열하고, `DELETE`로 지웁니다.

- 대상: `cr_host` 메타데이터로 찾은 슬롯 VM, 이미지 빌더, 폐기한 구간의 포트·서브넷·네트워크, 보안 그룹 `cr-range`와 `cr-build`, `cr_bundle` 속성이 있는 프로젝트 이미지
- `DELETE`는 `bin/cloud up` 마지막 단계에서 호출

### OpenStack 훈련 환경: 목표 구조

사용자가 2026-09-30에 정하고 2026-10-08에 바꾼 구조입니다. 역할마다 VM을 두지 않고, 훈련 환경 호스트 한 대에서 모든 슬롯을 컨테이너로 돌립니다.

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
     edge: nftables router; its wan holds one public address,
           121.134.88.42/29 (board.com and corp.com resolve to it),
           port-forwards tcp 80 to the waf (DNAT, no SNAT), so
           country sources survive; default route to kali's 5.188.10.10
       |
       v
   sN_estate (bridge sN-estate, 10.30.N.0/24): edge lan, waf
     waf: nginx + ModSecurity v3 + CRS
          (SecRuleEngine On; the learner tunes CRS to block)
       |
       v
   sN_web (bridge sN-web, 10.30.N+128.0/24): waf, board, corp-wp
     board (+ board-db on board-default), corp-wp (+ corp-db on corp-default)
   sensor (Suricata): sniffs sN-web (web) only, behind the WAF, no address,
     tc mirred from every other port of that bridge; eve-log xff on

 Evidence (sN_mgmt 관제망 172.29.N.0/24, then the range host's NAT and mgmt):
   sensor eve.json -- shipper in the sensor --+-- 514/tcp --> log-server -- 5140/udp --> Filebeat
   waf audit log, ---- shipper in the WAF ----+                                              |
   nginx refused.log                                                                         |
                                                                                             v
   Elasticsearch --> platform ingest --> scoring
   Elasticsearch ----------------> Kibana --> blue team
```

차단은 구축했습니다. WAF는 `SecRuleEngine On`으로 돌고, 학습자는 WAF 터미널이나 `PUT /api/sessions/<id>/waf/`로 CRS를 조정합니다.

- 실행한 케이스의 `meta["blocked"]`는 대상 시스템이 아니라 403 응답으로 정함. 예정된 sqlmap 공격은 주입 불가로 끝나도 `blocked`("점수 계산 방식" 절)
- 시작 paranoia level은 2026-10-10에 측정(`docs/DECISIONS.md`). PL1만으로도 board의 SQLi는 차단되고 O'Brien은 통과
- 그래서 과차단하도록 만든 방어 설정은 PL1보다 높은 단계에서 시작(시나리오의 `level2`, `level3`). 학습자는 PL을 낮추거나 임계치, 예외 규칙을 조정

남은 작업:

- 세션 수명 주기: WAF 모드와 시계 차이를 준비 상태 검사에 넣기

사람이 결정해야 할 남은 사항은 `docs/STATE.md`에 있습니다.
