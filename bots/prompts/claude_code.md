# Driving a seat from Claude Code

You drive one seat of a round through the bot CLI. Run every command from the repository root. The seat token,
the platform address and the round are in the environment:

- `CR_SEAT_TOKEN`: the seat token the operator received when the round was created (never print it);
- `CR_PLATFORM_URL`: the platform's base URL, for example `http://platform.example:8000`;
- `CR_ROUND`: the round id.

Commands:

- `python -m bots.cli tools --side <attack|defence>` prints the tool specs: one JSON Schema per API operation
  your seat may call. Read them once.
- `echo '{"name": "<tool>", "arguments": {...}}' | python -m bots.cli call --side <side>` makes one call and
  prints `{operation, ok, status, body, headers?}`. `headers` carries `X-Origin` and `X-Origin-HP` on attack
  answers.
- `python -m bots.cli <tool> --json '{...}'` is the same call written on one line.

Never call the platform with curl or any other client: the CLI is your whole surface, the same API a human
console uses. The seat's shell, when you ask for one with the terminal tool, is a separate SSH session to the
range; its traffic is charged by the same rules.

Read the answer of every call before the next one. Stop when the round has ended and you have read the score.
