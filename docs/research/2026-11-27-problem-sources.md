# 공개 문제 작성용 참고 자료 선별

## 목적

board(Django 게시판)와 corp(WordPress 회사 사이트) 워게임에 쓸 한국어 공개 문제의 근거 자료를 골랐습니다. 다섯 갈래(KISA, 국내 기타, 블루팀 플랫폼, 사이버 레인지, 웹 콘텐츠)로 모은 자료에서 다음 셋 중 하나에 해당하는 것만 남겼습니다.

- 웹 공격과 WAF/IDS 방어 문제를 쓰는 데 직접 쓸 수 있다.
- 우리 점수 체계와 맞는 채점·형식 아이디어를 준다. 우리 점수는 타깃 ground truth로 판정한 objective 손실, 탐지·대응 O/X, 케이스별 TP/FP/FN/TN이다.
- 심은 취약점이 아닌 현실적인 취약 원인을 준다.

이용 조건상 본문을 가져다 쓸 수 없는 자료는 문제를 직접 쓰고 출처만 인용하는 용도로 남겼습니다. 각 워게임의 실제 구성은 레포 기준입니다.

- board: `Django==3.2.4`, 정렬 파라미터를 `order_by(sort)`에 그대로 넘김 (`wargames/board/app/posts/views.py`)
- corp: `wordpress:6.6.2`, 플러그인 `ultimate-member/2.6.6`, `wp-gdpr-compliance/1.4.2`, `easy-post-submission/2.3.0` (`wargames/corp/app/Dockerfile`)

## 선별 자료

| 이름 | 기관 | 링크 | 쓸 수 있는 것 | 이용 조건 | 우리 프로젝트에 맞는 이유 |
|---|---|---|---|---|---|
| 2026 주요정보통신기반시설 기술적 취약점 분석·평가 방법 상세가이드 | KISA | https://www.kisa.or.kr/2060204/form?postSeq=22 | Web Application 21개 항목 코드(SI, XS, FD, BF, AU, AE 등), 웹 서비스 WEB-01~26, 보안 장비 S-01~23, 항목별 중요도 상/중/하와 양호/취약 기준 | 공공누리 표시 없음, "All rights reserved". 가이드 앞부분에 "교육기관 등에서 교육 자료로 활용하는 것을 권장하지 않습니다"라고 적혀 있음. 항목명·코드 인용만 함 | 공격 케이스와 블루 점검 항목에 붙일 한국어 공통 용어. CI 항목의 조치 방법이 웹 방화벽 룰셋 적용을 직접 언급함 |
| TTPs$ 국내 기업 환경의 공격표면 분석 및 대응전략 | KISA KrCERT/CC | https://www.boho.or.kr/kr/bbs/view.do?bbsId=B0000127&menuNo=205021&nttId=72138 | 3.1 대외 웹서비스·DMZ 환경, 3.4 업무 WAS·DB 관리·개발 환경 침해 시나리오, 4.1 AI 기반 공격 탐색의 특징 | TLP:CLEAR, 공공누리 없음. 재사용 조건 미확인. 인용만 함 | 국내 사례로 문제 배경을 쓸 수 있고, 봇 상대 라운드의 근거가 됨. PDF 본문은 미확인 |
| 웹 에디터 보안 가이드 | KISA KrCERT/CC | https://www.boho.or.kr/kr/bbs/view.do?bbsId=B0000127&menuNo=205021&nttId=67020 | FCKeditor, CKeditor, SmartEditor 2.0 등 국내 사이트에 흔히 쓰이는 에디터의 취약점과 조치 | 공공누리 없음. 인용만 함 | 국내 게시판에서 현실적으로 생기는 파일 업로드 침해 원인. 다만 board에는 아직 에디터가 없음 |
| 보호나라 보고서/가이드 게시판의 옛 사고분석 | KISA KrCERT/CC | https://www.boho.or.kr/kr/bbs/list.do?menuNo=205021&bbsId=B0000127 | [IN2005009] phpBB 취약점을 이용한 홈페이지 변조, [IN2007004] 취약한 웹서버 공격을 통한 내부망 해킹, TTPs#1 홈페이지를 통한 내부망 장악 사례 분석 | 게시물별 조건 미확인. 제목만 확인함 | 공개 CVE로 커뮤니티 게시판이 뚫린 실제 사례로, board 워게임의 전제와 같음 |
| 보호나라 취약점 정보 / 보안공지 | KISA KrCERT/CC | https://www.boho.or.kr/kr/bbs/list.do?menuNo=205023&bbsId=B0000302 | CVE별 심각도·CVSS, "<제조사> 제품 보안 업데이트 권고" 문구 | 공공누리 없음. 사실 인용만 함 | 구버전 CVE 문제의 한국어 권고문 문체를 참고할 수 있음 |
| [TR2008003] ModSecurity를 활용한 아파치 웹서버 보안 강화 가이드 | KISA KrCERT/CC | https://www.boho.or.kr/kr/bbs/view.do?bbsId=B0000127&menuNo=205021&nttId=21488 | ModSecurity 한국어 용어, "ModSecurity를 이용한 모의 공격 차단" | 인용 시 "[자료:한국인터넷진흥원(KISA)]" 명시 조건 | ModSecurity 용어를 한국어로 옮길 때 참고. 1.x/2.x 기준이라 CRS v4 내용은 아님 |
| OWASP CRS regression tests | OWASP CRS project | https://github.com/coreruleset/coreruleset/tree/main/tests/regression/tests | 룰 그룹별 페이로드와 기대 rule ID 쌍(930 LFI, 932 RCE, 941 XSS, 942 SQLI 등). 예: 942100.yaml `var=1234 OR 1=1` → `expect_ids [942100]` | Apache 2.0. 저작권·라이선스 고지를 남기면 복사 가능 | 케이스의 `expect` 문자열과 WAF 룰 테스트 페이로드로 바로 쓸 수 있음 |
| CRS 문서: paranoia levels | OWASP CRS project | https://coreruleset.org/docs/2-how-crs-works/2-2-paranoia_levels/ | PL 1~4와 FP의 trade-off, exclusion으로 튜닝 | 문서 라이선스 미확인. 인용만 함 | 블루 문제 "PL을 올리고 정상 트래픽 FP는 exclusion으로 제거"가 우리 FP/TN 점수와 그대로 맞음 |
| Emerging Threats Open (Suricata) | Proofpoint ET | https://rules.emergingthreats.net/open/suricata-7.0.3/rules/ | emerging-web_server, emerging-web_specific_apps, emerging-sql, emerging-scan 등 | SID 2000000-2799999 BSD, 1-3464·100000000-100000908 GPLv2, 2800000-2900000 ETPro(비공개) | IDS 케이스의 `expect`에 SID msg를 쓸 수 있음. 파일별 내용은 미확인 |
| Django security issues archive | Django Software Foundation | https://docs.djangoproject.com/en/dev/releases/security/ | Django CVE별 날짜, 영향 버전, 패치 | 문서 라이선스 미확인. CVE 사실만 쓰고 설명은 직접 씀 | board 타깃(Django 3.2.4)의 구버전 원인 근거 |
| GitHub Advisory Database | GitHub | https://github.com/github/advisory-database | pip·Composer 등 생태계 패키지의 advisory(OSV JSON) | CC BY 4.0. 한국어 번안 가능 | corp 플러그인 CVE와 board 파이썬 패키지 CVE를 확인하는 원천 |
| PyPA Advisory Database | PyPA | https://github.com/pypa/advisory-database | PyPI 패키지 advisory(OSV YAML) | CC BY 4.0(저장소 라벨만 확인) | board `requirements.txt` 패키지의 CVE 확인용 |
| OWASP Top 10:2025 / 2021 | OWASP Foundation | https://top10.owasp.org/2025 · https://top10.owasp.org/2021 | 문제 분류 라벨(A01~A10) | CC BY 3.0. 번안·상업 이용 가능, 저작자 표시 필요 | 2021 A06 구버전 구성요소, A05 설정 오류는 "심은 취약점 금지" 원칙과 같은 분류. 2025 A09 Logging and Alerting Failures는 블루 쪽 주제 |
| OWASP WSTG v4.2 | OWASP Foundation | https://wstg.owasp.org/v4.2/ | 4장 테스트 절차(정보 수집 → 인증 → 인가 → 입력 검증) | CC BY-SA 4.0. 번안하면 ShareAlike가 따라붙으므로 직접 쓰고 인용만 함 | 레드 문제의 공격 단계 순서 근거 |
| MITRE ATT&CK T1190 / T1110 / T1595, CAPEC, CWE | MITRE | https://attack.mitre.org/techniques/T1190/ · https://attack.mitre.org/techniques/T1110/ · https://attack.mitre.org/techniques/T1595/ · https://capec.mitre.org/data/definitions/66.html · https://cwe.mitre.org/about/termsofuse.html | 기법·공격 패턴·약점 ID 태그 | royalty-free, 상업 이용 가능, 사본에 저작권 고지 유지. 수정 언급은 없으므로 ID만 태그로 씀 | 케이스가 이미 `technique`, `pattern`(CAPEC) 필드를 씀. T1190 정의가 "software bug, ... or a misconfiguration"이어서 우리 원칙과 같음 |
| Locked Shields availability scoring (Pihelgas) | NATO CCDCOE | https://www.ccdcoe.org/uploads/2020/02/M_Pihelgas_-_Design_and_Implementation_of_an_Availability_Scoring_System_for_Cyber_Defence_Exercises.pdf | 레드팀 공격 성공은 감점. 가용성 점수가 공격 감점과 비슷한 비중 | 재사용 라이선스 표기 없음. 인용만 함 | objective 손실과 benign 케이스(FP) 규칙에 가장 가까운 공개 모델 |
| Trends and challenges for balanced scoring (Locked Shields) | Frontiers in Education 2022 | https://www.frontiersin.org/articles/10.3389/feduc.2022.958405 | 공격을 web·network·client-side로 분류, SITREP과 key event 대조, 더미 서비스로 체크를 속이면 감점 | open access(CC BY 추정, 미확인) | "모두 막으면 FP 점수는 좋지만 objective는 다 잃는다"는 우리 원칙의 근거 |
| Cybersecurity AI: Attack/Defense CTFs (arXiv 2510.17521) | Alias Robotics | https://arxiv.org/html/2510.17521v1 | patching과 operational defence(가용성을 지키는 방어)를 구분. 성공률 54.3% → 23.9% | arXiv, 재사용 조건 미확인. 인용만 함 | 사람 대 AI 봇 라운드에 가장 가까운 선행 연구 |
| ENOWARS docs (FAUST 계열) | ENOFLAG | https://enowars.github.io/docs/play/general | 공격·방어·SLA 분리. gameserver가 정상 기능으로 flag를 회수 | 규칙 문서. 인용만 함 | gameserver의 SLA 체크가 우리 benign 케이스와 같은 역할 |
| KYPO Training Design Field Manual / demo training.json | Masaryk University | https://webcentrum.muni.cz/media/3462734/kypo_crp-training_design-field_manual_v10.pdf · https://gitlab.ics.muni.cz/kypo-library/content/kypo-library-demo-training/-/raw/master/training.json | 시나리오 작성 절차(목표, 스토리, ATT&CK 매핑, inject). 문제 스키마(`max_score`, `hint_penalty`, `solution_penalized`) | demo training은 MIT. 매뉴얼 본문은 라이선스 표기 없음 | 우리와 같은 OpenStack 기반 레인지. 문제 문서 형식의 본보기 |
| Splunk BOTS v1 | Splunk | https://github.com/splunk/botsv1 | suricata, iis, stream:http 로그와 attack-only 데이터셋. Q&A는 요청 시 공개 (https://www.splunk.com/en_us/blog/security/boss-of-the-soc-scoring-server-questions-and-answers-and-dataset-open-sourced-and-ready-for-download.html) | CC0-1.0 | 유일하게 재사용 가능한 블루 콘텐츠. Kibana 로그 분석 문제의 형식 참고. Elasticsearch 적재는 해 보지 않음 |
| SA-ctf_scoreboard | Splunk | https://github.com/splunk/SA-ctf_scoreboard | 질문·답·힌트 CSV 구조 | CC0 1.0(일부 파일 제외), 2022년 지원 종료 | 문제 데이터 형식 참고 |
| TryHackMe SOC Sim | TryHackMe | https://help.tryhackme.com/en/articles/10508054-soc-sim | TP·FP가 섞인 실시간 알림 큐, TP를 오분류하면 시나리오 실패 | 독점, 형식만 참고 | 우리 TP/FP 판정과 "대응 없이 잃으면 2배" 규칙과 비교할 거리 |
| LetsDefend Detecting Web Attacks / 시나리오 생성 방식 | LetsDefend | https://app.letsdefend.io/training/lessons/web-attacks-101 · https://letsdefend.io/blog/how-we-generate-simulated-siem-alerts | SQLi·LFI·명령어 삽입 알림 이름(SOC165 등). 시나리오 구성 절차(공격 → 로그 → 시그니처 → 알림 → 플레이북 → 사고 보고) | 조건 표기 없음, 형식만 참고 | 문제 한 개를 쓰는 절차의 본보기. 알림 이름이 board 케이스와 대응됨 |
| 사이버공격방어대회 CCE | 국가정보원 주최(주관 문구 미확인) | https://cce.cstec.kr | 문제 유형을 "예방(취약점 점검)"과 "탐지 분석 대응(사고조사)"으로 나눔. 공격팀·방어팀 분리. "방어목표시스템의 가용성 확보" | 재사용 조건 미확인, 형식만 참고 | 레드·블루 분리를 한국어로 부르는 실제 용례 |
| 화이트햇 2026 | 국방부 주최(검색 요약 기준) | https://www.whitehat2026.kr | IR 부문: "침해사고 시나리오 기반 로그·증거 분석" | 형식만 참고 | 블루 쪽 Kibana 로그 분석 문제의 한국어 명칭 |
| KISA 사이버 위기대응 모의훈련 / 사이버 시큐리티 훈련 플랫폼 | KISA | https://www.boho.or.kr/kr/subPage.do?menuNo=205014 · https://www.boho.or.kr/kr/subPage.do?menuNo=205015 | "AI 에이전트를 활용하여 홈페이지 별 맞춤형 시나리오로 수행하는 AI 모의침투". 탐지 대응: "알려진 취약점 공격에 대한 탐지, 대응체계 여부 점검 (IPS, WAF 등...)" | 시나리오 비공개, 용어만 인용 | 국내 공공기관이 AI 모의침투와 WAF 탐지 대응 점검을 이미 운영함. 문제 소개문의 근거 |

## board 워게임 후보 문제

| 문제 제목 | 공격 경로(현실적 원인) | 방어 측이 탐지·차단할 것 | 출처 |
|---|---|---|---|
| 게시판 정렬 파라미터로 계정 테이블 빼내기 | Django 3.2.4가 `order_by()`에 사용자 입력 정렬값을 그대로 받음(`views.py`). CVE-2021-35042(QuerySet.order_by SQLi, 3.2.5에서 수정)로 판단되나, 보안 아카이브 원문과 대조하지 않아 미확인. sqlmap으로 `auth_user`를 덤프하면 objective "게시판 계정 일부/관리자/전체 계정 탈취" | CRS 942 SQLI 탐지(`expect: SQL`). sqlmap `--random-agent`, `--tamper` 변형 대응. 정상 정렬 요청(`board-normal-sort`)은 통과시켜야 함. 요청 약 2,000건이 한 케이스로 집계됨 | https://docs.djangoproject.com/en/dev/releases/security/ · https://github.com/coreruleset/coreruleset/tree/main/tests/regression/tests · https://attack.mitre.org/techniques/T1190/ · KISA 상세가이드 SI https://www.kisa.or.kr/2060204/form?postSeq=22 |
| 검색창 SQL 인젝션과 UNION 조회 | 검색 기능의 SQL 인젝션(`board-sqli-search`, `board-sqli-union-search`). 이 경로의 원인 코드가 현실적 원인 원칙에 맞는지 미확인 | 942 계열 탐지. 아포스트로피가 들어간 정상 검색(`board-normal-search-with-apostrophe`)과 한글 검색은 FP 없이 통과 | https://github.com/coreruleset/coreruleset/tree/main/tests/regression/tests · https://capec.mitre.org/data/definitions/66.html |
| 로그인 우회 | 로그인 폼에 `' OR 1=1--` 입력(`board-sqli-login-bypass`) | 942 탐지. 같은 origin 차단(deny)으로 대응 O | KISA 상세가이드 SI·IA https://www.kisa.or.kr/2060204/form?postSeq=22 · https://attack.mitre.org/techniques/T1190/ |
| 댓글 XSS | 댓글의 `<img onerror>`, 검색어의 `<script>`(`board-xss-*`) | CRS 941 XSS(`expect: XSS`). 정상 댓글(`board-normal-comment`)은 통과 | KISA 상세가이드 XS · https://github.com/coreruleset/coreruleset/tree/main/tests/regression/tests |
| 정적 파일 경로 조작 | `board-path-traversal-static`(`expect: traversal`) | CRS 930 LFI, ET emerging-web_server | KISA 상세가이드 FD · https://github.com/coreruleset/coreruleset/tree/main/tests/regression/tests · https://rules.emergingthreats.net/open/suricata-7.0.3/rules/ |
| 로그인 무차별 대입 (추가 후보) | 약한 비밀번호 정책을 노린 password guessing 또는 credential stuffing. 현재 케이스는 없음 | WAF error log의 `limit_req`나 deny로 origin을 막아 대응 O | https://attack.mitre.org/techniques/T1110/ · KISA 상세가이드 BF·AU |
| 웹 에디터 파일 업로드 (보류) | 구버전 웹 에디터의 업로드 취약점. board에 에디터를 넣어야 하므로 제품 결정이 필요함 | 웹쉘 업로드 요청과 응답 탐지(CRS 955 계열은 미확인) | https://www.boho.or.kr/kr/bbs/view.do?bbsId=B0000127&menuNo=205021&nttId=67020 |

배경 서사는 공개 CVE로 커뮤니티 게시판이 변조된 실제 사례를 참고할 수 있습니다. 게시물 제목은 [IN2005009] phpBB 취약점을 이용한 홈페이지 변조입니다(https://www.boho.or.kr/kr/bbs/list.do?menuNo=205021&bbsId=B0000127). 본문은 열어 보지 않아 내용은 미확인입니다.

## corp 워게임 후보 문제

| 문제 제목 | 공격 경로(현실적 원인) | 방어 측이 탐지·차단할 것 | 출처 |
|---|---|---|---|
| 회원가입으로 관리자 계정 만들기 | Ultimate Member 2.6.6 회원가입 폼에 `wp_capabilities[administrator]` 파라미터를 끼워 넣음(케이스 `corp-rogue-admin`은 유니코드 변형 `wp_càpabilities` 사용). CVE-2023-3460으로 판단되나 GitHub Advisory DB 대조는 미확인. objective "무단 관리자 계정 생성" | 요청 본문의 `[administrator]` 탐지(`expect`). 정상 회원가입(`corp-normal-registration`)은 통과 | https://github.com/github/advisory-database · https://attack.mitre.org/techniques/T1190/ · KISA 상세가이드 IN·PV |
| 인증 없이 사이트 설정 바꾸기 | WP GDPR Compliance 1.4.2의 admin-ajax `wpgdprc_process_action`으로 `users_can_register` 옵션 변경. CVE-2018-19207로 판단되나 대조는 미확인. objective "관리자 권한 회원가입 허용" | `users_can_register` 문자열이 든 admin-ajax 요청 탐지·차단 | https://github.com/github/advisory-database · KISA 상세가이드 IN https://www.kisa.or.kr/2060204/form?postSeq=22 |
| 비회원 글 등록으로 홈페이지 변조 | Easy Post Submission 2.3.0의 `rbsm_submit_post`로 비회원이 기존 글(postId 1)을 덮어씀. 해당 CVE 번호는 미확인. objective "콘텐츠 무단 작성·변조" | `rbsm_submit_post` 중 postId를 지정한 요청 차단. 정상 이용 흐름은 benign 케이스로 따로 정의해야 함(현재 없음, 미확인) | https://github.com/github/advisory-database · 보호나라 웹서버 보안 강화 안내서(2.1 홈페이지 변조) https://www.boho.or.kr/kr/bbs/view.do?bbsId=B0000127&menuNo=205021&nttId=27364 |
| 관리자 페이지 노출 (추가 후보) | `/wp-admin/`과 `/wp-login.php`가 외부에 그대로 열려 있는 설정 | 관리자 경로 접근 제한, 로그인 무차별 대입 `limit_req` | KISA 상세가이드 AE·BF · https://attack.mitre.org/techniques/T1110/ |
| 스캐너 정찰 (레슨 자료) | 디렉터리·워드리스트 스캔 | CRS 913, ET emerging-scan 탐지. 11-22 결정에 따라 스캐너는 점수에서 제외하고 레슨 자료로만 씀 | https://attack.mitre.org/techniques/T1595/ · https://rules.emergingthreats.net/open/suricata-7.0.3/rules/ |

배경 서사는 TTPs$ 보고서 3.1 대외 웹서비스·DMZ 환경을 참고합니다(https://www.boho.or.kr/kr/bbs/view.do?bbsId=B0000127&menuNo=205021&nttId=72138). PDF 본문은 미확인입니다.

## 채택할 만한 채점·형식 아이디어

| 아이디어 | 우리 점수와의 관계 | 출처 |
|---|---|---|
| 가용성 점수가 공격 감점과 비슷한 비중이어야 함 | benign 케이스 FP 규칙의 근거. 문제 설명에 "정상 트래픽을 막으면 실패"를 적는 이유 | https://www.ccdcoe.org/uploads/2020/02/M_Pihelgas_-_Design_and_Implementation_of_an_Availability_Scoring_System_for_Cyber_Defence_Exercises.pdf |
| SITREP을 key event와 대조, 체크를 속이면 감점 | 블루가 쓰는 사고 보고를 objective 손실 시점과 대조하는 문제 형식(미채택 후보) | https://www.frontiersin.org/articles/10.3389/feduc.2022.958405 |
| operational defence: 가용성을 지킨 방어만 방어로 인정 | 봇 상대 라운드의 대응 O 판정과 같은 원칙 | https://arxiv.org/html/2510.17521v1 |
| gameserver가 정상 기능으로 flag를 회수해 SLA 확인 | 플랫폼이 발사하는 benign 케이스와 같은 구조 | https://enowars.github.io/docs/play/general |
| CRS regression YAML의 `expect_ids` / `no_expect_ids` | 케이스 `expect`에 rule ID를 넣고, FP 케이스는 `no_expect_ids`처럼 기술 | https://github.com/coreruleset/coreruleset/tree/main/tests/regression/tests |
| 문제 스키마: `max_score`, `hint_penalty`, `solution_penalized`, `estimated_duration` | 공개 문제 문서의 필드 구성. 힌트 감점 도입 여부는 제품 결정 사항 | https://gitlab.ics.muni.cz/kypo-library/content/kypo-library-demo-training/-/raw/master/training.json |
| 시나리오 작성 절차(목표 → 스토리 → ATT&CK 매핑 → inject) | 문제 한 개의 작성 순서 | https://webcentrum.muni.cz/media/3462734/kypo_crp-training_design-field_manual_v10.pdf |
| "예방(취약점 점검)" / "탐지 분석 대응(사고조사)" 구분 | 레드·블루 문제를 한국어로 분류할 때의 명칭 | https://cce.cstec.kr |
| KISA 항목 코드와 중요도 상/중/하 | 문제 태그(SI, XS, FD 등)와 난이도 표기의 참고. objective `difficulty`와 별개 | https://www.kisa.or.kr/2060204/form?postSeq=22 |
| attack-only 데이터셋("just the needles") | 라운드 후 복기 문제: 공격 트래픽만 남긴 로그로 Kibana 질의 연습 | https://github.com/splunk/botsv1 |
| TP 오분류 시 시나리오 실패 | "대응 없이 잃으면 2배" 규칙과 비교할 만한 사례. 그대로 도입하지는 않음 | https://help.tryhackme.com/en/articles/10508054-soc-sim |

## 제외한 자료

- 웹서버 보안 강화 안내서(2018, https://www.boho.or.kr/kr/bbs/view.do?bbsId=B0000127&menuNo=205021&nttId=27364): 위 표에 출처로만 썼고 선별 목록에서는 뺐습니다. 2018년 Apache 기준 자료라 CRS v4와 nginx 구성에 맞지 않습니다.
- 해킹진단도구 활용 방안#5: 호스트 포렌식 위주라 WAF/IDS와 관련이 없습니다.
- 사이버 위협 동향 보고서(2026 상반기): 통계만 있고 시나리오가 없습니다.
- Security-Gym / K-Shield: 협약 기업 재직자 대상 과정이고 교재가 공개되지 않습니다.
- 2025 AI 해킹방어 대회(ACDC) 공고·결과: 주제가 AI 보안이라 웹과 WAF/IDS 범위 밖이고, 문제도 공개되지 않습니다.
- KISA 가이드라인 목록(시큐어코딩 등): 코드 개선 지침이라 공방 문제에 쓸 곳이 없습니다. Python 시큐어코딩 가이드는 board 원인 설명에 쓸 여지가 있으나 미확인입니다.
- Dreamhack 워게임·Enterprise: 약관 제9·10조가 복제·배포, AI 모델 개발용 수집, Write-up 공개를 금지합니다(https://dreamhack.io/services/tos).
- 금융보안원: 게시판 본문을 열지 못해 내용과 공개 범위를 확인하지 못했습니다.
- 국가사이버안보센터: 임시 페이지라 자료를 받을 수 없습니다.
- BoB: 문제나 교재가 공개되지 않습니다.
- Splunk BOTS v2·v3: 웹·IDS 비중이 v1보다 낮고 클라우드·APT 시나리오 위주입니다. v1으로 충분합니다.
- TryHackMe NSM 블로그, Snort Challenge 풀이(제3자): Snort 기준이고 공식 페이지로 확인하지 못했습니다.
- CyberDefenders, Blue Team Labs Online: "All rights reserved"이거나 조건 표기가 없고, WAF/IDS 룰 작성 실습도 없습니다.
- SANS NetWars, RangeForce/Cyberbit, Immersive Labs, Cloud Range: 비공개 상용 제품이라 채점 방식이 공개되지 않습니다.
- Locked Shields 공식 페이지, HTB Locked Shields 블로그: 채점 정보가 없습니다. 채점은 Pihelgas·Frontiers 논문으로 대신했습니다.
- iCTF 2021: 팀 간 tick 단위 배점이라 1대1 라운드의 objective 판정과 구조가 다릅니다.
- FAUST CTF(CTFtime): 규칙 페이지를 열지 못했습니다. ENOWARS로 대신했습니다.
- HTB Battlegrounds 블로그: 규칙이 없습니다. CAI 논문으로 대신했습니다.
- KYPO 프로젝트 사이트와 라이브러리 목록: 개발이 끝났고, 공개 훈련은 전부 1인 레드 게임입니다. 형식은 demo training으로 충분합니다.
- 적응형 학습 논문(arXiv 2307.05281): 난이도 단계 참고 외에 쓸 곳이 없고 단계 유형도 미확인입니다.
- go-ftw: 이미 자체 룰 테스트 게이트가 있습니다.
- PortSwigger Web Security Academy: 개인 용도로만 쓸 수 있고 수정·상업 이용이 금지됩니다. 랩도 심은 취약점 앱입니다.
- OWASP Juice Shop: 심은 취약점 앱이라 "현실적 원인" 원칙에 어긋납니다.
- Django 2025-11-05(CVE-2025-64459), 2024-08-06(CVE-2024-42005) 공지: board 코드가 해당 API(`_connector` kwargs 확장, JSONField `values()` 별칭)를 쓰지 않는 것으로 보여 이번 후보에서 뺐습니다. 코드 대조는 미확인입니다.
- ET Pro SID(2800000-2900000): 공개 룰이 아닙니다.
