#Requires -Version 5.1
<#
.SYNOPSIS
    SLACK AWS INTEGRATION — One-click Setup (Windows / PowerShell)
.DESCRIPTION
    Detects prerequisites, installs missing tools, generates secrets,
    creates .env from template, installs Python dependencies.
#>

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "SLACK AWS Integration — Setup"

function Write-Info  { Write-Host "[INFO]  $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN]  $args" -ForegroundColor Yellow }
function Write-Error { Write-Host "[ERROR] $args" -ForegroundColor Red }
function Write-Header { Write-Host "`n── $args ──`n" -ForegroundColor Cyan }

$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ProjectDir

$PythonRequired = "3.10"
$PipRequirements = "$ProjectDir\requirements.txt"
$EnvFile = "$ProjectDir\.env"
$EnvExample = "$ProjectDir\.env.example"

# ── Pre-flight ───────────────────────────────
Write-Header "Pre-flight Checks"

if ($PSVersionTable.PSEdition -ne "Desktop" -and $PSVersionTable.PSEdition -ne "Core") {
    Write-Warn "Unrecognized PowerShell edition. Proceeding anyway."
}

# ── Python ───────────────────────────────────
Write-Header "Python"

$python = $null
$pyVersion = $null

# Try common locations
$candidates = @(
    "python3", "python"
)
foreach ($cmd in $candidates) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $ver -match "(\d+)\.(\d+)") {
            $python = $cmd
            $pyVersion = $Matches[0]
            break
        }
    } catch {}
}

if (-not $python) {
    Write-Warn "Python $PythonRequired+ not found."
    Write-Warn "Install it from https://www.python.org/downloads/"
    Write-Warn "Ensure 'Add Python to PATH' is checked during installation."
    $choice = Read-Host "Press Enter after installing Python, or type 'skip' to continue without"
    if ($choice -eq "skip") {
        Write-Warn "Skipping Python check. Some steps will fail."
    } else {
        & python --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            $python = "python"
            $pyVersion = $(python --version 2>&1)
        }
    }
} else {
    Write-Info "Python $pyVersion detected."
}

# ── Docker (optional) ────────────────────────
Write-Header "Docker (optional)"

$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    $dv = & docker --version 2>&1
    Write-Info "Docker detected: $dv"
} else {
    Write-Warn "Docker not found — install from https://docs.docker.com/desktop/setup/install/windows-install/"
    Write-Info "Docker is optional (not required for Lambda deployment)."
}

$compose = Get-Command docker-compose -ErrorAction SilentlyContinue
if (-not $compose) {
    try { $null = & docker compose version 2>$null; $compose = $true } catch {}
}
if ($compose) {
    Write-Info "Docker Compose detected."
} else {
    Write-Warn "Docker Compose not found (optional)."
}

# ── Environment file ─────────────────────────
Write-Header "Environment Configuration"

if (Test-Path $EnvFile) {
    Write-Info ".env already exists — skipping generation."
    Write-Warn "Review $EnvFile and update credentials if needed."
} elseif (Test-Path $EnvExample) {
    Copy-Item $EnvExample $EnvFile
    Write-Info "Created .env from template."
} else {
    @"
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY_ID_HERE
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_ACCESS_KEY_HERE
SLACK_BOT_TOKEN=xoxb-YOUR-BOT-TOKEN-HERE
SLACK_SIGNING_SECRET=YOUR-SIGNING-SECRET-HERE
"@ | Set-Content -Path $EnvFile
    Write-Info "Created minimal .env."
}

Write-Host "`n  ACTION REQUIRED: Edit .env with your real credentials." -ForegroundColor Yellow
Write-Host "  - AWS credentials (or rely on IAM role / ~/.aws/credentials)"
Write-Host "  - Slack Bot Token (xoxb-...) with scopes: chat:write, files:read, channels:history"
Write-Host "  - Slack Signing Secret from https://api.slack.com/apps`n"

# ── Virtual Environment ──────────────────────
Write-Header "Python Virtual Environment"

$venvPath = "$ProjectDir\.venv"
if (Test-Path $venvPath) {
    Write-Info "Virtual environment already exists at .venv/"
} else {
    & $python -m venv $venvPath
    Write-Info "Created virtual environment at .venv/"
}

# Activate
$activateScript = "$venvPath\Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    . $activateScript
    Write-Info "Activated .venv"
} else {
    Write-Warn "Could not find activation script at $activateScript"
}

# ── Install Dependencies ─────────────────────
Write-Header "Installing Dependencies"

if (Test-Path $PipRequirements) {
    pip install --upgrade pip -q
    pip install -r $PipRequirements
    Write-Info "Dependencies installed from requirements.txt"
} else {
    pip install --upgrade pip -q
    pip install boto3 openpyxl python-dotenv slack_bolt requests
    Write-Info "No requirements.txt — installed core packages."
}

# ── Generate Secret Key ──────────────────────
Write-Header "Generating Secrets"

$secretKeyFile = "$ProjectDir\.secret_key"
if (-not (Test-Path $secretKeyFile)) {
    $key = -join ([char[]](48..57 + 65..90 + 97..122 + 45..45 + 95..95) | Get-Random -Count 43)
    Set-Content -Path $secretKeyFile -Value "$key`n"
    Write-Info "Generated cryptographic secret -> .secret_key"
} else {
    Write-Info "Secret key already exists at .secret_key"
}

# ── Summary ──────────────────────────────────
Write-Header "Setup Complete"

Write-Host ""
Write-Host "✔  SLACK AWS Integration is ready." -ForegroundColor Green
Write-Host ""

Write-Host "  Next Steps:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Activate the environment:"
Write-Host "     .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "  2. Edit credentials (if not done):"
Write-Host "     notepad .env"
Write-Host ""
Write-Host "  3. Run the CLI:"
Write-Host "     python main.py"
Write-Host ""
Write-Host "  4. Deploy the Slack Bot to Lambda:"
Write-Host "     pip install -r requirements.txt -t package/"
Write-Host "     copy app.py pricing_logic.py main.py package/"
Write-Host "     Compress-Archive -Path package\* -DestinationPath deployment.zip"
Write-Host "     aws lambda update-function-code --function-name YOUR_FUNCTION --zip-file fileb://deployment.zip"
Write-Host ""

Write-Host "  Project Structure:" -ForegroundColor Cyan
Write-Host "    app.py           - Slack bot Lambda handler"
Write-Host "    main.py          - Core EC2/RDS pricing logic"
Write-Host "    pricing_logic.py - Bridge between Slack and pricing logic"
Write-Host "    requirements.txt - Python dependencies"
Write-Host "    Jenkinsfile      - CI/CD pipeline for Lambda deployment"
Write-Host "    .env             - Your credentials (gitignored)"
Write-Host "    .secret_key      - Generated cryptographic key (gitignored)"
Write-Host ""
