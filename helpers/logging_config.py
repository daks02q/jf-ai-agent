import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_URL = re.compile(r"(://[^:/@]+:)[^@]+(@)")


def redact_url(url: str | None) -> str:
    """ Masks the password in a DB connection string for safe logging,
    e.g. postgresql://user:secret@host/db -> postgresql://user:***@host/db.
    """
    if not url:
        return repr(url)
    return _SECRET_URL.sub(r"\1***\2", url)


def setup_logging(level: int = logging.INFO) -> None:
    """ Configures the root logger once, at process startup — every module
    logging via logging.getLogger(__name__) inherits this. Writes to both
    stdout (so `journalctl -u ai-agent -f` shows it live) and a rotating
    file under logs/ (so history survives past journald's retention).
    """
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # These libraries are INFO-chatty in a way that drowns out our own
    # logs without adding much — keep them at WARNING.
    for noisy in ("httpx", "httpcore", "asyncio", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
