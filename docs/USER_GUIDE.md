# Using Tempo

[Download the latest release](https://github.com/ahmelkholy/tempo/releases/latest). Choose the Windows or Linux x86-64 archive, or the macOS archive for Apple Silicon or Intel. Extract the whole archive and open **Tempo**.

## Timer and tasks

Press **Start focus**, choose a break, or use **Custom…** for a different duration. Change the defaults and notifications in **Settings → Timer**. Choose **Settings → Appearance → Interface size** to resize text, controls, tasks, and popups together. Dragging the window edge changes the available space. Tempo remembers both preferences.

Type a task, choose how many focus sessions you expect it to take, and press **Enter** or **Add**. Check it off when finished. Select **Shortcuts** for keyboard controls or **More → Statistics** to see past sessions. Google Tasks is optional under **Settings → Tasks**.

## Music

Use **Choose music…** or **Change…** to open an audio file, playlist, or YouTube link. Tempo keeps your selection for the next launch. Press **Play** or start a focus session to listen. With the default settings, breaks pause and resume the same track.

For a personal YouTube Mix, paste the full radio link and choose **Options → YouTube → Chrome session**. The connection popup uses the YouTube account signed in to Chrome on this device. YouTube supplies the live queue and can change its order. The player can also use a public Mix.

## Run from source

Use Python 3.11 or later with Tk. Create a virtual environment with `python -m venv .venv`. Activate it with `.venv\Scripts\Activate.ps1` in Windows PowerShell or `source .venv/bin/activate` on macOS and Linux.

```sh
python -m pip install .
python main.py --gui
```

Source installations use mpv for audio and Deno for YouTube playback. The desktop archives include Deno and yt-dlp. [mpv installation](https://mpv.io/installation/) and [Deno installation](https://docs.deno.com/runtime/getting_started/installation/).

For the terminal timer, run `python main.py --console`. For the session dashboard, run `python main.py --dashboard`.
