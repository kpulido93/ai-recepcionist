from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from vicidial_vosk_cobranza_ivr.intent_classifier import intent_value, resolve_intent_name
from vicidial_vosk_cobranza_ivr.logging_utils import mask_sensitive_data

INTENT_STATE_MAP: dict[str, str] = {
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
INTENT_REPORT_ORDER: tuple[str, ...] = tuple(INTENT_STATE_MAP)
STATE_REPORT_ORDER: tuple[str, ...] = (
    "TRANSFERIR_A_ABOGADO",
    "NO_INTERESADO",
    "LLAMAR_DESPUES",
    "NUMERO_EQUIVOCADO",
    "NO_ES_PERSONA",
    "NO_ENTENDIDO",
    "SIN_RESPUESTA",
)
CSV_FIELDNAMES: tuple[str, ...] = (
    "timestamp",
    "uniqueid",
    "channel",
    "caller",
    "intent",
    "state",
    "confidence",
    "matched_phrase",
    "text",
    "stop_reason",
    "attempts",
    "source",
)


@dataclass(frozen=True)
class FinalCallEvent:
    timestamp: str
    uniqueid: str
    channel: str
    caller: str
    intent: str
    state: str
    confidence: float
    matched_phrase: str | None
    text: str
    stop_reason: str
    attempts: int | None
    source: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def map_intent_to_state(intent: str) -> str:
    normalized_intent = intent_value(resolve_intent_name(intent))
    return INTENT_STATE_MAP.get(normalized_intent, "NO_ENTENDIDO")


def build_final_call_event(
    *,
    uniqueid: str,
    channel: str,
    caller: str,
    intent: str,
    confidence: float,
    matched_phrase: str | None,
    text: str,
    stop_reason: str,
    attempts: int | None,
    source: str,
    mask_phone_numbers: bool,
    timestamp: datetime | None = None,
) -> FinalCallEvent:
    normalized_intent = intent_value(resolve_intent_name(intent))
    event_timestamp = timestamp or datetime.now().astimezone()
    return FinalCallEvent(
        timestamp=event_timestamp.isoformat(timespec="seconds"),
        uniqueid=_compact_text(uniqueid),
        channel=_normalize_event_text(channel, mask_phone_numbers=mask_phone_numbers),
        caller=_normalize_event_text(caller, mask_phone_numbers=mask_phone_numbers),
        intent=normalized_intent,
        state=map_intent_to_state(normalized_intent),
        confidence=float(confidence),
        matched_phrase=_normalize_optional_text(
            matched_phrase,
            mask_phone_numbers=mask_phone_numbers,
        ),
        text=_normalize_event_text(text, mask_phone_numbers=mask_phone_numbers),
        stop_reason=_compact_text(stop_reason),
        attempts=attempts,
        source=_compact_text(source),
    )


def append_final_call_event(
    path: str | Path,
    event: FinalCallEvent,
    logger: logging.Logger | None = None,
) -> bool:
    target_path = Path(path).expanduser()
    if not str(target_path).strip() or str(target_path) == ".":
        return False

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("a", encoding="utf-8") as file_handler:
            file_handler.write(json.dumps(event.to_record(), ensure_ascii=False))
            file_handler.write("\n")
    except OSError as exc:
        if logger is not None:
            logger.warning(
                "No fue posible escribir evento JSONL del IVR en %s: %s",
                target_path,
                exc,
            )
        return False

    return True


def load_final_call_events(path: Path) -> list[FinalCallEvent]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo JSONL: {path}")

    events: list[FinalCallEvent] = []
    with path.open("r", encoding="utf-8") as file_handler:
        for line_number, raw_line in enumerate(file_handler, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                loaded = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Linea JSONL invalida #{line_number}: {exc}") from exc

            if not isinstance(loaded, dict):
                raise ValueError(f"Cada linea JSONL debe contener un objeto. Linea #{line_number}")

            events.append(_parse_final_call_event(loaded, line_number))

    return events


def deduplicate_final_call_events(events: list[FinalCallEvent]) -> list[FinalCallEvent]:
    latest_by_uniqueid: dict[str, tuple[int, FinalCallEvent]] = {}
    for index, event in enumerate(events):
        dedupe_key = event.uniqueid or f"missing-uniqueid-{index}"
        latest_by_uniqueid[dedupe_key] = (index, event)

    return [
        event
        for _, event in sorted(
            latest_by_uniqueid.values(),
            key=lambda item: item[0],
        )
    ]


def filter_events_by_date(
    events: list[FinalCallEvent],
    *,
    target_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[FinalCallEvent]:
    filtered: list[FinalCallEvent] = []
    for event in events:
        event_date = _parse_event_timestamp(event.timestamp).date()
        if target_date is not None and event_date != target_date:
            continue
        if date_from is not None and event_date < date_from:
            continue
        if date_to is not None and event_date > date_to:
            continue
        filtered.append(event)
    return filtered


def summarize_by_intent(events: list[FinalCallEvent]) -> dict[str, int]:
    return _ordered_counts(
        Counter(event.intent for event in events),
        INTENT_REPORT_ORDER,
    )


def summarize_by_state(events: list[FinalCallEvent]) -> dict[str, int]:
    return _ordered_counts(
        Counter(event.state for event in events),
        STATE_REPORT_ORDER,
    )


def export_events_csv(events: list[FinalCallEvent], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_handler:
        writer = csv.DictWriter(file_handler, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for event in events:
            writer.writerow(event.to_record())


def build_report_payload(
    *,
    source_path: Path,
    events: list[FinalCallEvent],
    target_date: date | None,
    date_from: date | None,
    date_to: date | None,
    include_all_dates: bool,
) -> dict[str, Any]:
    return {
        "source_path": str(source_path),
        "filters": {
            "date": target_date.isoformat() if target_date is not None else None,
            "from": date_from.isoformat() if date_from is not None else None,
            "to": date_to.isoformat() if date_to is not None else None,
            "all": include_all_dates,
        },
        "calls_counted": len(events),
        "by_intent": summarize_by_intent(events),
        "by_state": summarize_by_state(events),
        "calls": [event.to_record() for event in events],
    }


def write_report_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handler:
        json.dump(payload, file_handler, ensure_ascii=False, indent=2)
        file_handler.write("\n")


def _parse_final_call_event(record: dict[str, Any], line_number: int) -> FinalCallEvent:
    attempts = record.get("attempts")
    if attempts in ("", None):
        parsed_attempts: int | None = None
    else:
        try:
            parsed_attempts = int(str(attempts))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"attempts invalido en linea #{line_number}: {attempts!r}") from exc

    matched_phrase = record.get("matched_phrase")
    if matched_phrase is not None:
        matched_phrase = str(matched_phrase)

    return FinalCallEvent(
        timestamp=_required_str(record, "timestamp", line_number),
        uniqueid=_required_str(record, "uniqueid", line_number),
        channel=_required_str(record, "channel", line_number),
        caller=_required_str(record, "caller", line_number),
        intent=_required_str(record, "intent", line_number),
        state=_required_str(record, "state", line_number),
        confidence=float(record.get("confidence", 0.0)),
        matched_phrase=matched_phrase,
        text=_required_str(record, "text", line_number),
        stop_reason=_required_str(record, "stop_reason", line_number),
        attempts=parsed_attempts,
        source=_required_str(record, "source", line_number),
    )


def _required_str(record: dict[str, Any], key: str, line_number: int) -> str:
    value = record.get(key)
    if value is None:
        raise ValueError(f"Falta el campo '{key}' en la linea #{line_number}")
    return str(value)


def _parse_event_timestamp(value: str) -> datetime:
    normalized_value = value.strip()
    if normalized_value.endswith("Z"):
        normalized_value = normalized_value[:-1] + "+00:00"
    return datetime.fromisoformat(normalized_value)


def _ordered_counts(counter: Counter[str], preferred_order: tuple[str, ...]) -> dict[str, int]:
    ordered: dict[str, int] = {}
    for key in preferred_order:
        if counter[key]:
            ordered[key] = counter[key]

    for key in sorted(counter):
        if key not in ordered and counter[key]:
            ordered[key] = counter[key]

    return ordered


def _normalize_optional_text(
    value: str | None,
    *,
    mask_phone_numbers: bool,
) -> str | None:
    if value is None:
        return None
    normalized = _normalize_event_text(value, mask_phone_numbers=mask_phone_numbers)
    return normalized or None


def _normalize_event_text(value: str, *, mask_phone_numbers: bool) -> str:
    compact_value = _compact_text(value)
    if not compact_value:
        return ""
    if not mask_phone_numbers:
        return compact_value
    return _compact_text(mask_sensitive_data(compact_value))


def _compact_text(value: str) -> str:
    return " ".join(str(value).split())
