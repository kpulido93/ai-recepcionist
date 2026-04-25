from __future__ import annotations

import argparse
import logging
import signal
import time
from collections.abc import Sequence

from ..core.config import get_settings
from ..core.logging import configure_logging

LOGGER_NAME = "ai_recepcionista.ari_worker"
SERVICE_NAME = "ari-worker"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap placeholder for the ari-worker process.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Start the worker, log bootstrap state, and exit immediately.",
    )
    return parser


def run_placeholder_worker(*, once: bool = False) -> int:
    settings = get_settings()
    configure_logging(
        service=SERVICE_NAME,
        environment=settings.environment,
        level=settings.log_level,
    )
    logger = logging.getLogger(LOGGER_NAME)
    logger.info(
        "ari_worker_bootstrap_ready",
        extra={"stasis_app_name": settings.stasis_app_name},
    )

    if once:
        return 0

    stop_requested = False

    def _request_stop(received_signal: int, _frame: object | None) -> None:
        nonlocal stop_requested
        stop_requested = True
        logger.info("ari_worker_stop_requested", extra={"signal": received_signal})

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    while not stop_requested:
        time.sleep(settings.worker_heartbeat_seconds)
        logger.info("ari_worker_heartbeat")

    logger.info("ari_worker_shutdown")
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(run_placeholder_worker(once=args.once))
