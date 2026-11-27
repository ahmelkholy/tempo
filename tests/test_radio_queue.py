from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("yt_dlp")
from yt_dlp import YoutubeDL
from yt_dlp.extractor.youtube import YoutubeTabIE
from yt_dlp.utils import ExtractorError

from src.radio_plugins.focus.yt_dlp_plugins.extractor.focus_radio import FocusRadioIE

MIX = "RDsJL3NuTkfRU"
SEED = "sJL3NuTkfRU"
NEXT = "Ey6Fi6SjBR4"
URL = f"https://www.youtube.com/watch?v={SEED}&list={MIX}&start_radio=1"


def row(video, selected=False, mix=MIX):
    return {
        "playlistPanelVideoRenderer": {
            "videoId": video,
            "selected": selected,
            "navigationEndpoint": {
                "commandMetadata": {
                    "webCommandMetadata": {
                        "url": f"/watch?v={video}&list={mix}&index=3"
                    }
                }
            },
        }
    }


@pytest.fixture
def radio(monkeypatch):
    monkeypatch.setenv("FOCUS_MIX_ID", MIX)
    monkeypatch.setenv("FOCUS_MIX_ACCOUNT", "1")
    monkeypatch.setenv("FOCUS_MIX_FOLLOW", "1")
    with YoutubeDL({"quiet": True}, auto_init=False) as downloader:
        yield FocusRadioIE(downloader)


def extract(radio, rows, account, ytcfg=None, mix=MIX):
    return radio._extract_from_playlist(
        MIX,
        URL,
        {"responseContext": {"mainAppWebResponseContext": account}},
        {"playlistId": mix, "contents": rows},
        ytcfg or {},
    )["entries"]


def test_signed_watch_queue_starts_at_selection_and_follows_the_supplied_endpoint(
    radio,
):
    entries = extract(
        radio, [row(NEXT), row(SEED, True), row(NEXT), row(NEXT)], {"loggedOut": False}
    )
    assert [entry["id"] for entry in entries] == [SEED, NEXT, NEXT]
    assert "list=" not in entries[1]["url"]
    assert parse_qs(urlsplit(entries[-1]["url"]).query) == {
        "v": [NEXT],
        "list": [MIX],
        "index": ["3"],
    }


@pytest.mark.parametrize(
    "account,ytcfg",
    [({"loggedOut": True}, {"LOGGED_IN": True}), ({}, {}), ({}, {"LOGGED_IN": False})],
)
def test_missing_or_signed_out_session_rejects_radio(radio, account, ytcfg):
    with pytest.raises(ExtractorError, match="signed-out"):
        extract(radio, [row(SEED)], account, ytcfg)


def test_wrong_mix_or_missing_radio_is_rejected(radio, monkeypatch):
    with pytest.raises(ExtractorError, match="different radio"):
        extract(radio, [row(SEED)], {}, {"LOGGED_IN": True}, mix="RDdifferent")
    monkeypatch.setattr(
        YoutubeTabIE, "_real_extract", lambda self, url: {"_type": "url", "id": SEED}
    )
    with pytest.raises(ExtractorError, match="did not return"):
        radio._real_extract(URL)


def test_guest_and_fixed_page_follow_the_same_track_order(monkeypatch, radio):
    monkeypatch.delenv("FOCUS_MIX_ACCOUNT")
    monkeypatch.delenv("FOCUS_MIX_FOLLOW")
    entries = extract(radio, [row(SEED, True), row(NEXT)], {"loggedOut": True})
    assert [entry["id"] for entry in entries] == [SEED, NEXT]
    assert "list=" not in entries[-1]["url"]


def test_single_song_cannot_pass_as_a_mix(radio):
    from src.radio_plugins.focus.yt_dlp_plugins.chrome_connection import (
        ChromeMixError,
        checked_tracks,
    )

    with pytest.raises(ChromeMixError, match="mix"):
        checked_tracks({"mix": MIX, "tracks": [{"id": SEED}]}, URL)
    with pytest.raises(ExtractorError, match="only one song"):
        extract(radio, [row(SEED)], {"loggedOut": False})


def test_next_page_cannot_switch_to_another_mix(radio):
    entries = extract(
        radio, [row(SEED, True), row(NEXT, mix="RDother")], {"loggedOut": False}
    )
    assert parse_qs(urlsplit(entries[-1]["url"]).query) == {"v": [NEXT], "list": [MIX]}


def test_mix_overview_uses_youtubes_first_song_to_open_verified_watch_queue(
    radio, monkeypatch
):
    monkeypatch.setattr(
        YoutubeTabIE,
        "_real_extract",
        lambda self, url: {
            "_type": "playlist",
            "id": MIX,
            "entries": iter([{"id": SEED}]),
        },
    )
    result = radio._real_extract(f"https://www.youtube.com/playlist?list={MIX}")
    assert result["ie_key"] == radio.ie_key()
    assert parse_qs(urlsplit(result["url"]).query) == {"v": [SEED], "list": [MIX]}


def test_paired_chrome_returns_only_tracks_in_requested_personal_mix(
    radio, monkeypatch
):
    from src.radio_plugins.focus.yt_dlp_plugins import chrome_connection

    monkeypatch.setenv("FOCUS_MIX_CONNECTION", "test folder")
    answer = {
        "mix": MIX,
        "tracks": [
            {"id": SEED, "title": "First"},
            {
                "id": NEXT,
                "title": "Next",
                "link": f"/watch?v={NEXT}&list={MIX}&index=2",
            },
        ],
    }
    monkeypatch.setattr(
        chrome_connection, "read_chrome_queue", lambda url, folder: answer
    )
    entries = radio._real_extract(URL)["entries"]
    assert [item["title"] for item in entries] == ["First", "Next"]
    assert parse_qs(urlsplit(entries[-1]["url"]).query)["list"] == [MIX]
    answer["mix"] = "RDother"
    with pytest.raises(ExtractorError, match="connection: mix"):
        radio._real_extract(URL)


def test_public_session_uses_the_mix_page_even_with_an_old_chrome_environment(
    radio, monkeypatch
):
    monkeypatch.setenv("FOCUS_MIX_CONNECTION", "unused")
    radio._downloader.params["extractor_args"] = {"focusradio": {"session": ["public"]}}
    monkeypatch.setattr(
        YoutubeTabIE,
        "_real_extract",
        lambda self, url: self._extract_from_playlist(
            MIX,
            url,
            {},
            {"playlistId": MIX, "contents": [row(SEED, True), row(NEXT)]},
            {},
        ),
    )
    entries = radio._real_extract(URL)["entries"]
    assert [item["id"] for item in entries] == [SEED, NEXT]
