#!/usr/bin/env python3
"""
system.py - OS-level integrations for Ultimate Focus Timer.

Combines: app_paths, logger, music_controller, notification_manager,
          tray_manager, hotkey_manager
"""

import json
import logging
import logging.handlers
import os
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ══════════════════════════════════════════════════════════════════════════════
# APP PATHS
# ══════════════════════════════════════════════════════════════════════════════


def _find_project_root() -> Path:
    """Resolve the project root whether running as script or frozen exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Running from source: this file lives at <root>/src/system.py
    return Path(__file__).resolve().parent.parent


def _default_app_home(project_root: Path) -> Path:
    """Resolve the writable app home for config, data, logs, and pid files."""
    env_home = os.environ.get("FOCUS_HOME")
    if env_home:
        return Path(env_home).expanduser()

    # In a source checkout, keep using the checkout folder so existing installs
    # like this long-lived AppData copy do not silently move their data.
    if not getattr(sys, "frozen", False) and (
        (project_root / ".git").exists() or (project_root / "config.yml").exists()
    ):
        return project_root

    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "focus"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "focus"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "focus"


PROJECT_ROOT: Path = _find_project_root()
APP_HOME: Path = _default_app_home(PROJECT_ROOT)

SRC_DIR: Path = PROJECT_ROOT / "src"
DATA_DIR: Path = APP_HOME / "data"
LOG_DIR: Path = APP_HOME / "log"
EXPORTS_DIR: Path = APP_HOME / "exports"

CONFIG_FILE: Path = APP_HOME / "config.yml"
TASKS_FILE: Path = DATA_DIR / "daily_tasks.json"
SESSION_LOG_FILE: Path = LOG_DIR / "focus.log"
APP_LOG_FILE: Path = LOG_DIR / "app.log"
ERROR_LOG_FILE: Path = APP_HOME / "error.log"
MPV_PID_FILE: Path = APP_HOME / "mpv_classical.pid"
DAEMON_PID_FILE: Path = APP_HOME / "daemon.pid"


def ensure_dirs() -> None:
    """Create required runtime directories if they don't exist."""
    for directory in (APP_HOME, DATA_DIR, LOG_DIR, EXPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════════════

_CONSOLE_FORMAT = "%(levelname)-8s %(name)s - %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO, verbose: bool = False) -> None:
    """Configure the root logger with a StreamHandler and a RotatingFileHandler."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    if root.handlers:
        return  # Already configured

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else level)
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))

    file_handler = logging.handlers.RotatingFileHandler(
        APP_LOG_FILE,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))

    root.addHandler(console_handler)
    root.addHandler(file_handler)

    for noisy in ("matplotlib", "PIL", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).debug("Logging initialised (app log: %s)", APP_LOG_FILE)


# ══════════════════════════════════════════════════════════════════════════════
# MUSIC CONTROLLER
# ══════════════════════════════════════════════════════════════════════════════

logger = logging.getLogger(__name__)

_SUBPROCESS_FLAGS: int = (
    subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
)


def _mac_music_proxy() -> str:
    """Resolve the active route on demand; a stopped local proxy means direct."""
    if platform.system() != "Darwin":
        return ""
    import socket
    import urllib.request
    from urllib.parse import urlsplit

    proxies = urllib.request.getproxies()
    # A GUI's no_proxy setting makes getproxies() ignore macOS settings.
    # Recover the system route when the environment only defines exclusions.
    if "no" in proxies and not (proxies.get("https") or proxies.get("http")):
        system_proxies = getattr(urllib.request, "getproxies_macosx_sysconf", dict)()
        proxies = {**system_proxies, **proxies}
    proxy = proxies.get("https") or proxies.get("http") or ""
    if not proxy:
        return ""
    try:
        parsed = urlsplit(proxy)
        if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
            with socket.create_connection(
                (parsed.hostname, parsed.port or 80), timeout=0.3
            ):
                pass
    except (OSError, ValueError):
        return ""
    return proxy


def youtube_source_kind(link: str) -> str:
    """Identify playlist-bearing YouTube links without changing their URL."""
    from urllib.parse import parse_qs, urlsplit

    parsed = urlsplit(link)
    host = (parsed.hostname or "").lower()
    if host not in ("youtube.com", "youtu.be") and not host.endswith(".youtube.com"):
        return ""
    playlist = parse_qs(parsed.query).get("list", [""])[0]
    return "radio" if playlist.startswith("RD") else "playlist" if playlist else "video"


def _mix_watch_url(source, remembered):
    """Preserve the Mix while opening a shared link or a remembered song."""

    import re
    from urllib.parse import parse_qs, urlencode, urlsplit

    parsed = urlsplit(source)
    query = parse_qs(parsed.query)
    mix_id = query["list"][0]
    video = (query.get("v") or [""])[0]
    if youtube_source_kind(remembered):
        last = parse_qs(urlsplit(remembered).query).get("v", [""])[0]
        if last != video and re.fullmatch(r"[a-zA-Z0-9_-]{11}", last):
            return mix_id, "https://www.youtube.com/watch?" + urlencode(
                {"v": last, "list": mix_id}
            )
    if parsed.hostname == "youtu.be" or parsed.path.startswith(
        ("/shorts/", "/embed/", "/live/")
    ):
        video = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    elif parsed.path == "/playlist" and not video:
        video = mix_id[2:]
    if parsed.path != "/watch" and re.fullmatch(r"[a-zA-Z0-9_-]{11}", video):
        query["v"] = [video]
        source = "https://www.youtube.com/watch?" + urlencode(query, doseq=True)
    elif parsed.path in ("/watch", "/playlist"):
        source = parsed._replace(
            scheme="https", netloc="www.youtube.com", fragment=""
        ).geturl()
    return mix_id, source


def normalise_music_link(link: str) -> str:
    """Validate one pasted media URL, repairing an exact double paste."""
    import re
    from urllib.parse import parse_qs, urlsplit

    link = link.strip()
    half = len(link) // 2
    if len(link) % 2 == 0 and link[:half] == link[half:]:
        link = link[:half]
    parsed = urlsplit(link)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or re.search(r"\s", link)
        or len(re.findall(r"https?://", link)) != 1
    ):
        raise ValueError("Paste one complete https:// video or playlist link.")
    host = parsed.hostname.lower()
    if host == "youtube.com" or host.endswith(".youtube.com"):
        query = parse_qs(parsed.query)
        if parsed.path == "/watch" and not query.get("v"):
            raise ValueError("This YouTube link is missing its video ID.")
        if parsed.path == "/playlist" and not query.get("list"):
            raise ValueError("This YouTube link is missing its playlist ID.")
    return link


_CHROME_COOKIE_ERROR = "The player couldn’t read your Chrome session. Connect Chrome to play your personal Mix in the timer."
_CHROME_SIGNED_OUT = "Sign in to YouTube in the Chrome profile with Focus Timer Mix enabled, then choose Connect Chrome in the timer."
_CHROME_CONNECTION_ERROR = (
    "Enable Focus Timer Mix in your Chrome profile, then return to the timer."
)
_CHROME_CONNECTION_ERRORS = {
    "extension": _CHROME_CONNECTION_ERROR,
    "pairing": "Chrome is paired with another timer folder. Load the folder shown in Connect Chrome.",
    "timeout": "Chrome didn’t answer the timer. Check that Focus Timer Mix is enabled in the profile you’re using.",
    "signin": _CHROME_SIGNED_OUT,
    "network": "Chrome could not load YouTube. Check that the Mix opens in your signed-in Chrome profile.",
    "mix": "YouTube didn’t return a queue for this Mix. Check the Mix link in Chrome.",
    "format": "Focus Timer Mix couldn’t read YouTube’s song order. Check for a timer update.",
}


def _chrome_mix_session():
    """Prefer the profile Chrome last used when more than one profile is signed in."""
    if sys.platform == "darwin":
        root = Path.home() / "Library/Application Support/Google/Chrome"
    elif sys.platform == "win32":
        root = (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "Google/Chrome/User Data"
        )
    else:
        root = (
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "google-chrome"
        )
    try:
        state = json.loads((root / "Local State").read_text(encoding="utf-8"))
        profile = state["profile"]["last_used"]
        if profile == "Default" or (
            isinstance(profile, str)
            and profile.startswith("Profile ")
            and profile[8:].isdigit()
        ):
            return f"chrome:{profile}"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "chrome"


def _music_failure_reason(line: str) -> Optional[str]:
    """Translate player diagnostics without exposing signed URLs or credentials."""
    text = line.lower()
    if "focus chrome connection:" in text:
        code = text.partition("focus chrome connection:")[2].strip().split()
        return _CHROME_CONNECTION_ERRORS.get(
            code[0] if code else "", _CHROME_CONNECTION_ERROR
        )
    if (
        "cookie" in text
        and any(
            word in text
            for word in ("decrypt", "could not", "failed", "permission denied")
        )
    ) or "keychain" in text or "dpapi" in text:
        return _CHROME_COOKIE_ERROR
    if "focus mix: youtube returned a signed-out queue" in text:
        return _CHROME_SIGNED_OUT
    if "focus mix: youtube returned only one song" in text:
        return _CHROME_CONNECTION_ERRORS["mix"]
    if "focus mix:" in text:
        return "YouTube changed this Mix. Reopen the Mix to load its current order."
    if "unsupported url" in text or "no suitable extractor" in text:
        return "The YouTube playback helper could not open this link. Update the helper and retry."
    if "playlist does not exist" in text or "playlist is private" in text:
        return "This YouTube playlist is unavailable or private. Add another link."
    if (
        "video unavailable" in text
        or "video is unavailable" in text
        or "private video" in text
        or "has been removed" in text
    ):
        return "This YouTube video is unavailable or private. Add another link."
    if "sign in" in text or "confirm you" in text or "http error 403" in text:
        return "YouTube requires sign-in or refused this stream."
    if ("yt-dlp" in text or "youtube-dl" in text) and (
        "not found" in text or "could not be found" in text
    ):
        return "The YouTube playback helper is missing."
    if "timed out" in text or "timeout" in text:
        return "Music connection timed out. Check your network or proxy, then retry."
    if (
        "connection refused" in text
        or "could not resolve" in text
        or "network is unreachable" in text
    ):
        return "Music cannot reach the network. Check your connection or proxy, then retry."
    if (
        "yt-dlp: error:" in text
        or "error parsing option" in text
        or "option not found" in text
    ):
        return "The music player settings are invalid. Check the player configuration."
    return None


def _read_pipe_json(pipe):
    """Yield JSON objects from an mpv named pipe, skipping malformed lines."""
    pending = b""
    read = getattr(pipe, "read1", pipe.read)
    while True:
        chunk = read(65536)
        if not chunk:
            return
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in lines:
            try:
                message = json.loads(line)
                if isinstance(message, dict):
                    yield message
            except (ValueError, UnicodeDecodeError):
                continue


def _music_operation(method):
    """Serialize controls, recovery, and shutdown for this player instance."""

    @wraps(method)
    def run(self, *args, **kwargs):
        with self._operation_lock:
            return method(self, *args, **kwargs)

    return run


class MusicController:
    """Cross-platform music controller using MPV."""

    def __init__(self, config_manager):
        self.config = config_manager
        self._operation_lock = threading.RLock()
        self.mpv_process: Optional[subprocess.Popen] = None
        self.pid_file: Path = MPV_PID_FILE
        self.ipc_socket: Optional[Path] = None

        self.mpv_executable: Optional[str] = None
        self._mpv_available: Optional[bool] = None
        self.current_playlist: Optional[str] = None
        self.bookmark = self.config.load_music_bookmark()
        self._closed = False
        self._pause_requested = False
        self._paused_for_break = False
        self._seek_on_load = None
        self.is_playing: bool = False
        self.current_track_name: str = ""
        self.playback_state = "stopped"
        self.last_error = ""
        self._playback_proxy = ""
        self._allow_proxy_retry = True
        self._using_chrome = False
        self._opening_track = ""
        self._guest_fallback = False
        self.play_attempt = 0
        self._live = {}
        self._live_time = time.monotonic()
        self._observed_process = None

    def _find_mpv_executable(self) -> Optional[str]:
        configured = self.config.get("mpv_executable", "mpv")
        if self._test_mpv_executable(configured):
            return configured

        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            for candidate in (
                exe_dir / "mpv.exe",
                exe_dir / "mpv",
                exe_dir / "_internal" / "mpv.exe",
                exe_dir / "_internal" / "mpv",
            ):
                if self._test_mpv_executable(str(candidate)):
                    return str(candidate)

        system = platform.system()
        search_paths: List[str] = []
        if system == "Darwin":
            search_paths = [
                "/opt/homebrew/bin/mpv",
                "/usr/local/bin/mpv",
                "/usr/bin/mpv",
                "mpv",
            ]
        elif system == "Linux":
            search_paths = [
                "/usr/bin/mpv",
                "/usr/local/bin/mpv",
                "/snap/bin/mpv",
                "mpv",
            ]
        elif system == "Windows":
            search_paths = [
                "mpv.exe",
                "mpv",
                str(Path.home() / "AppData" / "Local" / "mpv" / "mpv.exe"),
                "C:/Program Files/mpv/mpv.exe",
                "C:/Program Files (x86)/mpv/mpv.exe",
            ]

        for path in search_paths:
            if self._test_mpv_executable(path):
                return path

        logger.warning("MPV executable not found; music will be unavailable")
        return None

    def _test_mpv_executable(self, path: str) -> bool:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                timeout=5,
                creationflags=_SUBPROCESS_FLAGS,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return False

    def is_mpv_available(self) -> bool:
        if not self._mpv_available:
            self.mpv_executable = self._find_mpv_executable()
            self._mpv_available = self.mpv_executable is not None
        return self._mpv_available

    def get_available_playlists(self) -> List[Dict[str, Any]]:
        return self.config.get_music_playlists()

    def _select_default_playlist(self) -> Optional[str]:
        playlists = self.get_available_playlists()
        return playlists[0]["path"] if playlists else None

    @_music_operation
    def start_music(
        self,
        playlist_path: Optional[str] = None,
        volume: Optional[int] = None,
        *,
        _allow_proxy_retry: bool = True,
        _resume_track: str = "",
        _public_mix: bool = False,
        _start_paused: bool = False,
    ) -> bool:
        if self._closed:
            return False
        restore_track = playlist_path is None or not _allow_proxy_retry
        if (
            playlist_path is None
            and self.mpv_process
            and self.mpv_process.poll() is None
        ):
            if self._pause_requested or self.playback_state == "paused":
                return self.resume_music()
            return True

        self._stop_process_only()
        self._seek_on_load = None
        self.play_attempt += 1
        self.last_error = ""
        self.playback_state = "loading"
        if not self.is_mpv_available():
            self.playback_state = "error"
            self.last_error = "Install mpv to play music, then press Retry."
            logger.warning("MPV not available; skipping music start")
            return False

        if not playlist_path:
            playlist_path = self._select_default_playlist()

        if not playlist_path:
            self.playback_state = "error"
            self.last_error = "No music selected. Add a video or playlist link."
            logger.error("No playlist available to play")
            return False

        if (
            not playlist_path.startswith(("http://", "https://"))
            and not Path(playlist_path).exists()
        ):
            self.playback_state = "error"
            self.last_error = "This music file is unavailable. Reconnect its drive or choose another file."
            return False

        if volume is None:
            volume = int(self.config.get("classical_music_volume", 30))

        # Create IPC socket path for control
        import tempfile

        if platform.system() == "Windows":
            # mpv adds the named-pipe prefix on Windows.
            self.ipc_socket = Path(f"mpv_focus_{os.getpid()}_{id(self):x}")
        else:
            self.ipc_socket = (
                Path(tempfile.gettempdir()) / f"focus-{os.getpid()}-{id(self):x}.sock"
            )

        mpv_args = [
            self.mpv_executable,
            "--no-config",
            "--no-video",
            "--demuxer-max-bytes=4MiB",
            "--demuxer-max-back-bytes=1MiB",
            "--shuffle="
            + ("yes" if self.config.get("classical_music_shuffle", True) else "no"),
            "--loop-playlist="
            + ("inf" if self.config.get("classical_music_repeat", True) else "no"),
            "--ytdl-format=bestaudio/best",
            f"--volume={volume}",
            f"--input-ipc-server={self.ipc_socket}",
        ]

        extra = str(self.config.get("mpv_extra_args", "")).strip()
        if extra:
            mpv_args.extend(shlex.split(extra, posix=platform.system() != "Windows"))
        if _start_paused:
            mpv_args.append("--pause")

        # Finder does not inherit the shell PATH. Include standard Homebrew bins
        # for yt-dlp and its JavaScript runtime without changing the parent env.
        env = os.environ.copy()
        if platform.system() == "Darwin":
            env["PATH"] = os.pathsep.join(
                [env.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"]
            )
            self._playback_proxy = _mac_music_proxy()
            self._allow_proxy_retry = _allow_proxy_retry
            # Explicitly pass even an empty proxy, so yt-dlp cannot reuse a
            # configured local proxy whose application has been closed.
            for scheme in ("http", "https", "all"):
                env.pop(f"{scheme}_proxy", None)
                env.pop(f"{scheme.upper()}_PROXY", None)
            mpv_args.append(f"--http-proxy={self._playback_proxy}")
            mpv_args.append(f"--ytdl-raw-options-append=proxy={self._playback_proxy}")
        source_kind = youtube_source_kind(playlist_path)
        if source_kind:
            # GUI launchers often omit the app's Python scripts directory from PATH.
            import sysconfig

            env["PATH"] = os.pathsep.join(
                [sysconfig.get_path("scripts"), env.get("PATH", "")]
            )
            mpv_args.append("--ytdl-raw-options-append=ignore-config=")
        extractor = shutil.which("yt-dlp", path=env.get("PATH"))
        if extractor:
            mpv_args.append(f"--script-opts-append=ytdl_hook-ytdl_path={extractor}")
        env.pop("FOCUS_RESUME_TRACK", None)
        for key in (
            "FOCUS_MIX_ID",
            "FOCUS_MIX_ACCOUNT",
            "FOCUS_MIX_FOLLOW",
            "FOCUS_MIX_CONNECTION",
        ):
            env.pop(key, None)
        media_url = playlist_path
        remembered = _resume_track or (
            self.bookmark.get("track", "")
            if restore_track and self.bookmark.get("source") == playlist_path
            else ""
        )
        if remembered and source_kind != "radio":
            env["FOCUS_RESUME_TRACK"] = remembered
        browser = self.config.get("youtube_browser", "")
        personal_mix = source_kind == "radio" and browser == "chrome"
        connection = self.config.get("chrome_mix_connection")
        self._using_chrome = bool(
            source_kind
            and browser == "chrome"
            and not _public_mix
            and not (personal_mix and connection is False)
            and (source_kind == "radio" or not self._guest_fallback)
        )
        if self._using_chrome and not (personal_mix and connection):
            session = _chrome_mix_session() if source_kind == "radio" else "chrome"
            mpv_args.append(f"--ytdl-raw-options-append=cookies-from-browser={session}")
        elif source_kind:
            mpv_args.extend(
                [
                    "--ytdl-raw-options-remove=cookies-from-browser",
                    "--ytdl-raw-options-remove=cookies",
                ]
            )
        if source_kind in ("radio", "playlist"):
            # mpv otherwise treats a watch?v=...&list=... URL as one video.
            mpv_args.append("--shuffle=no")
            mpv_args.append("--ytdl-raw-options-append=yes-playlist=")
        if source_kind == "radio":
            env["FOCUS_MIX_ID"], media_url = _mix_watch_url(playlist_path, remembered)
            if self._using_chrome:
                env["FOCUS_MIX_ACCOUNT"] = "1"
            if self._using_chrome and connection is True:
                env["FOCUS_MIX_CONNECTION"] = str(
                    self.config.config_path.parent / "data" / "chrome-mix"
                )
            plugins = Path(__file__).with_name("radio_plugins")
            mpv_args.extend(
                [
                    f"--ytdl-raw-options-append=plugin-dirs={plugins}",
                    "--ytdl-raw-options-append=use-extractors=^(focus:mix|youtube)$",
                    "--ytdl-raw-options-append=playlist-end=50",
                    # The timer already selected the bookmarked song for this Mix.
                    "--no-resume-playback",
                    "--no-save-position-on-quit",
                ]
            )
            if self.config.get("radio_refresh", True):
                mpv_args.append("--loop-playlist=no")
                if self.config.get("classical_music_repeat", True):
                    env["FOCUS_MIX_FOLLOW"] = "1"
        mpv_args.extend(
            [
                "--ytdl-raw-options-append=socket-timeout=20",
                "--ytdl-raw-options-append=retries=1",
                "--ytdl-raw-options-append=extractor-retries=1",
                "--network-timeout=20",
                "--terminal=yes",
                f"--script={Path(__file__).with_name('focus_track.lua')}",
                "--msg-level=all=error,cplayer=info,focus_track=info",
                "--term-status-msg=",
                "--term-playing-msg=FOCUS_PLAYING:${media-title}",
                "--idle=no",
                "--keep-open=no",
                "--",
                media_url,
            ]
        )

        try:
            self.mpv_process = subprocess.Popen(
                mpv_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=_SUBPROCESS_FLAGS,
            )
            self.pid_file.write_text(str(self.mpv_process.pid))
            self.current_playlist = playlist_path
            self._opening_track = media_url
            self._pause_requested = _start_paused
            self.is_playing = True
            self.playback_state = "loading"
            self.current_track_name = ""
            self._live = {}
            self.last_error = ""
            logger.info(
                "Music started (pid=%d, playlist=%s)",
                self.mpv_process.pid,
                playlist_path,
            )
            # Start track info update thread
            threading.Thread(
                target=self._monitor_playback, args=(self.mpv_process,), daemon=True
            ).start()
            return True
        except OSError:
            self._stop_process_only()
            self.playback_state = "error"
            self.last_error = "Could not start the music player."
            logger.exception("Failed to launch MPV")
            return False

    @_music_operation
    def stop_music(self) -> bool:
        self._stop_process_only()
        self.current_playlist = None
        self._live = {}
        self.last_error = ""
        self.is_playing = False
        self.current_track_name = ""
        # Only Unix sockets are filesystem entries.
        if (
            platform.system() != "Windows"
            and self.ipc_socket
            and self.ipc_socket.exists()
        ):
            try:
                self.ipc_socket.unlink()
            except Exception:
                pass
        return True

    def _stop_process_only(self) -> None:
        self._paused_for_break = False
        self.is_playing = False
        self.playback_state = "stopped"
        if self.mpv_process and self.mpv_process.poll() is None:
            try:
                self.mpv_process.terminate()
                try:
                    self.mpv_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.mpv_process.kill()
                    self.mpv_process.wait(timeout=3)
            except OSError:
                logger.exception("Error terminating MPV process")

        # Never signal an unverified PID left by another instance or a crash.
        try:
            if self.mpv_process and self.pid_file.exists():
                if self.pid_file.read_text().strip() == str(self.mpv_process.pid):
                    self.pid_file.unlink(missing_ok=True)
        except OSError:
            logger.debug("Could not remove music PID file", exc_info=True)

        self.mpv_process = None

    @_music_operation
    def pause_music(self) -> bool:
        self._paused_for_break = False
        if not self.is_playing:
            return False
        self._pause_requested = True
        result = self._send_mpv_command(["set_property", "pause", True])
        if result and result.get("error") == "success":
            self.playback_state = "paused"
            return True
        return False

    @_music_operation
    def pause_for_break(self):
        if (
            self.config.get("pause_music_on_break", True)
            and self.is_playing
            and not self._pause_requested
            and self.playback_state != "paused"
        ):
            self.pause_music()
            self._paused_for_break = True

    @_music_operation
    def finish_break(self):
        if self._paused_for_break and self.is_playing:
            self.resume_music()

    @_music_operation
    def resume_music(self) -> bool:
        self._paused_for_break = False
        self._pause_requested = False
        if self.mpv_process and self.mpv_process.poll() is None:
            result = self._send_mpv_command(["set_property", "pause", False])
            if result and result.get("error") == "success":
                self.playback_state = "playing"
                return True
            return False
        return self.start_music()

    @_music_operation
    def set_volume(self, volume: int) -> bool:
        volume = max(0, min(100, volume))
        if self.config.get("classical_music_volume") != volume:
            self.config.set("classical_music_volume", volume)
            self.config.save_config()
        if self.is_playing:
            result = self._send_mpv_command(["set_property", "volume", volume])
            return bool(result and result.get("error") == "success")
        return True

    def get_status(self) -> Dict[str, Any]:
        live = self._live.copy()
        position = live.get("time-pos") or 0
        if self.playback_state == "playing" and not live.get("paused-for-cache"):
            position += min(2, time.monotonic() - self._live_time)
        duration = live.get("duration") or 0
        source_kind = youtube_source_kind(self.current_playlist or "")
        queue = live.get("playlist") or []
        index = live.get("playlist-pos")
        up_next = (
            queue[index + 1].get("title", "")
            if isinstance(index, int) and 0 <= index < len(queue) - 1
            else ""
        )
        return {
            "position": min(position, duration) if duration else position,
            "duration": duration,
            "buffering": bool(live.get("paused-for-cache")),
            "devices": live.get("audio-device-list") or [],
            "device": live.get("audio-device", "auto"),
            "route": "Proxy" if self._playback_proxy else "Direct",
            "source_kind": source_kind,
            "public_mix": source_kind == "radio" and not self._using_chrome,
            "youtube_browser": self.config.get("youtube_browser", ""),
            "guest_playback": self._guest_fallback
            and source_kind in ("video", "playlist")
            and not self._using_chrome,
            "attempt": self.play_attempt,
            "playlist_count": live.get("playlist-count") or 0,
            "up_next": up_next,
            "playlist_index": (live.get("playlist-pos") or 0) + 1,
            "muted": bool(live.get("mute")),
            "is_playing": self.is_playing,
            "state": self.playback_state,
            "error": self.last_error,
            "current_playlist": self.current_playlist,
            "mpv_available": self._mpv_available,
            "volume": live.get("volume", self.config.get("classical_music_volume", 30)),
            "current_track": self.current_track_name,
            "bookmark": self.bookmark,
        }

    @contextmanager
    def _ipc_stream(self, path, *, observe=False):
        if platform.system() == "Windows":
            # mpv exposes the same newline-delimited JSON over a named pipe.
            from io import BufferedRWPair

            with open(r"\\.\pipe" + "\\" + path.name, "r+b", buffering=0) as pipe:
                with BufferedRWPair(pipe, pipe) as stream:
                    yield stream
        else:
            import socket

            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(None if observe else 1.0)
                sock.connect(str(path))
                with sock.makefile("rwb") as stream:
                    yield stream

    def _send_mpv_command(self, command: List[Any]) -> Optional[Dict]:
        if not self.ipc_socket or not self.is_playing:
            return None
        try:
            with self._ipc_stream(self.ipc_socket) as stream:
                stream.write((json.dumps({"command": command}) + "\n").encode())
                stream.flush()
                for response in _read_pipe_json(stream):
                    if "error" in response:
                        return response
        except (OSError, ValueError) as exc:
            logger.debug("MPV command failed: %s", exc)
        return None

    @_music_operation
    def next_track(self) -> bool:
        """Skip to next track"""
        previous_state = self.playback_state
        self.playback_state = "loading"
        result = self._send_mpv_command(["playlist-next"])
        if result and result.get("error") == "success":
            logger.info("Skipped to next track")
            return True
        self.playback_state = previous_state
        return False

    @_music_operation
    def previous_track(self) -> bool:
        """Go to previous track"""
        previous_state = self.playback_state
        self.playback_state = "loading"
        result = self._send_mpv_command(["playlist-prev"])
        if result and result.get("error") == "success":
            logger.info("Went to previous track")
            return True
        self.playback_state = previous_state
        return False

    def get_current_track_info(self) -> Optional[str]:
        return Path(self.current_track_name).stem if self.current_track_name else None

    def _monitor_playback(self, process):
        """Read player events without polling or blocking the GUI thread."""
        try:
            for line in process.stdout:
                self._handle_player_line(process, line)
            self._player_finished(process, process.wait())
        finally:
            process.stdout.close()

    @_music_operation
    def _handle_player_line(self, process, line):
        if self.mpv_process is not process or not self.is_playing:
            return
        if line.startswith("[focus_track] FOCUS_TRACK "):
            self._remember_track(line.partition("FOCUS_TRACK ")[2])
        elif line.startswith("FOCUS_PLAYING:"):
            self.current_track_name = line.partition(":")[2].strip()
            self.playback_state = "paused" if self._pause_requested else "playing"
        elif line.startswith("AO:"):
            if self._observed_process is not process:
                self._observed_process = process
                threading.Thread(
                    target=self._observe_player,
                    args=(process, self.ipc_socket),
                    daemon=True,
                ).start()
            if self._pause_requested:
                self._send_mpv_command(["set_property", "pause", True])
            self.last_error = ""
        elif line.strip():
            reason = _music_failure_reason(line)
            if reason and not self.last_error:
                self.last_error = reason

    def _remember_track(self, payload):
        try:
            item = json.loads(payload)
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("track"), str)
                or not item["track"]
            ):
                return
            bookmark = {
                "source": self.current_playlist,
                "track": item["track"],
                "title": item.get("title") or "",
            }
            resume, self._seek_on_load = self._seek_on_load, None
            if resume and resume[0] == bookmark["track"]:
                self.seek(resume[1])
            if bookmark != self.bookmark:
                self.config.save_music_bookmark(bookmark)
                self.bookmark = bookmark
        except (ValueError, OSError):
            logger.warning("Could not remember the current song", exc_info=True)

    @_music_operation
    def _player_finished(self, process, returncode):
        if self.mpv_process is process and self.is_playing:
            if (
                returncode
                and self._using_chrome
                and youtube_source_kind(self.current_playlist or "") == "radio"
                and (
                    self.last_error == _CHROME_COOKIE_ERROR
                    or self.last_error in _CHROME_CONNECTION_ERRORS.values()
                )
            ):
                # A network error or an unavailable Mix says nothing about pairing.
                if self.last_error in (
                    _CHROME_COOKIE_ERROR,
                    _CHROME_CONNECTION_ERRORS["extension"],
                    _CHROME_CONNECTION_ERRORS["pairing"],
                ):
                    self.config.set("chrome_mix_connection", False)
                    self.config.save_config()
                paused, on_break = self._pause_requested, self._paused_for_break
                resume = self._seek_on_load
                started = self.start_music(
                    self.current_playlist,
                    _allow_proxy_retry=False,
                    _resume_track=self._opening_track,
                    _public_mix=True,
                    _start_paused=paused,
                )
                if started:
                    self._seek_on_load = resume
                    self._paused_for_break = on_break
                return
            if (
                returncode
                and self._using_chrome
                and youtube_source_kind(self.current_playlist or "") != "radio"
                and self.last_error == _CHROME_COOKIE_ERROR
                and not self._pause_requested
            ):
                self._guest_fallback = True
                logger.info(
                    "Chrome sign-in unavailable; retrying the same music as a guest"
                )
                self.start_music(self.current_playlist, _allow_proxy_retry=False)
                return
            if (
                returncode
                and platform.system() == "Darwin"
                and self._allow_proxy_retry
                and not self._pause_requested
                and self.current_playlist
                and _mac_music_proxy() != self._playback_proxy
            ):
                logger.info("Music connection changed; retrying playback once")
                self.start_music(self.current_playlist, _allow_proxy_retry=False)
                return
            self.is_playing = False
            self.current_track_name = ""
            self.playback_state = "error" if returncode else "stopped"
            if returncode:
                if not self.last_error:
                    self.last_error = "Playback failed. Check the link or connection."
                logger.warning(
                    "Music player exited with code %s: %s",
                    returncode,
                    self.last_error,
                )

    @_music_operation
    def restart_youtube_session(self, source):
        self._guest_fallback = False
        if (
            not self.is_playing
            or self.current_playlist != source
            or youtube_source_kind(source) != "radio"
        ):
            return self.change_playlist(source)
        track = (
            self.bookmark.get("track", "")
            if self.bookmark.get("source") == source
            else ""
        )
        position = self.get_status()["position"]
        paused = self._pause_requested or self.playback_state == "paused"
        on_break = self._paused_for_break
        if not self.start_music(source, _resume_track=track, _start_paused=paused):
            return False
        if track and position > 0:
            self._seek_on_load = (track, position)
        self._paused_for_break = on_break
        return True

    def connect_chrome_mix(self, source, folder, *, install=False):
        """Check the personal queue before enabling it. Leave active audio in place."""
        from .radio_plugins.focus.yt_dlp_plugins.chrome_connection import (
            ChromeMixError,
            checked_tracks,
            read_chrome_queue,
        )

        if youtube_source_kind(source or "") != "radio":
            raise ValueError("Select a YouTube Mix first.")
        with self._operation_lock:
            bookmark = self.bookmark
            previous_browser = self.config.get("youtube_browser", "")
            remembered = (
                bookmark.get("track", "") if bookmark.get("source") == source else ""
            )
        _, watch = _mix_watch_url(source, remembered)
        try:
            if install:
                from .chrome_setup import connect_on_install

                answer = connect_on_install(watch, folder)
            else:
                answer = read_chrome_queue(watch, folder)
            checked_tracks(answer, watch)
        except ChromeMixError as exc:
            raise ValueError(
                _CHROME_CONNECTION_ERRORS.get(str(exc), _CHROME_CONNECTION_ERROR)
            ) from None
        with self._operation_lock:
            if self._closed or previous_browser != self.config.get(
                "youtube_browser", ""
            ):
                return None
            previous_connection = self.config.get("chrome_mix_connection")
            self.config.set("youtube_browser", "chrome")
            self.config.set("chrome_mix_connection", True)
            if not self.config.save_config():
                self.config.set("youtube_browser", previous_browser)
                self.config.set("chrome_mix_connection", previous_connection)
                raise ValueError("Could not save the Chrome connection.")
            return "Connected. The next time you load this Mix, it will use your Chrome account."

    @_music_operation
    def retry_failed_attempt(self, attempt):
        if self.play_attempt == attempt and self.playback_state == "error":
            return self.start_music()
        return False

    def _observe_player(self, process, path):
        """Receive property changes from mpv; no periodic network queries."""
        properties = [
            "time-pos",
            "duration",
            "pause",
            "media-title",
            "volume",
            "mute",
            "paused-for-cache",
            "audio-device",
            "audio-device-list",
            "playlist-pos",
            "playlist-count",
        ]
        if youtube_source_kind(self.current_playlist or "") == "radio":
            properties.append("playlist")
        try:
            with self._ipc_stream(path, observe=True) as stream:
                for index, name in enumerate(properties):
                    cmd = {"command": ["observe_property", index, name]}
                    stream.write((json.dumps(cmd) + "\n").encode())
                stream.flush()
                for event in _read_pipe_json(stream):
                    with self._operation_lock:
                        if self.mpv_process is not process or not self.is_playing:
                            return
                        self._apply_player_event(event)
        except (OSError, ValueError):
            logger.debug("Music property observer closed")

    def _apply_player_event(self, event):
        kind = event.get("event")
        if kind == "property-change":
            self._apply_player_property(event.get("name"), event.get("data"))
        elif kind == "start-file":
            entry_id = event.get("playlist_entry_id")
            if self._using_chrome and entry_id is not None:
                for entry in self._live.get("playlist") or ():
                    if entry.get("id") == entry_id and entry.get("filename"):
                        self._opening_track = entry["filename"]
                        break
            self.playback_state = "loading"
            self.current_track_name = ""
            self._live.pop("time-pos", None)
            self._live.pop("duration", None)
        elif kind == "playback-restart":
            self.playback_state = "paused" if self._live.get("pause") else "playing"
            self.last_error = ""

    def _apply_player_property(self, name, value):
        self._live[name] = value
        if name == "time-pos":
            self._live_time = time.monotonic()
        elif name == "media-title" and isinstance(value, str):
            self.current_track_name = value
        elif name == "pause" and value is not None:
            self.playback_state = "paused" if value else "playing"

    @_music_operation
    def seek(self, position):
        result = self._send_mpv_command(["seek", float(position), "absolute"])
        return bool(result and result.get("error") == "success")

    @_music_operation
    def set_audio_device(self, device):
        result = self._send_mpv_command(["set_property", "audio-device", device])
        return bool(result and result.get("error") == "success")

    @_music_operation
    def change_playlist(self, playlist_path: str) -> bool:
        """Change to a different playlist"""
        if not playlist_path:
            return False

        return self.start_music(playlist_path=playlist_path)

    @_music_operation
    def cleanup(self):
        self._closed = True
        self.stop_music()


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION MANAGER
# ══════════════════════════════════════════════════════════════════════════════

try:
    import winsound as _winsound

    _WINSOUND_AVAILABLE = True
except ImportError:
    _winsound = None
    _WINSOUND_AVAILABLE = False

try:
    from plyer import notification as _plyer_notification

    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False
    _plyer_notification = None
    logger.debug("plyer not installed — desktop notifications may be limited")

if platform.system() == "Darwin":
    try:
        import pync as _pync

        PYNC_AVAILABLE = True
    except ImportError:
        _pync = None
        PYNC_AVAILABLE = False
else:
    _pync = None
    PYNC_AVAILABLE = False

MOTIVATIONAL_MESSAGES = {
    "work_start": [
        "Time to focus and make progress!",
        "You've got this! Let's get to work.",
        "Deep focus mode activated!",
        "Every minute counts. Let's do this!",
        "Focus on the task at hand.",
    ],
    "work_complete": [
        "Excellent work! You're building great habits.",
        "Another successful focus session! Keep it up!",
        "Well done! Your productivity is improving.",
        "Great job staying focused!",
        "You're on fire! Keep the momentum going.",
    ],
    "break_start": [
        "Time to recharge and refresh!",
        "Take a well-deserved break.",
        "Rest your mind for a moment.",
        "You've earned this break!",
        "Relax and come back stronger.",
    ],
    "daily_goal": [
        "You're making great progress today!",
        "Keep up the excellent work!",
        "Your focus is paying off!",
        "Productivity level: Outstanding!",
        "You're in the zone today!",
    ],
}


class NotificationManager:
    """Cross-platform notification manager."""

    def __init__(self, config_manager):
        self.config = config_manager
        self.notifications_enabled = self.config.get("desktop_notifications", True)
        self.notification_method = self._get_best_notification_method()

    def _get_best_notification_method(self) -> str:
        system = platform.system()

        if not self.notifications_enabled:
            return "disabled"

        if system == "Windows":
            return "plyer" if PLYER_AVAILABLE else "console"
        elif system == "Darwin":
            if PYNC_AVAILABLE:
                return "pync"
            return "osascript"
        elif system == "Linux":
            return "plyer" if PLYER_AVAILABLE else "notify-send"
        else:
            return "console"

    def show_notification(
        self,
        title: str,
        message: str,
        notification_type: str = "info",
        duration: Optional[int] = None,
    ) -> bool:
        if not self.notifications_enabled:
            return False

        if duration is None:
            duration = self.config.get("notification_persistence", 5)

        try:
            if self.notification_method == "disabled":
                return False
            elif self.notification_method == "pync":
                return self._show_pync(title, message, duration)
            elif self.notification_method == "plyer":
                return self._show_plyer(title, message, duration)
            elif self.notification_method == "osascript":
                return self._show_osascript(title, message)
            elif self.notification_method == "notify-send":
                return self._show_notify_send(title, message, duration)
            else:
                return self._show_console(title, message, notification_type)
        except Exception as e:
            logger.warning("Notification error (%s): %s", self.notification_method, e)
            return self._show_console(title, message, notification_type)

    def _show_pync(self, title: str, message: str, duration: int) -> bool:
        try:
            _pync.notify(message, title=title, timeout=duration)
            return True
        except Exception as e:
            logger.warning("pync error: %s", e)
            return False

    def _show_plyer(self, title: str, message: str, duration: int) -> bool:
        try:
            if _plyer_notification is None:
                return False
            _plyer_notification.notify(title=title, message=message, timeout=duration)
            return True
        except Exception as e:
            logger.warning("plyer error: %s", e)
            return False

    def _show_osascript(self, title: str, message: str) -> bool:
        try:
            title = title.replace("\\", "\\\\").replace('"', '\\"')
            message = message.replace("\\", "\\\\").replace('"', '\\"')
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
            return True
        except Exception as e:
            logger.warning("osascript error: %s", e)
            return False

    def _show_notify_send(self, title: str, message: str, duration: int) -> bool:
        try:
            subprocess.run(
                ["notify-send", "-t", str(duration * 1000), title, message],
                capture_output=True,
                timeout=5,
            )
            return True
        except Exception as e:
            logger.warning("notify-send error: %s", e)
            return False

    def _show_console(self, title: str, message: str, notification_type: str) -> bool:
        colors = {
            "info": "\033[94m",
            "success": "\033[92m",
            "warning": "\033[93m",
            "error": "\033[91m",
        }
        reset_color = "\033[0m"
        color = colors.get(notification_type, colors["info"])
        print(f"\n{color} {title}{reset_color}")
        print(f"{color} {message}{reset_color}\n")
        return True

    def show_session_start(self, session_type: str, duration: int) -> bool:
        icons = {"work": "🎯", "short_break": "☕", "long_break": "🛋️", "custom": "⏱️"}
        icon = icons.get(session_type, "⏱️")
        title = f"{icon} Focus Session Started"
        message = f"{session_type.replace('_', ' ').title()} session ({duration} min)"
        return self.show_notification(title, message, "info")

    def show_session_complete(self, session_type: str, duration: int) -> bool:
        title = "🎉 Session Complete!"
        message = f"Great work! You completed a {duration}-minute {session_type.replace('_', ' ')} session."
        return self.show_notification(title, message, "success")

    def show_early_warning(self, session_type: str, minutes_remaining: int) -> bool:
        title = "⏰ Time Warning"
        message = f"{minutes_remaining} minute(s) remaining in your {session_type.replace('_', ' ')} session"
        return self.show_notification(title, message, "warning")

    def show_motivational_message(self, message: str) -> bool:
        if not self.config.get("motivational_messages", True):
            return False
        return self.show_notification("💪 Stay Focused!", message, "info")

    def play_completion_sound(self) -> None:
        if not _WINSOUND_AVAILABLE:
            return
        try:
            for freq, duration in [(600, 150), (750, 150), (900, 300)]:
                _winsound.Beep(freq, duration)
        except Exception:
            logger.debug("winsound.Beep failed (may not be supported)")

    def play_start_sound(self) -> None:
        if not _WINSOUND_AVAILABLE:
            return
        try:
            for freq, duration in [(900, 120), (700, 120)]:
                _winsound.Beep(freq, duration)
        except Exception:
            logger.debug("winsound.Beep failed (may not be supported)")

    def enable_notifications(self) -> None:
        self.notifications_enabled = True
        self.config.set("desktop_notifications", True)
        logger.info("Notifications enabled")

    def disable_notifications(self) -> None:
        self.notifications_enabled = False
        self.config.set("desktop_notifications", False)
        logger.info("Notifications disabled")


# ══════════════════════════════════════════════════════════════════════════════
# TRAY MANAGER
# ══════════════════════════════════════════════════════════════════════════════

import importlib.util as _import_util

_PYSTRAY_AVAILABLE = all(
    _import_util.find_spec(name) is not None for name in ("pystray", "PIL")
)
pystray = Image = ImageDraw = None


def _load_tray_dependencies():
    global pystray, Image, ImageDraw, _PYSTRAY_AVAILABLE
    if pystray is not None:
        return True
    try:
        import pystray as tray_module
        from PIL import Image as image_module
        from PIL import ImageDraw as draw_module
    except ImportError:
        _PYSTRAY_AVAILABLE = False
        return False
    pystray, Image, ImageDraw = tray_module, image_module, draw_module
    return True


_ICON_SIZE = 64


def _make_icon(color: str) -> Any:
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, _ICON_SIZE - 4, _ICON_SIZE - 4], fill=color)
    return img


class TrayManager:
    """Manages the system tray icon and right-click context menu."""

    _COLORS = {
        "work": "#e74c3c",
        "break": "#3498db",
        "paused": "#f39c12",
        "idle": "#808080",
    }

    def __init__(
        self,
        on_show: Optional[Callable] = None,
        on_start_work: Optional[Callable] = None,
        on_start_break: Optional[Callable] = None,
        on_pause_resume: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
        on_quit: Optional[Callable] = None,
    ):
        self._on_show = on_show
        self._on_start_work = on_start_work
        self._on_start_break = on_start_break
        self._on_pause_resume = on_pause_resume
        self._on_stop = on_stop
        self._on_quit = on_quit
        self._icon: Optional[Any] = None
        self._thread = None
        self.available = _PYSTRAY_AVAILABLE

        # Detect Tcl 9.0 on macOS - known to crash with pystray/NSApplication
        self._is_macos_tcl9 = False
        if platform.system() == "Darwin":
            try:
                import tkinter

                if tkinter.TclVersion >= 9:
                    self._is_macos_tcl9 = True
                    logger.warning(
                        f"Tcl/Tk {tkinter.TclVersion} detected on macOS. "
                        "Disabling System Tray to prevent crash."
                    )
            except Exception:
                pass

    def _build_menu(self) -> Any:
        def _call(fn):
            def _handler(icon, item):
                if fn:
                    fn()

            return _handler

        return pystray.Menu(
            pystray.MenuItem("Show Window", _call(self._on_show), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start Work Session", _call(self._on_start_work)),
            pystray.MenuItem("Start Break Session", _call(self._on_start_break)),
            pystray.MenuItem("Pause / Resume", _call(self._on_pause_resume)),
            pystray.MenuItem("Stop Session", _call(self._on_stop)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _call(self._quit_from_tray)),
        )

    def start(self) -> None:
        if not _PYSTRAY_AVAILABLE or self._is_macos_tcl9:
            self.available = False
            return
        if not _load_tray_dependencies():
            self.available = False
            return
        try:
            import threading

            self._icon = pystray.Icon(
                "FocusTimer",
                _make_icon(self._COLORS["idle"]),
                "Focus Timer — Idle",
                self._build_menu(),
            )
            self._thread = threading.Thread(target=self._icon.run, daemon=True)
            self._thread.start()
            logger.info("System tray icon started")
        except Exception:
            logger.exception("Failed to start system tray icon")

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def _quit_from_tray(self) -> None:
        self.stop()
        if self._on_quit:
            self._on_quit()

    def set_state(self, state: str, tooltip: str = "") -> None:
        if not self._icon:
            return
        color = self._COLORS.get(state, self._COLORS["idle"])
        label = tooltip or f"Focus Timer — {state.title()}"
        try:
            self._icon.icon = _make_icon(color)
            self._icon.title = label
        except Exception:
            logger.exception("Failed to update tray icon state")


# ══════════════════════════════════════════════════════════════════════════════
# HOTKEY MANAGER
# ══════════════════════════════════════════════════════════════════════════════

if platform.system() == "Darwin" and not os.environ.get("FOCUS_ENABLE_MAC_HOTKEYS"):
    keyboard = None  # type: ignore[assignment]
    _KEYBOARD_AVAILABLE = False
    _KEYBOARD_DISABLED_REASON = "macos"
    logger.info(
        "Global hotkeys disabled on macOS. Set FOCUS_ENABLE_MAC_HOTKEYS=1 to opt in."
    )
else:
    try:
        import keyboard

        _KEYBOARD_AVAILABLE = True
        _KEYBOARD_DISABLED_REASON = ""
    except ImportError:
        keyboard = None  # type: ignore[assignment]
        _KEYBOARD_AVAILABLE = False
        _KEYBOARD_DISABLED_REASON = "missing"
        logger.warning("keyboard library not installed — global hotkeys disabled")


class HotkeyManager:
    """Registers and manages system-wide hotkeys."""

    HOTKEY_SHOW = "ctrl+alt+f"
    HOTKEY_PAUSE = "ctrl+alt+p"

    def __init__(
        self,
        on_show: Optional[Callable] = None,
        on_pause_resume: Optional[Callable] = None,
    ):
        self._on_show = on_show
        self._on_pause_resume = on_pause_resume
        self._registered = False
        self.available = _KEYBOARD_AVAILABLE

    def start(self) -> None:
        if not _KEYBOARD_AVAILABLE:
            if _KEYBOARD_DISABLED_REASON == "macos":
                logger.info("Global hotkeys disabled on macOS")
            return

        # Register each hotkey individually to prevent one failure from stopping all
        try:
            keyboard.add_hotkey(self.HOTKEY_SHOW, self._handle_show)
            logger.info("Global hotkey registered: %s (show)", self.HOTKEY_SHOW)
        except Exception as e:
            logger.warning(
                "Failed to register 'show' hotkey (%s): %s", self.HOTKEY_SHOW, e
            )

        try:
            keyboard.add_hotkey(self.HOTKEY_PAUSE, self._handle_pause_resume)
            logger.info(
                "Global hotkey registered: %s (pause/resume)", self.HOTKEY_PAUSE
            )
        except Exception as e:
            logger.warning(
                "Failed to register 'pause' hotkey (%s): %s", self.HOTKEY_PAUSE, e
            )

        self._registered = True

    def stop(self) -> None:
        if not _KEYBOARD_AVAILABLE or not self._registered:
            return
        try:
            keyboard.remove_hotkey(self.HOTKEY_SHOW)
            keyboard.remove_hotkey(self.HOTKEY_PAUSE)
            self._registered = False
            logger.info("Global hotkeys unregistered")
        except Exception:
            logger.exception("Failed to unregister global hotkeys")

    def _handle_show(self) -> None:
        if self._on_show:
            try:
                self._on_show()
            except Exception:
                logger.exception("Error in hotkey show handler")

    def _handle_pause_resume(self) -> None:
        if self._on_pause_resume:
            try:
                self._on_pause_resume()
            except Exception:
                logger.exception("Error in hotkey pause/resume handler")


# ══════════════════════════════════════════════════════════════════════════════
# BRAIN DUMP HOTKEY  (Zeigarnik Offload — Ctrl+Shift+Space)
# ══════════════════════════════════════════════════════════════════════════════

_BRAIN_DUMP_FILE = Path.home() / "brain_dump.md"
_BRAIN_DUMP_HOTKEY = "ctrl+shift+space"

logger_bd = logging.getLogger(__name__)


class BrainDumpHotkey:
    """Registers Ctrl+Shift+Space to instantly capture thoughts to ~/brain_dump.md.

    Pressing the hotkey opens a minimal Tkinter input box.  Whatever the user
    types is appended to ~/brain_dump.md with an ISO timestamp.  The box
    disappears on Enter or Escape so the user can return to work in under two
    seconds.
    """

    def __init__(self, dump_file: Optional[Path] = None) -> None:
        self.dump_file = dump_file or _BRAIN_DUMP_FILE
        self._registered = False

    def start(self) -> None:
        """Register the global hotkey.  Safe to call if keyboard lib is missing."""
        if not _KEYBOARD_AVAILABLE:
            if _KEYBOARD_DISABLED_REASON == "macos":
                logger_bd.info("BrainDumpHotkey disabled on macOS")
            else:
                logger_bd.warning(
                    "keyboard library not installed — BrainDumpHotkey disabled"
                )
            return
        try:
            keyboard.add_hotkey(_BRAIN_DUMP_HOTKEY, self._open_capture_box)
            self._registered = True
            logger_bd.info("BrainDumpHotkey registered: %s", _BRAIN_DUMP_HOTKEY)
        except Exception:
            logger_bd.exception("Failed to register BrainDumpHotkey")

    def stop(self) -> None:
        if not _KEYBOARD_AVAILABLE or not self._registered:
            return
        try:
            keyboard.remove_hotkey(_BRAIN_DUMP_HOTKEY)
            self._registered = False
        except Exception:
            logger_bd.exception("Failed to unregister BrainDumpHotkey")

    def _open_capture_box(self) -> None:
        """Open a tiny input window in a separate thread to avoid blocking."""
        threading.Thread(target=self._capture_ui, daemon=True).start()

    def _capture_ui(self) -> None:
        """Minimal Tkinter capture window — runs in its own thread."""
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title("Brain Dump")
            root.geometry("500x60+200+200")
            root.attributes("-topmost", True)
            root.configure(bg="#1e1e2e")

            var = tk.StringVar()
            entry = tk.Entry(
                root,
                textvariable=var,
                font=("Courier", 14),
                bg="#313244",
                fg="#cdd6f4",
                insertbackground="#cdd6f4",
                relief="flat",
                bd=8,
            )
            entry.pack(fill="both", expand=True)
            entry.focus_force()

            def _commit(event=None):
                text = var.get().strip()
                if text:
                    self._append_to_file(text)
                root.destroy()

            def _cancel(event=None):
                root.destroy()

            entry.bind("<Return>", _commit)
            entry.bind("<Escape>", _cancel)
            root.mainloop()
        except Exception:
            logger_bd.exception("BrainDumpHotkey capture UI error")

    def _append_to_file(self, text: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"- [{ts}] {text}\n"
        try:
            with open(self.dump_file, "a", encoding="utf-8") as fh:
                fh.write(line)
            logger_bd.debug("Brain dump appended: %s", self.dump_file)
        except OSError:
            logger_bd.exception("Failed to write brain dump")


# ══════════════════════════════════════════════════════════════════════════════
# BINAURAL BEAT GENERATOR  (40 Hz via numpy + sounddevice)
# ══════════════════════════════════════════════════════════════════════════════


class BinauralBeatGenerator:
    """Generates 40 Hz binaural beats using numpy + sounddevice.

    Left channel: carrier_hz
    Right channel: carrier_hz + beat_hz

    The 40 Hz beat frequency is associated with gamma-band neural activity
    and is used as an acoustic neuromodulation tool.
    """

    def __init__(
        self,
        carrier_hz: float = 200.0,
        beat_hz: float = 40.0,
        volume: float = 0.15,
        sample_rate: int = 44100,
    ) -> None:
        self.carrier_hz = carrier_hz
        self.beat_hz = beat_hz
        self.volume = volume
        self.sample_rate = sample_rate

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.is_playing = False

    def start(self) -> bool:
        """Start binaural beat generation.  Returns False if dependencies missing."""
        try:
            import numpy  # noqa: F401
            import sounddevice  # noqa: F401
        except ImportError:
            logger_bd.warning("numpy or sounddevice missing — binaural beats disabled")
            return False

        if self.is_playing:
            return True

        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.is_playing = True
        logger_bd.info(
            "Binaural beat started: %.0f Hz carrier + %.0f Hz beat",
            self.carrier_hz,
            self.beat_hz,
        )
        return True

    def stop(self) -> None:
        """Stop the binaural beat generator."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self.is_playing = False
        logger_bd.info("Binaural beat stopped")

    def _loop(self) -> None:
        import numpy as np
        import sounddevice as sd

        block_duration = 0.5
        block_samples = int(self.sample_rate * block_duration)
        sample_idx = 0

        while not self._stop.is_set():
            t = (np.arange(block_samples) + sample_idx) / self.sample_rate
            left = self.volume * np.sin(2 * np.pi * self.carrier_hz * t)
            right = self.volume * np.sin(
                2 * np.pi * (self.carrier_hz + self.beat_hz) * t
            )
            stereo = np.column_stack([left, right]).astype(np.float32)
            try:
                sd.play(stereo, samplerate=self.sample_rate, blocking=True)
            except Exception:
                logger_bd.exception("sounddevice playback error — stopping binaural")
                break
            sample_idx += block_samples
