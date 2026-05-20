# Audio Prompts De Nivel 1

Esta guia define el criterio de audio para el IVR Nivel 1 del laboratorio local y deja claro que en produccion no debe usarse TTS sintetico basico como sustituto de una voz humana.

## Produccion

- Para produccion usa voz humana dominicana grabada.
- No uses `espeak-ng` como audio final de produccion.
- Mantén el tono natural, breve y directo.
- Evita prompts largos porque aumentan latencia, fatiga y riesgo de eco.

## Reglas De Wording

- Evita decir frases exactas de intents fuertes si esas frases activan acciones.
- No uses prompts como `diga si`, `diga no`, `diga transfierame` o variantes que puedan coincidir con el clasificador.
- Prefiere cierres naturales de toma de turno como `Le escucho.`
- No uses pitidos.
- Si el entorno de pruebas tiene retorno de audio, usa auriculares para reducir eco y falsos positivos.

## Formato De Audio

Los audios del laboratorio y de produccion deben exportarse en:

- `8000 Hz`
- `mono`
- `PCM 16-bit`

## Prompts Recomendados

- `mensaje-cobranza`: `Hola, le llamamos por una gestión pendiente.`
- `pregunta-abogado`: `¿Lo transfiero ahora? Le escucho.`
- `no-entendi`: `Disculpe, no le escuché bien.`
- `mensaje-final`: `Gracias. Hasta luego.`

## Script Local

El repo incluye [scripts/generate_lab_prompts.sh](/D:/repos/ai-recepcionista/scripts/generate_lab_prompts.sh) para generar WAVs de laboratorio sin servicios cloud ni acceso a internet.

Ese script:

- usa `espeak-ng` y `ffmpeg` instalados localmente
- genera WAV `8 kHz`, `mono`, `PCM 16-bit`
- sirve solo para laboratorio y validacion local
- no debe considerarse reemplazo de una voz humana dominicana para produccion

## Validacion Practica

- Revisa el formato final con `soxi`.
- Prueba los audios con auriculares antes de conectarlos al dialplan.
- Si cambias el wording del IVR, vuelve a probar para evitar eco semantico contra `config/intents.yml`.
