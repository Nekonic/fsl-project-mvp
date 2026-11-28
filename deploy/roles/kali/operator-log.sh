__log_mark() {
  if [ -n "$__log_armed" ] && [ "$BASH_COMMAND" != __log_command ]; then
    __log_armed=
    __log_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  fi
}

__log_command() {
  local status=$? number text
  read -r number text <<< "$(history 1)"
  if [ -z "$__log_started" ]; then
    __log_started=1
    __log_last=$number
    __log_at=
    __log_armed=1
    return $status
  fi
  if [ -n "$text" ] && [ "$number" != "$__log_last" ]; then
    __log_last=$number
    printf '%s\t%s\t%s\n' \
      "${__log_at:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}" \
      "$(cat /var/lib/session/active 2>/dev/null || sudo -n cat /var/lib/session/active 2>/dev/null)" \
      "$text" >> /var/log/commands.log
  fi
  __log_at=
  __log_armed=1
  echo
  return $status
}

trap __log_mark DEBUG
PROMPT_COMMAND=__log_command
