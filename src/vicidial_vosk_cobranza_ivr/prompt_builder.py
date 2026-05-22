from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from vicidial_vosk_cobranza_ivr.config import PromptsSettings

MAX_PROMPT_VALUE_LENGTH = 80
MAX_PROMPT_TEXT_LENGTH = 280
SAFE_PROMPT_PUNCTUATION = {" ", ".", ",", "?", "¿", "!", "¡", "-", "'", "&"}
SAFE_FILENAME_PATTERN = re.compile(r"[^a-z0-9-]+")


def sanitize_prompt_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    sanitized_chars: list[str] = []
    for char in normalized:
        if char.isalnum() or char in SAFE_PROMPT_PUNCTUATION:
            sanitized_chars.append(char)
            continue
        if char.isspace():
            sanitized_chars.append(" ")
            continue
        sanitized_chars.append(" ")

    compact = " ".join("".join(sanitized_chars).split())
    return compact[:MAX_PROMPT_VALUE_LENGTH].strip()


def build_greeting_text(
    client_name: str | None,
    bank_name: str | None,
    config: PromptsSettings,
) -> str:
    safe_client_name = sanitize_prompt_value(client_name or "")
    safe_bank_name = sanitize_prompt_value(bank_name or "")

    if safe_client_name and safe_bank_name:
        return _limit_prompt_text(
            config.greeting_template.format(
                client_name=safe_client_name,
                bank_name=safe_bank_name,
            )
        )

    if safe_bank_name:
        return _limit_prompt_text(
            config.greeting_template_without_name.format(bank_name=safe_bank_name)
        )

    return _limit_prompt_text(config.greeting_fallback)


def build_cache_key(
    lead_id: str | None,
    client_name: str | None,
    bank_name: str | None,
    template_hash: str,
) -> str:
    safe_lead_fragment = _sanitize_filename_fragment(lead_id or "") or "anon"
    digest = hashlib.sha256(
        "|".join(
            [
                sanitize_prompt_value(lead_id or ""),
                sanitize_prompt_value(client_name or ""),
                sanitize_prompt_value(bank_name or ""),
                sanitize_prompt_value(template_hash),
            ]
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"lead-{safe_lead_fragment}-greeting-{digest}"


def build_template_hash(config: PromptsSettings) -> str:
    hash_input = "|".join(
        [
            config.greeting_template,
            config.greeting_template_without_name,
            config.greeting_fallback,
            config.tts_provider,
            config.tts_voice,
        ]
    )
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:12]


def build_generated_audio_path(cache_key: str, config: PromptsSettings) -> Path:
    safe_cache_key = _sanitize_filename_fragment(cache_key)
    if not safe_cache_key:
        raise ValueError("cache_key invalido para generar audio.")
    return Path(config.generated_audio_dir).expanduser() / f"{safe_cache_key}.wav"


def build_playback_target(cache_key: str, config: PromptsSettings) -> str:
    prefix = config.generated_audio_playback_prefix.strip().strip("/")
    safe_cache_key = _sanitize_filename_fragment(cache_key)
    if not prefix or not safe_cache_key:
        raise ValueError("No fue posible construir el target de Playback.")
    return f"{prefix}/{safe_cache_key}"


def generate_prompt_audio(
    text: str,
    output_path: str | Path,
    config: PromptsSettings,
) -> Path:
    safe_text = sanitize_prompt_value(text)
    if not safe_text:
        safe_text = sanitize_prompt_value(config.greeting_fallback)
    if not safe_text:
        raise ValueError("El texto del prompt quedo vacio despues de sanitizar.")

    target_path = _validate_output_path(output_path, config)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(target_path.parent)) as temp_dir:
        source_path = Path(temp_dir) / "prompt.source.wav"
        try:
            subprocess.run(
                [
                    config.tts_provider,
                    "-v",
                    config.tts_voice,
                    "-w",
                    str(source_path),
                    "--",
                    safe_text,
                ],
                check=True,
                capture_output=True,
                shell=False,
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source_path),
                    "-ar",
                    "8000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(target_path),
                ],
                check=True,
                capture_output=True,
                shell=False,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(
                f"No fue posible generar el audio personalizado localmente: {stderr or exc}"
            ) from exc

    return target_path


def _validate_output_path(output_path: str | Path, config: PromptsSettings) -> Path:
    allowed_root = Path(config.generated_audio_dir).expanduser().resolve()
    target_path = Path(output_path).expanduser().resolve()
    if target_path.suffix.lower() != ".wav":
        raise ValueError("El audio generado debe guardarse como .wav")
    try:
        target_path.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("La ruta de salida esta fuera del directorio permitido.") from exc
    return target_path


def _limit_prompt_text(value: str) -> str:
    compact = " ".join(value.split())
    return compact[:MAX_PROMPT_TEXT_LENGTH].strip()


def _sanitize_filename_fragment(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    lowered = ascii_value.lower().strip()
    collapsed = SAFE_FILENAME_PATTERN.sub("-", lowered)
    return collapsed.strip("-")
