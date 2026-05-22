from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from vicidial_vosk_cobranza_ivr.config import (
    AppConfig,
    AsteriskSettings,
    AudioSettings,
    IvrSettings,
    LoggingSettings,
    PromptsSettings,
    VoskSettings,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "agi" / "generate_personalized_prompt.py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_SPEC = importlib.util.spec_from_file_location("agi_generate_personalized_prompt", SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
generate_personalized_prompt = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = generate_personalized_prompt
_SPEC.loader.exec_module(generate_personalized_prompt)


class FakeSession:
    def __init__(
        self,
        *,
        variables: dict[str, str] | None = None,
        get_variable_values: dict[str, str] | None = None,
    ) -> None:
        self.variables = variables or {}
        self.get_variable_values = get_variable_values or {}

    def set_variable(self, name: str, value: str) -> str:
        self.variables[name] = value
        return "200 result=1"

    def get_variable(self, name: str) -> str | None:
        return self.get_variable_values.get(name)


def build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        audio=AudioSettings(min_rms=150.0),
        ivr=IvrSettings(
            listen_seconds=5,
            sample_rate=8000,
            retry_attempts=1,
            default_intent="DUDA",
            allow_dtmf_fallback=True,
            early_detection_enabled=True,
            early_detection_min_audio_ms=250,
            early_detection_min_chars=2,
            vad_enabled=True,
            min_speech_ms=250,
            silence_after_speech_ms=700,
            rms_speech_threshold=250.0,
            max_dtmf_wait_ms=5000,
            dtmf_map={"1": "SI", "2": "NO"},
        ),
        asterisk=AsteriskSettings(
            app_name="vicidial-vosk-cobranza-ivr",
            channel_variable_name="VOSK_INTENT",
            transfer_context="default",
            lawyer_destination_type="ingroup",
            lawyer_destination="INGROUP_ABOGADOS",
            final_disposition_yes="YES",
            final_disposition_no="NO",
            final_disposition_unknown="UNKNOWN",
        ),
        vosk=VoskSettings(
            websocket_url="ws://127.0.0.1:2700",
            sample_rate=8000,
            audio_format="s16le",
            language="es",
            websocket_timeout_seconds=10,
        ),
        logging=LoggingSettings(
            enabled=False,
            log_level="INFO",
            log_path="./logs/test.log",
            events_path="",
            log_transcript=False,
            mask_phone_numbers=True,
            debug_audio_dump_enabled=False,
            debug_audio_dump_dir="/tmp",
            rotate_max_bytes=10485760,
            rotate_backup_count=10,
        ),
        prompts=PromptsSettings(
            personalized_greeting_enabled=True,
            greeting_template=(
                "Hola {client_name}, nos comunicamos de SokaCorp por una gestion pendiente "
                "relacionada con {bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
            ),
            greeting_template_without_name=(
                "Hola, nos comunicamos de SokaCorp por una gestion pendiente relacionada con "
                "{bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
            ),
            greeting_fallback=(
                "Hola, nos comunicamos de SokaCorp por una gestion pendiente. "
                "¿Desea que le comuniquemos ahora? Le escucho."
            ),
            generated_audio_dir=str(tmp_path / "generated"),
            generated_audio_playback_prefix="custom/generated",
            tts_provider="espeak-ng",
            tts_voice="es-la",
            cache_enabled=True,
            privacy_mode=False,
            debug_log_values=False,
        ),
        intents={"SI": ["si"], "NO": ["no"], "DUDA": ["quien habla"], "SILENCIO": []},
    )


def build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.NullHandler())
    return logger


def test_run_generate_personalized_prompt_sets_fallback_when_generation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import vicidial_vosk_cobranza_ivr.prompt_builder as prompt_builder

    config = build_config(tmp_path)
    session = FakeSession(
        get_variable_values={
            "IVR_LEAD_ID": "12345",
            "IVR_CLIENT_NAME": "Juan Perez",
            "IVR_BANK_NAME": "Banco Popular",
        }
    )
    logger = build_logger("test_generate_personalized_prompt_agi.fallback")

    monkeypatch.setattr(
        prompt_builder,
        "generate_prompt_audio",
        lambda text, output_path, prompts_config: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = generate_personalized_prompt.run_generate_personalized_prompt(
        session=session,
        config=config,
        logger=logger,
        environment={},
    )

    assert result == 0
    assert session.variables["IVR_GREETING_AUDIO"] == "custom/mensaje-cobranza"
