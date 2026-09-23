import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("method, path, body", [
    ("get", "/api/rules/", None),
    ("post", "/api/rules/validate/", {"content": "alert http any any -> any any (sid:9000001;)"}),
    ("post", "/api/rules/apply/", {"content": "alert http any any -> any any (sid:9000001;)"}),
    ("post", "/api/rules/suppressions/", {"sid": 9000001}),
    ("post", "/api/attacker/label/", {"case_id": "sqli-login-bypass"}),
])
def test_a_range_that_cannot_answer_is_503_with_its_reason(client, method, path, body):
    if method == "get":
        response = client.get(path)
    else:
        response = client.post_json(path, body)

    assert response.status_code == 503, (
        f"{path} answered {response.status_code}. Before the runners told a "
        f"daemon error from a failed command, this endpoint handed docker's "
        f"error text back as if it were the rule file; now the error is "
        f"honest, and without a handler it is a bare 500"
    )
    assert "supplied no range" in response.json()["detail"]
