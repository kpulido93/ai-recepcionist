from __future__ import annotations

from io import StringIO

from vicidial_vosk_cobranza_ivr.agi_runtime import (
    AgiSession,
    _read_agi_environment,
    sanitize_agi_value,
)
from vicidial_vosk_cobranza_ivr.app import (
    _safe_write_error_result,
    _write_agi_result,
    agi_set_variable,
)


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def set_variable(self, name: str, value: str) -> str:
        self.calls.append((name, value))
        return "200 result=1"


def test_read_agi_environment_parses_dtmf_argument() -> None:
    stdin = StringIO(
        "agi_callerid: 3001234567\n"
        "agi_channel: SIP/test-00000001\n"
        "agi_uniqueid: 1716123456.12\n"
        "agi_arg_1: 1\n\n"
    )

    environment = _read_agi_environment(stdin)

    assert environment["agi_callerid"] == "3001234567"
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


def test_agi_set_variable_removes_crlf_from_value() -> None:
    stdin = StringIO("200 result=1\n")
    stdout = StringIO()
    session = AgiSession(stdin=stdin, stdout=stdout)

    agi_set_variable(session, "VOSK_TEXT", "uno\r\ndos\rtres\n")

    assert stdout.getvalue() == 'SET VARIABLE VOSK_TEXT "uno dos tres"\n'


def test_get_variable_reads_channel_variable_value() -> None:
    stdin = StringIO("200 result=1 (Banco Popular)\n")
    stdout = StringIO()
    session = AgiSession(stdin=stdin, stdout=stdout)

    value = session.get_variable("IVR_BANK_NAME")

    assert value == "Banco Popular"
    assert stdout.getvalue() == "GET VARIABLE IVR_BANK_NAME\n"


def test_get_variable_returns_none_when_channel_variable_is_missing() -> None:
    stdin = StringIO("200 result=0\n")
    stdout = StringIO()
    session = AgiSession(stdin=stdin, stdout=stdout)

    value = session.get_variable("IVR_BANK_NAME")

    assert value is None
    assert stdout.getvalue() == "GET VARIABLE IVR_BANK_NAME\n"


def test_write_agi_result_sets_all_vosk_variables() -> None:
    session = FakeSession()

    result = _write_agi_result(
        session=session,
        channel_variable_name="VOSK_INTENT",
        intent="SI",
        text="si quiero hablar",
        confidence="0.91",
        source="speech",
    )

    assert result is True
    assert session.calls == [
        ("VOSK_TEXT", "si quiero hablar"),
        ("VOSK_INTENT", "SI"),
        ("VOSK_CONFIDENCE", "0.91"),
        ("VOSK_SOURCE", "speech"),
    ]


def test_safe_write_error_result_does_not_crash_when_stdin_is_closed() -> None:
    session = AgiSession(stdin=StringIO(""), stdout=StringIO())

    _safe_write_error_result(session)


def test_sanitize_agi_value_truncates_to_safe_limit() -> None:
    sanitized = sanitize_agi_value("a" * 3000)

    assert len(sanitized) == 2048
