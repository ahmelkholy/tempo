$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install . "pyinstaller>=6.11"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python build.py
exit $LASTEXITCODE
