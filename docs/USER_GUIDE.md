# 🎯 Ultimate Focus Timer - Complete Documentation

Welcome to the comprehensive documentation for Ultimate Focus Timer, a cross-platform productivity application built with Python.

## 📚 Table of Contents

1. **[Quick Start](#-quick-start)**
2. **[Installation Guide](#-installation-guide)**
3. **[User Interfaces](#-user-interfaces)**
4. **[Configuration](#-configuration)**
5. **[Music Integration](#-music-integration)**
6. **[Analytics & Insights](#-analytics--insights)**
7. **[Advanced Features](#-advanced-features)**
8. **[Troubleshooting](#-troubleshooting)**
9. **[Development](#-development)**

## 🚀 Quick Start

Choose your desktop archive and extract the whole folder. Double-click **Ultimate Focus** to start. [Download the latest release](https://github.com/ahmelkholy/ultimate-focus-timer/releases/latest).

| Computer | Archive suffix | Application |
| --- | --- | --- |
| Windows x86-64 | `windows-x86_64.zip` | `Ultimate Focus.exe` |
| Mac with Apple Silicon | `macos-arm64.zip` | `Ultimate Focus.app` |
| Mac with Intel | `macos-x86_64.zip` | `Ultimate Focus.app` |
| Linux x86-64 | `linux-x86_64.tar.gz` | `Ultimate Focus` |

The download includes the Python runtime and YouTube helpers. Press **Play** to use the music popup if mpv needs installing. Use **Music → Change…** to select a song, playlist, or Mix.

## 📦 Installation Guide

For a source installation, use Python 3.11 or later with Tk. From the checkout, create a virtual environment with `python -m venv .venv`. Activate the environment with `.venv\Scripts\Activate.ps1` in Windows PowerShell or `source .venv/bin/activate` on macOS and Linux. Then run the following commands.

```sh
python -m pip install .
python main.py --gui
```

Source installations use mpv for music and Deno for YouTube playback. [mpv installation](https://mpv.io/installation/) and [Deno installation](https://docs.deno.com/runtime/getting_started/installation/).

## 🖥️ User Interfaces

### Interactive Launcher (Default)

```bash
python main.py
```

### GUI Interface

```bash
python main.py --gui
```

### Console Interface

```bash
python main.py --console
```

### Analytics Dashboard

```bash
python main.py --dashboard
```

## ⚙️ Configuration

All settings are stored in `config.yml`:

```yaml
# Session Timings
work_mins: 25
short_break_mins: 5
long_break_mins: 15

# Music Settings
classical_music: true
classical_music_volume: 70
fade_music_transitions: true

# Interface Settings
dark_theme: true
accent_color: "#00ff00"
animated_transitions: true
```

## 🎵 Music Integration

The application supports multiple audio sources and provides seamless background music during focus sessions.

## 📊 Analytics & Insights

Comprehensive productivity tracking with visual charts and export capabilities.

## 🛠️ Troubleshooting

### Common Issues

For detailed troubleshooting, see the main documentation files.

## 🔧 Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

---

**Thank you for using Ultimate Focus Timer! 🎯**
