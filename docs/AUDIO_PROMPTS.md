# Audio Prompts De Nivel 1

Esta guia define el criterio de audio para el IVR Nivel 1 del laboratorio local y deja claro que en produccion no debe usarse TTS sintetico basico como sustituto de una voz humana.

## Produccion

- Para produccion usa voz humana dominicana grabada.
- No uses `espeak-ng` como audio final de produccion.
- Mantén el tono natural, breve y directo.
- Evita prompts largos porque aumentan latencia, fatiga y riesgo de eco.
- Si usas nombre del cliente, idealmente deja solo el nombre como segmento dinámico.

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

## Saludo Con Nombre En Cache

El repo puede usar un modo opcional donde el IVR reproduce:

- `custom/hola`
- audio cacheado del nombre
- `custom/gestion-<banco>`

Ese diseño mantiene fijo el cuerpo principal del saludo y solo deja variable el nombre.

## ElevenLabs Como Complemento

La generación del nombre con ElevenLabs es opcional:

- `name_audio.enabled` debe permanecer en `false` por defecto.
- Solo se intenta generar el nombre si activas esa sección en `config/ivr.yml`.
- La credencial se toma de `ELEVENLABS_API_KEY`.
- Si falta la API key o la llamada al proveedor falla, el IVR debe seguir con el saludo de fallback.

No conviertas ElevenLabs en dependencia funcional del IVR. El camino principal debe seguir operando
con audio local y fallback seguro.

## Seguridad Del Nombre

- Sanitiza el nombre antes de generar audio o construir rutas de cache.
- Limita la longitud del nombre para evitar abuso o prompts anómalos.
- No loguees la API key.
- Evalúa si es apropiado decir el nombre antes de validar identidad.

## Cache Y Rotacion

Los audios de nombre pueden guardarse en:

- `/var/lib/asterisk/sounds/custom/generated/names`
- espejos opcionales como `/usr/share/asterisk/sounds/custom/generated/names`

Buenas prácticas:

- rota o borra entradas viejas del cache en ventanas de mantenimiento
- cambia `name_audio.version` cuando quieras invalidar audios previos
- evita dejar crecer el cache sin control en ambientes de prueba prolongados

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
