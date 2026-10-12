# Now

The handover to the next session, kept short. The product backlog and the
finished record are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
detail in `git log`. Numbers are in `metrics.json` (`bin/measure`).

Updated: 2026-10-11. Written for a session that has the cloud
(master@192.168.0.100, Keystone http://192.168.0.110:5000) and the Internet.

## Where things stand

- `dev` = e5c92c7 (pushed, images green, GHCR public). This branch adds the
  fixes the first live OpenStack run forced (`git log e5c92c7..`); not pushed.
- Read first, before planning: the spec
  `docs/superpowers/specs/2026-10-08-composable-isolated-learning-mvp-design.md`
  and the living-doc artifact 37HeLkkLEFQgVWbwLuXH7S.
- The cloud was cleaned and rebuilt from scratch with `bin/cloud up`: one
  hand-uploaded image (`ubuntu-24.04`), every golden image and the OPNsense
  26.7 edge built on the cloud. Results: `docs/OPENSTACK.md` status table
  and §7.
- Platform VM 192.168.0.210 (reserved floating IP), substrate openstack,
  READY; `/opt/fsl` is a `dev` clone overlaid with this branch's files.
- Acceptance: substrate docker 146 passed / 0 failed on that VM; substrate
  openstack 50 passed / 6 failed / 4 errors (the rest is backlog 0).

## Waiting for the user

1. Gate 2: push this branch to `dev` (fast-forward).
2. Release the leftover floating IP 192.168.0.220 in `fsl-range`.
3. Test audit: remove the 223 tests the 2026-10-10 audit lists (lowers the
   tests floor on purpose).
4. Rename `/api/rules/suppressions/` (it disables rules; Suricata's
   "suppression" hides alerts only).
5. Review of the seven-step lesson text.
6. Publishing the OPNsense image: BSD-2 allows it; a derived name needs
   project@opnsense.org's permission.

## Next, in order

1. After the push: the images workflow on the new `dev`, then
   `bin/platform-rebuild` on 192.168.0.210 so `/opt/fsl` is a clean clone;
   check the store and range key survive (never checked live).
2. `bin/cloud down` then `up` keeps the store (restore `down`'s backup).
3. WAF tuning on OpenStack (`rules/crs.py` per-host CRS path and reload).
4. The compose-only tests on the OpenStack range.
5. Acceptance run time (2,900 s): measure, then parallel sessions on
   docker, polling instead of fixed waits, edge config without a reboot.
6. Smaller: `down` leaves `fsl-build`; OPNsense-update survival unverified.
