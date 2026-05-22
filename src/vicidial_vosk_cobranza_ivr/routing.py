from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROUTING_PATH = PROJECT_ROOT / "config" / "routing.yml"
DEFAULT_SAFE_TRANSFER_TARGET = "PJSIP/1002"
PJSIP_OR_SIP_TARGET_PATTERN = re.compile(r"^(?:PJSIP|SIP)/[A-Za-z0-9_.-]+$")
LOCAL_TARGET_PATTERN = re.compile(r"^Local/[A-Za-z0-9_.#*+-]+@[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class PortfolioRoute:
    portfolio_id: str
    bank_names: tuple[str, ...]
    transfer_target: str


@dataclass(frozen=True)
class RoutingConfig:
    default_transfer_target: str
    portfolios: dict[str, PortfolioRoute]


def resolve_routing_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()

    env_value = os.getenv("VOSK_COBRANZA_ROUTING")
    if env_value:
        return Path(env_value).expanduser().resolve()

    return DEFAULT_ROUTING_PATH.resolve()


def load_routing_config(path: str | Path) -> RoutingConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"No existe el archivo de routing: {config_path}")

    with config_path.open("r", encoding="utf-8") as file_handler:
        loaded = yaml.safe_load(file_handler) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"routing.yml debe contener un objeto en la raiz: {config_path}")

    raw_default_target = str(loaded.get("default_transfer_target", DEFAULT_SAFE_TRANSFER_TARGET))
    portfolios_section = loaded.get("portfolios", {})
    if not isinstance(portfolios_section, dict):
        raise ValueError("La seccion 'portfolios' debe ser un objeto YAML.")

    portfolios: dict[str, PortfolioRoute] = {}
    for raw_portfolio_id, raw_portfolio in portfolios_section.items():
        if not isinstance(raw_portfolio, dict):
            raise ValueError(f"Cada portfolio debe ser un objeto. Recibido: {raw_portfolio!r}")

        portfolio_id = normalize_portfolio_id(str(raw_portfolio_id))
        if not portfolio_id:
            continue

        raw_bank_names = raw_portfolio.get("bank_names", [])
        if not isinstance(raw_bank_names, list):
            raise ValueError(f"bank_names debe ser una lista para {raw_portfolio_id}.")

        portfolios[portfolio_id] = PortfolioRoute(
            portfolio_id=portfolio_id,
            bank_names=tuple(
                normalized_name
                for bank_name in raw_bank_names
                if (normalized_name := normalize_bank_name(str(bank_name)))
            ),
            transfer_target=str(raw_portfolio.get("transfer_target", "")),
        )

    return RoutingConfig(
        default_transfer_target=_coerce_safe_transfer_target(
            raw_default_target,
            fallback=DEFAULT_SAFE_TRANSFER_TARGET,
        ),
        portfolios=portfolios,
    )


def normalize_bank_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.lower())
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    without_punctuation = re.sub(r"[^a-z0-9\s]", " ", ascii_only)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def resolve_transfer_target(
    bank_name: str | None = None,
    portfolio_id: str | None = None,
    config: RoutingConfig | None = None,
) -> str:
    effective_config = config or load_routing_config(resolve_routing_config_path())
    default_target = _coerce_safe_transfer_target(
        effective_config.default_transfer_target,
        fallback=DEFAULT_SAFE_TRANSFER_TARGET,
    )

    normalized_portfolio_id = normalize_portfolio_id(portfolio_id or "")
    if normalized_portfolio_id:
        portfolio_route = effective_config.portfolios.get(normalized_portfolio_id)
        if portfolio_route is not None:
            return _coerce_safe_transfer_target(
                portfolio_route.transfer_target,
                fallback=default_target,
            )

    normalized_bank_name = normalize_bank_name(bank_name or "")
    if normalized_bank_name:
        for portfolio_route in effective_config.portfolios.values():
            if normalized_bank_name in portfolio_route.bank_names:
                return _coerce_safe_transfer_target(
                    portfolio_route.transfer_target,
                    fallback=default_target,
                )

    return default_target


def normalize_portfolio_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    underscored = re.sub(r"[^a-z0-9]+", "_", ascii_only)
    return underscored.strip("_")


def is_safe_transfer_target(value: str) -> bool:
    compact_value = value.strip()
    if not compact_value:
        return False
    if PJSIP_OR_SIP_TARGET_PATTERN.fullmatch(compact_value):
        return True
    return LOCAL_TARGET_PATTERN.fullmatch(compact_value) is not None


def _coerce_safe_transfer_target(value: str, *, fallback: str) -> str:
    compact_value = value.strip()
    if is_safe_transfer_target(compact_value):
        return compact_value
    return fallback
