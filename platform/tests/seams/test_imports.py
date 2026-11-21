import ast
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[2]
SKIPPED = ("tests", ".venv", "node_modules")
HTTP = ("*/views*.py", "*/serializers.py", "*/urls.py", "cr/urls.py", "cr/handler.py", "cr/schema.py", "cr/settings.py",
        "cr/strings.py", "cr/wsgi.py", "*/management/commands/*.py", "*/management/*.py", "manage.py",
        "*/apps.py", "*/migrations/*.py")
HTTP_LAYER = 10
COORDINATORS = ("training/round/lifecycle.py", "training/round/lease.py", "training/round/follow.py",
                "training/round/site.py", "training/round/retention.py", "training/traffic/customers.py",
                "training/content/probes.py")
LAYERS = (
    (HTTP_LAYER, HTTP),
    (0, ("domain/*",)),
    (1, ("cr/__init__.py", "cr/config.py", "cr/errors.py", "*/__init__.py", "sandbox/*", "telemetry/elastic.py",
         "training/attack/cases.py", "training/attack/tools.py", "scoring/loot.py", "scoring/effect.py",
         "testing/*")),
    (2, ("users/*",)),
    (3, ("training/models.py",)),
    (4, ("telemetry/*",)),
    (5, ("scoring/*",)),
    (8, COORDINATORS),
    (6, ("training/round/access.py", "training/content/catalog.py", "training/content/problems.py")),
    (7, ("training/attack/actions.py", "training/defence/*")),
)
FRAMEWORKS = ("django", "rest_framework", "drf_spectacular")
L1_THIRD_PARTY = ("requests", "yaml")


def modules() -> list[str]:
    return sorted(
        str(path.relative_to(PLATFORM)) for path in PLATFORM.rglob("*.py")
        if not set(path.relative_to(PLATFORM).parts) & set(SKIPPED)
    )


def layer_of(path: str) -> int | None:
    return next((layer for layer, patterns in LAYERS if any(fnmatch(path, pattern) for pattern in patterns)), None)


def placed(path: str) -> int:
    layer = layer_of(path)
    return 99 if layer is None else layer


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
    return [path for path in modules() if layer_of(path) == layer]


def test_every_module_under_platform_is_assigned_a_layer():
    unassigned = [path for path in modules() if layer_of(path) is None]

    assert unassigned == [], f"modules with no layer in the unit table: {unassigned}"


def test_the_seams_exist_where_the_design_puts_them():
    expected = ["cr/config.py", "cr/errors.py", "telemetry/elastic.py", "sandbox/suricata.py", "sandbox/crs.py",
                "sandbox/openstack.py", "sandbox/cloud_config.py", "sandbox/stack_plan.py", "sandbox/definitions.py",
                "sandbox/fabric.py", "sandbox/wiring.py", "sandbox/topology.py", "sandbox/pool.py",
                "sandbox/refill.py", "sandbox/reachability.py", "sandbox/runner.py", "sandbox/reach.py",
                "sandbox/edge.py", "sandbox/access.py", "sandbox/attacker.py", "sandbox/kibana.py",
                "sandbox/service.py", "training/attack/cases.py", "training/attack/tools.py", "scoring/loot.py",
                "scoring/effect.py"]

    assert [path for path in expected if layer_of(path) != 1 or not (PLATFORM / path).is_file()] == []
    assert (PLATFORM / "sandbox/declaration.yaml").is_file()
    assert not (PLATFORM / "__init__.py").exists(), "platform is a stdlib name and must not be a package"


@pytest.mark.parametrize("path", in_layer(0))
def test_rule_1_domain_imports_only_the_standard_library_and_domain(path):
    strays = [dotted for dotted in imports(path) if not standard(dotted) and dotted.split(".")[0] != "domain"]

    assert strays == [], f"{path} imports {strays}"


SETTINGS_READER = {"cr/config.py": {"django.conf", "django.conf.settings"}}


@pytest.mark.parametrize("path", in_layer(1))
def test_rule_2_a_seam_imports_no_framework_no_app_and_only_lower_or_seam_modules(path):
    named = [dotted for dotted in imports(path) if dotted not in SETTINGS_READER.get(path, set())]
    frameworks = [dotted for dotted in named if dotted.split(".")[0] in FRAMEWORKS]
    third_party = [dotted for dotted in named
                   if not standard(dotted) and not own(dotted) and dotted.split(".")[0] not in L1_THIRD_PARTY]
    above = [target for target in targets(path) if placed(target) > 1]

    assert frameworks == [], f"{path} imports a framework: {frameworks}"
    assert third_party == [], f"{path} imports {third_party}"
    assert above == [], f"{path} imports app modules: {above}"


def test_the_one_settings_reader_among_the_seams_is_the_config_that_builds_from_them():
    assert sorted(dotted for dotted in imports("cr/config.py") if dotted.split(".")[0] in FRAMEWORKS) == [
        "django.conf", "django.conf.settings"]


@pytest.mark.parametrize("path", [path for path in modules() if layer_of(path) != HTTP_LAYER])
def test_a_module_imports_only_its_own_layer_or_a_lower_one(path):
    above = sorted(target for target in targets(path) if placed(target) > layer_of(path))

    assert above == [], f"{path} (layer {layer_of(path)}) imports {above}"


SCORING_SURFACE = ("scoring/baseline.py", "scoring/losses.py", "scoring/score.py", "scoring/__init__.py")


@pytest.mark.parametrize("path", modules())
def test_rule_4_only_scoring_reads_the_target_s_ground_truth_and_others_import_only_its_surface(path):
    if path.startswith("scoring/"):
        return
    reached = ground_truth_reached_past_the_surface(targets(path))

    assert reached == [], f"{path} imports {reached}; other units go through {SCORING_SURFACE}"


def ground_truth_reached_past_the_surface(reached: set[str]) -> list[str]:
    return sorted(target for target in reached if target.startswith("scoring/") and target not in SCORING_SURFACE)


def test_the_checker_sees_a_reach_into_scoring_s_seams_or_models():
    reached = {"scoring/loot.py", "scoring/effect.py", "scoring/models.py", "scoring/score.py",
               "scoring/losses.py", "scoring/__init__.py", "telemetry/events.py"}

    assert ground_truth_reached_past_the_surface(reached) == ["scoring/effect.py", "scoring/loot.py",
                                                              "scoring/models.py"]


def test_the_checker_sees_a_framework_import_an_app_import_and_a_relative_import():
    named = imports_in("from django.conf import settings\nfrom training.attack import actions\nfrom . import loot\n"
                       "from ..sandbox import attacker\n", "scoring/sample.py")

    assert "django.conf" in named and "training.attack.actions" in named
    assert "scoring.loot" in named and "sandbox.attacker" in named
    assert resolved("sandbox.attacker") == "sandbox/attacker.py"
    assert resolved("sandbox.runner.Ran") == "sandbox/runner.py"


APPS = ("users", "telemetry", "training", "scoring")
TRAINING_PARTS = ("content", "round", "traffic", "attack", "defence")
SURFACES = {
    "users": {"users/accounts.py", "users/permissions.py", "users/seats.py"},
    "telemetry": {"telemetry/events.py", "telemetry/alerts.py", "telemetry/access.py"},
    "scoring": set(SCORING_SURFACE),
    "training/content": {"training/content/problems.py", "training/content/probes.py"},
    "training/round": {"training/round/lifecycle.py", "training/round/lease.py", "training/round/access.py"},
    "training/traffic": {"training/traffic/customers.py"},
    "training/attack": {"training/attack/actions.py"},
    "training/defence": {"training/defence/rules.py", "training/defence/terminal.py",
                         "training/defence/kibana_gate.py"},
}
SHARED_TO_VIEWS = {"cr/errors.py", "training/round/access.py", "users/permissions.py", "users/accounts.py"}
SERVER_LINES = {"training/defence/views_kibana.py": {"cr/strings.py"}}
STAFF_RANGE_VIEWS = {"training/round/views.py": {"sandbox/service.py"}}
VIEW_FRAMEWORKS = ("rest_framework", "drf_spectacular")


def app_of(path: str) -> str | None:
    head = path.split("/")[0]
    return head if head in APPS else None


def part_of(path: str) -> str | None:
    parts = path.split("/")
    if parts[0] == "training" and len(parts) > 2 and parts[1] in TRAINING_PARTS:
        return f"training/{parts[1]}"
    return app_of(path)


def package_marker(path: str) -> bool:
    return path.endswith("/__init__.py") and not (PLATFORM / path).read_text().strip()


def views_and_serializers() -> list[str]:
    return [path for path in modules()
            if app_of(path) and (fnmatch(path, "*/views*.py") or fnmatch(path, "*/serializers.py"))]


@pytest.mark.parametrize("path", [path for path in modules()
                                  if app_of(path) == "telemetry" and layer_of(path) != HTTP_LAYER])
def test_rule_8_telemetry_imports_no_other_unit_but_the_round_records_it_points_to(path):
    others = [target for target in targets(path)
              if app_of(target) not in (None, "telemetry") and target not in ("training/models.py",)
              and not package_marker(target)]

    assert others == [], f"{path} imports {others}; telemetry is a leaf"


@pytest.mark.parametrize("path", [path for path in modules()
                                  if app_of(path) == "users" and layer_of(path) != HTTP_LAYER])
def test_users_imports_no_other_unit(path):
    others = [target for target in targets(path) if app_of(target) not in (None, "users")]

    assert others == [], f"{path} imports {others}; users is a leaf"


@pytest.mark.parametrize("path", views_and_serializers())
def test_rule_10_views_and_serializers_import_only_their_part_drf_and_the_shared_few(path):
    part = part_of(path)
    own_part = {target for target in modules() if part_of(target) == part}
    allowed = (own_part | {"training/models.py", "telemetry/models.py", path} | SHARED_TO_VIEWS
               | SERVER_LINES.get(path, set()) | STAFF_RANGE_VIEWS.get(path, set()))
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
             for field in model._meta.get_fields()
             if field.is_relation and field.related_model and not field.auto_created
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


def test_the_layer_order_of_models_runs_from_django_auth_up_to_scoring():
    assert model_layer("auth") < model_layer("users") < model_layer("training") < model_layer("telemetry")
    assert model_layer("telemetry") < model_layer("scoring")


def test_the_checker_sees_an_upward_migration_dependency():
    class Upward:
        dependencies = [("scoring", "0001_initial"), ("telemetry", "0001_initial"), ("users", "0001_initial"),
                        ("__setting__", "AUTH_USER_MODEL")]

    assert upward_relations([], {("training", "0002_x"): Upward}, "auth") == ["training.0002_x -> scoring",
                                                                              "training.0002_x -> telemetry"]


def cross_part_strays(path: str) -> list[str]:
    part = part_of(path)
    strays = []
    for target in targets(path):
        other = part_of(target)
        if other in (None, part) or layer_of(target) == 1 or package_marker(target):
            continue
        if target in SURFACES.get(other, set()) or target in SHARED_TO_VIEWS:
            continue
        if part == "training" and target.startswith("training/"):
            continue
        if target.endswith("/models.py") and placed(target) < placed(path):
            continue
        strays.append(target)
    return strays


@pytest.mark.parametrize("path", [path for path in modules() if app_of(path)])
def test_rule_9_across_a_unit_or_training_part_only_its_surface_or_a_lower_model_is_imported(path):
    assert cross_part_strays(path) == [], f"{path} reaches into another unit"


def test_the_checker_sees_a_reach_into_another_unit_s_inner_module(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "targets", lambda path: {"users/blocks.py", "training/attack/cases.py",
                                                                        "users/accounts.py"})

    assert cross_part_strays("training/content/problems.py") == ["users/blocks.py"]


CONTENT_REACHES = {"cr/errors.py", "sandbox/crs.py", "training/attack/cases.py", "training/models.py"}


@pytest.mark.parametrize("path", [path for path in modules() if part_of(path) == "training/content"
                                  and layer_of(path) not in (HTTP_LAYER, 8)])
def test_content_reaches_only_the_domain_and_the_seams_its_owner_row_names(path):
    strays = [target for target in targets(path)
              if not target.startswith(("domain/", "training/content/")) and target not in CONTENT_REACHES
              and not package_marker(target)]

    assert strays == [], f"{path} imports {strays}"


SCORING_MAY_READ = {"training/models.py"}


def scoring_strays(reached: set[str]) -> list[str]:
    return sorted(target for target in reached
                  if target.startswith("training/") and target not in SCORING_MAY_READ and not package_marker(target))


@pytest.mark.parametrize("path", [path for path in modules() if app_of(path) == "scoring"])
def test_rule_5_scoring_imports_no_side_and_no_round_service(path):
    assert scoring_strays(targets(path)) == [], f"{path} reaches past the records it is handed"


def test_the_checker_sees_scoring_reaching_into_a_side_or_the_round_service():
    reached = {"training/attack/actions.py", "training/defence/rules.py", "training/round/lifecycle.py",
               "training/models.py", "sandbox/attacker.py", "telemetry/events.py"}

    assert scoring_strays(reached) == ["training/attack/actions.py", "training/defence/rules.py",
                                       "training/round/lifecycle.py"]


LOST_KIND = "objective.lost"
LOST_KIND_DECLARED = "telemetry/events.py"


def names_lost_kind(source: str, path: str) -> bool:
    return any(isinstance(node, ast.Constant) and node.value == LOST_KIND
               for node in ast.walk(ast.parse(source, filename=path)))


@pytest.mark.parametrize("path", [path for path in modules()
                                  if not path.startswith("scoring/") and path != LOST_KIND_DECLARED])
def test_rule_11_only_scoring_names_the_objective_lost_kind(path):
    assert not names_lost_kind((PLATFORM / path).read_text(), path), f"{path} names {LOST_KIND}"


def test_the_checker_sees_the_lost_kind_passed_to_append_directly_and_through_a_name():
    assert names_lost_kind('log.append(7, "objective.lost", {})\n', "training/attack/actions.py")
    assert names_lost_kind('KIND = "objective.lost"\nlog.append(7, KIND)\n', "training/attack/actions.py")
    assert not names_lost_kind('log.append(7, "objective.kept")\n', "training/attack/actions.py")
    assert names_lost_kind((PLATFORM / "scoring/losses.py").read_text(), "scoring/losses.py")


def test_rule_15_reads_forward_relations_and_skips_the_reverse_accessors_django_adds():
    from types import SimpleNamespace

    from training.models import Round

    def meta(label):
        return SimpleNamespace(_meta=SimpleNamespace(label=label, app_label=label.split(".")[0]))

    upward = SimpleNamespace(name="objective", is_relation=True, auto_created=False,
                             related_model=meta("scoring.Objective"))
    lease = SimpleNamespace(_meta=SimpleNamespace(label="training.Lease", app_label="training",
                                                  get_fields=lambda: [upward]))

    assert upward_relations([Round], {}, "auth") == []
    assert upward_relations([lease], {}, "auth") == ["training.Lease.objective -> scoring.Objective"]


def test_rule_15_sees_the_round_records_point_down_to_the_training_records_and_auth():
    from django.apps import apps

    relations = {(model._meta.label, field.related_model._meta.label)
                 for model in apps.get_models() if model._meta.app_label in ("training", "telemetry", "scoring")
                 for field in model._meta.get_fields()
                 if field.is_relation and field.many_to_one and field.related_model}

    assert {("training.Lease", "training.Wargame"), ("training.Round", "training.Problem"),
            ("training.Seat", "auth.User"), ("scoring.Objective", "training.Round"),
            ("telemetry.Detection", "training.Round")} <= relations


ATTACK_REACHES = {"cr/config.py", "cr/errors.py", "sandbox/edge.py", "sandbox/access.py", "sandbox/reach.py",
                  "sandbox/runner.py", "sandbox/attacker.py", "telemetry/elastic.py", "telemetry/events.py",
                  "telemetry/models.py", "scoring/losses.py", "training/models.py", "training/round/access.py"}


def attack_strays(path: str, reached: set[str]) -> list[str]:
    allowed = ATTACK_REACHES - ({"training/round/access.py"} if layer_of(path) != HTTP_LAYER else set())
    return sorted(target for target in reached
                  if not target.startswith(("domain/", "training/attack/")) and target not in allowed
                  and not package_marker(target))


@pytest.mark.parametrize("path", [path for path in modules() if part_of(path) == "training/attack"])
def test_attack_reaches_only_what_its_owner_row_names(path):
    assert attack_strays(path, targets(path)) == [], f"{path} reaches past the attack owner row"


def test_the_checker_sees_attack_reaching_past_its_owner_row():
    reached = {"sandbox/crs.py", "training/round/lifecycle.py", "training/round/access.py", "sandbox/edge.py",
               "domain/ledger.py"}

    assert attack_strays("training/attack/actions.py", reached) == ["sandbox/crs.py", "training/round/access.py",
                                                                    "training/round/lifecycle.py"]
    assert attack_strays("training/attack/views.py", reached) == ["sandbox/crs.py", "training/round/lifecycle.py"]


SIDES = ("training/attack", "training/defence")


def other_side_reached(path: str, reached: set[str]) -> list[str]:
    side = part_of(path)
    if side not in SIDES:
        return []
    other = next(name for name in SIDES if name != side)
    return sorted(target for target in reached if target.startswith(f"{other}/"))


@pytest.mark.parametrize("path", [path for path in modules() if part_of(path) in SIDES])
def test_rule_3_attack_and_defence_never_import_each_other(path):
    assert other_side_reached(path, targets(path)) == [], f"{path} reaches the other side"


def test_the_checker_sees_a_side_reaching_the_other():
    reached = {"training/attack/actions.py", "training/defence/disable.py", "sandbox/access.py",
               "scoring/losses.py"}

    assert other_side_reached("training/defence/rules.py", reached) == ["training/attack/actions.py"]
    assert other_side_reached("training/attack/actions.py", reached) == ["training/defence/disable.py"]
    assert other_side_reached("scoring/losses.py", reached) == []


SIDE_SERVICES = {"training/attack/actions.py", "training/defence/rules.py"}
MAY_JOIN_SIDES = set(COORDINATORS)


def joins_sides(path: str, reached: set[str]) -> bool:
    return path not in MAY_JOIN_SIDES and len(reached & SIDE_SERVICES) > 1


@pytest.mark.parametrize("path", modules())
def test_rule_7_only_the_round_coordinators_import_both_side_services(path):
    assert not joins_sides(path, targets(path)), f"{path} imports more than one side service"


def test_the_checker_sees_a_module_joining_the_sides():
    assert joins_sides("scoring/score.py", SIDE_SERVICES)
    assert joins_sides("training/round/views.py", SIDE_SERVICES)
    assert not joins_sides("training/round/lifecycle.py", SIDE_SERVICES)
    assert not joins_sides("training/content/problems.py", {"training/attack/actions.py"})


def test_the_round_coordinators_sit_in_layer_eight():
    assert {layer_of(path) for path in MAY_JOIN_SIDES} == {8}


REPO = PLATFORM.parent
CLIENT_TREES = ("bots", "test", "bin")
GENERATED = ("bots/client/",)
LOADERS = ("spec_from_file_location", "SourceFileLoader")
PLATFORM_FILE = re.compile(r"""["'](platform/[\w/.-]+\.py)["']""")
PLATFORM_LOADS_ALLOWED = {("bin/platform-rebuild", "platform/sandbox/cloud_config.py")}
TYPESCRIPT_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""")


def python_script(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    if path.suffix or not path.is_file():
        return False
    first = path.read_bytes().split(b"\n", 1)[0]
    return first.startswith(b"#!") and b"python" in first


def client_modules() -> list[str]:
    found = []
    for tree in CLIENT_TREES:
        for path in sorted((REPO / tree).rglob("*")):
            relative = str(path.relative_to(REPO))
            if relative.startswith(GENERATED) or "__pycache__" in path.parts:
                continue
            if python_script(path):
                found.append(relative)
    return found


def local_names(path: str) -> set[str]:
    folder = (REPO / path).parent
    return {entry.stem for entry in folder.iterdir() if entry.suffix == ".py" or (entry / "__init__.py").exists()}


def platform_reaches(source: str, path: str) -> list[str]:
    platform_names = first_party() - local_names(path) - {"bots"} - set(sys.stdlib_module_names)
    reached = [name for name in imports_in(source, path) if name.split(".")[0] in platform_names]
    calls = [ast.unparse(node) for node in ast.walk(ast.parse(source, filename=path)) if isinstance(node, ast.Call)]
    reached += [f"sys.path: {call}" for call in calls if call.startswith("sys.path.") and "platform" in call]
    if any(loader in call for call in calls for loader in LOADERS):
        reached += [f"loads {name}" for name in PLATFORM_FILE.findall(source)
                    if (path, name) not in PLATFORM_LOADS_ALLOWED]
    return reached


@pytest.mark.parametrize("path", client_modules())
def test_rule_12_bots_test_and_bin_never_import_the_platform(path):
    assert platform_reaches((REPO / path).read_text(), path) == []


def test_rule_12_the_front_end_never_imports_the_platform():
    front = REPO / "front" / "src"
    sources = sorted(front.rglob("*.ts*")) if front.is_dir() else []
    reaching = [(str(path.relative_to(REPO)), named) for path in sources
                for named in TYPESCRIPT_IMPORT.findall(path.read_text()) if "platform/" in named]

    assert reaching == []


def test_rule_12_the_one_platform_file_bin_loads_by_path_is_still_loaded_there():
    assert [(script, loaded) for script, loaded in PLATFORM_LOADS_ALLOWED
            if loaded not in (REPO / script).read_text() or not (REPO / loaded).is_file()] == []


def test_rule_12_scans_the_scripts_and_the_test_helpers():
    scanned = set(client_modules())

    assert {"bin/prune", "bin/acceptance", "test/conftest.py", "bots/signin.py"} <= scanned
    assert not [path for path in scanned if path.startswith(GENERATED)]


def test_the_checker_sees_an_import_a_path_insert_and_a_file_load_of_the_platform():
    source = ("import sys\nfrom training.round import lifecycle\nimport range\n"
              "sys.path.insert(0, str(ROOT / 'platform'))\n"
              "LOADER = ROOT / 'platform/sandbox/openstack.py'\n"
              "spec = importlib.util.spec_from_file_location('x', LOADER)\n")

    reached = platform_reaches(source, "test/sample.py")

    assert "training.round.lifecycle" in reached
    assert not [name for name in reached if name.startswith("range")], "test/ has its own range.py"
    assert any(name.startswith("sys.path") for name in reached)
    assert "loads platform/sandbox/openstack.py" in reached
