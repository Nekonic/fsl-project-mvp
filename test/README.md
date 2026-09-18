# test

설계 문서 9장의 완료 기준을 검증한다. HTTP 만 쓰고 platform 내부를
임포트하지 않는다 — 밖에서 본 동작만 본다.

스택이 떠 있어야 한다.

```bash
docker compose up -d --build
python -m pytest test/ -v
```

스택이 떠 있지 않으면 skip 하지 않고 실패한다. 완료 기준 검증이
조용히 skip 되면 통과로 오독되기 때문이다.

Suricata 룰을 바꾸는 테스트가 있다. 끝나면 원래 룰로 되돌린다.
