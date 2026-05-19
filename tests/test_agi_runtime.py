from __future__ import annotations

from io import StringIO

from vicidial_vosk_cobranza_ivr.agi_runtime import (
    AgiSession,
    _read_agi_environment,
    sanitize_agi_value,
)
from vicidial_vosk_cobranza_ivr.app import agi_set_variable


def test_read_agi_environment_parses_dtmf_argument() -> None:
    stdin = StringIO(
        "agi_channel: SIP/test-00000001\nagi_uniqueid: 1716123456.12\nagi_arg_1: 1\n\n"
    )

    environment = _read_agi_environment(stdin)

    assert environment["agi_channel"] == "SIP/test-00000001"
    assert environment["agi_uniqueid"] == "1716123456.12"
    assert environment["agi_arg_1"] == "1"


def test_read_agi_environment_allows_missing_dtmf_argument() -> None:
    stdin = StringIO("agi_channel: SIP/test-00000002\nagi_uniqueid: 1716123456.13\n\n")

    environment = _read_agi_environment(stdin)

    assert "agi_arg_1" not in environment


def test_agi_set_variable_escapes_quotes_backslashes_and_newlines() -> None:
    stdin = StringIO("200 result=1\n")
    stdout = StringIO()
    session = AgiSession(stdin=stdin, stdout=stdout)

    response = agi_set_variable(
        session,
        "VOSK_TEXT",
        'hola "mundo"\nlinea dos\\final',
    )

    assert response == "200 result=1"
    assert stdout.getvalue() == 'SET VARIABLE VOSK_TEXT "hola \\"mundo\\" linea dos\\\\final"\n'


def test_sanitize_agi_value_truncates_to_safe_limit() -> None:
    sanitized = sanitize_agi_value("a" * 3000)

    assert len(sanitized) == 2048
