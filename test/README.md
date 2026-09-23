# test

Checks the acceptance criteria from section 9 of the design document. Speaks
only HTTP and never imports platform code: it sees the system from outside.

The stack must be running.

```bash
DOCKER_GID=$(bin/docker-gid) docker compose up -d --build
python -m pytest test/ -v
```

If the stack is down these fail rather than skip. An acceptance check that
quietly skips reads as "passed".

One test changes the Suricata rules. It puts them back when it is done.
