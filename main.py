# main.py
import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", "8000"))

class SimpleHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    # не писать логи в stdout слишком много
    def log_message(self, format, *args):
        return

def run_http_server(port: int):
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    logger.info(f"HTTP сервер слушает на порту {port}")
    try:
        server.serve_forever()
    except Exception as e:
        logger.exception("HTTP сервер завершился: %s", e)
    finally:
        try:
            server.server_close()
        except Exception:
            pass

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет, я бот-наставник Мнемоно. /status чтобы проверить цикл.")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Цикл не запущен (тестовый бот).")

def main():
    if not BOT_TOKEN:
        logger.error("ERROR: BOT_TOKEN не задан в окружении.")
        return

    # 1) Запускаем HTTP-сервер в отдельном потоке (чтобы Render увидел открытый порт)
    server_thread = threading.Thread(target=run_http_server, args=(PORT,), daemon=True)
    server_thread.start()

    # 2) Строим бот и запускаем polling в главном потоке (blocking)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))

    logger.info("Запускаю Telegram polling (blocking).")
    try:
        app.run_polling()
    except Exception as e:
        logger.exception("Ошибка в polling: %s", e)

if __name__ == "__main__":
    main()
