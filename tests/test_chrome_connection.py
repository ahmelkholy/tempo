import html
import json
import re
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from src.chrome_setup import prepare_extension
from src.core import ConfigManager
from src.radio_plugins.focus.yt_dlp_plugins.chrome_connection import (
    ChromeMixError,
    read_chrome_queue,
)

URL = "https://www.youtube.com/watch?v=sJL3NuTkfRU&list=RDsJL3NuTkfRU"


@pytest.mark.parametrize(
    "response",
    [
        {"mix": "RDsJL3NuTkfRU", "tracks": [{"id": "sJL3NuTkfRU"}]},
        {"error": "signin"},
        {"error": "extension"},
    ],
)
def test_one_request_chrome_connection(tmp_path, response):
    config = ConfigManager(tmp_path / "config.yml")
    folder = prepare_extension(config)
    pair = json.loads((folder / "pairing.json").read_text())
    assert prepare_extension(config) == folder
    assert json.loads((folder / "pairing.json").read_text()) == pair
    threads, checks = [], []
    http = build_opener(ProxyHandler({}))

    def browser(address, *, background):
        assert background and pair not in address

        def transfer():
            with http.open(address, timeout=3) as page:
                assert page.headers["Cache-Control"] == "no-store"
                text = page.read().decode()
                meta = re.search('name="focus-mix" content="([^"]*)"', text)
                assert json.loads(html.unescape(meta[1])) == {"pair": pair, "url": URL}
            request = Request(
                address,
                data=json.dumps(response).encode(),
                headers={"Origin": "https://example.org"},
            )
            with pytest.raises(HTTPError) as wrong_origin:
                http.open(request, timeout=3)
            assert wrong_origin.value.code == 403
            request.add_header("Origin", f"http://{urlsplit(address).netloc}")
            with http.open(request, timeout=3) as received:
                checks.append(received.status)

        thread = threading.Thread(target=transfer)
        threads.append(thread)
        thread.start()

    if "error" in response:
        with pytest.raises(ChromeMixError, match=response["error"]):
            read_chrome_queue(URL, folder, launch=browser)
    else:
        assert read_chrome_queue(URL, folder, launch=browser) == response
    for thread in threads:
        thread.join(3)
    assert checks == [204]


def test_failed_check_keeps_song_and_disconnected_setting(monkeypatch, tmp_path):
    from src.system import MusicController
    from src.radio_plugins.focus.yt_dlp_plugins import chrome_connection

    config = ConfigManager(tmp_path / "config.yml")
    config.set("youtube_browser", "chrome")
    config.set("chrome_mix_connection", False)
    player = MusicController(config)
    player.is_playing = True
    player.current_playlist = URL
    player.playback_state = "playing"

    def unavailable(watch, folder, **kwargs):
        raise ChromeMixError("extension")

    monkeypatch.setattr(chrome_connection, "read_chrome_queue", unavailable)
    with pytest.raises(ValueError, match="Enable Focus Timer Mix"):
        player.connect_chrome_mix(URL, tmp_path)
    assert config.get("chrome_mix_connection") is False
    assert player.playback_state == "playing" and player.current_playlist == URL


def test_install_checks_queue_from_the_approving_profile(tmp_path, monkeypatch):
    from src.radio_plugins.focus.yt_dlp_plugins import chrome_connection
    from src.system import MusicController

    config = ConfigManager(tmp_path / "config.yml")
    folder = prepare_extension(config)
    http = build_opener(ProxyHandler({}))
    pending = folder / "connect.json"
    response = {
        "mix": "RDsJL3NuTkfRU",
        "tracks": [{"id": "sJL3NuTkfRU"}, {"id": "Ey6Fi6SjBR4"}],
    }
    requests, profile_pages = [], []

    def approve(page):
        requests.append(page)
        address = json.loads(pending.read_text())["url"]
        if page == "chrome://extensions/":
            return
        assert page == address

        def install():
            with http.open(page, timeout=3) as setup:
                profile_pages.append(setup.read().decode())
            for message in ({"open_extensions": True}, response):
                req = Request(
                    address,
                    data=json.dumps(message).encode(),
                    headers={"Origin": "http://" + urlsplit(address).netloc},
                )
                with http.open(req, timeout=3) as result:
                    assert result.status == 204

        threading.Thread(target=install).start()

    monkeypatch.setattr(chrome_connection, "open_chrome", approve)
    MusicController(config).connect_chrome_mix(URL, folder, install=True)
    assert requests[1:] == ["chrome://extensions/"]
    assert "Copy folder and open Extensions" in profile_pages[0]
    assert "window.close()" not in profile_pages[0]
    assert ConfigManager(config.config_path).get("chrome_mix_connection") is True
    assert not pending.exists()


def test_verified_connection_preserves_the_current_public_queue_and_pause(
    monkeypatch, tmp_path
):
    from src.system import MusicController
    from src.radio_plugins.focus.yt_dlp_plugins import chrome_connection
    from unittest.mock import Mock

    config = ConfigManager(tmp_path / "config.yml")
    config.set("youtube_browser", "chrome")
    config.set("chrome_mix_connection", False)
    player = MusicController(config)
    player.is_playing = True
    player.mpv_process = process = Mock()
    player.current_playlist = URL
    player.playback_state = "paused"
    reply = {
        "mix": "RDsJL3NuTkfRU",
        "tracks": [
            {"id": "sJL3NuTkfRU", "title": "Now"},
            {"id": "Ey6Fi6SjBR4", "title": "Next"},
            {"id": "Z_TcwONEOpg", "title": "Last"},
        ],
    }
    monkeypatch.setattr(
        chrome_connection, "read_chrome_queue", lambda watch, folder, **kwargs: reply
    )

    send = Mock()
    monkeypatch.setattr(player, "_send_mpv_command", send)
    player.connect_chrome_mix(URL, tmp_path)
    send.assert_not_called()
    assert player.mpv_process is process and player.playback_state == "paused"
    assert ConfigManager(config.config_path).get("chrome_mix_connection")
