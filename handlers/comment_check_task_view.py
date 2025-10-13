# handlers/comment_check_task_view.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.db import get_task_by_id, get_comment_check_logs
import json

def _stats(task_id: int):
    rows = get_comment_check_logs(task_id)
    yes = sum(1 for r in rows if r[2] is True)
    no  = sum(1 for r in rows if r[2] is False)
    unk = sum(1 for r in rows if r[2] is None)
    return yes, no, unk

def _kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"cchk_refresh:{task_id}")],
        [InlineKeyboardButton(text="📤 Экспорт (с обсуждениями)", callback_data=f"cchk_export_yes:{task_id}")],
        [InlineKeyboardButton(text="📜 Полный лог", callback_data=f"cchk_export_all:{task_id}")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"confirm_delete_task_{task_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_task_execution")],
    ])

def create_cchk_task_card(task) -> tuple[str, InlineKeyboardMarkup]:
    if isinstance(task, int):
        t = get_task_by_id(task) or {}
    else:
        t = task or {}
    task_id = t.get("id")

    payload = t.get("payload") or {}
    if isinstance(payload, str):
        try: payload = json.loads(payload)
        except: payload = {}

    total   = int(payload.get("total_channels") or payload.get("channels_count") or 0)
    checked = int(payload.get("checked") or 0)
    status  = (t.get("status") or "-").lower()

    yes, no, unk = _stats(task_id)
    status_emoji = {"completed": "✅", "running": "🟡", "in_progress": "🟡", "error": "❌"}.get(status, "⏳")
    status_txt   = {"completed": "Завершена", "running": "В работе", "in_progress": "В работе", "error": "Ошибка"}.get(status, status.capitalize())

    text = "\n".join([
        "🧪 <b>Проверка обсуждений</b>",
        f"Задача #{task_id}", "",
        f"Прогресс: <b>{checked}/{total}</b>",
        f"Есть обсуждения: <b>{yes}</b>",
        f"Нет обсуждений: <b>{no}</b>",
        f"Неопределено/ошибки: <b>{unk}</b>", "",
        f"Статус: {status_emoji} <b>{status_txt}</b>",
    ])
    return text, _kb(task_id)
