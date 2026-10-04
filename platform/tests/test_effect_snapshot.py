import pytest

from api import effect
from range.ports import Ran, RangeUnavailable

pytestmark = pytest.mark.reads_target_state


def _runner(answers):
    calls = []

    def run(argv, stdin=None, timeout=60.0):
        calls.append(argv)
        for needle, output in answers.items():
            if needle in argv[-1]:
                return Ran(exit_code=0, output=output)
        return Ran(exit_code=0, output="")

    run.calls = calls
    return run


def test_snapshot_reads_admins_options_and_published_posts_from_the_container():
    run = _runner({
        "wp_usermeta": "1\n",
        "wp_options": "users_can_register\t0\ndefault_role\tsubscriber\n",
        "wp_posts": "2\n3\n",
    })

    assert effect.snapshot(run) == {
        "admins": [1],
        "options": {"users_can_register": "0", "default_role": "subscriber"},
        "posts": [2, 3],
    }
    assert all(argv[0] == "mysql" for argv in run.calls)
    assert all(argv[-1].lstrip().upper().startswith("SELECT") for argv in run.calls)


def test_snapshot_refuses_when_the_container_exits_nonzero():
    def run(argv, stdin=None, timeout=60.0):
        return Ran(exit_code=1, output="ERROR 2002 (HY000): Can't connect")

    with pytest.raises(effect.StateUnavailable):
        effect.snapshot(run)


def test_snapshot_refuses_when_the_range_is_down():
    def run(argv, stdin=None, timeout=60.0):
        raise RangeUnavailable("fsl-corp-db never reported")

    with pytest.raises(effect.StateUnavailable):
        effect.snapshot(run)
