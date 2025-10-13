# handlers/check_groups_task.py  (или замени соответствующий блок у тебя)

import asyncio, os, time, tempfile, re, random
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from utils.check_access import admin_only
from utils.check_groups import check_groups_members_filter
from app.db import (
    get_all_accounts, get_account_by_id, create_task_entry,
    get_ok_channels_for_task, get_connection
)
from app.db import get_account_groups_with_count  # ← чипсы групп

router = Router()

# ===== FSM =====
class CheckGroupsTaskStates(StatesGroup):
    selecting_accounts = State()
    waiting_for_links = State()
    waiting_for_filter = State()
    waiting_for_delay_accounts = State()
    waiting_for_delay_requests = State()
    waiting_for_floodwait_padding = State()

# ===== Sticky UI helpers (как в лайкере) =====
async def ui_get_ids(state) -> tuple[int | None, int | None]:
    d = await state.get_data()
    return d.get("ui_chat_id"), d.get("ui_message_id")

async def ui_set_ids(state, chat_id: int, message_id: int):
    await state.update_data(ui_chat_id=chat_id, ui_message_id=message_id)

async def ui_edit(bot, chat_id: int, message_id: int, text: str, kb: InlineKeyboardMarkup | None = None):
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text,
                                    reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        s = str(e).lower()
        if "message is not modified" in s:
            return

async def delete_user_message(msg: types.Message):
    try:
        await msg.delete()
    except Exception:
        pass

# ===== Виджеты выбора аккаунтов =====
def gc_accounts_keyboard(
    accounts: list[dict],
    selected_ids: set[int] | list[int] | None = None,
    page: int = 0,
    per_page: int = 10,
    groups: list[dict] | None = None,
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
        txt = f"{mark} {acc_id} ▸ @{uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"gc_toggle:{acc_id}")])

    # пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"gc_page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"gc_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп
    if groups:
        chips = []
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue
            name = f"{g.get('emoji','')} {g.get('name','')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"gc_group:{g['id']}"))
        for i in range(0, len(chips), 3):
            rows.append(chips[i:i+3])

    # массовые действия + управление
    rows.append([
        InlineKeyboardButton(text="Выбрать все", callback_data="gc_select_all"),
        InlineKeyboardButton(text="Снять все",   callback_data="gc_clear_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="Далее ➜", callback_data="gc_proceed"),
        InlineKeyboardButton(text="Отмена",   callback_data="menu_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ===== Утилиты для ввода =====
TEMP_DIR = os.getenv("TMPDIR", "/tmp")
MAX_TEXT_LINES = 200

def _norm_link(s: str) -> str:
    s = (s or "").strip()
    return s

async def _read_txt_lines(path: str) -> list[str]:
    def _read():
        out = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s:
                    out.append(s)
        return out
    return await asyncio.to_thread(_read)

def ok_to_delete_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ OK (Удалить файл)", callback_data="groupcheck_delete_file_msg")]]
    )

# ===== Старт =====
@router.callback_query(F.data == "start_check_groups_task")
@admin_only
async def start_check_groups_task(cb: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts()
    if not accounts:
        await cb.answer("⚠️ Нет доступных аккаунтов.", show_alert=True)
        return

    groups = get_account_groups_with_count()
    await state.set_state(CheckGroupsTaskStates.selecting_accounts)
    await state.update_data(accounts=accounts, selected_accounts=[], page=0)

    # закрепляем «липкую» карточку на текущем сообщении
    await ui_set_ids(state, cb.message.chat.id, cb.message.message_id)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выберите аккаунты для проверки групп:",
        gc_accounts_keyboard(accounts, set(), page=0, groups=groups)
    )
    await cb.answer()

# ===== Выбор аккаунтов (toggle/page/select/clear/group) =====
@router.callback_query(F.data.startswith("gc_toggle:"), CheckGroupsTaskStates.selecting_accounts)
@admin_only
async def gc_toggle(cb: types.CallbackQuery, state: FSMContext):
    acc_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected_accounts", []))
    if acc_id in selected: selected.remove(acc_id)
    else: selected.add(acc_id)
    await state.update_data(selected_accounts=list(selected))

    accounts = data.get("accounts", [])
    page = int(data.get("page", 0))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Выберите аккаунты:",
                  gc_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count()))
    await cb.answer()

@router.callback_query(F.data.startswith("gc_page:"), CheckGroupsTaskStates.selecting_accounts)
@admin_only
async def gc_page(cb: types.CallbackQuery, state: FSMContext):
    page = int(cb.data.split(":")[1])
    data = await state.get_data()
    await state.update_data(page=page)

    accounts = data.get("accounts", [])
    selected = set(data.get("selected_accounts", []))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Выберите аккаунты:",
                  gc_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count()))
    await cb.answer()

@router.callback_query(F.data == "gc_select_all", CheckGroupsTaskStates.selecting_accounts)
@admin_only
async def gc_select_all(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    all_ids = [a["id"] for a in accounts]
    await state.update_data(selected_accounts=all_ids)

    page = int(data.get("page", 0))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Все аккаунты выбраны. Нажмите «Далее».",
                  gc_accounts_keyboard(accounts, set(all_ids), page=page, groups=get_account_groups_with_count()))
    await cb.answer("✅ Выбраны все")

@router.callback_query(F.data == "gc_clear_all", CheckGroupsTaskStates.selecting_accounts)
@admin_only
async def gc_clear_all(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    await state.update_data(selected_accounts=[])

    page = int(data.get("page", 0))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Выбор очищен. Отметьте нужные аккаунты:",
                  gc_accounts_keyboard(accounts, set(), page=page, groups=get_account_groups_with_count()))
    await cb.answer("♻️ Сброшен выбор")

@router.callback_query(F.data.startswith("gc_group:"), CheckGroupsTaskStates.selecting_accounts)
@admin_only
async def gc_group(cb: types.CallbackQuery, state: FSMContext):
    group_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get("accounts", [])
    ids_in_group = {a["id"] for a in accounts if a.get("group_id") == group_id}
    if not ids_in_group:
        await cb.answer("В этой группе нет аккаунтов")
        return
    await state.update_data(selected_accounts=list(ids_in_group))

    page = int(data.get("page", 0))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Выберите аккаунты:",
                  gc_accounts_keyboard(accounts, ids_in_group, page=page, groups=get_account_groups_with_count()))
    await cb.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")

@router.callback_query(F.data == "gc_proceed", CheckGroupsTaskStates.selecting_accounts)
@admin_only
async def gc_proceed(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected_accounts"):
        await cb.answer("⚠️ Выберите хотя бы один аккаунт!", show_alert=True)
        return
    await state.set_state(CheckGroupsTaskStates.waiting_for_links)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "📋 Пришлите список групп (t.me/...), по одной в строке или .txt файлом.")
    await cb.answer()

# ===== Получение ссылок =====
@router.message(CheckGroupsTaskStates.waiting_for_links)
@admin_only
async def gc_links(msg: types.Message, state: FSMContext):
    links: list[str] = []

    if msg.text and not msg.document:
        lines = [s for s in (msg.text or "").splitlines() if s.strip()]
        if len(lines) > MAX_TEXT_LINES:
            await delete_user_message(msg)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(msg.bot, chat_id, message_id,
                          f"⚠️ В тексте {len(lines)} строк (> {MAX_TEXT_LINES}). "
                          "Пришлите .txt файл (по одной ссылке в строке).")
            return
        links = lines
    elif msg.document:
        ts = int(time.time())
        tmp_path = os.path.join(TEMP_DIR, f"groups_{msg.from_user.id}_{ts}.txt")
        try:
            await msg.bot.download(msg.document, destination=tmp_path)
            links = await _read_txt_lines(tmp_path)
        except Exception as e:
            await delete_user_message(msg)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(msg.bot, chat_id, message_id, f"❌ Не удалось прочитать файл: {e}")
            return
        finally:
            try: os.remove(tmp_path)
            except: pass
    else:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id,
                      "⚠️ Пришлите список групп текстом (до 200 строк) или .txt файлом.")
        return

    links = [_norm_link(x) for x in links]
    links = [x for x in links if x]
    if not links:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id, "⚠️ Не найдено ни одной ссылки. Пришлите ещё раз.")
        return

    random.shuffle(links)
    await state.update_data(links=links)
    await delete_user_message(msg)

    await state.set_state(CheckGroupsTaskStates.waiting_for_filter)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(msg.bot, chat_id, message_id, "✏️ Введи минимальное число участников (например, 20000):")

# ===== min members =====
@router.message(CheckGroupsTaskStates.waiting_for_filter)
@admin_only
async def gc_min_members(msg: types.Message, state: FSMContext):
    try:
        n = int((msg.text or "").strip())
        if n <= 0: raise ValueError
    except Exception:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id, "❗ Введи корректное число (например, 20000):")
        return

    await state.update_data(min_members=n)
    await delete_user_message(msg)

    await state.set_state(CheckGroupsTaskStates.waiting_for_delay_accounts)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(msg.bot, chat_id, message_id, "⏱ Введи задержку между аккаунтами (например: 5-10):")

# ===== задержка между аккаунтами =====
@router.message(CheckGroupsTaskStates.waiting_for_delay_accounts)
@admin_only
async def gc_delay_accounts(msg: types.Message, state: FSMContext):
    await state.update_data(delay_accounts=(msg.text or "").strip())
    await delete_user_message(msg)
    await state.set_state(CheckGroupsTaskStates.waiting_for_delay_requests)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(msg.bot, chat_id, message_id, "⏱ Введи задержку между запросами (например: 2-4):")

# ===== задержка между запросами =====
@router.message(CheckGroupsTaskStates.waiting_for_delay_requests)
@admin_only
async def gc_delay_requests(msg: types.Message, state: FSMContext):
    await state.update_data(delay_requests=(msg.text or "").strip())
    await delete_user_message(msg)
    await state.set_state(CheckGroupsTaskStates.waiting_for_floodwait_padding)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(msg.bot, chat_id, message_id, "⏱ Введи задержку после FloodWait (например: 5-15):")

# ===== финал: создание задачи и запуск =====
@router.message(CheckGroupsTaskStates.waiting_for_floodwait_padding)
@admin_only
async def gc_finalize(msg: types.Message, state: FSMContext):
    floodwait = (msg.text or "").strip()
    data = await state.get_data()

    selected_ids: list[int] = data.get("selected_accounts", [])
    accounts = [get_account_by_id(i) for i in selected_ids if get_account_by_id(i)]
    if not accounts:
        await msg.answer("❌ Нет доступных аккаунтов для задачи!")
        await state.clear()
        return

    delays = {
        "between_accounts": data["delay_accounts"],
        "between_requests": data["delay_requests"],
        "floodwait_padding": floodwait,
    }
    payload = {
        "links": data["links"],
        "min_members": data["min_members"],
        "accounts": selected_ids,
        "delays": delays,
    }
    task_id = create_task_entry("check_groups", created_by=msg.from_user.id, payload=payload)

    # карточка задачи (кнопка)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        msg.bot, chat_id, message_id,
        "✅ Задача создана! Открыть карточку:",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📋 Открыть карточку задачи", callback_data=f"show_check_groups_task_{task_id}")
        ]])
    )
    await delete_user_message(msg)

    # запуск проверки (не спамим промежуточными сообщениями)
    good, small, bad, errors = await check_groups_members_filter(
        links=data["links"],
        message=None,
        min_members=data["min_members"],
        accounts=accounts,
        task_id=task_id,
        delays=delays
    )

    # лог файлом
    parts = []
    if good:   parts.append("✅ Найдены группы:\n" + "\n".join(good))
    if small:  parts.append("⚠️ Мало участников:\n" + "\n".join(small))
    if bad:    parts.append("❌ Не удалось проверить:\n" + "\n".join(bad))
    if errors: parts.append("Ошибки:\n" + "\n".join(errors))
    text = "\n\n".join(parts) if parts else "Проверка завершена. Нет подходящих групп."

    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tmp:
        tmp.write(text)
        tmp_path = tmp.name
    with open(tmp_path, "rb") as f:
        await msg.bot.send_document(
            chat_id=chat_id,
            document=BufferedInputFile(f.read(), filename=f"check_groups_{task_id}.txt"),
            caption="📁 Лог задачи",
            reply_markup=ok_to_delete_keyboard()
        )
    try: os.remove(tmp_path)
    except: pass

    await state.clear()

# удалить сообщение с логом
@router.callback_query(F.data == "groupcheck_delete_file_msg")
async def groupcheck_delete_file_msg(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await callback.answer("✅ Сообщение удалено!")
