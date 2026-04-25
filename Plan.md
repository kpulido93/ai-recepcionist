# Plan.md

## Estado del plan
- Estado: cerrado para implementación.
- Alcance: sin cambios respecto a `AGENTS.md`, `Prompt.md` e `Implement.md`.
- Fase actual: documentación y diseño; todavía no hay código.

## Guardrails no negociables
- Python 3.11.
- Compatibilidad con Issabel/Asterisk 16/18.
- Un solo proceso `ari-worker` dueño del app Stasis `ai-recepcionista`.
- Un proceso separado `admin-api` con FastAPI.
- El cliente ARI vive solo en `ari-worker`; no entra en workers de FastAPI.
- `admin-api` no orquesta media ni controla el estado transaccional de la llamada.
- Media por ARI `externalMedia` usando RTP/UDP.
- No usar `chan_websocket` para media.
- Transferencia a agentes por AMI Redirect.
- STT local: Vosk principal y faster-whisper como fallback.
- TTS local: XTTS-v2 y Chatterbox-Multilingual detrás de una interfaz común.
- Sin servicios cloud de voz en la V1.
- Guion corto, una sola repregunta, transferencia solo con sí explícito, callback si no hay agente, guardar disposición final y no negociar dentro del bot.
- Diffs pequeños y cierre por hitos.

## Supuestos de diseño fijados
- El microservicio corre localmente o en la misma red privada del PBX.
- La app Stasis objetivo es `ai-recepcionista` y la posee un único `ari-worker`.
- La ruta de audio se implementa con `externalMedia` y un pipeline RTP/UDP -> PCM -> STT, y la respuesta usa TTS -> audio de retorno.
- El audio se normaliza internamente a PCM lineal mono con estrategia de resampling documentada, sin acoplar el core a un codec de telefonía concreto.
- La integración con VICIdial se resuelve por adaptadores, sin fijar todavía un backend adicional fuera de lo que el entorno ya requiera.
- La persistencia de callback, auditoría y disposición final queda detrás de puertos/adaptadores para no forzar una base concreta antes de tener requisito explícito.
- Los modelos STT/TTS se instalan de forma local y no se descargan dinámicamente en tiempo de llamada.
- Cada llamada mantiene correlación única entre `channel`, `bridge`, `externalMedia` y registros de auditoría para facilitar soporte e idempotencia.
- Los eventos de silencio, no-input, cuelgue remoto y cleanup de media forman parte del diseño base de la FSM y no se tratan como extensiones futuras.
- Salud y readiness se separan: proceso vivo no implica dependencias listas.

## Calidad obligatoria al cerrar cada hito
- `ruff check .`
- `ruff format --check .`
- `mypy src`
- `pytest -q`

## Hitos

## M1 - Bootstrap y límites de procesos
Aceptación:
- estructura mínima del repo creada bajo `src/`, `tests/` y `docs/`
- `pyproject.toml` con tooling de lint, formato, tipos y tests
- configuración central por variables de entorno y archivo de ejemplo
- contrato de configuración documentado para ARI, AMI, RTP, modelos locales, persistencia y logging
- entrypoint independiente para `ari-worker`
- entrypoint independiente para `admin-api`
- `admin-api` levanta sin cliente ARI embebido
- separación explícita entre API administrativa y runtime de llamada reflejada en la estructura de módulos
- logging estructurado y manejo de configuración listos para ambos procesos
- `Documentation.md` actualizado con comandos y estado

Validación:
- `uvicorn src.ai_recepcionista.api.app:app --host 0.0.0.0 --port 8000`
- `pytest -q`

## M2 - Control de llamada ARI y media RTP
Aceptación:
- conexión ARI estable con reconexión y cierre ordenado
- manejo de `StasisStart` y `StasisEnd`
- registro de sesión por llamada con cleanup garantizado
- correlación de identificadores de llamada, bridge y `externalMedia` por sesión
- bridge y `externalMedia` por RTP/UDP operativos
- reproducción de saludo simple funcional
- canal de retorno de audio hacia la llamada definido
- normalización RTP -> PCM lista para alimentar STT
- estrategia de codec, resampling y teardown de media documentada para Asterisk 16/18
- manejo explícito de cuelgue remoto, pérdida de media y liberación de puertos RTP
- smoke test pensado para Asterisk 16/18

Validación:
- tests de eventos ARI y ciclo de vida de sesión
- smoke test con WAV y flujo de playback

## M3 - Pipeline local de STT y TTS
Aceptación:
- interfaz común de STT con streaming incremental
- Vosk como implementación principal
- faster-whisper como fallback
- interfaz común de TTS
- XTTS-v2 implementado detrás de la interfaz
- Chatterbox-Multilingual implementado detrás de la interfaz
- caché de frases fijas para saludo y respuestas breves
- documentación de instalación local de modelos y prerequisitos
- validación de presencia y warmup mínimo de modelos locales antes de aceptar tráfico
- criterio de fallback documentado para fallos de carga o ejecución del STT principal
- presupuesto básico de latencia medido de extremo a extremo del pipeline de voz

Validación:
- tests con fixtures WAV
- tests de selección de proveedor/fallback
- benchmark básico de latencia offline

## M4 - FSM de diálogo y reglas de negocio
Aceptación:
- FSM de llamada con saludo, pregunta principal y cierre
- una sola repregunta para `UNCLEAR`
- clasificación `YES`, `NO` y `UNCLEAR`
- manejo de silencio/no-input dentro de la misma regla de una sola repregunta
- transferencia solo con `YES` explícito
- si no hay agente disponible, creación de callback
- si no hay `YES`, cierre normal con disposición final
- no se implementa negociación ni validación de identidad
- catálogo de disposiciones finales definido y documentado

Validación:
- tests unitarios de FSM y reglas
- tests de tabla de decisión `YES/NO/UNCLEAR`

## M5 - Integración con Issabel, AMI y VICIdial
Aceptación:
- adaptador de AMI Redirect para transferencia a agente
- verificación de disponibilidad de agente antes de transferir
- adaptador para crear callback cuando no haya agente
- adaptador para guardar disposición final y auditoría básica
- contratos de integración documentados para Issabel/VICIdial
- contrato explícito de campos mínimos para disponibilidad, callback, disposición y correlación de llamada
- operaciones de callback y disposición diseñadas para ser idempotentes por llamada/sesión
- mocks o simuladores de integración para pruebas automáticas

Validación:
- tests de integración con mocks de AMI y adapters
- escenario de transferencia exitosa y escenario de callback

## M6 - Admin API, operación local y empaquetado
Aceptación:
- FastAPI expone salud, readiness y estado operativo básico
- endpoints administrativos limitados al alcance V1
- semántica de health/readiness documentada para proceso, configuración y dependencias locales
- Dockerfile del servicio
- `docker-compose` para entorno local
- unit file de `systemd` para despliegue
- guía de configuración de red, puertos, modelos y credenciales locales
- guía de carpetas locales, secretos por entorno y prerrequisitos del host
- estrategia de apagado ordenado y arranque de ambos procesos documentada

Validación:
- smoke test de arranque local con contenedores
- smoke test de servicio con `systemd`

## M7 - End-to-end y cierre de V1
Aceptación:
- una llamada entra a Stasis
- el bot reproduce saludo
- el bot escucha y clasifica
- con `YES` explícito se transfiere por AMI Redirect
- sin agente disponible se crea callback
- sin `YES` se cuelga con disposición final
- los checks de lint, formato, tipos y tests pasan
- `Documentation.md` queda actualizado con decisiones y pendientes residuales
- `docs/runbook.md` y `docs/architecture.md` quedan consistentes con lo implementado

Validación:
- suite completa de calidad
- prueba end-to-end mínima en entorno local controlado

## Fuera de alcance en esta V1
- negociación automática
- validación de identidad
- WhatsApp o SMS
- STT/TTS cloud
