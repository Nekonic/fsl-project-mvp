# Scenario course on the range, with a GNS3 topology: design

Status: approved to build (2026-10-13, the user). Supersedes the lesson
shape of `2026-10-13-blue-team-course-design.md` (scripted step lessons,
Lesson / Practice / Wargame rungs); its foundation (server-side checks,
replays out of both scores, WAF snapshots, debrief, Suricata editor) stays.
Rulings in `docs/DECISIONS.md` (2026-10-13, "scenario course").

## Audience

University security-club freshmen. Most do not know networking. The course
therefore opens with foundations taught on the range itself, then moves to
scenarios where traffic flows and the learner defends.

## How people actually learn (research, 2026-10-13)

Seven research agents read lab pages, public learner write-ups, practitioner
tutorials and the learning-science literature.

- The common loop: a short explanation of one technique (PortSwigger 20-470
  words per lab); a walkthrough of that exact problem (Dreamhack's "Exercise"
  lectures, Netnea's curl steps); a new problem that changes one thing,
  solved alone (Dreamhack XSS-1 to XSS-2: the same app, `innerHTML`, the
  taught payload no longer works); a check against an answer or system
  state (TryHackMe/HTB flags, RangeForce's grading bot); an assessment in an
  unseen situation (HTB Skills Assessment, TryHackMe Snort Live Attacks, the
  KISA SOC course's day-4 red/blue exercise).
- What makes the next problem harder, with evidence: less feedback from the
  system (PortSwigger SQLi labs 9, 11, 12, 14, 16); evidence handed vs hunted
  (BTLO Deep Blue Q1-3 vs Q4-6); volume (Netnea tutorials 7-8: one request,
  a scanner, one false positive, a 10,000-line log); how much of the rule
  the learner writes (HTB "Working with IDS/IPS", TryHackMe Snort rooms); one
  rule improved against an evolving exploit (SANS SEC503); facts vs judgement
  (LetsDefend's six playbook questions, HTB SIEM assessment); known vs unknown
  attack.
- Defenders: Netnea (Folini) teaches false-positive tuning on recorded real
  traffic ("There is no point in learning to fight false positives on a lab
  server without traffic"), blocking mode with the threshold lowered over
  iterations; Emerging Threats tunes against kept true-positive traffic so a
  tune creates no false negative; Korean SOC training judges an alert by
  source reputation, payload and history and tunes on frequency and the
  true/false-positive ratio, and its learners complain of procedures without
  real logs.
- Learning science: task classes from simple to complex with support fading
  inside a class and variety between tasks (4C/ID, van Merriënboer; d=0.79,
  Costa et al. 2022); worked examples early, problem solving later, fading
  backward (Renkl); hints must be offered when a learner is stuck, not only
  made available (Vykopal et al. SIGCSE 2020; Aleven et al. 2003); debriefs
  improve performance about 25% (Tannenbaum and Cerasoli 2013).
- No surveyed platform teaches defender-side false-positive tuning; the
  range can, because it has a real target, real engines and real traffic.

## The course

### Foundations (F1-F6), on the range

Each unit: one short explanation, a hands-on step on the learner's own
range, a question answered from the learner's own records.

| Unit | The learner | Checked from |
|---|---|---|
| F1 My range | reads the topology: users, attacker, edge, WAF, web server, DB, log server | topology |
| F2 The path of one request | reads the hops on the network map; searches in Korean in the Website pane and reads the status code in its developer tools (the follow view it first followed the request in was removed 2026-10-16 by the user) | own request: status |
| F3 HTTP | URL, parameter, method, status code on that request | own request |
| F4 Reading logs | finds the request in Kibana, reads its fields | own detections |
| F5 Read one attack | sends `' OR 1=1` and runs sqlmap; finds where it stopped (developer tools) and the rule (Kibana) | own request and detections |
| F6 What a miss costs | the same attack with the rule off: accounts leak, the first score says lost | target ground truth |

### Scenarios

A scenario: a briefing (situation, one-line goal, how it is measured, time
limit); benign users and an attacker sending traffic for the whole session;
an attack schedule unknown to the learner; the learner's real tools; judged
by the product's two scores, with blocked customer requests counted in the
second; complete when, over the final verification window, every attack is
held and every customer request is served; supportive cards just in time;
a hint offered when the learner is stuck (repeated failing actions), free and
recorded; the debrief.

| Task class | Scenarios (guided to unguided) | Complete when |
|---|---|---|
| 1 Judgement | 1.1 a quiet shift: a failed sqlmap attempt and a blocked Korean search (worked) · 1.2 an inherited rule removal lets an attack succeed · 1.3 many alerts, no guidance | each alert judged attack or customer, and whether it succeeded, matching the target's records |
| 2 Availability vs blocking | 2.1 Korean searches blocked at PL3 · 2.2 `<b>` and URL searches blocked at PL2 · 2.3 several false positives, threshold lowered over iterations | no customer blocked and no objective lost over the window |
| 3 Missed attacks | 3.1 fix one value of a given rule · 3.2 write the `?sort=` rule · 3.3 catch the tamper variants with one rule · 3.4 body XSS | every attack variant detected, normal sort and comment quiet |
| 4 Unknown | 4.1 an unseen attack and new false positives, no guidance · 4.2 human red team vs blue | both scores |

O'Brien stays a benign regression case only.

### Topology: a real GNS3 project

- The range's topology is two GNS3 project files (`revision` 9, so GNS3 2.2
  opens them and 3.x upgrades them), one per substrate: segments are
  `ethernet_switch` nodes, containers `docker` nodes with their GHCR images,
  OpenStack VMs `qemu` nodes (the OPNsense edge with three adapters), links
  port to port. A test keeps them equal to `platform/range/declaration.yaml`;
  a check loads them in a real gns3-server.
- A GNS3 server (3.1.0a6, pinned; the official images are 2.x only, so the
  image is built from the gns3-server tag) runs in the platform's compose on
  its own port; nodes are never started (no KVM, no privilege, no docker
  socket). Learners see its web UI in the blue console read-only (the
  built-in Auditor role). The request-path overlay (Packet Tracer's
  simulation mode as precedent), drawn by the console from the same file and
  the session's detections, was built as the follow view and removed on
  2026-10-16 by the user; the Topology pane is the map alone.
- GNS3's MCP service (3.1) is for development only; it is not exposed to
  learners.

## Build order

| Phase | Work |
|---|---|
| P0 measure | the narrow fix for the Korean search at PL3; benign comment and login through the forms (CSRF); the traffic rate the range sustains; the threshold `setvar` |
| P1 topology | the GNS3 files, the consistency test, the load check, the GNS3 service and image, the console pane and the request-path overlay |
| P2 foundations | F1-F6 on the existing server-side step engine |
| P3 traffic | a benign-user generator running for the whole session, every request marked and recorded |
| P4 scenario engine and console | descriptor, attack schedule, triage API, window-based completion, stuck detection |
| P5 scenarios | classes 1-4 |
| P6 cleanup | remove lessons 0-5, 7 and the rungs; docs; live runs |
