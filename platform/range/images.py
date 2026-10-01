from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from range.ports import RangeUnavailable

BUILDER = "fsl-build-"
BUILDS = "fsl_image"
BUNDLE = "fsl_bundle"
READY = "fsl-image-ready"
FAILED = "fsl-image-failed"
TASK = "OS-EXT-STS:task_state"
WORKDIR = "/var/lib/fsl"
USER_DATA_LIMIT = 65535
SKIPPED = {"__pycache__"}
FAILED_IMAGE = {"killed", "deleted", "pending_delete", "deactivated"}
TAIL_LINES = 20

@dataclass(frozen=True)
class Bundle:
    host: str
    setup: str
    digest: str
    archive: bytes

@dataclass(frozen=True)
class Image:
    host: str
    bundle: str
    state: str
    image: str = ""
    builder: str = ""
    detail: str = ""

@dataclass(frozen=True)
class Plan:
    images: tuple[Image, ...] = ()
    leftovers: tuple[tuple[str, str, str], ...] = ()

    @property
    def clean(self) -> bool:
        return not self.leftovers and all(
            found.state == "ready" and not found.builder for found in self.images
        )

def _members(source: Path, paths) -> list[str]:
    found = []
    for path in paths:
        root = source / path
        if not root.exists():
            raise RangeUnavailable(
                f"{path} is declared for an image and {source} has no such file"
            )
        walked = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        found += [
            p.relative_to(source).as_posix() for p in walked
            if not SKIPPED & set(p.relative_to(source).parts)
        ]
    return sorted(dict.fromkeys(found))

def bundle(source: Path, host: str, setup: str, files) -> Bundle:
    source = Path(source)
    digest = hashlib.sha256()
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz", compresslevel=9) as archive:
        for member in _members(source, [setup, *files]):
            content = (source / member).read_bytes()
            info = tarfile.TarInfo(member)
            info.size = len(content)
            info.mode = (source / member).stat().st_mode & 0o777
            digest.update(f"{member}\0{info.mode:o}\0".encode() + content + b"\0")
            archive.addfile(info, io.BytesIO(content))
    return Bundle(host=host, setup=setup, digest=digest.hexdigest()[:16], archive=packed.getvalue())

def user_data(bundle: Bundle) -> str:
    unpacked = f"{WORKDIR}/image"
    script = (
        f"if mkdir -p {unpacked} && tar -xzf {WORKDIR}/image.tar.gz -C {unpacked} "
        f"&& sh {unpacked}/{bundle.setup}; "
        f"then said='{READY} {bundle.digest}'; else said='{FAILED} {bundle.digest}'; fi; "
        f"rm -rf {WORKDIR}; echo \"$said\" > /dev/console"
    )
    document = {
        "write_files": [{
            "path": f"{WORKDIR}/image.tar.gz",
            "encoding": "b64",
            "content": base64.b64encode(bundle.archive).decode(),
        }],
        "runcmd": [["sh", "-c", script]],
    }
    encoded = base64.b64encode(
        ("#cloud-config\n" + yaml.safe_dump(document)).encode()
    ).decode()
    if len(encoded) > USER_DATA_LIMIT:
        raise RangeUnavailable(
            f"the image {bundle.host} needs {len(encoded)} bytes of user data and "
            f"Nova takes at most {USER_DATA_LIMIT}; declare fewer files for it"
        )
    return encoded

def _tail(output: str) -> str:
    return "\n".join(output.strip().splitlines()[-TAIL_LINES:])

def _state(bundle: Bundle, current: dict | None, builder: dict | None, consoles: dict) -> Image:
    known = {
        "host": bundle.host, "bundle": bundle.digest,
        "image": current["id"] if current else "",
        "builder": builder["id"] if builder else "",
    }
    if current:
        status = current.get("status")
        if status == "active":
            return Image(**known, state="ready")
        if status in FAILED_IMAGE:
            return Image(**known, state="failed", detail=f"the snapshot is {status}")
        return Image(**known, state="saving")
    if builder is None:
        return Image(**known, state="missing")
    status = builder.get("status")
    if builder.get(TASK):
        return Image(**known, state="building", detail=f"Nova is {builder[TASK]} it")
    if status == "SHUTOFF":
        return Image(**known, state="stopped")
    said = consoles.get(builder["id"], "")
    if f"{FAILED} {bundle.digest}" in said:
        return Image(**known, state="failed", detail=_tail(said))
    if f"{READY} {bundle.digest}" in said:
        return Image(**known, state="built")
    if status == "ERROR":
        return Image(**known, state="failed",
                     detail=(builder.get("fault") or {}).get("message", "") or "Nova put it in ERROR")
    return Image(**known, state="building", detail=f"since {builder.get('created', '')}")

def _prebuilt_state(host: str, image_name: str, images: list) -> Image:
    current = next(
        (i for i in images if i.get("name") == image_name and i.get("status") == "active"),
        None,
    )
    if current:
        return Image(host=host, bundle="", state="ready", image=current["id"])
    return Image(
        host=host, bundle="", state="missing",
        detail=f"the cloud holds no active image {image_name!r}; build it by hand "
               f"(README) - this platform cannot build it from a script",
    )

def plan(bundles, images: list, builders: list, consoles: dict, prebuilt=()) -> Plan:
    found, leftovers = [], []
    found += [_prebuilt_state(host, image_name, images) for host, image_name in prebuilt]
    hosts = {b.host for b in bundles}
    for made in bundles:
        named = [i for i in images if i.get("name") == made.host]
        current = next(
            iter(sorted(
                (i for i in named if i.get(BUNDLE) == made.digest),
                key=lambda i: i.get("status") != "active",
            )),
            None,
        )
        leftovers += [
            ("image", i["id"], f"image {made.host} was built from bundle {i.get(BUNDLE) or 'none'}")
            for i in named if i is not current
        ]
        own = [s for s in builders if (s.get("metadata") or {}).get(BUILDS) == made.host]
        builder = next((s for s in own if s["metadata"].get(BUNDLE) == made.digest), None)
        leftovers += [
            ("server", s["id"], f"builder {s['name']} ran bundle {s['metadata'].get(BUNDLE) or 'none'}")
            for s in own if s is not builder
        ]
        found.append(_state(made, current, builder, consoles))
    leftovers += [
        ("server", s["id"], f"builder {s['name']} builds {s['metadata'][BUILDS]}, which nothing declares")
        for s in builders if (s.get("metadata") or {}).get(BUILDS) not in hosts
    ]
    return Plan(images=tuple(found), leftovers=tuple(leftovers))

def removable(plan: Plan) -> list[tuple[str, str]]:
    failed = [
        ("server", found.builder) if found.builder else ("image", found.image)
        for found in plan.images if found.state == "failed"
    ]
    return [(kind, ident) for kind, ident, _ in plan.leftovers] + failed
