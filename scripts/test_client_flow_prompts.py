#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


def _bootstrap_src_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


OPTIONAL_ENV_FILE = Path("/etc/default/vicidial-vosk-cobranza-ivr")


def _load_optional_runtime_env() -> None:
    if not OPTIONAL_ENV_FILE.exists():
        return

    target_vars = ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID")
    if all(os.getenv(variable_name) for variable_name in target_vars):
        return

    try:
        env_lines = OPTIONAL_ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in env_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in target_vars or os.getenv(key):
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


_bootstrap_src_path()
_load_optional_runtime_env()

from vicidial_vosk_cobranza_ivr.client_flow_audio import (  # noqa: E402
    DEFAULT_ELEVENLABS_API_KEY_ENV,
    DEFAULT_ELEVENLABS_VOICE_ID_ENV,
    ClientFlowPrompt,
    build_client_flow_prompts,
    get_cached_client_flow_audio,
    get_or_generate_client_flow_audio,
)
from vicidial_vosk_cobranza_ivr.config import PROJECT_ROOT  # noqa: E402


@dataclass(slots=True)
class PromptReport:
    slot: str
    status: str
    reason: str
    message: str
    text: str
    generated: bool
    cache_hit: bool
    playback_path: str
    wav_path: str


def load_config() -> dict[str, object]:
    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    with config_path.expanduser().resolve().open("r", encoding="utf-8") as file_handler:
        config_data = yaml.safe_load(file_handler) or {}
    if not isinstance(config_data, dict):
        raise SystemExit("config/ivr.yml debe contener un objeto YAML.")
    return config_data


def inspect_prompt(prompt: ClientFlowPrompt, config: dict[str, object]) -> PromptReport:
    client_flow_config = get_client_flow_config(config)
    if not bool(client_flow_config.get("enabled", False)):
        return build_report(
            prompt,
            status="disabled",
            reason="client_flow_audio_disabled",
            message="La configuración client_flow_audio.enabled está desactivada o no existe.",
        )

    voice_id = resolve_voice_id(client_flow_config)
    if not voice_id:
        voice_id_env = resolve_voice_id_env(client_flow_config)
        return build_report(
            prompt,
            status="invalid_config",
            reason="missing_voice_id",
            message=f"Falta voice_id en config y tampoco está seteada la variable {voice_id_env}.",
        )

    cached_path = get_cached_client_flow_audio(prompt.slot, prompt.text, config)
    if cached_path is not None:
        return build_report(
            prompt,
            status="cache_hit",
            reason="cache_hit",
            message="Audio encontrado en caché.",
            wav_path=str(cached_path),
            cache_hit=True,
        )

    api_key_env = resolve_api_key_env(client_flow_config)
    if not os.getenv(api_key_env, "").strip():
        return build_report(
            prompt,
            status="missing_api_key",
            reason="missing_api_key",
            message=f"Falta la variable de entorno {api_key_env}.",
        )

    audio_path = get_or_generate_client_flow_audio(prompt.slot, prompt.text, config)
    if audio_path is None:
        return build_report(
            prompt,
            status="error",
            reason="generation_failed",
            message="No fue posible generar el audio del flujo cliente.",
        )

    return build_report(
        prompt,
        status="generated",
        reason="generated",
        message="Audio generado correctamente.",
        wav_path=str(audio_path),
        generated=True,
    )


def build_report(
    prompt: ClientFlowPrompt,
    *,
    status: str,
    reason: str,
    message: str,
    wav_path: str = "",
    generated: bool = False,
    cache_hit: bool = False,
) -> PromptReport:
    return PromptReport(
        slot=prompt.slot,
        status=status,
        reason=reason,
        message=message,
        text=prompt.text,
        generated=generated,
        cache_hit=cache_hit,
        playback_path=prompt.playback_path,
        wav_path=wav_path,
    )


def get_client_flow_config(config: dict[str, object]) -> dict[str, object]:
    client_flow_config = config.get("client_flow_audio")
    if isinstance(client_flow_config, dict):
        return client_flow_config
    return {}


def resolve_api_key_env(client_flow_config: dict[str, object]) -> str:
    elevenlabs_config = get_elevenlabs_config(client_flow_config)
    api_key_env = str(elevenlabs_config.get("api_key_env", DEFAULT_ELEVENLABS_API_KEY_ENV)).strip()
    return api_key_env or DEFAULT_ELEVENLABS_API_KEY_ENV


def resolve_voice_id_env(client_flow_config: dict[str, object]) -> str:
    elevenlabs_config = get_elevenlabs_config(client_flow_config)
    voice_id_env = str(
        elevenlabs_config.get("voice_id_env", DEFAULT_ELEVENLABS_VOICE_ID_ENV)
    ).strip()
    return voice_id_env or DEFAULT_ELEVENLABS_VOICE_ID_ENV


def resolve_voice_id(client_flow_config: dict[str, object]) -> str:
    voice_id_env = resolve_voice_id_env(client_flow_config)
    voice_id_from_env = os.getenv(voice_id_env, "").strip()
    if voice_id_from_env:
        return voice_id_from_env
    elevenlabs_config = get_elevenlabs_config(client_flow_config)
    return str(elevenlabs_config.get("voice_id", "")).strip()


def get_elevenlabs_config(client_flow_config: dict[str, object]) -> dict[str, object]:
    elevenlabs_config = client_flow_config.get("elevenlabs")
    if isinstance(elevenlabs_config, dict):
        return elevenlabs_config
    return {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera o valida los prompts dinámicos del flujo cliente 9912."
    )
    parser.add_argument("--debtor", default="", help="Nombre ficticio del deudor.")
    parser.add_argument("--bank", default="", help="Banco ficticio del laboratorio.")
    parser.add_argument(
        "--gender",
        default="",
        choices=["", "male", "female", "unknown"],
        help="Género ficticio para el saludo dinámico.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    prompts = build_client_flow_prompts(
        config,
        debtor=args.debtor or None,
        bank=args.bank or None,
        gender=args.gender or None,
    )
    reports = [inspect_prompt(prompt, config) for prompt in prompts]

    for report in reports:
        print(f"slot={report.slot}")
        print(f"status={report.status}")
        print(f"reason={report.reason}")
        print(f"generated={'true' if report.generated else 'false'}")
        print(f"cache_hit={'true' if report.cache_hit else 'false'}")
        print(f"playback_path={report.playback_path}")
        print(f"wav_path={report.wav_path}")
        print(f"text={report.text}")
        print(f"message={report.message}")
        print("")

    return 0 if all(report.status in {"generated", "cache_hit"} for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
