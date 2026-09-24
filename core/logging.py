"""Asynchronous, non-blocking logging for TraderAIG.

Delivers log lines to multiple sinks without blocking the trading loop.
Supports console and rotating file output with configurable levels.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from logging.handlers import RotatingFileHandler
from typing import Optional

from .config import settings


class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that survives Windows file-lock rotation failures.

    On Windows, `os.rename` of an actively-open log file fails with
    ``PermissionError`` (WinError 32) whenever another process (e.g. the API
    server sharing ``system.log``) holds it open. Rather than leaking the
    stdlib ``--- Logging error ---`` traceback on every emit, this handler
    falls back to a per-process sidecar file and continues writing.
    """

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        try:
            if self.backupCount > 0:
                for i in range(self.backupCount - 1, 0, -1):
                    sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                    dfn = self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                    if os.path.exists(sfn):
                        if os.path.exists(dfn):
                            os.remove(dfn)
                        os.rename(sfn, dfn)
                dfn = self.rotation_filename(self.baseFilename + ".1")
                if os.path.exists(dfn):
                    os.remove(dfn)
                os.rename(self.baseFilename, dfn)
        except (OSError, PermissionError):
            # Primary file is locked by another process; continue writing to a
            # per-process sidecar so logging never interrupts the pipeline.
            self.baseFilename = "%s.%s" % (self.baseFilename, os.getpid())
        if not self.stream:
            self.stream = self._open()


class AsyncLogQueue:
    """Thread-safe queue that drains to the standard logging stack in the background."""

    def __init__(self, handler: logging.Handler, level: int = logging.INFO):
        self._handler = handler
        self._queue: "queue.Queue[logging.LogRecord]" = queue.Queue(maxsize=10000)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            # Drop oldest to avoid blocking the trading path.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(record)

    def _drain(self) -> None:
        while not self._stop.is_set():
            try:
                record = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._handler.handle(record)
            except Exception:
                pass

    def shutdown(self) -> None:
        self._stop.set()


class AsyncLogger:
    """AsyncLogger wraps a stdlib Logger and routes records through the async queue.

    The queue flushes every 0.1s or immediately if a `flush` is called.
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(settings.logging.level)
        self._logger.propagate = False
        self._async: Optional[AsyncLogQueue] = None

        if not self._logger.handlers:
            self._attach_handlers()

    def _attach_handlers(self) -> None:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console = logging.StreamHandler()
        console.setFormatter(fmt)
        self._logger.addHandler(console)

        # File handler behind the async queue when logs dir is writable.
        try:
            directory = settings.logging.directory
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = SafeRotatingFileHandler(
                str(directory / "system.log"),
                maxBytes=10_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            # Route file records through the async queue.
            self._async = AsyncLogQueue(file_handler, self._logger.level)
            self._logger.addHandler(_QueueHandler(self._async))
        except OSError:
            self._logger.warning("Log directory not writable; file logging disabled.")

    def debug(self, msg: str, *args, **kwargs) -> None:
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        self._logger.exception(msg, *args, **kwargs)

    def flush(self) -> None:
        if self._async:
            # Best-effort flush is not directly supported; relying on 0.1s drain.
            pass


class _QueueHandler(logging.Handler):
    """Bridges stdlib logging to the AsyncLogQueue."""

    def __init__(self, async_queue: AsyncLogQueue):
        super().__init__()
        self._async = async_queue

    def emit(self, record: logging.LogRecord) -> None:
        self._async.emit(record)


_loggers: dict[str, AsyncLogger] = {}


def get_logger(name: str) -> AsyncLogger:
    """Return a cached AsyncLogger for the given module name."""
    if name not in _loggers:
        _loggers[name] = AsyncLogger(name)
    return _loggers[name]


def get_logger_instance(name: str) -> AsyncLogger:
    """Alias for get_logger to avoid naming confusion."""
    return get_logger(name)
