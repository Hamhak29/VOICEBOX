"""Private Telegram Mini App, reusing Voicebox's profiles and generation engine."""
import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .telegram_auth import make_session, read_session, validate_init_data

STATIC = Path(__file__).resolve().parent.parent / "telegram"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED = {int(uid.strip()) for uid in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if uid.strip()}
MODELS = {"qwen-tts-0.6B", "qwen-custom-voice-0.6B"}
PUBLIC = {"/", "/miniapp", "/healthz", "/telegram/session", "/telegram/config"}
SAFE_ROUTES = [
    ("GET", r"/profiles"), ("POST", r"/profiles"),
    ("POST", r"/profiles/[\w-]+/samples"),
    ("GET", r"/history"), ("GET", r"/history/[\w-]+"),
    ("GET", r"/audio/[\w-]+"),
    ("POST", r"/generate"), ("POST", r"/generate/[\w-]+/cancel"),
    ("GET", r"/models/status"), ("POST", r"/models/download"),
    ("POST", r"/telegram/send/[\w-]+"),
]


@asynccontextmanager
async def lifespan(app):
    from . import config, database
    config.set_data_dir(os.environ.get("VOICEBOX_DATA_DIR", "/app/data"))
    database.init_db()
    from sqlalchemy import text
    with database.session.SessionLocal() as db:
        db.execute(text("UPDATE generations SET status='failed', error='Server restarted' WHERE status IN ('generating','loading_model')"))
        db.commit()
    from .services import task_queue
    task_queue.init_queue()
    from .utils.progress import get_progress_manager
    get_progress_manager()._set_main_loop(asyncio.get_running_loop())
    from .telegram_bot import run_bot
    bot_task = asyncio.create_task(run_bot(TOKEN, ALLOWED, os.environ.get("TELEGRAM_APP_URL", "")))
    yield
    bot_task.cancel()
    if task_queue._generation_worker_task:
        task_queue._generation_worker_task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def private_api(request: Request, call_next):
    path = request.url.path
    if path not in PUBLIC and not path.startswith("/miniapp-static/"):
        if not TOKEN or not ALLOWED:
            return JSONResponse({"detail": "Подключение Telegram ещё не завершено."}, status_code=503)
        try:
            authorization = request.headers.get("authorization", "")
            session = authorization[7:] if authorization.startswith("Bearer ") else request.cookies.get("voicebox_session", "")
            request.state.telegram_user_id = read_session(session, TOKEN, ALLOWED)
        except (ValueError, PermissionError):
            return JSONResponse({"detail": "Открой приложение через своего Telegram-бота."}, status_code=401)
        if not any(request.method == method and re.fullmatch(pattern, path) for method, pattern in SAFE_ROUTES):
            return JSONResponse({"detail": "Endpoint unavailable in Mini App"}, status_code=404)
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            from urllib.parse import urlsplit
            expected = urlsplit(os.environ.get("TELEGRAM_APP_URL", str(request.base_url)))
            if not origin or urlsplit(origin).netloc != expected.netloc:
                return JSONResponse({"detail": "Invalid request origin"}, status_code=403)
        if path in {"/generate", "/models/download", "/profiles"} and request.method == "POST":
            try:
                data = await request.json()
            except (ValueError, UnicodeDecodeError):
                return JSONResponse({"detail": "Invalid JSON"}, status_code=400)
            if not isinstance(data, dict) or (path == "/generate" and not isinstance(data.get("text"), str)):
                return JSONResponse({"detail": "Invalid request"}, status_code=400)
            if path == "/generate" and (data.get("engine") not in {"qwen", "qwen_custom_voice"} or data.get("model_size") != "0.6B" or len(data.get("text", "")) > 2000 or data.get("personality")):
                return JSONResponse({"detail": "Допустимы Qwen 0.6B и текст до 2000 символов."}, status_code=400)
            if path == "/models/download" and data.get("model_name") not in MODELS:
                return JSONResponse({"detail": "Model unavailable"}, status_code=400)
            if path == "/profiles" and (data.get("voice_type") not in {"cloned", "preset"} or data.get("default_engine") not in {"qwen", "qwen_custom_voice"} or data.get("preset_engine") not in {None, "qwen_custom_voice"}):
                return JSONResponse({"detail": "Unsupported profile"}, status_code=400)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if path not in {"/", "/miniapp"} and not path.startswith("/miniapp-static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class Login(BaseModel):
    init_data: str = Field(max_length=16384)


@app.post("/telegram/session")
async def login(data: Login):
    if not TOKEN or not ALLOWED:
        raise HTTPException(503, "Подключение Telegram ещё не завершено.")
    try:
        user = validate_init_data(data.init_data, TOKEN, ALLOWED)
    except PermissionError:
        raise HTTPException(403, "Это личное приложение. Доступ закрыт.")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "Открой приложение через Telegram заново.")
    session = make_session(user["id"], TOKEN)
    response = JSONResponse({"user": {"id": user["id"], "first_name": user.get("first_name", "")}, "access_token": session})
    response.set_cookie("voicebox_session", session, max_age=86400, httponly=True, secure=True, samesite="strict")
    return response


@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.get("/telegram/config")
async def public_config():
    return {"configured": bool(TOKEN and ALLOWED)}


@app.get("/")
@app.get("/miniapp")
async def index():
    return FileResponse(STATIC / "index.html")


@app.post("/telegram/send/{generation_id}")
async def send_audio(generation_id: str, request: Request):
    from . import config, database
    from .database import Generation
    with database.session.SessionLocal() as db:
        gen = db.query(Generation).filter_by(id=generation_id).first()
        if not gen or gen.status != "completed":
            raise HTTPException(404, "Готовая запись не найдена.")
        path = config.resolve_storage_path(gen.audio_path)
        if not path or not path.is_file() or not path.is_relative_to(config.get_data_dir()):
            raise HTTPException(404, "Аудиофайл не найден.")
        if path.stat().st_size > 49 * 1024 * 1024:
            raise HTTPException(413, "Файл слишком большой для Telegram.")
        async with httpx.AsyncClient(timeout=120) as client:
            with path.open("rb") as audio:
                result = await client.post(f"https://api.telegram.org/bot{TOKEN}/sendDocument", data={"chat_id": str(request.state.telegram_user_id), "caption": "VOICEBOX · готовая озвучка"}, files={"document": ("voicebox.wav", audio, "audio/wav")})
        if not result.is_success or not result.json().get("ok"):
            raise HTTPException(502, "Не удалось отправить. Сначала нажми /start в боте.")
    return {"sent": True}


# The private deployment exposes only the original core voice APIs.
from .routes import profiles, generations, history, audio, models
for module in (profiles, generations, history, audio, models):
    app.include_router(module.router)
app.mount("/miniapp-static", StaticFiles(directory=STATIC), name="miniapp-static")
