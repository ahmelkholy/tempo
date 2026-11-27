"""Compact music controls driven by the player's cached events."""

import logging
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from tkinter import ttk


def clock_text(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def source_label(source):
    if not source:
        return ""
    if not source.startswith(("https://", "http://")):
        return Path(source).name
    parsed = urlsplit(source)
    query = parse_qs(parsed.query)
    if parsed.hostname == "youtu.be" or (parsed.hostname or "").split(".")[-2:] == [
        "youtube",
        "com",
    ]:
        playlist = query.get("list", [""])[0]
        if playlist.startswith("RD"):
            return f"YouTube Mix · {playlist}"
        if playlist:
            return f"YouTube playlist · {playlist}"
        media = (query.get("v") or [parsed.path.strip("/")])[0]
        return f"YouTube · {media}" if media else "YouTube"
    return unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1]) or parsed.hostname


def open_chrome(source):
    """Open the user's normal Chrome session with its registered launcher."""
    from .radio_plugins.focus.yt_dlp_plugins.chrome_connection import (
        open_chrome as launch,
    )

    launch(source)


class MusicPanel(tk.Frame):
    def __init__(
        self,
        parent,
        controller,
        config,
        add_link,
        select_playlist,
        select_session=None,
        on_action=None,
    ):
        self.dark = config.get("dark_theme", True)
        self.bg = "#222830" if self.dark else "#f0f3f6"
        self.fg = "#f4f6f8" if self.dark else "#17212b"
        self.muted = "#a4afbc" if self.dark else "#5f6b78"
        self.accent = "#94d8c1" if self.dark else "#176f58"
        super().__init__(parent, bg=self.bg, padx=12, pady=10)
        self.controller = controller
        self._config = config
        self._connection_window = None
        self._connection_prompted = False
        self._choose_music = add_link
        self._recovery_window = None
        self._shown_failure = None
        self._updater = None
        self._update_attempt = None
        self.selected_source = ""
        self.on_action = on_action
        self._worker_lock = threading.Lock()
        self._worker = None
        self._actions = queue.Queue()
        self._closed = False
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._volume_drag = False
        self._seek_drag = False
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        header = tk.Frame(self, bg=self.bg)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(0, weight=1)
        self._label("Music", 12, bold=True).grid(
            in_=header, row=0, column=0, sticky="w"
        )
        self.status_label = self._label("Ready", 10, color=self.accent)
        self.status_label.grid(in_=header, row=0, column=1, padx=8)
        options = ttk.Menubutton(header, text="Options", width=7)
        options.grid(row=0, column=2)
        menu = tk.Menu(options, tearoff=False)
        options.configure(menu=menu)
        self.title_label = self._label("Choose music", 13, bold=True)
        self.title_label.configure(wraplength=320, justify="left")
        self.title_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        self.source_label = self._label("", 9, color=self.muted)
        self.source_label.grid(row=2, column=0, columnspan=2, sticky="w")
        self.connect_button = ttk.Button(
            self, text="Connect my personal Mix…", command=self._connect_chrome
        )

        timeline = tk.Frame(self, bg=self.bg)
        timeline.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        timeline.columnconfigure(1, weight=1)
        self.elapsed = tk.Label(
            timeline, text="0:00", bg=self.bg, fg=self.muted, font=("Arial", 9)
        )
        self.elapsed.grid(row=0, column=0)
        self.position = tk.DoubleVar()
        self.seek_slider = ttk.Scale(timeline, from_=0, to=1, variable=self.position)
        self.seek_slider.grid(row=0, column=1, sticky="ew", padx=6)
        self.seek_slider.bind(
            "<ButtonPress-1>", lambda e: setattr(self, "_seek_drag", True)
        )
        self.seek_slider.bind("<ButtonRelease-1>", self._seek)
        self.duration_label = tk.Label(
            timeline, text="—", bg=self.bg, fg=self.muted, font=("Arial", 9)
        )
        self.duration_label.grid(row=0, column=2)

        transport = tk.Frame(self, bg=self.bg)
        transport.grid(row=4, column=0, columnspan=2, pady=6)
        self.previous = ttk.Button(
            transport,
            text="‹ Prev",
            width=6,
            command=lambda: self.run(controller.previous_track),
        )
        self.previous.grid(row=0, column=0, padx=3)
        self.play_button = ttk.Button(
            transport,
            text="Play",
            width=9,
            command=self.toggle,
            style="MusicPlay.TButton",
        )
        self.play_button.grid(row=0, column=1, padx=3)
        self.next = ttk.Button(
            transport,
            text="Next ›",
            width=6,
            command=lambda: self.run(controller.next_track),
        )
        self.next.grid(row=0, column=2, padx=3)
        self.stop = ttk.Button(
            transport,
            text="Stop",
            width=5,
            command=lambda: self.run(controller.stop_music),
        )
        self.stop.grid(row=0, column=3, padx=3)

        volume_row = tk.Frame(self, bg=self.bg)
        volume_row.grid(row=5, column=0, columnspan=2, sticky="ew")
        volume_row.columnconfigure(1, weight=1)
        tk.Label(
            volume_row, text="Volume", bg=self.bg, fg=self.muted, font=("Arial", 9)
        ).grid(row=0, column=0)
        self.volume = tk.DoubleVar(value=config.get("classical_music_volume", 30))
        self.volume_slider = ttk.Scale(
            volume_row,
            from_=0,
            to=100,
            variable=self.volume,
            command=self._volume_preview,
        )
        self.volume_slider.grid(row=0, column=1, sticky="ew", padx=6)
        self.volume_label = tk.Label(
            volume_row,
            text=f"{int(self.volume.get())}%",
            bg=self.bg,
            fg=self.muted,
            width=4,
            font=("Arial", 9),
        )
        self.volume_label.grid(row=0, column=2)
        self.volume_slider.bind(
            "<ButtonPress-1>", lambda e: setattr(self, "_volume_drag", True)
        )
        self.volume_slider.bind("<ButtonRelease-1>", self._set_volume)
        self.volume_slider.bind("<KeyRelease>", self._set_volume)

        self.playlist_var = tk.StringVar()
        self.playlist_combo = ttk.Combobox(
            self, textvariable=self.playlist_var, state="readonly", width=12
        )
        self.playlist_combo.grid(row=6, column=0, sticky="ew", pady=(8, 0), padx=(0, 6))
        self.playlist_combo.bind("<<ComboboxSelected>>", select_playlist)
        ttk.Button(self, text="Change…", command=add_link).grid(
            row=6, column=1, sticky="e", pady=(8, 0)
        )
        self.device_menu = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label="Audio output", menu=self.device_menu)
        self.device_var = tk.StringVar(value="auto")
        session_menu = tk.Menu(menu, tearoff=False)
        menu.add_cascade(label="YouTube", menu=session_menu)
        self.browser_var = tk.StringVar(value=config.get("youtube_browser", ""))
        if select_session:
            session_menu.add_radiobutton(
                label="Chrome session",
                value="chrome",
                variable=self.browser_var,
                command=lambda: (
                    self._connect_chrome()
                    if config.get("chrome_mix_connection") is False
                    and self._selected_mix()
                    else select_session("chrome")
                ),
            )
            session_menu.add_command(
                label="Connect Chrome…", command=self._connect_chrome
            )
            session_menu.add_radiobutton(
                label="Play without sign-in",
                value="",
                variable=self.browser_var,
                command=lambda: select_session(""),
            )
        self._devices = None
        self.bind(
            "<Configure>",
            lambda e: (
                self.title_label.configure(wraplength=max(160, e.width - 24)),
                self.source_label.configure(wraplength=max(160, e.width - 24)),
            ),
        )

    def _label(self, text, size, bold=False, color=None):
        return tk.Label(
            self,
            text=text,
            bg=self.bg,
            fg=color or self.fg,
            anchor="w",
            font=("Arial", size, "bold" if bold else "normal"),
        )

    def _on_destroy(self, event):
        if event.widget is self:
            self._closed = True
            self._actions.put(None)

    def run(self, action):
        """Queue requests in order so a new link cannot be silently discarded."""
        if self._closed:
            return
        self._actions.put(action)
        # User actions wake a sleeping GUI; workers never touch Tk widgets.
        if self.on_action:
            self.on_action()
        with self._worker_lock:
            if self._worker is None:
                self._worker = threading.Thread(target=self._run_actions, daemon=True)
                self._worker.start()

    @property
    def busy(self):
        return self._actions.unfinished_tasks > 0 or self._updater is not None

    def _run_actions(self):
        while True:
            action = self._actions.get()
            if action is None or self._closed:
                return
            try:
                action()
            except Exception as exc:
                self.controller.last_error = (
                    "The player could not finish this action. Retry playback."
                )
                self.controller.playback_state = "error"
                logging.getLogger(__name__).warning(
                    "Music action failed: %s", type(exc).__name__
                )
            finally:
                self._actions.task_done()

    def toggle(self):
        state = self.controller.playback_state
        if state == "loading":
            return
        action = (
            self.controller.pause_music
            if state == "playing"
            else (
                self.controller.resume_music
                if state == "paused"
                else self.controller.start_music
            )
        )
        self.run(action)

    def _volume_preview(self, value):
        self.volume_label.configure(text=f"{round(float(value))}%")

    def _set_volume(self, event=None):
        value = round(self.volume.get())
        self._volume_drag = False
        self.run(lambda: self.controller.set_volume(value))

    def _seek(self, event=None):
        value = self.position.get()
        self._seek_drag = False
        self.run(lambda: self.controller.seek(value))

    def _dismiss_recovery(self):
        if self._recovery_window is not None:
            self._recovery_window.destroy()
            self._recovery_window = None

    def _selected_mix(self):
        from .system import youtube_source_kind

        return youtube_source_kind(self.selected_source) == "radio"

    def _connect_chrome(self):
        from tkinter import messagebox
        from .chrome_setup import prepare_extension
        from .system import _CHROME_CONNECTION_ERRORS, _CHROME_SIGNED_OUT

        if (
            self._connection_window is not None
            and self._connection_window.winfo_exists()
        ):
            self._connection_window.lift()
            return
        source = self.selected_source
        if not self._selected_mix():
            messagebox.showinfo(
                "Personal Mix",
                "Choose a YouTube Mix under Music → Change… first.",
                parent=self,
            )
            return
        try:
            folder = prepare_extension(self._config)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Chrome connection", str(exc), parent=self)
            return
        window = self._connection_window = tk.Toplevel(self)
        self._connection_prompted = True
        window.title("Personal Mix")
        window.transient(self.winfo_toplevel())
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        notice = tk.StringVar()
        ttk.Label(frame, textvariable=notice, wraplength=320).pack(
            anchor="w", pady=(0, 8)
        )
        button = ttk.Button(frame, text="Close", command=window.destroy)
        button.pack(anchor="e")
        window.bind("<Escape>", lambda event: window.destroy())

        def play():
            window.destroy()
            if self.selected_source == source:
                if (
                    self.controller.is_playing
                    and self.controller.current_playlist == source
                ):
                    self.run(lambda: self.controller.restart_youtube_session(source))
                elif not self.controller.is_playing:
                    self.run(self.controller.start_music)

        def sign_in():
            try:
                open_chrome("https://www.youtube.com/")
            except OSError:
                notice.set("Open YouTube in Google Chrome to sign in.")
            button.configure(text="Check connection", command=check)

        def finish(message, error):
            if not window.winfo_exists():
                return
            if message is None:
                window.destroy()
                return
            notice.set(message)
            label, action = "Done", window.destroy
            if error in (
                _CHROME_CONNECTION_ERRORS["extension"],
                _CHROME_CONNECTION_ERRORS["pairing"],
            ):
                notice.set("Chrome needs Tempo Mix to share your song order.")
                label, action = "Set up in Chrome", lambda: check(install=True)
            elif error == _CHROME_SIGNED_OUT:
                notice.set("Sign in to YouTube to use your personal Mix.")
                label, action = "Open YouTube", sign_in
            elif error:
                label, action = "Try again", check
            elif self.selected_source == source and (
                not self.controller.is_playing
                or self.controller.get_status().get("public_mix")
            ):
                notice.set("Your personal Mix is ready.")
                label, action = (
                    "Use my Mix" if self.controller.is_playing else "Play my Mix"
                ), play
            button.configure(text=label, command=action)

        def check(install=False):
            notice.set(
                "Waiting for Chrome setup…"
                if install
                else "Connecting to your personal Mix…"
            )
            button.configure(text="Close", command=window.destroy)

            def connect():
                error = None
                try:
                    message = self.controller.connect_chrome_mix(
                        source, folder, install=install
                    )
                except (OSError, ValueError) as exc:
                    message = error = str(exc)
                if not self._closed:
                    try:
                        self.after(0, finish, message, error)
                    except (tk.TclError, RuntimeError):
                        pass

            threading.Thread(target=connect, daemon=True).start()

        check()

    def _update_helper(self, attempt, install_player=None):
        self._update_attempt = attempt
        self._update_button.configure(state="disabled")
        self._update_error = (
            "mpv installation failed. Use the mpv download link or try again."
            if install_player
            else "The helper update failed. Check your connection and try again."
        )
        self._recovery_message.set(
            "Installing mpv…"
            if install_player
            else "Updating the YouTube playback helper…"
        )
        if self._updater is not None:
            return
        try:
            self._updater = subprocess.Popen(
                install_player
                or (
                    [sys.executable, "--update-youtube"]
                    if getattr(sys, "frozen", False)
                    else [
                        sys.executable,
                        "-m",
                        "pip",
                        "--disable-pip-version-check",
                        "--no-input",
                        "install",
                        "--upgrade",
                        "--only-binary=:all:",
                        "--retries",
                        "1",
                        "--timeout",
                        "15",
                        "yt-dlp[default]",
                    ]
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self._update_button.configure(state="normal")
            self._recovery_message.set(self._update_error)
            return
        if self.on_action:
            self.on_action()

    def _refresh_recovery(self, status):
        attempt = status.get("attempt", 0)
        failed = status["state"] == "error"
        if self._updater is not None and self._updater.poll() is not None:
            code = self._updater.returncode
            self._updater = None
            if failed and attempt == self._update_attempt and self._recovery_window:
                if code == 0:
                    self._dismiss_recovery()
                    self.after_idle(
                        lambda: self.run(
                            lambda: self.controller.retry_failed_attempt(attempt)
                        )
                    )
                    return
                self._recovery_message.set(self._update_error)
                self._update_button.configure(state="normal")
        if not failed:
            self._dismiss_recovery()
            self._shown_failure = None
            return
        if self._shown_failure == attempt:
            return
        self._shown_failure = attempt
        self._dismiss_recovery()
        self._show_recovery(status, attempt)

    def _show_recovery(self, status, attempt):
        import webbrowser
        from .system import (
            _CHROME_CONNECTION_ERRORS,
            _CHROME_COOKIE_ERROR,
            youtube_source_kind,
        )

        window = self._recovery_window = tk.Toplevel(self)
        window.title("Music couldn’t play")
        window.transient(self.winfo_toplevel())
        window.protocol("WM_DELETE_WINDOW", self._dismiss_recovery)
        window.bind("<Escape>", lambda event: self._dismiss_recovery())
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        self._recovery_message = tk.StringVar(value=status["error"])
        ttk.Label(frame, textvariable=self._recovery_message, wraplength=290).pack(
            anchor="w", pady=(0, 8)
        )

        def action(label, callback):
            def invoke():
                self._dismiss_recovery()
                callback()

            ttk.Button(frame, text=label, command=invoke).pack(fill="x", pady=2)

        source = self.selected_source or status.get("current_playlist") or ""
        chrome_mix = (
            youtube_source_kind(source) == "radio"
            and status.get("youtube_browser") == "chrome"
        )
        connection_failure = chrome_mix and (
            status["error"] in _CHROME_CONNECTION_ERRORS.values()
            or status["error"] == _CHROME_COOKIE_ERROR
            or "signed-out Mix" in status["error"]
        )
        if connection_failure:
            action("Connect Chrome…", self._connect_chrome)
        if chrome_mix:

            def open_mix():
                try:
                    open_chrome(source)
                except OSError:
                    self._recovery_message.set(
                        "Chrome couldn’t open. Check that Google Chrome is installed."
                    )

            ttk.Button(frame, text="Open Mix in Chrome", command=open_mix).pack(
                fill="x", pady=2
            )
        elif source.startswith(("https://", "http://")):
            action("Open in browser", lambda: webbrowser.open(source))
        if status.get("mpv_available") is False:
            from .mpv_installer import desktop_install_command

            install_player = desktop_install_command()
            if install_player:
                self._update_button = ttk.Button(
                    frame,
                    text="Install mpv and retry",
                    command=lambda: self._update_helper(attempt, install_player),
                )
                self._update_button.pack(fill="x", pady=2)
            action(
                "Open mpv downloads",
                lambda: webbrowser.open("https://mpv.io/installation/"),
            )
        elif youtube_source_kind(source) and not connection_failure:
            if getattr(sys, "frozen", False) or (
                sys.prefix != sys.base_prefix and sys.version_info >= (3, 11)
            ):
                self._update_button = ttk.Button(
                    frame,
                    text="Update YouTube helper and retry",
                    command=lambda: self._update_helper(attempt),
                )
                self._update_button.pack(fill="x", pady=2)
            else:
                action(
                    "Update YouTube helper…",
                    lambda: webbrowser.open(
                        "https://github.com/yt-dlp/yt-dlp/wiki/Installation"
                    ),
                )
        action("Choose music…", self._choose_music)
        action("Retry", lambda: self.run(self.controller.start_music))

    def refresh(self, status):
        state = status["state"]
        labels = {
            "loading": "Connecting…",
            "playing": "Playing",
            "paused": "Paused",
            "stopped": "Ready",
            "error": "Unable to play",
        }
        self.status_label.configure(
            text=(
                "Buffering…"
                if state == "playing" and status.get("buffering")
                else labels.get(state, "Ready")
            )
        )
        selected = self.selected_source
        bookmark = status.get("bookmark", {})
        remembered = bookmark.get("title") if selected == bookmark.get("source") else ""
        self.title_label.configure(
            text=status.get("current_track")
            or remembered
            or source_label(selected)
            or "Choose music"
        )
        details = []
        if status.get("source_kind") == "radio":
            details.append(
                "Public YouTube Mix"
                if status.get("public_mix")
                else "Personal YouTube Mix"
            )
        if (
            (
                status.get("public_mix")
                or (not status["is_playing"] and self._selected_mix())
            )
            and status.get("youtube_browser") == "chrome"
            and self._config.get("chrome_mix_connection") is False
        ):
            self.connect_button.grid(
                row=7, column=0, columnspan=2, sticky="w", pady=(6, 0)
            )
            if (
                state == "playing"
                and not self._connection_prompted
                and self._selected_mix()
                and selected == status.get("current_playlist")
            ):
                self._connection_prompted = True
                self.after_idle(self._connect_chrome)
        else:
            self.connect_button.grid_remove()
        if status.get("guest_playback") and status["is_playing"]:
            details.append("Playing as guest")
        count = status.get("playlist_count", 0)
        if status["is_playing"] and count > 1:
            details.append(f"Track {status.get('playlist_index', 1)} of {count}")
        if status.get("route") == "Proxy" and status["is_playing"]:
            details.append("Proxy")
        self.browser_var.set(status.get("youtube_browser", ""))
        detail = status.get("error") if state == "error" else " · ".join(details)
        if state in ("playing", "paused") and status.get("up_next"):
            detail += "\nUp next · " + status["up_next"]
        if detail:
            self.source_label.configure(text=detail, justify="left")
            self.source_label.grid()
        else:
            self.source_label.grid_remove()
        self.play_button.configure(
            text={"playing": "Pause", "paused": "Resume", "error": "Retry"}.get(
                state, "Play"
            ),
            state="disabled" if state == "loading" else "normal",
        )
        active = status["is_playing"]
        self.stop.configure(state="normal" if active else "disabled")
        queued = status.get("playlist_count", 0) > 1
        index = status.get("playlist_index", 1)
        self.previous.configure(
            state="normal" if active and queued and index > 1 else "disabled"
        )
        self.next.configure(
            state="normal" if active and queued and index < count else "disabled"
        )
        duration = status.get("duration", 0)
        position = status.get("position", 0) if active else 0
        self.elapsed.configure(text=clock_text(position))
        self.duration_label.configure(
            text=(
                clock_text(duration)
                if duration
                else "Live" if state == "playing" else "—"
            )
        )
        self.seek_slider.configure(
            to=max(1, duration), state="normal" if active and duration else "disabled"
        )
        if not self._seek_drag:
            self.position.set(position)
        if not self._volume_drag:
            self.volume.set(status["volume"])
            self._volume_preview(status["volume"])
        devices = status.get("devices", [])
        if devices != self._devices:
            self._devices = list(devices)
            self.device_menu.delete(0, "end")
            for device in devices or [
                {"name": "auto", "description": "System default"}
            ]:
                self.device_menu.add_radiobutton(
                    variable=self.device_var,
                    value=device["name"],
                    label=device["description"],
                    command=lambda name=device["name"]: self.run(
                        lambda: self.controller.set_audio_device(name)
                    ),
                )
        self.device_var.set(status.get("device") or "auto")
        self._refresh_recovery(status)
