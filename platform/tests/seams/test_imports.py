import ast
import sys
from fnmatch import fnmatch
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[2]
SKIPPED = ("tests", ".venv", "node_modules")
HTTP = ("*/views*.py", "*/serializers.py", "*/urls.py", "cr/urls.py", "cr/handler.py", "cr/settings.py",
        "cr/strings.py", "cr/wsgi.py", "*/management/commands/*.py", "*/management/*.py", "manage.py",
        "*/apps.py", "*/migrations/*.py")
LAYERS = (
    (8, HTTP),
    (0, ("domain/*",)),
    (1, ("cr/__init__.py", "cr/config.py", "cr/errors.py", "ingest/*", "rules/*", "range/*", "attack/__init__.py",
         "attack/box.py", "attack/jump.py", "attack/firing.py", "attack/tools.py", "defence/__init__.py",
         "defence/kibana.py", "referee/__init__.py", "referee/loot.py", "referee/effect.py", "testing/*")),
    (2, ("accounts/*", "events/*", "content/*")),
    (3, ("match/__init__.py", "match/models.py", "match/auth.py")),
    (4, ("referee/models.py", "referee/service.py")),
    (5, ("attack/models.py", "attack/service.py", "defence/*")),
    (6, ("match/service.py", "match/follow.py", "match/customers.py", "match/site.py", "match/retention.py",
         "match/probes.py")),
    (7, ("lessons/*",)),
)
FRAMEWORKS = ("django", "rest_framework", "drf_spectacular")
L1_THIRD_PARTY = ("requests", "yaml")
LEGACY = ("disable.py",)


def modules() -> list[str]:
    return sorted(
        str(path.relative_to(PLATFORM)) for path in PLATFORM.rglob("*.py")
        if not set(path.relative_to(PLATFORM).parts) & set(SKIPPED)
    )


def legacy(path: str) -> bool:
    return path.split("/")[0] in LEGACY


def layer_of(path: str) -> int | None:
    return next((layer for layer, patterns in LAYERS if any(fnmatch(path, pattern) for pattern in patterns)), None)


def first_party() -> set[str]:
    return {path.name.removesuffix(".py") for path in PLATFORM.iterdir()
            if (path.is_dir() and path.name not in SKIPPED and any(path.rglob("*.py"))) or path.suffix == ".py"}


def resolved(dotted: str) -> str | None:
    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        base = PLATFORM.joinpath(*parts[:end])
        if base.with_suffix(".py").is_file():
            return str(base.with_suffix(".py").relative_to(PLATFORM))
        if (base / "__init__.py").is_file():
            return str((base / "__init__.py").relative_to(PLATFORM))
    return None


def absolute(path: str, level: int, module: str | None) -> str:
    package = path.removesuffix(".py").split("/")[:-1]
    base = package[:len(package) - (level - 1)] if level > 1 else package
    return ".".join([*base, *([module] if module else [])])


def imports_in(source: str, path: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source, filename=path)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module if node.level == 0 else absolute(path, node.level, node.module)
            if module:
                found.append(module)
            found += [f"{module}.{alias.name}" if module else alias.name for alias in node.names if alias.name != "*"]
    return found


def imports(path: str) -> list[str]:
    return imports_in((PLATFORM / path).read_text(), path)


def own(dotted: str) -> bool:
    return dotted.split(".")[0] in first_party()


def standard(dotted: str) -> bool:
    return dotted.split(".")[0] in sys.stdlib_module_names or dotted == "__future__"


def targets(path: str) -> set[str]:
    return {target for dotted in imports(path) if own(dotted) and (target := resolved(dotted))}


def in_layer(layer: int) -> list[str]:
    return [path for path in modules() if not legacy(path) and layer_of(path) == layer]


def test_every_module_under_platform_is_assigned_a_layer():
    unassigned = [path for path in modules() if not legacy(path) and layer_of(path) is None]

    assert unassigned == [], f"modules with no layer in the side-split table: {unassigned}"


def test_the_legacy_list_names_only_what_still_stands():
    gone = [name for name in LEGACY if not (PLATFORM / name).exists()]

    assert gone == [], f"remove these from LEGACY, they are deleted: {gone}"


def test_the_seams_exist_where_the_design_puts_them():
    expected = ["cr/config.py", "cr/errors.py", "ingest/elastic.py", "rules/suricata.py", "rules/crs.py",
                "range/openstack.py", "range/cloud_config.py", "range/stack_plan.py", "range/declaration.py",
                "range/networks.py", "range/wiring.py", "range/topology.py", "range/pool.py", "range/refill.py",
                "range/reachability.py", "range/runner.py", "range/substrate.py", "range/edge.py",
                "attack/box.py", "attack/jump.py", "attack/firing.py", "attack/tools.py", "defence/kibana.py",
                "referee/loot.py", "referee/effect.py"]

    assert [path for path in expected if layer_of(path) != 1 or not (PLATFORM / path).is_file()] == []
    assert (PLATFORM / "range/declaration.yaml").is_file()
    assert not (PLATFORM / "__init__.py").exists(), "platform is a stdlib name and must not be a package"


@pytest.mark.parametrize("path", in_layer(0) or ["domain/__init__.py"])
def test_rule_1_domain_imports_only_the_standard_library_and_domain(path):
    if not (PLATFORM / path).is_file():
        pytest.skip("domain/ is built in another step")
    strays = [dotted for dotted in imports(path) if not standard(dotted) and dotted.split(".")[0] != "domain"]

    assert strays == [], f"{path} imports {strays}"


@pytest.mark.parametrize("path", in_layer(1))
def test_rule_2_a_seam_imports_no_framework_no_app_and_only_lower_or_seam_modules(path):
    named = imports(path)
    frameworks = [dotted for dotted in named if dotted.split(".")[0] in FRAMEWORKS]
    third_party = [dotted for dotted in named
                   if not standard(dotted) and not own(dotted) and dotted.split(".")[0] not in L1_THIRD_PARTY]
    above = [target for target in targets(path) if legacy(target) or (layer_of(target) or 9) > 1]

    assert frameworks == [], f"{path} imports a framework: {frameworks}"
    assert third_party == [], f"{path} imports {third_party}"
    assert above == [], f"{path} imports app or legacy modules: {above}"


@pytest.mark.parametrize("path", [path for path in modules() if not legacy(path)])
def test_rule_4_only_referee_reads_the_target_s_ground_truth(path):
    if path.startswith("referee/"):
        return
    reached = {target for target in targets(path) if target in ("referee/loot.py", "referee/effect.py")}

    assert reached == set(), f"{path} imports {sorted(reached)}; other apps go through referee.service"


def test_the_checker_sees_a_framework_import_an_app_import_and_a_relative_import():
    named = imports_in("from django.conf import settings\nfrom attack import service\nfrom . import loot\n"
                       "from ..attack import box\n", "referee/sample.py")

    assert "django.conf" in named and "attack.service" in named
    assert "referee.loot" in named and "attack.box" in named
    assert resolved("attack.box") == "attack/box.py"
    assert resolved("range.runner.Ran") == "range/runner.py"


APPS = ("accounts", "events", "content", "match", "referee", "attack", "defence", "lessons")
SERVICE_OF = {"events": "events/log.py"}
SHARED_TO_VIEWS = {"cr/errors.py", "match/auth.py", "accounts/service.py"}
VIEW_FRAMEWORKS = ("rest_framework", "drf_spectacular")


def app_of(path: str) -> str | None:
    head = path.split("/")[0]
    return head if head in APPS else None


def package_marker(path: str) -> bool:
    return path.endswith("/__init__.py") and not (PLATFORM / path).read_text().strip()


def views_and_serializers() -> list[str]:
    return [path for path in modules()
            if app_of(path) and (fnmatch(path, "*/views*.py") or fnmatch(path, "*/serializers.py"))]


@pytest.mark.parametrize("path", [path for path in modules() if app_of(path) == "events" and layer_of(path) != 8])
def test_rule_8_events_imports_no_other_app(path):
    others = [target for target in targets(path) if app_of(target) not in (None, "events")]

    assert others == [], f"{path} imports {others}; events is a leaf"


@pytest.mark.parametrize("path", views_and_serializers())
def test_rule_10_views_and_serializers_import_only_their_service_models_drf_and_the_shared_few(path):
    app = path.split("/")[0]
    allowed = {SERVICE_OF.get(app, f"{app}/service.py"), f"{app}/models.py", f"{app}/serializers.py",
               f"{app}/__init__.py", path} | SHARED_TO_VIEWS
    strays = sorted(target for target in targets(path) if target not in allowed and not package_marker(target))
    third_party = [dotted for dotted in imports(path)
                   if not standard(dotted) and not own(dotted) and dotted.split(".")[0] not in VIEW_FRAMEWORKS]

    assert strays == [], f"{path} imports {strays}"
    assert third_party == [], f"{path} imports {third_party}"


def model_layer(label: str) -> int:
    return layer_of(f"{label}/models.py") if label in APPS else -1


def upward_relations(models, migrations, user_app: str) -> list[str]:
    found = [f"{model._meta.label}.{field.name} -> {field.related_model._meta.label}"
             for model in models if model._meta.app_label in APPS
             for field in model._meta.get_fields() if field.is_relation and field.related_model
             and field.related_model._meta.app_label != model._meta.app_label
             and model_layer(field.related_model._meta.app_label) >= model_layer(model._meta.app_label)]
    for (app, name), migration in migrations.items():
        for dependency in migration.dependencies if app in APPS else ():
            target = user_app if dependency[0] == "__setting__" else dependency[0]
            if target != app and model_layer(target) >= model_layer(app):
                found.append(f"{app}.{name} -> {dependency[0]}")
    return found


def test_rule_15_model_relations_and_migrations_point_to_the_same_app_or_lower():
    from django.apps import apps
    from django.conf import settings
    from django.db.migrations.loader import MigrationLoader

    migrations = MigrationLoader(None, ignore_no_migrations=True).disk_migrations

    assert upward_relations(apps.get_models(), migrations, settings.AUTH_USER_MODEL.split(".")[0]) == []


def test_the_layer_order_of_models_runs_from_django_auth_up_to_lessons():
    assert model_layer("auth") < model_layer("accounts") < model_layer("match") < model_layer("referee")
    assert model_layer("referee") < model_layer("attack") < model_layer("lessons")
    assert model_layer("events") == model_layer("content") == model_layer("accounts")


def test_the_checker_sees_an_upward_migration_dependency():
    class Upward:
        dependencies = [("match", "0001_initial"), ("accounts", "0001_initial"), ("__setting__", "AUTH_USER_MODEL")]

    assert upward_relations([], {("events", "0002_x"): Upward}, "auth") == ["events.0002_x -> match",
                                                                            "events.0002_x -> accounts"]


def cross_app_strays(path: str) -> list[str]:
    app = app_of(path)
    strays = []
    for target in targets(path):
        other = app_of(target)
        if other in (None, app) or layer_of(target) == 1 or package_marker(target):
            continue
        if target == SERVICE_OF.get(other, f"{other}/service.py") or target in SHARED_TO_VIEWS:
            continue
        if target == f"{other}/models.py" and model_layer(other) < model_layer(app):
            continue
        strays.append(target)
    return strays


@pytest.mark.parametrize("path", [path for path in modules() if app_of(path)])
def test_rule_9_across_an_app_boundary_only_the_service_or_a_lower_model_is_imported(path):
    assert cross_app_strays(path) == [], f"{path} reaches into another app"


def test_the_checker_sees_a_reach_into_another_app_s_inner_module(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "targets", lambda path: {"accounts/signin.py", "attack/firing.py",
                                                                        "accounts/service.py"})

    assert cross_app_strays("content/service.py") == ["accounts/signin.py"]


CONTENT_REACHES = {"cr/errors.py", "rules/crs.py", "attack/firing.py"}


@pytest.mark.parametrize("path", [path for path in modules() if app_of(path) == "content" and layer_of(path) != 8])
def test_content_reaches_only_the_domain_and_the_seams_its_owner_row_names(path):
    strays = [target for target in targets(path)
              if not target.startswith(("domain/", "content/")) and target not in CONTENT_REACHES
              and not package_marker(target)]

    assert strays == [], f"{path} imports {strays}"
