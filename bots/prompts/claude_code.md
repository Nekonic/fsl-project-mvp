# Driving a player from Claude Code

You drive one player of a round through the bot CLI. Run every command from the working directory you start in. The
player's key, the platform address and the round are in the environment:

- `CR_PLAYER_TOKEN`: your player's key (never print it);
- `CR_PLATFORM_URL`: the platform's base URL;
- `CR_ROUND`: the round id.

Commands:

- `python -m bots.cli tools --side <attack|defence>` prints the tool specs: one JSON Schema per API operation
  your player may call. Read them once.
- `python -m bots.cli <tool> --json '{...}'` (or `--json-file call.json`, below) makes one call and prints `{operation, ok, status, body, headers?}`.
  `headers` carries `X-Origin` and `X-Origins-Left` on attack answers. The `shell` tool is on both sides, so name
  the side: `python -m bots.cli shell --side defence --json '{"command": "sudo nginx -t"}'` prints
  `{operation, ok, exit_code, stdout, stderr}`.
- `sleep <seconds>` waits.

Write each call as one command on its own line: no pipe, no `&&`, `;` or `$(...)` around it, and no other program.
Anything else is refused before it runs. When a value holds a quote of
either kind, keep the arguments off the command line: write the JSON object with the Write tool to `call.json` in
your working directory, then run `python -m bots.cli <tool> --json-file call.json`. Write may change that one file
and no other. A refused command sent
nothing; write it again as one plain call and carry on, the round is not over. An answer longer than the tool's
window is saved to a file you cannot open; ask again with fewer items (a later `after` cursor, a narrower query).
Never run a command in the background: its output goes to a file you cannot open.
Never call the platform with curl or any other client: the CLI is your whole surface, the same API and the same
shell a human player uses. `shell` asks the platform for the terminal's SSH grant and runs the command over the
platform's jump host; each CLI call asks for a new grant, which replaces the one before.
Shell traffic from the attacker box can spend an origin by the same rules.

Before each action, read `round_events` after the last `next` cursor you were given, and what your side watches
(`defence_alerts` and `defence_traffic`, or the `remaining` block), and act on what changed since your last action.
Reads never count against your pace.

Your difficulty step sets a pace and the operations you have. An action is every call that changes something (fire
a case, send, start or stop a tool, loot, move to the next origin, check, test or apply rules) and every terminal
grant, so each shell command is one action; forfeit is never held back. A call past the pace answers `429` with the
code `pace_limited` and `params.retry_after_s`: nothing was sent, so wait that long and call again. A call your
step does not give answers `403` with the code `not_at_this_step`: nothing was sent and it will not change this
round, so do something else.

Read the answer of every call before the next one. When the round has ended and you have read `round_score` until
`pending` is false, end with your intent: what you aimed at and why, in at most ten lines, as your last message. Then
stop.
