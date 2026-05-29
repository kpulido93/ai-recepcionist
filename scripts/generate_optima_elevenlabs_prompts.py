#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request

import yaml


def _bootstrap_src_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


_bootstrap_src_path()

from vicidial_vosk_cobranza_ivr.config import PROJECT_ROOT  # noqa: E402
from vicidial_vosk_cobranza_ivr.lead_context import (  # noqa: E402
    load_lead_context_from_csv,
    sanitize_lead_value,
)

DEFAULT_INSTALL_DIR = "/var/lib/asterisk/sounds/custom"
DEFAULT_MIRROR_DIR = "/usr/share/asterisk/sounds/custom"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_TTS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_TEMP_DIR = Path("/tmp/optima-elevenlabs")
DEFAULT_LEAD_ID = "lab-1003"
READABLE_AUDIO_MODE_BITS = 0o644


@dataclass(frozen=True)
class LeadPromptContext:
    lead_id: str | None
    client_name: str | None
    bank_name: str | None


@dataclass(frozen=True)
class PromptSpec:
    filename_stem: str
    template: str
    requires_name: bool = False
    requires_bank: bool = False


@dataclass(frozen=True)
class PreparedPrompt:
    filename_stem: str
    rendered_text: str
    output_path: Path


@dataclass(frozen=True)
class ProviderSettings:
    voice_id: str
    model_id: str
    output_format: str
    timeout_seconds: int
    voice_source: str


@dataclass(frozen=True)
class PromptResult:
    filename: str
    status: str
    installed_path: str
    validation: str


PROMPT_SPECS = (
    PromptSpec(
        "optima-01-saludo-validacion",
        "Saludos. ¿Hablo con {nombre}? Le escucho.",
        requires_name=True,
    ),
    PromptSpec(
        "optima-02-pregunta-abogado",
        (
            "Gracias. Le llamamos de Jurídica Optima por una gestión pendiente con {banco}. "
            "¿Desea que le comunique con un abogado para revisar su caso? Le escucho."
        ),
        requires_bank=True,
    ),
    PromptSpec(
        "optima-03-deuda-banco",
        (
            "Le estamos llamando por la deuda que tiene con {banco}, que usted ya conoce. "
            "Para más detalles puedo comunicarle con un abogado. ¿Desea que le comunique? "
            "Le escucho."
        ),
        requires_bank=True,
    ),
    PromptSpec(
        "optima-04-permitame-terminar",
        "Permítame terminar y con gusto le escucho.",
    ),
    PromptSpec(
        "optima-05-no-entendi",
        "Disculpe, no le escuché bien. ¿Desea que le comunique con un abogado? Le escucho.",
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera e instala prompts ElevenLabs para el flujo Optima 9913."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra qué archivos generaría; no llama a ElevenLabs ni instala archivos.",
    )
    parser.add_argument(
        "--install-dir",
        default=DEFAULT_INSTALL_DIR,
        help="Ruta de instalación principal para Asterisk.",
    )
    parser.add_argument(
        "--mirror-dir",
        default=DEFAULT_MIRROR_DIR,
        help="Ruta espejo opcional para Asterisk si existe.",
    )
    parser.add_argument(
        "--lead-id",
        default=DEFAULT_LEAD_ID,
        help="Lead de laboratorio a usar para resolver nombre y banco.",
    )
    parser.add_argument(
        "--client-name",
        default="",
        help="Sobrescribe el nombre del cliente sin depender del CSV.",
    )
    parser.add_argument(
        "--bank-name",
        default="",
        help="Sobrescribe el banco sin depender del CSV.",
    )
    parser.add_argument(
        "--temp-dir",
        default=str(DEFAULT_TEMP_DIR),
        help="Directorio temporal fuera del repo para descargas y conversión.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    install_dir = Path(args.install_dir).expanduser().resolve()
    mirror_dir = Path(args.mirror_dir).expanduser().resolve()
    temp_dir = Path(args.temp_dir).expanduser().resolve()
    prompt_context = resolve_prompt_context(
        config,
        lead_id=args.lead_id,
        client_name=args.client_name,
        bank_name=args.bank_name,
    )
    prepared_prompts = build_prepared_prompts(prompt_context, install_dir)
    provider_settings = resolve_provider_settings(config)
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()

    print(f"ELEVENLABS_API_KEY available: {'yes' if api_key else 'no'}")
    print(f"ELEVENLABS_VOICE_ID available: {'yes' if os.getenv('ELEVENLABS_VOICE_ID') else 'no'}")
    print(f"resolved_client_name: {'yes' if prompt_context.client_name else 'no'}")
    print(f"resolved_bank_name: {'yes' if prompt_context.bank_name else 'no'}")
    print(f"voice_id_source: {provider_settings.voice_source}")
    print(f"install_dir: {install_dir}")
    print(f"mirror_dir_exists: {'yes' if mirror_dir.exists() else 'no'}")

    if args.dry_run:
        for prompt in prepared_prompts:
            print(f"dry_run filename={prompt.filename_stem}.wav install={prompt.output_path}")
        return 0

    if not api_key:
        print("generation_skipped: ELEVENLABS_API_KEY not available")
        return 0

    results = generate_and_install_prompts(
        prompts=prepared_prompts,
        provider_settings=provider_settings,
        api_key=api_key,
        install_dir=install_dir,
        mirror_dir=mirror_dir,
        temp_dir=temp_dir,
    )
    for result in results:
        print(
            f"filename={result.filename} status={result.status} "
            f"installed={result.installed_path} validation={result.validation}"
        )
    return 0 if all(result.status == "generated" for result in results) else 1


def load_config() -> dict[str, object]:
    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    with config_path.expanduser().resolve().open("r", encoding="utf-8") as file_handler:
        config_data = yaml.safe_load(file_handler) or {}
    if not isinstance(config_data, dict):
        raise SystemExit("config/ivr.yml debe contener un objeto YAML.")
    config_data["__config_path__"] = str(config_path.expanduser().resolve())
    return config_data


def resolve_prompt_context(
    config: dict[str, object],
    *,
    lead_id: str | None,
    client_name: str,
    bank_name: str,
) -> LeadPromptContext:
    resolved_name = sanitize_lead_value(client_name, max_len=120)
    resolved_bank = sanitize_lead_value(bank_name, max_len=160)
    normalized_lead_id = sanitize_lead_value(lead_id)

    if resolved_name and resolved_bank:
        return LeadPromptContext(
            lead_id=normalized_lead_id,
            client_name=resolved_name,
            bank_name=resolved_bank,
        )

    csv_path = resolve_lead_context_csv_path(config)
    if csv_path.exists():
        context = load_lead_context_from_csv(csv_path, lead_id=normalized_lead_id)
        if context is not None:
            if not resolved_name:
                resolved_name = sanitize_lead_value(context.client_name, max_len=120)
            if not resolved_bank:
                resolved_bank = sanitize_lead_value(context.bank_name, max_len=160)

    return LeadPromptContext(
        lead_id=normalized_lead_id,
        client_name=resolved_name,
        bank_name=resolved_bank,
    )


def resolve_lead_context_csv_path(config: dict[str, object]) -> Path:
    raw_config_path = config.get("__config_path__", PROJECT_ROOT / "config" / "ivr.yml")
    config_path = Path(str(raw_config_path)).expanduser().resolve()
    lead_context_config = config.get("lead_context")
    csv_path = "lead_context.sample.csv"
    if isinstance(lead_context_config, dict):
        csv_path = str(lead_context_config.get("csv_path", csv_path)).strip() or csv_path
    resolved_path = Path(csv_path).expanduser()
    if resolved_path.is_absolute():
        return resolved_path.resolve()
    return (config_path.parent / resolved_path).resolve()


def build_prepared_prompts(
    prompt_context: LeadPromptContext,
    install_dir: Path,
) -> tuple[PreparedPrompt, ...]:
    prompts: list[PreparedPrompt] = []
    for spec in PROMPT_SPECS:
        if spec.requires_name and not prompt_context.client_name:
            continue
        if spec.requires_bank and not prompt_context.bank_name:
            continue
        rendered_text = spec.template.format(
            nombre=prompt_context.client_name or "",
            banco=prompt_context.bank_name or "",
        )
        prompts.append(
            PreparedPrompt(
                filename_stem=spec.filename_stem,
                rendered_text=rendered_text,
                output_path=install_dir / f"{spec.filename_stem}.wav",
            )
        )
    return tuple(prompts)


def resolve_provider_settings(config: dict[str, object]) -> ProviderSettings:
    provider_config = get_provider_config(config)
    voice_id_from_env = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    voice_id_source = "environment" if voice_id_from_env else "config"
    voice_id = voice_id_from_env or str(provider_config.get("voice_id", "")).strip()
    if not voice_id:
        raise SystemExit("No se encontró ELEVENLABS_VOICE_ID ni voice_id configurado.")

    model_id = str(provider_config.get("model_id", DEFAULT_MODEL_ID)).strip() or DEFAULT_MODEL_ID
    output_format = (
        str(provider_config.get("output_format", DEFAULT_OUTPUT_FORMAT)).strip()
        or DEFAULT_OUTPUT_FORMAT
    )
    timeout_seconds = provider_config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout_seconds, str):
        timeout_seconds = int(timeout_seconds)
    if not isinstance(timeout_seconds, int):
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    return ProviderSettings(
        voice_id=voice_id,
        model_id=model_id,
        output_format=output_format,
        timeout_seconds=timeout_seconds,
        voice_source=voice_id_source,
    )


def get_provider_config(config: dict[str, object]) -> dict[str, object]:
    for section_name in ("optima_audio", "name_audio", "client_flow_audio"):
        section_config = config.get(section_name)
        if not isinstance(section_config, dict):
            continue
        elevenlabs_config = section_config.get("elevenlabs")
        if isinstance(elevenlabs_config, dict):
            return elevenlabs_config
    return {}


def generate_and_install_prompts(
    *,
    prompts: tuple[PreparedPrompt, ...],
    provider_settings: ProviderSettings,
    api_key: str,
    install_dir: Path,
    mirror_dir: Path,
    temp_dir: Path,
) -> list[PromptResult]:
    install_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    results: list[PromptResult] = []

    for prompt in prompts:
        with tempfile.NamedTemporaryFile(
            dir=temp_dir,
            suffix=".source",
            delete=False,
        ) as source_tmp:
            source_path = Path(source_tmp.name)
        with tempfile.NamedTemporaryFile(
            dir=temp_dir,
            suffix=".wav",
            delete=False,
        ) as wav_tmp:
            wav_path = Path(wav_tmp.name)

        try:
            audio_bytes = request_elevenlabs_audio(
                text=prompt.rendered_text,
                provider_settings=provider_settings,
                api_key=api_key,
            )
            source_path.write_bytes(audio_bytes)
            convert_to_asterisk_wav(source_path, wav_path)
            shutil.copy2(wav_path, prompt.output_path)
            ensure_file_readable(prompt.output_path)
            maybe_chown_asterisk(prompt.output_path)

            if mirror_dir.exists():
                mirror_dir.mkdir(parents=True, exist_ok=True)
                mirror_path = mirror_dir / prompt.output_path.name
                shutil.copy2(wav_path, mirror_path)
                ensure_file_readable(mirror_path)
                maybe_chown_asterisk(mirror_path)

            results.append(
                PromptResult(
                    filename=prompt.output_path.name,
                    status="generated",
                    installed_path=str(prompt.output_path),
                    validation=validate_with_soxi(prompt.output_path),
                )
            )
        finally:
            source_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)

    return results


def request_elevenlabs_audio(
    *,
    text: str,
    provider_settings: ProviderSettings,
    api_key: str,
) -> bytes:
    query_params: dict[str, str] = {}
    if provider_settings.output_format.lower() != "wav":
        query_params["output_format"] = provider_settings.output_format

    request_url = DEFAULT_TTS_API_URL.format(
        voice_id=parse.quote(provider_settings.voice_id, safe="")
    )
    if query_params:
        request_url = f"{request_url}?{parse.urlencode(query_params)}"

    payload = json.dumps({"text": text, "model_id": provider_settings.model_id}).encode("utf-8")
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
        with request.urlopen(http_request, timeout=provider_settings.timeout_seconds) as response:
            response_body = response.read()
            if not isinstance(response_body, bytes):
                raise RuntimeError("La respuesta de ElevenLabs no devolvió bytes.")
            return response_body
    except error.HTTPError as exc:
        raise RuntimeError(f"ElevenLabs devolvió HTTP {exc.code}.") from exc
    except error.URLError as exc:
        raise RuntimeError("No fue posible contactar ElevenLabs.") from exc


def convert_to_asterisk_wav(source_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-af",
            "loudnorm=I=-18:TP=-2:LRA=7",
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


def validate_with_soxi(path: Path) -> str:
    sample_rate = _run_soxi_flag("-r", path)
    channels = _run_soxi_flag("-c", path)
    bits = _run_soxi_flag("-b", path)
    if sample_rate == "8000" and channels == "1" and bits == "16":
        return f"ok sample_rate={sample_rate} channels={channels} bits={bits}"
    return f"error sample_rate={sample_rate} channels={channels} bits={bits}"


def _run_soxi_flag(flag: str, path: Path) -> str:
    result = subprocess.run(
        ["soxi", flag, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def ensure_file_readable(path: Path) -> None:
    path.chmod(READABLE_AUDIO_MODE_BITS)


def maybe_chown_asterisk(path: Path) -> None:
    import grp
    import pwd

    try:
        user_info = pwd.getpwnam("asterisk")
        group_info = grp.getgrnam("asterisk")
    except KeyError:
        return
    os.chown(path, user_info.pw_uid, group_info.gr_gid)


if __name__ == "__main__":
    raise SystemExit(main())
