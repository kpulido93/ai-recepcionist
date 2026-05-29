from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
DANGEROUS_CHARS_PATTERN = re.compile(r"""[\\"'`$;&|<>]+""")
PHONE_DIGITS_PATTERN = re.compile(r"\D+")


@dataclass(frozen=True)
class LeadContext:
    lead_id: str | None
    phone_number: str | None
    client_name: str | None
    client_gender: str | None
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
        client_gender=sanitize_lead_value(data.get("client_gender")),
        bank_name=sanitize_lead_value(data.get("bank_name")),
        portfolio_id=sanitize_lead_value(data.get("portfolio_id")),
        campaign_id=sanitize_lead_value(data.get("campaign_id")),
        list_id=sanitize_lead_value(data.get("list_id")),
    )


def load_lead_context_from_lab_yaml(
    path: str | Path,
    *,
    lead_id: str | None = None,
    extension: str | None = None,
    phone_number: str | None = None,
) -> LeadContext | None:
    sanitized_lead_id = sanitize_lead_value(lead_id)
    sanitized_extension = sanitize_lead_value(extension, max_len=32)
    sanitized_phone_number = sanitize_lead_value(phone_number, max_len=32)
    normalized_phone_number = _normalize_phone_number(sanitized_phone_number)
    yaml_path = Path(path)

    if not yaml_path.exists():
        return None

    with yaml_path.open("r", encoding="utf-8") as file_handler:
        raw_data = yaml.safe_load(file_handler) or {}
    if not isinstance(raw_data, dict):
        return None

    raw_lab_leads = raw_data.get("lab_leads", {})
    if not isinstance(raw_lab_leads, dict):
        return None

    first_phone_match: LeadContext | None = None
    for raw_extension, raw_mapping in raw_lab_leads.items():
        if not isinstance(raw_mapping, dict):
            continue
        context = load_lead_context_from_mapping(
            _normalize_lab_lead_mapping(str(raw_extension), raw_mapping)
        )
        if sanitized_lead_id and context.lead_id == sanitized_lead_id:
            return context
        if (
            sanitized_extension
            and sanitize_lead_value(raw_extension, max_len=32) == sanitized_extension
        ):
            return context
        if (
            first_phone_match is None
            and normalized_phone_number
            and _normalize_phone_number(context.phone_number) == normalized_phone_number
        ):
            first_phone_match = context

    return first_phone_match


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


def _normalize_lab_lead_mapping(extension: str, raw_mapping: dict[str, object]) -> dict[str, str]:
    normalized_mapping = {
        str(key): "" if value is None else str(value) for key, value in raw_mapping.items()
    }
    client_name = normalized_mapping.get("client_name") or normalized_mapping.get("nombre", "")
    bank_name = normalized_mapping.get("bank_name") or normalized_mapping.get("banco", "")
    return {
        "lead_id": normalized_mapping.get("lead_id", ""),
        "phone_number": normalized_mapping.get("phone_number", extension),
        "client_name": client_name,
        "client_gender": normalized_mapping.get("client_gender", ""),
        "bank_name": bank_name,
        "portfolio_id": normalized_mapping.get("portfolio_id", ""),
        "campaign_id": normalized_mapping.get("campaign_id", ""),
        "list_id": normalized_mapping.get("list_id", ""),
    }


def _normalize_phone_number(phone_number: str | None) -> str:
    if phone_number is None:
        return ""
    return PHONE_DIGITS_PATTERN.sub("", phone_number)
