import pytest
from django.test import override_settings

import wargames
from api.models import Session
from fsl.settings import waf_layout
from range import declared

pytestmark = pytest.mark.django_db

LESSONS = [(wargame_id, lesson_id) for wargame_id in wargames.WARGAMES for lesson_id in [
    *wargames.taught_ids(wargame_id), *(one["id"] for one in wargames.stepped_scenarios(wargame_id))]]
def layout():
    return waf_layout(declared.read())

def commands(wargame_id, lesson_id):
    taught = wargames.lesson(wargame_id, layout(), lesson_id=lesson_id)
    return {step["id"]: step["command"] for step in taught["steps"] if step.get("command")}

def test_a_lesson_command_names_the_waf_vm_s_own_file():
    assert any(layout().rules in command for wargame_id, lesson_id in LESSONS
               for command in commands(wargame_id, lesson_id).values())

def test_the_waf_commands_a_learner_types_name_the_waf_s_file_and_reload_with_no_placeholder_left():
    waf = layout()
    typed = [command for wargame_id, lesson_id in LESSONS for command in commands(wargame_id, lesson_id).values()]
    edit = next(command for command in typed if "nano" in command)

    assert not [command for command in typed if "{" in command.replace("{target}", "")]
    assert edit == f"sudo nano {waf.rules} && " + waf.reload.replace(" 2>&1", "")

@pytest.mark.parametrize("wargame_id, lesson_id", LESSONS)
def test_every_lesson_renders_its_steps_for_a_session(client, wargame_id, lesson_id):
    declared = wargames.lesson(wargame_id, lesson_id=lesson_id)["steps"]
    session = Session.objects.create(scenario=wargame_id, baseline={}, guidance=True, lesson=lesson_id,
                                     lesson_steps={lesson_id: {step["id"]: {"reached": "2026-10-13T09:00:00+00:00"} for step in declared}})

    with override_settings(FSL_WAF=layout()):
        shown = client.get(f"/api/sessions/{session.pk}/").json()["lesson"]

    assert shown["id"] == lesson_id
    assert [step["id"] for step in shown["steps"]] == [step["id"] for step in wargames.lesson(wargame_id, lesson_id=lesson_id)["steps"]]
    assert all("accept" not in step["check"] for step in shown["steps"]), "no answer key leaves the server"
    assert {step["id"]: step["command"] for step in shown["steps"] if step.get("command")} == commands(
        wargame_id, lesson_id), "every reached step carries its command, rendered for the WAF VM"
