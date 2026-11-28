# Now

The handover to the next session, kept short. The build record, one line per
tree, and the backlog are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems in `docs/TROUBLESHOOTING.md`; the current design in
`docs/ARCHITECTURE.md`, the historical 2026-11-19 design in
`docs/specs/2026-11-19-side-split-design.md`; detail in `git log`.

Updated: 2026-11-28.

## What the cloud runs

`dev` on `cr-platform2`, since a replace on the evening of 2026-11-28
(UTC+9 20:55, exit 0, 30 min) onto new role images `cr-kali-bake5`,
`cr-waf-bake6` and `cr-infra-bake3` (target unchanged, `cr-target-bake3`):
the 2026-11-28 renames (role files in `deploy/roles/`, `cases/`,
`sites.conf`, `customers.py`, `web-proxy.py`, `board.rules`, the `refill`
service, `defence/waf/terminal/`) and the kali command log stamping a
command when it starts are live. The pvp time limit is 15 minutes, the
code default (`CR_PVP_TIME_LIMIT_SECONDS=900`). `main` holds the old product
until gate 2.

## Checked live today

- After that replace, both pvp wargames passed every step from sign-in to
  sign-out (rounds 499 board, 500 corp; `~/.cache/fsl-work/pvp-check/`):
  on corp the attack takes the objective, IDS sid 9000201 alerts, the
  defender's WAF rule passes its test, goes live and the same attack gets
  403; on board the search SQLi is refused by CRS and then by the
  defender's rule. Both rounds ran 15 minutes from start to `ends_at`.
- corp's WAF rule test replays the re-recorded `corp-rogue-admin` probe,
  whose registration request carries the form's `-5` field ids, and the
  defender's rule refuses it (TP).
- The full acceptance from the platform VM stopped at the one-hour limit:
  75 passed, 2 failed, 11 not reached (one group of 11 modules unfinished).
  `test_corp_authz.py::test_a_live_option_flip_is_lost_from_the_targets_own_row`
  lost `corp-rogue-admin` beside `corp-self-registration`;
  `test_origin_spend.py::test_the_first_origin_is_spent_and_the_box_moves_to_the_next`
  saw `origin.spent` but no `origin.switched`. Neither is explained yet.
- The demo answer sheet (attack and defence per wargame, the rules used and
  the sqlmap commands from `cases/board.yaml`) is a private artifact.

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
- The attack bot meets 2 refusals a run on Sonnet and Opus 5.5 and goes on.
- Round 406's `ground_truth_unavailable` (2026-11-27) is not explained; a
  round that does not start now logs why.
- Whether a platform read under three rounds still runs past 5 s now that it
  runs off the request thread (`CR_READ_IN_BACKGROUND=1`) is not measured.
- The rest is in `docs/STATE.md` "Not live-verified" and "Open points".

## Next, in order

1. The two acceptance failures above, then the 11 tests not reached.
2. External learners: the public-IP forwards (UDP 51820-51919, TCP 2222,
   the console) and `CR_VPN_HOST`.
3. Gate 2: a live review round with zero countable findings and a docs
   review, then the change and its evidence to the user.

Written for a session that reaches the cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet.
