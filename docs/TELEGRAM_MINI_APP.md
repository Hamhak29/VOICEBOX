# VOICEBOX in Telegram

This private Mini App reuses the existing Voicebox voice profiles, sample upload,
serial generation queue, history, and audio APIs. Desktop entrypoints are unchanged.
The deployment exposes only the small allowlisted API surface needed by the app.

## Railway

- Deploy the `telegram-mini-app` branch with Dockerfile path `Dockerfile.telegram`.
- Configure the service healthcheck as `/healthz` with a 300-second timeout.
  Railway's old `railway.json` Config as Code is deprecated; service settings are
  configured directly through Railway.
- Attach one persistent volume at `/app/data` (database, profiles, audio, HF cache).
- Run one replica and one Uvicorn worker. The engine uses SQLite and an in-process queue.
- Generate an HTTPS domain; the app is available at `/miniapp`.
- Set `TELEGRAM_APP_URL=https://YOUR-DOMAIN/miniapp`.
- Set `TELEGRAM_BOT_TOKEN` as a Railway secret variable, never in GitHub or frontend.
- With the token configured, `/id` returns the sender's numeric ID even before
  the allowlist is configured; it grants no access to studio data.
- Set `TELEGRAM_ALLOWED_USER_IDS` to the owner's numeric Telegram ID. Empty means closed.
- Use a dedicated bot with no existing webhook or other polling process.
- Send `/start` to the bot; it replies with the launch button and sets the private menu.
- Optionally configure the same URL as Main Mini App in BotFather for a profile launch button.

## Supported in this first release

- Qwen CustomVoice presets; Qwen Base voice cloning with a reference recording.
- Russian and the other nine Qwen languages; text up to 2000 characters per request.
- Qwen 0.6B only, downloaded on explicit first generation into the persistent cache.
- Audio playback, download, history, sending WAV as a document to the owner's bot chat.
- Signed Telegram initData (1 hour launch window), HttpOnly HTTPS session (24 hours),
  user allowlist, write-origin checks and restricted API routes.

The instance is one private studio. Additional allowlisted IDs share the same data;
do not open registration without implementing per-user ownership and quotas.
Railway has no GPU; CPU latency and peak memory must be measured before promising
interactive performance. No models are downloaded at boot. A GPU-backed external
worker is a possible later improvement if CPU inference is too slow.

## Checks

```bash
python -m unittest backend.tests.test_telegram_auth
node --check telegram/app.js
python -m compileall -q backend/telegram_app.py backend/telegram_bot.py
```

Manual acceptance after bot connection: unauthorized user denied; owner opens via
bot; add preset; generate a short Russian phrase; reopen history; play/download/send;
clone a permitted voice; redeploy and check profiles/history/cache persist. Test the
launch, audio playback and upload on actual Android and iOS Telegram clients.
