# WordPress authz target (sub-project B) — design

**Goal:** Add a second wargame target — a realistic WordPress company site — whose
objectives are unauthenticated broken-access-control attacks the default WAF
cannot see, scored by the platform observing the target's own database change
log. It complements the board: the board's SQLi/XSS are caught by default
OWASP CRS (so the blue team tunes/silences rules); B's authz attacks are
invisible to default CRS (so the blue team must write new detection).

**Architecture:** Real WordPress on MySQL, running three outdated plugins that
each carry a published missing-authorization CVE. A red-team case fires each
attack as a single unauthenticated HTTP request. The platform snapshots the
target's relevant state at session start and then reads the MySQL binary log
(ROW format) to observe the unauthorized state change the attack commits; a
change absent from the start-of-session baseline is the lost objective, bound
to the attack window by the committed row's timestamp. Ground truth is the
target's own stored rows, read off the detector's path — the platform never
credits an objective from a Suricata/ModSecurity alert.

**Tech stack:** WordPress (official image) + three pinned vulnerable plugins
from the wordpress.org plugin SVN tags; MySQL (binlog ROW enabled); the
existing Python platform, Suricata, ModSecurity/OWASP CRS, Elasticsearch,
nginx WAF. No new pip dependency and no new gated platform compose service;
WordPress, its MySQL and the plugins are the wargame's own services
(`wargame_services`, reported, not gated).

## Why this target, and the realism rule

Every vulnerability is a real published CVE in unpatched software — the same
"they did not update" model as the board's Django 3.2.4. Nothing is a
deliberately-planted vulnerable page (the rejected `members.json` shape). The
implied site is an entirely believable small community WordPress that left a
membership plugin, a GDPR/compliance plugin and a guest-posting plugin out of
date.

## The three objectives

Each objective is one real CVE, one vulnerable plugin, one distinct database
table, and is exploitable from an unauthenticated position in a single request.
None is remote code execution. None carries a SQLi/XSS/traversal token, so the
default OWASP CRS has no signature for it — that is the point.

| # | objective | plugin (pinned) | CVE | request (unauthenticated) | DB change observed | difficulty |
|---|---|---|---|---|---|---|
| 1 | rogue administrator created | Ultimate Member 2.6.6 | CVE-2023-3460 | registration POST smuggling `wp_capabilities[administrator]=1` | new `wp_users` row + `wp_usermeta` capability = administrator | 5 |
| 2 | site reconfigured to admin self-registration | WP GDPR Compliance 1.4.2 | CVE-2018-19207 | unauth `admin-ajax` `wpgdprc_process_action` sets `users_can_register=1`, `default_role=administrator`, then a plain registration | `wp_options` rows `users_can_register` and `default_role` change (then a `wp_users` row) | 4 |
| 3 | unauthorized content created / overwritten | Easy Post Submission 2.3.0 | CVE-2026-4431 | unauth `admin-ajax` `rbsm_submit_post`; no `postId` creates a post, a `postId` overwrites/unpublishes an existing one | `wp_posts` INSERT, or UPDATE flipping `post_status`/content of an existing row | 3 |

Sources: CVE-2023-3460 — https://nvd.nist.gov/vuln/detail/CVE-2023-3460 ,
https://www.wordfence.com/threat-intel/vulnerabilities/wordpress-plugins/ultimate-member/ultimate-member-266-privilege-escalation-via-arbitrary-user-meta-updates .
CVE-2018-19207 — https://nvd.nist.gov/vuln/detail/CVE-2018-19207 ,
https://www.rapid7.com/db/vulnerabilities/wp-gdpr-compliance-plugin-cve-2018-19207/ .
CVE-2026-4431 — https://www.wordfence.com/threat-intel/vulnerabilities/wordpress-plugins/easy-post-submission/easy-post-submission-230-missing-authorization .

The three objectives form the severity gradient on their own, so B needs no
partial/full/admin role ladder: for CVE-2023-3460 a rational attacker always
grants administrator in one request, so intermediate WordPress roles (author,
editor) would never occur and are not scored. Content overwrite (3) ranks below
the config flip and account work (2) below a freshly minted administrator (1).

## Scoring: the platform observes the target's state change

B introduces a third objective model beside `loot_verified` and `none`. Working
name: `effect_observed`. The attacker does not submit anything (there is no
pre-existing secret to prove possession of — the win is a state mutation), so
the submit-and-match flow of `loot_verified` does not apply. Instead:

- **Snapshot at session start.** Where the platform already snapshots ground
  truth onto `Session.baseline`, an `effect_observed` session instead records
  the target's relevant pre-attack state: the set of administrator user ids,
  the watched `wp_options` values, and the set of published post ids. Read off
  the detector's path, estate-only.
- **Observe via the binary log.** MySQL on the WordPress target runs with
  `binlog_format=ROW`. The platform reads the binlog over the session window
  (by running `mysqlbinlog` inside the database container — ships with MySQL,
  so no new pip dependency) and extracts the committed row changes to
  `wp_users`, `wp_usermeta`, `wp_options` and `wp_posts`. Each objective's
  signal is a specific committed change (a new administrator row; the two
  option rows flipping; a post INSERT or an existing post's UPDATE).
- **Attribute and credit.** A change whose committed timestamp falls in a
  malicious case's window, and which was not present in the start-of-session
  baseline, is the lost objective, credited through the existing
  `scoreboard.attribute` / `_breaches` / `game` path exactly as board loot is.
  The detected/undetected dimension (counts double when undetected) is
  unchanged.

This keeps the invariant: the objective is read only from the target's own
committed rows, orthogonal to whether Suricata/ModSecurity alerted. It is the
King-of-the-Hill / service-checker model (the platform reads the target's own
state) rather than the attacker-submits-a-flag model — see the research note
below.

### Why read the change log rather than diff two snapshots

A two-point snapshot (read admin set at start and at scoring, set-diff) is
simpler and is the board's proven pattern, but it only sees the net result and
misses a change made and undone inside a session. The binary log is the
database's own authoritative record of every committed change, catches the
exact moment, and still adds no pip dependency. This target was chosen to be
observed in real time.

### How other ranges decide "the target was beaten" (research)

Two camps. Flag-submission frameworks (iCTF/shellphish, FAUST ctf-gameserver,
ENOWARS enochecker, HackerDom checksystem) credit an attack when the attacker
submits a captured flag token — coupling the score to what the attacker chose
to send. B cannot use this (no pre-existing secret; the win is a mutation).
State-reading scoring (King-of-the-Hill's `/root/king.txt` poller on
CTFd/TryHackMe; CCDC-style service checkers) credits by reading the target's
own state on a schedule, independent of any defender alert. B's rogue-admin row
is exactly a KoTH marker the attacker plants by exploiting the CVE, and B's
monitor reads WordPress's own MySQL. FAUST's OK / FAULTY / DOWN taxonomy is the
vocabulary to separate "WordPress up, no unauthorized change", "WordPress up,
unauthorized change present", and "target unreachable, score inconclusive".

## The defensive challenge (blue team)

Default OWASP CRS does not detect any of the three — they are OWASP A01 broken
access control, logic flaws with no injection signature
(https://coreruleset.org/faq/). The blue team must add detection: a Suricata
rule matching the exploit request (e.g. the `wp_capabilities` parameter in a
registration POST, the `wpgdprc_process_action` option-write, the
`rbsm_submit_post` nopriv action), or a custom ModSecurity rule, or
log/audit-based alerting. The platform's TP/FP/FN/TN measures that detection,
and stays orthogonal to the objective check (which reads MySQL). This is the
whole reason the ground-truth layer is separate from the detector: the CVE's
own evasion story (the Ultimate Member banned-key denylist is bypassable by
altering the key) proves a request detector can miss the attack while the
database state still flips.

## Attack cases (red team)

Each objective is one scripted case in `redteam/cases/`, a single
unauthenticated HTTP request, console-fireable (unlike the board's finicky
sqlmap path, these are plain POSTs the console can send directly). Each
declares an `expect` substring of its own mechanism (e.g. `wp_capabilities`,
`wpgdprc`, `rbsm_submit_post`) so a true positive has to corroborate against
the attack's mechanism, not fire for an unrelated reason. B also needs benign
cases (a normal registration, a normal published-post read) so TN > 0 holds for
B on its own.

## Stack and reproducibility

A new `wargames/<id>/` directory with its own `compose.yaml` (included by the
top one): the WordPress app (official image), its MySQL with
`binlog_format=ROW`, and the three plugins pinned to their vulnerable versions
from the wordpress.org plugin SVN tags, installed and activated at build.
WordPress registration is set to auto-approve (no email activation, no admin
review) so the attacks are self-contained — an external attacker with no
account and no human in the loop. The WAF 404s any internal/estate-only read
path for WordPress exactly as the board's does, so the red team cannot read
ground truth. WordPress + its MySQL + plugins are `wargame_services` (reported,
not gated); `services` (the gated platform count) does not grow.

## Constraints (from CLAUDE.md)

- `core_loc` stays flat: the binlog reader and the `effect_observed` adapter
  live in product space (`platform/api/`, a wargame module), never in
  `scoring/`, `ingest/`, `rules/`, `redteam/harness.py`.
- `dependencies` stays 6: no new pip package (binlog read via `mysqlbinlog` in
  the DB container).
- `services` (gated) does not grow; `wargame_services` (reported) grows by the
  WordPress stack.
- `tests` floor only rises.
- The target decides: objectives are read from the target's committed rows,
  never from a detector alert.
- Every attack is a REST/HTTP request the console can fire.
- No code comments or docstrings.

## Relationship to the board

Both wargames coexist; the console picks which to run. The board exercises
"the WAF catches it, tune the rules"; B exercises "the WAF is blind, write the
rule." Together they cover both halves of the defensive skill. The
`effect_observed` model is general (any target whose win is an observable state
change), not WordPress-specific; WordPress is its first instance.

## Phasing (to be detailed in the implementation plan)

1. Bring up the WordPress + MySQL(binlog) + three-plugin stack as a new
   wargame; prove each CVE fires as a single unauthenticated request and
   commits its DB change; benign cases give TN > 0.
2. Add the `effect_observed` objective model: session-start state snapshot, the
   `mysqlbinlog` reader, the change-to-objective mapping, attribution into the
   existing scoreboard/game path.
3. The three objectives' `objectives.yaml`, the attack + benign cases, and the
   acceptance tests (each attack commits its change and is credited; detection
   is measured separately).

## Open items

- Confirm live, per CVE, that the single unauthenticated request commits the
  stated DB change on the pinned plugin version (verify the exact request shape
  and the committed rows before locking each case).
- Decide the exact `mysqlbinlog` read cadence/position-tracking (periodic exec
  over the session window vs. a longer-lived reader) during implementation;
  both stay dependency-free.
- The internal/estate-only read path for the session-start WordPress snapshot
  (admin set / options / post set) mirrors the board's WAF-404 pattern.
