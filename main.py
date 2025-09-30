# main.py
import os
import asyncio
import logging
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", "8000"))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет, я бот-наставник Мнемоно. /status чтобы проверить цикл.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Цикл не запущен (тестовый бот).")

async def run_bot():
    if not BOT_TOKEN:
        logger.error("ERROR: BOT_TOKEN не задан в окружении.")
        return None
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))

    # Инициализируем и запускаем polling в фоне
    await app.initialize()
    asyncio.create_task(app.start_polling())
    logger.info("Telegram polling запущен в фоне.")
    return app

async def handle_root(request):
    return web.Response(text="ok")

async def main():
    # Запускаем бота
    await run_bot()

    # Запускаем простой HTTP сервер на порту PORT
    web_app = web.Application()
    web_app.add_routes([web.get('/', handle_root)])
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"HTTP сервер поднят на порту {PORT}")

    # Ждём в цикле — процесс держится в живых
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(main())
