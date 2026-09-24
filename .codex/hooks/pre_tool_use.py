#!/usr/bin/env python3
"""Codex PreToolUse hook: 위험한 셸 명령을 차단한다 (.claude/settings.json 훅과 같은 패턴)."""

import json
import re
import sys

DANGEROUS = re.compile(r"rm\s+-rf|git\s+push\s+--force|git\s+reset\s+--hard|DROP\s+TABLE")


def main() -> int:
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if isinstance(command, list):
        command = " ".join(command)
    if DANGEROUS.search(command):
        print("BLOCKED: 위험한 명령어가 감지되었습니다.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
