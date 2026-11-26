# Bots

A bot is one player of a round, attack or defence, and reaches exactly what a human player reaches: the same
attack or defence API, under the same player permission, and the same shell. Every API call is built from the
committed `openapi/schema.yaml` at run time; there is no generated client. The player side is model-agnostic:
only the launcher names a program, Claude Code, and the model of each difficulty step comes from the platform.

| File | What it is |
|---|---|
| `tools.py` | Turns the operations a side may call into JSON Schema tool specs, from the committed schema, plus `shell` |
| `rest.py` | Sends one operation by its `operationId`: method, path and query from the schema, the body as JSON |
| `calls.py` | Checks a tool call against its spec, makes it and reports `{operation, ok, status, body, headers?}` |
| `shell.py` | Runs one `shell` command over the player's terminal SSH grant |
| `cli.py` | The command line: tool specs, prompts, one call, or a provider playing as the player |
| `play.py` | The turn loop a provider plays in |
| `provider.py` | The provider interface: `turn(system, tools, transcript) -> Turn(text, calls)` |
| `prompts/` | `attacker.md` (the engagement brief), `defender.md` (rules of play) and `claude_code.md` (the CLI) |
| `signin.py` | Signed-in and playing sessions (`requests`), shared with `test/` and `bin/` |
| `launcher.py` | The `bots` compose service: claims bot runs, starts one relay and one Claude Code child per run, reports notes and the finish |
| `watch.py` | The defence run's watch: what is new since the last feed, and the feed text |
| `relay.py` | The per-run relay the child calls instead of the platform: holds the player token, applies the step's pace and allowance |
| `pace.py` | Which calls count as actions and how long the next one waits |
| `Dockerfile` | The `bots` image: Python, `openssh-client`, the Claude Code CLI, `bots/` and `openapi/schema.yaml` only |

## A player

Staff create a round with an externally driven bot player (`POST /api/allocations/<allocation>/rounds/` with
`{bot: {name}}` for the side) and receive the player token once. A seat made with `{bot: {step}}` returns no token: the
platform queues a bot run at round start and the launcher claims it (`bot_run_claim`, tag `bots`), which issues the
token. A learner's lobby makes only `{bot: {step}}` seats, choosing the step from the problem's `bot_steps`; an attack
bot seat draws one of the problem's attack cards, which nobody sees before the end. The token reaches its side's routes and the round's `GET /`,
`events/`, `topology/` and, after the end, `score/`. After `round.ended` it stays valid read-only for 15
minutes, so the bot can read the end and the score.

The CLI reads the token from `CR_PLAYER_TOKEN`, the platform from `CR_PLATFORM_URL` (or `--base-url`) and the
round from `CR_ROUND` (or `--round`).

```
python -m bots.cli tools --side attack
python -m bots.cli prompt --side attack
echo '{"name": "attack_state", "arguments": {}}' | python -m bots.cli call --side attack
python -m bots.cli attack_fire_case --json '{"case": "board-sqli-search"}'
python -m bots.cli shell --side defence --json '{"command": "sudo nginx -t"}'
python -m bots.cli attack_send --json-file call.json
python -m bots.cli run --side defence --provider mypackage.mymodule:make_provider
```

`call` and the one-line form print one JSON answer. A refusal the platform made is printed with its status and
the exit code is 0; a refusal made before anything was sent (`"local": true`: unknown tool, an argument the
spec does not take, a value of the wrong type or outside its enum) exits 2, an unreachable platform exits 3.

A rule test takes minutes (a WAF test 3 to 6.5 minutes in rounds 277 and 278), past Claude Code's 120 s
command limit, and the platform answers `defence_waf_test` and `defence_ids_test` only when the test ends. So
`call` and the one-line form do not wait for it: they write a job file with the arguments (never the token)
under `~/.cache/cr-bots/tests/round-<n>/` (`CR_BOT_TESTS_DIR`), start a detached
`python -m bots.cli finish-test <job file>` that makes the call and stores its answer there, and print
`{running: true, job, poll}` at once. The poll command reads the job:

```
python -m bots.cli defence_waf_test --json-file call.json
python -m bots.cli defence_waf_test_result --job 1
```

It prints `{running: true, running_s}` until the answer is stored, then the test's own answer; its `body.test`
is the test id for `defence_waf_apply`'s `tested` and for `defence_waf_test_result` by id. A second test of the
same engine while one runs is refused locally with `test_running`, before the relay counts it. `run` keeps the
blocking call.

## The shell

Each side has a `shell` tool beside its API tools, offered only while the schema has that side's terminal
operation; the defence also has `ids_shell`, over `defence_ids_terminal`, on the Suricata sensor's host. It
is the shell a human player gets: the first call asks `attack_terminal`, `defence_terminal` or
`defence_ids_terminal` for the SSH grant (a key for the platform's jump host and the box behind it), and each
command then runs as `ssh -o ProxyCommand="ssh -W %h:%p jump@<jump>" <account>@<box> <command>`, the learner
account on the attacker box or `analyst` on the WAF or the sensor's host. The answer is `{operation, ok, exit_code, stdout, stderr}`, or `timed_out` when
the command outlasts `timeout` (default 120 seconds). Each command is a new login, so `cd` and variables do
not carry over.

The grant is kept for the run (`run`), and dropped when ssh itself fails (exit 255) so the next command asks
for a new one. `call` and the one-line form are one process each, so each of them asks for a new grant, which
replaces the one before. The bot needs `ssh` on its path and a route to the jump host; without `ssh`
the answer is local, with the code `ssh_unavailable`.

On the WAF, `analyst` can write the WAF files and run `sudo nginx -t`, `sudo nginx -T` and
`sudo systemctl reload nginx`. The reload loads only files a passing `defence_waf_test` of the round named,
and is recorded as the next WAF version on the next API request, like a human's reload in the terminal.

On the sensor's host, `analyst` can write the rule file the topology names, read the eve log and run the rule
test and the rule reload under sudo (`sudo -l` lists them); the IDS rules have no write API. The reload loads
only a file a passing `defence_ids_test` named and refuses rules that carry `config: logging`; a reload is
recorded as the next IDS version on the next API request.

## Plugging in a model

`run` takes `--provider package.module:factory`. The factory takes no arguments and returns an object with
`turn(system, tools, transcript) -> bots.provider.Turn`. `tools` is the side's tool spec list
(`{name, description, input_schema}`), and `transcript` is a list of plain entries:

- `{"role": "user", "text"}`: the opening, which carries the player's state;
- `{"role": "assistant", "text", "calls": [{"id", "name", "arguments"}]}`: what the provider answered;
- `{"role": "tool", "call_id", "name", "result"}`: the answer of each call.

The provider turns these into its model's own message format. A `Turn` with no calls ends the run; so does
`--turns`. Each entry is printed as one JSON line as it happens.

## Origins

The attacker plays from a set of source addresses (origins). An origin is spent when the WAF's nginx error log
names it in an `access forbidden by rule` line (a `deny`) or a `limiting requests` line (a limit_req). A CRS
rule's 403 does not spend it. A rate limit below twice the busiest benign customer's per-origin rate spends
nothing, and the defender is warned instead (`limit.below_floor`); so does a zone keyed by anything but the
client address (`limit.shared_key`).

Every successful attack answer carries `remaining: {origin: {id, label, ip}, left, total, spent}`, and every
attack answer, errors included, the headers `X-Origin` and `X-Origins-Left`. A spent origin is dropped at the
infra edge, open connections included, its tool runs stop, and the player moves to the next origin. The bot
may leave an origin early with `attack_next_origin`. The error log is read when the next API call for the
round comes in, so a spend shows a moment after the request that caused it. When `left` is 0 every attack
write answers `409 origins_spent` and the round ends.

## The attack baseline and what is scored

The attack bot's baseline is firing the declared cases with `attack_fire_case`. Declared cases and the benign
cases the platform fires are the only actions that enter TP/FP/FN/TN, one decision per case however many
alerts it draws. Free actions (`attack_send`, tool runs, shell traffic) are attributed by source address and
time and are never scored as TP/FP/FN/TN; they appear under `free_actions` in the score. Objectives are lost
only when the target's own data says so.

## The launcher

A seat made with `{bot: {step}}` is played by the `bots` compose service (`python -m bots.launcher`). It polls
`bot_run_claim` with the launcher key (`/run/secrets/bots_launcher_key`), which answers with the round, the side, a
fresh player token, the step's model, budget, turn cap, pace and allowance, for defence the watch interval (`watch_s`) and, for attack, the card. Per run it
starts a relay on `127.0.0.1` and Claude Code behind it. The child gets the relay's address as `CR_PLATFORM_URL` and a
random run key as `CR_PLAYER_TOKEN`; only the relay holds the player token and swaps it in, so a call that goes
around the relay reaches the platform with the run key and is refused. The relay forwards everything else unchanged.
A call past the step's pace answers `429` with the code `pace_limited` and `params.retry_after_s`; an operation or a
declared case the step does not give answers `403` with the code `not_at_this_step`. Neither reaches the platform. An
action is every call that is not a `GET`, and the three terminal grants; forfeit and the allocation heartbeat are never held back.
`bots.cli tools` hides the operations the step does not give (`CR_BOT_OPERATIONS`).

Claude Code runs in print mode with stream-json input: the launcher writes the system text, then the opening as
one user message. An attack run's stdin is closed after the opening, so the run ends when its turn does. A defence
run stays open until the round ends: every `watch_s` seconds of its step (75, 30 and 10 at steps 1 to 3), while
the model is between turns, the launcher reads `defence_state`, `defence_alerts` and `defence_traffic` with the
player token and its own cursors and, when there is a new alert, a refusal, a source address not fed before or a
change of phase, sends one more user message listing them (at most 20 alerts and 20 addresses, with how many
more). Each check is timed from the start of the one before, so the cadence holds; it has 80% of the interval
for its reads, each read at most 5 s and no longer than what is left, and a read past that time is not sent.
A read that fails or is not sent ends that check without moving the cursors, so the next check reads the same
alerts again. Every check writes one line to the launcher log (`run <n>: watch check <s> s of <budget> s:` then
each read with `200` or `failed (<why>)`, secrets masked). A turn's end does not end the run. When the phase is `ended` it sends a last message saying to read
`round_score` and closes stdin. The run also ends when the step's turns (counted across messages) or budget are
spent (`error_max_turns`, `error_max_budget_usd`).

Claude Code has Bash and Write as its only tools. Bash is allowed only `python -m bots.cli` and
`sleep`; Write only `.json` files at the top of its working directory (`Edit(/*.json)`), so arguments holding a quote reach
the CLI through `--json-file` and never through the shell's quoting (a raw `'` inside a single-quoted `--json`
leaves the command unparsed, and Claude Code refuses it). It runs with the read-only commands that could reach a
file or the environment denied, in `--safe-mode` with no setting sources,
from an empty working directory and a configuration directory of its own. One setting is passed on the command
line: `bashOutputMaxChars` 128000, so an answer such as `defence_waf` (about 42 KB) comes back inline; past
Claude Code's default of 30,000 characters it is saved to a file the child cannot read, since every file-reading
command is denied. So no CLAUDE.md, auto-memory, hooks,
skills or MCP servers reach it, and it never sees a checkout. The image holds `bots/` and `openapi/schema.yaml` only;
no cases, `expect` strings, target source or WAF roles are in it. The launcher runs as `launcher` and alone reads
the secrets; each child runs as one of `bot0`..`bot7`, its own uid with its own home, so one bot cannot read another
run's key. The Claude Code credential is `/run/secrets/claude_oauth_token`, passed to the child as
`CLAUDE_CODE_OAUTH_TOKEN`; with no credential or no key the launcher claims nothing. The bot's text, its calls,
permission denials, relay refusals, the model Claude Code started on and each safeguard stop (Claude Code's
"safeguards stopped the response" notice, and a `model_refusal_fallback` with the model it fell back to) are
reported as notes (`bot_run_report`) with the player token, the run key,
the credential and any `sk-ant-` string masked, and the closing text, cost, turns and refusal count with
`bot_run_finish`. A run that outlasts `CR_BOT_RUN_SECONDS` (two hours) is stopped as `timed_out`: SIGTERM, which
`sudo` passes on, then after 15 s SIGKILL to every process of the run's `botN` uid; a launcher that
restarts marks the runs it held `launcher_restarted`. `CR_BOT_RUNS_MAX` (2) runs at once.

Only accounts named in the platform's `CR_BOT_ROUND_USERS` may open a round with a launched bot
(`bot_rounds_closed` otherwise), while the bots run on one person's Claude Code login.

The service reaches the platform as `http://platform:8000`, so the platform's `DJANGO_ALLOWED_HOSTS` names
`platform` (the platform stack writes it); without it every claim answers `400` and no bot starts.

## Errors

Every refusal is `{errors: [{path, code, line?, params?}]}`. Codes a bot meets:

| Code | Status | Meaning |
|---|---|---|
| `not_signed_in` | 401 | no or unknown player token |
| `not_a_player` | 403 | the token is not a player of this side of this round |
| `invalid`, `required`, `max_length`, `invalid_choice`, ... | 400 | a field error at `path` |
| `unknown_case`, `unknown_tool`, `unknown_run` | 404 | no such declared case, tool or tool run |
| `round_not_started` | 409 | the round is not running yet |
| `round_closed` | 409 | the round has ended; reads still work for 15 minutes |
| `round_running` | 409 | the score is read only after the end |
| `origins_spent` | 409 | every attack origin is spent |
| `stale_version` | 409 | `base_version` is not the applied version; `params` has the current one |
| `test_busy` | 409 | another rule test of this engine is running |
| `not_tested` | 409 | no rule test of this round passed with the same WAF files |
| `suricata_syntax` | 422 | the Suricata text was refused, with `line` |
| `crs_refused`, `apply_refused` | 422 | the WAF files or the apply was refused |
| `attacker_unavailable`, `tool_unavailable`, `range_unavailable` | 503 | the attacker box or the range is not answering |
| `sensor_unavailable`, `waf_unavailable`, `elastic_unavailable` | 503 | a sensor, the WAF or the alert store is not answering |
