FSL_COMMAND_LOG=/var/log/fsl/commands.log
FSL_LABEL=/label/active

_fsl_record() {
  local status=$? number text
  read -r number text <<< "$(history 1)"
  if [ -z "$_FSL_STARTED" ]; then
    _FSL_STARTED=1
    _FSL_LAST=$number
    return $status
  fi
  if [ -n "$text" ] && [ "$number" != "$_FSL_LAST" ]; then
    _FSL_LAST=$number
    printf '%s\t%s\t%s\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      "$(cat "$FSL_LABEL" 2>/dev/null)" \
      "$text" >> "$FSL_COMMAND_LOG"
  fi
  return $status
}

PROMPT_COMMAND=_fsl_record
