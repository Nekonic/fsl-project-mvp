import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

PAGES = ["/", "/detections/", "/rules/"]


@pytest.fixture
def client():
    return Client()


@pytest.mark.parametrize("path", PAGES)
def test_page_renders(client, path):
    response = client.get(path)

    assert response.status_code == 200


@pytest.mark.parametrize("path", PAGES)
def test_page_fetches_its_data_from_the_api(client, path):
    # 구조 원칙: 화면 동작은 전부 REST API 로 먼저 존재한다. 템플릿이
    # 서버 렌더한 데이터를 들고 있으면 에이전트가 사람 자리에 들어올 수 없다.
    body = client.get(path).content.decode()

    assert "/api/" in body
    assert "fetch(" in body


def test_score_page_does_not_query_the_database(client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        client.get("/")

    assert len(queries) == 0
