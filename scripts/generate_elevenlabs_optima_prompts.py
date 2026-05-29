#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import csv
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
from vicidial_vosk_cobranza_ivr.env_file import load_optima_env_file_if_needed  # noqa: E402
from vicidial_vosk_cobranza_ivr.lead_context import sanitize_lead_value  # noqa: E402
from vicidial_vosk_cobranza_ivr.optima_audio_cache import (  # noqa: E402
    DEFAULT_ELEVENLABS_API_KEY_ENV,
    DEFAULT_ELEVENLABS_TIMEOUT_SECONDS,
    DEFAULT_ELEVENLABS_VOICE_ID_ENV,
    DEFAULT_OPTIMA_AUDIO_PLAYBACK_PREFIX,
    DEFAULT_OPTIMA_AUDIO_VERSION,
    OPTIMA_DEUDA_BANCO,
    OPTIMA_SALUDO_NOMBRE,
    build_optima_audio_text,
    build_optima_playback_path,
    get_cached_optima_audio,
    get_or_generate_optima_audio,
)
from vicidial_vosk_cobranza_ivr.prompt_builder import mirror_audio_file  # noqa: E402

ARTIFACTS_BASE_DIR = PROJECT_ROOT / "artifacts" / "lab-prompts"
ARTIFACTS_DYNAMIC_DIR = ARTIFACTS_BASE_DIR / "generated" / "optima"
DEFAULT_PROMPTS_DEST_DIR = "/var/lib/asterisk/sounds/custom"
DEFAULT_OPTIMA_PROVIDER = "elevenlabs"
DEFAULT_ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
READABLE_AUDIO_FILE_MODE_BITS = 0o444


@dataclass(frozen=True)
class StaticPrompt:
    filename_stem: str
    text: str


@dataclass(frozen=True)
class DynamicPrompt:
    prompt_type: str
    value: str
    rendered_text: str


@dataclass(frozen=True)
class ValidationReport:
    status: str
    tool: str
    details: str


@dataclass(frozen=True)
class AudioReport:
    category: str
    identifier: str
    status: str
    playback_path: str
    wav_path: str
    validation: ValidationReport


STATIC_PROMPTS = (
    StaticPrompt("optima-01-saludo-generico", "Saludos."),
    StaticPrompt(
        "optima-02-identificacion",
        "Le habla Carlos Montero, asistente legal de la Oficina de Abogados Jurídica Óptima.",
    ),
    StaticPrompt(
        "optima-03-acuerdo",
        (
            "Anteriormente ya habíamos hablado con usted respecto al acuerdo de pago "
            "que tiene que hacer con nosotros."
        ),
    ),
    StaticPrompt(
        "optima-04-deuda-generica",
        "Por la deuda que mantiene con la entidad correspondiente.",
    ),
    StaticPrompt(
        "optima-05-etapa",
        "Su caso se encuentra en una etapa avanzada, y por eso nos gustaría orientarle a tiempo.",
    ),
    StaticPrompt(
        "optima-06-transferencia",
        (
            "Si desea, le puedo pasar a la persona a cargo para que le dé todos los "
            "detalles de la deuda."
        ),
    ),
    StaticPrompt("optima-07-callback", "O bien, le puedo llamar mañana."),
    StaticPrompt(
        "optima-objecion-unica",
        (
            "Permítame terminar, que le voy a dar la palabra. Déjeme explicarle, por favor. "
            "Me mandaron a llamarle para validar si usted tiene interés en una negociación "
            "de pago. "
            "Si usted me autoriza, le paso a la persona encargada, o bien le llamo mañana. "
            "De mi parte, eso es lo único que puedo decirle."
        ),
    ),
)


def load_config() -> dict[str, object]:
    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    with config_path.expanduser().resolve().open("r", encoding="utf-8") as file_handler:
        config_data = yaml.safe_load(file_handler) or {}
    if not isinstance(config_data, dict):
        raise SystemExit("config/ivr.yml debe contener un objeto YAML.")
    config_data["__config_path__"] = str(config_path.expanduser().resolve())
    return config_data


def resolve_lead_context_csv_path(config: dict[str, object]) -> Path:
    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    lead_context_config = config.get("lead_context")
    if isinstance(lead_context_config, dict):
        csv_path = str(lead_context_config.get("csv_path", "lead_context.sample.csv")).strip()
    else:
        csv_path = "lead_context.sample.csv"
    resolved_path = Path(csv_path).expanduser()
    if resolved_path.is_absolute():
        return resolved_path
    return (config_path.expanduser().resolve().parent / resolved_path).resolve()


def build_dynamic_prompts_from_csv(
    csv_path: Path,
    config: dict[str, object],
) -> tuple[DynamicPrompt, ...]:
    if not csv_path.exists():
        return ()

    unique_prompts: list[DynamicPrompt] = []
    seen_rendered_texts: set[tuple[str, str]] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file_handler:
        reader = csv.DictReader(file_handler)
        for row in reader:
            client_name = sanitize_lead_value(row.get("client_name"), max_len=120)
            bank_name = sanitize_lead_value(row.get("bank_name"), max_len=160)
            if client_name:
                rendered_name = build_optima_audio_text(OPTIMA_SALUDO_NOMBRE, client_name, config)
                name_key = (OPTIMA_SALUDO_NOMBRE, rendered_name)
                if name_key not in seen_rendered_texts:
                    seen_rendered_texts.add(name_key)
                    unique_prompts.append(
                        DynamicPrompt(
                            prompt_type=OPTIMA_SALUDO_NOMBRE,
                            value=client_name,
                            rendered_text=rendered_name,
                        )
                    )
            if bank_name:
                rendered_bank = build_optima_audio_text(OPTIMA_DEUDA_BANCO, bank_name, config)
                bank_key = (OPTIMA_DEUDA_BANCO, rendered_bank)
                if bank_key not in seen_rendered_texts:
                    seen_rendered_texts.add(bank_key)
                    unique_prompts.append(
                        DynamicPrompt(
                            prompt_type=OPTIMA_DEUDA_BANCO,
                            value=bank_name,
                            rendered_text=rendered_bank,
                        )
                    )
    return tuple(unique_prompts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera prompts estáticos y caché dinámica ElevenLabs para el flujo Optima."
    )
    parser.add_argument(
        "--dest",
        default=os.getenv("PROMPTS_DEST_DIR", DEFAULT_PROMPTS_DEST_DIR),
        help="Directorio base custom para audios estáticos y generated/optima.",
    )
    parser.add_argument(
        "--mirror-dir",
        action="append",
        default=[],
        help="Directorio base custom adicional para espejar los audios.",
    )
    parser.add_argument("--force", action="store_true", help="Regenera aunque el WAV ya exista.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No genera archivos; solo muestra qué audios resolvería.",
    )
    parser.add_argument(
        "--env-file",
        default="",
        help="Archivo externo con ELEVENLABS_API_KEY y/o ELEVENLABS_VOICE_ID.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    env_load_status = load_optima_env_file_if_needed(
        config,
        explicit_env_file=args.env_file or None,
    )
    print(
        "Loaded ELEVENLABS_API_KEY from env-file: "
        f"{'yes' if env_load_status.loaded_api_key else 'no'}"
    )
    csv_path = resolve_lead_context_csv_path(config)
    selected_dirs = resolve_target_directories(args.dest, args.mirror_dir)
    reports: list[AudioReport] = []

    static_reports = ensure_static_prompts(
        STATIC_PROMPTS,
        config,
        base_dir=ARTIFACTS_BASE_DIR,
        mirror_dirs=selected_dirs,
        force=args.force,
        dry_run=args.dry_run,
    )
    reports.extend(static_reports)

    dynamic_prompts = build_dynamic_prompts_from_csv(csv_path, config)
    dynamic_reports = ensure_dynamic_prompts(
        dynamic_prompts,
        config,
        base_dir=ARTIFACTS_DYNAMIC_DIR,
        mirror_dirs=tuple(path / "generated" / "optima" for path in selected_dirs),
        force=args.force,
        dry_run=args.dry_run,
    )
    reports.extend(dynamic_reports)

    print_reports(reports, selected_dirs, csv_path)
    return 0 if all(report.status != "error" for report in reports) else 1


def resolve_target_directories(dest: str, mirror_dirs: list[str]) -> tuple[Path, ...]:
    resolved_paths: list[Path] = []
    seen: set[Path] = set()
    for raw_path in [dest, *mirror_dirs]:
        normalized_path = str(raw_path).strip()
        if not normalized_path:
            continue
        path = Path(normalized_path).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        if ensure_directory(path):
            resolved_paths.append(path)
    return tuple(resolved_paths)


def ensure_static_prompts(
    prompts: tuple[StaticPrompt, ...],
    config: dict[str, object],
    *,
    base_dir: Path,
    mirror_dirs: tuple[Path, ...],
    force: bool,
    dry_run: bool,
) -> list[AudioReport]:
    ensure_directory(base_dir)
    reports: list[AudioReport] = []
    for prompt in prompts:
        playback_path = f"custom/{prompt.filename_stem}"
        output_path = base_dir / f"{prompt.filename_stem}.wav"
        report = ensure_static_prompt(
            prompt,
            config,
            output_path=output_path,
            mirror_dirs=mirror_dirs,
            playback_path=playback_path,
            force=force,
            dry_run=dry_run,
        )
        reports.append(report)
    return reports


def ensure_static_prompt(
    prompt: StaticPrompt,
    config: dict[str, object],
    *,
    output_path: Path,
    mirror_dirs: tuple[Path, ...],
    playback_path: str,
    force: bool,
    dry_run: bool,
) -> AudioReport:
    if output_path.exists() and not force:
        _mirror_existing_file(output_path, mirror_dirs)
        return AudioReport(
            category="static",
            identifier=prompt.filename_stem,
            status="skipped_existing",
            playback_path=playback_path,
            wav_path=str(output_path),
            validation=validate_wav_file(output_path),
        )

    if dry_run:
        return AudioReport(
            category="static",
            identifier=prompt.filename_stem,
            status="dry_run",
            playback_path=playback_path,
            wav_path=str(output_path),
            validation=ValidationReport("skipped", "", "dry-run"),
        )

    try:
        generate_static_prompt_audio(prompt.text, output_path, config)
        _mirror_existing_file(output_path, mirror_dirs)
        return AudioReport(
            category="static",
            identifier=prompt.filename_stem,
            status="generated",
            playback_path=playback_path,
            wav_path=str(output_path),
            validation=validate_wav_file(output_path),
        )
    except Exception as exc:
        return AudioReport(
            category="static",
            identifier=prompt.filename_stem,
            status="error",
            playback_path=playback_path,
            wav_path=str(output_path),
            validation=ValidationReport("error", "", str(exc)),
        )


def ensure_dynamic_prompts(
    prompts: tuple[DynamicPrompt, ...],
    config: dict[str, object],
    *,
    base_dir: Path,
    mirror_dirs: tuple[Path, ...],
    force: bool,
    dry_run: bool,
) -> list[AudioReport]:
    ensure_directory(base_dir)
    generation_config = build_optima_generation_config(config, base_dir, mirror_dirs)
    reports: list[AudioReport] = []
    for prompt in prompts:
        cached_path = (
            None
            if force
            else get_cached_optima_audio(
                prompt.prompt_type,
                prompt.value,
                generation_config,
            )
        )
        if cached_path is not None:
            report_path = cached_path
            status = "skipped_existing"
        elif dry_run:
            report_path = base_dir / f"{prompt.prompt_type}.wav"
            status = "dry_run"
        else:
            generated_path = get_or_generate_optima_audio(
                prompt.prompt_type,
                prompt.value,
                generation_config,
                force=force,
            )
            if generated_path is None:
                reports.append(
                    AudioReport(
                        category="dynamic",
                        identifier=f"{prompt.prompt_type}:{prompt.rendered_text}",
                        status="error",
                        playback_path="",
                        wav_path="",
                        validation=ValidationReport(
                            "error",
                            "",
                            "No fue posible generar o recuperar el audio dinámico Optima.",
                        ),
                    )
                )
                continue
            report_path = generated_path
            status = "generated"

        playback_path = (
            build_optima_playback_path(report_path, generation_config)
            if status != "dry_run"
            else _build_dry_run_playback_path(prompt.prompt_type, generation_config)
        )
        validation = (
            validate_wav_file(report_path)
            if status in {"generated", "skipped_existing"}
            else ValidationReport("skipped", "", "dry-run")
        )
        reports.append(
            AudioReport(
                category="dynamic",
                identifier=f"{prompt.prompt_type}:{prompt.rendered_text}",
                status=status,
                playback_path=playback_path,
                wav_path=str(report_path),
                validation=validation,
            )
        )
    return reports


def build_optima_generation_config(
    config: dict[str, object],
    cache_dir: Path,
    mirror_dirs: tuple[Path, ...],
) -> dict[str, object]:
    generated_config = copy.deepcopy(config)
    optima_audio_config = generated_config.setdefault("optima_audio", {})
    if not isinstance(optima_audio_config, dict):
        optima_audio_config = {}
        generated_config["optima_audio"] = optima_audio_config
    optima_audio_config["enabled"] = True
    optima_audio_config["provider"] = (
        str(optima_audio_config.get("provider", DEFAULT_OPTIMA_PROVIDER)).strip()
        or DEFAULT_OPTIMA_PROVIDER
    )
    optima_audio_config["cache_enabled"] = True
    optima_audio_config["cache_dir"] = str(cache_dir)
    optima_audio_config["mirror_dirs"] = [str(path) for path in mirror_dirs]
    optima_audio_config["playback_prefix"] = (
        str(
            optima_audio_config.get("playback_prefix", DEFAULT_OPTIMA_AUDIO_PLAYBACK_PREFIX)
        ).strip()
        or DEFAULT_OPTIMA_AUDIO_PLAYBACK_PREFIX
    )
    optima_audio_config["version"] = (
        str(optima_audio_config.get("version", DEFAULT_OPTIMA_AUDIO_VERSION)).strip()
        or DEFAULT_OPTIMA_AUDIO_VERSION
    )
    return generated_config


def generate_static_prompt_audio(text: str, output_path: Path, config: dict[str, object]) -> None:
    provider_config = get_provider_config(config)
    provider = (
        str(
            config.get("optima_audio", {}).get("provider", DEFAULT_OPTIMA_PROVIDER)
            if isinstance(config.get("optima_audio"), dict)
            else DEFAULT_OPTIMA_PROVIDER
        )
        .strip()
        .lower()
    )
    if provider != DEFAULT_OPTIMA_PROVIDER:
        raise ValueError(f"Proveedor Optima no soportado: {provider}")

    api_key_env = str(provider_config.get("api_key_env", DEFAULT_ELEVENLABS_API_KEY_ENV)).strip()
    api_key = os.getenv(api_key_env or DEFAULT_ELEVENLABS_API_KEY_ENV, "").strip()
    if not api_key:
        raise ValueError(
            f"Falta la variable de entorno {api_key_env or DEFAULT_ELEVENLABS_API_KEY_ENV}."
        )

    ensure_directory(output_path.parent)
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent,
        suffix=".source",
        delete=False,
    ) as source_tmp:
        source_tmp_path = Path(source_tmp.name)
    with tempfile.NamedTemporaryFile(
        dir=output_path.parent,
        suffix=".wav",
        delete=False,
    ) as wav_tmp:
        wav_tmp_path = Path(wav_tmp.name)

    try:
        audio_bytes = request_elevenlabs_audio(text, config, api_key)
        source_tmp_path.write_bytes(audio_bytes)
        convert_audio_to_wav(source_tmp_path, wav_tmp_path)
        os.replace(wav_tmp_path, output_path)
        ensure_file_readable(output_path)
    finally:
        source_tmp_path.unlink(missing_ok=True)
        wav_tmp_path.unlink(missing_ok=True)


def get_provider_config(config: dict[str, object]) -> dict[str, object]:
    optima_audio_config = config.get("optima_audio")
    if isinstance(optima_audio_config, dict):
        elevenlabs_config = optima_audio_config.get("elevenlabs")
        if isinstance(elevenlabs_config, dict):
            return elevenlabs_config
    for section_name in ("name_audio", "client_flow_audio"):
        section_config = config.get(section_name)
        if not isinstance(section_config, dict):
            continue
        elevenlabs_config = section_config.get("elevenlabs")
        if isinstance(elevenlabs_config, dict):
            return elevenlabs_config
    return {}


def request_elevenlabs_audio(text: str, config: dict[str, object], api_key: str) -> bytes:
    provider_config = get_provider_config(config)
    voice_id = resolve_voice_id(provider_config)
    model_id = str(provider_config.get("model_id", "")).strip()
    if not model_id:
        raise ValueError("Falta model_id para generación Optima.")
    timeout_seconds = resolve_timeout_seconds(provider_config)
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


def resolve_voice_id(provider_config: dict[str, object]) -> str:
    voice_id_env = str(provider_config.get("voice_id_env", DEFAULT_ELEVENLABS_VOICE_ID_ENV)).strip()
    if voice_id_env:
        voice_id_from_env = os.getenv(voice_id_env, "").strip()
        if voice_id_from_env:
            return voice_id_from_env
    voice_id = str(provider_config.get("voice_id", "")).strip()
    if not voice_id:
        raise ValueError("Falta voice_id para generación Optima.")
    return voice_id


def resolve_timeout_seconds(provider_config: dict[str, object]) -> int:
    timeout_value = provider_config.get("timeout_seconds", DEFAULT_ELEVENLABS_TIMEOUT_SECONDS)
    if isinstance(timeout_value, int):
        return timeout_value
    if isinstance(timeout_value, str):
        return int(timeout_value)
    return DEFAULT_ELEVENLABS_TIMEOUT_SECONDS


def convert_audio_to_wav(source_path: Path, output_path: Path) -> None:
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


def validate_wav_file(path: Path) -> ValidationReport:
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=sample_rate,channels,codec_name",
                    "-of",
                    "default=noprint_wrappers=1:nokey=0",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            return ValidationReport("error", "ffprobe", exc.stderr.strip() or str(exc))
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        sample_rate = fields.get("sample_rate", "")
        channels = fields.get("channels", "")
        codec_name = fields.get("codec_name", "")
        details = f"sample_rate={sample_rate} channels={channels} codec_name={codec_name}"
        if sample_rate == "8000" and channels == "1" and codec_name == "pcm_s16le":
            return ValidationReport("ok", "ffprobe", details)
        return ValidationReport("error", "ffprobe", details)

    soxi_path = shutil.which("soxi")
    if soxi_path:
        try:
            sample_rate = subprocess.run(
                [soxi_path, "-r", str(path)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            channels = subprocess.run(
                [soxi_path, "-c", str(path)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            encoding = subprocess.run(
                [soxi_path, "-e", str(path)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except subprocess.CalledProcessError as exc:
            return ValidationReport("error", "soxi", exc.stderr.strip() or str(exc))
        details = f"sample_rate={sample_rate} channels={channels} encoding={encoding}"
        if sample_rate == "8000" and channels == "1" and "PCM" in encoding:
            return ValidationReport("ok", "soxi", details)
        return ValidationReport("error", "soxi", details)

    return ValidationReport("unavailable", "", "ffprobe/soxi no disponibles")


def ensure_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return path.is_dir() and os.access(path, os.W_OK)


def ensure_file_readable(path: Path) -> None:
    current_mode = path.stat().st_mode & 0o777
    target_mode = current_mode | READABLE_AUDIO_FILE_MODE_BITS
    if current_mode != target_mode:
        path.chmod(target_mode)


def _mirror_existing_file(source_path: Path, mirror_dirs: tuple[Path, ...]) -> None:
    ensure_file_readable(source_path)
    mirrored_paths = mirror_audio_file(source_path, mirror_dirs)
    for mirrored_path in mirrored_paths:
        ensure_file_readable(mirrored_path)


def _build_dry_run_playback_path(prompt_type: str, config: dict[str, object]) -> str:
    optima_audio_config = config.get("optima_audio")
    playback_prefix = (
        str(
            optima_audio_config.get(
                "playback_prefix",
                DEFAULT_OPTIMA_AUDIO_PLAYBACK_PREFIX,
            )
        ).strip("/")
        if isinstance(optima_audio_config, dict)
        else DEFAULT_OPTIMA_AUDIO_PLAYBACK_PREFIX
    )
    filename_stem = (
        "optima-01-saludo-nombre"
        if prompt_type == OPTIMA_SALUDO_NOMBRE
        else "optima-04-deuda-banco"
    )
    return f"{playback_prefix}/{filename_stem}-<cache_key>"


def print_reports(
    reports: list[AudioReport],
    target_dirs: tuple[Path, ...],
    csv_path: Path,
) -> None:
    static_reports = [report for report in reports if report.category == "static"]
    dynamic_reports = [report for report in reports if report.category == "dynamic"]
    print(f"csv_path={csv_path}")
    print(f"artifact_static_dir={ARTIFACTS_BASE_DIR}")
    print(f"artifact_dynamic_dir={ARTIFACTS_DYNAMIC_DIR}")
    print(f"target_dirs={','.join(str(path) for path in target_dirs) if target_dirs else '-'}")
    print("")
    print(f"static_generated={sum(report.status == 'generated' for report in static_reports)}")
    print(
        "static_skipped_existing="
        f"{sum(report.status == 'skipped_existing' for report in static_reports)}"
    )
    print(f"dynamic_generated={sum(report.status == 'generated' for report in dynamic_reports)}")
    print(
        "dynamic_skipped_existing="
        f"{sum(report.status == 'skipped_existing' for report in dynamic_reports)}"
    )
    print("")
    for report in reports:
        print(f"category={report.category}")
        print(f"identifier={report.identifier}")
        print(f"status={report.status}")
        print(f"playback_path={report.playback_path}")
        print(f"wav_path={report.wav_path}")
        print(f"validation_status={report.validation.status}")
        print(f"validation_tool={report.validation.tool}")
        print(f"validation_details={report.validation.details}")
        print("")


if __name__ == "__main__":
    raise SystemExit(main())
