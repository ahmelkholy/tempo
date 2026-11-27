#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Tempo Alias Installation Script
.DESCRIPTION
    This script sets up global aliases for the Tempo application
    so you can run it from anywhere on your system.
.EXAMPLE
    .\install-alias.ps1
#>

Write-Host "🎯 Tempo - Global Alias Installation" -ForegroundColor Cyan
Write-Host "=" * 50 -ForegroundColor Gray

$FOCUS_PATH = Split-Path -Parent $PSScriptRoot
$SCRIPTS_PATH = "$FOCUS_PATH\scripts"

Write-Host "📁 Focus Path: $FOCUS_PATH" -ForegroundColor Gray
Write-Host "📁 Scripts Path: $SCRIPTS_PATH" -ForegroundColor Gray

# Ensure scripts directory exists
if (-not (Test-Path $SCRIPTS_PATH)) {
    New-Item -ItemType Directory -Path $SCRIPTS_PATH -Force | Out-Null
}

# Check if PowerShell profile exists, create if not
$profilePath = $PROFILE.CurrentUserCurrentHost  # This targets Microsoft.PowerShell_profile.ps1
$profileDir = Split-Path -Parent $profilePath

Write-Host "📄 Target Profile: $profilePath" -ForegroundColor Gray

if (-not (Test-Path $profileDir)) {
    Write-Host "📁 Creating PowerShell profile directory..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
}

if (-not (Test-Path $profilePath)) {
    Write-Host "📄 Creating Microsoft.PowerShell_profile.ps1..." -ForegroundColor Yellow
    New-Item -ItemType File -Path $profilePath -Force | Out-Null
}

# Function to show profile information
function Show-ProfileInfo {
    Write-Host "`n📋 PowerShell Profile Information:" -ForegroundColor Cyan
    Write-Host "   Target Profile: $($PROFILE.CurrentUserCurrentHost)" -ForegroundColor White
    Write-Host "   Profile Exists: $(Test-Path $PROFILE.CurrentUserCurrentHost)" -ForegroundColor White
    if (Test-Path $PROFILE.CurrentUserCurrentHost) {
        $size = (Get-Item $PROFILE.CurrentUserCurrentHost).Length
        Write-Host "   Profile Size: $size bytes" -ForegroundColor White
    }
}

# Function to add alias to PowerShell profile
function Add-FocusAlias {
    $aliasContent = @"

# Tempo Alias - Added by Tempo Installation Script
function focus {
    param(
        [string]`$Mode = "",
        [int]`$Duration = 0
    )
    & "$SCRIPTS_PATH\focus.ps1" `$Mode `$Duration
}

# Additional convenient shortcuts
function focus-quick { focus quick `$args[0] }
function focus-break { focus break `$args[0] }
function focus-gui { focus gui }
function focus-console { focus console }
function focus-dashboard { focus dashboard }
function focus-stats { focus stats }
"@

    $currentContent = ""
    if (Test-Path $profilePath) {
        $currentContent = Get-Content -Path $profilePath -Raw -ErrorAction SilentlyContinue
    }

    # Check if alias already exists
    if ($currentContent -like "*Tempo Alias*") {
        Write-Host "✅ Tempo alias already exists in Microsoft.PowerShell_profile.ps1" -ForegroundColor Green
        return
    }

    # Add alias to profile
    Add-Content -Path $profilePath -Value $aliasContent
    Write-Host "✅ Added Tempo alias to Microsoft.PowerShell_profile.ps1" -ForegroundColor Green
}

# Function to add to System PATH (for batch file)
function Add-ToSystemPath {
    $currentPath = [Environment]::GetEnvironmentVariable("PATH", [EnvironmentVariableTarget]::User)

    if ($currentPath -split ';' -contains $SCRIPTS_PATH) {
        Write-Host "✅ Scripts directory already in PATH" -ForegroundColor Green
        return
    }

    try {
        $newPath = "$currentPath;$SCRIPTS_PATH"
        [Environment]::SetEnvironmentVariable("PATH", $newPath, [EnvironmentVariableTarget]::User)
        Write-Host "✅ Added scripts directory to user PATH" -ForegroundColor Green
        Write-Host "   You may need to restart your terminal for PATH changes to take effect" -ForegroundColor Yellow
    }
    catch {
        Write-Host "⚠️  Could not modify PATH automatically" -ForegroundColor Yellow
        Write-Host "   Please manually add '$SCRIPTS_PATH' to your PATH environment variable" -ForegroundColor Yellow
    }
}

# Function to make scripts executable (for Git Bash)
function Set-ScriptPermissions {
    try {
        if (Get-Command chmod -ErrorAction SilentlyContinue) {
            chmod +x "$SCRIPTS_PATH\focus.sh"
            Write-Host "✅ Made focus.sh executable" -ForegroundColor Green
        }
    }
    catch {
        Write-Host "⚠️  Could not set execute permissions on focus.sh" -ForegroundColor Yellow
    }
}

# Main installation
try {
    Write-Host "🔧 Installing Tempo aliases..." -ForegroundColor Cyan

    # Show profile information
    Show-ProfileInfo

    # Add PowerShell alias
    Add-FocusAlias

    # Add to PATH for batch file access
    Add-ToSystemPath

    # Set permissions for shell scripts
    Set-ScriptPermissions

    Write-Host "`n🎉 Installation completed successfully!" -ForegroundColor Green
    Write-Host "`n📖 Usage Examples:" -ForegroundColor Cyan
    Write-Host "   focus                  # Interactive launcher" -ForegroundColor White
    Write-Host "   focus gui              # Launch GUI mode" -ForegroundColor White
    Write-Host "   focus quick 25         # 25-minute focus session" -ForegroundColor White
    Write-Host "   focus break 5          # 5-minute break" -ForegroundColor White
    Write-Host "   focus stats            # Show statistics" -ForegroundColor White
    Write-Host "   focus dashboard        # Open analytics dashboard" -ForegroundColor White

    Write-Host "`n🔄 Next Steps:" -ForegroundColor Yellow
    Write-Host "   1. Restart your PowerShell terminal" -ForegroundColor White
    Write-Host "   2. Type 'focus' from any directory" -ForegroundColor White
    Write-Host "   3. Enjoy your productivity sessions! 🚀" -ForegroundColor White

    # Test if we can run the alias immediately
    Write-Host "`n🧪 Testing alias..." -ForegroundColor Cyan
    & "$SCRIPTS_PATH\focus.ps1" "info"

}
catch {
    Write-Host "❌ Installation failed: $_" -ForegroundColor Red
    Write-Host "💡 Please run this script as Administrator if you encounter permission issues" -ForegroundColor Yellow
    exit 1
}

Write-Host "`n✨ Tempo is now globally accessible!" -ForegroundColor Green
