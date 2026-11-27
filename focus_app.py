"""Windowed entry point for installed and packaged desktop applications."""

import os
import sys


def main() -> None:
    os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
    if sys.argv[1:] == ["--update-youtube"] and getattr(sys, "frozen", False):
        from src.system import update_bundled_extractor

        update_bundled_extractor()
        return
    if sys.argv[1:] == ["--daemon"]:
        from src.daemon import run_daemon

        run_daemon()
        return
    if sys.argv[1:] == ["--self-test"]:
        # Set the isolated home before importing src (which resolves runtime paths).
        import tempfile

        with tempfile.TemporaryDirectory() as home:
            os.environ["FOCUS_HOME"] = home
            from src.desktop_check import run

            try:
                run()
            except Exception:
                import traceback

                if report := os.environ.get("FOCUS_TEST_REPORT"):
                    with open(report, "w", encoding="utf-8") as details:
                        traceback.print_exc(file=details)
                else:
                    traceback.print_exc()
                raise SystemExit(1) from None
        return
    from main import UltimateFocusLauncher, _detach_gui_on_windows

    _detach_gui_on_windows()
    if not UltimateFocusLauncher.launch_gui():
        raise SystemExit(1)


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    main()
