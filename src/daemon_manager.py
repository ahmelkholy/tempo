#!/usr/bin/env python3
"""
Daemon Manager - Start/stop HTTP daemon from GUI
"""

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .core import _atomic_write_text
from .system import DAEMON_PID_FILE as APP_DAEMON_PID_FILE
from .system import LOG_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)


class DaemonManager:
    """Manages the HTTP daemon lifecycle"""

    DAEMON_PID_FILE = APP_DAEMON_PID_FILE
    DAEMON_PORT = 8765
    DAEMON_HOST = "127.0.0.1"

    def __init__(self, on_status_changed: Optional[Callable[[str], None]] = None):
        """
        Initialize daemon manager

        Args:
            on_status_changed: Callback when daemon status changes (status: str)
        """
        self.on_status_changed = on_status_changed
        self._daemon_process: Optional[subprocess.Popen] = None
        self._status = "unknown"  # unknown, stopped, running, error
        self._check_thread: Optional[threading.Thread] = None
        self._stop_checking = False
        self._owns_daemon = False

    @property
    def status(self) -> str:
        """Get current daemon status"""
        return self._status

    def _set_status(self, status: str):
        """Set status and notify callback"""
        if self._status != status:
            self._status = status
            logger.info(f"Daemon status changed: {status}")
            if self.on_status_changed:
                self.on_status_changed(status)

    def is_running(self) -> bool:
        """Check if daemon is running"""
        import urllib.request

        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(
                f"http://{self.DAEMON_HOST}:{self.DAEMON_PORT}/", timeout=2
            ) as response:
                info = json.loads(response.read(4096))
                return (
                    isinstance(info, dict)
                    and info.get("name") == "Ultimate Focus Timer Daemon"
                    and info.get("status") == "online"
                )
        except (OSError, ValueError):
            return False

    def _resolve_python_executable(self) -> str:
        """Prefer a windowless Python executable on Windows for daemon launch."""
        current_executable = Path(sys.executable)
        if sys.platform != "win32":
            return str(current_executable)

        candidates = []
        if current_executable.name.lower() == "pythonw.exe":
            candidates.append(current_executable)
            candidates.append(current_executable.parent / "python.exe")
        else:
            candidates.append(current_executable.parent / "pythonw.exe")
            candidates.append(current_executable)

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return str(current_executable)

    def _creation_flags(self) -> int:
        """Return subprocess flags that keep the daemon hidden on Windows."""
        if sys.platform != "win32":
            return 0
        return subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    def start(self) -> bool:
        """Start the daemon in background"""
        try:
            if self.is_running():
                logger.info("Daemon already running")
                self._set_status("running")
                return True

            logger.info("Starting daemon...")
            self._set_status("starting")

            python_exe = self._resolve_python_executable()

            # Start daemon subprocess - capture stderr for debugging
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_file = LOG_DIR / "daemon.log"
            with open(log_file, "a") as logf:
                self._daemon_process = subprocess.Popen(
                    (
                        [python_exe, "--daemon"]
                        if getattr(sys, "frozen", False)
                        else [python_exe, "-m", "src.daemon"]
                    ),
                    cwd=str(PROJECT_ROOT),
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    creationflags=self._creation_flags(),
                )
            self._owns_daemon = True

            # Save PID
            if self._daemon_process and self._daemon_process.pid:
                _atomic_write_text(self.DAEMON_PID_FILE, str(self._daemon_process.pid))

            # Wait for daemon to start
            for attempt in range(15):
                time.sleep(0.5)
                if self._daemon_process.poll() is not None:
                    break
                if self.is_running():
                    logger.info("Daemon started successfully")
                    self._set_status("running")
                    return True

            logger.warning("Daemon did not start. See %s", log_file)
        except Exception:
            logger.exception("Error starting daemon")
        self._stop_owned_process()
        self._set_status("error")
        return False

    def _stop_owned_process(self):
        proc = self._daemon_process
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        if self.DAEMON_PID_FILE.exists() and self.DAEMON_PID_FILE.read_text() == str(
            proc.pid
        ):
            self.DAEMON_PID_FILE.unlink(missing_ok=True)
        self._daemon_process = None
        self._owns_daemon = False

    def stop(self, managed_only: bool = False) -> bool:
        """Stop the child started by this instance."""
        try:
            if not self._owns_daemon:
                return managed_only or not self.is_running()
            self._stop_owned_process()
            self._set_status("stopped")
            return True
        except (OSError, subprocess.SubprocessError):
            logger.exception("Error stopping daemon")
            self._set_status("error")
            return False

    def check_status_background(self, interval: float = 60.0):
        """Start background thread to check daemon status"""
        self._stop_checking = False

        def _check():
            while not self._stop_checking:
                if self.is_running():
                    if self._status != "running":
                        self._set_status("running")
                else:
                    if self._status != "stopped":
                        self._set_status("stopped")
                time.sleep(interval)

        self._check_thread = threading.Thread(target=_check, daemon=True)
        self._check_thread.start()

    def stop_background_check(self):
        """Stop background status checker"""
        self._stop_checking = True
        if self._check_thread:
            self._check_thread.join(timeout=2)

    def get_status_display(self) -> str:
        """Get human-readable status"""
        status_map = {
            "running": "🟢 Daemon: Running",
            "stopped": "🔴 Daemon: Stopped",
            "starting": "🟡 Daemon: Starting...",
            "stopping": "🟡 Daemon: Stopping...",
            "error": "⚠️  Daemon: Error",
            "unknown": "❓ Daemon: Unknown",
        }
        return status_map.get(self._status, "❓ Daemon: Unknown")
