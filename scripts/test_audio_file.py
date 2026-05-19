#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Envia un WAV a Vosk y muestra el texto reconocido y la intencion detectada"
    )
    parser.add_argument("wav_file", type=Path, help="Archivo WAV mono PCM 16-bit")
    parser.add_argument(
        "--dtmf",
        default=None,
        help="Digito DTMF opcional para forzar clasificacion",
    )
    parser.add_argument("--config", type=Path, default=None, help="Ruta alternativa a ivr.yml")
    parser.add_argument("--intents", type=Path, default=None, help="Ruta alternativa a intents.yml")
    parser.add_argument("--vosk-url", default=None, help="Override del WebSocket de Vosk")
    return parser.parse_args()


def main() -> int:
    from vicidial_vosk_cobranza_ivr.audio import read_wave_file
    from vicidial_vosk_cobranza_ivr.config import load_app_config, resolve_runtime_paths
    from vicidial_vosk_cobranza_ivr.intent_classifier import IntentClassifier
    from vicidial_vosk_cobranza_ivr.vosk_client import VoskClient, VoskConnectionError

    args = parse_args()
    runtime_paths = resolve_runtime_paths(
        config_path=args.config,
        intents_path=args.intents,
    )
    config = load_app_config(runtime_paths.config_path, runtime_paths.intents_path)

    websocket_url = args.vosk_url or config.vosk.websocket_url
    classifier = IntentClassifier(
        phrases=config.intents,
        default_intent=config.ivr.default_intent,
        dtmf_map=config.ivr.dtmf_map,
    )
    vosk_client = VoskClient(
        websocket_url=websocket_url,
        timeout_seconds=config.vosk.websocket_timeout_seconds,
    )

    audio_packet = read_wave_file(args.wav_file)

    try:
        recognition = vosk_client.transcribe_pcm(
            audio_bytes=audio_packet.audio_bytes,
            sample_rate=audio_packet.sample_rate,
        )
    except VoskConnectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    classification = classifier.classify(
        transcript=recognition.transcript,
        dtmf=args.dtmf,
    )

    print(f"Archivo: {args.wav_file}")
    print(f"Sample rate: {audio_packet.sample_rate}")
    print(f"Texto reconocido: {recognition.transcript}")
    print(f"Intencion detectada: {classification.intent.value}")
    print(f"Confianza: {classification.confidence:.2f}")
    print(f"Fuente: {classification.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
