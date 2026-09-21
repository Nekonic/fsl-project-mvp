from __future__ import annotations

import subprocess

from range.ports import Ran, RangeUnavailable

class Docker:
    def __init__(self, hosts: dict[str, str], project: str = "fsl"):
        self.hosts = hosts
        self.project = project

    def runner(self, role: str, segment_id: str = ""):
        host = self.hosts.get(role)
        if host is None:
            raise RangeUnavailable(f"no host fills the role {role!r}")

        def run(argv: list[str], stdin: str | None = None, timeout: float = 60.0) -> Ran:
            command = ["docker", "exec"]
            if stdin is not None:
                command.append("-i")
            command += [host, *argv]
            try:
                done = subprocess.run(
                    command, input=stdin, capture_output=True,
                    text=True, timeout=timeout,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RangeUnavailable(f"could not reach {host}: {exc}") from exc
            output = (done.stdout or "") + (done.stderr or "")
            if done.returncode == 126 or "No such container" in output:
                raise RangeUnavailable(f"{host} is not running")
            return Ran(exit_code=done.returncode, output=output)

        return run
