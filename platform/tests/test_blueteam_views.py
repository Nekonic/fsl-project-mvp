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
    # Structural rule: everything the UI does exists as a REST API first. A
    # template carrying server-rendered data would block an agent from taking over.
    body = client.get(path).content.decode()

    assert "/api/" in body
    assert "fetch(" in body


def test_score_page_does_not_query_the_database(client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        client.get("/")

    assert len(queries) == 0
