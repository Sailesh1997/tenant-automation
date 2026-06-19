import requests
from config import SLACK_WEBHOOK


def post_slack(message: str) -> None:
    """Post a message to the configured Slack webhook. Silent on failure."""
    if not SLACK_WEBHOOK:
        return
    try:
        requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=5)
    except Exception:
        pass
