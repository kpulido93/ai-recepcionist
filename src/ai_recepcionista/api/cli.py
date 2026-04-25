from __future__ import annotations

import uvicorn

from ..core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ai_recepcionista.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
