#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import math
import os
import re
import select
import struct
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import yaml
from websocket import WebSocketException, WebSocketTimeoutException, create_connection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "ivr.yml"
DEFAULT_INTENTS_PATH = PROJECT_ROOT / "config" / "intents.yml"

AGI_TEXT_VARIABLE = "VOSK_TEXT"
AGI_INTENT_VARIABLE = "VOSK_INTENT"
AGI_CONFIDENCE_VARIABLE = "VOSK_CONFIDENCE"
SUPPORTED_INTENTS = ("SI", "NO", "DUDA", "SILENCIO")


class ConfigError(RuntimeError):
    """Raised when the IVR or intents YAML files are invalid."""


class VoskError(RuntimeError):
    """Raised when the Vosk server cannot be reached or parsed."""


@dataclass(frozen=True)
class AppConfig:
    listen_seconds: int
    websocket_url: str
    sample_rate: int
    websocket_timeout_seconds: int
    log_level: str
    log_path: str
    mask_phone_numbers: bool
    intents: dict[str, list[str]]


@dataclass(frozen=True)
class IntentResult:
    intent: str
    confidence: float
    matched_phrase: str | None = None


@dataclass(frozen=True)
class VoskResult:
    text: str
    partials: list[str]
    confidence: float | None


def load_config(
    config_path: Path | None = None,
    intents_path: Path | None = None,
) -> AppConfig:
    """Load runtime settings from YAML and apply light env overrides."""
    resolved_config_path = Path(
        os.getenv("VOSK_COBRANZA_CONFIG", str(config_path or DEFAULT_CONFIG_PATH))
    ).resolve()
    resolved_intents_path = Path(
        os.getenv("VOSK_COBRANZA_INTENTS", str(intents_path or DEFAULT_INTENTS_PATH))
    ).resolve()

    config_data = _read_yaml_mapping(resolved_config_path)
    intents_data = _read_yaml_mapping(resolved_intents_path)

    try:
        listen_seconds = int(os.getenv("IVR_LISTEN_SECONDS", config_data["ivr"]["listen_seconds"]))
        websocket_url = str(
            os.getenv("VOSK_WEBSOCKET_URL", config_data["vosk"]["websocket_url"])
        ).strip()
        sample_rate = int(os.getenv("VOSK_SAMPLE_RATE", config_data["vosk"]["sample_rate"]))
        websocket_timeout_seconds = int(config_data["vosk"]["websocket_timeout_seconds"])
        log_level = str(os.getenv("LOG_LEVEL", config_data["logging"]["log_level"])).upper()
        log_path = str(os.getenv("LOG_PATH", config_data["logging"]["log_path"])).strip()
        mask_phone_numbers = bool(config_data["logging"]["mask_phone_numbers"])
    except KeyError as exc:
        raise ConfigError(f"Falta una clave requerida en la configuracion: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"La configuracion contiene tipos invalidos: {exc}") from exc

    if not 1 <= listen_seconds <= 15:
        raise ConfigError("ivr.listen_seconds debe estar entre 1 y 15 segundos.")
    if sample_rate <= 0:
        raise ConfigError("vosk.sample_rate debe ser mayor que cero.")
    if not websocket_url.startswith(("ws://", "wss://")):
        raise ConfigError("vosk.websocket_url debe empezar con ws:// o wss://.")
    if not log_path:
        raise ConfigError("logging.log_path no puede estar vacio.")

    normalized_intents: dict[str, list[str]] = {}
    for intent_name in SUPPORTED_INTENTS:
        raw_phrases = intents_data.get(intent_name)
        if raw_phrases is None:
            raise ConfigError(f"Falta la lista del intent {intent_name} en intents.yml.")
        if not isinstance(raw_phrases, list):
            raise ConfigError(f"El intent {intent_name} debe contener una lista.")
        normalized_intents[intent_name] = [
            normalize_text(str(phrase)) for phrase in raw_phrases if normalize_text(str(phrase))
        ]

    return AppConfig(
        listen_seconds=listen_seconds,
        websocket_url=websocket_url,
        sample_rate=sample_rate,
        websocket_timeout_seconds=websocket_timeout_seconds,
        log_level=log_level,
        log_path=log_path,
        mask_phone_numbers=mask_phone_numbers,
        intents=normalized_intents,
    )


def normalize_text(text: str) -> str:
    """Convert text to lowercase ASCII and collapse punctuation/whitespace."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", cleaned).strip()


def classify_intent(text: str, intents: dict[str, list[str]]) -> IntentResult:
    """Classify normalized text into SI, NO, DUDA or SILENCIO."""
    normalized_text = normalize_text(text)
    if not normalized_text:
        return IntentResult(intent="SILENCIO", confidence=0.0, matched_phrase=None)

    yes_match = _find_best_phrase_match(normalized_text, "SI", intents)
    no_match = _find_best_phrase_match(normalized_text, "NO", intents)
    doubt_match = _find_best_phrase_match(normalized_text, "DUDA", intents)

    strongest_yes_no = max(
        yes_match[1] if yes_match is not None else 0.0,
        no_match[1] if no_match is not None else 0.0,
    )

    if doubt_match is not None and doubt_match[1] >= strongest_yes_no:
        return IntentResult(intent="DUDA", confidence=doubt_match[1], matched_phrase=doubt_match[0])

    if yes_match and no_match:
        return IntentResult(
            intent="DUDA",
            confidence=round(min(yes_match[1], no_match[1]) * 0.5, 2),
            matched_phrase=f"{yes_match[0]}|{no_match[0]}",
        )

    if yes_match:
        return IntentResult(intent="SI", confidence=yes_match[1], matched_phrase=yes_match[0])

    if no_match:
        return IntentResult(intent="NO", confidence=no_match[1], matched_phrase=no_match[0])

    return IntentResult(intent="DUDA", confidence=0.35, matched_phrase=None)


def read_eagi_audio(
    max_seconds: int,
    sample_rate: int,
    fd: int = 3,
) -> bytes:
    """Read raw signed 16-bit PCM audio from EAGI fd 3 for up to max_seconds."""
    bytes_per_second = sample_rate * 2
    target_bytes = bytes_per_second * max_seconds
    chunk_size = max(1600, int(bytes_per_second * 0.2))
    deadline = time.monotonic() + max_seconds + 0.5
    chunks: list[bytes] = []
    bytes_read = 0

    while bytes_read < target_bytes and time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([fd], [], [], min(0.2, remaining))
        if not readable:
            continue

        chunk = os.read(fd, min(chunk_size, target_bytes - bytes_read))
        if not chunk:
            break

        chunks.append(chunk)
        bytes_read += len(chunk)

    return b"".join(chunks)


def send_audio_to_vosk(
    audio_bytes: bytes,
    websocket_url: str,
    sample_rate: int,
    timeout_seconds: int,
) -> VoskResult:
    """Send PCM audio to Vosk Server and collect partial/final recognition messages."""
    websocket = None
    partials: list[str] = []
    final_text = ""
    word_confidences: list[float] = []
    chunk_size = max(1600, int(sample_rate * 2 * 0.2))

    try:
        websocket = create_connection(websocket_url, timeout=timeout_seconds)
        websocket.send(json.dumps({"config": {"sample_rate": sample_rate}}))

        for offset in range(0, len(audio_bytes), chunk_size):
            websocket.send_binary(audio_bytes[offset : offset + chunk_size])
            response = _receive_vosk_message(websocket)
            _collect_vosk_response(response, partials, word_confidences)
            response_text = str(response.get("text", "")).strip()
            if response_text:
                final_text = response_text

        websocket.send(json.dumps({"eof": 1}))
        final_response = _receive_vosk_message(websocket)
        _collect_vosk_response(final_response, partials, word_confidences)
        response_text = str(final_response.get("text", "")).strip()
        if response_text:
            final_text = response_text

        transcript = final_text or (partials[-1] if partials else "")
        if not transcript:
            confidence: float | None = 0.0
        elif word_confidences:
            confidence = sum(word_confidences) / len(word_confidences)
        else:
            confidence = None

        return VoskResult(text=transcript, partials=partials, confidence=confidence)
    except WebSocketTimeoutException as exc:
        raise TimeoutError(f"Timeout al consultar Vosk en {websocket_url}") from exc
    except (OSError, ValueError, WebSocketException) as exc:
        raise VoskError(f"No fue posible consultar Vosk en {websocket_url}") from exc
    finally:
        if websocket is not None:
            websocket.close()


def agi_set_variable(
    name: str,
    value: str,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
) -> str:
    """Send SET VARIABLE to Asterisk and return the raw AGI response line."""
    escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
    stdout.write(f'SET VARIABLE {name} "{escaped_value}"\n')
    stdout.flush()
    return stdin.readline().strip()


def main() -> int:
    """Entry point for the EAGI script."""
    agi_env = _read_agi_environment(sys.stdin)
    logger = _build_fallback_logger()

    try:
        config = load_config()
        logger = _build_logger(config)
    except ConfigError as exc:
        logger.error("Configuracion invalida: %s", exc)
        _write_agi_result(intent="DUDA", text="", confidence=0.0)
        return 1

    caller_id = agi_env.get("agi_callerid", "")
    unique_id = agi_env.get("agi_uniqueid", "")
    channel = agi_env.get("agi_channel", "")
    logger.info(
        "Inicio EAGI uniqueid=%s channel=%s caller=%s",
        _mask_value(unique_id, config.mask_phone_numbers),
        _mask_value(channel, config.mask_phone_numbers),
        _mask_value(caller_id, config.mask_phone_numbers),
    )

    try:
        audio_bytes = read_eagi_audio(
            max_seconds=config.listen_seconds,
            sample_rate=config.sample_rate,
        )

        if not audio_bytes or not _audio_has_signal(audio_bytes):
            logger.info("Audio vacio o sin energia suficiente para STT.")
            _write_agi_result(intent="SILENCIO", text="", confidence=0.0)
            return 0

        vosk_result = send_audio_to_vosk(
            audio_bytes=audio_bytes,
            websocket_url=config.websocket_url,
            sample_rate=config.sample_rate,
            timeout_seconds=config.websocket_timeout_seconds,
        )
        normalized_text = normalize_text(vosk_result.text)
        intent_result = classify_intent(normalized_text, config.intents)
        final_confidence = _combine_confidence(intent_result.confidence, vosk_result.confidence)
        _write_agi_result(
            intent=intent_result.intent,
            text=normalized_text,
            confidence=final_confidence,
        )
        logger.info(
            "Fin EAGI intent=%s confidence=%.2f phrase=%s text=%s",
            intent_result.intent,
            final_confidence,
            intent_result.matched_phrase or "-",
            _mask_value(normalized_text, config.mask_phone_numbers),
        )
        return 0
    except TimeoutError as exc:
        logger.error("Timeout de Vosk: %s", exc)
        _write_agi_result(intent="DUDA", text="", confidence=0.0)
        return 1
    except VoskError as exc:
        logger.error("Vosk no disponible: %s", exc)
        _write_agi_result(intent="DUDA", text="", confidence=0.0)
        return 1
    except OSError as exc:
        logger.error("No fue posible leer audio EAGI: %s", exc)
        _write_agi_result(intent="SILENCIO", text="", confidence=0.0)
        return 1
    except Exception:
        logger.exception("Error no controlado en vosk_cobranza.py")
        _write_agi_result(intent="DUDA", text="", confidence=0.0)
        return 1


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"No existe el archivo requerido: {path}")

    with path.open("r", encoding="utf-8") as file_handler:
        loaded = yaml.safe_load(file_handler) or {}

    if not isinstance(loaded, dict):
        raise ConfigError(f"El archivo YAML debe tener un objeto en la raiz: {path}")

    return loaded


def _phrase_match_score(normalized_text: str, phrase: str) -> float:
    if not phrase:
        return 0.0

    if normalized_text == phrase:
        return 1.0

    if f" {phrase} " in f" {normalized_text} ":
        token_bonus = min(0.1, len(phrase.split()) * 0.03)
        return round(0.8 + token_bonus, 2)

    return 0.0


def _find_best_phrase_match(
    normalized_text: str,
    intent_name: str,
    intents: dict[str, list[str]],
) -> tuple[str, float] | None:
    best_phrase: str | None = None
    best_score = -1.0

    for phrase in intents.get(intent_name, []):
        score = _phrase_match_score(normalized_text, phrase)
        if score <= 0:
            continue

        if score > best_score:
            best_phrase = phrase
            best_score = score
            continue

        if score == best_score and best_phrase is not None and len(phrase) > len(best_phrase):
            best_phrase = phrase
            best_score = score

    if best_phrase is None or best_score <= 0:
        return None

    return best_phrase, best_score


def _receive_vosk_message(websocket: Any) -> dict[str, Any]:
    payload = websocket.recv()
    if isinstance(payload, bytes):
        raise ValueError("Vosk devolvio un frame binario inesperado.")

    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ValueError("Vosk devolvio un JSON no valido.")
    return parsed


def _collect_vosk_response(
    response: dict[str, Any],
    partials: list[str],
    word_confidences: list[float],
) -> None:
    partial_text = str(response.get("partial", "")).strip()
    if partial_text:
        partials.append(partial_text)

    result_items = response.get("result", [])
    if isinstance(result_items, list):
        for item in result_items:
            if isinstance(item, dict) and "conf" in item:
                try:
                    word_confidences.append(float(item["conf"]))
                except (TypeError, ValueError):
                    continue


def _read_agi_environment(stdin: TextIO) -> dict[str, str]:
    agi_env: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if line == "":
            break

        stripped = line.rstrip("\n")
        if not stripped:
            break

        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        agi_env[key.strip()] = value.strip()

    return agi_env


def _audio_has_signal(audio_bytes: bytes, min_rms: float = 150.0) -> bool:
    sample_count = len(audio_bytes) // 2
    if sample_count < 200:
        return False

    squared_sum = 0.0
    for (sample,) in struct.iter_unpack("<h", audio_bytes[: sample_count * 2]):
        squared_sum += float(sample) * float(sample)

    rms = math.sqrt(squared_sum / sample_count)
    return rms >= min_rms


def _combine_confidence(classifier_confidence: float, speech_confidence: float | None) -> float:
    if speech_confidence is None:
        return classifier_confidence
    return min(classifier_confidence, speech_confidence)


def _build_fallback_logger() -> logging.Logger:
    logger = logging.getLogger("vosk_cobranza")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _build_logger(config: AppConfig) -> logging.Logger:
    logger = logging.getLogger("vosk_cobranza")
    logger.handlers.clear()
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    log_path = Path(config.log_path)
    if not log_path.is_absolute():
        log_path = (PROJECT_ROOT / log_path).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    return logger


def _write_agi_result(intent: str, text: str, confidence: float) -> None:
    agi_set_variable(AGI_TEXT_VARIABLE, text)
    agi_set_variable(AGI_INTENT_VARIABLE, intent)
    agi_set_variable(AGI_CONFIDENCE_VARIABLE, f"{confidence:.2f}")


def _mask_value(value: str, enabled: bool) -> str:
    if not enabled or not value:
        return value

    def replacer(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = [index for index, char in enumerate(raw) if char.isdigit()]
        visible_positions = set(digits[-2:])
        return "".join(
            char if not char.isdigit() or index in visible_positions else "X"
            for index, char in enumerate(raw)
        )

    masked = re.sub(r"(?<!\d)(\+?\d[\d\s-]{5,}\d)(?!\d)", replacer, value)
    return masked[:120]


if __name__ == "__main__":
    raise SystemExit(main())
