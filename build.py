"""Build a desktop distribution from program files and verified media helpers."""

import hashlib
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from src.__version__ import __version__

ROOT = Path(__file__).resolve().parent
NAME = "Ultimate Focus"
YTDLP = {
    "Darwin": (
        "yt-dlp_macos",
        "57654854886d0398a798895aadf5173e2749fbb5e249b9f3728022ab376e11fb",
    ),
    "Linux": (
        "yt-dlp_linux",
        "249ddb058234276bc449b9cd9492aad9f133bda5923c61a9e39983ae114ef17d",
    ),
    "Windows": (
        "yt-dlp.exe",
        "622ed48023cac1daa52a3bf3a6ac38f03514de214b5f0fa069389fd0f6d17e5c",
    ),
}
DENO = {
    ("Darwin", "arm64"): (
        "aarch64-apple-darwin",
        "9f0bf660393da2eaff044cdc7444cb08c73f235849b61d224d825a194ce7c98e",
    ),
    ("Darwin", "x86_64"): (
        "x86_64-apple-darwin",
        "4b2f5edd2639b7470f034238b321d7002d8dfb4726d8558f52c17afac370eb2c",
    ),
    ("Linux", "x86_64"): (
        "x86_64-unknown-linux-gnu",
        "e890975bc2549807bbcc0b584ffafda72cc7c93349dd99c80483dd784f6c4609",
    ),
    ("Windows", "x86_64"): (
        "x86_64-pc-windows-msvc",
        "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf",
    ),
}


def download(folder, repo, tag, name, digest):
    target = folder / name
    if (
        not target.exists()
        or hashlib.file_digest(target.open("rb"), "sha256").hexdigest() != digest
    ):
        with urllib.request.urlopen(
            f"https://github.com/{repo}/releases/download/{tag}/{name}", timeout=120
        ) as response, tempfile.NamedTemporaryFile(dir=folder, delete=False) as output:
            pending = Path(output.name)
            shutil.copyfileobj(response, output)
        try:
            with pending.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                    raise ValueError(f"Invalid SHA-256 for {name}")
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
    return target


def build():
    system = platform.system()
    arch = (
        platform.machine()
        .lower()
        .replace("amd64", "x86_64")
        .replace("aarch64", "arm64")
    )
    deno_platform, deno_hash = DENO[system, arch]
    work = ROOT / "build"
    downloads = work / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    yt = download(downloads, "yt-dlp/yt-dlp", "2026.11.23", *YTDLP[system])
    deno = download(
        downloads, "denoland/deno", "v2.9.8", f"deno-{deno_platform}.zip", deno_hash
    )
    dist = ROOT / "dist"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        NAME,
        "--distpath",
        str(dist),
        "--workpath",
        str(work / "freeze"),
        "--specpath",
        str(work),
        "--icon",
        str(ROOT / "files/icon.png"),
        "--exclude-module",
        "yt_dlp",
        "--collect-data",
        "googleapiclient",
        "--hidden-import",
        "src.daemon",
        "--collect-submodules",
        "plyer.platforms."
        + {"Darwin": "macosx", "Linux": "linux", "Windows": "win"}[system],
    ]
    for path in [
        ROOT / "src/focus_track.lua",
        *sorted((ROOT / "src/chrome_mix_extension").glob("*.js")),
        ROOT / "src/chrome_mix_extension/manifest.json",
        *sorted((ROOT / "src/radio_plugins").rglob("*.py")),
    ]:
        cmd += ["--add-data", f"{path}:{path.parent.relative_to(ROOT)}"]
    subprocess.run([*cmd, str(ROOT / "focus_app.py")], check=True, cwd=ROOT)
    bundle = dist / (NAME + ".app" if system == "Darwin" else NAME)
    helpers = bundle / ("Contents/Helpers" if system == "Darwin" else "player-tools")
    helpers.mkdir(exist_ok=True)
    suffix = ".exe" if system == "Windows" else ""
    helper = helpers / ("yt-dlp" + suffix)
    shutil.copyfile(yt, helper)
    helper.chmod(0o755)
    runtime = helpers / ("deno" + suffix)
    with zipfile.ZipFile(deno) as archive, archive.open(
        runtime.name
    ) as source, runtime.open("wb") as out:
        shutil.copyfileobj(source, out)
    runtime.chmod(0o755)
    notices = bundle / ("Contents/Resources" if system == "Darwin" else "")
    for file in ("LICENSE", "THIRD_PARTY.md"):
        shutil.copy2(ROOT / file, notices / file)
    stem = (
        "ultimate-focus-timer-"
        + __version__
        + "-"
        + {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}[system]
        + "-"
        + arch
    )
    if system == "Darwin":
        subprocess.run(["codesign", "--force", "--sign", "-", str(bundle)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", str(bundle)], check=True)
        subprocess.run(
            [
                "ditto",
                "-c",
                "-k",
                "--sequesterRsrc",
                "--keepParent",
                str(bundle),
                str(dist / (stem + ".zip")),
            ],
            check=True,
        )
    elif system == "Linux":
        with tarfile.open(dist / (stem + ".tar.gz"), "w:gz") as archive:
            archive.add(bundle, arcname=bundle.name)
    else:
        shutil.make_archive(str(dist / stem), "zip", dist, bundle.name)


if __name__ == "__main__":
    build()
