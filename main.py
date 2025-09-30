import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет, я бот-наставник Мнемоно. /status чтобы проверить цикл.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Цикл не запущен (тестовый бот).")

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN не задан в окружении.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    print("Бот запущен (polling).")
    app.run_polling()

if __name__ == "__main__":
    main()
