"""Configure the private bot and reply to /start without touching webhooks."""
import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)


async def run_bot(token: str, allowed: set[int], url: str):
    if not token or not allowed or not url.startswith("https://"):
        return
    async with httpx.AsyncClient(timeout=40) as client:
        async def call(method, payload):
            # Never log response URLs: Bot API URLs contain the token.
            response = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
            data = response.json()
            if not response.is_success or not data.get("ok"):
                raise RuntimeError(f"Telegram {method} failed")
            return data.get("result")
        try:
            webhook = await call("getWebhookInfo", {})
            if webhook.get("url"):
                logger.warning("Bot has a webhook; polling was not started. Use a dedicated bot.")
                return
            for uid in allowed:
                await call("setChatMenuButton", {"chat_id": uid, "menu_button": {"type": "web_app", "text": "VOICEBOX", "web_app": {"url": url}}})
            offset = None
            while True:
                try:
                    updates = await call("getUpdates", {"timeout": 25, "offset": offset, "allowed_updates": ["message"]})
                    for update in updates:
                        offset = update["update_id"] + 1
                        message = update.get("message", {})
                        sender = message.get("from", {}).get("id")
                        if sender in allowed and message.get("chat", {}).get("type") == "private" and message.get("text", "").split(" ")[0].split("@")[0] in {"/start", "/app"}:
                            await call("sendMessage", {"chat_id": sender, "text": "VOICEBOX — твоя личная голосовая студия. Открой приложение, чтобы озвучить текст, добавить голос и получить запись.", "reply_markup": {"inline_keyboard": [[{"text": "Открыть VOICEBOX", "web_app": {"url": url}}]]}})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Telegram polling temporarily unavailable")
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Telegram setup incomplete. Check token, allowlist, and bot permissions.")
