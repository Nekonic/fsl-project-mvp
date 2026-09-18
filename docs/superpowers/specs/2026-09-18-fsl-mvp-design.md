# fsl-project-mvp 설계

작성일: 2026-09-18

## 1. 목적

사이버 공방 훈련 플랫폼의 가설 검증용 MVP. 메인 프로젝트는 별도 레포.

검증할 가설:

> 레드팀 공격에 ground truth 라벨을 붙일 수 있고, Suricata·ModSecurity 경보를
> 그 라벨에 자동 대응시켜 오탐/미탐을 기계적으로 채점할 수 있다.

이 고리가 돌지 않으면 OpenStack 온디맨드 인스턴스도, 다중 워게임 앱도,
사람 자리를 대체할 에이전트도 의미가 없다. 따라서 MVP는 이 고리만 만든다.

## 2. 범위

### 포함

- 단일 호스트 Docker Compose 스택 (방어 대상 + WAF + IDS + 로그 파이프라인 + 플랫폼)
- 레드팀 공격 하니스와 ground truth 기록
- 오탐·미탐 채점 엔진과 REST API
- 블루팀 콘솔 (룰 조회·편집·검증·반영, 스코어 조회)
- 완료 기준 검증 테스트

### 제외

- OpenStack Heat 템플릿. compose 스택을 얹은 VM 하나를 감싸는 얇은 층이라
  가설 검증에 기여하지 않는다. 가설이 서면 메인 레포에서 만든다.
- Juice Shop 외의 워게임 앱. `wargame/` 디렉터리 구조로 자리만 비워둔다.
- 사용자 인증·다중 테넌시·세션 격리. MVP는 단일 사용자 단일 세션.
- 에이전트. 구조 원칙("화면 동작은 전부 REST API가 먼저")으로 자리만 확보한다.

## 3. 핵심 설계 — ground truth 대응

채점이 성립하려면 "이 경보가 저 공격에 대한 것"이라는 대응 관계가 필요하다.
시간창만으로 맞추면 동시 트래픽에서 무너진다. 두 단계로 해결한다.

### 3.1 마커 헤더 (주 경로)

레드팀 하니스가 모든 HTTP 요청에 `X-FSL-Case: <case_id>` 헤더를 주입한다.

- ModSecurity: 감사 로그(JSON)가 요청 헤더 전체를 남기므로 경보에서 바로
  꺼낸다.
- Suricata: `eve-log` 의 `http` 출력에 `dump-all-headers: request` 를 설정하면
  헤더가 **http 이벤트**에 실린다. 그러나 **alert 이벤트는 HTTP 요청 헤더를
  담지 않는다.** 그래서 경보를 같은 트랜잭션의 http 이벤트와 짝지어
  마커를 가져온다.

실측으로 확인한 것 세 가지 (Suricata 8.0.7):

1. `custom: [X-FSL-Case]` 는 아무 효과가 없다. `dump-all-headers: request`
   는 동작한다.
2. alert 이벤트와 그 http 이벤트는 `tx_id` 로 정확히 짝지어진다.
3. **조인 키는 `flow_id` 가 아니라 `(flow_id, tx_id)` 다.** HTTP keep-alive
   에서는 TCP 흐름 하나 위로 요청 수십 개가 흐른다. `flow_id` 만으로 조인하면
   흐름의 첫 마커가 그 흐름의 모든 경보에 붙어 전부 엉뚱한 케이스로 귀속된다.
   점수는 그럴듯해 보이면서 조용히 거짓이 된다 — MVP 에서 실제로 겪었고,
   ModSecurity 경보가 마커를 직접 실어 나르는 덕에 점수가 그럴듯해 보여
   한참 보이지 않았다.

요청 하나가 경보 둘을 낳을 수 있다. Suricata 가 WAF 의 네임스페이스 안에서
공격자→WAF 와 WAF→juice-shop 두 다리를 모두 보기 때문이다. 채점은 케이스
단위로 접으므로 문제되지 않는다.

ModSecurity 감사 로그의 `time_stamp` 는 ISO 가 아니라 ctime 형식
(`Fri Sep 18 15:25:02 2026`)이다. 시간대가 없어 UTC 로 읽는다.

### 3.3 요청이 선언대로 나가는지

`requests` 는 `/ftp/../../../../etc/passwd` 를 전송 전에 `/etc/passwd` 로
정규화한다. 공격이 나가지 않았는데 ground truth 에는 "공격을 보냈다" 고
남으면 채점이 거짓말을 한다 — 미탐으로 집계되지만 실제로는 방어가 아니라
하니스가 실패한 것이다.

하니스는 요청을 보내기 전에 선언한 경로와 실제로 나갈 경로를 비교하고,
다르면 예외를 던진다. 퍼센트 인코딩의 표기 차이(`%2e` → `.`, `%2f` → `%2F`)는
RFC 3986 상 같은 경로이므로 무시하고, `..` 세그먼트가 사라지는 구조적
재작성만 잡는다.

한계를 명시한다: 실제 공격자는 마커를 달아주지 않는다. 그러나 ground truth를
생성하는 쪽은 플랫폼이 통제하므로 성립한다. 이는 훈련 환경의 채점 장치이지
탐지 기법이 아니다.

### 3.2 시간창 + 출발지 IP (보조)

HTTP가 아닌 케이스(nmap 포트스캔 등)는 헤더를 주입할 수 없다.
케이스의 `started_at`/`ended_at` 구간과 출발지 IP로 대응시킨다.
구간은 앞뒤 2초 여유를 둔다.

케이스 하나는 두 전략 중 하나만 쓴다. 케이스 정의에 `correlation: marker|window`
로 명시한다. 암묵적 폴백은 두지 않는다 — 마커가 붙었어야 할 케이스에서
마커가 사라진 것을 시간창 대응이 조용히 덮어버리면 버그가 보이지 않는다.

## 4. 채점

케이스 단위로 접는다. 케이스 하나가 요청 여러 개를 보내도 판정은 하나다.

|              | 경보 있음 | 경보 없음 |
|--------------|-----------|-----------|
| malicious    | TP        | FN (미탐) |
| benign       | FP (오탐) | TN        |

산출 지표: precision, recall, F1, false positive rate, 그리고 원시 TP/FP/FN/TN.

**benign 케이스는 선택이 아니라 필수다.** 정상 트래픽 케이스가 없으면
"전부 차단"하는 룰이 만점을 받는다. 오탐을 채점하는 것이 이 플랫폼의 존재
이유이므로, 케이스 파일에 정상 트래픽을 1급 시민으로 넣는다. 스코어 API는
benign 케이스가 0건이면 경고 필드를 실어 보낸다.

경보의 severity나 룰 종류는 MVP에서 채점에 쓰지 않는다. "경보가 났는가"만
본다. 가중치는 가설이 선 뒤에 붙인다.

## 5. 아키텍처

```
redteam 하니스 ──공격/정상 요청 + X-FSL-Case──▶ nginx+ModSecurity+CRS ──▶ juice-shop
      │                                                  │
      │ POST 케이스 (ground truth)              Suricata (인터페이스 스니핑)
      ▼                                                  │
  platform (Django + DRF)  ◀── Filebeat ─▶ Elasticsearch ◀─ EVE JSON / ModSec audit
      ▲                                                  │
  blueteam 콘솔 ──룰 편집 / 검증 / 반영 / reload──────────┘
```

데이터 흐름:

1. 레드팀이 세션을 열고 케이스를 실행. 각 케이스 실행 전후로 platform에
   ground truth를 POST.
2. 요청이 nginx(ModSecurity)를 지나 juice-shop에 도달. Suricata가 같은
   트래픽을 스니핑.
3. Suricata EVE JSON과 ModSecurity 감사 로그를 Filebeat이 Elasticsearch로.
4. platform이 채점 요청을 받으면 ES를 조회해 Detection을 끌어오고,
   케이스와 대응시켜 스코어를 계산.
5. 블루팀이 콘솔에서 룰을 고치고 반영하면 다음 실행의 스코어가 달라진다.

## 6. 컴포넌트

### 6.1 platform — Django + DRF

`platform`은 채점, 룰 검증·반영, API 제공을 맡는다.

모델:

- `Session` — 훈련 세션 하나. `started_at`, `ended_at`, `scenario`.
- `Case` — ground truth 한 건. `session`, `case_id`(uuid), `name`,
  `malicious`(bool), `technique`, `correlation`(marker|window),
  `source_ip`, `started_at`, `ended_at`, `meta`(json).
- `Detection` — ES에서 끌어온 경보 한 건. `session`, `source`(suricata|modsecurity),
  `signature`, `severity`, `timestamp`, `src_ip`, `marker`, `raw`(json).
- `RuleSet` — Suricata 룰 파일의 한 버전. `content`, `created_at`, `applied_at`,
  `validation_output`.
- `Score` — 계산 결과 스냅샷. `session`, `tp/fp/fn/tn`, `precision`, `recall`,
  `f1`, `computed_at`, `per_case`(json).

API (`/api/`):

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST   | `/sessions/` | 세션 시작 |
| GET    | `/sessions/{id}/` | 세션 조회 |
| POST   | `/sessions/{id}/close/` | 세션 종료 |
| POST   | `/sessions/{id}/cases/` | 케이스(ground truth) 기록 |
| GET    | `/sessions/{id}/cases/` | 케이스 목록 |
| POST   | `/sessions/{id}/ingest/` | ES에서 Detection 수집 |
| GET    | `/sessions/{id}/score/` | 채점 결과 (수집 후 계산) |
| GET    | `/sessions/{id}/detections/` | 수집된 경보 목록 |
| GET    | `/rules/` | 현재 룰셋 |
| POST   | `/rules/validate/` | `suricata -T` 로 문법 검증 (반영 없음) |
| POST   | `/rules/apply/` | 검증 통과 시 파일 기록 + Suricata reload |

내부 구조는 관심사별로 쪼갠다.

- `platform/scoring/correlate.py` — 케이스 ↔ Detection 대응. 순수 함수.
  입력은 케이스 리스트와 Detection 리스트, 출력은 케이스별 매칭 결과.
  ES도 DB도 모르며, 따라서 스택 없이 단위 테스트가 된다.
- `platform/scoring/metrics.py` — 매칭 결과에서 TP/FP/FN/TN과 지표 계산.
  역시 순수 함수.
- `platform/ingest/elastic.py` — ES 조회와 Detection 정규화. 여기만 ES를 안다.
- `platform/rules/suricata.py` — 룰 검증(`suricata -T`)과 reload.
  여기만 Suricata 프로세스를 안다.

`suricata` 바이너리는 platform 컨테이너에 없다. platform은 Docker 소켓을
읽기 전용으로 마운트받아 `docker exec suricata suricata -T -S <후보파일>` 로
검증하고, 통과하면 룰 파일을 bind mount에 쓴 뒤 같은 방식으로 reload 한다.

Docker 소켓 마운트는 컨테이너 탈출 경로다. 로컬 훈련 랩이라 감수하지만
메인 레포에서는 Suricata 쪽에 룰 검증·반영만 노출하는 작은 사이드카를
두어 걷어내야 한다. `platform/rules/suricata.py` 한 파일에 가둬 둔 이유가
이것이다 — 교체 지점이 한 곳이어야 한다.

채점 로직(`correlate` + `metrics`)이 I/O를 전혀 모르는 것이 이 설계의 핵심이다.
가설의 본체가 그 두 파일에 있고, 스택 없이 검증할 수 있어야 한다.

### 6.2 redteam — 공격 실행과 ground truth

`redteam/cases/*.yaml` 에 케이스를 선언한다.

```yaml
- name: sqli-login-bypass
  malicious: true
  technique: SQLi
  correlation: marker
  request:
    method: POST
    path: /rest/user/login
    json: {email: "' OR 1=1--", password: "x"}

- name: normal-product-search
  malicious: false
  technique: null
  correlation: marker
  request:
    method: GET
    path: /rest/products/search
    params: {q: "apple juice"}
```

`redteam/run.py` 가 케이스를 읽어 세션을 열고, 케이스마다
`X-FSL-Case` 헤더를 붙여 요청을 보내고, ground truth를 platform에 POST한다.
외부 도구(sqlmap, nmap)는 `tool:` 필드로 선언하며 MVP에서는
sqlmap만 지원한다 — `--headers` 로 마커 주입이 가능하기 때문.

케이스 파일은 공격과 정상 트래픽을 같은 파일에 섞어 둔다. 분리하면
정상 트래픽을 빠뜨리기 쉽다.

### 6.3 blueteam — 방어자 콘솔

platform의 Django 앱. Tailwind CSS(CDN, MVP 한정).

화면 셋:

1. 스코어 — TP/FP/FN/TN, 지표, 케이스별 판정 표. 미탐/오탐 케이스 강조.
2. 경보 — 수집된 Detection 목록, 케이스 대응 여부.
3. 룰 — Suricata 룰 편집기. 검증 → 결과 표시 → 반영.

모든 화면은 자기 자신의 REST API를 호출한다. 템플릿이 ORM을 직접 쓰지 않는다.
이게 "나중에 사람 자리에 에이전트가 들어온다"는 원칙을 강제하는 방법이다.

### 6.4 deploy — 스택 설정

`compose.yaml` 서비스:

| 서비스 | 이미지 | 역할 |
|--------|--------|------|
| juice-shop | bkimminich/juice-shop | 방어 대상 |
| waf | owasp/modsecurity-crs:nginx | 리버스 프록시 + WAF |
| suricata | jasonish/suricata | IDS |
| elasticsearch | elasticsearch:8 | 로그 저장 |
| kibana | kibana:8 | 로그 조회 |
| filebeat | elastic/filebeat:8 | 로그 수집 |
| platform | 로컬 빌드 (Django) | 채점·API·콘솔 |

- Suricata는 `network_mode: "service:waf"` 로 WAF 컨테이너의 네트워크
  네임스페이스에 들어가 그 `eth0` 을 스니핑한다. `NET_ADMIN`/`NET_RAW` 필요.
  `network_mode: host` 는 쓰지 않는다 — Docker Desktop(macOS)에서는 호스트가
  아니라 Linux VM의 네임스페이스에 붙어 동작이 플랫폼마다 달라진다.
  WAF의 `eth0` 에는 공격자→WAF 와 WAF→juice-shop 양쪽 다리가 모두 흐르므로
  필요한 트래픽을 전부 본다. VM 안에서 컨테이너를 돌리면 Neutron 포트
  미러링이 불필요하다는 판단과 같은 논리를 컨테이너 층에 한 번 더 적용한 것.
- Elasticsearch는 단일 노드, 보안 비활성(MVP 한정). `discovery.type=single-node`,
  `ES_JAVA_OPTS=-Xms512m -Xmx512m`. Docker Desktop 기본 메모리에서 스택
  전체가 떠야 한다.
- Filebeat은 EVE JSON과 ModSec 감사 로그를 볼륨으로 공유받아 읽는다.
  GeoIP는 ES ingest pipeline으로. Logstash 없음.
- 룰 파일과 로그는 named volume이 아니라 bind mount로 둔다.
  platform이 룰을 쓰고 Suricata가 읽어야 하므로.

## 7. 오류 처리

- ES가 아직 안 떴거나 인덱스가 없음 → `/ingest/` 가 503과 사유를 반환.
  채점을 0점으로 만들지 않는다. 데이터 없음과 탐지 실패는 다르다.
- 룰 검증 실패 → `/rules/apply/` 가 400과 `suricata -T` 원문 출력을 반환.
  검증을 통과하지 못한 룰은 절대 파일에 쓰지 않는다.
- reload 실패 → 직전 룰셋으로 되돌리고 500과 사유를 반환.
- benign 케이스 0건 → 스코어에 `warnings: ["no benign cases"]`.
- 케이스가 마커를 선언했는데 Detection에 마커가 하나도 없음 →
  스코어에 경고. 조용히 전부 FN으로 처리하면 파이프라인 고장을
  탐지 실패로 오독한다.

## 8. 테스트

3층으로 나눈다.

1. **단위** — `correlate.py`, `metrics.py`. 스택 불필요.
   합성 케이스/Detection 리스트로 TP/FP/FN/TN 경계를 전부 짚는다.
   마커 대응, 시간창 대응, 중복 경보, 경계 시각.
2. **API** — Django 테스트 클라이언트. ES와 Suricata는 모킹.
   세션 → 케이스 → 수집 → 채점 왕복.
3. **통합** (`test/`) — 실제 compose 스택 대상. 완료 기준 검증.
   스택을 띄우고 `redteam/run.py` 를 돌린 뒤 스코어를 확인.

## 9. 완료 기준

1. `docker compose up -d` 로 전 서비스가 healthy.
2. `python redteam/run.py` 가 오류 없이 완주하고 세션 id를 출력.
3. `GET /api/sessions/{id}/score/` 가 TP > 0, TN > 0 인 스코어를 반환.
   (탐지되는 공격과 탐지되지 않는 정상 트래픽이 둘 다 존재)
4. 블루팀 콘솔에서 룰 하나를 추가·반영한 뒤 재실행하면 스코어가
   예측한 방향으로 움직인다.
5. `test/` 가 1~4를 자동으로 검증한다.

3번이 이 MVP의 반증 지점이다. TP > 0 이 안 나오면 경보-케이스 대응이
실패한 것이고, TN > 0 이 안 나오면 오탐 채점이 무의미한 것이다.
