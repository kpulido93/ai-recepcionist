from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vicidial_vosk_cobranza_ivr.config import PROJECT_ROOT

SAFE_DEFAULT_TRANSFER_TARGET = "PJSIP/1002"
DEFAULT_ALLOWED_TARGET_PATTERNS = (
    r"^PJSIP/[A-Za-z0-9_-]+$",
    r"^Local/[A-Za-z0-9_-]+@[A-Za-z0-9_-]+$",
)
SAFE_TRANSFER_TARGET_CHARS = re.compile(r"^[A-Za-z0-9_@/-]+$")
DEFAULT_ROUTING_CONFIG_PATH = PROJECT_ROOT / "config" / "routing.yml"


class RoutingConfigError(RuntimeError):
    """Raised when routing configuration cannot be loaded."""


@dataclass(frozen=True)
class PortfolioRoute:
    bank_names: tuple[str, ...]
    transfer_target: str


@dataclass(frozen=True)
class RoutingConfig:
    default_transfer_target: str
    allowed_target_patterns: tuple[str, ...]
    portfolios: dict[str, PortfolioRoute]


def load_routing_config(path: Path) -> RoutingConfig:
    config_data = _load_yaml_file(path)
    default_transfer_target = str(
        config_data.get("default_transfer_target", SAFE_DEFAULT_TRANSFER_TARGET)
    )
    allowed_target_patterns = _normalize_allowed_patterns(
        config_data.get("allowed_target_patterns")
    )
    raw_portfolios = config_data.get("portfolios", {})
    if not isinstance(raw_portfolios, dict):
        raise RoutingConfigError("La seccion 'portfolios' debe ser un objeto YAML.")

    portfolios: dict[str, PortfolioRoute] = {}
    for raw_portfolio_id, raw_route in raw_portfolios.items():
        normalized_portfolio_id = normalize_portfolio_id(str(raw_portfolio_id))
        if not normalized_portfolio_id:
            continue

        if not isinstance(raw_route, dict):
            raise RoutingConfigError(f"La cartera '{raw_portfolio_id}' debe ser un objeto YAML.")

        bank_names = _normalize_bank_names(raw_route.get("bank_names"))
        transfer_target = str(raw_route.get("transfer_target", ""))
        portfolios[normalized_portfolio_id] = PortfolioRoute(
            bank_names=bank_names,
            transfer_target=transfer_target,
        )

    return RoutingConfig(
        default_transfer_target=default_transfer_target,
        allowed_target_patterns=allowed_target_patterns,
        portfolios=portfolios,
    )


def normalize_portfolio_id(value: str | None) -> str:
    if value is None:
        return ""
    ascii_value = _to_ascii(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", ascii_value)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def normalize_bank_name(value: str | None) -> str:
    if value is None:
        return ""
    ascii_value = _to_ascii(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", ascii_value)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def validate_transfer_target(target: str, allowed_patterns: tuple[str, ...] | list[str]) -> bool:
    if not isinstance(target, str):
        return False
    if not target or target != target.strip():
        return False
    if len(target) > 128:
        return False
    if not SAFE_TRANSFER_TARGET_CHARS.fullmatch(target):
        return False

    for pattern in _effective_allowed_patterns(allowed_patterns):
        try:
            if re.fullmatch(pattern, target):
                return True
        except re.error:
            continue

    return False


def resolve_transfer_target(
    portfolio_id: str | None = None,
    bank_name: str | None = None,
    config: RoutingConfig | None = None,
) -> str:
    routing_config = config or load_routing_config(DEFAULT_ROUTING_CONFIG_PATH)
    default_target = _resolve_default_target(routing_config)

    normalized_portfolio_id = normalize_portfolio_id(portfolio_id)
    if normalized_portfolio_id:
        route = routing_config.portfolios.get(normalized_portfolio_id)
        if route is not None:
            return _validated_or_default(route.transfer_target, routing_config, default_target)

    normalized_bank_name = normalize_bank_name(bank_name)
    if normalized_bank_name:
        for route in routing_config.portfolios.values():
            if normalized_bank_name in route.bank_names:
                return _validated_or_default(route.transfer_target, routing_config, default_target)

    return default_target


def _load_yaml_file(path: Path) -> dict[str, Any]:
    resolved_path = path.expanduser().resolve()
    if not resolved_path.exists():
        raise RoutingConfigError(f"No existe el archivo: {resolved_path}")

    with resolved_path.open("r", encoding="utf-8") as file_handler:
        data = yaml.safe_load(file_handler) or {}

    if not isinstance(data, dict):
        raise RoutingConfigError(f"El YAML debe contener un objeto en la raiz: {resolved_path}")

    return data


def _normalize_allowed_patterns(raw_patterns: object) -> tuple[str, ...]:
    if raw_patterns is None:
        return DEFAULT_ALLOWED_TARGET_PATTERNS
    if not isinstance(raw_patterns, list):
        raise RoutingConfigError("La seccion 'allowed_target_patterns' debe ser una lista YAML.")

    normalized_patterns = tuple(str(pattern) for pattern in raw_patterns if str(pattern).strip())
    if not normalized_patterns:
        return DEFAULT_ALLOWED_TARGET_PATTERNS
    return normalized_patterns


def _normalize_bank_names(raw_bank_names: object) -> tuple[str, ...]:
    if raw_bank_names is None:
        return ()
    if not isinstance(raw_bank_names, list):
        raise RoutingConfigError("La lista 'bank_names' debe ser una lista YAML.")

    normalized_bank_names: list[str] = []
    for bank_name in raw_bank_names:
        normalized_bank_name = normalize_bank_name(str(bank_name))
        if normalized_bank_name:
            normalized_bank_names.append(normalized_bank_name)

    return tuple(normalized_bank_names)


def _effective_allowed_patterns(allowed_patterns: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized_patterns = tuple(pattern for pattern in allowed_patterns if pattern.strip())
    if normalized_patterns:
        return normalized_patterns
    return DEFAULT_ALLOWED_TARGET_PATTERNS


def _resolve_default_target(config: RoutingConfig) -> str:
    if validate_transfer_target(config.default_transfer_target, config.allowed_target_patterns):
        return config.default_transfer_target
    return SAFE_DEFAULT_TRANSFER_TARGET


def _validated_or_default(target: str, config: RoutingConfig, default_target: str) -> str:
    if validate_transfer_target(target, config.allowed_target_patterns):
        return target
    return default_target


def _to_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))
