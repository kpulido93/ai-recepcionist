from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from vicidial_vosk_cobranza_ivr.reporting import (
    append_final_call_event,
    build_final_call_event,
    load_final_call_events,
    map_intent_to_state,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "report_ivr_calls.py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_SPEC = importlib.util.spec_from_file_location("scripts_report_ivr_calls", SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
report_ivr_calls = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = report_ivr_calls
_SPEC.loader.exec_module(report_ivr_calls)


def test_map_intent_to_state_uses_expected_level1_contract() -> None:
    expected = {
        "SI": "TRANSFERIR_A_ABOGADO",
        "INFO_COBRO": "TRANSFERIR_A_ABOGADO",
        "PROMESA_PAGO": "TRANSFERIR_A_ABOGADO",
        "NO": "NO_INTERESADO",
        "CALLBACK": "LLAMAR_DESPUES",
        "NUMERO_EQUIVOCADO": "NUMERO_EQUIVOCADO",
        "NO_ES_PERSONA": "NO_ES_PERSONA",
        "DUDA": "NO_ENTENDIDO",
        "SILENCIO": "SIN_RESPUESTA",
    }

    assert {intent: map_intent_to_state(intent) for intent in expected} == expected


def test_append_final_call_event_masks_sensitive_fields(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    event = build_final_call_event(
        timestamp=datetime(2026, 5, 20, 14, 0, tzinfo=timezone.utc),
        uniqueid="1716123456.321",
        channel="SIP/3001234567-00000001",
        caller="3001234567",
        intent="CALLBACK",
        confidence=0.8,
        matched_phrase="llameme al 3001234567",
        text="llameme al 3001234567",
        stop_reason="timeout",
        attempts=1,
        source="speech",
        mask_phone_numbers=True,
    )

    append_final_call_event(events_path, event)
    loaded_events = load_final_call_events(events_path)

    assert len(loaded_events) == 1
    assert loaded_events[0].caller == "XXXXXXXX67"
    assert "3001234567" not in loaded_events[0].channel
    assert loaded_events[0].matched_phrase == "llameme al XXXXXXXX67"
    assert loaded_events[0].text == "llameme al XXXXXXXX67"
    assert loaded_events[0].state == "LLAMAR_DESPUES"


def test_report_script_filters_by_date_and_deduplicates_by_uniqueid(
    tmp_path: Path,
    capsys,
) -> None:
    events_path = tmp_path / "events.jsonl"
    append_final_call_event(
        events_path,
        build_final_call_event(
            timestamp=datetime(2026, 5, 20, 8, 0, tzinfo=timezone.utc),
            uniqueid="call-1",
            channel="SIP/test-1",
            caller="3001234567",
            intent="SI",
            confidence=0.9,
            matched_phrase="si",
            text="si",
            stop_reason="early_intent",
            attempts=1,
            source="speech",
            mask_phone_numbers=False,
        ),
    )
    append_final_call_event(
        events_path,
        build_final_call_event(
            timestamp=datetime(2026, 5, 20, 8, 3, tzinfo=timezone.utc),
            uniqueid="call-1",
            channel="SIP/test-1",
            caller="3001234567",
            intent="NO",
            confidence=0.95,
            matched_phrase="no",
            text="no",
            stop_reason="silence_after_speech",
            attempts=2,
            source="speech",
            mask_phone_numbers=False,
        ),
    )
    append_final_call_event(
        events_path,
        build_final_call_event(
            timestamp=datetime(2026, 5, 21, 9, 0, tzinfo=timezone.utc),
            uniqueid="call-2",
            channel="SIP/test-2",
            caller="3007654321",
            intent="CALLBACK",
            confidence=0.8,
            matched_phrase="llameme despues",
            text="llameme despues",
            stop_reason="timeout",
            attempts=1,
            source="speech",
            mask_phone_numbers=False,
        ),
    )

    exit_code = report_ivr_calls.main(
        [
            "--input",
            str(events_path),
            "--date",
            "2026-05-20",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "events_read: 3" in captured.out
    assert "calls_after_dedup: 2" in captured.out
    assert "calls_in_report: 1" in captured.out
    assert "NO: 1" in captured.out
    assert "SI: 1" not in captured.out
    assert "NO_INTERESADO: 1" in captured.out


def test_report_script_exports_csv_and_json(tmp_path: Path, capsys) -> None:
    events_path = tmp_path / "events.jsonl"
    csv_path = tmp_path / "daily.csv"
    json_path = tmp_path / "daily.json"
    append_final_call_event(
        events_path,
        build_final_call_event(
            timestamp=datetime(2026, 5, 22, 10, 30, tzinfo=timezone.utc),
            uniqueid="call-9",
            channel="SIP/test-9",
            caller="3001234567",
            intent="INFO_COBRO",
            confidence=0.88,
            matched_phrase="cuanto debo",
            text="cuanto debo",
            stop_reason="silence_after_speech",
            attempts=1,
            source="speech",
            mask_phone_numbers=False,
        ),
    )

    exit_code = report_ivr_calls.main(
        [
            "--input",
            str(events_path),
            "--all",
            "--csv",
            str(csv_path),
            "--json",
            str(json_path),
        ]
    )

    captured = capsys.readouterr()
    csv_content = csv_path.read_text(encoding="utf-8")
    json_payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "csv:" in captured.out
    assert "json:" in captured.out
    assert csv_path.exists()
    assert "uniqueid,intent,state" not in csv_content
    assert "call-9" in csv_content
    assert "INFO_COBRO" in csv_content
    assert "TRANSFERIR_A_ABOGADO" in csv_content
    assert json_payload["calls_counted"] == 1
    assert json_payload["by_intent"] == {"INFO_COBRO": 1}
    assert json_payload["by_state"] == {"TRANSFERIR_A_ABOGADO": 1}
