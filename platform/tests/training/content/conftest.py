import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
RECORDED = ("board-sqli-search", "board-sqli-login-bypass")
DIGEST = "sha256:placeholder"


def copied_source(into: Path) -> Path:
    for folder in sorted((REPO / "wargames").iterdir()):
        if (folder / "wargame.yaml").is_file():
            (into / "wargames" / folder.name).mkdir(parents=True)
            for name in ("wargame.yaml", "topology.yaml", "objectives.yaml", "traffic.yaml"):
                if (folder / name).is_file():
                    shutil.copy(folder / name, into / "wargames" / folder.name / name)
    shutil.copytree(REPO / "redteam" / "cases", into / "redteam" / "cases")
    return into


def recorded(source: Path, wargame: str, cases: tuple[str, ...], digest: str = DIGEST) -> None:
    probes = source / "wargames" / wargame / "probes"
    probes.mkdir(exist_ok=True)
    (probes / "manifest.json").write_text(json.dumps({
        "image_digest": digest, "recorded_at": "2026-11-20T00:00:00+00:00",
        "cases": {case: {"marker": case} for case in cases}}))


@pytest.fixture
def source(tmp_path, settings):
    made = copied_source(tmp_path / "source")
    recorded(made, "board", RECORDED)
    settings.CR_SOURCE = made
    return made
