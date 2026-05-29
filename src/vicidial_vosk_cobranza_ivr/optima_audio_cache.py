from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib import error, parse, request

from vicidial_vosk_cobranza_ivr.env_file import load_optima_env_file_if_needed
from vicidial_vosk_cobranza_ivr.prompt_builder import mirror_audio_file

CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
DANGEROUS_VALUE_PATTERN = re.compile(r"""[\\/:"'`$;&|<>]+""")
WEIRD_SPACE_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]+")
MULTISPACE_PATTERN = re.compile(r"\s+")
DEFAULT_OPTIMA_AUDIO_PROVIDER = "elevenlabs"
DEFAULT_OPTIMA_AUDIO_CACHE_DIR = "/var/lib/asterisk/sounds/custom/generated/optima"
DEFAULT_OPTIMA_AUDIO_MIRROR_DIRS = ("/usr/share/asterisk/sounds/custom/generated/optima",)
DEFAULT_OPTIMA_AUDIO_PLAYBACK_PREFIX = "custom/generated/optima"
DEFAULT_OPTIMA_AUDIO_VERSION = "v1-optima-segmented"
DEFAULT_OPTIMA_AUDIO_MAX_NAME_CHARS = 80
DEFAULT_OPTIMA_AUDIO_MAX_BANK_CHARS = 120
DEFAULT_OPTIMA_AUDIO_TEMPLATE_SALUDO_NOMBRE = "Saludos {name}."
DEFAULT_OPTIMA_AUDIO_TEMPLATE_DEUDA_BANCO = "Por la deuda que mantiene en {bank}."
DEFAULT_OPTIMA_AUDIO_FALLBACK_SALUDO_GENERICO = "custom/optima-01-saludo-generico"
DEFAULT_OPTIMA_AUDIO_FALLBACK_DEUDA_GENERICA = "custom/optima-04-deuda-generica"
DEFAULT_ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_ELEVENLABS_API_KEY_ENV = "ELEVENLABS_API_KEY"
DEFAULT_ELEVENLABS_VOICE_ID_ENV = "ELEVENLABS_VOICE_ID"
DEFAULT_ELEVENLABS_TIMEOUT_SECONDS = 15
READABLE_AUDIO_FILE_MODE_BITS = 0o444

OPTIMA_SALUDO_NOMBRE: Literal["saludo_nombre"] = "saludo_nombre"
OPTIMA_DEUDA_BANCO: Literal["deuda_banco"] = "deuda_banco"
OptimaPromptType = Literal["saludo_nombre", "deuda_banco"]

PROMPT_TYPE_TO_STEM = {
    OPTIMA_SALUDO_NOMBRE: "optima-01-saludo-nombre",
    OPTIMA_DEUDA_BANCO: "optima-04-deuda-banco",
}
PROMPT_TYPE_TO_TEMPLATE_KEY = {
    OPTIMA_SALUDO_NOMBRE: "saludo_nombre",
    OPTIMA_DEUDA_BANCO: "deuda_banco",
}
PROMPT_TYPE_TO_FALLBACK_KEY = {
    OPTIMA_SALUDO_NOMBRE: "saludo_generico_audio",
    OPTIMA_DEUDA_BANCO: "deuda_generica_audio",
}


def normalize_optima_value(value: str, *, prompt_type: OptimaPromptType) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = CONTROL_CHARS_PATTERN.sub(" ", normalized)
    normalized = WEIRD_SPACE_PATTERN.sub(" ", normalized)
    normalized = DANGEROUS_VALUE_PATTERN.sub(" ", normalized)
    normalized = MULTISPACE_PATTERN.sub(" ", normalized)
    max_chars = (
        DEFAULT_OPTIMA_AUDIO_MAX_NAME_CHARS
        if prompt_type == OPTIMA_SALUDO_NOMBRE
        else DEFAULT_OPTIMA_AUDIO_MAX_BANK_CHARS
    )
    return normalized.strip()[:max_chars].strip()


def build_optima_audio_text(
    prompt_type: OptimaPromptType,
    value: str,
    config: Mapping[str, object],
) -> str:
    optima_audio_config = _resolve_optima_runtime_config(config)
    normalized_value = _normalize_value_for_runtime(value, optima_audio_config, prompt_type)
    if not normalized_value:
        raise ValueError("El valor normalizado quedó vacío.")

    template = _get_template(optima_audio_config, prompt_type)
    try:
        if prompt_type == OPTIMA_SALUDO_NOMBRE:
            rendered_text = template.format(name=normalized_value)
        else:
            rendered_text = template.format(bank=normalized_value)
    except KeyError as exc:
        raise ValueError("La plantilla de audio Optima es inválida.") from exc

    normalized_text = _normalize_rendered_text(rendered_text)
    if not normalized_text:
        raise ValueError("El texto final del audio Optima quedó vacío.")
    return normalized_text


def build_optima_cache_key(
    prompt_type: OptimaPromptType,
    value: str,
    voice_id: str,
    model_id: str,
    version: str,
    *,
    final_text: str | None = None,
) -> str:
    normalized_prompt_type = _normalize_prompt_type(prompt_type)
    normalized_value = _normalize_rendered_text(value)
    normalized_text = _normalize_rendered_text(final_text or normalized_value)
    digest_source = "|".join(
        [
            normalized_prompt_type,
            normalized_value,
            normalized_text,
            voice_id.strip(),
            model_id.strip(),
            version.strip(),
        ]
    )
    return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]


def build_optima_audio_filename(prompt_type: OptimaPromptType, cache_key: str) -> str:
    return f"{_get_filename_stem(prompt_type)}-{cache_key}.wav"


def build_optima_playback_path(audio_path: Path, config: Mapping[str, object]) -> str:
    optima_audio_config = _get_optima_audio_config(config)
    playback_prefix = str(
        optima_audio_config.get("playback_prefix", DEFAULT_OPTIMA_AUDIO_PLAYBACK_PREFIX)
    ).strip("/")
    if not playback_prefix:
        playback_prefix = DEFAULT_OPTIMA_AUDIO_PLAYBACK_PREFIX
    return f"{playback_prefix}/{audio_path.stem}"


def get_optima_fallback_audio(
    prompt_type: OptimaPromptType,
    config: Mapping[str, object],
) -> str:
    optima_audio_config = _resolve_optima_runtime_config(config)
    fallbacks_config = _get_nested_mapping(optima_audio_config, "fallbacks")
    fallback_key = PROMPT_TYPE_TO_FALLBACK_KEY[_normalize_prompt_type(prompt_type)]
    default_fallback = (
        DEFAULT_OPTIMA_AUDIO_FALLBACK_SALUDO_GENERICO
        if prompt_type == OPTIMA_SALUDO_NOMBRE
        else DEFAULT_OPTIMA_AUDIO_FALLBACK_DEUDA_GENERICA
    )
    fallback_audio = str(fallbacks_config.get(fallback_key, default_fallback)).strip()
    return fallback_audio or default_fallback


def get_cached_optima_audio(
    prompt_type: OptimaPromptType,
    value: str,
    config: Mapping[str, object],
) -> Path | None:
    optima_audio_config = _get_optima_audio_config(config)
    if not bool(optima_audio_config.get("enabled", False)):
        return None
    if not bool(optima_audio_config.get("cache_enabled", True)):
        return None

    normalized_value = _normalize_value_for_runtime(value, optima_audio_config, prompt_type)
    if not normalized_value:
        return None

    rendered_text = build_optima_audio_text(prompt_type, normalized_value, config)
    cache_key = build_optima_cache_key(
        prompt_type,
        normalized_value,
        _get_voice_id(config),
        _get_model_id(config),
        _get_version(optima_audio_config),
        final_text=rendered_text,
    )
    filename = build_optima_audio_filename(prompt_type, cache_key)

    for base_dir in _all_cache_dirs(optima_audio_config):
        candidate = _safe_output_path(base_dir, filename)
        if candidate.exists():
            return candidate
    return None


def generate_optima_audio(
    prompt_type: OptimaPromptType,
    value: str,
    config: Mapping[str, object],
    *,
    force: bool = False,
) -> Path:
    optima_audio_config = _get_optima_audio_config(config)
    if not bool(optima_audio_config.get("enabled", False)):
        raise ValueError("La generación de audio Optima está desactivada.")

    provider = (
        str(optima_audio_config.get("provider", DEFAULT_OPTIMA_AUDIO_PROVIDER)).strip().lower()
    )
    if provider != DEFAULT_OPTIMA_AUDIO_PROVIDER:
        raise ValueError(f"Proveedor Optima no soportado: {provider}")

    normalized_value = _normalize_value_for_runtime(value, optima_audio_config, prompt_type)
    if not normalized_value:
        raise ValueError("El valor normalizado quedó vacío.")
    rendered_text = build_optima_audio_text(prompt_type, normalized_value, config)

    api_key = _read_api_key(config)
    if not api_key:
        raise ValueError("No se encontró API key de ElevenLabs.")

    cache_dir = _get_cache_dir(optima_audio_config)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = build_optima_cache_key(
        prompt_type,
        normalized_value,
        _get_voice_id(config),
        _get_model_id(config),
        _get_version(optima_audio_config),
        final_text=rendered_text,
    )
    final_output_path = _safe_output_path(
        cache_dir,
        build_optima_audio_filename(prompt_type, cache_key),
    )

    if final_output_path.exists() and not force:
        _sync_optima_audio_artifacts(final_output_path, optima_audio_config)
        return final_output_path

    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".source", delete=False) as source_tmp:
        source_tmp_path = Path(source_tmp.name)
    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".wav", delete=False) as converted_tmp:
        converted_tmp_path = Path(converted_tmp.name)

    try:
        audio_bytes = _request_elevenlabs_audio(rendered_text, config, api_key)
        source_tmp_path.write_bytes(audio_bytes)
        _convert_audio_to_wav(source_tmp_path, converted_tmp_path)
        os.replace(converted_tmp_path, final_output_path)
        _sync_optima_audio_artifacts(final_output_path, optima_audio_config)
    finally:
        source_tmp_path.unlink(missing_ok=True)
        converted_tmp_path.unlink(missing_ok=True)

    return final_output_path


def get_or_generate_optima_audio(
    prompt_type: OptimaPromptType,
    value: str,
    config: Mapping[str, object],
    *,
    force: bool = False,
) -> Path | None:
    optima_audio_config = _get_optima_audio_config(config)
    if not bool(optima_audio_config.get("enabled", False)):
        return None

    try:
        if not force:
            cached_path = get_cached_optima_audio(prompt_type, value, config)
            if cached_path is not None:
                _sync_optima_audio_artifacts(cached_path, optima_audio_config)
                return cached_path
        return generate_optima_audio(prompt_type, value, config, force=force)
    except Exception:
        if bool(optima_audio_config.get("fallback_on_error", True)):
            return None
        raise


def _get_optima_audio_config(config: Mapping[str, object]) -> Mapping[str, object]:
    optima_audio_config = config.get("optima_audio")
    if isinstance(optima_audio_config, Mapping):
        return optima_audio_config
    return {}


def _resolve_optima_runtime_config(config: Mapping[str, object]) -> Mapping[str, object]:
    optima_audio_config = _get_optima_audio_config(config)
    if optima_audio_config:
        return optima_audio_config
    return config


def _normalize_prompt_type(prompt_type: OptimaPromptType) -> OptimaPromptType:
    if prompt_type not in {OPTIMA_SALUDO_NOMBRE, OPTIMA_DEUDA_BANCO}:
        raise ValueError("Tipo de prompt Optima no soportado.")
    return prompt_type


def _normalize_value_for_runtime(
    value: str,
    config: Mapping[str, object],
    prompt_type: OptimaPromptType,
) -> str:
    max_chars = _get_max_chars(config, prompt_type)
    normalized = unicodedata.normalize("NFKC", value)
    normalized = CONTROL_CHARS_PATTERN.sub(" ", normalized)
    normalized = WEIRD_SPACE_PATTERN.sub(" ", normalized)
    normalized = DANGEROUS_VALUE_PATTERN.sub(" ", normalized)
    normalized = MULTISPACE_PATTERN.sub(" ", normalized)
    return normalized.strip()[:max_chars].strip()


def _get_max_chars(config: Mapping[str, object], prompt_type: OptimaPromptType) -> int:
    config_key = "max_name_chars" if prompt_type == OPTIMA_SALUDO_NOMBRE else "max_bank_chars"
    default_value = (
        DEFAULT_OPTIMA_AUDIO_MAX_NAME_CHARS
        if prompt_type == OPTIMA_SALUDO_NOMBRE
        else DEFAULT_OPTIMA_AUDIO_MAX_BANK_CHARS
    )
    raw_value = config.get(config_key, default_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        return int(raw_value)
    return default_value


def _get_template(config: Mapping[str, object], prompt_type: OptimaPromptType) -> str:
    templates_config = _get_nested_mapping(config, "templates")
    template_key = PROMPT_TYPE_TO_TEMPLATE_KEY[_normalize_prompt_type(prompt_type)]
    default_template = (
        DEFAULT_OPTIMA_AUDIO_TEMPLATE_SALUDO_NOMBRE
        if prompt_type == OPTIMA_SALUDO_NOMBRE
        else DEFAULT_OPTIMA_AUDIO_TEMPLATE_DEUDA_BANCO
    )
    template = str(templates_config.get(template_key, default_template)).strip()
    return template or default_template


def _normalize_rendered_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = CONTROL_CHARS_PATTERN.sub(" ", normalized)
    normalized = WEIRD_SPACE_PATTERN.sub(" ", normalized)
    normalized = MULTISPACE_PATTERN.sub(" ", normalized)
    return normalized.strip()


def _read_api_key(config: Mapping[str, object]) -> str:
    _load_provider_env_if_needed(config)
    provider_config = _get_provider_config(config)
    api_key_env = str(provider_config.get("api_key_env", DEFAULT_ELEVENLABS_API_KEY_ENV)).strip()
    if not api_key_env:
        api_key_env = DEFAULT_ELEVENLABS_API_KEY_ENV
    return os.getenv(api_key_env, "").strip()


def _request_elevenlabs_audio(text: str, config: Mapping[str, object], api_key: str) -> bytes:
    provider_config = _get_provider_config(config)
    voice_id = _get_voice_id(config)
    model_id = _get_model_id(config)
    timeout_seconds = _get_timeout_seconds(provider_config)
    output_format = str(provider_config.get("output_format", "wav")).strip()

    query_params: dict[str, str] = {}
    if output_format and output_format.lower() != "wav":
        query_params["output_format"] = output_format

    request_url = DEFAULT_ELEVENLABS_API_URL.format(voice_id=parse.quote(voice_id, safe=""))
    if query_params:
        request_url = f"{request_url}?{parse.urlencode(query_params)}"

    payload = json.dumps({"text": text, "model_id": model_id}).encode("utf-8")
    http_request = request.Request(
        request_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/*",
            "xi-api-key": api_key,
        },
    )

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            response_body = response.read()
            if not isinstance(response_body, bytes):
                raise RuntimeError("La respuesta de ElevenLabs no devolvió bytes.")
            return response_body
    except error.HTTPError as exc:
        raise RuntimeError(f"ElevenLabs devolvió HTTP {exc.code}.") from exc
    except error.URLError as exc:
        raise RuntimeError("No fue posible contactar ElevenLabs.") from exc


def _convert_audio_to_wav(source_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-ar",
            "8000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _sync_optima_audio_artifacts(source_path: Path, config: Mapping[str, object]) -> None:
    _ensure_audio_file_readable(source_path)
    mirrored_paths = mirror_audio_file(source_path, _all_cache_dirs(config))
    for mirrored_path in mirrored_paths:
        _ensure_audio_file_readable(mirrored_path)


def _ensure_audio_file_readable(audio_path: Path) -> None:
    current_mode = audio_path.stat().st_mode & 0o777
    target_mode = current_mode | READABLE_AUDIO_FILE_MODE_BITS
    if current_mode != target_mode:
        audio_path.chmod(target_mode)


def _all_cache_dirs(config: Mapping[str, object]) -> tuple[Path, ...]:
    cache_dirs = [str(_get_cache_dir(config))]
    cache_dirs.extend(_get_mirror_dirs(config))
    return tuple(Path(path).expanduser().resolve() for path in cache_dirs if str(path).strip())


def _get_cache_dir(config: Mapping[str, object]) -> Path:
    cache_dir = str(config.get("cache_dir", DEFAULT_OPTIMA_AUDIO_CACHE_DIR)).strip()
    if not cache_dir:
        cache_dir = DEFAULT_OPTIMA_AUDIO_CACHE_DIR
    return Path(cache_dir).expanduser().resolve()


def _get_mirror_dirs(config: Mapping[str, object]) -> tuple[str, ...]:
    mirror_dirs = config.get("mirror_dirs")
    if isinstance(mirror_dirs, list):
        return tuple(str(path) for path in mirror_dirs if str(path).strip())
    return DEFAULT_OPTIMA_AUDIO_MIRROR_DIRS


def _get_version(config: Mapping[str, object]) -> str:
    version = str(config.get("version", DEFAULT_OPTIMA_AUDIO_VERSION)).strip()
    return version or DEFAULT_OPTIMA_AUDIO_VERSION


def _get_provider_config(config: Mapping[str, object]) -> Mapping[str, object]:
    optima_audio_config = _resolve_optima_runtime_config(config)
    optima_provider_config = _get_nested_mapping(optima_audio_config, "elevenlabs")
    if optima_provider_config:
        return optima_provider_config

    for section_name in ("name_audio", "client_flow_audio"):
        section_config = config.get(section_name)
        if not isinstance(section_config, Mapping):
            continue
        provider_config = _get_nested_mapping(section_config, "elevenlabs")
        if provider_config:
            return provider_config
    return {}


def _get_voice_id(config: Mapping[str, object]) -> str:
    _load_provider_env_if_needed(config)
    provider_config = _get_provider_config(config)
    voice_id_env = str(provider_config.get("voice_id_env", DEFAULT_ELEVENLABS_VOICE_ID_ENV)).strip()
    if voice_id_env:
        voice_id_from_env = os.getenv(voice_id_env, "").strip()
        if voice_id_from_env:
            return voice_id_from_env
    voice_id = str(provider_config.get("voice_id", "")).strip()
    if not voice_id:
        raise ValueError("Falta voice_id para audio Optima.")
    return voice_id


def _get_model_id(config: Mapping[str, object]) -> str:
    provider_config = _get_provider_config(config)
    model_id = str(provider_config.get("model_id", "")).strip()
    if not model_id:
        raise ValueError("Falta model_id para audio Optima.")
    return model_id


def _load_provider_env_if_needed(config: Mapping[str, object]) -> None:
    load_optima_env_file_if_needed(config)


def _get_timeout_seconds(config: Mapping[str, object]) -> int:
    timeout_value = config.get("timeout_seconds", DEFAULT_ELEVENLABS_TIMEOUT_SECONDS)
    if isinstance(timeout_value, int):
        return timeout_value
    if isinstance(timeout_value, str):
        return int(timeout_value)
    return DEFAULT_ELEVENLABS_TIMEOUT_SECONDS


def _get_nested_mapping(config: Mapping[str, object], key: str) -> Mapping[str, object]:
    nested_value = config.get(key)
    if isinstance(nested_value, Mapping):
        return nested_value
    return {}


def _get_filename_stem(prompt_type: OptimaPromptType) -> str:
    return PROMPT_TYPE_TO_STEM[_normalize_prompt_type(prompt_type)]


def _safe_output_path(base_dir: Path, filename: str) -> Path:
    output_path = (base_dir / filename).resolve()
    try:
        output_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError("La ruta de audio Optima queda fuera del directorio permitido.") from exc
    return output_path
