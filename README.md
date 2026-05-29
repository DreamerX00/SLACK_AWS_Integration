# AWS Cost Report By Type

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Fetches EC2 and RDS pricing from the **AWS Pricing API** and **Savings Plans API**, then generates a formatted Excel report comparing On-Demand, Reserved Instance, and Compute Savings Plan costs.

Two interfaces are available:
- **CLI** (`main.py`) — Interactive or seed-file-driven mode for local use.
- **Slack Bot** (`app.py`) — Deployed to AWS Lambda behind API Gateway. Users upload an `.xlsx` file to a Slack channel and receive the cost report back in the thread.

---

## Table of Contents

- [Pricing Models](#pricing-models)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Usage (CLI)](#usage-cli)
- [Slack Bot (Lambda)](#slack-bot-lambda)
- [IAM Policy](#iam-policy)
- [Security](#security)
- [License](#license)

---

## Pricing Models

| Service | Model                               | Source API        |
| ------- | ----------------------------------- | ----------------- |
| EC2     | On-Demand                           | Pricing API       |
| EC2     | Compute Savings Plan 1yr No Upfront | Savings Plans API |
| EC2     | Compute Savings Plan 3yr No Upfront | Savings Plans API |
| EC2     | Standard RI 1yr No Upfront          | Pricing API       |
| EC2     | Standard RI 3yr No Upfront          | Pricing API       |
| RDS     | On-Demand                           | Pricing API       |
| RDS     | Standard RI 1yr No Upfront          | Pricing API       |

---

## Project Structure

```
.
├── app.py                 # Slack bot Lambda handler (slack_bolt)
├── main.py                # Core pricing logic (Pricing / SP API calls)
├── pricing_logic.py       # Bridge: reads uploaded xlsx, calls main.py, writes report
├── requirements.txt       # Python dependencies
├── Jenkinsfile            # CI/CD pipeline for Lambda deployment
├── seed.json.example      # Example seed file for the --seed flag
├── .env.example           # Template for environment variables
├── .gitignore
└── README.md
```

---

## Prerequisites

- **Python 3.10+**
- **AWS credentials** with `pricing:GetProducts` and `savingsplans:DescribeSavingsPlansOfferingRates`
- For the **Slack Bot**: a Slack App with appropriate bot token scopes

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your AWS credentials (and Slack tokens if using the bot)
```

Environment variables (see [`.env.example`](.env.example)):

| Variable              | Required For       | Description                                    |
| --------------------- | ------------------ | ---------------------------------------------- |
| `AWS_ACCESS_KEY_ID`   | CLI                | AWS access key (optional if using IAM role)    |
| `AWS_SECRET_ACCESS_KEY`| CLI               | AWS secret key (optional if using IAM role)    |
| `SLACK_BOT_TOKEN`     | Slack Bot          | Slack Bot token (`xoxb-...`)                   |
| `SLACK_SIGNING_SECRET`| Slack Bot          | Slack App signing secret                       |

---

## Usage (CLI)

### Interactive mode

```bash
python main.py
```

Type comma-separated values at each prompt:

```
--- EC2 Input ---
Instance types: t3.micro,m5.large,c5.xlarge
Regions: us-east-1,eu-west-1
OS: Linux,Windows

--- RDS Input ---
Instance types: db.t3.micro,db.m5.large
Regions: us-east-1,eu-west-1
Engines: MySQL,PostgreSQL,MariaDB
```

### Seed file mode

```bash
cp seed.json.example seed.json
# Edit seed.json with your desired lists
python main.py --seed seed.json
```

The seed file supports both explicit row definitions and cross-product lists:

```json
{
    "ec2": {
        "instance_types": ["t3.micro", "m5.large"],
        "regions": ["us-east-1", "eu-west-1"],
        "os_list": ["Linux", "Windows"]
    },
    "rds": {
        "rows": [
            {"instance_type": "db.t3.micro", "region": "us-east-1", "engine": "MySQL"}
        ]
    }
}
```

### Output

Reports are saved as `aws_cost_report_<timestamp>.xlsx` with styled sheets, currency formatting, and N/A highlighting.

---

## Slack Bot (Lambda)

### Architecture

The Slack integration (`app.py`) runs on **AWS Lambda** behind **API Gateway**:

1. User uploads an `.xlsx` file to a Slack channel.
2. Slack sends a `message` event to the API Gateway endpoint.
3. Lambda acknowledges within 3 seconds (Lazy Listener pattern in `slack_bolt`).
4. Lambda downloads the file to `/tmp/`, validates it (`.xlsx` format, ≤50 rows), and calls `generate_cost_report`.
5. Once the report is generated, Lambda uploads the result back to the same Slack thread.

### Slack App Setup

1. Create a new app at https://api.slack.com/apps
2. Under **OAuth & Permissions**, add these Bot Token Scopes:
   - `chat:write` — post messages
   - `files:read` — read uploaded files
   - `channels:history` — read channel messages
3. Install the app to your workspace and copy the **Bot Token** (`xoxb-...`).
4. Under **App Credentials**, copy the **Signing Secret**.
5. Enable **Events** and subscribe to `message.channels` and `app_mention`.
6. Set the **Request URL** to your API Gateway endpoint (e.g. `https://abc123.execute-api.ap-south-1.amazonaws.com/prod/slack/events`).

### Lambda Deployment

```bash
# Package
pip install -r requirements.txt -t package/
cp app.py pricing_logic.py main.py package/
cd package && zip -r ../deployment.zip .
cd ..

# Upload to AWS
aws lambda update-function-code \
    --function-name SlackAwsCostCalculator \
    --zip-file fileb://deployment.zip \
    --region ap-south-1
```

| Setting               | Value                        |
| --------------------- | ---------------------------- |
| **Runtime**           | Python 3.13 (or 3.10+)       |
| **Handler**           | `app.lambda_handler`         |
| **Timeout**           | 5+ minutes (Pricing API)     |
| **Memory**            | 512 MB                       |
| **API Gateway**       | HTTP API, `POST /slack/events`|

### Input File Format

Upload an `.xlsx` file with one or both sheets:

**Sheet: `EC2`**

| instance_type | region     | os      |
|---------------|------------|---------|
| t3.micro      | us-east-1  | Linux   |
| m5.large      | eu-west-1  | Windows |
| r5.large      | ap-south-1 | RHEL    |

**Sheet: `RDS`**

| instance_type   | region     | engine     |
|-----------------|------------|------------|
| db.t3.micro     | us-east-1  | MySQL      |
| db.m5.large     | eu-west-1  | PostgreSQL |

**Row limit:** Maximum 50 rows across all sheets (Lambda timeout guard).

---

## IAM Policy

### CLI Usage

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "pricing:GetProducts",
                "savingsplans:DescribeSavingsPlansOfferingRates"
            ],
            "Resource": "*"
        }
    ]
}
```

### Lambda Execution Role

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "pricing:GetProducts",
                "savingsplans:DescribeSavingsPlansOfferingRates"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "*"
        }
    ]
}
```

---

## Security

- **Credentials:** Never commit `.env` or `seed.json` (actual data). They are gitignored by default. Use `.env.example` and `seed.json.example` as templates.
- **Slack tokens:** The bot token (`xoxb-...`) has `chat:write` and `files:read` scopes — restrict the Slack App to channels where it is needed.
- **Lambda IAM:** The execution role grants read-only access to Pricing and Savings Plans APIs plus CloudWatch Logs. Do not attach broader policies.
- **Jenkinsfile:** The CI/CD pipeline does not store secrets. Ensure the Jenkins agent has an IAM role with `lambda:UpdateFunctionCode` attached via instance profile.

---

## License

MIT
