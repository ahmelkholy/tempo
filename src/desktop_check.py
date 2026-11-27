"""Exercise the installed GUI and music player against a disposable app home."""

import os
from pathlib import Path
import time
import wave


def run():
    temp = os.environ["FOCUS_HOME"]
    from .chrome_setup import prepare_extension
    from .ui import FocusGUI

    gui = FocusGUI()
    try:
        gui.root.withdraw()
        gui.root.update_idletasks()
        player = gui.music
        if player.get_status()["state"] != "stopped":
            raise RuntimeError("Music started on launch")
        prepare_extension(gui.config)
        song = Path(temp) / "sample.wav"
        with wave.open(str(song), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", ""))
            audio.writeframes(bytes(8000 * 2 * 30))
        gui.config.set("mpv_extra_args", "--ao=null")
        if not player.start_music(str(song), volume=0):
            raise RuntimeError(player.last_error)
        deadline = time.monotonic() + 15
        while not (player.bookmark.get("track") and player.get_status()["duration"]):
            if player.playback_state == "error" or time.monotonic() >= deadline:
                raise RuntimeError(
                    player.last_error or "Packaged audio or IPC did not start"
                )
            time.sleep(0.05)
        player.pause_for_break()
        if player.playback_state != "paused":
            raise RuntimeError("Packaged player did not pause")
        player.finish_break()
        if player.playback_state != "playing":
            raise RuntimeError("Packaged player did not resume")
    finally:
        gui.on_closing()
