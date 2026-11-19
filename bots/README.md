# Bots

A bot holds one seat of a round, attack or defence, and reaches exactly what a human console reaches: the same
attack or defence API, under the same seat permission, through the client generated from
`openapi/schema.yaml` into `bots/client/` (`bin/gen-clients`; not committed). The bots are model-agnostic:
nothing here names a model or a vendor.

| File | What it is |
|---|---|
| `tools.py` | Turns the operations a side may call into JSON Schema tool specs, from the committed schema |
| `calls.py` | Makes one tool call through the generated client and reports `{operation, ok, status, body, headers?}` |
| `cli.py` | The command line: tool specs, prompts, one call, or a provider playing the seat |
| `play.py` | The turn loop a provider plays in |
| `provider.py` | The provider interface: `turn(system, tools, transcript) -> Turn(text, calls)` |
| `prompts/` | `attacker.md`, `defender.md` (rules of play) and `claude_code.md` (the CLI) |
| `signin.py` | Signed-in and seated clients, shared with `test/` and `bin/` |

## A seat

The operator creates a round with a bot seat (`POST /api/leases/<lease>/rounds/` with `{bot: {name}}` for the
side) and receives the seat token once. The token reaches its side's routes and the round's `GET /`,
`events/`, `topology/` and, after the end, `score/`. After `round.ended` it stays valid read-only for 15
minutes, so the bot can read the end and the score.

The CLI reads the token from `CR_SEAT_TOKEN`, the platform from `CR_PLATFORM_URL` (or `--base-url`) and the
round from `CR_ROUND` (or `--round`).

```
python -m bots.cli tools --side attack
python -m bots.cli prompt --side attack
echo '{"name": "attack_state", "arguments": {}}' | python -m bots.cli call --side attack
python -m bots.cli attack_fire_case --json '{"case": "board-sqli-search"}'
python -m bots.cli run --side defence --provider mypackage.mymodule:make_provider
```

`call` and the one-line form print one JSON answer. A refusal the platform made is printed with its status and
the exit code is 0; a refusal made before anything was sent (`"local": true`: unknown tool, an argument the
spec does not take, a value the client cannot encode) exits 2, an unreachable platform exits 3.

## Plugging in a model

`run` takes `--provider package.module:factory`. The factory takes no arguments and returns an object with
`turn(system, tools, transcript) -> bots.provider.Turn`. `tools` is the side's tool spec list
(`{name, description, input_schema}`), and `transcript` is a list of plain entries:

- `{"role": "user", "text"}`: the opening, which carries the seat's state;
- `{"role": "assistant", "text", "calls": [{"id", "name", "arguments"}]}`: what the provider answered;
- `{"role": "tool", "call_id", "name", "result"}`: the answer of each call.

The provider turns these into its model's own message format. A `Turn` with no calls ends the run; so does
`--turns`. Each entry is printed as one JSON line as it happens.

## Hit points

Every attack origin has a budget, and every request drains it. The rule is the `hp.rule` block of every attack
answer:

| Field | Meaning |
|---|---|
| `budget` | hit points each origin starts with |
| `per_request` | cost of one request |
| `refused_x` | multiplier for a request the WAF refused |
| `refused_statuses` | the statuses that count as refused: 400 and 403 |
| `burst_per_s` | requests per second from one origin before the burst multiplier applies |
| `burst_x` | multiplier for requests beyond `burst_per_s` in one second; it multiplies with `refused_x` |

Every attack answer, errors included, carries `hp: {origin: {id, label, ip}, left, budget, origins_left,
spent, rule}` and the headers `X-Origin` and `X-Origin-HP`. At `left` 0 the origin is spent: the infra edge
drops it, open connections included, its tool runs stop, and the seat moves to the next origin. The bot may
leave an origin early with `attack_next_origin`. When `origins_left` is 0 every attack write answers
`409 origins_spent`. API sends are charged at once and exactly; shell and tool traffic is charged from the WAF
access log one tick late.

## The attack baseline and what is scored

The attack bot's baseline is firing the declared cases with `attack_fire_case`. Declared cases and the benign
cases the platform fires are the only actions that enter TP/FP/FN/TN, one decision per case however many
alerts it draws. Free actions (`attack_send`, tool runs, shell traffic) are attributed by source address and
time and are never scored as TP/FP/FN/TN; they appear under `free_actions` in the score. Objectives are lost
only when the target's own data says so.

## Errors

Every refusal is `{errors: [{path, code, line?, params?}]}`; attack refusals add `hp`. Codes a bot meets:

| Code | Status | Meaning |
|---|---|---|
| `not_signed_in` | 401 | no or unknown seat token |
| `not_seated` | 403 | the token is not a seat of this side of this round |
| `invalid`, `required`, `max_length`, `invalid_choice`, ... | 400 | a field error at `path` |
| `unknown_case`, `unknown_tool`, `unknown_run` | 404 | no such declared case, tool or tool run |
| `round_not_started` | 409 | the round is not running yet |
| `round_closed` | 409 | the round has ended; reads still work for 15 minutes |
| `round_running` | 409 | the score is read only after the end |
| `origins_spent` | 409 | every attack origin is spent |
| `stale_version` | 409 | `base_version` is not the applied version; `params` has the current one |
| `test_busy` | 409 | another rule test of this engine is running |
| `suricata_syntax`, `unread_sid` | 422 | the Suricata text was refused, with `line` |
| `crs_refused`, `apply_refused` | 422 | the CRS posture or the apply was refused |
| `attacker_unavailable`, `tool_unavailable`, `range_unavailable` | 503 | the attacker box or the range is not answering |
| `sensor_unavailable`, `waf_unavailable`, `elastic_unavailable` | 503 | a sensor, the WAF or the alert store is not answering |
