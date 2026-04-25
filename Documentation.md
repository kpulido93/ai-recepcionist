# Documentation.md

## Estado actual
- Fecha de referencia: 2026-04-25.
- Estado del proyecto: `M1 - Bootstrap` implementado y validado.
- Estado del workspace: ya existe scaffold de aplicación, pero todavía no hay ARI ni lógica de negocio real.
- Alcance funcional: sin cambios respecto a `AGENTS.md`, `Prompt.md`, `Plan.md` e `Implement.md`.

## Inventario real del repo
Base de aplicación disponible:
- `pyproject.toml`
- `.env.example`
- `Dockerfile`
- `docker-compose.yml`
- `src/`
- `tests/`
- `docs/`

Módulos implementados en `M1`:
- `src/ai_recepcionista/api/app.py`: FastAPI admin API con `/health`, `/ready` y `/version`
- `src/ai_recepcionista/api/cli.py`: entrypoint de `admin-api`
- `src/ai_recepcionista/ari_worker/cli.py`: placeholder separado para `ari-worker`
- `src/ai_recepcionista/core/config.py`: configuración central por variables de entorno
- `src/ai_recepcionista/core/logging.py`: logging estructurado JSON

## Decisiones consolidadas en M1
- Se mantiene objetivo de compatibilidad con Python 3.11.
- El `Dockerfile` usa `python:3.11-slim`.
- La ruta de arranque pedida para desarrollo local queda en `src.ai_recepcionista.api.app:app`.
- `admin-api` queda aislado de ARI y solo expone endpoints administrativos.
- `ari-worker` existe como proceso separado, pero en `M1` solo arranca como placeholder sin integrar ARI.
- La configuración central cubre desde ahora ARI, AMI, RTP, backends de callback/disposición/auditoría y parámetros de proceso.

## Estado operativo de M1
Disponible hoy:
- `GET /health`
- `GET /ready`
- `GET /version`
- tests básicos del admin API
- tooling de `ruff`, `mypy` y `pytest`
- empaquetado inicial con Docker y Compose

Pendiente para siguientes hitos:
- conexión ARI real
- media `externalMedia` RTP/UDP
- pipeline STT/TTS local
- FSM de diálogo
- integración AMI/VICIdial
- operación end-to-end de llamada

## Comandos de trabajo
Crear entorno e instalar dependencias de desarrollo:
- `python -m venv .venv`
- `.\.venv\Scripts\python.exe -m pip install --ignore-requires-python -e .[dev]`

Levantar admin API:
- `.\.venv\Scripts\uvicorn.exe src.ai_recepcionista.api.app:app --host 0.0.0.0 --port 8000`

Levantar placeholder de worker:
- `.\.venv\Scripts\ari-worker.exe --once`

Validaciones obligatorias del repo:
- `.\.venv\Scripts\pytest.exe -q`
- `.\.venv\Scripts\ruff.exe check .`
- `.\.venv\Scripts\python.exe -m mypy src`

## Nota de entorno local
- Esta máquina no tiene Python 3.11 instalado; la validación local de este hito se ejecutó con Python 3.12.
- El código, el `Dockerfile` y la configuración siguen orientados al runtime objetivo 3.11.

## Riesgos abiertos
- La mayor incertidumbre técnica sigue en `externalMedia` RTP/UDP y la compatibilidad práctica con Asterisk 16/18.
- La latencia y el consumo de STT/TTS locales todavía no se han medido sobre hardware objetivo.
- Los contratos concretos con Issabel/VICIdial para disponibilidad, callback y disposición siguen pendientes de implementación en `M5`.
