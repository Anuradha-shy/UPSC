import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from sqlalchemy import select

from config import BOT_TOKEN, WEBAPP_BASE_URL, PORT, BOT_NAME
from database import init_db, seed_sections, seed_courses, migrate_v2, async_session, Section, Course
from keyboards import get_line
from webapp_template import render_section_page
import user_handlers
import admin_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# aiogram 3.7+ requires parse_mode via DefaultBotProperties, not a direct kwarg.
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# Admin commands registered before the generic user fallback (which lives at
# the bottom of user_handlers' router) so they're never swallowed by it.
dp.include_router(admin_handlers.router)
dp.include_router(user_handlers.router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_sections()
    await seed_courses()
    await migrate_v2()  # idempotent — restructures an existing DB to the v2 home-screen layout

    if WEBAPP_BASE_URL:
        webhook_url = f"{WEBAPP_BASE_URL}/webhook"
        try:
            await bot.set_webhook(webhook_url, drop_pending_updates=True)
            logger.info(f"Webhook set to {webhook_url}")
        except Exception:
            # Don't let a bad/unresolvable WEBAPP_BASE_URL crash the whole
            # container — log it loudly and keep the web server (and health
            # check) alive so the deployment doesn't restart-loop.
            logger.exception(f"Failed to set webhook to '{webhook_url}' — check WEBAPP_BASE_URL")
    else:
        logger.warning("WEBAPP_BASE_URL not set and RAILWAY_PUBLIC_DOMAIN unavailable — webhook NOT configured yet.")

    yield

    await bot.delete_webhook()
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/")
async def health():
    return {"status": "ok", "bot": BOT_NAME}


@app.get("/webapp/section/{section_key}", response_class=HTMLResponse)
async def webapp_section(section_key: str):
    if section_key == "all":
        return render_section_page("all", "All Courses", get_line())
    async with async_session() as session:
        result = await session.execute(select(Section).where(Section.key == section_key))
        section = result.scalar_one_or_none()
    title = section.name if section else section_key.replace("_", " ").title()
    return render_section_page(section_key, title, get_line())


@app.get("/api/courses")
async def api_courses(section_key: str):
    async with async_session() as session:
        if section_key == "all":
            result = await session.execute(select(Course).where(Course.is_active == True))  # noqa: E712
            courses = result.scalars().all()
        else:
            result = await session.execute(select(Section).where(Section.key == section_key))
            section = result.scalar_one_or_none()
            if not section:
                return JSONResponse([])
            courses = [c for c in section.courses if c.is_active]

        payload = [
            {
                "id": c.id, "name": c.name, "faculty": c.faculty, "medium": c.medium,
                "notes": c.notes, "price": float(c.price) if c.price is not None else None,
            }
            for c in courses
        ]
    return JSONResponse(payload)


if __name__ == "__main__":
    # Pass the app object directly (not the "main:app" string) — using the
    # string form makes uvicorn re-import this file as a second module,
    # which re-runs all the router registration code and crashes with
    # "Router is already attached" the second time around.
    uvicorn.run(app, host="0.0.0.0", port=PORT)
