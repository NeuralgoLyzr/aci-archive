import logging
from logging.handlers import RotatingFileHandler

try:
    # The K8s OTel operator injects OTEL_TRACES_SAMPLER_ARG, which logfire
    # mis-reads as its float trace_sample_rate; neutralize it before importing.
    from aci.common.otel_compat import neutralize_incompatible_otel_sampler_env

    neutralize_incompatible_otel_sampler_env()

    import logfire
except Exception:
    # An incompatible opentelemetry SDK or env injected by the OTel operator's
    # auto-instrumentation can make logfire fail to import (ImportError, or a
    # ValueError raised while it reads its config); run without it.
    logfire = None  # type: ignore[assignment]


# the setup is called once at the start of the app
def setup_logging(
    formatter: logging.Formatter | None = None,
    level: int = logging.INFO,
    filters: list[logging.Filter] | None = None,
    include_file_handler: bool = False,
    file_path: str | None = None,
    environment: str = "local",
) -> None:
    if filters is None:
        filters = []

    if formatter is None:
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)  # Set the root logger level

    # Create a console handler (for output to console)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    for filter in filters:
        console_handler.addFilter(filter)
    root_logger.addHandler(console_handler)

    if include_file_handler:
        if file_path is None:
            raise ValueError("file_path must be provided if include_file_handler is True")
        file_handler = RotatingFileHandler(file_path, maxBytes=10485760, backupCount=10)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        for filter in filters:
            file_handler.addFilter(filter)
        root_logger.addHandler(file_handler)

    if environment != "local":
        if logfire is not None:
            root_logger.addHandler(logfire.LogfireLoggingHandler())
        else:
            root_logger.warning("logfire unavailable - skipping LogfireLoggingHandler")

    # Set up module-specific loggers if necessary (e.g., with different levels)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger
