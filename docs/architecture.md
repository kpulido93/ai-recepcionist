# Architecture V1

## Objetivo
Microservicio Python local para recepcionista digital de cobranza, integrado con Issabel/Asterisk + VICIdial, sin servicios cloud de voz y sin ampliar el alcance funcional definido.

## Componentes
- `ari-worker`: único dueño del app Stasis `ai-recepcionista`. Controla llamadas, sesiones, bridges, `externalMedia`, pipeline de voz, FSM y decisiones de transferencia/callback/cierre.
- `admin-api`: proceso FastAPI separado. Expone salud, readiness y operaciones administrativas básicas. No controla media ni contiene cliente ARI.
- Adaptador ARI: conexión al PBX, eventos `StasisStart` y `StasisEnd`, creación y cleanup de recursos por llamada.
- Adaptador AMI: ejecuta `Redirect` para transferir a un agente solo cuando existe un `YES` explícito y hay disponibilidad.
- Adaptadores de integración: resuelven disponibilidad de agente, creación de callback, auditoría y guardado de disposición final sin fijar todavía un backend concreto.
- Motores de voz locales:
  - STT principal: Vosk.
  - STT fallback: faster-whisper.
  - TTS: XTTS-v2 y Chatterbox-Multilingual detrás de una interfaz común.

## Flujo de llamada
1. Asterisk entrega la llamada al app Stasis `ai-recepcionista`.
2. `ari-worker` crea la sesión de llamada, correlaciona IDs y prepara bridge + canal `externalMedia`.
3. El audio entra por RTP/UDP, se desempaqueta y se normaliza a PCM lineal mono para el pipeline de STT.
4. El STT produce texto incremental; el clasificador reduce la respuesta a `YES`, `NO` o `UNCLEAR`.
5. La FSM aplica reglas de negocio:
   - saludo corto
   - una sola repregunta si el resultado es `UNCLEAR` o no hay input útil
   - transferencia solo con `YES` explícito
   - callback si hay `YES` pero no hay agente disponible
   - cierre normal con disposición final en cualquier otro caso
6. Si corresponde responder por voz, el texto pasa al TTS local y vuelve a la llamada por el canal de retorno de audio.
7. Al finalizar la llamada, el worker persiste auditoría y disposición, y libera bridge, media y recursos de sesión.

## Límites de arquitectura
- Solo existe un propietario del app Stasis: `ari-worker`.
- `admin-api` queda aislado del runtime de voz y no participa en el control de llamada.
- La media usa `externalMedia` con RTP/UDP; no se usa `chan_websocket`.
- La transferencia se hace con AMI Redirect; no se cambia este mecanismo en V1.
- No hay negociación automática, validación de identidad, WhatsApp/SMS ni STT/TTS cloud.

## Operación local
- El servicio corre en el mismo host o red privada accesible desde el PBX.
- La configuración entra por variables de entorno y archivos locales.
- Los modelos STT/TTS deben estar presentes antes de aceptar tráfico; no se descargan durante la llamada.
- Health y readiness se separan: proceso vivo no implica ARI/AMI/modelos listos.
- Logging y auditoría deben permitir rastrear cada llamada por sus IDs correlacionados.

## Criterios de compatibilidad
- Se mantiene compatibilidad con Issabel/Asterisk 16/18.
- El diseño debe tolerar cuelgue remoto, pérdida de media y cleanup ordenado.
- Las integraciones con VICIdial se encapsulan detrás de contratos para mantener diffs pequeños y por hito.
