from __future__ import annotations

import base64
import hashlib
import io
import re
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

SERVED = "/var/lib/fsl-serve"
DISK = "disk.qcow2"
SERVE_PORT = 8080
SERVED_SHA = re.compile(r"sha256=([0-9a-f]{64})")

@dataclass(frozen=True)
class Bundle:
    host: str
    setup: str
    digest: str
    archive: bytes
    image: str = ""
    uploads: bool = False

    @property
    def name(self) -> str:
        return self.image or self.host

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

def bundle(source: Path, host: str, setup: str, files, generated: dict[str, bytes] | None = None,
           image: str = "", uploads: bool = False) -> Bundle:
    source = Path(source)
    digest = hashlib.sha256()
    packed = io.BytesIO()
    contents = {
        member: ((source / member).read_bytes(), (source / member).stat().st_mode & 0o777)
        for member in _members(source, [setup, *files])
    }
    clashing = sorted(set(contents) & set(generated or {}))
    if clashing:
        raise RangeUnavailable(f"{', '.join(clashing)} would be both a repo file and a generated one")
    contents.update({member: (content, 0o644) for member, content in (generated or {}).items()})
    with tarfile.open(fileobj=packed, mode="w:gz", compresslevel=9) as archive:
        for member in sorted(contents):
            content, mode = contents[member]
            info = tarfile.TarInfo(member)
            info.size = len(content)
            info.mode = mode
            digest.update(f"{member}\0{info.mode:o}\0".encode() + content + b"\0")
            archive.addfile(info, io.BytesIO(content))
    return Bundle(host=host, setup=setup, digest=digest.hexdigest()[:16], archive=packed.getvalue(),
                  image=image, uploads=uploads)

def _serving(bundle: Bundle) -> str:
    if not bundle.uploads:
        return f"said='{READY} {bundle.digest}'"
    return (
        f"sha=$(sha256sum {SERVED}/{DISK} | cut -c1-64) && "
        f"systemd-run --unit=fsl-serve /usr/bin/python3 -m http.server {SERVE_PORT} "
        f"--directory {SERVED} && said=\"{READY} {bundle.digest} sha256=$sha\""
    )


def user_data(bundle: Bundle) -> str:
    unpacked = f"{WORKDIR}/image"
    script = (
        f"if mkdir -p {unpacked} && tar -xzf {WORKDIR}/image.tar.gz -C {unpacked} "
        f"&& sh {unpacked}/{bundle.setup} && {_serving(bundle)}; "
        f"then :; else said='{FAILED} {bundle.digest}'; fi; "
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

def record(bundle: Bundle, properties: dict) -> dict:
    return {"name": bundle.name, "disk_format": "qcow2", "container_format": "bare",
            "visibility": "private", BUNDLE: bundle.digest, **properties}

def served_sha256(said: str, digest: str) -> str:
    line = next((entry for entry in said.splitlines() if f"{READY} {digest}" in entry), "")
    found = SERVED_SHA.search(line)
    return found.group(1) if found else ""

def _from_builder(bundle: Bundle, known: dict, builder: dict | None, consoles: dict) -> Image:
    if builder is None:
        if known["image"]:
            return Image(**known, state="failed", detail="a Glance record no builder fills")
        return Image(**known, state="missing")
    status = builder.get("status")
    if builder.get(TASK):
        return Image(**known, state="building", detail=f"Nova is {builder[TASK]} it")
    said = consoles.get(builder["id"], "")
    if f"{FAILED} {bundle.digest}" in said:
        return Image(**known, state="failed", detail=_tail(said))
    if status == "SHUTOFF":
        if bundle.uploads:
            return Image(**known, state="failed", detail="the builder stopped, so it serves no disk")
        return Image(**known, state="stopped")
    if f"{READY} {bundle.digest}" in said:
        return Image(**known, state="built")
    if status == "ERROR":
        return Image(**known, state="failed",
                     detail=(builder.get("fault") or {}).get("message", "") or "Nova put it in ERROR")
    return Image(**known, state="building", detail=f"since {builder.get('created', '')}")

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
        if not (bundle.uploads and status == "queued"):
            return Image(**known, state="saving")
    return _from_builder(bundle, known, builder, consoles)

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

def _retired(bundles, images: list, families) -> list[tuple[str, str, str]]:
    current = {made.name for made in bundles}
    return [
        ("image", i["id"], f"image {i['name']} is of a release the settings no longer name")
        for i in images
        if i.get(BUNDLE) and i.get("name") not in current
        and any(str(i.get("name", "")).startswith(family) for family in families)
    ]

def plan(bundles, images: list, builders: list, consoles: dict, prebuilt=(), families=(),
         in_use=frozenset()) -> Plan:
    found, leftovers = [], list(_retired(bundles, images, families))
    found += [_prebuilt_state(host, image_name, images) for host, image_name in prebuilt]
    hosts = {b.host for b in bundles}
    for made in bundles:
        named = [i for i in images if i.get("name") == made.name]
        current = next(
            iter(sorted(
                (i for i in named if i.get(BUNDLE) == made.digest),
                key=lambda i: i.get("status") != "active",
            )),
            None,
        )
        leftovers += [
            ("image", i["id"], f"image {made.name} was built from bundle {i.get(BUNDLE) or 'none'}")
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
    kept = [entry for entry in leftovers if not (entry[0] == "image" and entry[1] in in_use)]
    return Plan(images=tuple(found), leftovers=tuple(kept))

def removable(plan: Plan) -> list[tuple[str, str]]:
    failed = [
        ("server", found.builder) if found.builder else ("image", found.image)
        for found in plan.images if found.state == "failed"
    ]
    return [(kind, ident) for kind, ident, _ in plan.leftovers] + failed
