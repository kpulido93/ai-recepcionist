# Formato de audio recomendado

Para prompts y pruebas locales usa:

- WAV
- Mono
- 8000 Hz
- PCM 16-bit signed little-endian

## Conversion con ffmpeg

```bash
ffmpeg -i entrada.mp3 -ac 1 -ar 8000 -sample_fmt s16 salida.wav
```

## Conversion con sox

```bash
sox entrada.wav -r 8000 -c 1 -b 16 salida_asterisk.wav
```

## Validacion

```bash
soxi salida_asterisk.wav
```
