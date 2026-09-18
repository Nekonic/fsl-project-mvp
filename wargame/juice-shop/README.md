# juice-shop

방어 대상 앱. 이미지를 그대로 쓰므로 여기에는 설정 파일이 없다.

교체 가능한 슬롯이다. Juice Shop 은 자체 챌린지 API 가 공격 성공 판정을
대신해 주고 DB 가 필요 없어 골랐다. 셸 획득이 안 되므로 나중에 PHP 게시판이나
Spring 앱이 옆에 붙는다. 붙일 때는 `wargame/<앱이름>/` 을 만들고
`compose.yaml` 의 `waf` 서비스 `BACKEND` 를 그 앱으로 돌린다.
