# handlers/twofa_task_view.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import types
from datetime import datetime
import json

def _fmt_dt(dt):
    if not dt:
        return "—"
    if isinstance(dt, str):
        return dt
    try:
        # предполагаем timezone-aware
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(dt)

def _mode_human(mode: str) -> str:
    m = (mode or "").lower()
    return {"new": "🆕 Новый 2FA", "replace": "♻️ Замена 2FA", "none": "🙅 Без изменений"}.get(m, "—")

def _status_badge(status: str) -> str:
    s = (status or "unknown").lower()
    mp = {
        "completed": "✅ Завершена",
        "active": "🟢 Активна",
        "running": "🟡 Выполняется",
        "pending": "⏳ В очереди",
        "error": "❌ Ошибка",
        "paused": "⏸️ Пауза",
    }
    return mp.get(s, f"❓ {status or 'unknown'}")

def _safe_payload(task: dict) -> dict:
    payload = task.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    return payload

def _accounts_count(task: dict) -> int:
    # пробуем из payload.accounts / accounts_json или из твоей агрегации
    payload = _safe_payload(task)
    accs = payload.get("accounts") or payload.get("accounts_json") or task.get("accounts_json") or []
    if isinstance(accs, str):
        try:
            accs = json.loads(accs)
        except Exception:
            accs = []
    if isinstance(accs, dict):
        # на всякий случай
        accs = list(accs.values())
    return len(accs) if isinstance(accs, list) else (task.get("accounts_count") or 0)

def _masked(s: str | None) -> str:
    if not s:
        return "—"
    return "•" * len(s)

def create_twofa_task_card(task: dict) -> tuple[str, InlineKeyboardMarkup]:
    """
    На вход — задача из get_task_by_id по типу "twofa".
    Возвращает (text, markup).
    """
    payload = _safe_payload(task)

    task_id    = task.get("id")
    status     = task.get("status") or payload.get("status")
    started_at = task.get("started_at") or payload.get("started_at")
    finished_at= task.get("finished_at") or payload.get("finished_at")
    scheduled  = task.get("scheduled_at")

    mode       = payload.get("mode") or task.get("mode")
    kill_other = bool(payload.get("kill_other") or task.get("kill_other"))

    new_pw     = payload.get("new_password") or task.get("new_password")
    old_pw     = payload.get("old_password") or task.get("old_password")

    accs_cnt   = _accounts_count(task)

    text = (
        f"🔐 <b>2FA — карточка задачи</b> #{task_id}\n"
        f"• Статус: {_status_badge(status)}\n"
        f"• Cтарт задачи: {_fmt_dt(started_at)}\n\n"
        f"• Режим: {_mode_human(mode)}\n"
        f"• Аккаунтов: {accs_cnt}\n"
        f"• Удалить остальные сессии: {'Да' if kill_other else 'Нет'}\n"
        f"• Старый пароль: <code>{_masked(old_pw)}</code>\n"
        f"• Новый пароль: <code>{_masked(new_pw)}</code>\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Показать лог", callback_data=f"twofa:log:{task_id}")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_twofa_task_{task_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"twofa:delete:{task_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_task_execution")],
    ])
    return text, kb
