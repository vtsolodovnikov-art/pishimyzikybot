# main.py
import os
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date, datetime, timedelta
from math import floor
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PORT = int(os.environ.get("PORT", "8000"))
STATE_FILE = "state.json"

# Этапы и веса (как обсуждали)
STAGES = [
    ("Сочинение", 0.30),
    ("Запись демо", 0.10),
    ("Аранжировка", 0.25),
    ("Запись вокала", 0.15),
    ("Сведение и мастеринг", 0.20),
]

# --- HTTP (чтобы Render принял сервис) ---
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

# --- Сохранение / загрузка состояния ---
def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_state() -> dict | None:
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception("Ошибка чтения state.json: %s", e)
        return None

# --- Распределение дней по этапам (алгоритм из наших обсуждений) ---
def allocate_days(total_days: int):
    raw = []
    for name, weight in STAGES:
        rd = weight * total_days
        raw.append((name, rd))
    floors = [(name, int(floor(rd)), rd - floor(rd)) for name, rd in raw]
    S = sum(x[1] for x in floors)
    R = total_days - S
    # сортируем по дробной части, убыванию
    sorted_by_frac = sorted(floors, key=lambda x: x[2], reverse=True)
    extras = {name: 0 for name, _, _ in floors}
    i = 0
    while R > 0 and i < len(sorted_by_frac):
        extras[sorted_by_frac[i][0]] += 1
        R -= 1
        i += 1
    # итоговый список с минимум 1 днём на этап
    schedule = []
    for name, base, frac in floors:
        days_count = max(1, base + extras.get(name, 0))
        schedule.append((name, days_count))
    # корректировка на случай, если сумма всё ещё не равна (редкий случай)
    total_alloc = sum(d for _, d in schedule)
    if total_alloc != total_days:
        diff = total_days - total_alloc
        # тупо добавим/уберём у последнего этапа
        last_name, last_count = schedule[-1]
        schedule[-1] = (last_name, max(1, last_count + diff))
    return schedule

def build_schedule(start_date: date):
    # days in month of start_date
    next_month = start_date.replace(day=28) + timedelta(days=4)
    last_day = (next_month - timedelta(days=next_month.day)).day
    total_days = last_day
    alloc = allocate_days(total_days)
    # build with start/end day indices (1-based within month)
    schedule = []
    cursor = 1
    for name, days in alloc:
        schedule.append({
            "name": name,
            "days": days,
            "start_day": cursor,
            "end_day": cursor + days - 1,
            "completed": False
        })
        cursor += days
    return {"start_date": start_date.isoformat(), "total_days": total_days, "schedule": schedule}

# --- Утилиты для статуса ---
def get_current_day_index(start_date: date) -> int:
    today = date.today()
    delta = (today - start_date).days + 1
    return delta  # может быть <=0 или > total_days

def find_stage_by_day(schedule: list, day: int):
    for idx, s in enumerate(schedule):
        if s["start_day"] <= day <= s["end_day"]:
            return idx, s
    return None, None

def pretty_schedule_text(state: dict):
    lines = []
    for s in state["schedule"]:
        done = "✅" if s.get("completed") else "⏳"
        lines.append(f'{done} {s["name"]}: дни {s["start_day"]}-{s["end_day"]} ({s["days"]} дн.)')
    return "\n".join(lines)

# --- Telegram handlers ---
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Я бот-наставник. Команды:\n"
        "/start_cycle [YYYY-MM-DD] — начать цикл (по умолчанию 1-е число текущего месяца)\n"
        "/status — показать текущий статус цикла\n"
        "/done <этап> — пометить этап выполненным (пример: /done Аранжировка)\n"
        "/help — эта подсказка\n\n"
        "Этапы:\n" + "\n".join([f"- {name}" for name, _ in STAGES])
    )
    await update.message.reply_text(txt)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет, я бот-наставник Мнемоно. /help чтобы увидеть команды.")

async def start_cycle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start_cycle [YYYY-MM-DD] - если не указан, стартуем с 1-го дня текущего месяца"""
    arg = None
    if context.args:
        arg = context.arg
