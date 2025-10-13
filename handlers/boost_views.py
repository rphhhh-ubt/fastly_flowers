# handlers/boost_views.py
import re
from typing import List, Optional
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.db import get_all_accounts, get_account_groups_with_count  # + get_account_groups_with_count

from utils.check_access import admin_only
from app.db import get_all_accounts
from utils.boost_views import BoostViewsExecutor  # остаётся как у тебя
import asyncio
import traceback

router = Router()

# ───────────────────────── helpers ─────────────────────────

STATUS_ICONS = {
    "active": "🟢", "new": "🆕", "banned": "🔴", "freeze": "❄️",
    "needs_login": "🟡", "proxy_error": "🛡️", "unknown": "⚠️"
}
PAGE = 20

def boost_accounts_keyboard(
    accounts: List[dict],
    selected_ids: set[int] | list[int] | None = None,
    page: int = 0,
    per_page: int = 10,
    groups: List[dict] | None = None,
) -> InlineKeyboardMarkup:
    selected = set(selected_ids or [])
    start = page * per_page
    chunk = accounts[start:start + per_page]

    rows: list[list[InlineKeyboardButton]] = []
    for acc in chunk:
        acc_id = acc["id"]
        uname = acc.get("username") or "-"
        phone = acc.get("phone") or "-"
        mark = "✅" if acc_id in selected else "⏹️"
        text = f"{mark} {acc_id} ▸ @{uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"boost_toggle:{acc_id}")])

    # пагинация
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"boost_page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"boost_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп
    if groups:
        chips: list[InlineKeyboardButton] = []
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue
            name = f"{g.get('emoji','')} {g.get('name','')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"boost_group:{g['id']}"))
        for i in range(0, len(chips), 3):
            rows.append(chips[i:i+3])

    # массовые действия
    rows.append([
        InlineKeyboardButton(text="Выбрать все", callback_data="boost_select_all"),
        InlineKeyboardButton(text="Снять все",   callback_data="boost_clear_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="Далее ➜", callback_data="boost_done_select"),
        InlineKeyboardButton(text="Отмена",   callback_data="menu_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ok_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в задачи", callback_data="menu_task_execution")]
    ])

def _sticky_ok_kb():
    # кнопка закрытия текущего «хост»-сообщения (липкого меню)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="OK ✅", callback_data="boost_ui_close")]
    ])

def _normalize_channels(raw: str) -> List[str]:
    out = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        line = line.replace("https://t.me/", "").replace("http://t.me/", "")
        if line.startswith("@"):
            line = line[1:]
        out.append(line)
    # дубли НЕ удаляем
    return [c for c in out if c]

async def _send_host(message: types.Message, state: FSMContext, text: str, kb: Optional[InlineKeyboardMarkup] = None):
    """Создаёт «хост»-месседж и сохраняет его id в FSM."""
    sent = await message.answer(text, reply_markup=kb)
    await state.update_data(host_msg_id=sent.message_id)
    return sent

async def _edit_host(message_or_cb, state, text, kb=None):
    data = await state.get_data()
    host_id = data.get("host_msg_id")
    chat_id = (message_or_cb.chat.id if isinstance(message_or_cb, types.Message)
               else message_or_cb.message.chat.id)
    bot = message_or_cb.bot
    if host_id:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=host_id, text=text, reply_markup=kb)
            return
        except Exception:
            # если не получилось — удаляем старый и создаём новый
            try:
                await bot.delete_message(chat_id=chat_id, message_id=host_id)
            except Exception:
                pass
    sent = (await message_or_cb.answer(text, reply_markup=kb)
            if isinstance(message_or_cb, types.Message)
            else await message_or_cb.message.answer(text, reply_markup=kb))
    await state.update_data(host_msg_id=sent.message_id)

async def _delete_host(message_or_cb: types.Message | types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    host_id = data.get("host_msg_id")
    if not host_id:
        return
    chat_id = (message_or_cb.chat.id if isinstance(message_or_cb, types.Message)
               else message_or_cb.message.chat.id)
    bot = message_or_cb.bot
    try:
        await bot.delete_message(chat_id=chat_id, message_id=host_id)
    except Exception:
        pass
    await state.update_data(host_msg_id=None)



# ───────────────────────── FSM ─────────────────────────

class BoostViewsStates(StatesGroup):
    selecting_accounts = State()
    waiting_channels = State()
    waiting_posts_last = State()
    waiting_delays = State()

# ───────────────────────── cleanup кнопки (общие) ─────────────────────────

@router.callback_query(F.data.startswith("boost_cleanup:"))
@admin_only
async def boost_cleanup_cb(cb: types.CallbackQuery):
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer("Удалено", show_alert=False)

@router.callback_query(F.data == "boost_ui_close")
@admin_only
async def boost_ui_close_cb(cb: types.CallbackQuery, state: FSMContext):
    try:
        await cb.message.delete()   # удаляем текущее «липкое» сообщение с кнопкой
    except Exception:
        pass
    await state.clear()             # потом чистим состояние
    await cb.answer("Закрыто", show_alert=False)



# ───────────────────────── flow ─────────────────────────

@router.message(Command("boost"))
@admin_only
async def cmd_boost(message: types.Message, state: FSMContext):
    await state.set_state(BoostViewsStates.selecting_accounts)
    await state.update_data(selected=[], page=0)
    accs = get_all_accounts()
    groups = get_account_groups_with_count()
    await _send_host(
        message, state,
        "👥 Выберите аккаунты (страница 1):",
        boost_accounts_keyboard(accs, [], page=0, groups=groups)
    )
    try:
        await message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "tasktype_boost_views")
@admin_only
async def boost_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(BoostViewsStates.selecting_accounts)
    await state.update_data(selected=[], page=0)
    accs = get_all_accounts()
    groups = get_account_groups_with_count()
    await _edit_host(cb, state, "👥 Выберите аккаунты (страница 1):",
                     boost_accounts_keyboard(accs, [], page=0, groups=groups))
    await cb.answer()


@router.callback_query(F.data.startswith("boost_page:"), BoostViewsStates.selecting_accounts)
@admin_only
async def boost_page(cb: types.CallbackQuery, state: FSMContext):
    page = int(cb.data.split(":")[1])
    data = await state.get_data()
    accs = get_all_accounts()
    groups = get_account_groups_with_count()
    await state.update_data(page=page)
    await _edit_host(cb, state,
        f"👥 Выберите аккаунты (страница {page+1}):",
        boost_accounts_keyboard(accs, data.get("selected", []), page=page, groups=groups)
    )
    await cb.answer()

@router.callback_query(F.data.startswith("boost_toggle:"), BoostViewsStates.selecting_accounts)
@admin_only
async def boost_toggle(cb: types.CallbackQuery, state: FSMContext):
    acc_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    sel = set(data.get("selected", []))
    if acc_id in sel: sel.remove(acc_id)
    else: sel.add(acc_id)
    await state.update_data(selected=list(sel))

    accs = get_all_accounts()
    groups = get_account_groups_with_count()
    page = int(data.get("page", 0))
    await _edit_host(cb, state,
        f"👥 Выберите аккаунты (страница {page+1}):",
        boost_accounts_keyboard(accs, sel, page=page, groups=groups)
    )
    await cb.answer()

@router.callback_query(F.data == "boost_select_all", BoostViewsStates.selecting_accounts)
@admin_only
async def boost_select_all(cb: types.CallbackQuery, state: FSMContext):
    accs = get_all_accounts()
    all_ids = [a["id"] for a in accs]
    await state.update_data(selected=all_ids)
    page = (await state.get_data()).get("page", 0)
    groups = get_account_groups_with_count()
    await _edit_host(cb, state,
        "👥 Все аккаунты выбраны. Нажмите «Далее».",
        boost_accounts_keyboard(accs, set(all_ids), page=page, groups=groups)
    )
    await cb.answer("✅ Выбраны все")

@router.callback_query(F.data == "boost_clear_all", BoostViewsStates.selecting_accounts)
@admin_only
async def boost_clear_all(cb: types.CallbackQuery, state: FSMContext):
    accs = get_all_accounts()
    await state.update_data(selected=[])
    page = (await state.get_data()).get("page", 0)
    groups = get_account_groups_with_count()
    await _edit_host(cb, state,
        "👥 Выбор очищен. Отметьте нужные аккаунты:",
        boost_accounts_keyboard(accs, set(), page=page, groups=groups)
    )
    await cb.answer("♻️ Сброшен выбор")

@router.callback_query(F.data.startswith("boost_group:"), BoostViewsStates.selecting_accounts)
@admin_only
async def boost_group_pick(cb: types.CallbackQuery, state: FSMContext):
    group_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    accs = get_all_accounts()
    # выберем все id из этой группы
    ids_in_group = [a["id"] for a in accs if a.get("group_id") == group_id]
    if not ids_in_group:
        await cb.answer("В этой группе нет аккаунтов")
        return

    await state.update_data(selected=ids_in_group)
    page = int(data.get("page", 0))
    groups = get_account_groups_with_count()
    await _edit_host(cb, state,
        "👥 Выбрана группа. Можно продолжать.",
        boost_accounts_keyboard(accs, set(ids_in_group), page=page, groups=groups)
    )
    await cb.answer(f"Группа выбрана ({len(ids_in_group)} акк.)")


@router.callback_query(F.data == "boost_done_select", BoostViewsStates.selecting_accounts)
@admin_only
async def boost_done_select(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected"):
        await cb.answer("Выберите хотя бы один аккаунт", show_alert=True)
        return
    await state.set_state(BoostViewsStates.waiting_channels)
    await _edit_host(
        cb, state,
        "📣 Введите каналы (по одному в строке). Форматы: @name, name, https://t.me/name\n"
        "Дубли НЕ удаляются.",
        _ok_kb()
    )
    await cb.answer()

@router.message(BoostViewsStates.waiting_channels, F.text)
@admin_only
async def boost_got_channels(msg: types.Message, state: FSMContext):
    chans = _normalize_channels(msg.text)
    # удаляем сообщение пользователя
    try:
        await msg.delete()
    except Exception:
        pass

    if not chans:
        await _edit_host(msg, state, "❗Не распознал каналы. Пришлите ещё раз.", _ok_kb())
        return
    await state.update_data(channels=chans)
    await state.set_state(BoostViewsStates.waiting_posts_last)
    await _edit_host(msg, state, "🔢 Сколько последних постов смотреть в каждом канале? (число, напр. 5)")

@router.message(BoostViewsStates.waiting_posts_last, F.text)
@admin_only
async def boost_got_n(msg: types.Message, state: FSMContext):
    txt = (msg.text or "").strip()
    try:
        await msg.delete()
    except Exception:
        pass

    if not txt.isdigit():
        await _edit_host(msg, state, "Нужно целое число, напр. 5")
        return
    n = int(txt)
    if n <= 0:
        await _edit_host(msg, state, "Число должно быть > 0.")
        return
    await state.update_data(posts_last=n)
    await state.set_state(BoostViewsStates.waiting_delays)
    await _edit_host(
        msg, state,
        "⏱ Укажите задержки в формате:\n"
        "`между постами, между каналами, между аккаунтами, одновременно запущенных аккаунтов`\n"
        "Пример: `1-2, 3-5, 0-1, 3`"
    )

@router.message(BoostViewsStates.waiting_delays, F.text)
@admin_only
async def boost_got_delays(msg: types.Message, state: FSMContext):
    raw = (msg.text or "").replace(" ", "")
    try:
        await msg.delete()
    except Exception:
        pass

    m = re.fullmatch(r"(\d+)-(\d+),(\d+)-(\d+),(\d+)-(\d+),(\d+)", raw)
    if not m:
        await _edit_host(
            msg, state,
            "❌ Неверный формат.\n"
            "Укажите задержки в формате:\n"
            "`посты, каналы, аккаунты, параллельно`\n"
            "Пример: `1-2, 3-5, 0-1, 3`"
        )
        return

    a1, a2, b1, b2, c1, c2, max_parallel = map(int, m.groups())
    if a1 > a2 or b1 > b2 or c1 > c2:
        await _edit_host(msg, state, "Левая граница должна быть ≤ правой во всех диапазонах.")
        return
    if max_parallel < 1:
        await _edit_host(msg, state, "Количество одновременных аккаунтов должно быть ≥ 1.")
        return

    data = await state.get_data()
    payload = {
        "user_id": msg.from_user.id,
        "accounts": data["selected"],
        "channels": data["channels"],
        "posts_last": data["posts_last"],
        "delay_between_posts": [a1, a2],
        "delay_between_channels": [b1, b2],
        "delay_between_accounts": [c1, c2],
        "max_parallel": max_parallel,
    }

    # запускаем как у тебя — напрямую executor в фоне (без лишних сообщений в чат)
    fake_task = {
        "id": 0,
        "account_id": None,
        "payload": payload
    }

    async def run_boost():
        try:
            executor = BoostViewsExecutor(task=fake_task, account=None)
            await executor.run()
        except Exception as e:
            print(f"[CRITICAL] BoostViews failed: {e}")
            traceback.print_exc()

    # ✅ запускаем задачу в фоне
    asyncio.create_task(run_boost())

    # сначала удаляем старый «хост»
    await _delete_host(msg, state)

    # создаём новый «хост» с финальным экраном
    sent = await msg.answer(
        "✅ Задача запущена в фоне!\n"
        f"Аккаунтов: {len(payload['accounts'])}\n"
        f"Каналов: {len(payload['channels'])}\n"
        f"Постов/канал: {payload['posts_last']}\n"
        f"Параллельно: {payload['max_parallel']}",
        reply_markup=_sticky_ok_kb()
    )
    await state.update_data(host_msg_id=sent.message_id)

    # только после этого — чистим состояние
    await state.clear()

