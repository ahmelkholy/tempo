"""Prepare the user-approved, locally installed Chrome Mix extension."""

import json
import secrets
from pathlib import Path

from .core import _atomic_write_text, _config_write_lock


def prepare_extension(config):
    folder = config.config_path.parent / "data" / "chrome-mix"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    templates = Path(__file__).with_name("chrome_mix_extension")
    pair = folder / "pairing.json"
    with _config_write_lock(pair):
        if not pair.exists():
            _atomic_write_text(pair, json.dumps(secrets.token_hex(32)))
        key = json.loads(pair.read_text(encoding="utf-8"))
        if not isinstance(key, str) or len(key) != 64:
            raise ValueError("The Chrome pairing file is damaged.")
        for name in ("mix.js", "connect.js", "manifest.json"):
            content = (templates / name).read_text(encoding="utf-8")
            dest = folder / name
            if not dest.exists() or dest.read_text(encoding="utf-8") != content:
                _atomic_write_text(dest, content)
    return folder


def connect_on_install(watch, folder):
    """Let the newly approved extension finish setup in its own Chrome profile."""
    import time
    from .radio_plugins.focus.yt_dlp_plugins.chrome_connection import (
        open_chrome,
        read_chrome_queue,
    )

    pending = folder / "connect.json"
    invitation = None
    setup_seconds = 15 * 60

    def open_setup(address, **kwargs):
        nonlocal invitation
        invitation = json.dumps(
            {"url": address, "expires": int(time.time()) + setup_seconds}
        )
        with _config_write_lock(pending):
            _atomic_write_text(pending, invitation)
        open_chrome(address)

    try:
        return read_chrome_queue(
            watch, folder, launch=open_setup, timeout=setup_seconds, interactive=True
        )
    finally:
        with _config_write_lock(pending):
            if pending.exists() and pending.read_text(encoding="utf-8") == invitation:
                pending.unlink()
