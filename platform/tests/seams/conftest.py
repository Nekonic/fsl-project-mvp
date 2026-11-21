import pytest


@pytest.fixture(autouse=True)
def nothing_remembered_between_tests():
    from sandbox import openstack

    openstack.forget()
    yield
    openstack.forget()
