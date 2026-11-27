#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Tempo Launcher Script for PowerShell
.DESCRIPTION
    This script activates the virtual environment and launches Tempo
    from anywhere on your system.
.PARAMETER Mode
    Launch mode: gui, console, dashboard, quick, break, stats, check, info, interactive
.PARAMETER Duration
    Duration in minutes for quick sessions
.EXAMPLE
    focus
    focus gui
    focus quick 25
    focus break 5
    focus stats
#>

param(
    [string]$Mode = "",
    [int]$Duration = 0
)

# Tempo installation path
$FOCUS_PATH = Split-Path -Parent $PSScriptRoot
$VENV_ACTIVATE = "$FOCUS_PATH\.venv\Scripts\Activate.ps1"
$MAIN_SCRIPT = "$FOCUS_PATH\main.py"

# Check if installation exists
if (-not (Test-Path $FOCUS_PATH)) {
    Write-Host "❌ Tempo not found at: $FOCUS_PATH" -ForegroundColor Red
    Write-Host "💡 Please ensure Tempo is properly installed." -ForegroundColor Yellow
    exit 1
}

# Check if virtual environment exists
if (-not (Test-Path $VENV_ACTIVATE)) {
    Write-Host "❌ Virtual environment not found at: $VENV_ACTIVATE" -ForegroundColor Red
    Write-Host "💡 Please run setup to create the virtual environment." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $MAIN_SCRIPT)) {
    Write-Host "❌ Main launcher not found at: $MAIN_SCRIPT" -ForegroundColor Red
    Write-Host "💡 Please verify the Tempo installation." -ForegroundColor Yellow
    exit 1
}

# Save current location
$originalLocation = Get-Location

try {
    # Change to Tempo directory
    Set-Location $FOCUS_PATH

    # Activate virtual environment
    & $VENV_ACTIVATE

    # Determine command based on parameters
    if ($Mode -eq "") {
        # No parameters - show interactive launcher
        python "$MAIN_SCRIPT"
    }
    elseif ($Mode -eq "bg" -or $Mode -eq "background") {
        # Launch in background (detached) - use python.exe with window, not pythonw
        Start-Process -FilePath "python" -ArgumentList "`"$MAIN_SCRIPT`"","--gui" -WorkingDirectory $FOCUS_PATH
        Write-Host "✅ Tempo started in background" -ForegroundColor Green
        return
    }
    elseif ($Mode -eq "gui") {
        python "$MAIN_SCRIPT" --gui
    }
    elseif ($Mode -eq "console") {
        python "$MAIN_SCRIPT" --console
    }
    elseif ($Mode -eq "dashboard") {
        python "$MAIN_SCRIPT" --dashboard
    }
    elseif ($Mode -eq "stats") {
        python "$MAIN_SCRIPT" --stats
    }
    elseif ($Mode -eq "quick") {
        if ($Duration -gt 0) {
            python "$MAIN_SCRIPT" --quick-session $Duration
        } else {
            python "$MAIN_SCRIPT" --quick-session 25  # Default 25 minutes
        }
    }
    elseif ($Mode -eq "break") {
        if ($Duration -gt 0) {
            python "$MAIN_SCRIPT" --quick-break $Duration
        } else {
            python "$MAIN_SCRIPT" --quick-break 5   # Default 5 minutes
        }
    }
    elseif ($Mode -eq "check") {
        python "$MAIN_SCRIPT" --check-deps
    }
    elseif ($Mode -eq "info") {
        python "$MAIN_SCRIPT" --sys-info
    }
    elseif ($Mode -eq "interactive") {
        python "$MAIN_SCRIPT" --interactive
    }
    elseif ($Mode.StartsWith('-')) {
        python "$MAIN_SCRIPT" @($Mode) @args
    }
    else {
        Write-Host "❌ Unknown mode: $Mode" -ForegroundColor Red
        Write-Host "📖 Available modes: gui, console, dashboard, quick [minutes], break [minutes], stats, check, info, interactive" -ForegroundColor Yellow
        Write-Host "📝 Examples:" -ForegroundColor Cyan
        Write-Host "   focus" -ForegroundColor White
        Write-Host "   focus gui" -ForegroundColor White
        Write-Host "   focus quick 25" -ForegroundColor White
        Write-Host "   focus break 5" -ForegroundColor White
        Write-Host "   focus stats" -ForegroundColor White
        Write-Host "" -ForegroundColor White
        Write-Host "👉 Forwarding arguments directly to main.py" -ForegroundColor Yellow
        $forwardArgs = @($Mode)
        if ($Duration -ne 0) { $forwardArgs += $Duration }
        if ($args.Count -gt 0) { $forwardArgs += $args }
        python "$MAIN_SCRIPT" @forwardArgs
    }
}
catch {
    Write-Host "❌ Error launching Tempo: $_" -ForegroundColor Red
}
finally {
    # Restore original location
    Set-Location $originalLocation
}

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
