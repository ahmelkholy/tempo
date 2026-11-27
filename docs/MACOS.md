# Using Ultimate Focus on macOS

Install the Finder/Dock launcher from the checkout:

```sh
.venv/bin/python scripts/install_macos_app.py
open "$HOME/Applications/Ultimate Focus.app"
```

Keep this checkout and its virtual environment in place. Run the installer again
if you move them. Drag the app into the Dock for access while working in other
applications. The existing `focus gui` command also works from Terminal.

The window keeps the timer, today's tasks, and music together. Use **Music → Change…** to play a link or open a local audio file or playlist. Music continues when
you switch applications or minimize the window. Quitting the app stops it.
Settings and statistics are under **More**. No login service is installed.

Local music uses mpv. For YouTube, the player first looks for yt-dlp in the app’s Python environment. Finder launches can discover Homebrew tools in
`/opt/homebrew/bin` and `/usr/local/bin`. On macOS, each playback checks the
system proxy settings. If a configured localhost proxy is not listening, it
connects directly. Both yt-dlp and mpv use the same route. If playback fails
and the proxy route has changed, it retries once. Switching routes can interrupt
playback and restart the track; this is not a seamless handoff. Direct playback
still requires YouTube to be reachable on your network.

The status displays Connecting, Playing, Paused, or a connection error. Pausing
a session pauses the player in place; resuming continues the same track.
Player options follow the [mpv manual](https://mpv.io/manual/stable/).

This Mac's Tk 9.1 configuration disables the tray to avoid a known crash in the
existing integration. Use the Dock to return to the window. Global hotkeys are
opt-in on macOS. The native Tk runtime exceeds the project's 50 MB memory target
on this machine even with an empty window; the app is not yet within that target.

Use the **− / +** buttons beside the header to resize text and controls (65–150%).
**⌘−**, **⌘+**, and **⌘0** zoom out, zoom in, and reset to 100%; on Windows/Linux
use Ctrl instead. Zoom and window dimensions are saved separately.

The music card shows track time, buffering and pause state. Drag the timeline
to seek, release the volume slider to apply a level, or choose an audio device
under **Options → Audio output**. Player events drive the controls on macOS, Linux, and Windows.

The task header shows **NORMAL** or **INSERT**. Click **? keys**, use **More →
Keyboard shortcuts**, or press **? / F1** to see the full guide.

| Key (Normal mode) | Action |
| --- | --- |
| `i`, `a`, `t` | Enter a new task |
| `j` / `k`, Down / Up | Select next / previous task |
| `g` / `G` | Select first / last task |
| `e` / `x` | Edit / complete the selected task |
| `dd` | Delete the selected task |
| Enter / `s` | Start focus, using the selected incomplete task |
| Space / `p` | Pause / resume the timer |
| `b` / Shift+S | Start a short break / stop the timer |
| `m` / `w` | Play/pause music / open the tasks window |

In task entry, **Enter** saves and **Esc** cancels, returning to Normal mode.
Text fields retain their normal editing keys. Starting focus from the keyboard
does not replace a running or paused session. Delete requires a selected task.

If playback fails, a popup shows the reason. Choose **Open in browser** for an online link, **Choose music…** for a different source, or **Retry**. For YouTube, **Update YouTube helper and retry** updates yt-dlp on demand in the app’s Python 3.11+ virtual environment. Other installs link to the updater instructions. Adding a
new link or selecting another playlist starts that source immediately, including
after an earlier failure. Retry uses the saved current selection. An exact link
pasted twice is repaired; two different URLs in one field are rejected. Deleted
or private YouTube playlists must be replaced with an accessible source.

The text launcher accepts `q`, `quit`, `exit`, or `9` to close.

For your personal YouTube Mix, sign in to YouTube in Google Chrome and choose
**Music → Options → YouTube → Chrome session**. Press **Play** to load the current
Mix for that session. **Up next** shows the next title in YouTube’s order. With
repeat enabled, the player follows the next watch link YouTube supplies for the
same Mix. Reopening the app keeps the last song selected. Starting playback fetches
the live Mix at that song. YouTube can change the recommendations between sessions.

If Chrome is disconnected, **Play** loads the **Public YouTube Mix** for the same
link, starting at the selected song. **Next** and **Prev** follow that queue.
When you chose a personal Mix, a small timer popup checks your Chrome connection
once during public playback. You can also open it with **Connect my personal
Mix…**. An existing connection works automatically. When the player is idle, the
popup offers **Play my Mix**.

For a first-time installation, the popup offers **Set up in Chrome**. On the
Focus Timer Mix page in Chrome, click **Copy folder and open Extensions**. Turn on **Developer
mode**, click **Load unpacked**, press **⌘⇧G**, paste, press Return, and select the
folder. The setup page stays open and checks the Mix automatically.

Once connected, click **Use my Mix** to switch an active public Mix to your
account at the current song and position. The same connection works with the other Mix links you save under
**Change…**.

The connection opens a temporary local tab when the timer needs a new page of
recommendations. Chrome sends the ordered song IDs, titles, and Mix links. The
timer plays public audio streams with mpv and controls breaks and Next. Tracks that
require account access for the audio itself may still be unavailable. Keep the
extension enabled in the Chrome profile you use for YouTube. To disconnect, remove
**Focus Timer Mix** in Chrome and select **Play without sign-in** in the timer.
**Open Mix in Chrome** starts separate browser playback.

With `radio_refresh: false`, repeat loops the loaded page. Ordinary playlist
links, including watch links containing `list=PL…`, also load as playlists.

The YouTube session preference, selected radio, and GUI zoom are stored in
`config.yml` and apply through `focus gui` and the installed Mac application on
every launch. No helper launch script is needed. On reopen, the last song is selected. Press **Play** or start work to listen. With break pausing enabled, both short and long breaks pause the player and continue from the same timestamp when the break ends.

The app does not show a floating timer or raise its window when you switch
applications, minimise it, or finish a session. Restore it explicitly to interact.
