# Vocabulary

What this console calls things, in English and Korean, and where each word came from.

Two rules produced this table, and they are the point of it:

1. **No term is here because it sounded right.** Every row was taken from a page that was
   actually fetched, and the quote justifying it is on the linked page. Terms that could not
   be sourced are listed under *No settled term*, and those keep their English.
2. **The repo's own code wins ties.** Where a template and the Python disagreed, the Python
   was right and the template was changed.

Korean lives only in `platform/console/templates/console/strings.html`.
A test keeps it out of every other template. This file is documentation and is not counted
by `bin/measure`.


## Detection and alerting

*탐지와 경보 - the blue console*

| English | 한국어 | Notes | Source |
|---|---|---|---|
| `alert` | **경보** | 또 보이는 형태: 알림 (클라우드 SIEM 문서), 알람 (SIEM이 띄우는 팝업), 알럿 (문어체에서는 안 씀). 한국 관제센터 문서는 IDS/WAF가 올리는 것을 일관되게 '경보'라고 씁니다. 구글 SecOps 한국어 문서는 'alert'를 '알림'으로 옮기지만, 관제 현업 글은 '경보'입니다. '알럿'은 1차 출처에서 한 번도 안 나왔습니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/siem%EC%9D%84-%ED%86%B5%ED%95%9C-%EA%B2%BD%EB%B3%B4-%EC%84%A4%EC%A0%95%EA%B3%BC-%EC%9D%B4%EB%B2%A4%ED%8A%B8-%EB%8C%80%EC%9D%91/) |
| `auto-refresh` | **자동 새로고침** | 또 보이는 형태: 새로 고침 (띄어쓰기), 자동 갱신. 구글 SecOps 한국어가 대시보드 갱신 간격 설정을 이 말로 씁니다. | [cloud.google.com](https://cloud.google.com/chronicle/docs/detection/view-all-rules?hl=ko) |
| `block` | **차단** | 또 보이는 형태: 차단조치. ModSecurity가 요청을 막는 동작. '탐지 모드 / 차단 모드' 쌍으로 자주 씁니다. | [aws.amazon.com](https://aws.amazon.com/ko/blogs/korea/aws-waf-operation-guide-rule-setting-and-false-positive/) |
| `correlation` | **상관분석** | 또 보이는 형태: 연관 분석 (같은 국내 SIEM 벤더가 엔진 설명에서 쓰는 말). SIEM이 여러 이벤트를 묶어 하나의 경보로 만드는 것. 이 콘솔에서 알림을 공격 케이스에 붙이는 동작도 같은 말로 부를 수 있습니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%ED%9A%A8%EA%B3%BC%EC%A0%81%EC%9D%B8-%EC%9B%B9-%ED%95%B4%ED%82%B9-%ED%83%90%EC%A7%80%EC%99%80-access-log-%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EB%B6%84%EC%84%9D-2%EB%B6%80/) |
| `coverage` | **적용 범위** | 또 보이는 형태: 커버리지 (같은 문서가 제목에서는 이쪽을 씀). MS Sentinel 한국어 문서가 MITRE coverage를 본문에서 '적용 범위', 제목에서 '커버리지'로 씁니다. 둘 다 통용되며, 짧은 콘솔 라벨에는 '커버리지'가 자연스럽습니다. | [learn.microsoft.com](https://learn.microsoft.com/ko-kr/azure/sentinel/mitre-coverage) |
| `dashboard` | **대시보드** | 국내 SIEM 제품 매뉴얼이 그대로 '대시보드'. 번역 후보 없음. | [docs.logpresso.com](https://docs.logpresso.com/ko/sonar/3.1/ui/dashboard-list) |
| `destination` | **목적지 IP** | 또 보이는 형태: 대상 IP (구글 한국어 문서), 도착지. 출발지 IP와 짝. 구글 클라우드 IDS 한국어 문서도 포트에 대해서는 '목적지'를 씁니다. | [cloud.google.com](https://cloud.google.com/intrusion-detection-system/docs/logging?hl=ko) |
| `detection` | **탐지** | 또 보이는 형태: 감지 (구글 한국어 문서), 검출. 보안 장비가 잡아내는 행위는 일관되게 '탐지'입니다. 구글 클라우드 한국어 문서만 'detection'을 '감지'로 옮기는데, 한국 보안 문서 관행은 '탐지'입니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%ED%9A%A8%EA%B3%BC%EC%A0%81%EC%9D%B8-%EC%9B%B9-%ED%95%B4%ED%82%B9-%ED%83%90%EC%A7%80%EC%99%80-access-log-%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EB%B6%84%EC%84%9D-2%EB%B6%80/) |
| `detection policy / rule set` | **탐지정책** | 또 보이는 형태: 탐지 패턴, 룰셋. 개별 룰이 아니라 운용 중인 룰 묶음 전체를 가리킬 때 쓰는 말. 아래 tuning 항목과 같은 문장에서 나옵니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C%EB%B0%A9%EB%B2%95%EB%A1%A0-%EA%B8%B0%EB%B0%98-%EC%9D%B8%EA%B3%B5%EC%A7%80%EB%8A%A5-%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C-%ED%94%84%EB%A1%9C%EC%84%B8%EC%8A%A4/) |
| `disable a rule` | **룰 사용 중지** | 또 보이는 형태: 비활성화, 룰 해제. 구글 SecOps 한국어가 enable/disable을 '사용 설정/사용 중지'로 통일합니다. '비활성화'도 널리 쓰이고 더 짧습니다. | [cloud.google.com](https://cloud.google.com/chronicle/docs/detection/view-all-rules?hl=ko) |
| `enable a rule` | **룰 사용 설정** | 또 보이는 형태: 활성화. 위와 같은 문장이 근거. 콘솔 토글 라벨이면 '활성화/비활성화' 쌍이 더 짧고 자연스럽습니다. | [cloud.google.com](https://cloud.google.com/chronicle/docs/detection/view-all-rules?hl=ko) |
| `engine` | **엔진 (탐지 엔진)** | 또 보이는 형태: 탐지 엔진. Suricata/ModSecurity 각각을 가리킬 때 '탐지 엔진'이 그대로 통합니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%ED%9A%A8%EA%B3%BC%EC%A0%81%EC%9D%B8-%EC%9B%B9-%ED%95%B4%ED%82%B9-%ED%83%90%EC%A7%80%EC%99%80-access-log-%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EB%B6%84%EC%84%9D-2%EB%B6%80/) |
| `event` | **이벤트** | 또 보이는 형태: 보안이벤트. 장비가 뱉는 원자료는 '이벤트', 그것을 규칙으로 묶어 관제사에게 올린 것이 '경보'. 이 구분은 한국 관제 문서에서 일관됩니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C%EB%B0%A9%EB%B2%95%EB%A1%A0-%EA%B8%B0%EB%B0%98-%EC%9D%B8%EA%B3%B5%EC%A7%80%EB%8A%A5-%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C-%ED%94%84%EB%A1%9C%EC%84%B8%EC%8A%A4/) |
| `false negative (FN)` | **미탐** | 또 보이는 형태: 위음성 / 가음성 / 오음성 (MS 기계번역, 한 페이지에서 세 가지가 섞여 나옴). 매핑 확정: 미탐 = 공격인데 못 잡음. 인용문은 로그소스 설정이 빠져서 '탐지 자체가 안 되는' 상황을 미탐이라 부르는 실제 용례입니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%ED%9A%A8%EA%B3%BC%EC%A0%81%EC%9D%B8-%EC%9B%B9-%ED%95%B4%ED%82%B9-%ED%83%90%EC%A7%80%EC%99%80-access-log-%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EB%B6%84%EC%84%9D-2%EB%B6%80/) |
| `false positive (FP)` | **오탐** | 또 보이는 형태: 가양성 / 거짓 양성 / 오탐지 (MS·Google 한국어 기계번역). 매핑 확정: 오탐 = 정상인데 탐지. AWS 한국 공식 블로그 제목도 '오탐(False Positive)'으로 못박습니다. MS 한국어 문서는 같은 페이지 안에서 가양성/오탐/거짓 양성을 섞어 쓰므로 근거로 삼지 마세요. | [aws.amazon.com](https://aws.amazon.com/ko/blogs/korea/aws-waf-operation-guide-rule-setting-and-false-positive/) |
| `HTTP method` | **HTTP 요청 메서드** | 또 보이는 형태: 메서드, HTTP 동사. '메소드'가 아니라 '메서드'가 표준 표기입니다. | [developer.mozilla.org](https://developer.mozilla.org/ko/docs/Web/HTTP/Reference/Methods) |
| `IDS` | **IDS *(영문 유지)*** | 또 보이는 형태: 침입탐지시스템. 한국 관제 문서는 본문에서 약어 IDS를 그대로 씁니다. 풀어 쓸 자리에서만 '침입탐지시스템'. 콘솔 라벨은 IDS로 두는 게 맞습니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/siem%EC%9D%84-%ED%86%B5%ED%95%9C-%EA%B2%BD%EB%B3%B4-%EC%84%A4%EC%A0%95%EA%B3%BC-%EC%9D%B4%EB%B2%A4%ED%8A%B8-%EB%8C%80%EC%9D%91/) |
| `live` | **실시간** | '라이브'는 보안 문서에서 안 씁니다. 실시간 규칙/실시간 모니터링이 표준. | [cloud.google.com](https://cloud.google.com/chronicle/docs/detection/view-all-rules?hl=ko) |
| `overview` | **개요** | 또 보이는 형태: 현황 (숫자 요약 화면이라면 이쪽). 설명 문서 첫 장은 '개요'. 다만 경보 건수·TP/FP 합계를 보여주는 화면이라면 '탐지 현황'이 한국 관제 화면 표기에 더 가깝습니다. | [cloud.google.com](https://cloud.google.com/intrusion-detection-system/docs/overview?hl=ko) |
| `paused` | **일시중지됨** | 또 보이는 형태: 일시 정지. 규칙 실행이 멈춘 상태 표시에 쓰이는 말. | [cloud.google.com](https://cloud.google.com/chronicle/docs/detection/view-all-rules?hl=ko) |
| `port` | **포트** | 번역 후보 없음. 출발지 포트 / 목적지 포트로 씁니다. | [cloud.google.com](https://cloud.google.com/intrusion-detection-system/docs/logging?hl=ko) |
| `precision` | **정밀도** | 또 보이는 형태: 정확도는 accuracy이므로 혼동 금지. 관제 현업 글에서는 '정탐률'이라는 말도 쓰지만 정의가 느슨합니다. 계산식이 있는 수치라면 '정밀도'가 정확합니다. | [developers.google.com](https://developers.google.com/machine-learning/crash-course/classification/precision-and-recall?hl=ko) |
| `raw log record` | **원본 로그** | 또 보이는 형태: 원시 로그 (구글 한국어 문서), 근거 로그 (왜 탐지됐는지 보여주는 로그를 가리킬 때). 국내 SIEM 매뉴얼은 '원본 로그'. 경보를 클릭해서 펼치는 로그라면 이글루 문서의 '근거 로그'가 의미상 더 정확합니다. | [docs.logpresso.com](https://docs.logpresso.com/ko/sonar/3.1/ui/section-log-parser) |
| `recall` | **재현율** | 또 보이는 형태: 참양성률(TPR), 검출률. 같은 페이지가 재현율의 다른 이름이 TPR임을 밝힙니다. | [developers.google.com](https://developers.google.com/machine-learning/crash-course/classification/precision-and-recall?hl=ko) |
| `request path` | **URI 경로** | 또 보이는 형태: 요청 경로, URL 패턴. WAF 오탐 문맥에서 실제로 쓰인 표기. HTTP 요청의 경로 부분을 가리킬 때 '요청 경로'도 무방합니다. | [aws.amazon.com](https://aws.amazon.com/ko/blogs/korea/aws-waf-operation-guide-rule-setting-and-false-positive/) |
| `rule` | **룰** | 또 보이는 형태: 탐지 룰, 탐지 규칙, 탐지정책, 규칙 (클라우드 문서). Snort/Suricata 류의 시그니처 규칙은 한국 현업에서 그냥 '룰'입니다 — 인용문이 바로 SNORT/YARA 룰을 '룰'이라 부르는 국내 제품 설명입니다. 글에서는 '탐지 룰', 클라우드 SIEM 문서에서는 '규칙'. 이 콘솔은 Suricata를 쓰므로 '탐지 룰'을 권합니다. | [docs.nhncloud.com](https://docs.nhncloud.com/ko/Security/Web%20Firewall/ko/console-guide/) |
| `severity` | **심각도** | 또 보이는 형태: 위험도 (국내 SIEM 화면 표기), 신뢰도 (룰에 매기는 1~10 점수는 따로 이렇게 부름). 등급 표기는 높음/중간/낮음, 그 아래 정보성은 '정보'. 국내 SIEM 화면은 '위험도'를 쓰는 경우도 많습니다. | [cloud.google.com](https://cloud.google.com/chronicle/docs/detection/view-all-rules?hl=ko) |
| `severity: high / medium / low` | **높음 / 중간 / 낮음** | 또 보이는 형태: 상/중/하, 위험/경고/주의. 구글 클라우드 IDS 한국어 문서가 위협 심각도 등급을 이 세 단어로 씁니다. | [cloud.google.com](https://cloud.google.com/intrusion-detection-system/docs/overview?hl=ko) |
| `signature` | **시그니처** | 또 보이는 형태: 시그니쳐 (옛 표기), 탐지패턴, 서명 (구글 기계번역, 쓰지 말 것). 구글 클라우드 IDS 한국어 문서는 signature를 '서명'으로 옮기는데 이건 오역 수준이라 현업에서 안 통합니다. '시그니처'가 표준. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%ED%9A%A8%EA%B3%BC%EC%A0%81%EC%9D%B8-%EC%9B%B9-%ED%95%B4%ED%82%B9-%ED%83%90%EC%A7%80%EC%99%80-access-log-%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EB%B6%84%EC%84%9D-2%EB%B6%80/) |
| `SOC / security monitoring` | **보안관제** | 또 보이는 형태: 관제, 관제요원 (분석가). 이 제품이 훈련시키는 대상 업무 자체의 이름. 블루팀 화면 제목에 쓸 만합니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C%EB%B0%A9%EB%B2%95%EB%A1%A0-%EA%B8%B0%EB%B0%98-%EC%9D%B8%EA%B3%B5%EC%A7%80%EB%8A%A5-%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C-%ED%94%84%EB%A1%9C%EC%84%B8%EC%8A%A4/) |
| `source IP` | **출발지 IP** | 또 보이는 형태: 소스 IP (구글 한국어 문서), 공격 IP. 국내 SIEM 화면 필드명이 '출발지 IP'입니다. 구글 클라우드 번역의 '소스 IP'는 현업 표기가 아닙니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%ED%9A%A8%EA%B3%BC%EC%A0%81%EC%9D%B8-%EC%9B%B9-%ED%95%B4%ED%82%B9-%ED%83%90%EC%A7%80%EC%99%80-access-log-%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EB%B6%84%EC%84%9D-2%EB%B6%80/) |
| `suppression` | **억제** | 또 보이는 형태: 예외처리 (국내 관제에서 오탐 룰을 죽일 때 쓰는 말). '억제'는 탐지가 난 뒤 경보만 안 올리는 후처리, '예외처리'는 애초에 안 잡도록 룰에 예외를 넣는 것. 이 콘솔에서 룰을 주석 처리해 끄는 동작은 '예외처리'보다 '억제'에 가깝습니다. | [cloud.google.com](https://cloud.google.com/chronicle/docs/detection/manage-all-rules?hl=ko) |
| `threshold` | **임계치** | 또 보이는 형태: 임계값. 목록에는 없었지만 Suricata 룰 튜닝 화면에 반드시 나오는 말이라 같이 넣습니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%ED%9A%A8%EA%B3%BC%EC%A0%81%EC%9D%B8-%EC%9B%B9-%ED%95%B4%ED%82%B9-%ED%83%90%EC%A7%80%EC%99%80-access-log-%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EB%B6%84%EC%84%9D-2%EB%B6%80/) |
| `triage` | **경보 분류** | 또 보이는 형태: 정·오탐 판단 (국내 관제의 실제 작업 이름), 선별. 영어 triage에 딱 맞는 한 단어는 없습니다. 클라우드 문서는 '알림 분류', 국내 관제 문서는 그 작업을 '정·오탐 판단'이라고 부릅니다. 이 콘솔은 정탐/오탐을 고르는 화면이므로 '정·오탐 판단'이 가장 정확합니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C%EB%B0%A9%EB%B2%95%EB%A1%A0-%EA%B8%B0%EB%B0%98-%EC%9D%B8%EA%B3%B5%EC%A7%80%EB%8A%A5-%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C-%ED%94%84%EB%A1%9C%EC%84%B8%EC%8A%A4/) |
| `true negative (TN)` | **참음성** | 또 보이는 형태: 정상 판정 / 미탐지(정상). 주의: 한국 관제 현업에는 TN에 해당하는 굳어진 단어가 없습니다. 정탐/오탐/미탐 세 개만 씁니다. 통계·ML 쪽 용어인 '참음성'이 유일하게 출처가 있는 말이므로, 콘솔에서는 '참음성(TN)'처럼 약어를 함께 적거나 '정상 트래픽을 정상으로 판정'처럼 풀어 쓰는 편이 읽힙니다. | [developers.google.com](https://developers.google.com/machine-learning/crash-course/classification/precision-and-recall?hl=ko) |
| `true positive (TP)` | **정탐** | 또 보이는 형태: 진양성 / 진정한 긍정 (MS 기계번역, 쓰지 말 것). 매핑 확정: 정탐 = 실제 공격을 맞게 탐지. 같은 문장 안에서 정탐↔차단조치, 오탐↔예외처리로 짝지어져 있어 뒤집힐 여지가 없습니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/siem%EC%9D%84-%ED%86%B5%ED%95%9C-%EA%B2%BD%EB%B3%B4-%EC%84%A4%EC%A0%95%EA%B3%BC-%EC%9D%B4%EB%B2%A4%ED%8A%B8-%EB%8C%80%EC%9D%91/) |
| `tuning` | **정책 최적화** | 또 보이는 형태: 튜닝 (구어에서 자주), 룰 튜닝. 관제 방법론 문서는 오탐이 나면 하는 작업을 '탐지정책 검증/변경/최적화'로 정의합니다. 콘솔 라벨로는 '룰 튜닝'이 짧고 현업에서 바로 읽힙니다. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C%EB%B0%A9%EB%B2%95%EB%A1%A0-%EA%B8%B0%EB%B0%98-%EC%9D%B8%EA%B3%B5%EC%A7%80%EB%8A%A5-%EB%B3%B4%EC%95%88%EA%B4%80%EC%A0%9C-%ED%94%84%EB%A1%9C%EC%84%B8%EC%8A%A4/) |
| `WAF` | **웹방화벽** | 또 보이는 형태: 웹 방화벽 (띄어쓰기), WAF. 국내 문서는 '웹방화벽'이 압도적이고 약어 WAF도 병기합니다. '웹 애플리케이션 방화벽'은 해외 벤더 번역투. | [aws.amazon.com](https://aws.amazon.com/ko/blogs/korea/aws-waf-operation-guide-rule-setting-and-false-positive/) |
| `zone` | **영역 / Zone *(영문 유지)*** | 또 보이는 형태: 보호 대상(Zone), 구역. 근거 강도 낮음 — 이 인용은 페이지 요약을 통해 얻은 것이라 원문 대조를 못 했습니다. 국내 클라우드 보안 제품은 Zone을 영문 그대로 두는 편이니 콘솔에서도 영문 유지를 권합니다. | [guide.ncloud-docs.com](https://guide.ncloud-docs.com/docs/securitymonitoring-info) |

## Attack and exercise

*공격과 훈련 - the red console*

| English | 한국어 | Notes | Source |
|---|---|---|---|
| `attack case` | **공격 시나리오** | 또 보이는 형태: 공격 유형, 점검 항목. '공격 케이스'라는 표현은 어느 1차 출처에서도 찾지 못함. 한 건의 공격 실행 단위를 가리킬 때 현업은 '공격 시나리오' 또는 통계 문맥에서 '공격 유형'을 씀. | [boannews.com](http://www.boannews.com/news/articleView.html?idxno=144994) |
| `attacker` | **공격자** | 또 보이는 형태: 위협 행위자 (threat actor). 안랩 사이버보안 101. 예외 없이 '공격자'. Microsoft Learn 한국어 Defender 문서도 전부 '공격자'. | [ahnlab.com](https://www.ahnlab.com/ko/contents/cybersecurity-101/what-is-c2) |
| `benign traffic` | **정상 트래픽** | 또 보이는 형태: 악성 트래픽 / 공격 트래픽 (반대말). 같은 논문에 '정탐 100%, 오탐 0%, 미탐 0%'가 있어 TP/FP/FN 라벨까지 같이 가져다 쓸 수 있음. | [scienceon.kisti.re.kr](https://scienceon.kisti.re.kr/srch/selectPORSrchArticle.do?cn=JAKO201915061088999) |
| `blue team` | **블루팀** | 또 보이는 형태: 블루 팀, 방어팀. 금융보안원 보도자료(위 red team 항목)에서도 '블루팀(방어자)'로 동일하게 쓰임. | [checkpoint.com](https://www.checkpoint.com/kr/cyber-hub/cyber-security/what-is-a-red-team/) |
| `challenge (a CTF-style objective the red team must capture)` | **문제** | 또 보이는 형태: 챌린지. 티오리(국내 공격보안 기업) 기술 블로그. KISA 해킹방어대회도 '문제가 출제된다'로 씀. Juice Shop의 challenge는 '문제'가 맞고 '챌린지'는 영어 UI를 그대로 읽은 것. | [theori.io](https://theori.io/ko/blog/ctf-hacking-competition-schedule) |
| `cyber range` | **사이버 레인지** | 또 보이는 형태: 사이버 훈련장, (라틴 표기) Cyber Range. KCI 논문 제목. 주목할 점: 같은 논문 본문은 '각군의 특성이 반영된 Cyber Range를 서로 엮어서'처럼 한국어 문장 안에 라틴 표기를 그대로 섞어 씀. ETRI 전자통신동향분석은 'Intelligent Cyber Range'를 '지능형 사이버 훈련장'으로 옮김 — KISA·군 문맥에서는 '사이버 훈련장'이 더 흔함. | [kci.go.kr](https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002865075) |
| `difficulty` | **난이도** | 또 보이는 형태: 초급/중급/고급 (레벨 구분). KISA 아카데미 실전형 사이버훈련장도 과정을 '초급과정/중급과정'으로 나눔. | [theori.io](https://theori.io/ko/blog/ctf-hacking-competition-schedule) |
| `exercise (a training run)` | **훈련** | 또 보이는 형태: 모의훈련, 연습. KISA 보호나라. 국내 표준은 '훈련/모의훈련'이며 '연습'은 Check Point 한국어 같은 번역서에서만 보임 — 쓰지 말 것. 실제로 공격을 쏘는 훈련은 '실전형 모의훈련'. | [boho.or.kr](https://www.boho.or.kr/kr/subPage.do?menuNo=205014) |
| `exploit` | **익스플로잇** | 또 보이는 형태: 취약점 악용, 익스플로잇 키트. 명사는 '익스플로잇', 동사적으로 쓸 때는 '취약점을 악용한다'. Microsoft 한국어 문서가 두 형태를 섞어 쓰는 점은 주의. | [learn.microsoft.com](https://learn.microsoft.com/ko-kr/defender-endpoint/malware/exploits-malware) |
| `initial access` | **초기 액세스** | 또 보이는 형태: 초기 침투, 초기 진입. ATT&CK 전술명으로 쓸 때는 '초기 액세스'가 사실상 표준(Microsoft 한국어 전면 채택). 침투테스트 서술문에서는 금융보안원 가이드라인 기사처럼 '초기 침투'가 자연스러움 — 문맥에 따라 골라 쓸 것. | [learn.microsoft.com](https://learn.microsoft.com/ko-kr/azure/defender-for-cloud/alerts-windows-machines) |
| `objective` | **목표** | 또 보이는 형태: 목표지향적 (objective-driven). 금융보안원 '금융분야 침투테스트(모의해킹) 수행 가이드라인' 발간 기사. 같은 기사에 '목표지향적 모의 침투 시나리오 정립'. Check Point 한국어도 '연습의 참여 규칙과 목표를 정의'. | [boannews.com](http://www.boannews.com/news/articleView.html?idxno=144994) |
| `operator (the human running the attack side)` | **화이트해커** | 또 보이는 형태: 모의해킹 수행자, 관제요원(방어 측). 금융보안원 보도자료 제목. 공격을 수행하는 사람은 '화이트해커'. 콘솔의 역할 라벨로서의 'operator'(=오퍼레이터/운영자)는 1차 출처를 찾지 못함 — could_not_source 참고. 방어 측 사람은 '관제요원'. | [fsec.or.kr](https://www.fsec.or.kr/bbs/detail?menuNo=69&bbsNo=11566) |
| `origin network / source address` | **출발지** | 또 보이는 형태: 출발지 IP, 출발지 주소 (반대말 목적지 IP). KISA 보호나라 보안공지. 국내 관제 화면은 예외 없이 '출발지/목적지'이고 '소스/대상'은 클라우드 벤더 번역투. 다만 1차 출처에서 확인한 형태는 '출발지 IP'이며 '출발지 네트워크'는 그 확장형. | [boho.or.kr](https://www.boho.or.kr/kr/bbs/view.do?searchCnd=&bbsId=B0000133&searchWrd=&menuNo=205020&pageIndex=1&categoryCode=&nttId=35573) |
| `payload` | **페이로드** | 또 보이는 형태: 셸코드 (shellcode). 관제 문맥에서는 탐지 로그의 패킷 본문도 '페이로드'라고 부름. | [learn.microsoft.com](https://learn.microsoft.com/ko-kr/defender-endpoint/malware/exploits-malware) |
| `penetration test` | **침투테스트** | 또 보이는 형태: 모의해킹, 모의침투, 침투 시험(TTA 용어사전). 금융보안원이 2026년 가이드라인 제목에서 '침투테스트(모의해킹)'로 병기 — 현재 국내 공식 용어는 '침투테스트'이고 '모의해킹'이 현장 구어. KISA 모의훈련 항목명은 '모의침투'. | [boannews.com](http://www.boannews.com/news/articleView.html?idxno=144994) |
| `proxy` | **프록시** | 또 보이는 형태: 프록시 서버. Microsoft Learn 한국어. 단독 명사는 '프록시', 장비를 가리키면 '프록시 서버'. | [learn.microsoft.com](https://learn.microsoft.com/ko-kr/defender-endpoint/configure-proxy-internet) |
| `reconnaissance` | **정찰** | 또 보이는 형태: 정보 수집 (침투테스트 절차 명칭). MITRE ATT&CK Reconnaissance의 한국어 전술명이 '정찰'로 고정되어 있음(Microsoft Defender for Identity 경고 범주도 '정찰 및 검색 경고'). 모의해킹 절차 문서에서는 같은 단계를 '정보 수집'이라 부름. | [learn.microsoft.com](https://learn.microsoft.com/ko-kr/azure/defender-for-cloud/alerts-windows-machines) |
| `red team` | **레드팀** | 또 보이는 형태: 레드 팀 (띄어쓰기), 공격팀. 금융보안원(FSI) 보도자료. 한글 음차로 정착. 이 한 문장이 레드팀=공격자, 블루팀=방어자 대응까지 못박아 줌. Check Point 한국어 페이지는 '레드 팀'으로 띄어 씀. | [fsec.or.kr](https://www.fsec.or.kr/bbs/detail?menuNo=69&bbsNo=11535) |
| `scenario` | **시나리오** | 또 보이는 형태: 훈련 시나리오. 사이버 훈련 문맥에서는 '훈련 시나리오'가 굳어진 복합어. | [kci.go.kr](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002615762) |
| `shell` | **셸** | 또 보이는 형태: 쉘 (웹쉘, 리버스쉘 표기가 현업에 흔함). 표준 표기는 '셸'(Microsoft, Check Point 한국어 모두). 실제 현업 문서·게시글에는 '쉘/웹쉘/리버스쉘'이 더 많이 보이므로 한 쪽으로 통일할 것. reverse shell = 리버스 셸. | [checkpoint.com](https://www.checkpoint.com/kr/cyber-hub/cyber-security/what-is-a-reverse-shell-attack/) |
| `solved` | **풀이 / 푼 문제** | 또 보이는 형태: 해결. 동사형 '(문제를) 풀다'가 실제 쓰이는 형태. UI 상태 라벨은 '풀림/푼 문제'가 자연스럽고, '해결됨'은 티켓 시스템 냄새가 남. 라벨 자체를 1차 출처로 확인하지는 못함. | [theori.io](https://theori.io/ko/blog/ctf-hacking-competition-schedule) |
| `target (the system being attacked)` | **대상 시스템** | 또 보이는 형태: 공격 대상, 표적, 목표 시스템. KCI 등재 논문. UI 라벨로는 '대상 시스템'이 가장 중립적. '표적'은 군·위협인텔 문맥, '공격 대상'은 서술문에서 자연스러움. | [kci.go.kr](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001708345) |
| `terminal` | **터미널** | 또 보이는 형태: 콘솔, 명령줄. Microsoft Learn 한국어. | [learn.microsoft.com](https://learn.microsoft.com/ko-kr/windows/terminal/) |

## Network and assets

*네트워크와 자산*

| English | 한국어 | Notes | Source |
|---|---|---|---|
| `asset` | **자산** | 또 보이는 형태: 정보자산; 자산관리 (asset management screen). 자산 is the SOC word and it ships as a menu label: Igloo's SIEM has 설정관리 > 자산관리, and the product line includes 자산위협관리 solutions. TTA defines 정보 자산 formally, but in a console 자산 alone i | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EA%B4%80%EC%A0%9C%EB%A5%BC-%EC%9C%84%ED%95%9C-siem-%EA%B5%AC%EC%B6%95-%EA%B0%80%EC%9D%B4%EB%93%9C/) |
| `container` | **컨테이너** | TTA standard term, and Igloo's CNAPP article uses it as a bare noun throughout alongside 쿠버네티스 and 워크로드. No Korean practitioner writes anything else. | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EC%BB%A8%ED%85%8C%EC%9D%B4%EB%84%88) |
| `DMZ` | **DMZ *(영문 유지)*** | 또 보이는 형태: 비무장 지대; DMZ망; DMZ영역. TTA registers 비무장 지대 as the Korean headword, but Korean practitioners write DMZ in running text and in product screens (Igloo: DMZ 망, DMZ영역). Keep DMZ; do not translate to 비무장 지대 in a console. | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EB%B9%84%EB%AC%B4%EC%9E%A5%EC%A7%80%EB%8C%80) |
| `externally exposed / public-facing (of the target web app)` | **외부 공개** | 또 보이는 형태: 외부공개 웹 사이트. Igloo's dashboard case study splits monitoring into 네트워크 보안장비 모니터링 and 외부공개 웹 사이트 모니터링. For Juice Shop as 'the app exposed to the internet', 외부 공개 웹 서버 is the natural Korean, and it is the closest sourced thi | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%82%98-%ED%99%80%EB%A1%9C-%EB%B3%B4%EC%95%88%EB%8B%B4%EB%8B%B9%EC%9E%90%EB%A5%BC-%EC%9C%84%ED%95%9C-%EC%9D%B4%EC%83%81%ED%96%89%EC%9C%84-%ED%83%90%EC%A7%80-%EB%AA%A8%EB%8B%88%ED%84%B0%EB%A7%81/) |
| `firewall` | **방화벽** | Universal. Igloo's SIEM guide uses it as a device-type label throughout (방화벽 로그, 방화벽 정책). | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EA%B4%80%EC%A0%9C%EB%A5%BC-%EC%9C%84%ED%95%9C-siem-%EA%B5%AC%EC%B6%95-%EA%B0%80%EC%9D%B4%EB%93%9C/) |
| `gateway` | **게이트웨이** | TTA standard term. AhnLab's own CLI manual uses it as a plain UI field beside IP 주소 and DNS 서버, which is exactly this console's usage. | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EA%B2%8C%EC%9D%B4%ED%8A%B8%EC%9B%A8%EC%9D%B4) |
| `geolocation` | **지오로케이션** | 또 보이는 형태: 지리적 위치 추정; (in SOC practice just 국가). TTA registers 지오로케이션 with 지리적 위치 추정 as a synonym, and explicitly covers the IP-address case (인터넷 지오로케이션). But in an actual SOC screen nobody writes 지오로케이션 - the column is simply 국가 o | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EC%A7%80%EC%98%A4%EB%A1%9C%EC%BC%80%EC%9D%B4%EC%85%98) |
| `host` | **호스트** | 또 보이는 형태: 호스트 이름 (hostname). Standard as a loanword in both vendor prose and TTA. AhnLab writes 호스트 이름 for hostname; TTA's IDS entry writes 호스트 기반 IDS(HIDS) and 호스트 PC. For 'the host that owns this address', 호스트 is right; 단말 means | [ahnlab.com](https://www.ahnlab.com/ko/contents/cybersecurity-101/what-is-c2) |
| `information asset (formal)` | **정보 자산** | 또 보이는 형태: 자산. TTA standard definition (TTAK.KO-12.0093). Use only where the console needs the formal register; 자산 elsewhere. | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EC%A0%95%EB%B3%B4%20%EC%9E%90%EC%82%B0) |
| `inside / outside (direction of an attack)` | **내부 / 외부** | 또 보이는 형태: 외부 -> 내부 (as a direction label). For traffic direction and threat classification, Korean SOC text drops the -망 and writes plain 내부/외부. Igloo's detection-policy table uses 외부 / 내부 위협 as the top-level split and 외부 -> 내부 as | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EA%B4%80%EC%A0%9C%EB%A5%BC-%EC%9C%84%ED%95%9C-siem-%EA%B5%AC%EC%B6%95-%EA%B0%80%EC%9D%B4%EB%93%9C/) |
| `internal business network` | **내부업무망** | 또 보이는 형태: 업무망. Regulatory register, from 금융보안원's own notice text. Useful if this console's internal segment should read as a corporate work network rather than a generic 내부망. | [fsec.or.kr](https://www.fsec.or.kr/bbs/detail?menuNo=222&bbsNo=11686) |
| `internal network / external network` | **내부망 / 외부망** | 또 보이는 형태: 내부 네트워크 / 외부 네트워크; 내부업무망. 내부망/외부망 is standard and appears in a shipping Korean firewall manual describing a router between the two. 금융보안원 uses the same pair in regulation text (내부업무망ㆍ전산실, 외부망으로부터 독립된 인프라). The -망 suffix, | [help.ahnlab.com](https://help.ahnlab.com/TrusGuard/AhnLab_TrusGuard_DPX/ko_KR/outofpath.htm) |
| `internet segment (the outside of the range)` | **인터넷망** | 또 보이는 형태: 인터넷 영역. Igloo's SIEM guide lists 인터넷망 beside DMZ망 and 내부망 as the standard '영역 별' split, and elsewhere writes 외부(인터넷영역). This is the term for the console's outermost segment - better than 외부망, which in Korean regulation o | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EA%B4%80%EC%A0%9C%EB%A5%BC-%EC%9C%84%ED%95%9C-siem-%EA%B5%AC%EC%B6%95-%EA%B0%80%EC%9D%B4%EB%93%9C/) |
| `intrusion detection system (IDS, i.e. Suricata)` | **침입 탐지 시스템** | 또 보이는 형태: IDS; 네트워크 기반 IDS(NIDS). TTA standard term. The entry also confirms 탐지/경고 as the verbs, and 시그니처 기반 - useful for this console's alert wording. | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EC%B9%A8%EC%9E%85%20%ED%83%90%EC%A7%80%20%EC%8B%9C%EC%8A%A4%ED%85%9C) |
| `IP range (of a segment)` | **IP 대역** | 또 보이는 형태: 영역 별 IP 대역. Sourced from the same Igloo detection-policy table that fixes 영역. This is the word for the CIDR a segment owns; 대역폭 is bandwidth and is a different word - do not confuse them. | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EA%B4%80%EC%A0%9C%EB%A5%BC-%EC%9C%84%ED%95%9C-siem-%EA%B5%AC%EC%B6%95-%EA%B0%80%EC%9D%B4%EB%93%9C/) |
| `management network` | **관리망** | AhnLab lists 관리망 as a segment peer of 사용자 영역, 서버 영역 and 중요 정보 시스템 - exactly the topology role this console has. Sourced cleanly; use it. | [ahnlab.com](https://www.ahnlab.com/ko/contents/cybersecurity-101/what-is-c2) |
| `network segment` | **네트워크 구간** | 또 보이는 형태: 네트워크 영역 / 영역. AhnLab's own Korean product manual writes 네트워크 구간 for a stretch of network where equipment is placed. 영역 is the other native word (see 'zone'). Do not calque 세그먼트: TTA's 세그먼트 entry is memory/DB segmentation | [help.ahnlab.com](https://help.ahnlab.com/TrusGuard/AhnLab_TrusGuard_DPX/ko_KR/outofpath.htm) |
| `network separation / segmentation (as a practice)` | **망 분리** | 또 보이는 형태: 네트워크 분리. TTA standard term (TTAK.KO-11.0276) with 네트워크 분리 given as an explicit synonym, and the entry itself models the 인터넷망 vs 업무망 split. This is the verb-noun for what this console's topology depicts. | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EB%A7%9D%20%EB%B6%84%EB%A6%AC) |
| `reverse proxy` | **리버스 프록시 서버** | 또 보이는 형태: 리버스 프록시. Igloo transliterates rather than translating, and pairs it with 백엔드 서버 and 포워드 프록시. I could NOT source 역방향 프록시 from any Korean first-party security document - see could_not_source. | [igloo.co.kr](https://www.igloo.co.kr/security-information/web-cache-deception-%EA%B3%B5%EA%B2%A9-%EA%B8%B0%EB%B2%95/) |
| `source country` | **출발지 국가** | 또 보이는 형태: 공격 국가 (in dashboard widget titles). This is a literal SIEM field name in a shipping Korean product: Igloo normalizes it as 출발지 국가(s_country) beside 목적지 국가(d_country). Pair with 출발지 IP / 목적지 IP, which the same passage fix | [igloo.co.kr](https://www.igloo.co.kr/security-information/%EB%B9%85%EB%8D%B0%EC%9D%B4%ED%84%B0-%EA%B4%80%EC%A0%9C%EB%A5%BC-%EC%9C%84%ED%95%9C-siem-%EA%B5%AC%EC%B6%95-%EA%B0%80%EC%9D%B4%EB%93%9C/) |
| `source IP / destination IP` | **출발지 IP / 목적지 IP** | 또 보이는 형태: 출발지IP / 목적지IP (no space, as the field label). Not 소스 IP and not 발신지. Both Igloo and AhnLab's firewall manual use 출발지/목적지; AhnLab's policy screen reads '출발지 IP 주소, 목적지 IP 주소, 서비스가 일치하는 통신을 허용합니다.' | [help.ahnlab.com](https://help.ahnlab.com/TrusGuard/TrusGuard2.0/ko_KR/firewall_firewall_fw_policy_add_v6.htm) |
| `subnet` | **서브넷** | TTA standard term (TTAS.KO-04.0043). Note its own definition calls a subnet '하나의 세그먼트' - that is the only networking use of 세그먼트 I could source, and it is inside the subnet entry, not a headword of its own. | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EC%84%9C%EB%B8%8C%EB%84%B7) |
| `web application firewall (WAF, i.e. ModSecurity)` | **웹 방화벽** | 또 보이는 형태: WAF. TTA headword, and Igloo uses 웹 방화벽 as a live console label beside SSLVPN. This is the word for the ModSecurity side of this range - not 애플리케이션 방화벽. | [terms.tta.or.kr](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EC%9B%B9%20%EB%B0%A9%ED%99%94%EB%B2%BD) |
| `zone` | **영역** | 또 보이는 형태: 망 (as in 내부망 / 인터넷망 / DMZ망). AhnLab uses 영역 for a policy-bearing network zone (사용자 영역, 서버 영역). Igloo's SIEM guide classifies detection policy by '영역 별': DMZ망, 내부망, 인터넷망. I could not source 존 from any first-party Korean d | [ahnlab.com](https://www.ahnlab.com/ko/contents/cybersecurity-101/what-is-c2) |

## General product UI

*화면 공통*

| English | 한국어 | Notes | Source |
|---|---|---|---|
| `apply` | **적용** | 필터·설정 확정 버튼. '반영'·'적용하기' 아님. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `cancel` | **취소** | 확인 버튼은 "확인" (vs/base/browser/ui/dialog/dialog/ok). 취소와 짝. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `clear / reset` | **지우기 / 초기화** | 또 보이는 형태: 모두 지우기. 입력·목록 내용을 비우면 '지우기', 기본값으로 되돌리면 '초기화'. 필터 리셋은 '초기화'. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `close` | **닫기** | '종료'는 프로세스를 끝낼 때만. 패널/다이얼로그는 전부 '닫기'. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `closed` | **종결** | 또 보이는 형태: 닫힘 / 종료. 인시던트·케이스가 끝난 상태는 '종결'. UI 일반(이슈 상태)에서는 '닫힘'도 쓰임 — VS Code baseIssueReporterService/closed = "닫힘". 세션에는 '종료'가 자연스러움. | [docs.aws.amazon.com](https://docs.aws.amazon.com/ko_kr/security-ir/latest/userguide/dashboard.html) |
| `count` | **건수** | 또 보이는 형태: 개수 / …개 항목 / …건. 보안 이벤트·알림처럼 '건'으로 세는 것은 '건수'. 일반 항목은 '개수' 또는 '{0}개 항목' (VS Code scmHistoryViewPane/items = "{0}개 항목"). | [docs.aws.amazon.com](https://docs.aws.amazon.com/ko_kr/security-ir/latest/userguide/dashboard.html) |
| `error` | **오류** | '에러' 아님. 심각도 라벨로도 '오류'. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `failed` | **실패** | 또 보이는 형태: 실패했습니다 (문장). 상태 칩은 '실패', 문장은 '…에 실패했습니다'. 조사는 '을/를'이 아니라 '에'. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `filter` | **필터** | 또 보이는 형태: 필터링 (동사형) / 초기화 (필터 해제). 명사 라벨은 '필터', 동작 설명은 '필터링'. 필터 해제 버튼은 '초기화' (agentSessionsFilter/agentSessions.filter.reset), 입력 비우기는 '지우기'. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `language` | **표시 언어** | 또 보이는 형태: 언어 / 언어 선택. UI 언어 전환은 '표시 언어'. 그냥 '언어'는 소스코드 언어와 헷갈리므로 이 콘솔에서도 '표시 언어'를 권장. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `loading` | **로드 중...** | 또 보이는 형태: 불러오는 중. 말줄임표 포함이 관례. 진행 상태는 모두 '-하는 중' / '-중' 형: '시작하는 중', '중지하는 중'. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `no results` | **결과 없음** | 또 보이는 형태: 결과를 찾을 수 없습니다.. 좁은 자리(뱃지·인라인)는 명사형 '결과 없음', 넓은 빈 화면은 합니다체 한 문장. 두 형태를 한 화면에 섞지 말 것. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `not reachable` | **연결할 수 없음** | 또 보이는 형태: 연결되지 않았습니다 (문장) / 연결 안 됨. '도달할 수 없음'은 한국어 UI에 없음 — 쓰지 말 것. 서비스가 안 뜰 때는 '연결할 수 없음'. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `nothing yet` | **아직 …이(가) 없습니다** | 또 보이는 형태: 사용 가능한 …이(가) 없습니다. '아직'은 '데이터가 곧 생김'을, '사용 가능한 …없음'은 '해당 없음'을 뜻함 — 구분해서 씀. 짧은 명사형 라벨(예: '아직 없음')로 쓰인 예는 못 찾음. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `open (동사/버튼)` | **열기** | '오픈' 아님. '<대상> 열기' 어순. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `open (상태: 미종결)` | **열림** | 또 보이는 형태: 활성 / 미처리. 보안 인시던트/케이스의 미종결 상태는 '열림'. Microsoft Sentinel 한국어는 같은 자리에 '활성'을 씀. | [docs.aws.amazon.com](https://docs.aws.amazon.com/ko_kr/security-ir/latest/userguide/dashboard.html) |
| `pause` | **일시 중지** | 또 보이는 형태: 일시 중지됨 (상태). 버튼은 '일시 중지', 상태 칩은 '일시 중지됨'. 띄어쓰기 '일시 중지' (붙여쓴 '일시중지' 아님). | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `paused` | **일시 중지됨** | 상태는 '-됨' 형. 문장으로 풀지 않음. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `refresh` | **새로 고침** | 또 보이는 형태: 자동 새로 고침. 반드시 띄어쓰기 '새로 고침'. '갱신'·'리프레시' 아님. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `REGISTER — 버튼 라벨` | **명사형/동사 명사형 (종결어미 없음)** | 버튼은 예외 없이 '-기' 또는 한자 명사. '저장하기'·'닫아요'·'저장합니다' 같은 형태는 한 건도 없음. 목적어가 필요하면 '<명사> <동작>' 어순 ('세션 시작', '터미널 세션 중지'). | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `REGISTER — 빈 상태` | **짧은 자리는 명사형, 넓은 자리는 합니다체 한 문장** | 문장형 빈 상태는 항상 '-습니다.'로 끝나고 마침표를 찍음. '-어요'·'-네요'는 0건. 명사형 빈 상태에는 마침표를 찍지 않음. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `REGISTER — 상태 라벨` | **'-중' / '-됨' 형** | 진행형은 '-중', 완료/피동은 '-됨', 불가능은 '-할 수 없음'. 세 형태만 쓰고 문장으로 풀지 않음. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `REGISTER — 오류 메시지` | **합니다체 + 명령형은 '-하세요'** | 패턴이 고정돼 있음: [무슨 일이 일어났는가 + 했습니다.] + [무엇을 하라 + 하세요.] 두 문장. '-해 주세요'·'-해요'·'-바랍니다'는 쓰지 않음. 주어를 '사용자님'처럼 부르지 않고 생략함. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `retry` | **다시 시도** | 또 보이는 형태: 다시 시도하세요 (오류 문장 안에서). 버튼은 '다시 시도', 문장 안에서는 '다시 시도하세요'. '재시도'는 버튼 라벨로 쓰지 않음. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `running` | **실행 중** | '구동 중'·'가동 중' 아님. '실행중' 붙여쓰기 아님. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `save` | **저장** |  | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `search` | **검색** | 또 보이는 형태: 조회 (SIEM 로그 검색 화면). '찾기'는 에디터 내 Find에만. 목록/로그는 '검색'. 국내 SIEM UI는 '조회'도 씀. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `settings` | **설정** | '환경설정'·'세팅' 아님. 단, '…하도록 설정합니다'처럼 동사로도 쓰이니 메뉴 라벨은 단독 '설정'. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `start` | **시작** | 또 보이는 형태: 세션 시작 / 시작하는 중 (전이 상태). 버튼은 <목적어> + 시작 어순. 이 콘솔이면 '세션 시작'. 진행 중 상태는 '시작하는 중' (mcpCommands/mcp.agentHost.status.starting). '스타트'·'개시'는 쓰지 않음. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `stop` | **중지** | 또 보이는 형태: 중지됨 (상태) / 중지하는 중. '정지'가 아니라 '중지'. 상태 라벨은 '중지됨' (mcpTypes/mcpstate.stopped). '세션 중지'처럼 목적어를 앞에 둠. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `time range` | **시간 범위** | 또 보이는 형태: 기간. Microsoft Learn 한국어도 "최대 30일의 과거 시간 범위를 쿼리하여"로 동일. 시작/끝이 있는 구간은 '기간', 조회 창은 '시간 범위'. | [elastic.co](https://www.elastic.co/kr/kibana/kibana-dashboard) |
| `top N` | **상위 N개** | 또 보이는 형태: 상위 5개 / 상위 N개 목록. '상위 N' 뒤에 반드시 분류사 '개'가 붙음. 'Top N' 그대로 두는 화면도 있으나 한국어 UI는 '상위 N개'가 표준. | [learn.microsoft.com](https://learn.microsoft.com/ko-kr/azure/azure-monitor/vm/vminsights-performance) |
| `total` | **총 …수** | 또 보이는 형태: 합계. '전체'는 '전부'를 강조할 때만. 숫자 합계 라벨은 '총 <명사> 수'. '총계'는 VS Code 한국어에 0회. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `unavailable` | **사용할 수 없음** | 상태 라벨은 명사형 '사용할 수 없음'. 문장 자리에서는 '…을(를) 사용할 수 없습니다.' | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |
| `validate` | **유효성 검사** | 또 보이는 형태: 검증. 단독 버튼 라벨로 쓰인 예는 못 찾음 — 항상 '<대상> 유효성 검사' 형태. 룰 문법 검사라면 '규칙 유효성 검사'. 보안 문서체에서는 '검증'도 통용. | [raw.githubusercontent.com](https://raw.githubusercontent.com/microsoft/vscode-loc/main/i18n/vscode-language-pack-ko/translations/main.i18n.json) |


## No settled term

Things this product does that the field has no word for, in one language or both. The
evidence is a search that came back empty, not an oversight. **These keep their English or
are spelled out. Do not invent a replacement.**


**Detection and alerting**

- rule id (sid) — 'sid'를 한국어로 뭐라 부르는지 1차 출처를 못 찾았습니다. 구글 클라우드 IDS 한국어 문서는 '위협 ID'를 쓰지만 이건 Palo Alto 고유 개념이라 Suricata sid와 다릅니다. 국내 Snort/Suricata 룰 설명은 전부 개인 블로그뿐이라 인용 불가. 권고: 'SID' 또는 '룰 ID'로 영문 유지.
- true negative (TN) — 한국 관제 현업에 굳어진 단어가 없음이 확인됐습니다. 정탐/오탐/미탐 셋만 쓰이고 TN은 아예 화제에 오르지 않습니다. 통계 용어 '참음성'만 출처가 있어 그쪽으로 넣었으나, 콘솔에서는 약어 TN 병기를 권합니다.
- unattributed / uncorrelated alert — 어느 공격 케이스에도 붙지 않은 알림을 가리키는 한국어를 어느 출처에서도 찾지 못했습니다. 국내 관제 문서는 이 상태를 따로 이름 붙이지 않고 '미분류', '원인 미상'처럼 그때그때 풀어 씁니다. 근거 없이 단정하지 않겠습니다 — '미귀속'은 제 창작이 될 것이라 쓰지 않았습니다.
- alert vs notification 구분 — 경보(IDS가 올린 것)와 알림(시스템이 사용자에게 보내는 것)을 한 화면에서 구분해 쓰는 국내 용례를 확인할 출처를 찾지 못했습니다. 콘솔에서 둘 다 필요하면 경보/알림으로 나누되 근거는 없습니다.
- triage — 영어 단어에 1:1 대응하는 한국 관제 용어가 없습니다. '정·오탐 판단'은 작업 이름이고 '알림 분류'는 클라우드 번역투라, 둘 다 완전한 대응은 아닙니다.

**Attack and exercise**

- session / run of an exercise — '훈련 세션', '훈련 회차', '차수' 어느 것도 KISA·금융보안원·벤더 문서에서 확인하지 못함. KISA는 '연 2회(상·하반기) 실시'처럼 횟수만 서술하고 한 번의 실행을 가리키는 명사를 쓰지 않음. 영어 session을 그대로 둘지 '훈련 회차'로 할지는 근거 없이 정해야 하는 자리.
- operator (콘솔의 역할 라벨로서의 '오퍼레이터' 또는 '운영자') — 공격을 수행하는 사람은 '화이트해커'로 사원되지만, 레드팀 역할 이름으로서의 operator는 1차 출처에 없음. 검색 결과에 '레드팀 오퍼레이터'가 보였으나 출처가 개인 블로그(blog.sunggwanchoi.com)라 채택하지 않음.
- operator log — '오퍼레이터 로그(Operator Log)'라는 표현이 개인 블로그에만 존재. KISA/금융보안원/보안기업 문서에서 확인 실패. '수행 기록', '공격 로그' 중 무엇을 쓸지 근거 없음.
- redirector (C2 리다이렉터) — 한국어 1차 출처를 전혀 찾지 못함. 국내 문서는 '프록시'까지만 다루고 레드팀 인프라의 redirector 개념을 다루는 공개 한국어 문서가 없음. 영어 그대로 두는 것이 안전해 보이나 이를 뒷받침할 인용도 없음.
- solved (UI 상태 라벨) — 동사 '문제를 풀다'는 확인했으나, 상태 배지로서의 '풀림/해결됨/성공' 중 무엇이 표준인지 보여 주는 출처 없음.
- SK쉴더스 EQST 및 SK쉴더스 레드팀 인사이트 문서 — 레드팀 용어의 1급 국내 출처로 보였으나 두 URL 모두 HTTP 403으로 본문을 가져오지 못함. 접근 가능해지면 레드팀/오퍼레이터/C2 용어를 다시 확인할 가치가 있음.
- KISA 아카데미(academy.kisa.or.kr) 및 kisa.or.kr 일부 페이지 — TLS 인증서 체인 검증 실패로 fetch 불가. 실전형 사이버훈련장의 실제 UI 용어(난이도 표기, 훈련 단위 명칭)는 여기에 있을 가능성이 높음.

**Network and assets**

- zone as 존(Zone) - I could not get a single first-party Korean source (TTA, KISA, 금융보안원, AhnLab, Igloo) to write 존 for a network zone. Every one of them uses 영역, 구간, or -망. Recommendation: do NOT ship 존 in the console; use 영역 for the concept and 인터넷망/내부망/DMZ for the segment names. If the UI needs the English, keep 'Zone' rather than 존.
- front door / ingress - nothing sourced. No Korean security document I fetched names the edge device this way. The nearest sourced idea is 외부 공개 (externally exposed), which describes the app, not the nginx in front of it. Candidates 진입점 / 관문 / 인그레스 all failed to appear in any first-party source. Recommendation: keep English (nginx / ingress) or restate as 외부 공개 웹 서버.
- application estate - no Korean term found anywhere. Korean documents talk about 자산 (assets) and 업무 영역, never an 'estate'. Recommendation: do not translate the metaphor; call it 대상 자산 or 애플리케이션 자산 if a label is needed, and say so is a coinage.
- internal wiki - 내부 위키 appears in no first-party Korean security or IT document I could reach. Recommendation: keep 'wiki' in English (내부 위키 is understandable but unsourced), or name the thing concretely (내부 문서 서버).
- reverse proxy as 역방향 프록시 - only 리버스 프록시 could be sourced (Igloo). 역방향 프록시 exists in Microsoft's Korean pages but those are machine-translated (ms.translationtype: MT), so I did not count them. Use 리버스 프록시.
- network segment as 네트워크 세그먼트 - not sourced as a networking headword. TTA's 세그먼트 entry covers memory and database segments only; the word appears in networking sense just once, inside the 서브넷 definition. Use 네트워크 구간 or 영역.
- Microsoft Learn ko-kr was rejected as a source tier. Every Azure security page I fetched carries 'ms.translationtype: MT' in its front matter - machine translation, not the carefully reviewed Korean glossary the brief assumed. Its output is visibly unidiomatic ('둘레' for perimeter, '완만 영역' for DMZ, '판독기 권한' for Reader). Do not use it to settle Korean terminology.
- isms.kisa.or.kr / isms-p.kisa.or.kr (the ISMS-P 인증기준 안내서, which would have settled 네트워크 영역 / DMZ / 서버팜 authoritatively) did not resolve in DNS from this machine, and www.ncsc.go.kr's N2SF guideline page returned an error. Those two documents are the best remaining sources for segment vocabulary if someone can reach them.

**General product UI**

- most frequent — 한국어 제품 UI에서 '가장 빈번한'·'빈도순' 같은 라벨을 1차 출처로 확인하지 못함. VS Code 한국어 언어팩에 '빈도' 0건, '가장 많' 0건. 한국재정정보원 사이버안전센터 통계는 '악성코드 감염이 39.2%로 가장 높은 비중을 차지했으며'처럼 보고서 산문체일 뿐 UI 라벨이 아님(https://fis.kr/ko/major_biz/cyber_safety_oper/attack_info/notice_issue?articleSeq=2589). 이 자리는 'most frequent'를 따로 번역하지 말고 근거가 확실한 '상위 N개'로 통일할 것을 권함.
- validate (단독 버튼 라벨) — '유효성 검사'는 '<대상> 유효성 검사' 형태로만 확인됨. 버튼 하나에 '유효성 검사'만 올린 1차 사례는 못 찾음. 목적어를 붙여 '규칙 유효성 검사'로 쓰는 편이 안전.
- nothing yet (짧은 명사형 라벨) — 문장형('아직 … 없습니다')만 확인됨. 칩·뱃지 크기의 짧은 라벨은 근거 없음. 좁은 자리에는 근거가 있는 '결과 없음'을 쓸 것.
- 국내 보안 벤더 UI 원문 — 이글루코퍼레이션 SPiDER TM 가이드(igloo.co.kr)는 TLS 인증서 체인 검증 실패로 가져오지 못했고, 안랩·SK쉴더스·윈스는 공개 페이지에 콘솔 문자열이 노출되지 않아 '미처리/처리중/처리완료' 같은 국내 관제 상태 어휘를 1차 출처로 확정하지 못함. 인시던트 상태는 AWS 한국어 문서의 '열림/종결'을 근거로 사용함.
- KISA·TTA 용어사전 — krcert.or.kr 동향 문서는 404, terms.tta.or.kr은 검색 결과에 노출되지 않아 이번 어휘(일반 UI 동사·상태어)에 대해서는 인용 가능한 항목을 얻지 못함. 다만 이번 목록은 보안 전문용어가 아니라 일반 제품 UI 어휘라 해당 출처가 필수는 아님.


## How to add a word

Find it in a primary source first: the product's own documentation, its published UI
strings, or a standards body. For Korean that means a Korean security vendor's own writing,
KISA, 금융보안원, or the Korean edition of a product's official docs - not a blog and not a
course page. Quote the sentence you found it in. If there is no such page, the word goes
under *No settled term* and the English stays.

