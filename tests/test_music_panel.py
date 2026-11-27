import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from unittest.mock import Mock

import pytest

from src.music_panel import MusicPanel
from src.ui import FocusGUI


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    window.withdraw()
    yield window
    window.destroy()


def test_personal_mix_popup_uses_existing_connection_and_offers_play(
    root, monkeypatch, tmp_path
):
    from src.core import ConfigManager
    from src.system import _CHROME_CONNECTION_ERRORS

    class InlineThread:
        def __init__(self, *, target, daemon):
            self.start = target

    monkeypatch.setattr("src.music_panel.threading.Thread", InlineThread)
    player = Mock(is_playing=False)
    config = ConfigManager(tmp_path / "config.yml")
    panel = MusicPanel(root, player, config, Mock(), Mock())
    panel.selected_source = (
        "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    )
    panel.run = Mock()

    def popup_button():
        root.update()
        frame = panel._connection_window.winfo_children()[0]
        return next(
            child for child in frame.winfo_children() if isinstance(child, ttk.Button)
        )

    player.connect_chrome_mix.return_value = "Connected."
    panel._connect_chrome()
    assert player.connect_chrome_mix.call_args.kwargs == {"install": False}
    button = popup_button()
    assert button.cget("text") == "Play my Mix"
    button.invoke()
    panel.run.assert_called_once_with(player.start_music)

    player.connect_chrome_mix.side_effect = [
        ValueError(_CHROME_CONNECTION_ERRORS["extension"]),
        "Connected.",
    ]
    panel._connect_chrome()
    button = popup_button()
    assert button.cget("text") == "Set up in Chrome"
    assert player.connect_chrome_mix.call_args.kwargs == {"install": False}
    button.invoke()
    assert player.connect_chrome_mix.call_args.kwargs == {"install": True}
    assert popup_button().cget("text") == "Play my Mix"


def test_public_playback_prompts_once_when_personal_mix_requested(root, monkeypatch):
    panel = MusicPanel(root, Mock(), {"chrome_mix_connection": False}, Mock(), Mock())
    panel.selected_source = (
        "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    )
    popup = Mock()
    monkeypatch.setattr(panel, "_connect_chrome", popup)
    status = dict(
        state="stopped",
        is_playing=False,
        volume=30,
        error="",
        public_mix=True,
        current_playlist=panel.selected_source,
        youtube_browser="chrome",
    )
    panel.refresh(status)
    root.update_idletasks()
    popup.assert_not_called()
    for _ in range(2):
        panel.refresh({**status, "is_playing": True, "state": "playing"})
    root.update_idletasks()
    popup.assert_called_once()


def test_panel_updates_controls_and_preserves_volume_drag(root):
    panel = MusicPanel(
        root, Mock(), Mock(get=lambda key, default: default), Mock(), Mock()
    )
    status = dict(
        state="playing",
        is_playing=True,
        error="",
        current_track="Now playing",
        current_playlist="https://youtube.com/watch?v=test",
        position=65,
        duration=180,
        volume=60,
        devices=[],
        route="Proxy",
    )
    panel.refresh(status)
    assert panel.title_label.cget("text") == "Now playing"
    assert panel.play_button.cget("text") == "Pause"
    assert panel.elapsed.cget("text") == "1:05"
    assert panel.duration_label.cget("text") == "3:00"
    panel._volume_drag = True
    panel.volume.set(30)
    panel.refresh({**status, "state": "paused"})
    assert panel.volume.get() == 30
    assert panel.play_button.cget("text") == "Resume"
    panel.destroy()


def test_zoom_restores_fonts_without_compounding(root):
    gui = FocusGUI.__new__(FocusGUI)
    gui.root = root
    gui.config = Mock()
    gui.main_frame = ttk.Frame(root)
    gui.music_panel = tk.Frame(root)
    gui.zoom_label = ttk.Label(root, text="100%")
    sample = tk.Label(root, text="Timer", font=("Arial", 20))
    gui._zoom_level = 1.0
    gui._zoom_fonts = {}
    gui.set_zoom(0.8, save=False, resize=False)
    assert tkfont.Font(root=root, font=sample.cget("font")).actual("size") == 16
    gui.set_zoom(1.0, save=False, resize=False)
    assert tkfont.Font(root=root, font=sample.cget("font")).actual("size") == 20
    gui.config.save_config.assert_not_called()


def test_replacement_request_is_not_dropped_while_an_action_runs(root):
    import threading

    panel = MusicPanel(
        root, Mock(), Mock(get=lambda key, default: default), Mock(), Mock()
    )
    started, release, replaced = threading.Event(), threading.Event(), threading.Event()

    def first():
        started.set()
        release.wait(3)

    panel.run(first)
    assert started.wait(2)
    panel.run(replaced.set)
    release.set()
    assert replaced.wait(2)
    panel.destroy()


def test_failure_popup_opens_once_and_opens_selected_link(monkeypatch, root):
    import webbrowser

    browser = Mock()
    monkeypatch.setattr(webbrowser, "open", browser)
    panel = MusicPanel(root, Mock(), {}, Mock(), Mock())
    panel.selected_source = "https://youtu.be/test"
    failure = dict(
        state="error",
        error="YouTube refused this stream.",
        attempt=1,
        source_kind="video",
    )
    panel._refresh_recovery(failure)
    popup = panel._recovery_window
    panel._refresh_recovery(failure)
    assert panel._recovery_window is popup
    buttons = popup.winfo_children()[0].winfo_children()
    next(
        b
        for b in buttons
        if isinstance(b, ttk.Button) and b.cget("text") == "Open in browser"
    ).invoke()
    browser.assert_called_once_with(panel.selected_source)
    panel._refresh_recovery(failure)
    assert panel._recovery_window is None
    panel._refresh_recovery({**failure, "attempt": 2})
    assert panel._recovery_window is not None
    panel._refresh_recovery({"state": "playing", "attempt": 3})
    assert panel._recovery_window is None


@pytest.mark.parametrize(
    "same_attempt,code,retries", [(True, 0, 1), (False, 0, 0), (True, 1, 0)]
)
def test_helper_update_retries_only_current_failure(
    monkeypatch, root, same_attempt, code, retries
):
    process = Mock(returncode=code)
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr("src.music_panel.subprocess.Popen", launch)
    monkeypatch.setattr("src.music_panel.sys.prefix", "test-venv")
    monkeypatch.setattr("src.music_panel.sys.version_info", (3, 12))
    panel = MusicPanel(root, Mock(), {}, Mock(), Mock())
    panel.run = Mock()
    panel.selected_source = "https://youtu.be/test"
    status = dict(state="error", error="Unavailable", attempt=1, source_kind="video")
    panel._refresh_recovery(status)
    panel._update_button.invoke()
    assert "yt-dlp[default]" in launch.call_args.args[0]
    assert panel.busy
    process.poll.return_value = code
    panel._refresh_recovery({**status, "attempt": 1 if same_attempt else 2})
    root.update_idletasks()
    assert not panel.busy
    assert panel.run.call_count == retries
    if code:
        assert "update failed" in panel._recovery_message.get()


def test_missing_player_install_button_retries_the_original_attempt(root, monkeypatch):
    cmd = ["test-package-manager", "install", "mpv"]
    monkeypatch.setattr("src.mpv_installer.desktop_install_command", lambda: cmd)
    process = Mock(returncode=0)
    launch = Mock(return_value=process)
    monkeypatch.setattr("src.music_panel.subprocess.Popen", launch)
    panel = MusicPanel(root, Mock(), {}, Mock(), Mock())
    panel.run = lambda callback: callback()
    failure = dict(state="error", error="Install mpv", mpv_available=False, attempt=4)
    panel._refresh_recovery(failure)
    panel._update_button.invoke()
    assert launch.call_args.args[0] == cmd
    process.poll.return_value = 0
    panel._refresh_recovery(failure)
    root.update_idletasks()
    panel.controller.retry_failed_attempt.assert_called_once_with(4)


def test_signed_radio_popup_opens_original_mix_in_chrome_and_keeps_retry_available(
    root, monkeypatch
):
    from src.system import _CHROME_COOKIE_ERROR

    open_mix = Mock()
    monkeypatch.setattr("src.music_panel.open_chrome", open_mix)
    panel = MusicPanel(root, Mock(), {}, Mock(), Mock())
    panel.selected_source = (
        "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    )
    panel._refresh_recovery(
        dict(
            state="error",
            attempt=1,
            error=_CHROME_COOKIE_ERROR,
            youtube_browser="chrome",
        )
    )
    frame = panel._recovery_window.winfo_children()[0]
    buttons = {
        b.cget("text"): b for b in frame.winfo_children() if isinstance(b, ttk.Button)
    }
    assert "Connect Chrome…" in buttons
    assert "Update YouTube helper and retry" not in buttons
    buttons["Open Mix in Chrome"].invoke()
    open_mix.assert_called_once_with(panel.selected_source)
    assert buttons["Retry"].winfo_exists()
