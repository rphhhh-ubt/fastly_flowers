# handlers/reauthorize_accounts.py
# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import List, Dict, Any, Iterable, Optional

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from utils.check_access import admin_only
from app.db import get_all_accounts, get_connection, get_account_groups_with_count
from utils.reauthorize_accounts import run_reauth_task
from app.db import get_available_api_key, increment_api_key_usage

router = Router()
log = logging.getLogger("reauth_handlers")

# ==========================
# FSM
# ==========================
class ReauthFSM(StatesGroup):
    select_accounts = State()
    ask_twofa = State()
    confirm = State()

# ==========================
# Константы/хелперы состояния
# ==========================
STATE_ACCOUNTS = "reauth_accounts"
STATE_SELECTED = "reauth_selected"
STATE_PAGE     = "reauth_page"
PER_PAGE       = 10

def _group_ids(accounts: List[Dict[str, Any]], group_id: int) -> set[int]:
    return {a["id"] for a in accounts if a.get("group_id") == group_id}

async def safe_edit_markup(message: types.Message, reply_markup: InlineKeyboardMarkup):
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise

# ==========================
# helpers (UI)
# ==========================
def _accounts_keyboard(
    accounts: List[Dict[str, Any]],
    selected: Iterable[int] | None,
    page: int = 0,
    per_page: int = PER_PAGE,
    groups: Optional[List[Dict[str, Any]]] = None,  # [{'id','name','emoji','count'}, ...]
) -> InlineKeyboardMarkup:
    selected = set(selected or [])
    start = page * per_page
    chunk = accounts[start: start + per_page]

    rows: List[List[InlineKeyboardButton]] = []

    # список аккаунтов (текущая страница)
    for acc in chunk:
        acc_id = acc["id"]
        uname  = acc.get("username") or "-"
        if uname != "-" and not str(uname).startswith("@"):
            uname = f"@{uname}"
        phone  = acc.get("phone") or "-"
        mark   = "✅" if acc_id in selected else "⏹️"
        txt    = f"{mark} {acc_id} ▸ {uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"reauth_toggle:{acc_id}")])

    # навигация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"reauth_page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"reauth_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп (по 3 в ряд)
    chips: List[InlineKeyboardButton] = []
    if groups:
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue
            name  = f"{g.get('emoji','')} {g.get('name','')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"reauth_group:{g['id']}"))
    for i in range(0, len(chips), 3):
        rows.append(chips[i:i+3])

    # массовые действия
    rows.append([
        InlineKeyboardButton(text="✅ Выбрать все", callback_data="reauth_select_all"),
        InlineKeyboardButton(text="⏹️ Снять все",   callback_data="reauth_clear_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="➡ Далее",  callback_data="reauth_to_twofa"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="menu_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _twofa_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="2FA нет", callback_data="reauth_twofa_none")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="reauth_back_select")],
    ])

def _confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить", callback_data="reauth_start")],
        [InlineKeyboardButton(text="⬅️ Назад (2FA)", callback_data="reauth_back_twofa")],
        [InlineKeyboardButton(text="Отмена", callback_data="menu_main")],
    ])

# ==========================
# ENTRY POINT
# ==========================
@router.callback_query(F.data == "task_reauth_start")
@admin_only
async def task_reauth_start(call: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts() or []
    groups   = get_account_groups_with_count()

    await state.set_state(ReauthFSM.select_accounts)
    await state.update_data(
        **{
            STATE_ACCOUNTS: accounts,
            STATE_SELECTED: [],
            STATE_PAGE: 0
        }
    )
    kb = _accounts_keyboard(accounts, set(), 0, PER_PAGE, groups)
    await call.message.edit_text(
        "🔑 <b>Переавторизация аккаунтов</b>\n\nВыберите аккаунты:",
        reply_markup=kb, parse_mode="HTML"
    )
    await call.answer()

# ======= выбор аккаунтов =======
@router.callback_query(F.data.startswith("reauth_page:"))
@admin_only
async def reauth_page_sw(call: types.CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    selected = set(data.get(STATE_SELECTED, []))
    await state.update_data(**{STATE_PAGE: page})
    kb = _accounts_keyboard(accounts, selected, page, PER_PAGE, get_account_groups_with_count())
    await safe_edit_markup(call.message, kb)
    await call.answer()

@router.callback_query(F.data.startswith("reauth_toggle:"))
@admin_only
async def reauth_toggle_acc(call: types.CallbackQuery, state: FSMContext):
    acc_id = int(call.data.split(":")[1])
    data = await state.get_data()
    sel = set(data.get(STATE_SELECTED, []))
    if acc_id in sel:
        sel.remove(acc_id)
    else:
        sel.add(acc_id)
    await state.update_data(**{STATE_SELECTED: list(sel)})
    accounts = data.get(STATE_ACCOUNTS, [])
    page = int(data.get(STATE_PAGE, 0))
    kb = _accounts_keyboard(accounts, sel, page, PER_PAGE, get_account_groups_with_count())
    await safe_edit_markup(call.message, kb)
    await call.answer()

@router.callback_query(F.data == "reauth_select_all")
@admin_only
async def reauth_select_all(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    all_ids = [a["id"] for a in accounts]
    await state.update_data(**{STATE_SELECTED: all_ids})
    page = int(data.get(STATE_PAGE, 0))
    kb = _accounts_keyboard(accounts, set(all_ids), page, PER_PAGE, get_account_groups_with_count())
    await safe_edit_markup(call.message, kb)
    await call.answer("✅ Выбраны все аккаунты")

@router.callback_query(F.data == "reauth_clear_all")
@admin_only
async def reauth_clear_all(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    await state.update_data(**{STATE_SELECTED: []})
    page = int(data.get(STATE_PAGE, 0))
    kb = _accounts_keyboard(accounts, set(), page, PER_PAGE, get_account_groups_with_count())
    await safe_edit_markup(call.message, kb)
    await call.answer("♻️ Сброшен выбор")

# чипс группы (выбираем ровно эту группу)
@router.callback_query(F.data.startswith("reauth_group:"))
@admin_only
async def reauth_group_pick(call: types.CallbackQuery, state: FSMContext):
    group_id = int(call.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    page     = int(data.get(STATE_PAGE, 0))

    ids_in_group = _group_ids(accounts, group_id)
    if not ids_in_group:
        await call.answer("В этой группе нет аккаунтов")
        return

    await state.update_data(**{STATE_SELECTED: list(ids_in_group)})

    # если на текущей странице визуально что-то изменится — перерисуем
    start = page * PER_PAGE
    page_ids = {a["id"] for a in accounts[start:start + PER_PAGE]}
    changed_on_page = bool(ids_in_group & page_ids)

    kb = _accounts_keyboard(accounts, ids_in_group, page, PER_PAGE, get_account_groups_with_count())
    if changed_on_page:
        await safe_edit_markup(call.message, kb)

    await call.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")

@router.callback_query(F.data == "reauth_to_twofa")
@admin_only
async def reauth_to_twofa(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_ids = data.get(STATE_SELECTED, [])
    if not selected_ids:
        await call.answer("Выберите хотя бы один аккаунт.", show_alert=True)
        return
    await state.set_state(ReauthFSM.ask_twofa)
    await call.message.edit_text(
        "🔐 Введите общий пароль 2FA (если есть) одним сообщением.\n"
        "Или нажмите «2FA нет».",
        reply_markup=_twofa_keyboard()
    )
    await call.answer()

@router.callback_query(F.data == "reauth_back_select")
@admin_only
async def reauth_back_select(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCOUNTS, [])
    page = int(data.get(STATE_PAGE, 0))
    selected = set(data.get(STATE_SELECTED, []))
    await state.set_state(ReauthFSM.select_accounts)
    kb = _accounts_keyboard(accounts, selected, page, PER_PAGE, get_account_groups_with_count())
    await call.message.edit_text(
        "🔑 <b>Переавторизация аккаунтов</b>\n\nВыберите аккаунты:",
        reply_markup=kb, parse_mode="HTML"
    )
    await call.answer()

# ======= ввод 2FA =======
@router.callback_query(F.data == "reauth_twofa_none")
@admin_only
async def reauth_twofa_none(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accs = data.get(STATE_SELECTED, [])
    await state.update_data(twofa_password=None)
    await state.set_state(ReauthFSM.confirm)

    text = (
        "✅ <b>Проверьте параметры задачи</b>\n\n"
        f"• Аккаунтов: <b>{len(accs)}</b>\n"
        f"• 2FA пароль: <b>—</b>\n\n"
        "Стартуем?"
    )
    await call.message.edit_text(text, reply_markup=_confirm_keyboard(), parse_mode="HTML")
    await call.answer()

@router.message(ReauthFSM.ask_twofa)
async def reauth_set_twofa(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    accs = data.get(STATE_SELECTED, [])
    pwd = (msg.text or "").strip() or None

    await state.update_data(twofa_password=pwd)
    await state.set_state(ReauthFSM.confirm)

    text = (
        "✅ <b>Проверьте параметры задачи</b>\n\n"
        f"• Аккаунтов: <b>{len(accs)}</b>\n"
        f"• 2FA пароль: <b>{'указан' if pwd else '—'}</b>\n\n"
        "Стартуем?"
    )
    await msg.answer(text, reply_markup=_confirm_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "reauth_back_twofa")
@admin_only
async def reauth_back_twofa(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(ReauthFSM.ask_twofa)
    await call.message.edit_text(
        "🔐 Введите общий пароль 2FA (если есть) одним сообщением.\n"
        "Или нажмите «2FA нет».",
        reply_markup=_twofa_keyboard()
    )
    await call.answer()

# ======= старт =======
def _create_task_in_db(payload: dict) -> int:
    """Создаём задачу и гарантируем, что payload в БД тоже содержит task_id."""
    task_id = None

    try:
        from app.db import add_task
        tid = add_task(task_type="reauthorize_accounts", payload=payload, status="pending")
        task_id = tid["id"] if isinstance(tid, dict) and "id" in tid else int(tid)
    except Exception:
        # fallback: прямой INSERT (здесь payload в БД пока без task_id)
        conn = get_connection()
        cur = conn.cursor()
        import json
        cur.execute("""
            INSERT INTO tasks (type, status, payload)
            VALUES (%s, %s, %s)
            RETURNING id
        """, ("reauthorize_accounts", "pending", json.dumps(payload)))
        task_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

    # Добавляем task_id в исходный словарь (для передачи в воркер)
    payload["task_id"] = task_id

    # Чтобы и в БД payload содержал task_id — обновим строку:
    try:
        conn = get_connection()
        cur = conn.cursor()
        import json
        cur.execute("""
            UPDATE tasks
               SET payload = %s
             WHERE id = %s
        """, (json.dumps(payload), task_id))
        conn.commit()
    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

    return task_id

@router.callback_query(F.data == "reauthorize_accounts_card")
@admin_only
async def show_card_placeholder(call: types.CallbackQuery):
    await call.answer("Карточка будет показана после создания задачи.", show_alert=True)

@router.callback_query(F.data == "reauth_start")
@admin_only
async def reauth_start(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    acc_ids = data.get(STATE_SELECTED, [])
    if not acc_ids:
        await call.answer("Пустой список аккаунтов.", show_alert=True)
        return

    twofa = data.get("twofa_password")

    # берём один API ключ на всю задачу
    api_key = get_available_api_key()
    if not api_key:
        await call.answer("❌ Нет свободных API ключей.", show_alert=True)
        return
    increment_api_key_usage(api_key["id"])

    payload = {
        "accounts": acc_ids,
        "twofa_password": twofa,
    }
    task_id = _create_task_in_db(payload)
    payload["task_id"] = task_id

    # Запускаем асинхронно выполнение
    asyncio.create_task(
        run_reauth_task(api_key["api_id"], api_key["api_hash"], payload, logger=log, task_id=task_id)
    )

    # Карточка-уведомление
    txt = (
        f"🚀 Задача <b>#{task_id}</b> запущена.\n\n"
        f"Тип: <code>reauthorize_accounts</code>\n"
        f"Аккаунтов: <b>{len(acc_ids)}</b>\n"
        f"2FA: <b>{'указан' if twofa else '—'}</b>\n\n"
        f"Открой «Список задач», чтобы посмотреть прогресс и логи."
    )
    await call.message.edit_text(
        txt, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Открыть список задач", callback_data="menu_task_execution")],
        ])
    )
    await state.clear()
    await call.answer("Стартуем ✅")
