from __future__ import annotations

import re
import sys
from typing import TextIO

RESULT_PATTERN = re.compile(r"result=(-?\d+)(?:\s+\((.*)\))?")


class AgiIoError(RuntimeError):
    """Raised when Asterisk closes the AGI stream or stdio becomes unavailable."""


class AgiSession:
    def __init__(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        self.stdin = stdin
        self.stdout = stdout

    def read_environment(self) -> dict[str, str]:
        return _read_agi_environment(self.stdin)

    def command(self, command_line: str) -> str:
        try:
            self.stdout.write(f"{command_line}\n")
            self.stdout.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise AgiIoError("No fue posible escribir en stdout AGI.") from exc

        try:
            response = self.stdin.readline()
        except (OSError, ValueError) as exc:
            raise AgiIoError("No fue posible leer la respuesta AGI.") from exc

        if response == "":
            raise AgiIoError("Asterisk cerro el stream AGI.")

        return response.strip()

    def set_variable(self, name: str, value: str) -> str:
        escaped_value = sanitize_agi_value(value)
        return self.command(f'SET VARIABLE {name} "{escaped_value}"')

    def get_variable(self, name: str) -> str | None:
        response = self.command(f"GET VARIABLE {name}")
        result, value = parse_agi_response(response)
        if result != "1":
            return None
        if value is None:
            return None
        return value

    def verbose(self, message: str, level: int = 1) -> None:
        escaped_message = sanitize_agi_value(message)
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
    result, _ = parse_agi_response(response)
    return result


def parse_agi_response(response: str) -> tuple[str | None, str | None]:
    match = RESULT_PATTERN.search(response)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _read_agi_environment(stdin: TextIO) -> dict[str, str]:
    environment: dict[str, str] = {}

    while True:
        try:
            line = stdin.readline()
        except (OSError, ValueError) as exc:
            raise AgiIoError("No fue posible leer el entorno AGI.") from exc

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


def sanitize_agi_value(value: str, max_length: int = 2048) -> str:
    compact = value.replace("\\", "\\\\").replace('"', '\\"')
    compact = compact.replace("\r", " ").replace("\n", " ")
    compact = " ".join(compact.split())
    return compact[:max_length]
