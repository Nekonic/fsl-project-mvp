__log_command() {
  local status=$? number text
  read -r number text <<< "$(history 1)"
  if [ -z "$__log_started" ]; then
    __log_started=1
    __log_last=$number
    return $status
  fi
  if [ -n "$text" ] && [ "$number" != "$__log_last" ]; then
    __log_last=$number
    printf '%s\t%s\t%s\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      "$(cat /var/lib/session/active 2>/dev/null)" \
      "$text" >> /var/log/commands.log
  fi
  echo
  return $status
}

PROMPT_COMMAND=__log_command
