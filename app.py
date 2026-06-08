import os
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

import requests
from slack_bolt import App
from slack_bolt.adapter.aws_lambda import SlackRequestHandler

from pricing_logic import (
    generate_cost_report,
    inspect_input_workbook,
)

logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
    process_before_response=True,
)

MAX_ROWS = 50
ALLOWED_FILE_MIMETYPES = frozenset({
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})
SLACK_CDN_DOMAINS = frozenset({
    "files.slack.com",
    "slack-files.com",
})
IST = timezone(timedelta(hours=5, minutes=30))


class UserInputError(Exception):
    def __init__(self, slack_message: str, response_error: str | None = None):
        super().__init__(slack_message)
        self.slack_message = slack_message
        self.response_error = response_error or slack_message


def _is_slack_cdn_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.hostname in SLACK_CDN_DOMAINS and parsed.scheme == "https"
    except Exception:
        return False


def _ack_within_3s(body, ack):
    ack()


def _download_excel(file_url: str, input_path: str):
    logger.info("Downloading file")
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    response = requests.get(file_url, headers=headers, timeout=30)
    response.raise_for_status()

    # Slack returns an HTML login/error page (HTTP 200, text/html) instead of the
    # file bytes when the bot can't access the file — typically a missing
    # `files:read` scope, the bot not being in the channel, or a bad/expired token.
    # Detect that here so we surface an actionable error instead of writing the HTML
    # page to disk and failing later with a misleading "Invalid file format".
    content_type = response.headers.get("Content-Type", "")
    if content_type and content_type.split(";")[0].strip() not in ALLOWED_FILE_MIMETYPES:
        logger.warning(
            "Slack did not return an Excel file (Content-Type: %s). "
            "Check the bot's files:read scope and channel membership.",
            content_type,
        )
        raise UserInputError(
            "Could not download the file from Slack. The bot may lack permission "
            "to read it — ensure it has the `files:read` scope and is a member of "
            "the channel.",
            "Slack file download failed (check bot files:read scope & channel access)",
        )

    with open(input_path, "wb") as input_file:
        input_file.write(response.content)

    logger.info("Excel downloaded")


def _validate_workbook(input_path: str) -> dict[str, int]:
    try:
        workbook_metrics = inspect_input_workbook(input_path)
    except Exception as exc:
        raise UserInputError(
            "Invalid input file format. Ensure the file contains valid data.",
            "Invalid file format",
        ) from exc

    total_rows = workbook_metrics["total_rows"]

    if total_rows == 0:
        raise UserInputError("Uploaded file has no data rows.")

    if total_rows > MAX_ROWS:
        raise UserInputError(
            f"Row Limit Exceeded! Max {MAX_ROWS} rows allowed (got {total_rows})."
        )

    return {
        "ec2_count": workbook_metrics["ec2_count"],
        "rds_count": workbook_metrics["rds_count"],
    }


def _build_report_names() -> tuple[str, str]:
    now = datetime.now(IST)
    filename_ts = now.strftime("%Y%m%d_%H%M%S")
    title_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"aws_cost_report_{filename_ts}.xlsx",
        f"AWS Cost Report ({title_ts})",
    )


def _cleanup_temp_file(path: str):
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            logger.warning("Failed to delete temp file: %s", path)


def generate_and_upload_report(
    *,
    file_url: str,
    filename: str,
    channel: str,
    thread_ts: str,
    client,
    announce_start: bool = False,
) -> dict[str, int | str | bool]:
    if not filename.lower().endswith(".xlsx"):
        raise UserInputError(
            "Unsupported file format. Please upload an .xlsx file.",
            "Invalid file format",
        )

    if not _is_slack_cdn_url(file_url):
        logger.warning("Blocked download from non-Slack URL: %s", file_url)
        raise UserInputError(
            "Invalid file source. Please upload the file directly to Slack."
        )

    if announce_start:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Received your file! I'm checking the limits and calculating costs now...",
        )

    request_id = uuid4().hex
    input_path = f"/tmp/input_{request_id}.xlsx"
    output_path = f"/tmp/completed_report_{request_id}.xlsx"

    try:
        _download_excel(file_url, input_path)
        workbook_counts = _validate_workbook(input_path)

        logger.info("Generating report")
        try:
            generate_cost_report(input_path=input_path, output_path=output_path)
        except ValueError as exc:
            raise UserInputError(
                "Invalid input file format. Ensure the file contains valid data.",
                "Invalid file format",
            ) from exc

        report_filename, report_title = _build_report_names()

        logger.info("Uploading report")
        client.files_upload_v2(
            channel=channel,
            thread_ts=thread_ts,
            file=output_path,
            filename=report_filename,
            title=report_title,
            initial_comment="Cost report generated successfully!",
        )
        logger.info("Report uploaded successfully")

        return {
            "ok": True,
            "ec2_count": workbook_counts["ec2_count"],
            "rds_count": workbook_counts["rds_count"],
            "message": "Report generated successfully",
        }
    finally:
        _cleanup_temp_file(input_path)
        _cleanup_temp_file(output_path)


def _post_slack_error(client, channel: str, thread_ts: str, message: str):
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=message,
    )


def _handle_file_upload(body, client, logger):
    event = body.get("event", {})

    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    channel = event.get("channel")
    thread_ts = event.get("ts")
    files = event.get("files") or []

    if not files or not channel or not thread_ts:
        return

    file_info = files[0]
    file_url = file_info.get("url_private_download")
    filename = file_info.get("name", "")

    if not file_url:
        logger.warning(
            "Slack event missing file_url for channel=%s thread_ts=%s",
            channel,
            thread_ts,
        )
        return

    try:
        generate_and_upload_report(
            file_url=file_url,
            filename=filename,
            channel=channel,
            thread_ts=thread_ts,
            client=client,
            announce_start=True,
        )
    except UserInputError as exc:
        logger.warning("Slack file validation failed: %s", exc.slack_message)
        _post_slack_error(client, channel, thread_ts, exc.slack_message)
    except requests.RequestException:
        logger.exception("Failed to download file from Slack")
        _post_slack_error(
            client,
            channel,
            thread_ts,
            "Could not download the uploaded file. Please try again.",
        )
    except Exception:
        logger.exception("Failed to generate cost report")
        _post_slack_error(
            client,
            channel,
            thread_ts,
            "An error occurred while generating the report.",
        )


def _n8n_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        **body,
    }


def process_n8n_request(event):
    file_url = event.get("file_url")
    filename = event.get("file_name", "")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts")
    user_id = event.get("user_id")

    try:
        missing_fields = [
            field_name
            for field_name, field_value in (
                ("file_url", file_url),
                ("file_name", filename),
                ("channel", channel),
                ("thread_ts", thread_ts),
            )
            if not field_value
        ]
        if missing_fields:
            raise UserInputError(
                f"Missing required field(s): {', '.join(missing_fields)}",
                f"Missing required field(s): {', '.join(missing_fields)}",
            )

        logger.info(
            "Processing n8n request for user_id=%s channel=%s thread_ts=%s file_name=%s",
            user_id,
            channel,
            thread_ts,
            filename,
        )

        result = generate_and_upload_report(
            file_url=file_url,
            filename=filename,
            channel=channel,
            thread_ts=thread_ts,
            client=app.client,
        )
        return _n8n_response(200, result)
    except UserInputError as exc:
        logger.warning("n8n request validation failed: %s", exc.response_error)
        return _n8n_response(
            400,
            {
                "ok": False,
                "error": exc.response_error,
            },
        )
    except requests.RequestException as exc:
        logger.exception("n8n request download failed")
        return _n8n_response(
            500,
            {
                "ok": False,
                "error": str(exc),
            },
        )
    except Exception as exc:
        logger.exception("n8n request failed")
        return _n8n_response(
            500,
            {
                "ok": False,
                "error": str(exc),
            },
        )


app.event("app_mention")(ack=_ack_within_3s, lazy=[_handle_file_upload])
app.event("message")(ack=_ack_within_3s, lazy=[_handle_file_upload])


def lambda_handler(event, context):
    if "file_url" in event:
        logger.info("n8n invocation detected")
        return process_n8n_request(event)

    headers = event.get("headers", {}) or {}
    headers_lower = {k.lower(): v for k, v in headers.items()}
    if "x-slack-retry-num" in headers_lower:
        retry_num = headers_lower["x-slack-retry-num"]
        retry_reason = headers_lower.get("x-slack-retry-reason", "unknown")
        logger.info(
            "Received Slack retry (num: %s, reason: %s). Returning immediate 200 OK to prevent duplicate execution.",
            retry_num,
            retry_reason,
        )
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": '{"ok": true, "message": "Ignored retry"}',
        }

    slack_handler = SlackRequestHandler(app=app)
    return slack_handler.handle(event, context)
