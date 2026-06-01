import os
import logging

import requests
import pandas as pd
from slack_bolt import App
from slack_bolt.adapter.aws_lambda import SlackRequestHandler

from pricing_logic import generate_cost_report

logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
    process_before_response=True,
)

MAX_ROWS = 50


def _ack_within_3s(body, ack):
    ack()


def _handle_file_upload(body, client, logger):
    event = body.get("event", {})

    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    channel = event.get("channel")
    ts = event.get("ts")
    files = event.get("files") or []

    if not files:
        return

    file_info = files[0]
    file_url = file_info.get("url_private_download")
    filename = file_info.get("name", "")

    if not file_url:
        return

    if not filename.lower().endswith(".xlsx"):
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text="❌ Unsupported file format. Please upload a *.xlsx* file.",
        )
        return

    client.chat_postMessage(
        channel=channel,
        thread_ts=ts,
        text="Received your file! I'm checking the limits and calculating costs now... ⏳",
    )

    input_path = "/tmp/input.xlsx"
    output_path = "/tmp/completed_report.xlsx"

    try:
        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
        resp = requests.get(file_url, headers=headers, timeout=30)
        resp.raise_for_status()

        with open(input_path, "wb") as f:
            f.write(resp.content)

        sheets = pd.read_excel(input_path, sheet_name=None)
        total_rows = sum(len(df) for df in sheets.values())

        if total_rows == 0:
            client.chat_postMessage(
                channel=channel,
                thread_ts=ts,
                text="❌ Uploaded file has no data rows.",
            )
            return

        if total_rows > MAX_ROWS:
            client.chat_postMessage(
                channel=channel,
                thread_ts=ts,
                text=f"🚨 Row Limit Exceeded! Max {MAX_ROWS} rows allowed (got {total_rows}).",
            )
            return

        generate_cost_report(input_path=input_path, output_path=output_path)

        from datetime import datetime, timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(ist)
        filename_ts = now.strftime("%Y%m%d_%H%M%S")
        title_ts = now.strftime("%Y-%m-%d %H:%M:%S")
        
        report_filename = f"aws_cost_report_{filename_ts}.xlsx"
        report_title = f"AWS Cost Report ({title_ts})"

        client.files_upload_v2(
            channel=channel,
            thread_ts=ts,
            file=output_path,
            filename=report_filename,
            title=report_title,
            initial_comment="✅ Cost report generated successfully!",
        )
    except ValueError as e:
        logger.warning("Bad input file: %s", e)
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f"❌ Invalid input file: {e}",
        )
    except requests.RequestException as e:
        logger.exception("Failed to download file from Slack")
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f"❌ Could not download the uploaded file: {e}",
        )
    except Exception as e:
        logger.exception("Failed to generate cost report")
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text=f"❌ An error occurred while generating the report: {e}",
        )


app.event("app_mention")(ack=_ack_within_3s, lazy=[_handle_file_upload])
app.event("message")(ack=_ack_within_3s, lazy=[_handle_file_upload])

def lambda_handler(event, context):
    slack_handler = SlackRequestHandler(app=app)
    return slack_handler.handle(event, context)
