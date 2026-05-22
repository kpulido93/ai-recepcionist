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
from urllib import error, parse, request

from vicidial_vosk_cobranza_ivr.prompt_builder import mirror_audio_file

CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
DANGEROUS_NAME_PATTERN = re.compile(r"""[\\/:"'`$;&|<>]+""")
WEIRD_SPACE_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]+")
MULTISPACE_PATTERN = re.compile(r"\s+")
SAFE_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
DEFAULT_NAME_AUDIO_PROVIDER = "elevenlabs"
DEFAULT_NAME_AUDIO_CACHE_DIR = "/var/lib/asterisk/sounds/custom/generated/names"
DEFAULT_NAME_AUDIO_MIRROR_DIRS = ("/usr/share/asterisk/sounds/custom/generated/names",)
DEFAULT_NAME_AUDIO_PLAYBACK_PREFIX = "custom/generated/names"
DEFAULT_NAME_AUDIO_VERSION = "v1"
DEFAULT_NAME_AUDIO_MAX_NAME_CHARS = 80
DEFAULT_ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_ELEVENLABS_API_KEY_ENV = "ELEVENLABS_API_KEY"
DEFAULT_ELEVENLABS_VOICE_ID_ENV = "ELEVENLABS_VOICE_ID"
DEFAULT_ELEVENLABS_TIMEOUT_SECONDS = 15


def normalize_person_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name)
    normalized = CONTROL_CHARS_PATTERN.sub(" ", normalized)
    normalized = WEIRD_SPACE_PATTERN.sub(" ", normalized)
    normalized = DANGEROUS_NAME_PATTERN.sub(" ", normalized)
    normalized = MULTISPACE_PATTERN.sub(" ", normalized)
    return normalized.strip()[:DEFAULT_NAME_AUDIO_MAX_NAME_CHARS]


def safe_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_value = ascii_value.lower()
    slug = SAFE_SLUG_PATTERN.sub("-", ascii_value)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-._")
    return slug[:48] or "name"


def build_name_cache_key(name: str, voice_id: str, model_id: str, version: str) -> str:
    normalized_name = normalize_person_name(name)
    slug = safe_slug(normalized_name)
    digest_source = "|".join([normalized_name, voice_id.strip(), model_id.strip(), version.strip()])
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
    return f"{slug}-{digest}"


def get_cached_name_audio(name: str, config: Mapping[str, object]) -> Path | None:
    name_audio_config = _get_name_audio_config(config)
    if not bool(name_audio_config.get("enabled", False)):
        return None
    if not bool(name_audio_config.get("cache_enabled", True)):
        return None

    normalized_name = _normalize_name_for_runtime(name, name_audio_config)
    if not normalized_name:
        return None

    cache_key = build_name_cache_key(
        normalized_name,
        _get_voice_id(name_audio_config),
        _get_model_id(name_audio_config),
        _get_version(name_audio_config),
    )

    for base_dir in _all_cache_dirs(name_audio_config):
        candidate = _safe_output_path(base_dir, f"{cache_key}.wav")
        if candidate.exists():
            return candidate
    return None


def generate_name_audio(name: str, config: Mapping[str, object]) -> Path:
    name_audio_config = _get_name_audio_config(config)
    if not bool(name_audio_config.get("enabled", False)):
        raise ValueError("La generación de audio de nombre está desactivada.")

    provider = str(name_audio_config.get("provider", DEFAULT_NAME_AUDIO_PROVIDER)).strip().lower()
    if provider != DEFAULT_NAME_AUDIO_PROVIDER:
        raise ValueError(f"Proveedor de nombre no soportado: {provider}")

    normalized_name = _normalize_name_for_runtime(name, name_audio_config)
    if not normalized_name:
        raise ValueError("El nombre normalizado quedó vacío.")

    api_key = _read_api_key(name_audio_config)
    if not api_key:
        raise ValueError("No se encontró API key de ElevenLabs.")

    cache_dir = _get_cache_dir(name_audio_config)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = build_name_cache_key(
        normalized_name,
        _get_voice_id(name_audio_config),
        _get_model_id(name_audio_config),
        _get_version(name_audio_config),
    )
    final_output_path = _safe_output_path(cache_dir, f"{cache_key}.wav")

    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".source", delete=False) as source_tmp:
        source_tmp_path = Path(source_tmp.name)
    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".wav", delete=False) as converted_tmp:
        converted_tmp_path = Path(converted_tmp.name)

    try:
        audio_bytes = _request_elevenlabs_audio(normalized_name, name_audio_config, api_key)
        source_tmp_path.write_bytes(audio_bytes)
        _convert_audio_to_wav(source_tmp_path, converted_tmp_path)
        os.replace(converted_tmp_path, final_output_path)
        _mirror_name_audio(final_output_path, name_audio_config)
    finally:
        source_tmp_path.unlink(missing_ok=True)
        converted_tmp_path.unlink(missing_ok=True)

    return final_output_path


def get_or_generate_name_audio(name: str, config: Mapping[str, object]) -> Path | None:
    name_audio_config = _get_name_audio_config(config)
    if not bool(name_audio_config.get("enabled", False)):
        return None

    cached_path = get_cached_name_audio(name, config)
    if cached_path is not None:
        return cached_path

    try:
        return generate_name_audio(name, config)
    except Exception:
        if bool(name_audio_config.get("fallback_on_error", True)):
            return None
        raise


def _get_name_audio_config(config: Mapping[str, object]) -> Mapping[str, object]:
    name_audio_config = config.get("name_audio")
    if isinstance(name_audio_config, Mapping):
        return name_audio_config
    return {}


def _normalize_name_for_runtime(name: str, config: Mapping[str, object]) -> str:
    max_name_chars_value = config.get("max_name_chars", DEFAULT_NAME_AUDIO_MAX_NAME_CHARS)
    if isinstance(max_name_chars_value, int):
        max_name_chars = max_name_chars_value
    elif isinstance(max_name_chars_value, str):
        max_name_chars = int(max_name_chars_value)
    else:
        max_name_chars = DEFAULT_NAME_AUDIO_MAX_NAME_CHARS

    normalized_name = normalize_person_name(name)
    return normalized_name[:max_name_chars].strip()


def _read_api_key(config: Mapping[str, object]) -> str:
    elevenlabs_config = _get_elevenlabs_config(config)
    api_key_env = str(elevenlabs_config.get("api_key_env", DEFAULT_ELEVENLABS_API_KEY_ENV)).strip()
    if not api_key_env:
        api_key_env = DEFAULT_ELEVENLABS_API_KEY_ENV
    api_key = os.getenv(api_key_env, "").strip()
    return api_key


def _request_elevenlabs_audio(name: str, config: Mapping[str, object], api_key: str) -> bytes:
    elevenlabs_config = _get_elevenlabs_config(config)
    voice_id = _get_voice_id(config)
    model_id = _get_model_id(config)
    timeout_seconds = _get_timeout_seconds(elevenlabs_config)
    output_format = str(elevenlabs_config.get("output_format", "wav")).strip()

    query_params: dict[str, str] = {}
    if output_format and output_format.lower() != "wav":
        query_params["output_format"] = output_format

    request_url = DEFAULT_ELEVENLABS_API_URL.format(voice_id=parse.quote(voice_id, safe=""))
    if query_params:
        request_url = f"{request_url}?{parse.urlencode(query_params)}"

    payload = json.dumps({"text": name, "model_id": model_id}).encode("utf-8")
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
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _mirror_name_audio(source_path: Path, config: Mapping[str, object]) -> None:
    mirror_dirs = _get_mirror_dirs(config)
    if not mirror_dirs:
        return
    try:
        mirror_audio_file(source_path, mirror_dirs)
    except OSError:
        return


def _all_cache_dirs(config: Mapping[str, object]) -> tuple[Path, ...]:
    cache_dirs = [str(_get_cache_dir(config))]
    cache_dirs.extend(_get_mirror_dirs(config))
    return tuple(Path(path).expanduser().resolve() for path in cache_dirs if str(path).strip())


def _get_cache_dir(config: Mapping[str, object]) -> Path:
    cache_dir = str(config.get("cache_dir", DEFAULT_NAME_AUDIO_CACHE_DIR)).strip()
    if not cache_dir:
        cache_dir = DEFAULT_NAME_AUDIO_CACHE_DIR
    return Path(cache_dir).expanduser().resolve()


def _get_mirror_dirs(config: Mapping[str, object]) -> tuple[str, ...]:
    mirror_dirs = config.get("mirror_dirs")
    if isinstance(mirror_dirs, list):
        return tuple(str(path) for path in mirror_dirs if str(path).strip())
    return DEFAULT_NAME_AUDIO_MIRROR_DIRS


def _get_version(config: Mapping[str, object]) -> str:
    version = str(config.get("version", DEFAULT_NAME_AUDIO_VERSION)).strip()
    if not version:
        return DEFAULT_NAME_AUDIO_VERSION
    return version


def _get_voice_id(config: Mapping[str, object]) -> str:
    elevenlabs_config = _get_elevenlabs_config(config)
    voice_id_env = str(
        elevenlabs_config.get("voice_id_env", DEFAULT_ELEVENLABS_VOICE_ID_ENV)
    ).strip()
    if voice_id_env:
        voice_id_from_env = os.getenv(voice_id_env, "").strip()
        if voice_id_from_env:
            return voice_id_from_env
    voice_id = str(elevenlabs_config.get("voice_id", "")).strip()
    if not voice_id:
        raise ValueError("Falta voice_id para audio de nombre.")
    return voice_id


def _get_model_id(config: Mapping[str, object]) -> str:
    elevenlabs_config = _get_elevenlabs_config(config)
    model_id = str(elevenlabs_config.get("model_id", "")).strip()
    if not model_id:
        raise ValueError("Falta model_id para audio de nombre.")
    return model_id


def _get_timeout_seconds(config: Mapping[str, object]) -> int:
    timeout_value = config.get("timeout_seconds", DEFAULT_ELEVENLABS_TIMEOUT_SECONDS)
    if isinstance(timeout_value, int):
        return timeout_value
    if isinstance(timeout_value, str):
        return int(timeout_value)
    return DEFAULT_ELEVENLABS_TIMEOUT_SECONDS


def _get_elevenlabs_config(config: Mapping[str, object]) -> Mapping[str, object]:
    elevenlabs_config = config.get("elevenlabs")
    if isinstance(elevenlabs_config, Mapping):
        return elevenlabs_config
    return {}


def _safe_output_path(base_dir: Path, filename: str) -> Path:
    output_path = (base_dir / filename).resolve()
    try:
        output_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(
            "La ruta de audio de nombre queda fuera del directorio permitido."
        ) from exc
    return output_path
