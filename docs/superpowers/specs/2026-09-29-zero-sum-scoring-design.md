# Zero-sum scoring: one balance, four pillars, revealed at the end

Date: 2026-09-29. Decided with the user. Replaces the two-number model as the
headline; the detection confusion matrix and the target-decided objectives
stay underneath as the ground truth the score is built from.

## What changes and what does not

The old model reported two numbers side by side: what the red team took
(objectives, target flips its own `solved`) and what the defence got wrong
(TP/FP/FN/TN). The user's decisions:

- **One zero-sum balance.** Points the attacker gains are points the defender
  loses. One scale that tips red or blue.
- **The defence is a single score**, made of four pillars: speed, accuracy,
  coverage, response.
- **Revealed at the end.** During a session the score is hidden; alerts and
  logs stay live because that is the defender's working material, but the tally
  is only shown once the session is closed. Live score lets either side game it.

What does not change, and must not: **the target still decides whether it was
beaten.** Juice Shop flips its own `solved`; the wiki access log judges the
internal read. Zero-sum only converts that target-decided outcome, and the
detector's own records, into points. The platform never decides a breach.

## The four pillars (defender)

Each pillar is computed per attack case (one case is one decision, however many
alerts it drew) and aggregated.

- **Speed.** Time from a case's start to its first corroborated detection.
  Full credit when fast, decaying to zero as it slows, zero if never detected.
  Aggregated as a mean time to detect. Data present: `Case.started_at`,
  `Detection.timestamp`.
- **Accuracy.** From the existing confusion matrix: corroborated true positives
  earn, false positives cost heavily (alert fatigue), true negatives earn a
  little. The `corroborated` gate stays: a true positive whose alert does not
  name the attack's mechanism does not count.
- **Coverage.** Of the ATT&CK stages present in the fired attacks, the fraction
  with at least one corroborated detection. Data present: `Case.stage`,
  `Case.technique`.
- **Response.** Whether attacks were blocked (contained) and whether benign
  traffic was wrongly blocked (an availability cost). Needs a per-case
  `blocked` disposition, which does not exist yet; see staging.

## The zero-sum balance

A single ledger, reported from the defender's side (positive = defence ahead,
negative = attack ahead):

- The attacker earns each objective's `difficulty`, multiplied by how long it
  stayed undetected (dwell). This is the pot the defender is trying to hold.
- The defender claws points back through the four pillars: detecting fast and
  correctly, covering the kill chain, and (once built) blocking.
- The defender loses points for its own mistakes: false positives and blocking
  benign traffic. In a zero-sum ledger those losses tip the balance toward the
  attacker.

Weights across the pillars are declared and shown beside the score (the
transparency lesson from Locked Shields); the four pillar sub-scores are always
visible under the one headline (the breakdown MITRE's evaluations keep). Cases
are weighted by difficulty, so a hard attack counts more than an easy one.

## Reveal at the end

`GET /api/sessions/<id>/score/` returns the score only once the session is
closed; while it is open it reports that the score is withheld. The blue
console shows the scoreboard only after close. Alerts, the live dashboard and
the rules editor stay available throughout — only the tally waits.

## Where the code goes

The detection confusion matrix in `platform/scoring/` (core, gated to shrink)
stays as it is. The new game math — pillars, dwell, the zero-sum roll-up —
goes in `platform/scoreboard.py` and a new `platform/game.py`, both product
code (not counted as core), as pure functions with no I/O, tested without the
stack.

## Staging (build cheap, keep what survives)

1. **Speed and coverage now.** The data already exists, so these two pillars
   and a first zero-sum balance (with response neutral) can be built and
   unit-tested without the stack, and revealed at session end.
2. **Response next.** Turn on blocking (the WAF's blocking mode, Suricata
   inline) and record a per-case `blocked` disposition, then add the response
   pillar and its availability cost.
3. **Weights and console last.** The declared weights, the single headline, and
   the end-of-session reveal in the blue console.

## Tests

- Pure unit tests for the pillar functions and the zero-sum roll-up: a fast
  detection scores higher than a slow one; a false positive tips the balance to
  the attacker; an undetected objective is worth more to the attacker than a
  detected one; covering more ATT&CK stages scores higher.
- Acceptance: the score endpoint withholds the tally on an open session and
  returns it once closed.
