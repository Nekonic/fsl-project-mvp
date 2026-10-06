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
    assert all(argv[:3] == ["env", "MYSQL_PWD=wordpress", "mysql"] for argv in run.calls)
    assert not any(part.startswith("-p") for argv in run.calls for part in argv[:-1])
    assert all(argv[-1].lstrip().upper().startswith("SELECT") for argv in run.calls)


def test_snapshot_refuses_when_the_container_exits_nonzero():
    def run(argv, stdin=None, timeout=60.0):
        return Ran(exit_code=1, output="ERROR 2002 (HY000): Can't connect")

    with pytest.raises(effect.StateUnavailable):
        effect.snapshot(run)


def test_snapshot_refuses_when_the_range_is_down():
    def run(argv, stdin=None, timeout=60.0):
        raise RangeUnavailable("fsl-wg-corp-db never reported")

    with pytest.raises(effect.StateUnavailable):
        effect.snapshot(run)


WARNING = "mysql: [Warning] Using a password on the command line interface can be insecure.\n"


def test_snapshot_ignores_the_clients_own_warning_line():
    run = _runner({
        "wp_usermeta": WARNING + "1\n",
        "wp_options": WARNING + "users_can_register\t0\ndefault_role\tsubscriber\n",
        "wp_posts": WARNING + "2\n3\n",
    })

    assert effect.snapshot(run) == {
        "admins": [1],
        "options": {"users_can_register": "0", "default_role": "subscriber"},
        "posts": [2, 3],
    }


@pytest.mark.parametrize("needle", ["wp_usermeta", "wp_posts", "wp_options"])
def test_snapshot_fails_loud_on_any_other_stray_line(needle):
    answers = {
        "wp_usermeta": "1\n",
        "wp_options": "users_can_register\t0\ndefault_role\tsubscriber\n",
        "wp_posts": "2\n3\n",
    }
    answers[needle] = "some unexpected diagnostic\n" + answers[needle]

    with pytest.raises(effect.StateUnavailable):
        effect.snapshot(_runner(answers))
