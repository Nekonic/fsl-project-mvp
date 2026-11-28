# Now

The handover to the next session, kept short. The build record, one line per
tree, and the backlog are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems in `docs/TROUBLESHOOTING.md`; the current design in
`docs/ARCHITECTURE.md`, the historical 2026-11-19 design in
`docs/specs/2026-11-19-side-split-design.md`; detail in `git log`.

Updated: 2026-11-28.

## What the cloud runs

`dev` on `cr-platform2`, since a replace on the afternoon of 2026-11-28
(UTC+9 15:49, exit 0, 16 min): times shown in UTC+9 on the console and in
Kibana, log lines and backup names in UTC+9, and English terms written in
English on the console (probes, range, slot, stack, signature). The pvp
time limit is 15 minutes: set on the VM through `CR_PVP_TIME_LIMIT_SECONDS=900`
in `/opt/cr/openstack.env`, and the code default on `dev` is 900 since,
not yet deployed. `main` holds the old product until gate 2.

## Checked live today

- After that replace, both pvp wargames passed every step from sign-in to
  sign-out (rounds 497 board, 498 corp; `~/.cache/fsl-work/pvp-check/`):
  on corp the attack takes the objective, IDS sid 9000201 alerts, the
  defender's WAF rule passes its test, goes live and the same attack gets
  403; on board the search SQLi is refused by CRS and then by the
  defender's rule. Times on screen read UTC+9; no Hangul spelling of an
  English term shows.
- The demo answer sheet (attack and defence per wargame, the rules used and
  the sqlmap commands from `cases/board.yaml`) is a private artifact.
- corp's committed probes for `corp-rogue-admin` still hold the old `-4`
  registration requests; the case itself sends `-5` since the fix. They are
  not recorded again yet.

## Open

- Start takes 25-40 s (posture 7.6 s, baseline 3.1 s measured, on a 2-vCPU
  platform VM); both consoles say so while it runs.
- The name `cr-platform`: Heat keeps the abandoned stack's record, so a
  replace under that name stops (`docs/OPENSTACK.md` §5.3); an admin removes
  it. The platform runs as `cr-platform2` meanwhile.
- Left from the sweep's testers: the site pane is blank for about 6 s on
  first open, the Kali MOTD prints twice, the debrief and the result page can
  disagree on pending for a few seconds, a staff problem edit's leave warning
  does not cover the back button, Kibana's own English UI.
- The launcher does not stop a bot's child process when its round ends (the
  platform marks the run ended; the child runs to `CR_BOT_RUN_SECONDS`).
- The kali change `deploy/roles/kali/operator-log.sh` waits for a kali bake; the
  slots run `cr-kali-bake4`'s command log.
- The attack bot meets 2 refusals a run on Sonnet and Opus 5.5 and goes on.
- Round 406's `ground_truth_unavailable` (2026-11-27) is not explained; a
  round that does not start now logs why.
- Whether a platform read under three rounds still runs past 5 s now that it
  runs off the request thread (`CR_READ_IN_BACKGROUND=1`) is not measured.
- The 2026-11-28 renames on `sweep-fix` (role files in `deploy/roles/`,
  `cases/`, `sites.conf`, `customers.py`, `web-proxy.py`, `board.rules`, the
  `refill` service, `defence/waf/terminal/`) are not deployed; the role files
  reach the VMs at the next bake of each role (DECISIONS 2026-11-28).
- The rest is in `docs/STATE.md` "Not live-verified" and "Open points".

## Next, in order

1. Record corp's probes again with the fixed `corp-rogue-admin` case
   (`bin/record-probes`) and commit them.
2. Deploy `dev` (`bin/cloud up --replace`).
3. External learners: the public-IP forwards (UDP 51820-51919, TCP 2222,
   the console) and `CR_VPN_HOST`.
4. Gate 2: a live review round with zero countable findings and a docs
   review, then the change and its evidence to the user.

Written for a session that reaches the cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet.
