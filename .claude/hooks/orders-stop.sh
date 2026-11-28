#!/bin/sh

root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
payload="$(cat)"
case "$payload" in
  *'"stop_hook_active":true'*|*'"stop_hook_active": true'*) exit 0 ;;
esac
python="$root/.venv/bin/python"
[ -x "$python" ] || python=python3
said="$(timeout 15 "$python" "$root/bin/orders-check" --fast 2>&1)"
code=$?
[ "$code" = 1 ] || exit 0
failing="$(printf '%s\n' "$said" | grep -E '\| (fail|검사 없음)' ; printf '%s\n' "$said" | tail -1)"
jq -cn --arg reason "user-orders.md에 끝남으로 적은 줄의 검사가 실패합니다. 끝내기 전에 고치거나 상태를 진행으로 되돌리고 이유를 보고하세요:
$failing" '{decision:"block",reason:$reason}' 2>/dev/null || exit 0
