"""A short-lived, loopback-only exchange for one page of a Chrome Mix."""

import json
import secrets
import re
import subprocess
import sys
import time
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit


class ChromeMixError(Exception):
    pass


def checked_tracks(answer, watch):
    query = parse_qs(urlsplit(watch).query)
    rows = answer.get("tracks")
    if (
        query.get("list") != [answer.get("mix")]
        or not isinstance(rows, list)
        or not 2 <= len(rows) <= 50
    ):
        raise ChromeMixError("mix")
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{11}", row["id"])
        ):
            raise ChromeMixError("format")
    if query.get("v") and query["v"] != [rows[0]["id"]]:
        raise ChromeMixError("mix")
    return rows


def continuation_url(mix, video, link):
    target = urlsplit(
        urljoin("https://www.youtube.com", link if isinstance(link, str) else "")
    )
    query = parse_qs(target.query)
    if (
        target.scheme == "https"
        and target.netloc == "www.youtube.com"
        and target.path == "/watch"
        and query.get("list") == [mix]
        and query.get("v") == [video]
    ):
        return target.geturl()
    return "https://www.youtube.com/watch?" + urlencode({"v": video, "list": mix})


def open_chrome(url, *, background=False):
    if sys.platform == "darwin":
        command = ["/usr/bin/open"]
        if url == "chrome://extensions/":
            # Launch Services can acknowledge an internal URL without showing a tab.
            script = """tell application "Google Chrome"
                if (count of windows) = 0 then make new window
                set w to front window
                if URL of active tab of w does not start with "chrome://extensions" then
                    make new tab at end of tabs of w with properties {URL:"chrome://extensions/"}
                    set active tab index of w to count of tabs of w
                end if
                set minimized of w to false
                activate
            end tell"""
            try:
                if (
                    subprocess.run(
                        ["/usr/bin/osascript", "-e", script],
                        capture_output=True,
                        timeout=8,
                    ).returncode
                    == 0
                ):
                    return
            except (OSError, subprocess.TimeoutExpired):
                pass
            command += ["-n", "-b", "com.google.Chrome", "--args", "--new-window"]
        else:
            command += (["-g"] if background else []) + ["-b", "com.google.Chrome"]
    elif sys.platform == "win32":
        import winreg

        key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                command = [winreg.QueryValue(hive, key)]
                break
            except OSError:
                continue
        else:
            raise FileNotFoundError("Chrome is unavailable")
    else:
        import shutil

        command = [shutil.which("google-chrome") or "google-chrome-stable"]
    subprocess.Popen(
        [*command, url],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_chrome_queue(url, folder, *, launch=None, timeout=28, interactive=False):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    try:
        pair = json.loads((Path(folder) / "pairing.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ChromeMixError("pairing") from None
    if not isinstance(pair, str) or len(pair) != 64:
        raise ChromeMixError("pairing")
    path = "/focus-mix/" + secrets.token_hex(16)
    request = escape(json.dumps({"url": url, "pair": pair}), quote=True)
    nonce = secrets.token_hex(16)
    instructions = ""
    if interactive:
        instructions = f"""<section hidden><h2>Connect this Chrome profile</h2>
<button id="copy">Copy folder and open Extensions</button>
<ol><li>On the Extensions page, turn on <b>Developer mode</b> and click <b>Load unpacked</b>.
<li>{"Press <b>⌘⇧G</b>, paste the path, then press Return and click <b>Select</b>." if sys.platform == "darwin" else "Paste the folder path into the folder chooser and select it."}
<br><code id="folder">{escape(str(folder))}</code></ol>
<p>Tempo checks your Mix automatically when you select the folder.</p></section>"""
    close_tab = "" if interactive else "window.close();"
    # A single timeout lets an uninstalled/disabled extension report back promptly.
    page = f"""<!doctype html><html lang="en" data-manual="{int(interactive)}"><meta charset="utf-8"><title>Tempo Mix</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style nonce="{nonce}">:root{{color-scheme:light dark;font:17px/1.5 system-ui}}body{{max-width:38rem;margin:10vh auto;padding:1rem}}li{{margin:.8rem 0}}code{{overflow-wrap:anywhere}}button{{font:inherit}}</style>
<meta name="focus-mix" content="{request}"><h1>Tempo Mix</h1><p>Checking your connection to YouTube…</p>{instructions}
<script nonce="{nonce}">document.querySelector("#copy")?.addEventListener("click", async e => {{
  try {{await navigator.clipboard.writeText(document.querySelector("#folder").textContent);}} catch {{}}
  try {{
    const res=await fetch(location.pathname, {{method:"POST",headers:{{"Content-Type":"application/json"}},body:'{{"open_extensions":true}}'}});
    if (!res.ok) throw Error();
  }} catch {{document.querySelector("p").textContent="The timer closed this check. Type chrome://extensions in Chrome’s address bar to finish the steps below, then choose Connect Chrome in the timer.";}}
}});
if (document.documentElement.dataset.manual === "1") {{
  new BroadcastChannel(location.pathname).onmessage = e => {{
    document.querySelector("p").textContent = e.data;
    document.querySelector("section").hidden = true;
  }};
}}</script>
<script nonce="{nonce}">window.addEventListener("load", () => setTimeout(async () => {{
  if (document.documentElement.dataset.focusConnected) return;
  document.querySelector("p").textContent = "Tempo Mix hasn’t connected in this Chrome profile.";
  const steps = document.querySelector("section"); if (steps) {{steps.hidden=false;return;}}
  await fetch(location.pathname, {{method:"POST",headers:{{"Content-Type":"application/json"}},body:'{{"error":"extension"}}'}}).catch(() => {{}});
  {close_tab}
}}, 2000));</script></html>""".encode()
    answer = None

    class Handler(BaseHTTPRequestHandler):
        timeout = 3

        def log_message(self, *args):
            pass

        def valid(self):
            return self.path == path and self.headers.get("Host") == host

        def do_GET(self):
            if not self.valid():
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            nonlocal answer
            allowed = self.valid() and self.headers.get("Origin") == origin
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 131072:
                    raise ValueError
                # Consume the bounded body before replying. Closing with unread data
                # can reset a Windows loopback connection before its response arrives.
                body = self.rfile.read(length)
                if not allowed:
                    return self.send_error(403)
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError
            except (ValueError, OSError):
                return self.send_error(400 if allowed else 403)
            if interactive and result.get("open_extensions") is True:
                try:
                    open_chrome("chrome://extensions/")
                except OSError:
                    return self.send_error(503)
            else:
                answer = result
            self.send_response(204)
            self.end_headers()

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        host = f"127.0.0.1:{server.server_port}"
        origin = f"http://{host}"
        try:
            (launch or open_chrome)(origin + path, background=not interactive)
        except OSError:
            raise ChromeMixError("extension") from None
        deadline = time.monotonic() + timeout
        while answer is None:
            server.timeout = deadline - time.monotonic()
            if server.timeout <= 0:
                raise ChromeMixError("timeout")
            server.handle_request()
    if "error" in answer:
        code = answer["error"]
        raise ChromeMixError(
            code
            if code in ("extension", "pairing", "signin", "network", "format", "mix")
            else "format"
        )
    return answer
