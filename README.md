# fsl-project-mvp

사이버 공방 훈련 플랫폼 MVP. 레드팀이 웹 앱을 공격하고 블루팀이
Suricata·ModSecurity 로 막는 환경을 세우고, 방어 성패를 오탐·미탐으로 채점한다.

메인 프로젝트는 별도 레포. 여기는 가설 검증용이다.

검증하는 가설: **레드팀 공격에 ground truth 라벨을 붙일 수 있고, Suricata·
ModSecurity 경보를 그 라벨에 자동 대응시켜 오탐/미탐을 기계적으로 채점할 수 있다.**

설계는 [`docs/superpowers/specs/2026-09-18-fsl-mvp-design.md`](docs/superpowers/specs/2026-09-18-fsl-mvp-design.md).

## 띄우기

```bash
docker compose up -d --build
```

| 주소 | 용도 |
|------|------|
| http://localhost:8000 | 블루팀 콘솔 + `/api/` |
| http://localhost:8080 | WAF 를 통과하는 juice-shop (공격 대상) |
| http://localhost:5601 | Kibana |
| http://localhost:9200 | Elasticsearch |

ES ingest pipeline 을 한 번 등록한다.

```bash
curl -X PUT http://localhost:9200/_ingest/pipeline/fsl-geoip -H 'Content-Type: application/json' --data-binary @deploy/elastic/ingest-pipeline.json
```

레드팀 외부 도구(sqlmap) 이미지를 한 번 만든다. 일회성으로 `docker run`
되므로 `up` 에서는 뜨지 않는다.

```bash
docker compose --profile tools build
```

호스트가 arm64 (Apple Silicon) 면 Docker 도 arm64 로 돌려야 한다.
Elasticsearch 의 amd64 JVM 은 x86 에뮬레이션 아래에서 SIGSEGV 로 죽는다.

## 한 판 돌리기

```bash
python redteam/run.py
```

세션 번호가 출력된다. 콘솔(http://localhost:8000)에서 그 번호를 넣으면
TP/FP/FN/TN 과 케이스별 판정이 보인다.

## 완료 기준 검증

```bash
python -m pytest test/ -v
```

설계 문서 9장의 완료 기준을 그대로 검사한다. `TP > 0` 과 `TN > 0` 이
이 MVP 의 반증 지점이다.

단위·API 테스트는 스택 없이 돈다.

```bash
cd platform && python -m pytest tests -q
```

## 디렉터리

- `deploy` — 스택 설정 파일
- `wargame` — 방어 대상 앱, 하나당 디렉터리 하나
- `redteam` — 공격 실행, 무엇을 언제 공격했는지 ground truth 기록
- `blueteam` — 방어자 콘솔 (`platform/blueteam`)
- `platform` — 채점, 룰 검증·반영, API 제공
- `test` — 완료 기준 검증

## 구조 원칙

화면에서 되는 모든 동작은 `platform` REST API 로 먼저 존재한다. 콘솔 템플릿은
값을 하나도 서버 렌더하지 않고 브라우저에서 `/api/` 를 fetch 한다. 나중에
사람 자리에 에이전트가 들어올 때 고칠 곳이 없어야 한다.

## 주의

로컬 훈련 랩 전용이다. Elasticsearch 보안 비활성, Django `DEBUG=1`,
`ALLOWED_HOSTS=*`, platform 컨테이너에 Docker 소켓 마운트. 어느 것도
공개 네트워크에 두어서는 안 된다.
