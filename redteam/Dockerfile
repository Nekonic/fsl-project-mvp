# 레드팀 외부 도구. 케이스가 `tool:` 로 선언하면 하니스가 이 이미지를
# fsl 네트워크에 붙여 일회성으로 돌린다.
#
# 배포된 sqlmap 이미지를 쓰지 않고 직접 만든다 — 대부분 amd64 전용이라
# arm64 호스트에서 서지 않는다.
FROM python:3.13-slim

RUN pip install --no-cache-dir sqlmap==1.9.2

ENTRYPOINT []
CMD ["sqlmap", "--version"]
