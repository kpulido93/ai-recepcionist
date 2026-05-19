from __future__ import annotations

import os
import select
import time
import wave
from dataclasses import dataclass
from pathlib import Path


class AudioFormatError(RuntimeError):
    """Raised when audio format is not compatible with the simple V1 pipeline."""


@dataclass(frozen=True)
class AudioPacket:
    audio_bytes: bytes
    sample_rate: int


def read_wave_file(path: Path) -> AudioPacket:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        if channels != 1:
            raise AudioFormatError("El WAV debe ser mono.")
        if sample_width != 2:
            raise AudioFormatError("El WAV debe ser PCM 16-bit.")

        return AudioPacket(
            audio_bytes=wav_file.readframes(wav_file.getnframes()),
            sample_rate=sample_rate,
        )


def capture_eagi_audio(
    fd: int,
    listen_seconds: int,
    sample_rate: int,
    chunk_size: int = 3200,
) -> bytes:
    if os.name == "nt":
        raise RuntimeError("La captura EAGI solo se ejecuta en Linux.")

    bytes_per_second = sample_rate * 2
    target_bytes = bytes_per_second * listen_seconds
    deadline = time.monotonic() + listen_seconds + 0.5
    chunks: list[bytes] = []
    bytes_read = 0

    while bytes_read < target_bytes and time.monotonic() < deadline:
        timeout = max(0.0, min(0.2, deadline - time.monotonic()))
        readable, _, _ = select.select([fd], [], [], timeout)
        if not readable:
            continue

        chunk = os.read(fd, min(chunk_size, target_bytes - bytes_read))
        if not chunk:
            break

        chunks.append(chunk)
        bytes_read += len(chunk)

    return b"".join(chunks)
