# Generar WAVs de prueba

## Desde un MP3 o M4A

```bash
ffmpeg -i ejemplo.m4a -ac 1 -ar 8000 -sample_fmt s16 pruebas/ejemplo.wav
```

## Desde una grabacion nueva

```bash
sox -d -r 8000 -c 1 -b 16 pruebas/respuesta_si.wav trim 0 4
```

## Frases sugeridas

- "Si, comuniqueme con un abogado"
- "No, ahora no"
- "Quien habla"
- 4 segundos de silencio

## Verificar formato

```bash
soxi pruebas/respuesta_si.wav
```
