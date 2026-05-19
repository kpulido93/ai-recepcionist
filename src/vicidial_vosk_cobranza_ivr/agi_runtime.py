from __future__ import annotations

import re
import sys
from typing import TextIO

RESULT_PATTERN = re.compile(r"result=(-?\d+)(?:\s+\((.*)\))?")


class AgiSession:
    def __init__(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        self.stdin = stdin
        self.stdout = stdout

    def read_environment(self) -> dict[str, str]:
        environment: dict[str, str] = {}

        while True:
            line = self.stdin.readline()
            if line == "":
                break

            stripped = line.rstrip("\n")
            if not stripped:
                break

            if ":" not in stripped:
                continue

            key, value = stripped.split(":", 1)
            environment[key.strip()] = value.strip()

        return environment

    def command(self, command_line: str) -> str:
        self.stdout.write(f"{command_line}\n")
        self.stdout.flush()
        return self.stdin.readline().strip()

    def set_variable(self, name: str, value: str) -> None:
        escaped_value = value.replace('"', '\\"')
        self.command(f'SET VARIABLE {name} "{escaped_value}"')

    def verbose(self, message: str, level: int = 1) -> None:
        escaped_message = message.replace('"', '\\"')
        self.command(f'VERBOSE "{escaped_message}" {level}')

    def wait_for_digit(self, timeout_ms: int) -> str | None:
        response = self.command(f"WAIT FOR DIGIT {timeout_ms}")
        result = parse_agi_result(response)
        if result in (None, "", "0"):
            return None

        assert result is not None
        digit_result = result
        if digit_result.isdigit() and int(digit_result) > 9:
            try:
                return chr(int(digit_result))
            except ValueError:
                return None

        return digit_result


def parse_agi_result(response: str) -> str | None:
    match = RESULT_PATTERN.search(response)
    if not match:
        return None
    return match.group(1)
