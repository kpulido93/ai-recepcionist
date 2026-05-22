# Nivel 1 IVR Robusto

## Objetivo

El objetivo de este Nivel 1 es clasificar la intención de una llamada de cobranza y tomar una decisión de ruteo en el dialplan sin usar agente LLM.

Este diseño busca:

- operar `100% local`
- evitar costes mensuales por APIs externas
- mantener un flujo simple, auditable y robusto
- servir tanto para laboratorio local como para una integración posterior con VICIdial

## Arquitectura

Arquitectura base:

```text
Asterisk/VICIdial -> EAGI -> Vosk local -> classifier -> dialplan
```

Flujo resumido:

1. Asterisk o VICIdial reproduce el prompt del IVR.
2. `EAGI(vosk_cobranza.py)` captura audio de la llamada.
3. El audio se envía a Vosk local por WebSocket.
4. El clasificador asigna un intent usando reglas locales y configuración YAML.
5. El dialplan decide si transferir, reintentar, finalizar o dejar una disposición documentada.

## Saludo Segmentado Opcional

El flujo base del Nivel 1 sigue funcionando sin dependencias externas, pero puede
usar un modo opcional de saludo segmentado para decir solo el nombre del cliente:

```text
custom/hola -> audio-cache-del-nombre -> custom/gestion-banco -> EAGI/Vosk
```

Puntos clave:

- La mayor parte del prompt debe seguir siendo audio fijo o voz humana.
- El nombre es el único segmento pensado para TTS externo opcional.
- Si el cache del nombre no existe y la API falla o no está configurada, el flujo cae
  al saludo habitual sin romper la llamada.
- `name_audio.enabled` permanece en `false` por defecto.

## Cache De Nombres

Cuando `name_audio.enabled=true`, el sistema puede generar el nombre una sola vez y
reutilizarlo en llamadas futuras.

Configuración relevante en `config/ivr.yml`:

- `name_audio.cache_dir`: directorio principal del cache.
- `name_audio.mirror_dirs`: directorios espejo opcionales para compatibilidad con Asterisk.
- `name_audio.playback_prefix`: prefijo reproducible por `Playback()`.
- `name_audio.version`: invalida el cache de forma controlada al cambiar voz o estrategia.
- `name_audio.max_name_chars`: limita el nombre antes de llamar al proveedor.
- `name_audio.fallback_on_error`: si está en `true`, cualquier fallo devuelve `None` y el IVR sigue con fallback local.

## ElevenLabs Opcional

El proveedor externo de nombre está pensado como complemento opcional, no como dependencia
del IVR.

- La API key se lee solo desde la variable de entorno `ELEVENLABS_API_KEY`.
- La API key no debe guardarse en YAML, `.env` versionado ni logs.
- Si falta `ELEVENLABS_API_KEY`, no se genera audio de nombre y el flujo continúa.
- La salida final se convierte siempre a WAV `8 kHz`, `mono`, `PCM 16-bit`.

## Riesgo Operativo

Decir el nombre de una persona antes de validar identidad puede no ser apropiado en todos los
casos de uso de cobranza.

Recomendación:

- No actives el saludo con nombre si tu flujo todavía no valida identidad mínima.
- Usa el modo segmentado solo en escenarios de laboratorio o donde el área legal/operativa ya lo haya aprobado.

## Limpieza Del Cache

El cache de nombres debe revisarse periódicamente para evitar crecimiento innecesario y para
rotar versiones antiguas.

Ejemplos prácticos:

- borrar audios viejos por fecha
- invalidar audios al cambiar `voice_id`, `model_id` o `name_audio.version`
- limpiar manualmente `custom/generated/names/` durante pruebas controladas

## Intents

El Nivel 1 robusto trabaja con estos intents:

- `SI`
- `INFO_COBRO`
- `PROMESA_PAGO`
- `NO`
- `CALLBACK`
- `NUMERO_EQUIVOCADO`
- `NO_ES_PERSONA`
- `DUDA`
- `SILENCIO`

## Ruteo Recomendado

- `SI`, `INFO_COBRO` y `PROMESA_PAGO` -> transferir
- `NO` -> finalizar o marcar rechazo
- `CALLBACK` -> disposición callback
- `NUMERO_EQUIVOCADO` -> disposición número equivocado
- `NO_ES_PERSONA` -> disposición tercero o no contacto
- `DUDA` y `SILENCIO` -> reintento controlado

En laboratorio, el sample voice-first actual transfiere a `1002` y limita el reintento a una sola vez.

## Recomendaciones De Audio

- Usa voz humana dominicana para producción.
- Mantén prompts cortos.
- No uses pitido.
- Si tu canal no tiene barge-in real, la persona no debe hablar encima del prompt.
- Cierra con una frase natural de toma de turno, por ejemplo `Le escucho.`
- Usa WAV `8 kHz`, `mono`, `PCM 16-bit`.

## Robustez

La robustez actual del Nivel 1 se apoya en varias capas:

- `early detection`: permite cortar temprano cuando Vosk detecta una intención clara en partials
- `VAD`: corta la captura tras voz seguida de silencio para reducir ruido y latencia
- `prioridad de clasificación`: evita que frases negativas o específicas queden tapadas por coincidencias más débiles
- `logs`: exponen `intent`, `confidence`, `matched_phrase`, `stop_reason` y métricas útiles sin mostrar teléfonos completos por defecto
- `evaluación automática`: el repo incluye un set local de frases RD de cobranza para medir accuracy del clasificador

## No Objetivos

Este Nivel 1 no busca:

- usar LLM
- usar servicios cloud
- sostener conversación abierta
- resolver negociación compleja o multi-turn
- reemplazar todavía una integración completa con VICIdial

## Roadmap Futuro

- prueba A/B con `faster-whisper` local opcional
- barge-in real con `ARI ExternalMedia`
- integración VICIdial real con dispositions y ruteo operativo

## Alcance Actual

Este diseño está pensado para resolver primero el tramo más importante:

- detección de intención de cobranza
- transferencia simple y controlada
- operación local y barata
- observabilidad suficiente para laboratorio y endurecimiento progresivo

Eso permite validar el flujo antes de abrir la puerta a una capa conversacional o a una automatización más compleja.
