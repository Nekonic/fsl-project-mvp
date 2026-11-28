#!/bin/sh
cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"The user's message decides. (1) If it asks a question, answer it in text first, short, before any tool call. (2) If the user interrupted or rejected a tool call, do not run that call again; answer and wait. (3) Do only what the message asks; no extra steps."}}
JSON
