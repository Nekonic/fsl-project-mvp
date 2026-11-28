# Now

The handover to the next session, kept short. The build record, one line per
tree, and the backlog are in `docs/STATE.md`; rulings in `docs/DECISIONS.md`;
problems in `docs/TROUBLESHOOTING.md`; the current design in
`docs/ARCHITECTURE.md`, the historical 2026-11-19 design in
`docs/specs/2026-11-19-side-split-design.md`; detail in `git log`.

Updated: 2026-11-29.

## What the cloud runs

`dev` on `cr-platform2`, since a replace just after midnight UTC+9 on
2026-11-29 (exit 0, 14 min; role images unchanged: `cr-kali-bake5`,
`cr-waf-bake6`, `cr-infra-bake3`, `cr-target-bake3`). Live with it:

- One port. The site pane is `/site/<round>/<host>/` on 8000 under
  `Content-Security-Policy: sandbox allow-forms allow-same-origin; script-src 'none'; object-src 'none'; base-uri 'none'`
  (`docs/DECISIONS.md` 2026-11-28 "One port"). The old site port is gone from compose
  and from the `cr-platform` group, which now opens 22, 2222, 8000 and
  udp 51820-51919. The user forwards 8000, 2222 and udp 51820-51919.
- The guardrails (`docs/DECISIONS.md` 2026-11-28 "Six checks"), with a
  `commit-msg` hook and a CI step refusing attribution lines. Each clone
  turns the hooks on once: `git config core.hooksPath .githooks`.
- The terminals run with `TZ='<+09>-9'`, so `date` shows `+09`.

The pvp time limit is 15 minutes, the code default. `main` holds the old
product until gate 2.

## Checked live today

- After the one-port replace: a board pvp check (round 542) passed 19 of 19
  steps and a corp pvp check (round 543) 21 of 21. Both checks now require
  the site frame on `:8000/site/` with the policy above. On corp a
  registration posted through the pane (302, one POST row), and the
  browser logged `Blocked script execution` for the target's scripts.
  `bin/acceptance --only test_front_door,test_range_isolation` from the
  platform VM: 13 passed, 0 failed in 7.5 min. `bin/select-tests` named all
  88 acceptance tests for the change (the Heat template and `cr/config.py`
  are named by no test), past the one-hour limit, so these two modules, the
  ones that check what reaches the platform VM, ran instead.
- Before the one-port change, on the tree before it:
  both pvp wargames passed every step from sign-in to
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
  saw `origin.spent` but no `origin.switched`. Both were the tests, not the
  product. The spend logs `origin.switched` after the edge and the box move,
  about 2 s after `origin.spent` (round 518: 12:59:19.7 and 12:59:21.6 UTC),
  and the test read the events at once; it now waits for the switch. In the
  option-flip round (506) the benign `corp-normal-registration` POST got 302
  at 12:21:33 UTC after `default_role` became `administrator`, and the
  target's binary log gave `corp-rogue-admin` an administrator grant at
  12:21:36, attributed to the `default_role` flip: a real rogue admin the
  flip made. The test now allows that loss when it is
  attributed to one of the flip's own requests. Rerun from the platform VM
  with the two fixed modules and the 11 not reached: 40 passed, 0 failed,
  0 errors in 40 min (`test_corp_authz` 3, `test_origin_spend` 6, the group
  of 11 31). No platform image changed, so no replace.
- After that, both pvp checks passed again: board 19 of 19 steps (round
  533), corp 20 of 20 (round 535).
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
- `bin/acceptance --only` takes module stems (`test_front_door`); a name with
  `.py` matches nothing and the run reports 0 passed, 0 failed.
- The rest is in `docs/STATE.md` "Not live-verified" and "Open points".

## Next, in order

1. External learners: the public-IP forwards (TCP 8000, TCP 2222,
   UDP 51820-51919) and `CR_VPN_HOST`.
2. Gate 2: a live review round with zero countable findings and a docs
   review, then the change and its evidence to the user.

Written for a session that reaches the cloud through the user's VPN
(Keystone http://10.0.0.10:5000, platform VM http://192.168.2.247:8000) and
the Internet.
