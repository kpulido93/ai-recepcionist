from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch


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
    module_path = Path(__file__).resolve().parents[1] / "agi" / "generate_personalized_prompt.py"
    spec = importlib.util.spec_from_file_location("generate_personalized_prompt_agi", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_personalized_prompt_agi_sets_fallback_when_generation_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    generated_dir = tmp_path / "generated"
    sound_dir = tmp_path / "sounds"
    custom_dir = sound_dir / "custom"
    custom_dir.mkdir(parents=True)
    (custom_dir / "gestion-banco-uno.wav").write_bytes(b"wav")
    config_path = tmp_path / "ivr.yml"
    config_path.write_text(
        f"""
prompts:
  personalized_greeting_enabled: true
  greeting_template: "Hola {{client_name}}, banco {{bank_name}}."
  greeting_template_without_name: "Hola, banco {{bank_name}}."
  greeting_fallback: "Hola fallback."
  generated_audio_dir: "{generated_dir}"
  generated_audio_playback_prefix: "custom/generated"
  default_greeting_audio: "custom/mensaje-cobranza"
  greeting_followup_audio: "custom/pregunta-abogado"
  sound_search_dirs:
    - "{sound_dir}"
  tts_provider: "espeak-ng"
  tts_voice: "es-la"
  cache_enabled: false
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_agi_module()

    def fail_generation(text: str, output_path: Path, config: dict[str, object]) -> None:
        raise RuntimeError("tts failed")

    monkeypatch.setattr(module, "generate_prompt_audio", fail_generation)
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_LEAD_ID": "200 result=1 (123)",
            "GET VARIABLE IVR_CLIENT_NAME": "200 result=1 (Ana Perez)",
            "GET VARIABLE IVR_BANK_NAME": "200 result=1 (Banco Uno)",
        }
    )

    exit_code = module.run_generate_personalized_prompt(session=session, environment={})

    assert exit_code == 0
    assert session.variables["IVR_GREETING_AUDIO"] == "custom/mensaje-cobranza"
    assert session.variables["IVR_GREETING_FOLLOWUP_AUDIO"] == "custom/pregunta-abogado"
    assert session.variables["IVR_BANK_GREETING_AUDIO"] == "custom/gestion-banco-uno"
