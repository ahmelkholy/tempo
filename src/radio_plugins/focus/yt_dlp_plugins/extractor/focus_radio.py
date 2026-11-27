"""Keep mpv on the watch-page queue returned by YouTube for this Mix."""

import os
from urllib.parse import parse_qs, urlencode, urlsplit

from yt_dlp.extractor.youtube import YoutubeTabIE
from yt_dlp.utils import ExtractorError


class FocusRadioIE(YoutubeTabIE):
    IE_NAME = "focus:mix"

    def _uses_account(self):
        default = ["chrome" if os.environ.get("FOCUS_MIX_ACCOUNT") else "public"]
        return self._configuration_arg("session", default) == ["chrome"]

    @classmethod
    def suitable(cls, url):
        mix_id = os.environ.get("FOCUS_MIX_ID")
        return bool(
            mix_id
            and parse_qs(urlsplit(url).query).get("list") == [mix_id]
            and super().suitable(url)
        )

    def _real_extract(self, url):
        connection = os.environ.get("FOCUS_MIX_CONNECTION")
        if connection and self._uses_account():
            from ..chrome_connection import (
                ChromeMixError,
                checked_tracks,
                read_chrome_queue,
            )

            try:
                watch = (
                    urlsplit(url)
                    ._replace(scheme="https", netloc="www.youtube.com", fragment="")
                    .geturl()
                )
                answer = read_chrome_queue(watch, connection)
            except ChromeMixError as exc:
                raise ExtractorError(
                    f"Focus Chrome connection: {exc}", expected=True
                ) from None
            try:
                tracks = checked_tracks(answer, url)
            except ChromeMixError as exc:
                raise ExtractorError(
                    f"Focus Chrome connection: {exc}", expected=True
                ) from None
            entries = [
                self.url_result(
                    "https://www.youtube.com/watch?v=" + track["id"],
                    ie="Youtube",
                    video_id=track["id"],
                    video_title=track.get("title") or "",
                )
                for track in tracks
            ]
            return self._ordered_mix(answer["mix"], entries, tracks[-1].get("link", ""))
        result = super()._real_extract(url)
        if result.pop("focus_watch_queue", False):
            return result
        # A saved Mix can open on a playlist overview with no selected video.
        if urlsplit(url).path == "/playlist" and result.get("id") == os.environ.get(
            "FOCUS_MIX_ID"
        ):
            first = next(iter(result.get("entries") or ()), {})
            if first.get("id"):
                watch = "https://www.youtube.com/watch?" + urlencode(
                    {"v": first["id"], "list": result["id"]}
                )
                return self.url_result(watch, ie=self.ie_key())
        raise ExtractorError(
            "Focus Mix: YouTube did not return the radio queue", expected=True
        )

    def _extract_from_playlist(self, item_id, url, data, playlist, ytcfg):
        mix_id = os.environ.get("FOCUS_MIX_ID")
        if playlist.get("playlistId") != mix_id:
            raise ExtractorError(
                "Focus Mix: YouTube returned a different radio", expected=True
            )
        account = data.get("responseContext", {}).get("mainAppWebResponseContext", {})
        signed_in = account.get("loggedOut") is False
        if "loggedOut" not in account:
            signed_in = (ytcfg or {}).get("LOGGED_IN") is True
        if self._uses_account() and not signed_in:
            raise ExtractorError(
                "Focus Mix: YouTube returned a signed-out queue", expected=True
            )

        rows = [
            r["playlistPanelVideoRenderer"]
            for r in playlist.get("contents", [])
            if r.get("playlistPanelVideoRenderer", {}).get("videoId")
        ]
        start = next((i for i, row in enumerate(rows) if row.get("selected")), None)
        seed = parse_qs(urlsplit(url).query).get("v", [None])[0]
        if start is None:
            start = next((i for i, row in enumerate(rows) if row["videoId"] == seed), 0)
        rows = rows[start : start + 50]
        if not rows or (seed and rows[0]["videoId"] != seed):
            raise ExtractorError(
                "Focus Mix: YouTube changed the selected track", expected=True
            )

        entries = [self._extract_video(row) for row in rows]
        endpoint = rows[-1].get("navigationEndpoint", {})
        link = (
            endpoint.get("commandMetadata", {})
            .get("webCommandMetadata", {})
            .get("url", "")
        )
        return self._ordered_mix(mix_id, entries, link, playlist.get("title"))

    def _ordered_mix(self, mix_id, entries, link, title=None):
        if len(entries) < 2:
            raise ExtractorError(
                "Focus Mix: YouTube returned only one song for this radio",
                expected=True,
            )
        if os.environ.get("FOCUS_MIX_FOLLOW"):
            # Expand the final unplayed song at its position in the same Mix.
            from ..chrome_connection import continuation_url

            entries[-1]["url"] = continuation_url(mix_id, entries[-1]["id"], link)
            entries[-1]["ie_key"] = self.ie_key()
        return self.playlist_result(
            entries,
            playlist_id=mix_id,
            playlist_title=title,
            focus_watch_queue=True,
        )
