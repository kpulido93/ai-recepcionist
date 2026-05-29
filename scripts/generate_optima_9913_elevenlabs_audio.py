#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request

import yaml


def _bootstrap_src_path() -> None:
    src_path = Path(__file__).resolve().parents[1] / "src"
    if str(src_path) not in sys.path and src_path.exists():
        sys.path.insert(0, str(src_path))


_bootstrap_src_path()

from vicidial_vosk_cobranza_ivr.lead_context import load_lead_context_from_lab_yaml  # noqa: E402
from vicidial_vosk_cobranza_ivr.optima_9913_lab_audio import (  # noqa: E402
    DEFAULT_ENV_FILE,
    DEFAULT_INSTALL_DIR,
    DEFAULT_MIRROR_DIRS,
    DEFAULT_MODEL_ID,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_TEMP_DIR,
    DEFAULT_TIMEOUT_SECONDS,
    OPTIMA_9913_DEUDA_BANCO,
    OPTIMA_9913_PREGUNTA_ABOGADO,
    OPTIMA_9913_SALUDO,
    build_optima_9913_lab_stem,
    format_validation,
    get_or_generate_optima_9913_lab_audio,
    validate_wav,
)

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
ENV_ASSIGNMENT_PATTERN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
READABLE_MODE_BITS = 0o644


@dataclass(frozen=True)
class PromptSpec:
    filename: str
    text: str
    leading_silence_ms: int
    allow_typing_sfx: bool = False


PROMPT_SPECS = (
    PromptSpec(
        filename="optima-01-saludo-validacion.wav",
        text="Saludos. ¿Hablo con usted? Le escucho.",
        leading_silence_ms=500,
    ),
    PromptSpec(
        filename="optima-02-pregunta-abogado.wav",
        text=(
            "Gracias. Le llamamos de Jurídica Optima por una gestión pendiente. "
            "¿Desea que le comunique con un abogado para revisar su caso? Le escucho."
        ),
        leading_silence_ms=250,
    ),
    PromptSpec(
        filename="optima-03-deuda-banco.wav",
        text=(
            "Le estamos llamando por una deuda que usted ya conoce. "
            "Para más detalles puedo comunicarle con un abogado. "
            "¿Desea que le comunique? Le escucho."
        ),
        leading_silence_ms=250,
    ),
    PromptSpec(
        filename="optima-04-permitame-terminar.wav",
        text="Permítame terminar y con gusto le escucho.",
        leading_silence_ms=250,
        allow_typing_sfx=True,
    ),
    PromptSpec(
        filename="optima-05-no-entendi.wav",
        text="Disculpe, no le escuché bien. ¿Desea que le comunique con un abogado? Le escucho.",
        leading_silence_ms=250,
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Genera e instala los prompts base y dinámicos del flujo Optima 9913 para laboratorio."
        )
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--install-dir", default=str(DEFAULT_INSTALL_DIR))
    parser.add_argument("--mirror-dir", action="append", default=[])
    parser.add_argument("--temp-dir", default=str(DEFAULT_TEMP_DIR))
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[1] / "config" / "ivr.yml"),
    )
    parser.add_argument(
        "--lab-leads-file",
        default=str(Path(__file__).resolve().parents[1] / "config" / "lab_leads.yml"),
    )
    parser.add_argument("--typing-sfx-path", default="")
    parser.add_argument("--output-format", default=DEFAULT_OUTPUT_FORMAT)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--enable-typing-sfx", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_file = Path(args.env_file).expanduser().resolve()
    install_dir = Path(args.install_dir).expanduser().resolve()
    mirror_dirs = resolve_target_dirs(install_dir, args.mirror_dir)
    temp_dir = Path(args.temp_dir).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()
    lab_leads_path = Path(args.lab_leads_file).expanduser().resolve()
    typing_sfx_path = (
        Path(args.typing_sfx_path).expanduser().resolve() if args.typing_sfx_path.strip() else None
    )

    runtime_config = load_runtime_config(config_path)
    loaded_from_env_file = load_env_file_if_needed(env_file)
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice_id = resolve_voice_id(runtime_config)

    print(f"ELEVENLABS_API_KEY loaded: {bool(api_key)}")
    print(f"ELEVENLABS_VOICE_ID loaded: {voice_id or 'NO'}")
    print(f"Loaded ELEVENLABS_API_KEY from env-file: {'yes' if loaded_from_env_file else 'no'}")
    print(f"install_dir: {install_dir}")
    print(f"mirror_dirs: {','.join(str(path) for path in mirror_dirs[1:])}")

    if args.dry_run:
        for prompt in PROMPT_SPECS:
            print(
                f"dry_run filename={prompt.filename} "
                f"install={','.join(str(path / prompt.filename) for path in mirror_dirs)}"
            )
        for extension, lead_id, stem in iter_lab_lead_stems(lab_leads_path):
            print(
                f"dry_run extension={extension} lead_id={lead_id} stem={stem} "
                f"install={','.join(str(path / f'{stem}.wav') for path in mirror_dirs)}"
            )
        return 0

    if not api_key or not voice_id:
        print_missing_env_diagnostics(env_file)
        return 1

    for target_dir in mirror_dirs:
        target_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    for prompt in PROMPT_SPECS:
        primary_path = mirror_dirs[0] / prompt.filename
        primary_slin_path = primary_path.with_suffix(".slin")
        validation = validate_wav(primary_path) if primary_path.exists() else None
        if (
            validation is not None
            and validation.ok
            and primary_slin_path.exists()
            and not args.force
        ):
            print(
                f"filename={prompt.filename} status=existing "
                f"validation={format_validation(validation)}"
            )
            continue

        generated_validation = generate_static_prompt(
            prompt=prompt,
            target_dirs=mirror_dirs,
            api_key=api_key,
            voice_id=voice_id,
            model_id=args.model_id,
            output_format=args.output_format,
            timeout_seconds=args.timeout_seconds,
            temp_dir=temp_dir,
            enable_typing_sfx=args.enable_typing_sfx,
            typing_sfx_path=typing_sfx_path,
        )
        print(
            f"filename={prompt.filename} status=generated "
            f"validation={format_validation(generated_validation)}"
        )

    for extension, lead_context in iter_lab_lead_contexts(lab_leads_path):
        if not lead_context.lead_id or not lead_context.client_name or not lead_context.bank_name:
            continue
        for prompt_kind in (
            OPTIMA_9913_SALUDO,
            OPTIMA_9913_PREGUNTA_ABOGADO,
            OPTIMA_9913_DEUDA_BANCO,
        ):
            audio_path = get_or_generate_optima_9913_lab_audio(
                prompt_kind,
                lead_id=lead_context.lead_id,
                person_name=lead_context.client_name,
                bank_name=lead_context.bank_name,
                config=runtime_config,
                install_dir=install_dir,
                mirror_dirs=args.mirror_dir,
                temp_dir=temp_dir,
                force=args.force,
            )
            if audio_path is None:
                print(
                    f"extension={extension} lead_id={lead_context.lead_id} prompt={prompt_kind} "
                    "status=skipped"
                )
                return 1
            validation = validate_wav(audio_path)
            if validation is None or not validation.ok:
                print(
                    f"extension={extension} lead_id={lead_context.lead_id} prompt={prompt_kind} "
                    "status=error reason=invalid-wav"
                )
                return 1
            print(
                f"extension={extension} lead_id={lead_context.lead_id} "
                f"filename={audio_path.name} "
                f"status={'existing' if not args.force else 'generated'} "
                f"validation={format_validation(validation)}"
            )

    return 0


def load_runtime_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file_handler:
        data = yaml.safe_load(file_handler) or {}
    if not isinstance(data, dict):
        return {}
    data["__config_path__"] = str(path)
    return data


def iter_lab_lead_contexts(lab_leads_path: Path):
    with lab_leads_path.open("r", encoding="utf-8") as file_handler:
        data = yaml.safe_load(file_handler) or {}
    raw_lab_leads = data.get("lab_leads", {})
    if not isinstance(raw_lab_leads, dict):
        return
    for extension in raw_lab_leads:
        lead_context = load_lead_context_from_lab_yaml(
            lab_leads_path,
            extension=str(extension),
            phone_number=str(extension),
        )
        if lead_context is not None:
            yield str(extension), lead_context


def iter_lab_lead_stems(lab_leads_path: Path):
    for extension, lead_context in iter_lab_lead_contexts(lab_leads_path):
        if not lead_context.lead_id:
            continue
        for prompt_kind in (
            OPTIMA_9913_SALUDO,
            OPTIMA_9913_PREGUNTA_ABOGADO,
            OPTIMA_9913_DEUDA_BANCO,
        ):
            yield (
                extension,
                lead_context.lead_id,
                build_optima_9913_lab_stem(
                    lead_context.lead_id,
                    prompt_kind,
                ),
            )


def load_env_file_if_needed(env_file: Path) -> bool:
    if os.getenv("ELEVENLABS_API_KEY") and os.getenv("ELEVENLABS_VOICE_ID"):
        return False
    if not env_file.exists() or not os.access(env_file, os.R_OK):
        return False

    parsed = parse_env_file(env_file)
    loaded = False
    for key in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"):
        if os.getenv(key):
            continue
        value = parsed.get(key, "")
        if value:
            os.environ[key] = value
            loaded = loaded or key == "ELEVENLABS_API_KEY"
    return loaded


def parse_env_file(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_ASSIGNMENT_PATTERN.match(line)
        if match is None:
            continue
        key = match.group(1)
        value = strip_optional_quotes(match.group(2).strip())
        parsed[key] = value
    return parsed


def strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def resolve_voice_id(config: dict[str, object]) -> str:
    name_audio = config.get("name_audio")
    if not isinstance(name_audio, dict):
        return os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    provider_config = name_audio.get("elevenlabs", {})
    if not isinstance(provider_config, dict):
        return os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    voice_id_env = str(provider_config.get("voice_id_env", "ELEVENLABS_VOICE_ID")).strip()
    if voice_id_env:
        voice_id = os.getenv(voice_id_env, "").strip()
        if voice_id:
            return voice_id
    return str(provider_config.get("voice_id", "")).strip()


def print_missing_env_diagnostics(env_file: Path) -> None:
    exists = env_file.exists()
    readable = os.access(env_file, os.R_OK)
    contains_api_key = False
    contains_voice_id = False
    api_key_format_valid = False
    voice_id_format_valid = False
    if exists and readable:
        parsed = parse_env_file(env_file)
        contains_api_key = "ELEVENLABS_API_KEY" in parsed
        contains_voice_id = "ELEVENLABS_VOICE_ID" in parsed
        api_key_format_valid = bool(parsed.get("ELEVENLABS_API_KEY", ""))
        voice_id_format_valid = bool(parsed.get("ELEVENLABS_VOICE_ID", ""))

    print(f"env file exists: {'yes' if exists else 'no'}")
    print(f"env file readable: {'yes' if readable else 'no'}")
    print(f"ELEVENLABS_API_KEY assignment present: {'yes' if contains_api_key else 'no'}")
    print(f"ELEVENLABS_VOICE_ID assignment present: {'yes' if contains_voice_id else 'no'}")
    print(f"ELEVENLABS_API_KEY KEY=value valid: {'yes' if api_key_format_valid else 'no'}")
    print(f"ELEVENLABS_VOICE_ID KEY=value valid: {'yes' if voice_id_format_valid else 'no'}")


def resolve_target_dirs(install_dir: Path, mirror_dir_args: list[str]) -> tuple[Path, ...]:
    resolved_dirs = [install_dir]
    for default_path in DEFAULT_MIRROR_DIRS:
        resolved_dirs.append(default_path.expanduser().resolve())
    for raw_path in mirror_dir_args:
        resolved_dirs.append(Path(raw_path).expanduser().resolve())

    unique_dirs: list[Path] = []
    seen: set[str] = set()
    for path in resolved_dirs:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_dirs.append(path)
    return tuple(unique_dirs)


def all_outputs_exist(target_dirs: tuple[Path, ...], filename: str) -> bool:
    for target_dir in target_dirs:
        wav_path = target_dir / filename
        slin_path = wav_path.with_suffix(".slin")
        if not wav_path.exists() or not slin_path.exists():
            return False
    return True


def generate_static_prompt(
    *,
    prompt: PromptSpec,
    target_dirs: tuple[Path, ...],
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    timeout_seconds: int,
    temp_dir: Path,
    enable_typing_sfx: bool,
    typing_sfx_path: Path | None,
):
    with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".source", delete=False) as source_tmp:
        source_path = Path(source_tmp.name)
    with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".wav", delete=False) as wav_tmp:
        wav_path = Path(wav_tmp.name)
    with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".slin", delete=False) as slin_tmp:
        slin_path = Path(slin_tmp.name)

    try:
        audio_bytes = request_tts_audio(
            text=prompt.text,
            api_key=api_key,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
            timeout_seconds=timeout_seconds,
        )
        source_path.write_bytes(audio_bytes)
        convert_to_wav(source_path, wav_path, prompt.leading_silence_ms)
        if (
            enable_typing_sfx
            and prompt.allow_typing_sfx
            and typing_sfx_path is not None
            and typing_sfx_path.exists()
        ):
            apply_typing_sfx(wav_path, typing_sfx_path)
        convert_to_slin(wav_path, slin_path)
        for target_dir in target_dirs:
            install_prompt_files(wav_path, slin_path, target_dir / prompt.filename)
        validation = validate_wav(target_dirs[0] / prompt.filename)
        if validation is None or not validation.ok:
            raise RuntimeError("Static prompt validation failed.")
        return validation
    finally:
        source_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        slin_path.unlink(missing_ok=True)


def request_tts_audio(
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


def convert_to_wav(source_path: Path, output_path: Path, leading_silence_ms: int) -> None:
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


def convert_to_slin(source_wav_path: Path, output_path: Path) -> None:
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


def apply_typing_sfx(voice_wav_path: Path, typing_sfx_path: Path) -> None:
    with tempfile.NamedTemporaryFile(
        dir=voice_wav_path.parent,
        suffix=".wav",
        delete=False,
    ) as mixed_tmp:
        mixed_path = Path(mixed_tmp.name)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(typing_sfx_path),
                "-i",
                str(voice_wav_path),
                "-filter_complex",
                (
                    "[0:a]atrim=0:0.35,volume=0.05,afade=t=out:st=0.30:d=0.05[sfx];"
                    "[sfx][1:a]concat=n=2:v=0:a=1[out]"
                ),
                "-map",
                "[out]",
                "-ar",
                "8000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(mixed_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.move(str(mixed_path), str(voice_wav_path))
    except subprocess.CalledProcessError:
        mixed_path.unlink(missing_ok=True)
    finally:
        mixed_path.unlink(missing_ok=True)


def install_prompt_files(
    source_wav_path: Path,
    source_slin_path: Path,
    final_wav_path: Path,
) -> None:
    install_file(source_wav_path, final_wav_path)
    install_file(source_slin_path, final_wav_path.with_suffix(".slin"))


def install_file(source_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, final_path)
    final_path.chmod(READABLE_MODE_BITS)
    maybe_chown_asterisk(final_path)


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
