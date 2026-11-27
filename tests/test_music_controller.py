import io
import subprocess
import threading
import time

from src.core import ConfigManager
from src.system import MusicController


class FakeProcess:
    def __init__(self, pid, returncode=None):
        self.pid = pid
        self.returncode = returncode
        self.stdout = io.StringIO()
        self._done = threading.Event()
        if returncode is not None:
            self._done.set()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if timeout is None:
            self._done.wait()
        elif not self._done.wait(timeout):
            raise subprocess.TimeoutExpired("fake-mpv", timeout)

        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self._done.set()

    def kill(self):
        self.returncode = -9
        self._done.set()


def make_controller(monkeypatch, tmp_path):
    monkeypatch.setattr(MusicController, "_find_mpv_executable", lambda self: "mpv")
    monkeypatch.setattr(
        MusicController, "_test_mpv_executable", lambda self, path: True
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )
    config = ConfigManager(tmp_path / "config.yml")
    video = tmp_path / "song.wav"
    video.touch()
    config.set("classical_music_selected_playlist", str(video))
    controller = MusicController(config)
    controller.pid_file = tmp_path / "mpv.pid"
    return controller


def wait_for(condition, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_unexpected_mpv_exit_reports_error_without_restart(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path)
    processes = []

    def fake_popen(*args, **kwargs):
        process = FakeProcess(1000 + len(processes), returncode=1)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    assert controller.start_music()
    assert wait_for(lambda: controller.playback_state == "error")
    assert len(processes) == 1
    assert controller.is_playing is False
    assert controller.last_error


def test_music_stop_does_not_restart_mpv(monkeypatch, tmp_path):
    controller = make_controller(monkeypatch, tmp_path)
    processes = []

    def fake_popen(*args, **kwargs):
        process = FakeProcess(2000 + len(processes))
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    assert controller.start_music()
    controller.stop_music()

    assert wait_for(lambda: processes[0].returncode == -15)
    time.sleep(0.05)
    assert len(processes) == 1
    assert controller.is_playing is False
