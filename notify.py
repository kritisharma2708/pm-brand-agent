"""Send draft posts to Telegram."""

import aiohttp

import config

TELEGRAM_API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
MAX_MESSAGE_LENGTH = 4096


async def _send_message(text: str):
    """Send a single message via Telegram Bot API."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[WARN] Telegram not configured — skipping notification.")
        return

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                print(f"[ERROR] Telegram send failed ({resp.status}): {body}")


def _format_post(result: dict, index: int) -> str:
    """Format a single post result for Telegram."""
    score = result["review"].get("score", "?")
    passed = result["review"].get("passed", False)
    status = "Ready" if passed else "Needs review"
    platform = result["platform"].title()
    mode = result["content_mode"]
    post_id = result["post_id"]

    header = f"*{index}. {platform} — {mode}*\nScore: {score}/5 | {status} | ID: `{post_id}`"
    draft = result["final_draft"]

    suggestions = result["review"].get("suggestions", [])
    footer = f"\n_Suggestions: {'; '.join(suggestions)}_" if suggestions else ""

    return f"{header}\n\n{draft}{footer}"


async def send_drafts(results: list[dict], label: str = "Drafts"):
    """Send generated drafts to Telegram, one message per post."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[WARN] Telegram not configured — skipping notification.")
        return

    # Header message
    ready = sum(1 for r in results if r["review"].get("passed"))
    header = f"*{label}* — {len(results)} posts ({ready} ready)\n\nScore with:\n`python3 main.py score <id> --likes N --comments N --shares N --impressions N`"
    await _send_message(header)

    # One message per post (avoids hitting the 4096 char limit)
    for i, result in enumerate(results, 1):
        text = _format_post(result, i)
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH - 20] + "\n\n_(truncated)_"
        await _send_message(text)

    print(f"[OK] {len(results)} drafts sent to Telegram.")
