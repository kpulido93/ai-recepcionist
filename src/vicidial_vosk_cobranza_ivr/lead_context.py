from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
DANGEROUS_CHARS_PATTERN = re.compile(r"""[\\"'`$;&|<>]+""")
PHONE_DIGITS_PATTERN = re.compile(r"\D+")


@dataclass(frozen=True)
class LeadContext:
    lead_id: str | None
    phone_number: str | None
    client_name: str | None
    bank_name: str | None
    portfolio_id: str | None
    campaign_id: str | None
    list_id: str | None


def sanitize_lead_value(value: str | None, max_len: int = 80) -> str | None:
    if value is None:
        return None

    sanitized = CONTROL_CHARS_PATTERN.sub(" ", str(value))
    sanitized = DANGEROUS_CHARS_PATTERN.sub(" ", sanitized)
    sanitized = " ".join(sanitized.split())
    sanitized = sanitized[:max_len].strip()
    if not sanitized:
        return None
    return sanitized


def load_lead_context_from_mapping(data: dict[str, str]) -> LeadContext:
    return LeadContext(
        lead_id=sanitize_lead_value(data.get("lead_id")),
        phone_number=sanitize_lead_value(data.get("phone_number")),
        client_name=sanitize_lead_value(data.get("client_name")),
        bank_name=sanitize_lead_value(data.get("bank_name")),
        portfolio_id=sanitize_lead_value(data.get("portfolio_id")),
        campaign_id=sanitize_lead_value(data.get("campaign_id")),
        list_id=sanitize_lead_value(data.get("list_id")),
    )


def load_lead_context_from_csv(
    path: str | Path,
    lead_id: str | None = None,
    phone_number: str | None = None,
) -> LeadContext | None:
    sanitized_lead_id = sanitize_lead_value(lead_id)
    sanitized_phone_number = sanitize_lead_value(phone_number)
    normalized_phone_number = _normalize_phone_number(sanitized_phone_number)
    csv_path = Path(path)

    if not csv_path.exists():
        return None

    first_phone_match: LeadContext | None = None
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file_handler:
        reader = csv.DictReader(file_handler)
        for row in reader:
            context = load_lead_context_from_mapping(_clean_csv_row(row))
            if sanitized_lead_id and context.lead_id == sanitized_lead_id:
                return context
            if (
                first_phone_match is None
                and normalized_phone_number
                and _normalize_phone_number(context.phone_number) == normalized_phone_number
            ):
                first_phone_match = context

    return first_phone_match


def _clean_csv_row(row: dict[str, str | None]) -> dict[str, str]:
    return {key: value or "" for key, value in row.items() if key is not None}


def _normalize_phone_number(phone_number: str | None) -> str:
    if phone_number is None:
        return ""
    return PHONE_DIGITS_PATTERN.sub("", phone_number)
