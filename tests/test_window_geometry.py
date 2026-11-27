from src.ui import (
    _format_window_geometry,
    _normalise_window_geometry,
    _parse_window_geometry,
)


def test_parse_window_geometry_accepts_legacy_negative_offsets():
    assert _parse_window_geometry("250x720+-595+75") == (250, 720, -595, 75)


def test_normalise_window_geometry_formats_tk_compatible_offsets():
    assert _normalise_window_geometry("250x720+-595+-75") == "250x720-595-75"
    assert _normalise_window_geometry("900x700+40+80") == "900x700+40+80"


def test_parse_window_geometry_keeps_size_without_position():
    assert _parse_window_geometry("900x700") == (900, 700, None, None)
    assert _format_window_geometry(900, 700) == "900x700"


def test_parse_window_geometry_rejects_invalid_values():
    assert _parse_window_geometry("not-a-geometry") is None


def test_transient_double_minus_offsets_are_rejected_without_crashing():
    assert _parse_window_geometry("360x764-2092--18") is None
    assert _normalise_window_geometry("360x764-2092--18") is None


def test_reopen_preserves_portrait_dimensions_at_saved_zoom(tmp_path, monkeypatch):
    import tkinter as tk

    import pytest

    from src.core import ConfigManager
    from src.ui import FocusGUI

    try:
        probe = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    height = min(761, probe.winfo_screenheight() - 160)
    probe.destroy()
    path = tmp_path / "config.yml"
    config = ConfigManager(path)
    config.set("gui_zoom", 0.65)
    config.set("window_geometry", f"283x{height}+30+30")
    config.set("classical_music_selected_playlist", "Quiet piano.wav")
    assert config.save_config()
    monkeypatch.setattr("src.ui.ConfigManager", lambda: ConfigManager(path))
    monkeypatch.setattr("src.ui.create_google_integration", lambda *args: None)
    monkeypatch.setattr("src.core.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.core.TASKS_FILE", tmp_path / "tasks.json")
    monkeypatch.setattr("src.core._STATE_FILE", tmp_path / "session_state.json")
    monkeypatch.setattr("src.ui.TrayManager.start", lambda self: None)
    monkeypatch.setattr("src.ui.HotkeyManager.start", lambda self: None)

    for expected in [(283, height), (306, height - 49)]:
        app = FocusGUI()
        try:
            app.root.update()
            assert (app.root.winfo_width(), app.root.winfo_height()) == expected
            assert app.music.mpv_process is None
            assert app.music_panel.title_label.cget("text") == "Quiet piano.wav"
            if expected == (283, height):
                app.root.geometry(f"306x{height - 49}+30+30")
                app.root.update()
        finally:
            app.on_closing()
