import io
from pathlib import Path
from unittest.mock import Mock

from src.core import ConfigManager
from src.system import MusicController


def test_playlist_url_survives_config_round_trip(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(
        "classical_music_default_playlist: https://www.youtube.com/watch?v=abc&list=xyz\n"
    )
    config = ConfigManager(path)
    url = config.get("classical_music_default_playlist")
    assert url == "https://www.youtube.com/watch?v=abc&list=xyz"
    assert config.get_music_playlists()[0]["path"] == url
    assert not any("playlist not found" in issue for issue in config.validate_config())
    assert config.save_config()
    assert ConfigManager(path).get("classical_music_default_playlist") == url


def test_repairs_previously_collapsed_url_in_memory(tmp_path):
    path = tmp_path / "config.yml"
    original = "classical_music_default_playlist: https:/www.youtube.com/watch?v=abc\n"
    path.write_text(original)
    config = ConfigManager(path)
    assert config.get("classical_music_default_playlist").startswith("https://")
    assert path.read_text() == original


def controller(monkeypatch, tmp_path):
    monkeypatch.setattr(MusicController, "_find_mpv_executable", lambda self: "mpv")
    monkeypatch.setattr(MusicController, "_test_mpv_executable", lambda *args: True)
    return MusicController(ConfigManager(tmp_path / "config.yml"))


def test_player_exit_clears_false_playing_status(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    process = Mock(stdout=io.StringIO("network error\n"))
    process.wait.return_value = 2
    music.mpv_process = process
    music.is_playing = True
    music._monitor_playback(process)
    assert not music.is_playing
    assert music.get_status()["state"] == "error"
    assert music.get_status()["error"]


def test_old_player_cannot_change_new_player_status(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    old = Mock(stdout=io.StringIO("FOCUS_PLAYING:old track\n"))
    old.wait.return_value = 2
    music.mpv_process = Mock()
    music.is_playing = True
    music.playback_state = "loading"
    music._monitor_playback(old)
    assert music.is_playing
    assert music.playback_state == "loading"
    assert music.current_track_name == ""


def test_pause_and_volume_use_existing_player(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    music.mpv_process = Mock()
    music.mpv_process.poll.return_value = None
    music.is_playing = True
    music._send_mpv_command = Mock(return_value={"error": "success"})
    assert music.pause_music()
    assert music.playback_state == "paused"
    assert music.resume_music()
    assert music.set_volume(35)
    assert music._send_mpv_command.call_args.args[0] == ["set_property", "volume", 35]


def test_mac_proxy_running_uses_proxy(monkeypatch):
    import socket
    import urllib.request

    from src.system import _mac_music_proxy

    monkeypatch.setattr("src.system.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        urllib.request, "getproxies", lambda: {"http": "http://127.0.0.1:10808"}
    )
    from unittest.mock import MagicMock

    connection = MagicMock()
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: connection)
    assert _mac_music_proxy() == "http://127.0.0.1:10808"
    connection.__exit__.assert_called_once()


def test_mac_proxy_closed_uses_direct(monkeypatch):
    import socket
    import urllib.request

    from src.system import _mac_music_proxy

    monkeypatch.setattr("src.system.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        urllib.request, "getproxies", lambda: {"https": "http://localhost:10808"}
    )

    def refused(*args, **kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(socket, "create_connection", refused)
    assert _mac_music_proxy() == ""


def test_mac_without_proxy_uses_direct(monkeypatch):
    import urllib.request

    from src.system import _mac_music_proxy

    monkeypatch.setattr("src.system.platform.system", lambda: "Darwin")
    monkeypatch.setattr(urllib.request, "getproxies", dict)
    assert _mac_music_proxy() == ""


def test_gui_no_proxy_does_not_hide_mac_system_proxy(monkeypatch):
    import socket
    import urllib.request
    from unittest.mock import MagicMock

    from src.system import _mac_music_proxy

    monkeypatch.setattr("src.system.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        urllib.request, "getproxies", lambda: {"no": "localhost,127.0.0.1"}
    )
    monkeypatch.setattr(
        urllib.request,
        "getproxies_macosx_sysconf",
        lambda: {"http": "http://127.0.0.1:10808"},
        raising=False,
    )
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: MagicMock())
    assert _mac_music_proxy() == "http://127.0.0.1:10808"


def test_live_player_events_keep_progress_pause_and_volume_in_sync(
    monkeypatch, tmp_path
):
    music = controller(monkeypatch, tmp_path)
    monkeypatch.setattr("src.system.time.monotonic", lambda: 100)
    music.is_playing = True
    music._apply_player_property("time-pos", 42)
    music._apply_player_property("duration", 180)
    music._apply_player_property("media-title", "A new track")
    music._apply_player_property("volume", 60)
    music._apply_player_property("pause", True)
    monkeypatch.setattr("src.system.time.monotonic", lambda: 110)
    status = music.get_status()
    assert status["position"] == 42
    assert status["duration"] == 180
    assert status["state"] == "paused"
    assert status["volume"] == 60
    assert status["current_track"] == "A new track"


def test_exact_double_paste_is_repaired_and_multiple_different_links_rejected():
    import pytest

    from src.system import normalise_music_link

    link = (
        "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU&start_radio=1"
    )
    assert normalise_music_link(link + link) == link
    with pytest.raises(ValueError):
        normalise_music_link(link + "https://youtu.be/another")
    with pytest.raises(ValueError):
        normalise_music_link("https://www.youtube.com/watch")


def test_retry_uses_new_selection_instead_of_failed_old_playlist(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    new = "https://www.youtube.com/watch?v=sJL3NuTkfRU"
    music.config.set("classical_music_default_playlist", new)
    music._paused_playlist = "https://www.youtube.com/playlist?list=removed"
    music.playback_state = "error"
    music.pid_file = tmp_path / "player.pid"
    process = Mock(pid=12345)
    launch = Mock(return_value=process)
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    assert music.start_music()
    assert launch.call_args.args[0][-1] == new


def test_unavailable_playlist_reports_specific_reason(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    process = Mock(
        stdout=io.StringIO(
            "WARNING: YouTube said: The playlist does not exist.\n"
            "[ytdl_hook] youtube-dl failed: unexpected error occurred\n"
        )
    )
    process.wait.return_value = 2
    music.mpv_process = process
    music.is_playing = True
    music._monitor_playback(process)
    assert "unavailable or private" in music.last_error


def test_youtube_radio_and_video_links_are_distinguished():
    from src.system import youtube_source_kind

    assert (
        youtube_source_kind(
            "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU&start_radio=1"
        )
        == "radio"
    )
    assert (
        youtube_source_kind("https://www.youtube.com/watch?v=sJL3NuTkfRU&list=PLtest")
        == "playlist"
    )
    assert youtube_source_kind("https://www.youtube.com/watch?v=sJL3NuTkfRU") == "video"
    assert youtube_source_kind("https://example.com/watch?list=RDtest") == ""


def test_radio_launch_expands_mix_without_unbounded_extraction(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "player.pid"
    launch = Mock(return_value=Mock(pid=12345))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    url = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU&start_radio=1"
    assert music.start_music(url)
    args = launch.call_args.args[0]
    assert "--ytdl-raw-options-append=yes-playlist=" in args
    assert "--ytdl-raw-options-append=playlist-end=50" in args
    assert args[-1] == url
    assert [arg for arg in args if arg.startswith("--shuffle=")][-1] == "--shuffle=no"

    music.config.set("classical_music_shuffle", True)
    assert music.change_playlist("https://www.youtube.com/playlist?list=PLexample")
    args = launch.call_args.args[0]
    assert "--ytdl-raw-options-append=yes-playlist=" in args
    assert [arg for arg in args if arg.startswith("--shuffle=")][-1] == "--shuffle=no"


def test_radio_track_change_returns_from_loading_to_playing(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    music.playback_state = "playing"
    music.current_track_name = "Old song"
    music._live = {"time-pos": 180, "duration": 180, "pause": False}
    music._apply_player_event({"event": "start-file"})
    assert music.playback_state == "loading"
    assert not music.current_track_name
    assert music.get_status()["duration"] == 0
    music._apply_player_event(
        {"event": "property-change", "name": "media-title", "data": "Next song"}
    )
    music._apply_player_event({"event": "playback-restart"})
    assert music.playback_state == "playing"
    assert music.current_track_name == "Next song"


def test_chrome_session_is_opt_in_and_only_used_for_youtube(monkeypatch, tmp_path):
    from unittest.mock import Mock

    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "player.pid"
    launch = Mock(return_value=Mock(pid=12345))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    youtube = "https://www.youtube.com/watch?v=sJL3NuTkfRU"
    flag = "--ytdl-raw-options-append=cookies-from-browser=chrome"
    assert music.start_music(youtube)
    assert flag not in launch.call_args.args[0]
    music.mpv_process = None
    music.config.set("youtube_browser", "chrome")
    assert music.start_music(youtube)
    assert flag in launch.call_args.args[0]
    music.mpv_process = None
    assert music.start_music("https://example.com/music.mp3")
    assert flag not in launch.call_args.args[0]


def test_radio_uses_youtubes_continuation_and_stops_with_the_player(
    monkeypatch, tmp_path
):
    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "player.pid"
    url = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    launch = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    for repeat in (True, False):
        music.config.set("classical_music_repeat", repeat)
        assert music.start_music(url)
        env = launch.call_args.kwargs["env"]
        assert bool(env.get("FOCUS_MIX_FOLLOW")) is repeat
        assert env["FOCUS_MIX_ID"] == "RDsJL3NuTkfRU"
        count = launch.call_count
        music._player_finished(music.mpv_process, 0)
        assert music.playback_state == "stopped"
        assert launch.call_count == count


def test_radio_reopens_at_saved_track_in_the_original_mix(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "player.pid"
    url = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    music.config.set("classical_music_selected_playlist", url)
    music.bookmark = {
        "source": url,
        "track": "https://www.youtube.com/watch?v=Ey6Fi6SjBR4",
    }
    launch = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    assert music.start_music()
    assert (
        launch.call_args.args[0][-1]
        == "https://www.youtube.com/watch?v=Ey6Fi6SjBR4&list=RDsJL3NuTkfRU"
    )
    assert music.current_playlist == url
    assert "FOCUS_RESUME_TRACK" not in launch.call_args.kwargs["env"]


def test_radio_and_chrome_preferences_survive_reopen(tmp_path):
    path = tmp_path / "config.yml"
    first = ConfigManager(path)
    source = (
        "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU&start_radio=1"
    )
    for key, value in {
        "youtube_browser": "chrome",
        "classical_music_default_playlist": source,
        "classical_music_selected_playlist": source,
        "gui_zoom": 0.85,
        "radio_refresh": True,
    }.items():
        first.set(key, value)
    assert first.save_config()
    second = ConfigManager(path)
    assert second.get("youtube_browser") == "chrome"
    assert second.get("classical_music_selected_playlist") == source
    assert second.get("gui_zoom") == 0.85
    assert second.get("radio_refresh")


def test_chrome_cookie_failure_retries_individual_video_as_guest_once(
    monkeypatch, tmp_path
):
    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "mpv.pid"
    music.config.set("youtube_browser", "chrome")
    url = "https://www.youtube.com/watch?v=seed"
    attempts = [Mock(pid=i) for i in (1, 2, 3)]
    launch = Mock(side_effect=attempts)
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    monkeypatch.setattr("src.system._mac_music_proxy", lambda: "")
    assert music.start_music(url)
    line = "[ytdl_hook] ERROR: Could not copy Chrome cookie database"
    music._handle_player_line(attempts[0], line)
    music._player_finished(attempts[0], 2)
    guest_args = launch.call_args.args[0]
    assert music.mpv_process is attempts[1]
    assert guest_args[-1] == url
    assert "--ytdl-raw-options-append=cookies-from-browser=chrome" not in guest_args
    assert "--ytdl-raw-options-append=ignore-config=" in guest_args
    assert "--ytdl-raw-options-remove=cookies-from-browser" in guest_args
    assert music.get_status()["guest_playback"]
    assert music.config.get("youtube_browser") == "chrome"

    music._handle_player_line(attempts[1], line)
    music._player_finished(attempts[1], 2)
    assert music.get_status()["state"] == "error"
    assert launch.call_count == 2
    assert music.restart_youtube_session(url)
    assert (
        "--ytdl-raw-options-append=cookies-from-browser=chrome"
        in launch.call_args.args[0]
    )
    assert not music.get_status()["guest_playback"]


def test_youtube_uses_app_extractor_with_launcher_path(monkeypatch, tmp_path):
    import os
    import sysconfig

    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "mpv.pid"
    scripts = tmp_path / "app tools"
    scripts.mkdir()
    helper = scripts / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    helper.touch(mode=0o755)
    monkeypatch.setattr(sysconfig, "get_path", lambda name: str(scripts))
    monkeypatch.setenv("PATH", str(tmp_path))
    launch = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    monkeypatch.setattr("src.system._mac_music_proxy", lambda: "")
    assert music.start_music("https://youtu.be/seed")
    args = launch.call_args.args[0]
    option = "--script-opts-append=ytdl_hook-ytdl_path="
    assert [Path(arg[len(option) :]) for arg in args if arg.startswith(option)] == [
        helper
    ]


def test_outdated_repair_cannot_restart_stopped_or_replaced_music(
    monkeypatch, tmp_path
):
    music = controller(monkeypatch, tmp_path)
    music.start_music = Mock(return_value=True)
    music.play_attempt = 3
    music.playback_state = "stopped"
    assert not music.retry_failed_attempt(3)
    music.playback_state = "error"
    assert not music.retry_failed_attempt(2)
    music.start_music.assert_not_called()
    assert music.retry_failed_attempt(3)
    music.start_music.assert_called_once_with()


def test_unavailable_chrome_retries_the_same_full_mix_as_public_once(
    monkeypatch, tmp_path
):
    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "player.pid"
    music.config.set("youtube_browser", "chrome")
    music._guest_fallback = True  # A previous standalone video needed guest playback.
    url = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    launch = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    monkeypatch.setattr("src.system._mac_music_proxy", lambda: "")
    assert music.start_music(url)
    assert launch.call_args.kwargs["env"]["FOCUS_MIX_ACCOUNT"] == "1"
    music._handle_player_line(
        music.mpv_process, "ERROR: could not find chrome cookies database"
    )
    music._player_finished(music.mpv_process, 2)
    assert launch.call_count == 2
    assert launch.call_args.args[0][-1] == url
    assert "--no-resume-playback" in launch.call_args.args[0]
    assert "FOCUS_MIX_ACCOUNT" not in launch.call_args.kwargs["env"]
    assert "FOCUS_MIX_CONNECTION" not in launch.call_args.kwargs["env"]
    assert music.current_playlist == url
    assert music.get_status()["public_mix"]
    assert music.config.get("chrome_mix_connection") is False
    assert ConfigManager(music.config.config_path).get("chrome_mix_connection") is False
    assert not music.last_error

    public = music.mpv_process
    music._handle_player_line(public, "ERROR: video unavailable")
    music._player_finished(public, 2)
    assert launch.call_count == 2 and music.playback_state == "error"


def test_up_next_uses_the_players_next_entry(monkeypatch, tmp_path):
    music = controller(monkeypatch, tmp_path)
    music._apply_player_property("playlist", [{"title": "One"}, {"title": "Two"}])
    for index, expected in ((None, ""), (-1, ""), (0, "Two"), (1, "")):
        music._apply_player_property("playlist-pos", index)
        assert music.get_status()["up_next"] == expected


def test_mix_uses_profile_last_open_in_chrome(monkeypatch, tmp_path):
    import json
    from src.system import _chrome_mix_session

    monkeypatch.setattr("src.system.sys.platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    state = tmp_path / "google-chrome" / "Local State"
    assert _chrome_mix_session() == "chrome"
    state.parent.mkdir()
    state.write_text(json.dumps({"profile": {"last_used": "Profile 3"}}))
    assert _chrome_mix_session() == "chrome:Profile 3"


def test_shared_and_saved_mix_links_open_on_the_matching_watch_page():
    from urllib.parse import parse_qs, urlsplit
    from src.system import _mix_watch_url

    mix = "RDsJL3NuTkfRU"
    for source in (
        f"https://youtu.be/sJL3NuTkfRU?list={mix}",
        f"https://www.youtube.com/playlist?list={mix}",
    ):
        mix_id, watch = _mix_watch_url(source, "")
        parsed = urlsplit(watch)
        assert mix_id == mix and parsed.path == "/watch"
        assert parse_qs(parsed.query) == {"list": [mix], "v": ["sJL3NuTkfRU"]}
    for host in ("music.youtube.com", "m.youtube.com", "youtube.com"):
        _, watch = _mix_watch_url(
            f"https://{host}/watch?v=sJL3NuTkfRU&list={mix}&index=3", ""
        )
        assert urlsplit(watch).netloc == "www.youtube.com"
        assert parse_qs(urlsplit(watch).query)["index"] == ["3"]


def test_unavailable_mix_falls_back_once_without_unpairing_other_mixes(
    monkeypatch, tmp_path
):
    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "player.pid"
    music.config.set("youtube_browser", "chrome")
    music.config.set("chrome_mix_connection", True)
    launch = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    first = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    other = "https://www.youtube.com/watch?v=Ey6Fi6SjBR4&list=RDEy6Fi6SjBR4"
    assert music.start_music(first)
    music._handle_player_line(
        music.mpv_process, "ERROR: Focus Chrome connection: network"
    )
    music._player_finished(music.mpv_process, 2)
    assert music.get_status()["public_mix"] and music.config.get(
        "chrome_mix_connection"
    )
    assert launch.call_count == 2
    assert music.change_playlist(other)
    env = launch.call_args.kwargs["env"]
    assert env["FOCUS_MIX_CONNECTION"] and env["FOCUS_MIX_ID"] == "RDEy6Fi6SjBR4"


def test_paired_chrome_plays_radio_without_reading_browser_cookies(
    monkeypatch, tmp_path
):
    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "mpv.pid"
    music.config.set("youtube_browser", "chrome")
    music.config.set("chrome_mix_connection", True)
    from src.system import _music_failure_reason

    profile = Mock(side_effect=AssertionError("unexpected Chrome profile access"))
    monkeypatch.setattr("src.system._chrome_mix_session", profile)
    launch = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    assert music.start_music(
        "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    )
    assert launch.call_args.kwargs["env"]["FOCUS_MIX_CONNECTION"] == str(
        tmp_path / "data" / "chrome-mix"
    )
    assert "--ytdl-raw-options-remove=cookies-from-browser" in launch.call_args.args[0]
    assert "Sign in" in _music_failure_reason(
        "[ytdl_hook] Focus Chrome connection: signin"
    )


def test_disconnected_mix_reopens_at_remembered_song_with_public_continuation(
    monkeypatch, tmp_path
):
    from urllib.parse import parse_qs, urlsplit

    music = controller(monkeypatch, tmp_path)
    url = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    music.pid_file = tmp_path / "mpv.pid"
    for key, value in {
        "classical_music_selected_playlist": url,
        "youtube_browser": "chrome",
        "chrome_mix_connection": False,
    }.items():
        music.config.set(key, value)
    music.bookmark = {
        "source": url,
        "track": "https://www.youtube.com/watch?v=Ey6Fi6SjBR4",
        "title": "Second",
    }
    monkeypatch.setenv("FOCUS_MIX_CONNECTION", "old connection")
    monkeypatch.setenv("FOCUS_MIX_ACCOUNT", "1")
    launch = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    assert music.start_music()
    args = launch.call_args.args[0]
    env = launch.call_args.kwargs["env"]
    assert parse_qs(urlsplit(args[-1]).query) == {
        "v": ["Ey6Fi6SjBR4"],
        "list": ["RDsJL3NuTkfRU"],
    }
    assert env["FOCUS_MIX_ID"] == "RDsJL3NuTkfRU" and env["FOCUS_MIX_FOLLOW"] == "1"
    assert "FOCUS_MIX_CONNECTION" not in env and "FOCUS_MIX_ACCOUNT" not in env
    assert "--no-resume-playback" in args and "--shuffle=no" in args
    assert music.current_playlist == url and music.get_status()["public_mix"]


def test_chrome_loss_during_mix_continuation_keeps_track_and_break(
    monkeypatch, tmp_path
):
    from urllib.parse import parse_qs, urlsplit

    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "mpv.pid"
    music.config.set("youtube_browser", "chrome")
    music.config.set("chrome_mix_connection", True)
    source = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    next_song = "https://www.youtube.com/watch?v=Ey6Fi6SjBR4&list=RDsJL3NuTkfRU"
    launch = Mock(side_effect=[Mock(pid=1), Mock(pid=2)])
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    monkeypatch.setattr(
        music, "_send_mpv_command", Mock(return_value={"error": "success"})
    )
    assert music.start_music(source)
    signed = music.mpv_process
    music._observed_process = signed
    music._apply_player_property("playlist", [{"id": 5, "filename": next_song}])
    music._apply_player_event({"event": "start-file", "playlist_entry_id": 5})
    music.pause_for_break()
    music._handle_player_line(signed, "ERROR: Focus Chrome connection: extension")
    music._player_finished(signed, 3)
    assert parse_qs(urlsplit(launch.call_args.args[0][-1]).query) == parse_qs(
        urlsplit(next_song).query
    )
    assert music.current_playlist == source and music.get_status()["public_mix"]
    assert music._paused_for_break and music._pause_requested


def test_switch_to_personal_mix_during_break_seeks_only_the_current_song(
    monkeypatch, tmp_path
):
    import json

    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "player.pid"
    source = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"
    song = "https://www.youtube.com/watch?v=Ey6Fi6SjBR4"
    music.current_playlist = source
    music.is_playing = True
    music.playback_state = "paused"
    music._paused_for_break = music._pause_requested = True
    music._live = {"time-pos": 27.5, "duration": 120}
    music.bookmark = {"source": source, "track": song}
    music.config.set("youtube_browser", "chrome")
    music.config.set("chrome_mix_connection", True)
    launch = Mock(return_value=Mock(pid=20))
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    send = Mock(return_value={"error": "success"})
    monkeypatch.setattr(music, "_send_mpv_command", send)
    assert music.restart_youtube_session(source)
    assert "--pause" in launch.call_args.args[0]
    assert "v=Ey6Fi6SjBR4" in launch.call_args.args[0][-1]
    assert music._paused_for_break and music._pause_requested
    for track in (song, "https://www.youtube.com/watch?v=Z_TcwONEOpg"):
        music._remember_track(json.dumps({"track": track}))
    send.assert_called_once_with(["seek", 27.5, "absolute"])


def test_unreadable_browser_cookies_fall_back_to_cookieless_playback(
    monkeypatch, tmp_path
):
    music = controller(monkeypatch, tmp_path)
    music.pid_file = tmp_path / "player.pid"
    music.config.set("youtube_browser", "chrome")
    link = "https://www.youtube.com/watch?v=sJL3NuTkfRU"
    flag = "--ytdl-raw-options-append=cookies-from-browser=chrome"
    failed = Mock(
        pid=1,
        stdout=io.StringIO("[ytdl_hook] ERROR: Failed to decrypt with DPAPI\n"),
    )
    failed.wait.return_value = 3
    retry = Mock(pid=2)
    launch = Mock(side_effect=[failed, retry, Mock(pid=3)])
    monkeypatch.setattr("src.system.subprocess.Popen", launch)
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    assert music.start_music(link)
    assert flag in launch.call_args.args[0]
    music._monitor_playback(failed)
    assert launch.call_count == 2
    assert flag not in launch.call_args.args[0]
    assert music.is_playing
    assert music.last_error == ""
    music.mpv_process = None
    assert music.start_music(link)
    assert flag not in launch.call_args.args[0]


def test_pipe_reader_returns_each_json_line_even_when_events_are_interleaved():
    import io

    from src.system import _read_pipe_json

    stream = io.BytesIO(
        b'{"event":"start-file"}\nnot json\n{"error":"success","data":1}\n{"ev'
    )
    assert list(_read_pipe_json(stream)) == [
        {"event": "start-file"},
        {"error": "success", "data": 1},
    ]


def test_each_controller_uses_its_own_windows_pipe(monkeypatch, tmp_path):
    from unittest.mock import Mock

    monkeypatch.setattr("src.system.platform.system", lambda: "Windows")
    first, second = controller(monkeypatch, tmp_path), controller(monkeypatch, tmp_path)
    monkeypatch.setattr("src.system.subprocess.Popen", Mock(return_value=Mock(pid=1)))
    monkeypatch.setattr("src.system.threading.Thread", Mock())
    for music in (first, second):
        music.pid_file = tmp_path / "player.pid"
        assert music.start_music("https://example.com/a.mp3")
    assert first.ipc_socket != second.ipc_socket
