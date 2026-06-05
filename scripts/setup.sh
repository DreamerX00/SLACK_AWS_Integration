#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# SLACK AWS INTEGRATION — One-click Setup (Linux)
# ──────────────────────────────────────────────

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
NC="\033[0m"

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
header(){ echo -e "\n${BOLD}${CYAN}── $* ──${NC}\n"; }

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

PYTHON_REQUIRED="3.10"
PIP_REQUIREMENTS="$PROJECT_DIR/requirements.txt"
ENV_FILE="$PROJECT_DIR/.env"
ENV_EXAMPLE="$PROJECT_DIR/.env.example"

# ── Pre-flight checks ────────────────────────
header "Pre-flight Checks"

if [ "$(uname)" != "Linux" ]; then
    warn "This script is optimized for Linux/Ubuntu."
    warn "Proceeding anyway — some commands may differ."
fi

# ── Python ────────────────────────────────────
header "Python"

install_python() {
    warn "Python $PYTHON_REQUIRED+ is required."
    if command -v apt-get &>/dev/null; then
        info "Installing python3, pip, venv via apt..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq python3 python3-pip python3-venv
    elif command -v yum &>/dev/null; then
        sudo yum install -y python3 python3-pip
    elif command -v brew &>/dev/null; then
        brew install python@3
    else
        error "No supported package manager found. Install Python $PYTHON_REQUIRED+ manually."
        exit 1
    fi
}

if command -v python3 &>/dev/null; then
    PY_VER="$(python3 --version 2>&1 | awk '{print $2}')"
    info "Python $PY_VER detected."
else
    install_python
    PY_VER="$(python3 --version 2>&1 | awk '{print $2}')"
fi

# Compare major.minor
PY_MAJOR="$(echo "$PY_VER" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VER" | cut -d. -f2)"
REQ_MAJOR="$(echo "$PYTHON_REQUIRED" | cut -d. -f1)"
REQ_MINOR="$(echo "$PYTHON_REQUIRED" | cut -d. -f2)"

if [ "$PY_MAJOR" -lt "$REQ_MAJOR" ] || { [ "$PY_MAJOR" -eq "$REQ_MAJOR" ] && [ "$PY_MINOR" -lt "$REQ_MINOR" ]; }; then
    error "Python $PYTHON_REQUIRED+ required (found $PY_VER)."
    exit 1
fi

# ── Docker (optional) ────────────────────────
header "Docker (optional)"

if command -v docker &>/dev/null; then
    info "Docker $(docker --version | awk '{print $3}' | tr -d ',') detected."
else
    warn "Docker not found — install it if you plan to containerize:"
    warn "  curl -fsSL https://get.docker.com | sudo sh"
    info "Skipping Docker setup (not required for Lambda deployment)."
fi

if command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
    info "Docker Compose detected."
else
    warn "Docker Compose not found (optional)."
fi

# ── Environment file ─────────────────────────
header "Environment Configuration"

if [ -f "$ENV_FILE" ]; then
    info ".env already exists — skipping generation."
    warn "Review $ENV_FILE and update credentials if needed."
else
    if [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        info "Created $ENV_FILE from template."
    else
        warn "No .env.example found; creating minimal .env"
        cat > "$ENV_FILE" <<- 'EOF'
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY_ID_HERE
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_ACCESS_KEY_HERE
SLACK_BOT_TOKEN=xoxb-YOUR-BOT-TOKEN-HERE
SLACK_SIGNING_SECRET=YOUR-SIGNING-SECRET-HERE
EOF
        info "Created minimal $ENV_FILE."
    fi
    echo ""
    info "${BOLD}ACTION REQUIRED:${NC} Edit $ENV_FILE and fill in your real credentials."
    echo ""
    info "  - AWS credentials (or rely on IAM role / ~/.aws/credentials)"
    info "  - Slack Bot Token (xoxb-...) with scopes: chat:write, files:read, channels:history"
    info "  - Slack Signing Secret from https://api.slack.com/apps"
fi

# ── Virtual Environment ──────────────────────
header "Python Virtual Environment"

if [ -d ".venv" ]; then
    info "Virtual environment already exists at .venv/"
else
    python3 -m venv .venv
    info "Created virtual environment at .venv/"
fi

source .venv/bin/activate
info "Activated .venv"

# ── Install Dependencies ─────────────────────
header "Installing Dependencies"

if [ -f "$PIP_REQUIREMENTS" ]; then
    pip install --upgrade pip -q
    pip install -r "$PIP_REQUIREMENTS"
    info "Dependencies installed from requirements.txt"
else
    pip install --upgrade pip -q
    pip install boto3 openpyxl python-dotenv slack_bolt requests
    info "No requirements.txt — installed core packages."
fi

# ── Generate Secret Key (for session signing etc.) ──
header "Generating Secrets"

if [ ! -f "$PROJECT_DIR/.secret_key" ]; then
    python3 -c "
import secrets, os
key = secrets.token_urlsafe(32)
os.makedirs(os.path.dirname('$PROJECT_DIR/.secret_key'), exist_ok=True)
with open('$PROJECT_DIR/.secret_key', 'w') as f:
    f.write(key + '\n')
" 2>/dev/null
    info "Generated cryptographic secret → .secret_key"
else
    info "Secret key already exists at .secret_key"
fi

# ── Summary ──────────────────────────────────
header "Setup Complete"

echo ""
info "${BOLD}${GREEN}✔  SLACK AWS Integration is ready.${NC}"
echo ""
echo -e "  ${BOLD}Next Steps:${NC}"
echo ""
echo "  1. Activate the environment:"
echo "     source .venv/bin/activate"
echo ""
echo "  2. Edit credentials (if not done):"
echo "     nano .env"
echo ""
echo "  3. Run the CLI:"
echo "     python main.py"
echo ""
echo "  4. Deploy the Slack Bot to Lambda:"
echo "     pip install -r requirements.txt -t package/"
echo "     cp app.py pricing_logic.py main.py package/"
echo "     cd package && zip -r ../deployment.zip ."
echo "     aws lambda update-function-code --function-name YOUR_FUNCTION --zip-file fileb://deployment.zip"
echo ""
echo -e "  ${BOLD}Project Structure:${NC}"
echo "    app.py           — Slack bot Lambda handler"
echo "    main.py          — Core EC2/RDS pricing logic"
echo "    pricing_logic.py — Bridge between Slack and pricing logic"
echo "    requirements.txt — Python dependencies"
echo "    Jenkinsfile      — CI/CD pipeline for Lambda deployment"
echo "    .env             — Your credentials (gitignored)"
echo "    .secret_key      — Generated cryptographic key (gitignored)"
echo ""
