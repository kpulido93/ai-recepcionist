from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib import error, parse, request

from vicidial_vosk_cobranza_ivr.env_file import load_optima_env_file_if_needed

DEFAULT_ENV_FILE = Path("/etc/default/vicidial-vosk-cobranza-ivr")
DEFAULT_INSTALL_DIR = Path("/usr/share/asterisk/sounds/custom")
DEFAULT_MIRROR_DIRS = (
    Path("/usr/share/asterisk/sounds/en/custom"),
    Path("/var/lib/asterisk/sounds/custom"),
)
DEFAULT_TEMP_DIR = Path("/tmp/optima-9913-elevenlabs")
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_TIMEOUT_SECONDS = 30
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
READABLE_MODE_BITS = 0o644
SAFE_SLUG_PATTERN = re.compile(r"[^a-z0-9-]+")
CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
MULTISPACE_PATTERN = re.compile(r"\s+")

OPTIMA_9913_SALUDO: Literal["saludo"] = "saludo"
OPTIMA_9913_PREGUNTA_ABOGADO: Literal["pregunta_abogado"] = "pregunta_abogado"
OPTIMA_9913_DEUDA_BANCO: Literal["deuda_banco"] = "deuda_banco"
Optima9913PromptKind = Literal["saludo", "pregunta_abogado", "deuda_banco"]


@dataclass(frozen=True)
class Optima9913PromptSpec:
    kind: Optima9913PromptKind
    suffix: str
    leading_silence_ms: int


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    sample_rate: str
    channels: str
    bits: str
    encoding: str


PROMPT_SPECS: dict[Optima9913PromptKind, Optima9913PromptSpec] = {
    OPTIMA_9913_SALUDO: Optima9913PromptSpec(
        kind=OPTIMA_9913_SALUDO,
        suffix="saludo",
        leading_silence_ms=500,
    ),
    OPTIMA_9913_PREGUNTA_ABOGADO: Optima9913PromptSpec(
        kind=OPTIMA_9913_PREGUNTA_ABOGADO,
        suffix="pregunta-abogado",
        leading_silence_ms=250,
    ),
    OPTIMA_9913_DEUDA_BANCO: Optima9913PromptSpec(
        kind=OPTIMA_9913_DEUDA_BANCO,
        suffix="deuda-banco",
        leading_silence_ms=250,
    ),
}


def build_optima_9913_lab_text(
    prompt_kind: Optima9913PromptKind,
    *,
    person_name: str,
    bank_name: str,
) -> str:
    safe_name = _sanitize_prompt_value(person_name)
    safe_bank_name = _sanitize_prompt_value(bank_name)
    if prompt_kind == OPTIMA_9913_SALUDO:
        if not safe_name:
            raise ValueError("El saludo dinámico requiere nombre.")
        return f"Saludos. ¿Hablo con {safe_name}? Le escucho."
    if prompt_kind == OPTIMA_9913_PREGUNTA_ABOGADO:
        if not safe_bank_name:
            raise ValueError("La pregunta dinámica requiere banco.")
        return (
            "Gracias. Le llamamos de Jurídica Optima por una gestión pendiente con "
            f"{safe_bank_name}. ¿Desea que le comunique con un abogado para revisar su caso? "
            "Le escucho."
        )
    if prompt_kind == OPTIMA_9913_DEUDA_BANCO:
        if not safe_bank_name:
            raise ValueError("La respuesta de deuda requiere banco.")
        return (
            "Le estamos llamando por la deuda que tiene con "
            f"{safe_bank_name}, que usted ya conoce. Para más detalles puedo comunicarle "
            "con un abogado. ¿Desea que le comunique? Le escucho."
        )
    raise ValueError(f"Prompt 9913 no soportado: {prompt_kind}")


def build_optima_9913_lab_stem(
    lead_id: str,
    prompt_kind: Optima9913PromptKind,
) -> str:
    safe_lead_id = _safe_lead_slug(lead_id)
    prompt_spec = PROMPT_SPECS[prompt_kind]
    return f"optima-{safe_lead_id}-{prompt_spec.suffix}"


def build_optima_9913_lab_playback_path(
    lead_id: str,
    prompt_kind: Optima9913PromptKind,
) -> str:
    return f"custom/{build_optima_9913_lab_stem(lead_id, prompt_kind)}"


def get_or_generate_optima_9913_lab_audio(
    prompt_kind: Optima9913PromptKind,
    *,
    lead_id: str,
    person_name: str,
    bank_name: str,
    config: Mapping[str, object],
    install_dir: str | Path | None = None,
    mirror_dirs: Sequence[str | Path] | None = None,
    temp_dir: str | Path | None = None,
    force: bool = False,
) -> Path | None:
    resolved_install_dir = _resolve_install_dir(install_dir)
    resolved_target_dirs = resolve_target_dirs(resolved_install_dir, mirror_dirs)
    stem = build_optima_9913_lab_stem(lead_id, prompt_kind)
    primary_wav_path = resolved_target_dirs[0] / f"{stem}.wav"
    primary_slin_path = primary_wav_path.with_suffix(".slin")

    if (
        primary_wav_path.exists()
        and primary_slin_path.exists()
        and primary_slin_path.stat().st_size > 0
        and not force
    ):
        _sync_prompt_files(primary_wav_path, primary_slin_path, resolved_target_dirs)
        return primary_wav_path

    load_optima_env_file_if_needed(config, explicit_env_file=DEFAULT_ENV_FILE)
    api_key = _read_api_key(config)
    if not api_key:
        return None

    voice_id = _get_voice_id(config)
    if not voice_id:
        return None

    rendered_text = build_optima_9913_lab_text(
        prompt_kind,
        person_name=person_name,
        bank_name=bank_name,
    )
    prompt_spec = PROMPT_SPECS[prompt_kind]
    resolved_temp_dir = _resolve_temp_dir(temp_dir)
    for target_dir in resolved_target_dirs:
        target_dir.mkdir(parents=True, exist_ok=True)
    resolved_temp_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        dir=resolved_temp_dir,
        suffix=".source",
        delete=False,
    ) as source_tmp:
        source_path = Path(source_tmp.name)
    with tempfile.NamedTemporaryFile(dir=resolved_temp_dir, suffix=".wav", delete=False) as wav_tmp:
        wav_path = Path(wav_tmp.name)
    with tempfile.NamedTemporaryFile(
        dir=resolved_temp_dir,
        suffix=".slin",
        delete=False,
    ) as slin_tmp:
        slin_path = Path(slin_tmp.name)

    try:
        audio_bytes = _request_tts_audio(
            text=rendered_text,
            api_key=api_key,
            voice_id=voice_id,
            model_id=_get_model_id(config),
            output_format=_get_output_format(config),
            timeout_seconds=_get_timeout_seconds(config),
        )
        source_path.write_bytes(audio_bytes)
        _convert_to_wav(source_path, wav_path, prompt_spec.leading_silence_ms)
        _convert_to_slin(wav_path, slin_path)
        for target_dir in resolved_target_dirs:
            _install_prompt_files(wav_path, slin_path, target_dir / f"{stem}.wav")
        validation = validate_wav(primary_wav_path)
        if validation is None or not validation.ok or not validate_slin(primary_wav_path):
            raise RuntimeError("El audio dinámico 9913 no quedó en formato válido.")
        return primary_wav_path
    finally:
        source_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        slin_path.unlink(missing_ok=True)


def resolve_target_dirs(
    install_dir: Path,
    mirror_dirs: Sequence[str | Path] | None = None,
) -> tuple[Path, ...]:
    raw_dirs: list[Path] = [install_dir]
    raw_dirs.extend(path.expanduser().resolve() for path in DEFAULT_MIRROR_DIRS)
    if mirror_dirs is not None:
        raw_dirs.extend(Path(path).expanduser().resolve() for path in mirror_dirs)

    unique_dirs: list[Path] = []
    seen: set[str] = set()
    for raw_dir in raw_dirs:
        key = str(raw_dir)
        if key in seen:
            continue
        seen.add(key)
        unique_dirs.append(raw_dir)
    return tuple(unique_dirs)


def validate_wav(path: Path) -> ValidationResult | None:
    if not path.exists():
        return None
    try:
        sample_rate = _run_soxi_flag("-r", path)
        channels = _run_soxi_flag("-c", path)
        bits = _run_soxi_flag("-b", path)
        encoding = _run_soxi_flag("-e", path)
    except subprocess.CalledProcessError:
        return None

    normalized_encoding = encoding.casefold()
    ok = (
        sample_rate == "8000"
        and channels == "1"
        and bits == "16"
        and "signed integer" in normalized_encoding
    )
    return ValidationResult(
        ok=ok,
        sample_rate=sample_rate,
        channels=channels,
        bits=bits,
        encoding=encoding,
    )


def validate_slin(wav_path: Path) -> bool:
    slin_path = wav_path.with_suffix(".slin")
    return slin_path.exists() and slin_path.stat().st_size > 0


def format_validation(result: ValidationResult) -> str:
    status = "ok" if result.ok else "error"
    return (
        f"{status} sample_rate={result.sample_rate} channels={result.channels} "
        f"bits={result.bits} encoding={result.encoding}"
    )


def _request_tts_audio(
    *,
    text: str,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    timeout_seconds: int,
) -> bytes:
    query = parse.urlencode({"output_format": output_format}) if output_format else ""
    request_url = ELEVENLABS_API_URL.format(voice_id=parse.quote(voice_id, safe=""))
    if query:
        request_url = f"{request_url}?{query}"

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
    except error.HTTPError as exc:
        raise RuntimeError(f"ElevenLabs HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError("ElevenLabs request failed") from exc

    if not isinstance(response_body, bytes) or not response_body:
        raise RuntimeError("ElevenLabs returned an empty body")
    return response_body


def _convert_to_wav(source_path: Path, output_path: Path, leading_silence_ms: int) -> None:
    audio_filters = ["loudnorm=I=-18:TP=-2:LRA=7"]
    if leading_silence_ms > 0:
        audio_filters.append(f"adelay={leading_silence_ms}:all=1")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-af",
            ",".join(audio_filters),
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


def _convert_to_slin(source_wav_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_wav_path),
            "-ar",
            "8000",
            "-ac",
            "1",
            "-f",
            "s16le",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _install_prompt_files(
    source_wav_path: Path,
    source_slin_path: Path,
    final_wav_path: Path,
) -> None:
    _install_file(source_wav_path, final_wav_path)
    _install_file(source_slin_path, final_wav_path.with_suffix(".slin"))


def _install_file(source_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, final_path)
    final_path.chmod(READABLE_MODE_BITS)
    _maybe_chown_asterisk(final_path)


def _sync_prompt_files(
    source_wav_path: Path,
    source_slin_path: Path,
    target_dirs: Sequence[Path],
) -> None:
    source_wav_path.chmod(READABLE_MODE_BITS)
    source_slin_path.chmod(READABLE_MODE_BITS)
    _maybe_chown_asterisk(source_wav_path)
    _maybe_chown_asterisk(source_slin_path)
    for target_dir in target_dirs[1:]:
        _install_prompt_files(source_wav_path, source_slin_path, target_dir / source_wav_path.name)


def _maybe_chown_asterisk(path: Path) -> None:
    import grp
    import pwd

    try:
        user_info = pwd.getpwnam("asterisk")
        group_info = grp.getgrnam("asterisk")
    except KeyError:
        return
    os.chown(path, user_info.pw_uid, group_info.gr_gid)


def _read_api_key(config: Mapping[str, object]) -> str:
    provider_config = _get_provider_config(config)
    api_key_env = str(provider_config.get("api_key_env", "ELEVENLABS_API_KEY")).strip()
    return os.getenv(api_key_env, "").strip()


def _get_voice_id(config: Mapping[str, object]) -> str:
    provider_config = _get_provider_config(config)
    voice_id_env = str(provider_config.get("voice_id_env", "ELEVENLABS_VOICE_ID")).strip()
    if voice_id_env:
        voice_id_from_env = os.getenv(voice_id_env, "").strip()
        if voice_id_from_env:
            return voice_id_from_env
    return str(provider_config.get("voice_id", "")).strip()


def _get_model_id(config: Mapping[str, object]) -> str:
    provider_config = _get_provider_config(config)
    model_id = str(provider_config.get("model_id", DEFAULT_MODEL_ID)).strip()
    return model_id or DEFAULT_MODEL_ID


def _get_output_format(config: Mapping[str, object]) -> str:
    provider_config = _get_provider_config(config)
    output_format = str(provider_config.get("output_format", DEFAULT_OUTPUT_FORMAT)).strip()
    return output_format or DEFAULT_OUTPUT_FORMAT


def _get_timeout_seconds(config: Mapping[str, object]) -> int:
    provider_config = _get_provider_config(config)
    timeout_value = provider_config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout_value, int):
        return timeout_value
    if isinstance(timeout_value, str):
        return int(timeout_value)
    return DEFAULT_TIMEOUT_SECONDS


def _get_provider_config(config: Mapping[str, object]) -> Mapping[str, object]:
    for section_name in ("optima_audio", "name_audio", "client_flow_audio"):
        section_config = config.get(section_name)
        if not isinstance(section_config, Mapping):
            continue
        provider_config = section_config.get("elevenlabs")
        if isinstance(provider_config, Mapping):
            return provider_config
    return {}


def _resolve_install_dir(install_dir: str | Path | None) -> Path:
    base_dir = DEFAULT_INSTALL_DIR if install_dir is None else Path(install_dir)
    return base_dir.expanduser().resolve()


def _resolve_temp_dir(temp_dir: str | Path | None) -> Path:
    base_dir = DEFAULT_TEMP_DIR if temp_dir is None else Path(temp_dir)
    return base_dir.expanduser().resolve()


def _sanitize_prompt_value(value: str, *, max_len: int = 120) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = CONTROL_CHARS_PATTERN.sub(" ", normalized)
    normalized = MULTISPACE_PATTERN.sub(" ", normalized)
    return normalized.strip()[:max_len].strip()


def _safe_lead_slug(lead_id: str) -> str:
    normalized = unicodedata.normalize("NFKD", lead_id)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = SAFE_SLUG_PATTERN.sub("-", ascii_value.lower()).strip("-")
    if not slug:
        raise ValueError("El lead_id no produjo un slug válido.")
    return slug


def _run_soxi_flag(flag: str, path: Path) -> str:
    result = subprocess.run(
        ["soxi", flag, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
