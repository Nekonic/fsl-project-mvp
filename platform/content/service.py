from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import F, ProtectedError

from content import catalog
from content.models import Posture, ProbeSet, Problem, RoundSetup, Step, Wargame
from cr import errors
from domain.problems import validate_problem
from rules.crs import TuningRefused, checked

DOCUMENT_KEYS = ("problem", "steps", "round", "start_posture")
PROBLEM_DEFAULTS = {"summary": "", "body": "", "published": False}
DEFAULT_BENIGN_EVERY_S = 60
POSTURE_KEYS = ("name", "suricata_rules", "crs_tuning")


def source() -> Path:
    return Path(settings.CR_SOURCE)


def read_catalog() -> dict[str, catalog.Wargame]:
    return {wargame.id: wargame for wargame in catalog.wargames(source())}


def sync_wargames() -> dict[str, catalog.Wargame]:
    declared = read_catalog()
    for wargame in declared.values():
        Wargame.objects.update_or_create(id=wargame.id, defaults={
            "title": wargame.title, "image": wargame.image, "public_url": wargame.public_url,
            "hosts": list(wargame.hosts), "objective_model": wargame.objective_model,
            "case_file": wargame.case_file, "default_traffic": wargame.default_traffic,
        })
        if wargame.probes:
            ProbeSet.objects.update_or_create(
                wargame_id=wargame.id, image_digest=wargame.probes.image_digest,
                defaults={"recorded_at": datetime.fromisoformat(wargame.probes.recorded_at),
                          "cases": wargame.probes.cases})
    return declared


def wargames():
    sync_wargames()
    return Wargame.objects.all()


def published():
    return Problem.objects.filter(published=True).prefetch_related("steps")


def published_problem(problem_id: int) -> Problem:
    found = published().filter(pk=problem_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_problem")
    return found


def problems():
    return Problem.objects.all()


def problem(problem_id: int) -> Problem:
    found = Problem.objects.filter(pk=problem_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_problem")
    return found


def posture_document(posture: Posture | None) -> dict | None:
    if posture is None:
        return None
    return {"name": posture.name, "suricata_rules": posture.suricata_rules, "crs_tuning": posture.crs_tuning}


def step_document(step: Step) -> dict:
    return {"order": step.order, "body": step.body, "opens": step.opens, "check": step.check_spec,
            "answer": step.answer, "hints": step.hints}


def setup_document(setup: RoundSetup | None) -> dict | None:
    if setup is None:
        return None
    return {"matchups": setup.matchups, "posture": setup.posture.name if setup.posture else None,
            "probe_cases": setup.probe_cases, "objectives": setup.objectives, "hp": setup.hp,
            "traffic": setup.traffic, "benign_every_s": setup.benign_every_s, "time_limit_s": setup.time_limit_s}


def setup_of(found: Problem) -> RoundSetup | None:
    return RoundSetup.objects.filter(problem=found).select_related("posture").first()


def exported(found: Problem) -> dict:
    return {
        "problem": {"kind": found.kind, "wargame": found.wargame_id, "side": found.side, "title": found.title,
                    "summary": found.summary, "body": found.body, "published": found.published},
        "steps": [step_document(step) for step in found.steps.order_by("order")],
        "round": setup_document(setup_of(found)),
        "start_posture": posture_document(found.start_posture),
    }


def document(found: Problem) -> dict:
    shown = exported(found)
    shown["problem"] = {"id": found.pk, **shown["problem"], "revision": found.revision,
                        "author": found.author.username if found.author else None, "updated": found.updated}
    return shown


def export(problem_id: int) -> dict:
    return exported(problem(problem_id))


def shown_errors(found) -> tuple[errors.FieldError, ...]:
    return tuple(errors.FieldError(path=error.path, code=error.code,
                                   params={name: list(value) if isinstance(value, tuple) else value
                                           for name, value in error.params}) for error in found)


def validate(doc: object) -> list[errors.FieldError]:
    if not isinstance(doc, Mapping):
        return [errors.FieldError(path="", code="not_an_object")]
    declared = sync_wargames()
    found = list(shown_errors(validate_problem(doc, {key: value.for_validation() for key, value in declared.items()})))
    found += [errors.FieldError(path=key, code="unknown_field") for key in doc if key not in DOCUMENT_KEYS]
    problem_part = doc.get("problem")
    wargame = declared.get(problem_part.get("wargame")) if isinstance(problem_part, Mapping) else None
    found += start_posture_errors(doc.get("start_posture"))
    found += setup_errors(doc.get("round"), doc.get("start_posture"), wargame)
    return found


def start_posture_errors(given: object) -> list[errors.FieldError]:
    if given is None:
        return []
    if not isinstance(given, Mapping):
        return [errors.FieldError(path="start_posture", code="not_an_object")]
    return [errors.FieldError(path=f"start_posture.{key}", code="unknown_field") for key in given
            if key not in POSTURE_KEYS] + posture_errors(given, "start_posture.")


def posture_errors(given: Mapping, at: str) -> list[errors.FieldError]:
    found = []
    if not isinstance(given.get("name"), str) or not given["name"].strip():
        found.append(errors.FieldError(path=f"{at}name", code="required"))
    if not isinstance(given.get("suricata_rules", ""), str):
        found.append(errors.FieldError(path=f"{at}suricata_rules", code="not_a_text"))
    try:
        checked(given.get("crs_tuning"))
    except TuningRefused:
        found.append(errors.FieldError(path=f"{at}crs_tuning", code="crs_refused"))
    return found


def setup_errors(setup: object, start: object, wargame: catalog.Wargame | None) -> list[errors.FieldError]:
    if not isinstance(setup, Mapping) or wargame is None:
        return []
    found = []
    named = setup.get("posture")
    inline = start.get("name") if isinstance(start, Mapping) else None
    if named is not None and named != inline and not Posture.objects.filter(wargame_id=wargame.id,
                                                                            name=named).exists():
        found.append(errors.FieldError(path="round.posture", code="unknown_posture"))
    traffic = setup.get("traffic")
    if traffic is not None and traffic not in wargame.traffic_profiles:
        found.append(errors.FieldError(path="round.traffic", code="unknown_profile"))
    return found


def validated(doc: object) -> None:
    found = validate(doc)
    if found:
        raise errors.Invalid(errors=tuple(found))


def revision_given(base_revision: object) -> int:
    if type(base_revision) is not int:
        raise errors.Invalid(code="required", path="base_revision")
    return base_revision


def save_document(doc: Mapping, base_revision: object = None, *, problem_id: int | None = None, author=None) -> Problem:
    doc = {key: value for key, value in doc.items() if key != "base_revision"} if isinstance(doc, Mapping) else doc
    expected = revision_given(base_revision) if problem_id is not None else None
    validated(doc)
    with transaction.atomic():
        if problem_id is None:
            found = Problem(author=author)
        else:
            moved = Problem.objects.filter(pk=problem_id, revision=expected).update(revision=F("revision") + 1)
            found = Problem.objects.filter(pk=problem_id).first()
            if found is None:
                raise errors.NotFound(code="unknown_problem")
            if not moved:
                raise errors.Conflict(code="stale_revision", params={"current_revision": found.revision})
        written(found, doc)
    return found


def import_document(doc: Mapping, author=None) -> Problem:
    return save_document(doc, author=author)


def written(found: Problem, doc: Mapping) -> None:
    given = {**PROBLEM_DEFAULTS, **doc["problem"]}
    found.kind, found.side, found.title = given["kind"], given["side"], given["title"]
    found.summary, found.body, found.published = given["summary"], given["body"], given["published"]
    found.wargame_id = given["wargame"]
    found.start_posture = kept_posture(given["wargame"], doc.get("start_posture"))
    found.save()
    found.steps.all().delete()
    Step.objects.bulk_create(Step(problem=found, order=step["order"], body=step["body"],
                                  opens=step.get("opens", "none"), check_spec=step["check"], answer=step.get("answer"),
                                  hints=step.get("hints", [])) for step in doc.get("steps", []))
    setup = doc.get("round")
    if setup is None:
        RoundSetup.objects.filter(problem=found).delete()
        return
    named = setup.get("posture")
    RoundSetup.objects.update_or_create(problem=found, defaults={
        "matchups": setup["matchups"],
        "posture": Posture.objects.get(wargame_id=found.wargame_id, name=named) if named else None,
        "probe_cases": setup.get("probe_cases", []), "objectives": setup.get("objectives", []),
        "hp": setup["hp"], "traffic": setup.get("traffic"),
        "benign_every_s": setup.get("benign_every_s", DEFAULT_BENIGN_EVERY_S),
        "time_limit_s": setup.get("time_limit_s"),
    })


def kept_posture(wargame_id: str, given: Mapping | None) -> Posture | None:
    if given is None:
        return None
    kept, _ = Posture.objects.update_or_create(wargame_id=wargame_id, name=given["name"], defaults={
        "suricata_rules": given.get("suricata_rules", ""), "crs_tuning": checked(given["crs_tuning"])})
    return kept


def delete_problem(problem_id: int) -> None:
    found = problem(problem_id)
    try:
        with transaction.atomic():
            found.delete()
    except ProtectedError as refused:
        raise errors.Conflict(code="in_use") from refused


def snapshot(found: Problem) -> dict[str, Any]:
    declared = catalog.read(source(), found.wargame_id)
    setup = setup_of(found)
    chosen = set(setup.objectives) if setup and setup.objectives else None
    frozen = {
        "problem": {"id": found.pk, "kind": found.kind, "side": found.side, "title": found.title,
                    "summary": found.summary, "body": found.body, "revision": found.revision},
        "wargame": {"id": declared.id, "title": declared.title, "image": declared.image,
                    "public_url": declared.public_url, "hosts": list(declared.hosts),
                    "objective_model": declared.objective_model, "case_file": declared.case_file,
                    "secret": declared.secret},
        "steps": [step_document(step) for step in found.steps.order_by("order")],
        "start_posture": posture_document(found.start_posture),
        "objectives": [{"key": tier.key, "name": tier.name, "category": tier.category, "difficulty": tier.difficulty,
                        "rule": tier.rule}
                       for tier in declared.objectives if chosen is None or tier.key in chosen],
        "round": None,
    }
    if setup is not None:
        frozen["round"] = {
            **setup_document(setup),
            "posture": posture_document(setup.posture or found.start_posture),
            "traffic": setup.traffic or declared.default_traffic,
            "benign_cases": list(declared.benign_cases),
        }
    return json.loads(json.dumps(frozen))


def postures():
    return Posture.objects.all()


def posture(posture_id: int) -> Posture:
    found = Posture.objects.filter(pk=posture_id).first()
    if found is None:
        raise errors.NotFound(code="unknown_posture")
    return found


def save_posture(given: object, posture_id: int | None = None) -> Posture:
    if not isinstance(given, Mapping):
        raise errors.Invalid(code="not_an_object")
    declared = sync_wargames()
    found = [errors.FieldError(path=key, code="unknown_field") for key in given
             if key not in (*POSTURE_KEYS, "wargame")]
    if given.get("wargame") not in declared:
        found.append(errors.FieldError(path="wargame", code="unknown_wargame"))
    found += posture_errors(given, "")
    if not found and Posture.objects.filter(wargame_id=given["wargame"], name=given["name"]).exclude(
            pk=posture_id).exists():
        found.append(errors.FieldError(path="name", code="name_taken"))
    if found:
        raise errors.Invalid(errors=tuple(found))
    kept = Posture() if posture_id is None else posture(posture_id)
    kept.wargame_id, kept.name = given["wargame"], given["name"]
    kept.suricata_rules, kept.crs_tuning = given.get("suricata_rules", ""), checked(given["crs_tuning"])
    kept.save()
    return kept
