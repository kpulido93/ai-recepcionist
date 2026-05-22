from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import unicodedata
from collections.abc import Mapping
from pathlib import Path

CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
DANGEROUS_CHARS_PATTERN = re.compile(r"""[\\"'`$;&|<>]+""")
SAFE_CACHE_FRAGMENT_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
DEFAULT_GREETING_TEMPLATE = (
    "Hola {client_name}, nos comunicamos de SokaCorp por una gestión pendiente relacionada "
    "con {bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
)
DEFAULT_GREETING_TEMPLATE_WITHOUT_NAME = (
    "Hola, nos comunicamos de SokaCorp por una gestión pendiente relacionada con "
    "{bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
)
DEFAULT_GREETING_FALLBACK = (
    "Hola, nos comunicamos de SokaCorp por una gestión pendiente. "
    "¿Desea que le comuniquemos ahora? Le escucho."
)
DEFAULT_GREETING_AUDIO = "custom/mensaje-cobranza"
DEFAULT_GREETING_FOLLOWUP_AUDIO = "custom/pregunta-abogado"
DEFAULT_BANK_GREETING_TEMPLATE = "custom/gestion-{bank_slug}"
DEFAULT_BANK_GREETING_FALLBACK = ""
DEFAULT_SOUND_SEARCH_DIRS = (
    "/var/lib/asterisk/sounds",
    "/usr/share/asterisk/sounds",
)
DEFAULT_TTS_PROVIDER = "espeak-ng"
DEFAULT_TTS_VOICE = "es-la"
DEFAULT_MAX_PROMPT_VALUE_LENGTH = 80
DEFAULT_MAX_PROMPT_TEXT_LENGTH = 320


def build_greeting_text(
    client_name: str | None,
    bank_name: str | None,
    config: Mapping[str, object],
) -> str:
    prompts_config = _get_prompts_config(config)
    fallback = _get_config_string(
        prompts_config,
        "greeting_fallback",
        DEFAULT_GREETING_FALLBACK,
    )
    if not bool(prompts_config.get("personalized_greeting_enabled", False)):
        return _limit_text(fallback, prompts_config)

    safe_client_name = sanitize_prompt_value(client_name)
    safe_bank_name = sanitize_prompt_value(bank_name)
    if safe_client_name and safe_bank_name:
        template = _get_config_string(
            prompts_config,
            "greeting_template",
            DEFAULT_GREETING_TEMPLATE,
        )
        return _limit_text(
            template.format(client_name=safe_client_name, bank_name=safe_bank_name),
            prompts_config,
        )

    if safe_bank_name:
        template_without_name = _get_config_string(
            prompts_config,
            "greeting_template_without_name",
            DEFAULT_GREETING_TEMPLATE_WITHOUT_NAME,
        )
        return _limit_text(template_without_name.format(bank_name=safe_bank_name), prompts_config)

    return _limit_text(fallback, prompts_config)


def sanitize_prompt_value(value: str | None) -> str:
    if value is None:
        return ""

    sanitized = CONTROL_CHARS_PATTERN.sub(" ", str(value))
    sanitized = DANGEROUS_CHARS_PATTERN.sub(" ", sanitized)
    sanitized = " ".join(sanitized.split())
    return sanitized[:DEFAULT_MAX_PROMPT_VALUE_LENGTH].strip()


def build_cache_key(
    lead_id: str | None,
    client_name: str | None,
    bank_name: str | None,
    template_hash: str,
) -> str:
    safe_lead_id = _safe_cache_fragment(sanitize_prompt_value(lead_id)) or "no-lead"
    digest_source = "|".join(
        [
            safe_lead_id,
            sanitize_prompt_value(client_name),
            sanitize_prompt_value(bank_name),
            sanitize_prompt_value(template_hash),
        ]
    )
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:20]
    return f"greeting-{safe_lead_id}-{digest}"


def generate_prompt_audio(
    text: str,
    output_path: str | Path,
    config: Mapping[str, object],
) -> None:
    prompts_config = _get_prompts_config(config)
    provider = _get_config_string(prompts_config, "tts_provider", DEFAULT_TTS_PROVIDER)
    if provider != "espeak-ng":
        raise ValueError(f"Proveedor TTS no soportado: {provider}")

    voice = _get_config_string(prompts_config, "tts_voice", DEFAULT_TTS_VOICE)
    prompt_text = _limit_text(" ".join(text.split()), prompts_config)
    if not prompt_text:
        raise ValueError("El texto del prompt no puede estar vacío.")

    resolved_output_path = Path(output_path).expanduser().resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_output_path = resolved_output_path.with_suffix(".raw-tts.wav")
    converted_output_path = resolved_output_path.with_suffix(".tmp.wav")

    try:
        subprocess.run(
            [provider, "--stdin", "-v", voice, "-w", str(raw_output_path)],
            input=prompt_text,
            text=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_output_path),
                "-ar",
                "8000",
                "-ac",
                "1",
                "-acodec",
                "pcm_s16le",
                str(converted_output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.replace(converted_output_path, resolved_output_path)
    finally:
        raw_output_path.unlink(missing_ok=True)
        converted_output_path.unlink(missing_ok=True)


def build_bank_greeting_audio(bank_name: str | None, config: Mapping[str, object]) -> str:
    prompts_config = _get_prompts_config(config)
    safe_bank_name = sanitize_prompt_value(bank_name)
    if not safe_bank_name:
        return ""

    bank_slug = _bank_slug(safe_bank_name)
    if not bank_slug:
        return ""

    template = _get_config_string(
        prompts_config,
        "bank_greeting_filename_template",
        DEFAULT_BANK_GREETING_TEMPLATE,
    )
    candidate = template.format(bank_slug=bank_slug)
    if _playback_audio_exists(candidate, prompts_config):
        return candidate

    fallback_audio = _get_config_string(
        prompts_config,
        "bank_greeting_fallback_audio",
        DEFAULT_BANK_GREETING_FALLBACK,
    )
    if fallback_audio and _playback_audio_exists(fallback_audio, prompts_config):
        return fallback_audio
    return ""


def get_default_greeting_audio(config: Mapping[str, object]) -> str:
    prompts_config = _get_prompts_config(config)
    return _get_config_string(
        prompts_config,
        "default_greeting_audio",
        DEFAULT_GREETING_AUDIO,
    )


def get_greeting_followup_audio(config: Mapping[str, object]) -> str:
    prompts_config = _get_prompts_config(config)
    return _get_config_string(
        prompts_config,
        "greeting_followup_audio",
        DEFAULT_GREETING_FOLLOWUP_AUDIO,
    )


def mirror_audio_file(source_path: str | Path, mirror_dirs: list[str] | tuple[str, ...]) -> None:
    resolved_source_path = Path(source_path).expanduser().resolve()
    if not resolved_source_path.exists():
        raise FileNotFoundError(resolved_source_path)

    for mirror_dir in mirror_dirs:
        if not mirror_dir:
            continue
        resolved_mirror_dir = Path(mirror_dir).expanduser().resolve()
        resolved_mirror_dir.mkdir(parents=True, exist_ok=True)
        target_path = _safe_output_path(resolved_mirror_dir, resolved_source_path.name)
        temp_path = target_path.with_suffix(".tmp.wav")
        try:
            shutil.copy2(resolved_source_path, temp_path)
            os.replace(temp_path, target_path)
        finally:
            temp_path.unlink(missing_ok=True)


def _get_prompts_config(config: Mapping[str, object]) -> Mapping[str, object]:
    prompts_config = config.get("prompts")
    if isinstance(prompts_config, Mapping):
        return prompts_config
    return config


def _get_config_string(
    config: Mapping[str, object],
    key: str,
    default_value: str,
) -> str:
    value = config.get(key)
    if value is None:
        return default_value
    return str(value)


def _limit_text(text: str, config: Mapping[str, object]) -> str:
    max_length_value = config.get("max_prompt_text_length", DEFAULT_MAX_PROMPT_TEXT_LENGTH)
    if isinstance(max_length_value, int):
        max_length = max_length_value
    elif isinstance(max_length_value, str):
        max_length = int(max_length_value)
    else:
        max_length = DEFAULT_MAX_PROMPT_TEXT_LENGTH
    return text[:max_length].strip()


def _safe_cache_fragment(value: str) -> str:
    safe_value = SAFE_CACHE_FRAGMENT_PATTERN.sub("-", value.strip())
    return safe_value.strip("-_")[:32]


def _bank_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    return _safe_cache_fragment(ascii_value.lower())


def _playback_audio_exists(playback_path: str, config: Mapping[str, object]) -> bool:
    search_dirs = _get_sound_search_dirs(config)
    for sound_dir in search_dirs:
        base_dir = Path(sound_dir).expanduser().resolve()
        file_base = (base_dir / playback_path).resolve()
        candidates = [
            file_base,
            file_base.with_suffix(".wav"),
            file_base.with_suffix(".WAV"),
        ]
        if any(candidate.exists() for candidate in candidates):
            return True
    return False


def _get_sound_search_dirs(config: Mapping[str, object]) -> tuple[str, ...]:
    search_dirs = config.get("sound_search_dirs")
    if isinstance(search_dirs, list):
        return tuple(str(path) for path in search_dirs if str(path).strip())
    return DEFAULT_SOUND_SEARCH_DIRS


def _safe_output_path(base_dir: Path, filename: str) -> Path:
    output_path = (base_dir / filename).resolve()
    try:
        output_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError("La ruta de audio generado queda fuera del directorio permitido.") from exc
    return output_path
