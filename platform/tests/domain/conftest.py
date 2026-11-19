import sys

import pytest

FORBIDDEN = ("django", "rest_framework")


def loaded_frameworks() -> list[str]:
    return sorted(name for name in sys.modules if name.split(".")[0] in FORBIDDEN)


assert not loaded_frameworks(), "the domain tests must run without Django loaded"


def pytest_sessionfinish(session, exitstatus):
    if loaded_frameworks():
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        raise AssertionError(f"the domain tests loaded {loaded_frameworks()[:5]}")
