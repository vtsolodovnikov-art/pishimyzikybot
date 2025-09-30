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

# фиксированные этапы и веса
STAGES = [
    ("Сочинение", 0.30),
    ("Запись демо", 0.10),
    ("Аранжировка", 0.25),
    ("Запись вокала", 0.15),
    ("Сведение и мастеринг", 0.20),
]

# HTTP (чтобы Render принимал сервис)
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

# state хранит единственную песню под ключом "song" или None
def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"song": None}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception("Ошибка чтения state.json: %s", e)
        return {"song": None}

# распределение дней по этапам (ранее обсуждали)
def allocate_days(total_days: int):
    raw = []
    for name, weight in STAGES:
        rd = weight * total_days
        raw.append((name, rd))
    floors = [(name, int(floor(rd)), rd - floor(rd)) for name, rd in raw]
    S = sum(x[1] for x in floors)
    R = total_days - S
    sorted_by_frac = sorted(floors, key=lambda x: x[2], reverse=True)
    extras = {name: 0 for name, _, _ in floors}
    i = 0
    while R > 0 and i < len(sorted_by_frac):
        extras[sorted_by_frac[i][0]] += 1
        R -= 1
        i += 1
    schedule = []
    for name, base, frac in floors:
        days_count = max(1, base + extras.get(name, 0))
        schedule.append((name, days_count))
    total_alloc = sum(d for _, d in schedule)
    if total_alloc != total_days:
        diff = total_days - total_alloc
        last_name, last_count = schedule[-1]
        schedule[-1] = (last_name, max(1, last_count + diff))
    return schedule

def build_schedule_from_days(start_date: date, total_days: int):
    alloc = allocate_days(total_days)
    schedule = []
    cursor = 1
    for name, days in alloc:
        schedule.append({
            "name": name,
            "days": days,
            "start_offset": cursor,
            "end_offset": cursor + days - 1,
            "completed": False
        })
        cursor += days
    return {
        "name": None,
        "start_date": start_date.isoformat(),
        "total_days": total_days,
        "schedule": schedule,
        "created_at": datetime.now().isoformat()
    }

def pretty_schedule_text(song: dict):
    lines = []
    for s in song["schedule"]:
        done = "✅" if s.get("completed") else "⏳"
        lines.append(f'{done} {s["name"]}: дни {s["start_offset"]}-{s["end_offset"]} ({s["days"]} дн.)')
    return "\n".join(lines)

def get_day_index_from_start(start_date_iso: str) -> int:
    sd = datetime.fromisoformat(start_date_iso).date()
    today = date.today()
    return (today - sd).days + 1  # может быть <=0 или > total_days

# --- Telegram handlers ---
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "Команды (упрощённо, 1 песня/цикл):\n"
        "/new <название> [дни] — начать новый цикл для песни (по умолчанию 30 дн.). Если есть активный — бот попросит подтвердить через /new_confirm.\n"
        "/new_confirm <название> [дни] — принудительно создать новый цикл (перезапишет старый)\n"
        "/status — статус текущей песни/цикла\n"
        "/done <этап> — отметить этап выполненным (пример: /done Аранжировка)\n"
        "/help — эта подсказка\n\n"
        "Этапы:\n" + "\n".join([f"- {name}" for name, _ in STAGES])
    )
    await update.message.reply_text(txt)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет, я бот-продюсер. /help — команды.")

async def new_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/new <name> [days] — создаёт новый цикл, но если уже есть активный — просит подтвердить с /new_confirm"""
    state = load_state()
    args = context.args
    if not args:
        await update.message.reply_text("Укажи название песни. Пример: /new МояПесня 30")
        return
    name = args[0].strip()
    days = 30
    if len(args) > 1:
        try:
            days = max(7, int(args[1]))
        except:
            await update.message.reply_text("Неверное число дней. Использую 30.")
            days = 30

    if state.get("song"):
        song = state["song"]
        day_idx = get_day_index_from_start(song["start_date"])
        total = song["total_days"]
        if 1 <= day_idx <= total:
            # активно — просим подтверждение
            await update.message.reply_text(
                f"Уже есть активный цикл для «{song['name']}» (день {day_idx}/{total}).\n"
                f"Если хочешь перезаписать — используй /new_confirm {name} {days} ."
            )
            return
    # нет активного — создаём
    start_date = date.today()
    song = build_schedule_from_days(start_date, days)
    song["name"] = name
    state["song"] = song
    save_state(state)
    await update.message.reply_text(f"Создал новый цикл для «{name}», длина {days} дн.\n\nРасписание:\n{pretty_schedule_text(song)}")

async def new_confirm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/new_confirm <name> [days] — принудительно создать новый цикл, перезаписывая старый"""
    state = load_state()
    args = context.args
    if not args:
        await update.message.reply_text("Укажи название песни. Пример: /new_confirm МояПесня 30")
        return
    name = args[0].strip()
    days = 30
    if len(args) > 1:
        try:
            days = max(7, int(args[1]))
        except:
            await update.message.reply_text("Неверное число дней. Использую 30.")
            days = 30
    start_date = date.today()
    song = build_schedule_from_days(start_date, days)
    song["name"] = name
    state["song"] = song
    save_state(state)
    await update.message.reply_text(f"Новый цикл создан для «{name}», длина {days} дн. (перезаписан старый) \n\nРасписание:\n{pretty_schedule_text(song)}")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    song = state.get("song")
    if not song:
        await update.message.reply_text("Сейчас нет активной песни. Создай /new <название>.")
        return
    day_idx = get_day_index_from_start(song["start_date"])
    total = song["total_days"]
    if day_idx < 1:
        await update.message.reply_text(f"Цикл ещё не начался. Старт: {song['start_date']}")
        return
    if day_idx > total:
        await update.message.reply_text(f"Цикл для «{song['name']}» завершён ({total} дн.).\nРасписание:\n{pretty_schedule_text(song)}")
        return
    cur_stage = None
    for s in song["schedule"]:
        if s["start_offset"] <= day_idx <= s["end_offset"]:
            cur_stage = s
            break
    completed_count = sum(1 for s in song["schedule"] if s.get("completed"))
    days_into_stage = day_idx - cur_stage["start_offset"] + 1
    pct = int(days_into_stage / cur_stage["days"] * 100)
    txt = (
        f"Песня: «{song['name']}»\n"
        f"Дата старта: {song['start_date']}\nДень {day_idx}/{total}\n"
        f"Текущий этап: {cur_stage['name']} ({days_into_stage}/{cur_stage['days']} дн., {pct}%)\n"
        f"Завершено этапов: {completed_count}/{len(song['schedule'])}\n\n"
        f"Полное расписание:\n{pretty_schedule_text(song)}\n\n"
        f"Если этап готов — отмечай /done <этап> (пример: /done Аранжировка)"
    )
    await update.message.reply_text(txt)

async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    song = state.get("song")
    if not song:
        await update.message.reply_text("Нет активной песни. Создай /new <название>.")
        return
    if not context.args:
        await update.message.reply_text("Укажи этап. Пример: /done Аранжировка")
        return
    stage_name = " ".join(context.args).strip()
    found = False
    for s in song["schedule"]:
        if s["name"].lower() == stage_name.lower():
            s["completed"] = True
            found = True
            break
    if not found:
        await update.message.reply_text("Этап не найден в расписании.")
        return
    state["song"] = song
    save_state(state)
    await update.message.reply_text(f"Отмечено: «{stage_name}» как выполненный для песни «{song['name']}». /status")

# --- Запуск ---
def main():
    if not BOT_TOKEN:
        logger.error("ERROR: BOT_TOKEN не задан в окружении.")
        return

    server_thread = threading.Thread(target=run_http_server, args=(PORT,), daemon=True)
    server_thread.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("new", new_cmd))
    app.add_handler(CommandHandler("new_confirm", new_confirm_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("done", done_cmd))

    logger.info("Запускаю Telegram polling (blocking).")
    try:
        app.run_polling()
    except Exception as e:
        logger.exception("Ошибка в polling: %s", e)

if __name__ == "__main__":
    main()
