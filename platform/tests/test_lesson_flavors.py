import pytest
from django.test import override_settings

import wargames
from api.models import Session
from fsl.settings import waf_layout
from range import declared

pytestmark = pytest.mark.django_db

LESSONS = [(wargame_id, lesson_id) for wargame_id in wargames.WARGAMES for lesson_id in [
    *wargames.taught_ids(wargame_id), *(one["id"] for one in wargames.stepped_scenarios(wargame_id))]]
FLAVORS = ["", "openstack"]

def layout(flavor):
    return waf_layout(declared.read(flavor=flavor))

def commands(wargame_id, lesson_id, flavor):
    taught = wargames.lesson(wargame_id, layout(flavor), lesson_id=lesson_id)
    return {step["id"]: step["command"] for step in taught["steps"] if step.get("command")}

def test_the_two_waf_layouts_differ_and_each_has_a_lesson_command_naming_its_own_file():
    assert layout("").rules != layout("openstack").rules, "the docker WAF container and the OpenStack WAF VM differ"
    for flavor in FLAVORS:
        assert any(layout(flavor).rules in command for wargame_id, lesson_id in LESSONS
                   for command in commands(wargame_id, lesson_id, flavor).values()), flavor

@pytest.mark.parametrize("flavor", FLAVORS)
def test_the_waf_commands_a_learner_types_name_the_flavor_s_file_and_reload_with_no_placeholder_left(flavor):
    waf = layout(flavor)
    typed = [command for wargame_id, lesson_id in LESSONS for command in commands(wargame_id, lesson_id, flavor).values()]
    edit = next(command for command in typed if "nano" in command)

    assert not [command for command in typed if "{" in command.replace("{target}", "")]
    assert edit == ("sudo " if flavor else "") + f"nano {waf.rules} && " + waf.reload.replace(" 2>&1", "")

@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("wargame_id, lesson_id", LESSONS)
def test_every_lesson_renders_its_steps_for_a_session_on_either_flavor(client, wargame_id, lesson_id, flavor):
    declared = wargames.lesson(wargame_id, lesson_id=lesson_id)["steps"]
    session = Session.objects.create(scenario=wargame_id, baseline={}, guidance=True, lesson=lesson_id,
                                     lesson_steps={lesson_id: {step["id"]: {"reached": "2026-10-13T09:00:00+00:00"} for step in declared}})

    with override_settings(FSL_WAF=layout(flavor)):
        shown = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]

    assert shown["id"] == lesson_id
    assert [step["id"] for step in shown["steps"]] == [step["id"] for step in wargames.lesson(wargame_id, lesson_id=lesson_id)["steps"]]
    assert all("accept" not in step["check"] for step in shown["steps"]), "no answer key leaves the server"
    assert {step["id"]: step["command"] for step in shown["steps"] if step.get("command")} == commands(
        wargame_id, lesson_id, flavor), "every reached step carries its command, rendered for the flavor"
