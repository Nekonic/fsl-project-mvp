import subprocess

import pytest
from django.test import override_settings

import wargames
from api.models import Session
from fsl.settings import waf_layout
from range import declared

pytestmark = pytest.mark.django_db

LESSONS = [(wargame_id, taught["id"]) for wargame_id in wargames.WARGAMES for taught in wargames.lessons(wargame_id)]
FLAVORS = ["", "openstack"]

def layout(flavor):
    return waf_layout(declared.read(flavor=flavor))

def commands(wargame_id, lesson_id, flavor):
    taught = wargames.lesson(wargame_id, layout(flavor), lesson_id=lesson_id)
    return {step["id"]: step["command"] for step in taught["steps"] if step.get("command")}

def test_every_declared_lesson_is_covered_on_two_waf_layouts():
    assert ("board", "waf-exclusion") in LESSONS
    assert layout("").rules != layout("openstack").rules, "the docker WAF container and the OpenStack WAF VM differ"

@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("wargame_id, lesson_id", LESSONS)
def test_every_lesson_command_names_the_flavor_s_own_waf_file_and_reload(wargame_id, lesson_id, flavor):
    waf = layout(flavor)

    for step_id, command in commands(wargame_id, lesson_id, flavor).items():
        assert "{waf_rules}" not in command and "{waf_reload}" not in command, step_id
        if "REQUEST-900" in command or "$F" in command:
            assert f"F={waf.rules}" in command and waf.reload in command, (flavor, step_id)

@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("wargame_id, lesson_id", LESSONS)
def test_every_lesson_exclusion_command_runs_against_the_flavor_s_file(tmp_path, wargame_id, lesson_id, flavor):
    waf = layout(flavor)
    rules = tmp_path / "exclusions.conf"
    rules.write_text("")
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, body in {"nginx": "exit 0", "sudo": 'exec "$@"', "systemctl": "exit 0"}.items():
        (tools / name).write_text(f"#!/bin/sh\n{body}\n")
        (tools / name).chmod(0o755)

    for step_id, command in commands(wargame_id, lesson_id, flavor).items():
        done = subprocess.run(["sh", "-c", command.replace(waf.rules, str(rules))], capture_output=True, text=True,
                              env={"PATH": f"{tools}:/usr/bin:/bin"})
        assert done.returncode == 0 and "reloaded" in done.stdout, (flavor, step_id, done.stdout, done.stderr)
        assert "ctl:ruleRemove" in rules.read_text()

@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("wargame_id, lesson_id", LESSONS)
def test_every_lesson_renders_its_steps_for_a_session_on_either_flavor(client, wargame_id, lesson_id, flavor):
    declared = wargames.lesson(wargame_id, lesson_id=lesson_id)["steps"]
    session = Session.objects.create(scenario=wargame_id, baseline={}, guidance=True, lesson=lesson_id,
                                     lesson_steps={step["id"]: {"reached": "2026-10-13T09:00:00+00:00"} for step in declared})

    with override_settings(FSL_WAF=layout(flavor)):
        shown = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]

    assert shown["id"] == lesson_id
    assert [step["id"] for step in shown["steps"]] == [step["id"] for step in wargames.lesson(wargame_id, lesson_id=lesson_id)["steps"]]
    assert all("accept" not in step["check"] for step in shown["steps"]), "no answer key leaves the server"
    assert {step["id"]: step["command"] for step in shown["steps"] if step.get("command")} == commands(
        wargame_id, lesson_id, flavor), "every reached step carries its command, rendered for the flavor"
