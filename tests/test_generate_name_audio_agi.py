from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch

from vicidial_vosk_cobranza_ivr.name_audio_cache import build_name_audio_text, build_name_cache_key


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
    module_path = Path(__file__).resolve().parents[1] / "agi" / "generate_name_audio.py"
    spec = importlib.util.spec_from_file_location("generate_name_audio_agi", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_config(path: Path, cache_dir: Path) -> None:
    path.write_text(
        f"""
name_audio:
  enabled: true
  provider: "elevenlabs"
  cache_enabled: true
  cache_dir: "{cache_dir}"
  mirror_dirs: []
  playback_prefix: "custom/generated/names"
  version: "v1"
  max_name_chars: 80
  fallback_on_error: true
  templates:
    male: "Señor {{name}},"
    female: "Señora {{name}},"
    unknown: "{{name}},"
  elevenlabs:
    api_key_env: "ELEVENLABS_API_KEY"
    voice_id: "voice-demo"
    model_id: "model-demo"
    output_format: "wav"
    timeout_seconds: 15
""".strip(),
        encoding="utf-8",
    )


def name_audio_templates_config() -> dict[str, object]:
    return {
        "name_audio": {
            "templates": {
                "male": "Señor {name},",
                "female": "Señora {name},",
                "unknown": "{name},",
            }
        }
    }


def test_generate_name_audio_agi_sets_name_audio_when_cache_exists(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "names"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir)
    config = name_audio_templates_config()
    rendered_text = build_name_audio_text("Juan Perez", config, gender="unknown")
    cache_key = build_name_cache_key(
        "Juan Perez",
        "voice-demo",
        "model-demo",
        "v1",
        gender="unknown",
        final_text=rendered_text,
    )
    (cache_dir / f"{cache_key}.wav").write_bytes(b"wav")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_CLIENT_NAME": "200 result=1 (Juan Perez)",
        }
    )

    exit_code = module.run_generate_name_audio(session=session, environment={})

    assert exit_code == 0
    assert session.variables["IVR_NAME_AUDIO"] == f"custom/generated/names/{cache_key}"


def test_generate_name_audio_agi_uses_gender_to_resolve_cache_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "names"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir)
    config = name_audio_templates_config()
    rendered_text = build_name_audio_text("Juan Perez", config, gender="male")
    cache_key = build_name_cache_key(
        "Juan Perez",
        "voice-demo",
        "model-demo",
        "v1",
        gender="male",
        final_text=rendered_text,
    )
    (cache_dir / f"{cache_key}.wav").write_bytes(b"wav")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_CLIENT_NAME": "200 result=1 (Juan Perez)",
            "GET VARIABLE IVR_CLIENT_GENDER": "200 result=1 (male)",
        }
    )

    exit_code = module.run_generate_name_audio(session=session, environment={})

    assert exit_code == 0
    assert session.variables["IVR_NAME_AUDIO"] == f"custom/generated/names/{cache_key}"


def test_generate_name_audio_agi_sets_empty_when_generation_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "names")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_CLIENT_NAME": "200 result=1 (Juan Perez)",
        }
    )

    monkeypatch.setattr(
        module,
        "get_or_generate_name_audio",
        lambda name, config, gender=None: None,
    )

    exit_code = module.run_generate_name_audio(session=session, environment={})

    assert exit_code == 0
    assert session.variables["IVR_NAME_AUDIO"] == ""
