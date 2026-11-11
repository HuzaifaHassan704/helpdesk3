"""Structured logging: every log line (ours, uvicorn's, SQLAlchemy's) goes through structlog."""

import logging
import sys

import structlog

from app.core.config import settings


def configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,  # request_id, path, user_id ... bound by middleware/deps
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer = structlog.processors.JSONRenderer() if settings.LOG_JSON else structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,  # applies the same processors to stdlib/uvicorn records
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Route uvicorn through the root handler; our middleware emits the access log instead.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if settings.DEBUG else logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
