from __future__ import annotations

import os
import subprocess

from range.ports import RangeUnavailable


def refused(what: str) -> RangeUnavailable:
    return RangeUnavailable(
        f"this unit test supplied no range, so {what} was refused. Production "
        f"code sees the same state when the substrate is down; a test that "
        f"needs a range must stub api.views.substrate"
    )

class StandIn:
    max_sessions = 2

    def __init__(self, declared=None, **options):
        self.declared = declared

    def describe(self):
        raise refused("reading the range's shape")

    def segments(self):
        raise refused("reading the range's segments")

    def interfaces(self, hosts=None):
        raise refused("reading the range's interfaces")

    def address(self, role: str) -> str:
        return ""

    def runner(self, role: str, segment_id: str = ""):
        def run(argv, stdin=None, timeout=60.0):
            raise refused(f"running {' '.join(argv[:3])} on {role}")

        return run

    def launcher(self, segment_id: str):
        def launch(image, argv, timeout=600.0):
            raise refused(f"starting {image} on {segment_id}")

        return launch

    def users_box(self, segment_ids, image):
        raise refused(f"starting the users' box on {', '.join(segment_ids)}")

def refusing_docker(real=subprocess.Popen):
    def popen(args, *rest, **options):
        first = args[0] if isinstance(args, (list, tuple)) and args else ""
        if os.path.basename(str(first)) == "docker":
            raise refused(" ".join(str(part) for part in args[:3]))
        return real(args, *rest, **options)

    return popen
