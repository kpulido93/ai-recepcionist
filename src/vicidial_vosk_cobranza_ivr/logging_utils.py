from __future__ import annotations

import logging
import re
from logging.config import dictConfig
from pathlib import Path
from typing import Any

import yaml

from vicidial_vosk_cobranza_ivr.config import LoggingSettings

PHONE_NUMBER_PATTERN = re.compile(r"(?<!\d)(\+?\d[\d\s-]{5,}\d)(?!\d)")


class PhoneMaskingFilter(logging.Filter):
    def __init__(self, enabled: bool = True) -> None:
        super().__init__()
        self.enabled = enabled

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.enabled:
            return True

        message = record.getMessage()
        record.msg = mask_phone_numbers(message)
        record.args = ()
        return True


def configure_logging(
    logging_settings: LoggingSettings,
    logging_config_path: Path,
) -> logging.Logger:
    if not logging_settings.enabled:
        logging.basicConfig(level=logging.CRITICAL)
        return logging.getLogger("vicidial_vosk_cobranza_ivr")

    config_data = _load_logging_config(logging_config_path)
    log_path = Path(logging_settings.log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if "handlers" in config_data and "file" in config_data["handlers"]:
        config_data["handlers"]["file"]["filename"] = str(log_path)
        config_data["handlers"]["file"]["level"] = logging_settings.log_level
    if "handlers" in config_data and "console" in config_data["handlers"]:
        config_data["handlers"]["console"]["level"] = logging_settings.log_level
    if "root" in config_data:
        config_data["root"]["level"] = logging_settings.log_level
    if "loggers" in config_data and "vicidial_vosk_cobranza_ivr" in config_data["loggers"]:
        config_data["loggers"]["vicidial_vosk_cobranza_ivr"]["level"] = logging_settings.log_level
    if "filters" in config_data and "phone_mask" in config_data["filters"]:
        config_data["filters"]["phone_mask"]["enabled"] = logging_settings.mask_phone_numbers

    dictConfig(config_data)
    return logging.getLogger("vicidial_vosk_cobranza_ivr")


def mask_phone_numbers(message: str) -> str:
    return PHONE_NUMBER_PATTERN.sub(_mask_match, message)


def _mask_match(match: re.Match[str]) -> str:
    value = match.group(0)
    digit_positions = [index for index, char in enumerate(value) if char.isdigit()]
    visible_positions = set(digit_positions[-2:])
    return "".join(
        char if not char.isdigit() or index in visible_positions else "X"
        for index, char in enumerate(value)
    )


def _load_logging_config(logging_config_path: Path) -> dict[str, Any]:
    with logging_config_path.open("r", encoding="utf-8") as file_handler:
        config_data = yaml.safe_load(file_handler) or {}

    if not isinstance(config_data, dict):
        raise RuntimeError("logging.yml debe contener un objeto en la raiz.")

    return config_data
