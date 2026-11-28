#!/bin/sh

facts="${CR_WORK_DIR:-$HOME/.cache/fsl-work}/facts.txt"
oldest_minutes=30
payload="$(cat)"

deny() {
  jq -cn --arg reason "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
  exit 0
}

if command -v jq >/dev/null 2>&1; then
  brief="$(printf '%s' "$payload" | jq -r '[.tool_input.prompt, .tool_input.script, .tool_input.description] | map(select(. != null) | tostring) | join("\n")' 2>/dev/null)"
  if [ ! -f "$facts" ]; then
    deny "No $facts. Run bin/facts first, read what it printed, and name facts.txt in the brief (quote the lines the delegated work depends on)."
  fi
  if [ -n "$(find "$facts" -mmin +"$oldest_minutes" 2>/dev/null)" ]; then
    deny "$facts is older than $oldest_minutes minutes. Run bin/facts again, then write the brief from what it prints, naming facts.txt."
  fi
  case "$brief" in
    *facts.txt*) ;;
    *) deny "The brief does not name facts.txt. Every fact a brief gives (what dev holds, what the VM runs, slot states, settings) comes from $facts, written by bin/facts in the last $oldest_minutes minutes; name the file and quote the lines used." ;;
  esac
fi

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"Before this delegation, check the brief against the mistakes the user has caught: (1) Live scope: every live step names the changed file that needs it; acceptance only the modules `bin/verify --changed --live` lists; one live round per behaviour the change adds; nothing a unit test already proves; no second round to see a parameter. (1b) While fixing, run only bin/verify --changed; full acceptance runs once, after a review round finds nothing; any step over an hour is an error to stop and diagnose, so the final check runs only --changed --live modules. (2) Every fact in the brief (what a doc says, what a branch holds, what the cloud runs) was read this session from origin, not recalled. (3) No SendMessage to a workflow agent; to change a running workflow, stop it only when no replace or bake is mid-way. (4) The user's own words decide; no CVP or account tier. If the brief breaks one, rewrite it before sending."}}
JSON
