import threading
import tkinter as tk
from unittest.mock import Mock

import pytest

from src.core import ConfigManager, SessionType
from src.music_panel import MusicPanel
from src.ui import CustomSessionDialog, SettingsDialog


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    window.geometry("360x500")
    window.update()
    yield window
    window.destroy()


def test_settings_validate_before_changing_anything_and_retry(
    root, tmp_path, monkeypatch
):
    config = ConfigManager(tmp_path / "config.yml")
    config.set("google_task_list_id", "my-list")
    config.set("classical_music_selected_playlist", "favorite.m3u")
    assert config.save_config()
    sync = Mock()
    dialog = SettingsDialog(root, config, sync)
    dialog.timer_fields["work_mins"][1].set("36")
    dialog.timer_fields["short_break_mins"][1].set("0")
    dialog.save_application_settings()
    assert dialog.dialog.winfo_exists() and dialog.notice.cget("text")
    assert config.get("work_mins") == 25

    dialog.timer_fields["short_break_mins"][1].set("5")
    with monkeypatch.context() as patch:
        patch.setattr(config, "save_config", lambda: False)
        dialog.save_application_settings()
        assert config.get("work_mins") == 25
        assert dialog.dialog.winfo_exists() and not dialog.result

    dialog.dark_theme.set(False)
    dialog.interface_size.set("75%")
    dialog.save_application_settings()
    restored = ConfigManager(config.config_path)
    assert dialog.result and not dialog.dialog.winfo_exists()
    assert restored.get("work_mins") == 36 and not restored.get("dark_theme")
    assert restored.get("gui_zoom") == 0.75
    assert restored.get("google_task_list_id") == "my-list"
    assert restored.get("classical_music_selected_playlist") == "favorite.m3u"
    sync.get_task_lists.assert_not_called()


def test_task_list_request_allows_closing_settings(root, tmp_path):
    config = ConfigManager(tmp_path / "config.yml")
    config.set("google_task_list_id", "my-list")
    fetch_started, release = threading.Event(), threading.Event()
    account = Mock()

    def fetch():
        fetch_started.set()
        release.wait(4)
        return [{"id": "my-list", "title": "Work"}]

    account.get_task_lists.side_effect = fetch
    dialog = SettingsDialog(root, config, account)
    try:
        root.update()
        account.get_task_lists.assert_not_called()
        dialog.notebook.select(dialog.tasks_tab)
        root.update()
        assert fetch_started.wait(2)
        dialog.cancel()
        assert not dialog.dialog.winfo_exists()
    finally:
        release.set()

    def wait_for_result():
        if root._tempo_account_busy:
            root.after(10, wait_for_result)
        else:
            root.quit()

    guard = root.after(4000, root.quit)
    root.after(0, wait_for_result)
    root.mainloop()
    root.after_cancel(guard)
    assert not root._tempo_account_busy
    assert config.get("google_task_list_id") == "my-list"


def test_custom_session_allows_correcting_duration(root):
    dialog = CustomSessionDialog(root)
    dialog.duration_var.set("-5")
    dialog.ok_clicked()
    assert dialog.result is None and dialog.notice.cget("text")
    dialog.duration_var.set("8")
    dialog.type_var.set("break")
    dialog.ok_clicked()
    assert dialog.result == (SessionType.SHORT_BREAK, 8)


def test_first_music_action_opens_chooser_and_selected_source_reveals_controls(root):
    player = Mock(playback_state="stopped")
    choose = Mock()
    panel = MusicPanel(root, player, {}, choose, Mock())
    panel.pack()
    status = {"state": "stopped", "volume": 30, "is_playing": False, "error": ""}
    panel.refresh(status)
    root.update_idletasks()
    assert panel.change_button.cget("text") == "Choose music…"
    assert not panel.play_button.winfo_ismapped()
    panel.toggle()
    choose.assert_called_once()
    player.start_music.assert_not_called()
    panel.selected_source = "sample.m3u"
    panel.refresh(status)
    root.update_idletasks()
    assert panel.play_button.winfo_ismapped()
    assert panel.change_button.cget("text") == "Change…"


def test_zoom_scales_later_rows_dialogs_and_spacing_from_originals(root, tmp_path):
    from tkinter import font, ttk
    from src.appearance import scale_interface

    def measures(label):
        return font.Font(root=root, font=label.cget("font")).actual("size"), int(
            label.cget("padx")
        )

    first = tk.Label(root, font=("Arial", 20), padx=12)
    first.pack(pady=8)
    scale_interface(root, 0.75)
    later = tk.Label(root, font=("Arial", 20), padx=12)
    later.pack(pady=8)
    root.update()
    assert measures(first) == measures(later) == (15, 9)
    assert int(later.pack_info()["pady"]) == 6
    dialog = SettingsDialog(root, ConfigManager(tmp_path / "config.yml"))
    assert (
        font.Font(root=root, font=ttk.Style(root).lookup("TButton", "font")).actual(
            "size"
        )
        == 8
    )
    assert tuple(int(str(p)) for p in dialog.timer_tab.cget("padding")) == (10,)
    scale_interface(root, 1.25)
    assert measures(first) == measures(later) == (25, 15)
    assert int(later.pack_info()["pady"]) == 10
    scale_interface(root, 1.0)
    assert measures(first) == measures(later) == (20, 12)
    assert tuple(int(str(p)) for p in dialog.timer_tab.cget("padding")) == (14,)
    dialog.cancel()
