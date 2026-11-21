import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
from django.apps import apps
from django.db import connection

BACKUP = Path(__file__).resolve().parents[3] / "bin" / "backup"
ROUND_RECORDS = ("training.Lease", "training.Round", "training.Seat", "training.Action", "telemetry.Detection",
                 "scoring.Objective", "telemetry.Event")


def listed_tables() -> list[str]:
    loader = SourceFileLoader("backup", str(BACKUP))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("backup", loader))
    loader.exec_module(module)
    return [table for _, table in module.TABLES]


@pytest.mark.django_db
def test_every_table_bin_backup_counts_is_a_table_of_the_store():
    present = set(connection.introspection.table_names())

    assert [table for table in listed_tables() if table not in present] == []


def test_bin_backup_counts_the_round_records():
    counted = set(listed_tables())

    assert [label for label in ROUND_RECORDS if apps.get_model(label)._meta.db_table not in counted] == []
