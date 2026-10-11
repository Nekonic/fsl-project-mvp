# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-11. Written for a session that has the cloud
(master@192.168.0.100, Keystone http://192.168.0.110:5000) and the Internet.

## Where things stand

- Branch `claude/status-check-and-tasks-c83b9e`: every commit since
  `origin/dev` (870b15f) is local and not pushed. Push is gate 2.
- Read first, before planning: the spec
  `docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`
  and the living-doc artifact 37HeLkkLEFQgVWbwLuXH7S (confirmed items are
  final; one recorded deviation: `mgmt` stays shared).
- Live-verified, substrate docker: the MVP acceptance on `fsl-acceptance`
  (192.168.0.220), 146 passed, 0 failed (2026-10-10); the seven-step WAF
  lesson walked to VERIFY PASS (sessions 204, 205); the console redesign and
  site browser (session 202 onward).
- Built, never run on OpenStack: prebuilt images from GHCR,
  `bin/platform-rebuild`, `bin/cloud up|down`, `cloud.yaml`, the OPNsense edge
  and its image builder (the builder serves its disk; the platform checks the
  SHA256 and uploads it), Kali on Ubuntu, the review fixes
  (`docs/DECISIONS.md`, the last two 2026-10-11 entries). The build-script
  tests (`test_opnsense_image.py`) check strings and their order, not
  behaviour, until a live run.
- 192.168.0.210 still runs origin/dev (870b15f), substrate openstack, pfSense.

## Next session, in order

1. **Push (gate 2).** Show the user what changed since 870b15f (table or
   diagram) and ask. On a yes: `git push origin HEAD:dev` (fast-forward
   only). Check: `git log --oneline -1 origin/dev` is this branch's HEAD.
2. **Images workflow.** `gh run list --workflow images.yml --branch dev -L 1`,
   then `gh run watch <id>`. Check: success, six images tagged with the
   pushed commit.
3. **GHCR packages public (the user, once, irreversible).** github.com →
   the user's profile → Packages → each of `fsl-platform`, `fsl-board`,
   `fsl-corp`, `fsl-corp-db`, `fsl-kali`, `fsl-proxy` → Package settings →
   Danger Zone → Change visibility → Public. GitHub does not let a public
   package go private again, so ask first. Check: `bin/platform-rebuild`'s
   anonymous HEAD (run by step 7) passes.
4. **Base image.** `openstack image list --name ubuntu-24.04`; if absent,
   `docs/OPENSTACK.md` §3.6 (download, `sha256sum --ignore-missing -c
   SHA256SUMS`, `openstack image create ... ubuntu-24.04`). Check: exactly one
   active image of that name.
5. **cloud.yaml.** `cp deploy/openstack/cloud.example.yaml
   deploy/openstack/cloud.yaml` (git ignores it). Known values: keystone
   `http://192.168.0.110:5000`, project and user `fsl-range`, external
   network `provider`, MTU 1450. The password lives in
   `/root/fsl-range.password` on master@192.168.0.100: copy it with
   `umask 077` to the file `identity.password_file` names, never print it.
   Check every flavor it names exists (`openstack flavor list`;
   `compute.flavors.edge` is required, 3 GB RAM or more). Check:
   `.venv/bin/python -c "import sys; sys.path.insert(0, 'platform'); from range import cloud; cloud.read()"`
   raises nothing. The `fsl-range` core quota is 20 of 20 used.
6. **Clean up (ask the user first; irreversible).** Delete the obsolete VMs
   `fsl-kiosk`, `fsl-wiki`, `fsl-juice-shop`; `fsl-acceptance` (.220) and the
   flavor `m1.platform8` go only at step 9. Check: `openstack quota show
   --usage fsl-range` leaves cores for the platform, builders and slot.
7. **`.venv/bin/python bin/cloud up`.** Then check live, each against its
   claim in `docs/OPENSTACK.md`:
   - the importer's console strings and `vtbd1` under QEMU; TCG build time;
   - the `.sig` verifies over the unpacked image; the mirror paths and both
     SHA256 values for 26.7;
   - `fsl-serve` still serves after cloud-init ends and the platform pulls
     it (port 8080 on the platform network); the uploaded image is active;
   - Kali on Ubuntu installs every tool, especially mitmproxy, nikto, ffuf,
     gobuster, whatweb, dirb;
   - Suricata loads the `conf.d` include and `fsl.rules`, and both survive a
     reboot and an OPNsense update; the `suricatasc` path and socket the
     declaration names;
   - the edge is back within 900 s; the WAN pass rule is in pf;
   - `bin/cloud down` then leaves no stack, builder or range network.
8. **Acceptance.** On the platform VM (`ssh ubuntu@<address>`, `cd /opt/fsl`)
   run `bin/verify` (substrate openstack; the single-slot 409 with the
   session fixtures is a known cause, `docs/STATE.md` backlog 0). The docker
   gate on the pushed commit: `bin/verify` on .220 as on 2026-10-10.
9. **Only then** remove `fsl-acceptance` (.220) and `m1.platform8`, with the
   user's yes.

## Decisions waiting for the user

- The push (step 1) and the GHCR visibility (step 3).
- Test audit: 223 tests the 2026-10-10 audit would remove, which lowers the
  tests floor on purpose (`docs/STATE.md` backlog 0).
- Rename `/api/rules/suppressions/` (it disables rules; Suricata's
  "suppression" hides alerts only).
- Review of the seven-step lesson text.
- Publishing the OPNsense image: BSD-2 allows it; the trademark policy allows
  "based on OPNsense"; a derived name needs project@opnsense.org's permission.

## Known open

The checklist under backlog 0 in `docs/STATE.md`.
