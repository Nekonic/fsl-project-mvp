# Blue-team course: design

Status: approved to build (2026-10-13, the user: "proceed as recommended").
Extends `2026-10-08-composable-isolated-learning-mvp-design.md`; where the two
differ, this file and the 2026-10-13 entry in `docs/DECISIONS.md` win.
Produced by six research agents (Dreamhack, KISA, HTB, TryHackMe, PortSwigger,
CRS/Netnea, LetsDefend, CyberDefenders, RangeForce, Immersive Labs, Cyberbit,
Locked Shields, AhnLab ASEC, ESTsecurity ESRC, Igloo) and a 28-agent design
workflow (13 dimensions, 108 options generated, 12 dropped by skeptics,
66 added).

## The problem

The one lesson (`wargames/board/scenario.yaml` `lesson:`) states its goal only
in a non-default tab, and the goal text ("block every sqlmap variant")
misstates what VERIFY judges. The learner's only real work is one exclusion,
done by a Run button. Steps can be skipped with Next and nothing records it;
answer keys and step state live in the browser; a 60 s timer records a hint
the learner never asked for. There is no debrief beyond one line per step.

## What every platform surveyed shares

1. A goal header before any action: one "To solve" sentence, the success
   criterion, prerequisites, time, level (Dreamhack 학습목표, PortSwigger,
   Immersive "how you will be measured").
2. Short theory immediately followed by practice (Dreamhack, HTB Academy,
   KISA 40/60).
3. Each step ends in a check against system state or a question whose answer
   is in the record (HTB "questions are the flags", RangeForce automatic
   grading).
4. Hints that fade, guided and unguided modes over the same task (HTB Guided /
   Adventure, TryHackMe difficulty = amount of guidance).
5. A final unguided assessment (HTB Skills Assessment, RangeForce challenge).
6. A debrief from the platform's own record: before/after per case, the change
   made, timeline (Cyberbit, KISA "모의 공격 및 공격차단 확인", Igloo
   before/after).

No surveyed platform has a defender-side WAF false-positive lesson; HTB's and
TryHackMe's WAF rooms are attacker-side.

## Findings in the code that shape the build

| # | Finding | Where |
|---|---|---|
| X1 | A guided open applies the lesson posture and the seed replay only when the adapter has `for_session` (docker). On OpenStack the lesson likely opens at PL1, where step 1 cannot fail. | `platform/api/views.py` `_take_defense`/`_seed_logs` gates |
| X4 | Answer keys reach the browser; answer/choice are judged there; the step lives in localStorage; Next skips silently; the 60 s timer records a hint. | `views.py` session detail, `blue_lesson_script.html` |
| X5 | The `waf` and `served` checks replay through `POST /attacks/` as unmarked cases, so `/score/` counts them. Breaks "one case counts once". | `views.py` attacks, `blue_lesson_script.html` |
| X6 | "Held" is sqlmap's "not injectable"; a board whose sink does not execute passes. The control replay in `test/test_lesson.py` is the only proof the sink is live. | `views.py` verify, `redteam/tools.py` |
| X8 | Suricata only detects on both substrates; no Suricata lesson can pass the 2026-10-08 completion rule. | `session.yaml`, `deploy/opnsense/config.xml` |
| X9 | Six of eight board attacks fail against the app itself; only the two sqlmap `?sort=` variants move ground truth. | `redteam/cases/board.yaml` |
| X10 | A leak found by VERIFY is excluded from attribution and so always counts lost and unnoticed (double). | `views.py` score |
| X11 | After close, `GET /waf/` returns the open posture; the learner's edit is lost. | `views.py` waf |
| X13 | The only measured false positive is O'Brien at PL4 (920273). | DECISIONS 2026-10-10 |

Stale record, corrected: WAF tuning on OpenStack works (504ad9b, 72 passed
2026-10-12); "OpenStack sqlmap does not extract" was measured on the retired
board VM image and is unverified on the wargame host.

## Rulings (2026-10-13)

- **D1** Lowering the paranoia level stays a passing fix for the false-positive
  lesson (2026-10-10 ruling kept). The result names which fix was made
  (path-scoped target exclusion / target exclusion / whole rule removed /
  level lowered), reported beside PASS, never gating. A false positive that
  exists at PL1 is to be measured; if a realistic one exists it replaces the
  PL4 start.
- **D2** A Suricata lesson completes on detection: every attack case of the
  lesson is a true positive whose alert corroborates `expect`, every benign
  case draws no alert. It reports in the second score only and never marks an
  objective. This amends the 2026-10-08 rule "every malicious variant
  blocked, judged by target state" for IDS lessons only.
- **D3** The learner writes a Suricata rule in a console text area that calls
  `PUT /api/rules/apply/`. This reverses "no rule editor" (DECISIONS
  2026-09-30) for Suricata signatures only; CRS stays exclusion-only.
- **D7** A leak found by the learner's own VERIFY or by a lesson check is
  reported in the lesson diagnosis and kept out of the first score, as seed
  and VERIFY replays are already kept out of the second.
- **D8** One investigation lab late in the path; per-case triage in plain
  words; no triage/report track.
- **D9** No virtual-patch SecRules for corp; corp lessons teach noticing a
  loss.
- **D11** Several lessons (and their postures) in one `scenario.yaml` are the
  proof of "one image, many scenarios"; `board-easy`/`board-hard` directories
  are retired.
- Engineering defaults taken with the recommendation: open lesson order with a
  recommended sequence; skipping allowed and recorded; no learner identity
  beyond browser-local session ids plus server step records; the floating
  note stays; debrief times are API-only; the 60 s timer becomes a
  non-recording "hint available"; Korean stays in `strings.html`.
- Audience: a university club (spec 2026-10-08); lesson 0 teaches the console
  for complete beginners; a separate HTTP/SQLi primer is not in scope.

## The build, in order

### Foundation (shared by every lesson)

1. Ungate the open path: the lesson posture and the seed replay run on every
   substrate; `test_lesson` runs on OpenStack.
2. Server-side lesson progress: `Session` records each step reached, passed,
   skipped, hinted, done-for-me; checks are judged on the server; answer keys
   leave the session payload.
3. Check replays are marked and kept out of both scores (X5) and leaks found
   by lesson replays out of the first score (D7).
4. The WAF configuration is snapshotted at each VERIFY and before the close
   rebuild (X11).
5. The goal line is corrected and pinned; the lesson declares its defense;
   the console stops hard-coding `minimal`.

### Package 1: the existing lesson made honest

- Lesson / Practice / Wargame rungs on the same task (Practice = guidance on,
  no Run button, no filter chip, hints hidden; Wargame = guidance off, full).
- Opening: the Goal tab first, the customer ticket (facts from `GET /waf/`
  only), the starting PASS/FAIL card from the seed replay.
- Steps: passed vs skipped shown; one sqlmap regression replay after the
  exclusion; "inconclusive" has its own message; fix narrowness reported.
- Debrief after PASS (Igloo/ASEC order): overview, evidence log rows from
  `session.detections`, the change (config diff from the snapshots),
  before/after per case (seed vs last VERIFY), remaining risk.

### Package 2: one linear path (open order)

| # | Lesson | To solve | Check |
|---|---|---|---|
| 0 | Console tour | Find your own request in Kibana and say which rule blocked it. | alert / answer / choice |
| 1 | Read the block | Name the rule that blocked O'Brien and the parameter it fired on. | answers computed from the session's detections |
| 2 | Narrow exclusion | Make the O'Brien search load while sqlmap still concludes `?sort=` is not injectable and the other ordinary pages still load. | waf check + VERIFY |
| 3 | Choose the level | Find the highest paranoia level at which every ordinary request is served and both sqlmap variants are held, with no exclusions. | VERIFY + `GET /waf/` paranoia |
| 4 | IDS signature | Write a rule that alerts on both sqlmap `?sort=` variants and not on `?sort=-created_at`. | D2 detection completion |
| 5 | XSS in the body | Alert on the comment XSS sent in the request body without alerting on an ordinary comment. | D2; needs a benign comment POST case |
| 6 | Corp: what a WAF cannot see | Make the option flip noticed. | needs a red actor outside the lesson, corp replay fixes |
| 7 | Assessment | Board at PL4, no guidance: O'Brien served, attacks held. | VERIFY |

Lessons 0-3 need no further ruling. Lessons 4-5 wait on the Suricata
isolation check below; lesson 6 on the corp replay fixes (repeatable logins,
reset before VERIFY) and an outside red actor; lesson 7 on the rungs.

## Checked before the lesson that depends on it

- U1/U2/U11 Guided open on OpenStack applies PL4 and seeds; the board on the
  wargame host executes the `?sort=` sink and sqlmap dumps; the exclusion
  posture leaks there as on docker: `test_lesson` on OpenStack.
- Suricata rule isolation on OpenStack: whether a rule applied for one
  session loads into every slot's sensor (`declaration.yaml` sensor rule
  file). Blocks lessons 4-5 until measured.
- VERIFY "served" is any 2xx: whether a learner can pass by rewriting the
  WAF's deny status; if so benign cases need a body marker. Unverified.
- U6 Which sid fires on each sqlmap variant, and whether one rule catches the
  tamper variant without matching `?sort=-created_at`.
- U7 A realistic false positive at PL1-3 (D1).
- U12 The persistent OpenStack Kali's sqlmap session cache and the VERIFY
  verdict (`--flush-session`).
