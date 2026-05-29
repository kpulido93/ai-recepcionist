from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch

from vicidial_vosk_cobranza_ivr.optima_audio_cache import (
    OPTIMA_DEUDA_BANCO,
    OPTIMA_SALUDO_NOMBRE,
    build_optima_audio_filename,
    build_optima_audio_text,
    build_optima_cache_key,
)


class FakeAgiSession:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.variables: dict[str, str] = {}

    def command(self, command_line: str) -> str:
        return self.responses.get(command_line, "200 result=0")

    def set_variable(self, name: str, value: str) -> str:
        self.variables[name] = value
        return "200 result=1"


def load_agi_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "agi" / "generate_optima_audio.py"
    spec = importlib.util.spec_from_file_location("generate_optima_audio_agi", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_config(path: Path, cache_dir: Path) -> None:
    path.write_text(
        f"""
name_audio:
  elevenlabs:
    api_key_env: "ELEVENLABS_API_KEY"
    voice_id: "voice-demo"
    model_id: "model-demo"
    output_format: "wav"
    timeout_seconds: 15
optima_audio:
  enabled: true
  provider: "elevenlabs"
  cache_enabled: true
  cache_dir: "{cache_dir}"
  mirror_dirs: []
  playback_prefix: "custom/generated/optima"
  version: "v1-optima-segmented"
  max_name_chars: 80
  max_bank_chars: 120
  fallback_on_error: true
  templates:
    saludo_nombre: "Saludos {{name}}."
    deuda_banco: "Por la deuda que mantiene en {{bank}}."
  fallbacks:
    saludo_generico_audio: "custom/optima-01-saludo-generico"
    deuda_generica_audio: "custom/optima-04-deuda-generica"
""".strip(),
        encoding="utf-8",
    )


def test_generate_optima_audio_agi_sets_playback_paths_when_cache_exists(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "generated" / "optima"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir)
    config = {
        "optima_audio": {
            "templates": {
                "saludo_nombre": "Saludos {name}.",
                "deuda_banco": "Por la deuda que mantiene en {bank}.",
            }
        }
    }
    saludo_text = build_optima_audio_text(OPTIMA_SALUDO_NOMBRE, "Juan Perez", config)
    saludo_key = build_optima_cache_key(
        OPTIMA_SALUDO_NOMBRE,
        "Juan Perez",
        "voice-demo",
        "model-demo",
        "v1-optima-segmented",
        final_text=saludo_text,
    )
    deuda_text = build_optima_audio_text(OPTIMA_DEUDA_BANCO, "Banco Popular", config)
    deuda_key = build_optima_cache_key(
        OPTIMA_DEUDA_BANCO,
        "Banco Popular",
        "voice-demo",
        "model-demo",
        "v1-optima-segmented",
        final_text=deuda_text,
    )
    (cache_dir / build_optima_audio_filename(OPTIMA_SALUDO_NOMBRE, saludo_key)).write_bytes(b"wav")
    (cache_dir / build_optima_audio_filename(OPTIMA_DEUDA_BANCO, deuda_key)).write_bytes(b"wav")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_CLIENT_NAME": "200 result=1 (Juan Perez)",
            "GET VARIABLE IVR_BANK_NAME": "200 result=1 (Banco Popular)",
        }
    )

    exit_code = module.run_generate_optima_audio(session=session, environment={})

    assert exit_code == 0
    assert (
        session.variables["IVR_OPTIMA_SALUDO_NOMBRE_AUDIO"]
        == f"custom/generated/optima/optima-01-saludo-nombre-{saludo_key}"
    )
    assert (
        session.variables["IVR_OPTIMA_DEUDA_BANCO_AUDIO"]
        == f"custom/generated/optima/optima-04-deuda-banco-{deuda_key}"
    )


def test_generate_optima_audio_agi_uses_fallback_when_name_is_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "generated" / "optima")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_agi_module()
    session = FakeAgiSession({"GET VARIABLE IVR_BANK_NAME": "200 result=1 (Banco Popular)"})

    exit_code = module.run_generate_optima_audio(session=session, environment={})

    assert exit_code == 0
    assert session.variables["IVR_OPTIMA_SALUDO_NOMBRE_AUDIO"] == "custom/optima-01-saludo-generico"


def test_generate_optima_audio_agi_uses_fallback_when_bank_is_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "generated" / "optima")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_agi_module()
    session = FakeAgiSession({"GET VARIABLE IVR_CLIENT_NAME": "200 result=1 (Juan Perez)"})

    exit_code = module.run_generate_optima_audio(session=session, environment={})

    assert exit_code == 0
    assert session.variables["IVR_OPTIMA_DEUDA_BANCO_AUDIO"] == "custom/optima-04-deuda-generica"
