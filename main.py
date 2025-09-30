# main.py
import os
import asyncio
import logging
import threading
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", "8000"))

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет, я бот-наставник Мнемоно. /status чтобы проверить цикл.")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Цикл не запущен (тестовый бот).")

def _start_polling_in_thread(app):
    """
    Blocking call run_polling() запускаем в отдельном потоке,
    чтобы не блокировать asyncio loop (и чтобы Render видел открытый порт).
    """
    try:
        app.run_polling()
    except Exception as e:
        logger.exception("Ошибка в polling-потоке: %s", e)

async def run_bot():
    if not BOT_TOKEN:
        logger.error("ERROR: BOT_TOKEN не задан в окружении.")
        return None

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))

    # Запускаем blocking polling в фоне (daemon thread)
    thread = threading.Thread(target=_start_polling_in_thread, args=(app,), daemon=True)
    thread.start()
    logger.info("Telegram polling запущен в фоне (thread).")
    return app

async def handle_root(request):
    return web.Response(text="ok")

async def main():
    # Стартуем бота (в фоне)
    await run_bot()

    # Запускаем лёгкий HTTP сервер на порт PORT (Render требует открытый порт)
    web_app = web.Application()
    web_app.add_routes([web.get('/', handle_root)])
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"HTTP сервер поднят на порту {PORT}")

    # Держим процесс живым
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(main())
