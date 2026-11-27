import shutil
import time
import wave
from unittest.mock import Mock

import pytest

from src.core import ConfigManager
from src.system import MusicController


def test_reopen_uses_selected_source_after_another_window_saves(tmp_path):
    path = tmp_path / "config.yml"
    settings = ConfigManager(path)
    settings.set("classical_music_default_playlist", "old.m3u")
    assert settings.save_config()
    older_window = ConfigManager(path)
    song = "https://example.org/new.mp3"
    settings.set("classical_music_selected_playlist", song)
    assert settings.save_config()
    older_window.set("window_geometry", "283x761+0+0")
    assert older_window.save_config()
    reopened = ConfigManager(path)
    assert reopened.get("window_geometry") == "283x761+0+0"
    assert reopened.get_music_playlists()[0]["path"] == song


def test_idle_player_does_not_probe_mpv(monkeypatch, tmp_path):
    probe = Mock()
    monkeypatch.setattr(MusicController, "_find_mpv_executable", probe)
    music = MusicController(ConfigManager(tmp_path / "config.yml"))
    assert music.get_status()["state"] == "stopped"
    probe.assert_not_called()


@pytest.mark.parametrize(
    "pause_on_break,already_paused", [(False, False), (True, True)]
)
def test_break_only_resumes_music_it_paused(tmp_path, pause_on_break, already_paused):
    config = ConfigManager(tmp_path / "config.yml")
    config.set("pause_music_on_break", pause_on_break)
    player = MusicController(config)
    player.is_playing = True
    player.playback_state = "paused" if already_paused else "playing"
    player._send_mpv_command = Mock()
    player.pause_for_break()
    player.finish_break()
    player._send_mpv_command.assert_not_called()


@pytest.mark.skipif(not shutil.which("mpv"), reason="mpv is unavailable")
def test_real_player_break_and_reordered_playlist_on_reopen(tmp_path):
    songs = []
    for name in ("First.wav", "Second.wav", "Third.wav"):
        song = tmp_path / name
        with wave.open(str(song), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", ""))
            audio.writeframes(bytes(8000 * 2 * 20))
        songs.append(str(song))
    playlist = tmp_path / "Focus.m3u8"
    playlist.write_text("\n".join(songs), encoding="utf-8")
    settings = ConfigManager(tmp_path / "config.yml")
    settings.set("classical_music_selected_playlist", str(playlist))
    settings.set("classical_music_shuffle", False)
    settings.set("mpv_extra_args", "--no-config --ao=null")
    assert settings.save_config()

    def wait_for(predicate):
        deadline = time.monotonic() + 8
        while not predicate():
            assert time.monotonic() < deadline, "Timed out waiting for local mpv"
            time.sleep(0.04)

    music = MusicController(settings)
    music.pid_file = tmp_path / "player.pid"
    try:
        assert music.start_music()
        wait_for(lambda: music.bookmark.get("track") == songs[0])
        assert music.next_track()
        wait_for(lambda: music.bookmark.get("track") == songs[1])
        assert music.seek(7)
        wait_for(lambda: music.get_status()["position"] >= 7)
        music.pause_for_break()
        music.pause_for_break()  # Work completion followed by the break start.
        assert music.playback_state == "paused"
        original_process = music.mpv_process
        music.finish_break()
        assert music.start_music()  # Work starts with the already-resumed player.
        assert music.mpv_process is original_process
        assert music.get_status()["position"] >= 7
    finally:
        music.cleanup()

    playlist.write_text("\n".join([songs[0], songs[2], songs[1]]), encoding="utf-8")
    music = MusicController(ConfigManager(settings.config_path))
    music.pid_file = tmp_path / "player.pid"
    try:
        assert music.mpv_process is None
        assert music.bookmark["title"] == "Second.wav"
        assert music.start_music()
        wait_for(lambda: music.get_status()["current_track"] == "Second.wav")
        wait_for(lambda: music.get_status()["playlist_index"] == 3)
    finally:
        music.cleanup()
