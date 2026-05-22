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

En el sample del laboratorio, la rama `transferir-abogado` tambien guarda `TRANSFER_STATUS=${DIALSTATUS}` despues del `Dial()` para dejar trazable si la transferencia fue contestada o no.

Significado operativo de `TRANSFER_STATUS`:

- `ANSWER`: el agente o abogado contesto
- `NOANSWER`: no contesto
- `BUSY`: estaba ocupado
- `CANCEL`: el llamante colgo
- `CHANUNAVAIL`: el agente o canal no estaba disponible

## Recomendaciones De Audio

- Usa voz humana dominicana para producción.
- Mantén prompts cortos.
- No uses pitido.
- Si tu canal no tiene barge-in real, la persona no debe hablar encima del prompt.
- Cierra con una frase natural de toma de turno, por ejemplo `Le escucho.`
- Usa WAV `8 kHz`, `mono`, `PCM 16-bit`.

## Saludo Personalizado

El Nivel 1 puede generar un saludo inicial local por lead o cartera sin usar APIs externas. El flujo pensado es:

```text
Asterisk -> AGI(generate_personalized_prompt.py) -> espeak-ng local -> ffmpeg local -> Playback()
```

La configuracion vive en [config/ivr.yml](/D:/repos/ai-recepcionista/config/ivr.yml) bajo `prompts`:

- `personalized_greeting_enabled`
- `greeting_template`
- `greeting_template_without_name`
- `greeting_fallback`
- `generated_audio_dir`
- `generated_audio_playback_prefix`
- `tts_provider`
- `tts_voice`
- `cache_enabled`

### Variables De Canal

Antes de invocar el AGI, el dialplan puede pasar:

- `IVR_LEAD_ID`
- `IVR_CLIENT_NAME`
- `IVR_BANK_NAME`

Ejemplo de uso desde el dialplan:

```asterisk
same => n,Set(__IVR_LEAD_ID=${LEAD_ID})
same => n,Set(__IVR_CLIENT_NAME=${NOMBRE_CLIENTE})
same => n,Set(__IVR_BANK_NAME=${NOMBRE_BANCO})
same => n,AGI(generate_personalized_prompt.py)
same => n,Set(IVR_GREETING_AUDIO=${IF($["${IVR_GREETING_AUDIO}"=""]?custom/mensaje-cobranza:${IVR_GREETING_AUDIO})})
```

El AGI devuelve `IVR_GREETING_AUDIO` con un valor reproducible por `Playback()`, por ejemplo `custom/generated/lead-12345-greeting-abc123def456`.

### Cache Local De Audios

Los audios se cachean en `generated_audio_dir` usando una clave estable basada en:

- `IVR_LEAD_ID`
- nombre sanitizado
- banco sanitizado
- hash del template y de la configuracion TTS

Si `cache_enabled=true` y ya existe el WAV generado, el AGI lo reutiliza sin volver a sintetizarlo.

### Recomendacion De Contenido

Aunque el sistema soporte nombre y banco, se recomienda no decir frases como `deuda pendiente` antes de validar identidad. Para un Nivel 1 mas prudente, usa wording neutral como `gestion pendiente` hasta confirmar que hablas con la persona correcta.

### Fallback Seguro

Si faltan datos, el builder usa templates mas seguros:

- con nombre y banco: `greeting_template`
- sin nombre y con banco: `greeting_template_without_name`
- sin banco o ante datos insuficientes: `greeting_fallback`

Si la generacion local falla por TTS, `ffmpeg`, permisos o cualquier otro error, el AGI fija:

```text
IVR_GREETING_AUDIO=custom/mensaje-cobranza
```

Para mantener el flujo actual, cuando uses ese fallback estatico deja el `Playback(custom/pregunta-abogado)` existente despues del saludo.

## Robustez

La robustez actual del Nivel 1 se apoya en varias capas:

- `early detection`: permite cortar temprano cuando Vosk detecta una intención clara en partials
- `VAD`: corta la captura tras voz seguida de silencio para reducir ruido y latencia
- `prioridad de clasificación`: evita que frases negativas o específicas queden tapadas por coincidencias más débiles
- `logs`: exponen `intent`, `confidence`, `matched_phrase`, `stop_reason` y métricas útiles sin mostrar teléfonos completos por defecto
- `evaluación automática`: el repo incluye un set local de frases RD de cobranza para medir accuracy del clasificador

## Reporte Estructurado Diario

El AGI puede escribir un evento JSONL final por cada intento EAGI para luego consolidar el resultado diario sin usar base de datos.

Campos del evento:

- `timestamp`
- `uniqueid`
- `channel`
- `caller`
- `intent`
- `state`
- `confidence`
- `matched_phrase`
- `text`
- `stop_reason`
- `attempts`
- `source`

Si `mask_phone_numbers=true`, el JSONL enmascara `caller` y tambien cualquier numero sensible que aparezca en `channel`, `matched_phrase` o `text`.

### Activar El Reporte

Opcion recomendada en [config/ivr.yml](/D:/repos/ai-recepcionista/config/ivr.yml):

```yaml
logging:
  events_path: "/var/log/asterisk/vosk_cobranza_events.jsonl"
```

El default del repo es `/var/log/asterisk/vosk_cobranza_events.jsonl`.

Para laboratorio sin permisos de `root`, puedes usar un path local del repo:

```yaml
logging:
  events_path: "./logs/vosk_cobranza_events.jsonl"
```

Alternativamente, `config/logging.yml` tambien acepta `events_path` o `reporting.events_path` si prefieres centralizar ahi el destino del JSONL.

Si quieres poblar `attempts`, el dialplan puede pasar el contador actual como segundo argumento del AGI, por ejemplo `EAGI(vosk_cobranza.py,${OPCION},${TRY})`. Si no se envia, el campo queda vacio.

### Generar El Reporte Diario

Ejemplos:

```bash
python scripts/report_ivr_calls.py --date 2026-05-22
python scripts/report_ivr_calls.py --from 2026-05-01 --to 2026-05-22
python scripts/report_ivr_calls.py --all --csv ./logs/ivr_calls.csv --json ./logs/ivr_calls.json
```

Comportamiento del script:

- lee el JSONL configurado o uno alterno con `--input`
- deduplica por `uniqueid` y conserva el ultimo evento final de la llamada
- resume conteos por `intent`
- resume conteos por `state`
- puede exportar las llamadas deduplicadas a CSV con `--csv`
- puede exportar el reporte estructurado a JSON con `--json`

El JSONL del AGI no guarda `DIALSTATUS` porque su alcance termina antes de la transferencia. Aun asi, el `uniqueid` del evento permite correlacionar despues ese resultado con CDR de Asterisk o con una integracion posterior. Este repo no implementa todavia una integracion con VICIdial para esa correlacion.

### Significado De Cada State

- `TRANSFERIR_A_ABOGADO`: la llamada mostro interes claro o necesita detalle de cobro; aplica a `SI`, `INFO_COBRO` y `PROMESA_PAGO`
- `NO_INTERESADO`: rechazo explicito; aplica a `NO`
- `LLAMAR_DESPUES`: la persona pidio retomar mas tarde; aplica a `CALLBACK`
- `NUMERO_EQUIVOCADO`: la linea no corresponde al contacto buscado
- `NO_ES_PERSONA`: quien contesta indica que no es el titular o no corresponde a esa deuda
- `NO_ENTENDIDO`: la respuesta fue ambigua o no clasificable; aplica a `DUDA`
- `SIN_RESPUESTA`: no hubo audio util; aplica a `SILENCIO`

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
