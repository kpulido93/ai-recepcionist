from __future__ import annotations

import json
import os
import subprocess
import tempfile
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request

from vicidial_vosk_cobranza_ivr.prompt_builder import mirror_audio_file, sanitize_prompt_value

DEFAULT_CLIENT_FLOW_AUDIO_CACHE_DIR = "/var/lib/asterisk/sounds/custom/generated/client-flow-9912"
DEFAULT_CLIENT_FLOW_AUDIO_MIRROR_DIRS = (
    "/usr/share/asterisk/sounds/custom/generated/client-flow-9912",
)
DEFAULT_CLIENT_FLOW_AUDIO_PLAYBACK_PREFIX = "custom/generated/client-flow-9912"
DEFAULT_CLIENT_FLOW_AUDIO_VERSION = "v2-client-flow-9912"
DEFAULT_CLIENT_FLOW_AUDIO_PROVIDER = "elevenlabs"
DEFAULT_ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_ELEVENLABS_API_KEY_ENV = "ELEVENLABS_API_KEY"
DEFAULT_ELEVENLABS_VOICE_ID_ENV = "ELEVENLABS_VOICE_ID"
DEFAULT_ELEVENLABS_TIMEOUT_SECONDS = 15
DEFAULT_CLIENT_FLOW_AUDIO_TRAILING_SILENCE_MS = 800
READABLE_AUDIO_FILE_MODE_BITS = 0o444


@dataclass(frozen=True)
class ClientFlowPrompt:
    slot: str
    text: str
    playback_path: str


def build_client_flow_prompts(
    config: Mapping[str, object],
    *,
    debtor: str | None = None,
    bank: str | None = None,
    gender: str | None = None,
) -> tuple[ClientFlowPrompt, ...]:
    client_flow_config = _get_client_flow_audio_config(config)
    prompts_config = _get_nested_mapping(client_flow_config, "prompts")
    defaults_config = _get_nested_mapping(client_flow_config, "defaults")
    safe_debtor = sanitize_prompt_value(debtor) or sanitize_prompt_value(
        str(defaults_config.get("debtor", "Kevin"))
    )
    safe_bank = sanitize_prompt_value(bank) or sanitize_prompt_value(
        str(defaults_config.get("bank", "Banco de Prueba"))
    )
    safe_gender = _normalize_gender(gender or str(defaults_config.get("gender", "unknown")))
    greeting_template = _resolve_greeting_template(prompts_config, safe_gender)
    bank_template = str(
        prompts_config.get(
            "bank",
            "Le llamo con relación a la deuda que usted mantiene con el {bank}.",
        )
    ).strip()
    debt_known_template = str(
        prompts_config.get(
            "debt_known",
            "Le estamos llamando por la deuda que tiene con {bank}, que usted ya conoce.",
        )
    ).strip()

    greeting_text = _normalize_text(greeting_template.format(debtor=safe_debtor, name=safe_debtor))
    bank_text = _normalize_text(bank_template.format(bank=safe_bank))
    debt_known_text = _normalize_text(debt_known_template.format(bank=safe_bank))
    return (
        ClientFlowPrompt(
            slot="greeting",
            text=greeting_text,
            playback_path=build_client_flow_playback_path("greeting", config),
        ),
        ClientFlowPrompt(
            slot="bank",
            text=bank_text,
            playback_path=build_client_flow_playback_path("bank", config),
        ),
        ClientFlowPrompt(
            slot="deuda-conocida",
            text=debt_known_text,
            playback_path=build_client_flow_playback_path("deuda-conocida", config),
        ),
    )


def build_client_flow_playback_path(slot: str, config: Mapping[str, object]) -> str:
    client_flow_config = _get_client_flow_audio_config(config)
    playback_prefix = str(
        client_flow_config.get("playback_prefix", DEFAULT_CLIENT_FLOW_AUDIO_PLAYBACK_PREFIX)
    ).strip("/")
    return f"{playback_prefix}/{slot}"


def get_cached_client_flow_audio(
    slot: str,
    text: str,
    config: Mapping[str, object],
) -> Path | None:
    client_flow_config = _get_client_flow_audio_config(config)
    if not bool(client_flow_config.get("enabled", False)):
        return None
    if not bool(client_flow_config.get("cache_enabled", True)):
        return None

    cache_dir = _get_cache_dir(client_flow_config)
    audio_path = _build_slot_audio_path(cache_dir, slot)
    metadata_path = _build_slot_metadata_path(cache_dir, slot)
    if not audio_path.exists():
        return None
    if not metadata_path.exists():
        return audio_path

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None

    if not _metadata_matches(metadata, text, client_flow_config):
        return None
    return audio_path


def generate_client_flow_audio(
    slot: str,
    text: str,
    config: Mapping[str, object],
) -> Path:
    client_flow_config = _get_client_flow_audio_config(config)
    if not bool(client_flow_config.get("enabled", False)):
        raise ValueError("La generación client_flow_audio está desactivada.")

    provider = (
        str(client_flow_config.get("provider", DEFAULT_CLIENT_FLOW_AUDIO_PROVIDER)).strip().lower()
    )
    if provider != DEFAULT_CLIENT_FLOW_AUDIO_PROVIDER:
        raise ValueError(f"Proveedor client_flow_audio no soportado: {provider}")

    normalized_text = _normalize_text(text)
    if not normalized_text:
        raise ValueError("El prompt dinámico quedó vacío.")

    api_key = _read_api_key(client_flow_config)
    if not api_key:
        raise ValueError("No se encontró API key de ElevenLabs.")

    cache_dir = _get_cache_dir(client_flow_config)
    cache_dir.mkdir(parents=True, exist_ok=True)
    final_output_path = _build_slot_audio_path(cache_dir, slot)
    metadata_path = _build_slot_metadata_path(cache_dir, slot)
    trailing_silence_ms = _get_trailing_silence_ms(client_flow_config)

    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".source", delete=False) as source_tmp:
        source_tmp_path = Path(source_tmp.name)
    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".wav", delete=False) as converted_tmp:
        converted_tmp_path = Path(converted_tmp.name)
    with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".wav", delete=False) as padded_tmp:
        padded_tmp_path = Path(padded_tmp.name)

    try:
        audio_bytes = _request_elevenlabs_audio(normalized_text, client_flow_config, api_key)
        source_tmp_path.write_bytes(audio_bytes)
        _convert_audio_to_wav(source_tmp_path, converted_tmp_path)
        _append_trailing_silence_to_wav(
            converted_tmp_path,
            padded_tmp_path,
            trailing_silence_ms=trailing_silence_ms,
        )
        os.replace(padded_tmp_path, final_output_path)
        _write_metadata(metadata_path, normalized_text, client_flow_config)
        _sync_client_flow_artifacts(final_output_path, client_flow_config)
    finally:
        source_tmp_path.unlink(missing_ok=True)
        converted_tmp_path.unlink(missing_ok=True)
        padded_tmp_path.unlink(missing_ok=True)

    return final_output_path


def get_or_generate_client_flow_audio(
    slot: str,
    text: str,
    config: Mapping[str, object],
) -> Path | None:
    client_flow_config = _get_client_flow_audio_config(config)
    if not bool(client_flow_config.get("enabled", False)):
        return None

    try:
        cached_path = get_cached_client_flow_audio(slot, text, config)
        if cached_path is not None:
            _sync_client_flow_artifacts(cached_path, client_flow_config)
            return cached_path
        return generate_client_flow_audio(slot, text, config)
    except Exception:
        if bool(client_flow_config.get("fallback_on_error", True)):
            return None
        raise


def _metadata_matches(
    metadata: Mapping[str, object],
    text: str,
    config: Mapping[str, object],
) -> bool:
    return (
        str(metadata.get("text", "")).strip() == text
        and str(metadata.get("voice_id", "")).strip() == _get_voice_id(config)
        and str(metadata.get("model_id", "")).strip() == _get_model_id(config)
        and str(metadata.get("version", "")).strip() == _get_version(config)
    )


def _write_metadata(metadata_path: Path, text: str, config: Mapping[str, object]) -> None:
    payload = {
        "text": text,
        "voice_id": _get_voice_id(config),
        "model_id": _get_model_id(config),
        "version": _get_version(config),
    }
    tmp_path = metadata_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, metadata_path)


def _sync_client_flow_artifacts(source_path: Path, config: Mapping[str, object]) -> None:
    _ensure_audio_file_readable(source_path)
    mirrored_paths = mirror_audio_file(source_path, _get_mirror_dirs(config))
    for mirrored_path in mirrored_paths:
        _ensure_audio_file_readable(mirrored_path)


def _ensure_audio_file_readable(audio_path: Path) -> None:
    current_mode = audio_path.stat().st_mode & 0o777
    target_mode = current_mode | READABLE_AUDIO_FILE_MODE_BITS
    if current_mode != target_mode:
        audio_path.chmod(target_mode)


def _request_elevenlabs_audio(text: str, config: Mapping[str, object], api_key: str) -> bytes:
    voice_id = _get_voice_id(config)
    model_id = _get_model_id(config)
    elevenlabs_config = _get_nested_mapping(config, "elevenlabs")
    timeout_seconds = _get_timeout_seconds(elevenlabs_config)
    output_format = str(elevenlabs_config.get("output_format", "wav")).strip()

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
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _append_trailing_silence_to_wav(
    source_path: Path,
    output_path: Path,
    *,
    trailing_silence_ms: int,
) -> None:
    with wave.open(str(source_path), "rb") as source_wav:
        channels = source_wav.getnchannels()
        sample_width = source_wav.getsampwidth()
        sample_rate = source_wav.getframerate()
        frame_count = source_wav.getnframes()
        audio_frames = source_wav.readframes(frame_count)

    silence_frame_count = max(0, int(sample_rate * trailing_silence_ms / 1000))
    silence_bytes = b"\x00" * silence_frame_count * channels * sample_width

    with wave.open(str(output_path), "wb") as output_wav:
        output_wav.setnchannels(channels)
        output_wav.setsampwidth(sample_width)
        output_wav.setframerate(sample_rate)
        output_wav.writeframes(audio_frames + silence_bytes)


def _get_client_flow_audio_config(config: Mapping[str, object]) -> Mapping[str, object]:
    client_flow_config = config.get("client_flow_audio")
    if isinstance(client_flow_config, Mapping):
        return client_flow_config
    return {}


def _get_nested_mapping(config: Mapping[str, object], key: str) -> Mapping[str, object]:
    nested_value = config.get(key)
    if isinstance(nested_value, Mapping):
        return nested_value
    return {}


def _get_cache_dir(config: Mapping[str, object]) -> Path:
    cache_dir = str(config.get("cache_dir", DEFAULT_CLIENT_FLOW_AUDIO_CACHE_DIR)).strip()
    return Path(cache_dir or DEFAULT_CLIENT_FLOW_AUDIO_CACHE_DIR).expanduser().resolve()


def _get_mirror_dirs(config: Mapping[str, object]) -> tuple[Path, ...]:
    mirror_dirs = config.get("mirror_dirs")
    if isinstance(mirror_dirs, list):
        return tuple(
            Path(str(path)).expanduser().resolve() for path in mirror_dirs if str(path).strip()
        )
    return tuple(
        Path(path).expanduser().resolve() for path in DEFAULT_CLIENT_FLOW_AUDIO_MIRROR_DIRS
    )


def _read_api_key(config: Mapping[str, object]) -> str:
    elevenlabs_config = _get_nested_mapping(config, "elevenlabs")
    api_key_env = str(elevenlabs_config.get("api_key_env", DEFAULT_ELEVENLABS_API_KEY_ENV)).strip()
    return os.getenv(api_key_env or DEFAULT_ELEVENLABS_API_KEY_ENV, "").strip()


def _get_voice_id(config: Mapping[str, object]) -> str:
    elevenlabs_config = _get_nested_mapping(config, "elevenlabs")
    voice_id_env = str(
        elevenlabs_config.get("voice_id_env", DEFAULT_ELEVENLABS_VOICE_ID_ENV)
    ).strip()
    if voice_id_env:
        voice_id_from_env = os.getenv(voice_id_env, "").strip()
        if voice_id_from_env:
            return voice_id_from_env
    voice_id = str(elevenlabs_config.get("voice_id", "")).strip()
    if not voice_id:
        raise ValueError("Falta voice_id para client_flow_audio.")
    return voice_id


def _get_model_id(config: Mapping[str, object]) -> str:
    elevenlabs_config = _get_nested_mapping(config, "elevenlabs")
    model_id = str(elevenlabs_config.get("model_id", "")).strip()
    if not model_id:
        raise ValueError("Falta model_id para client_flow_audio.")
    return model_id


def _get_version(config: Mapping[str, object]) -> str:
    version = str(config.get("version", DEFAULT_CLIENT_FLOW_AUDIO_VERSION)).strip()
    return version or DEFAULT_CLIENT_FLOW_AUDIO_VERSION


def _get_timeout_seconds(config: Mapping[str, object]) -> int:
    timeout_value = config.get("timeout_seconds", DEFAULT_ELEVENLABS_TIMEOUT_SECONDS)
    if isinstance(timeout_value, int):
        return timeout_value
    if isinstance(timeout_value, str):
        return int(timeout_value)
    return DEFAULT_ELEVENLABS_TIMEOUT_SECONDS


def _get_trailing_silence_ms(config: Mapping[str, object]) -> int:
    raw_value = config.get("trailing_silence_ms", DEFAULT_CLIENT_FLOW_AUDIO_TRAILING_SILENCE_MS)
    if isinstance(raw_value, int):
        return max(0, raw_value)
    if isinstance(raw_value, str):
        return max(0, int(raw_value))
    return DEFAULT_CLIENT_FLOW_AUDIO_TRAILING_SILENCE_MS


def _build_slot_audio_path(cache_dir: Path, slot: str) -> Path:
    return _safe_output_path(cache_dir, f"{slot}.wav")


def _build_slot_metadata_path(cache_dir: Path, slot: str) -> Path:
    return _safe_output_path(cache_dir, f"{slot}.json")


def _safe_output_path(base_dir: Path, filename: str) -> Path:
    output_path = (base_dir / filename).resolve()
    try:
        output_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(
            "La ruta de client_flow_audio queda fuera del directorio permitido."
        ) from exc
    return output_path


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _normalize_gender(value: str) -> str:
    normalized_value = value.strip().lower()
    if normalized_value in {"male", "female", "unknown"}:
        return normalized_value
    return "unknown"


def _resolve_greeting_template(prompts_config: Mapping[str, object], gender: str) -> str:
    greeting_templates = _get_nested_mapping(prompts_config, "greeting_templates")
    gender_template = str(
        greeting_templates.get(gender, greeting_templates.get("unknown", ""))
    ).strip()
    if gender_template:
        return gender_template

    legacy_template = str(prompts_config.get("greeting", "")).strip()
    if legacy_template:
        return legacy_template

    if gender == "male":
        return "Saludos. ¿Cómo está, señor {name}?"
    if gender == "female":
        return "Saludos. ¿Cómo está, señora {name}?"
    return "Saludos. ¿Cómo está, {name}?"
