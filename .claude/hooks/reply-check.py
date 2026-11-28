#!/usr/bin/env python3

import json
import os
import re
import sys
from pathlib import Path

WORDS = Path(os.environ.get("CR_WORK_DIR") or Path.home() / ".cache/fsl-work") / "asked-words.txt"
TAIL_BYTES = 400_000
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
QUESTION_ENDINGS = re.compile(r"(까요|습니까|인가요|은가요|는가요)(?![가-힣])")
ASKING_FOR = re.compile(r"주세요[^\n]*[?？]|[?？][^\n]*주세요")
PARTS = {
    "무엇인지": re.compile(r"무엇|질문|결정할 것|정할 것|고를 것|선택지"),
    "영향": re.compile(r"영향|효과|바뀌는 것|달라지는 것|결과"),
    "추천": re.compile(r"추천|권장|제안|권고"),
    "답이 없으면": re.compile(r"(답|응답|대답|회신)(이|을)? ?없으면|답하지 않으면|말씀이 없으면"),
}
INSTRUCTION = (
    "답장이 사용자에게 묻는데 다음이 빠졌습니다: {missing}. 물을 때는 한 번에 네 가지를 씁니다: "
    "무엇을 정하는지, 그 선택의 영향, 추천안, 답이 없으면 어떻게 진행하는지. CLAUDE.md의 'Do not ask' 목록에 "
    "드는 일이면 묻지 말고 직접 정해 진행합니다. 답장을 고쳐 다시 쓰세요."
)
UNEXPLAINED = (
    "답장이 사용자가 뜻을 물었던 말 {words}을(를) 풀이 없이 씁니다(~/.cache/fsl-work/asked-words.txt). "
    "같은 답장 안에서 무엇을 가리키는지 풀어 쓰거나, 그 말 대신 뜻을 쓰세요."
)


def last_reply(payload: dict) -> str:
    if isinstance(payload.get("last_assistant_message"), str):
        return payload["last_assistant_message"]
    path = Path(payload.get("transcript_path") or "")
    with path.open("rb") as transcript:
        transcript.seek(max(0, path.stat().st_size - TAIL_BYTES))
        lines = transcript.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") or {}
        if entry.get("type") != "assistant" or message.get("role") != "assistant":
            continue
        content = message.get("content")
        texts = [content] if isinstance(content, str) else [
            block.get("text", "") for block in content or [] if isinstance(block, dict) and block.get("type") == "text"]
        text = "\n".join(texts).strip()
        if text:
            return text
    return ""


def asks(prose: str) -> bool:
    stripped = prose.rstrip()
    return (stripped.endswith(("?", "？")) or bool(QUESTION_ENDINGS.search(prose))
            or bool(ASKING_FOR.search(prose)))


def missing_parts(prose: str) -> list[str]:
    return [name for name, pattern in PARTS.items() if not pattern.search(prose)]


def explained(word: str, prose: str) -> bool:
    quoted = re.escape(word)
    return bool(re.search(
        rf"{quoted}['\"”’]?\s*(\(|:|—|=)"
        rf"|{quoted}['\"”’]?(이?란|이라는 것은|은|는|이라 함은)\s[^.\n]{{0,80}}(뜻|말합니다|가리킵니다|의미|것입니다|것이다)",
        prose))


def unexplained_words(prose: str, words: list[str]) -> list[str]:
    return [word for word in words if word in prose and not explained(word, prose)]


def asked_words(path: Path = WORDS) -> list[str]:
    try:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


def verdict(reply: str, words: list[str]) -> str:
    prose = CODE.sub("", reply)
    if asks(prose):
        missing = missing_parts(prose)
        if missing:
            return INSTRUCTION.format(missing=", ".join(missing))
    unexplained = unexplained_words(prose, words)
    if unexplained:
        return UNEXPLAINED.format(words=", ".join(f"'{word}'" for word in unexplained))
    return ""


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if payload.get("stop_hook_active"):
            return 0
        reason = verdict(last_reply(payload), asked_words())
    except Exception:
        return 0
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
