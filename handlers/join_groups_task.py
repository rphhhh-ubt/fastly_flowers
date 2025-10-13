# handlers/join_groups_task.py

import asyncio, os, time, random
from aiogram import Router, types, F
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from app.db import (
    get_all_accounts, get_account_by_id, create_task_entry,
    insert_join_groups_log, update_task_payload, get_account_groups_with_count,
    get_task_by_id,
)
from app.telegram_client import get_client
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import FloodWaitError
from telethon import events
from .join_groups_task_view import create_join_groups_task_card

router = Router()

# ===== FSM =====
class JoinGroupsFSM(StatesGroup):
    selecting_accounts = State()
    waiting_for_links = State()
    waiting_for_delay = State()
    processing = State()

MAX_CB_ANSWER = 190  # запас к лимиту ~200
def _cb_text(s: str) -> str:
    s = s.strip().replace("\n", " ")
    return (s[:MAX_CB_ANSWER-1] + "…") if len(s) > MAX_CB_ANSWER else s


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

async def _safe_delete(msg: types.Message):
    try: await msg.delete()
    except Exception: pass

# ===== Виджет выбора аккаунтов (пагинация + чипсы групп) =====
def jg_accounts_keyboard(
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
        uname  = acc.get("username") or "-"
        phone  = acc.get("phone") or "-"
        mark   = "✅" if acc_id in selected else "⏹️"
        rows.append([InlineKeyboardButton(text=f"{mark} {acc_id} ▸ @{uname} ▸ {phone}",
                                          callback_data=f"jg_toggle:{acc_id}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"jg_page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"jg_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп
    if groups:
        chips = []
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1: continue
            name  = f"{g.get('emoji','')} {g.get('name','')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"jg_group:{g['id']}"))
        for i in range(0, len(chips), 3):
            rows.append(chips[i:i+3])

    # массовые действия
    rows.append([
        InlineKeyboardButton(text="Выбрать все",   callback_data="jg_select_all"),
        InlineKeyboardButton(text="Снять все",     callback_data="jg_clear_all"),
        InlineKeyboardButton(text="Активные",      callback_data="jg_select_active"),
    ])
    rows.append([
        InlineKeyboardButton(text="Далее ➜", callback_data="jg_proceed"),
        InlineKeyboardButton(text="Отмена",   callback_data="menu_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ===== Входная точка =====
@router.callback_query(F.data == "start_join_groups_task")
async def start_join_groups_task(cb: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts()
    if not accounts:
        await cb.answer("⚠️ Нет доступных аккаунтов.", show_alert=True)
        return

    await state.set_state(JoinGroupsFSM.selecting_accounts)
    await state.update_data(accounts=accounts, selected_accounts=[], page=0)

    # закрепляем липкую карту на текущем сообщении
    await ui_set_ids(state, cb.message.chat.id, cb.message.message_id)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выберите аккаунты для вступления в группы:",
        jg_accounts_keyboard(accounts, set(), page=0, groups=get_account_groups_with_count())
    )
    await cb.answer()

# ===== Выбор аккаунтов: toggle / page / select all / clear / active / by group =====
@router.callback_query(F.data.startswith("jg_toggle:"), JoinGroupsFSM.selecting_accounts)
async def jg_toggle(cb: types.CallbackQuery, state: FSMContext):
    acc_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected_accounts", []))
    if acc_id in selected: selected.remove(acc_id)
    else: selected.add(acc_id)
    await state.update_data(selected_accounts=list(selected))
    accounts = data.get("accounts", [])
    page     = int(data.get("page", 0))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Выберите аккаунты:",
                  jg_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count()))
    await cb.answer()

@router.callback_query(F.data.startswith("jg_page:"), JoinGroupsFSM.selecting_accounts)
async def jg_page(cb: types.CallbackQuery, state: FSMContext):
    page = int(cb.data.split(":")[1])
    data = await state.get_data()
    await state.update_data(page=page)
    accounts = data.get("accounts", [])
    selected = set(data.get("selected_accounts", []))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Выберите аккаунты:",
                  jg_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count()))
    await cb.answer()

@router.callback_query(F.data == "jg_select_all", JoinGroupsFSM.selecting_accounts)
async def jg_select_all(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    all_ids = [a["id"] for a in accounts]
    await state.update_data(selected_accounts=all_ids)
    page = int(data.get("page", 0))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Все аккаунты выбраны. Нажмите «Далее».",
                  jg_accounts_keyboard(accounts, set(all_ids), page=page, groups=get_account_groups_with_count()))
    await cb.answer("✅ Выбраны все")

@router.callback_query(F.data == "jg_clear_all", JoinGroupsFSM.selecting_accounts)
async def jg_clear_all(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    await state.update_data(selected_accounts=[])
    page = int(data.get("page", 0))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Выбор очищен. Отметьте нужные аккаунты:",
                  jg_accounts_keyboard(accounts, set(), page=page, groups=get_account_groups_with_count()))
    await cb.answer("♻️ Сброшен выбор")

@router.callback_query(F.data == "jg_select_active", JoinGroupsFSM.selecting_accounts)
async def jg_select_active(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    active_ids = [a["id"] for a in accounts if a.get("status", "active") == "active"]
    await state.update_data(selected_accounts=active_ids)
    page = int(data.get("page", 0))
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "👤 Активные аккаунты выбраны. Нажмите «Далее».",
                  jg_accounts_keyboard(accounts, set(active_ids), page=page, groups=get_account_groups_with_count()))
    await cb.answer("🟢 Активные выбраны")

@router.callback_query(F.data.startswith("jg_group:"), JoinGroupsFSM.selecting_accounts)
async def jg_group(cb: types.CallbackQuery, state: FSMContext):
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
                  jg_accounts_keyboard(accounts, ids_in_group, page=page, groups=get_account_groups_with_count()))
    await cb.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")

@router.callback_query(F.data == "jg_proceed", JoinGroupsFSM.selecting_accounts)
async def jg_proceed(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected_accounts"):
        await cb.answer("⚠️ Выберите хотя бы один аккаунт!", show_alert=True)
        return
    await state.set_state(JoinGroupsFSM.waiting_for_links)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(cb.message.bot, chat_id, message_id,
                  "📋 Пришлите список ссылок на группы (по одной в строке или .txt файлом):")
    await cb.answer()

# ===== Сбор ссылок =====
TEMP_DIR = os.getenv("TMPDIR", "/tmp")
MAX_TEXT_LINES = 200

async def _read_txt_lines(path: str) -> list[str]:
    def _read():
        out = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s: out.append(s)
        return out
    return await asyncio.to_thread(_read)

@router.message(JoinGroupsFSM.waiting_for_links)
async def join_receive_links(msg: types.Message, state: FSMContext):
    links: list[str] = []
    if msg.text and not msg.document:
        lines = [s for s in (msg.text or "").splitlines() if s.strip()]
        if len(lines) > MAX_TEXT_LINES:
            await _safe_delete(msg)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(msg.bot, chat_id, message_id,
                          f"⚠️ В тексте {len(lines)} строк (> {MAX_TEXT_LINES}). "
                          "Пришлите один .txt (по одной ссылке в строке).")
            return
        links = lines
    elif msg.document:
        import time as _t, os as _os
        ts = int(_t.time())
        path = _os.path.join(TEMP_DIR, f"join_links_{msg.from_user.id}_{ts}.txt")
        try:
            await msg.bot.download(msg.document, destination=path)
            links = await _read_txt_lines(path)
        except Exception as e:
            await _safe_delete(msg)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(msg.bot, chat_id, message_id, f"❌ Не удалось прочитать файл: {e}")
            return
        finally:
            try: _os.remove(path)
            except Exception: pass
    else:
        await _safe_delete(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id,
                      "⚠️ Пришлите ссылки текстом (до 200 строк) или одним .txt файлом.")
        return

    links = [s.strip() for s in links if s.strip()]
    random.shuffle(links)
    if not links:
        await _safe_delete(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id, "⚠️ Не найдено ни одной ссылки. Пришлите ещё раз.")
        return

    await state.update_data(links=links)
    await _safe_delete(msg)
    await state.set_state(JoinGroupsFSM.waiting_for_delay)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(msg.bot, chat_id, message_id, "⏱ Введите задержку между вступлениями (секунды, не менее 35):")

# ===== Задержка и старт =====
@router.message(JoinGroupsFSM.waiting_for_delay)
async def join_receive_delay(msg: types.Message, state: FSMContext):
    try:
        delay = int((msg.text or "").strip())
        if delay < 35: delay = 35
    except Exception:
        await _safe_delete(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id, "⚠️ Введите целое число (секунд), не менее 35:")
        return

    await state.update_data(delay=delay)
    await _safe_delete(msg)

    # создаём задачу один раз
    data = await state.get_data()
    user_id = msg.from_user.id
    task_id = create_task_entry(task_type="join_groups", created_by=user_id)
    await state.update_data(task_id=task_id)

    # рисуем карточку
    card_data = {
        "total_accounts": len(data["selected_accounts"]),
        "total_groups":   len(data["links"]),
        "success_joins":  0,
        "captcha_joins":  0,
        "pending_joins":  0,
        "failed_joins":   0,
        "frozen_accounts":0,
        "avg_delay":      delay,
        "total_time":     "0 мин",
        "task_id":        task_id,
        "status":         "🟡 В процессе",
    }
    card_text, card_markup = create_join_groups_task_card(card_data)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(msg.bot, chat_id, message_id, card_text, card_markup)
    await state.update_data(progress_message_id=message_id)

    await state.set_state(JoinGroupsFSM.processing)
    asyncio.create_task(process_join_groups(state, msg))

# ===== Кнопка удаления лога =====
def join_groups_log_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ОК (удалить сообщение)", callback_data="join_groups_delete_log_msg")]
    ])

@router.callback_query(F.data == "join_groups_delete_log_msg")
async def join_groups_delete_log_msg(callback: types.CallbackQuery):
    try: await callback.message.delete()
    except Exception: pass
    await callback.answer("✅ Сообщение удалено!", show_alert=False)

# ===== Работа задачи =====
async def has_inline_captcha(client, entity):
    try:
        async for msg in client.iter_messages(entity, limit=2):
            if msg.reply_markup:
                try:
                    await msg.click(0)
                    return True
                except Exception:
                    return False
        return False
    except Exception:
        return False

async def wait_for_captcha_robust(client, entity, timeout=20):
    import asyncio
    if await has_inline_captcha(client, entity):
        return True

    future = asyncio.get_event_loop().create_future()

    async def on_new_message(event):
        if event.chat_id == entity.id and event.message.reply_markup:
            try:
                await event.message.click(0)
                if not future.done():
                    future.set_result(True)
            except Exception:
                if not future.done():
                    future.set_result(False)

    client.add_event_handler(on_new_message, events.NewMessage)
    result = False
    try:
        try:
            await asyncio.wait_for(future, timeout=timeout-2)
            if future.done():
                result = future.result()
        except asyncio.TimeoutError:
            await asyncio.sleep(2)
            result = await has_inline_captcha(client, entity)
    finally:
        client.remove_event_handler(on_new_message, events.NewMessage)
        if not future.done():
            future.set_result(False)
    return result

async def process_join_groups(state: FSMContext, message: types.Message):
    data = await state.get_data()
    selected_accounts = data["selected_accounts"]
    links  = data["links"]
    delay  = data["delay"]
    task_id = data["task_id"]

    progress_message_id = data.get("progress_message_id")
    chat_id = message.chat.id

    accounts = [get_account_by_id(acc_id) for acc_id in selected_accounts if get_account_by_id(acc_id)]
    n_acc = len(accounts)
    n_grp = len(links)
    per_account = n_grp // n_acc if n_acc else 0
    extra = n_grp % n_acc if n_acc else 0

    account_groups = []
    idx = 0
    for i, acc in enumerate(accounts):
        count = per_account + (1 if i < extra else 0)
        account_groups.append((acc, links[idx:idx+count]))
        idx += count

    summary = []
    remaining_groups = []
    start_time = time.time()
    frozen_account_ids = set()
    banned_account_ids = set()

    async def update_progress_card(running=True):
        success_joins = sum(len(blocks["no_captcha"]) for _, blocks in summary)
        captcha_joins = sum(len(blocks["with_captcha"]) for _, blocks in summary)
        pending_joins = sum(len(blocks["requested"]) for _, blocks in summary)
        failed_joins  = sum(len(blocks["fail"]) for _, blocks in summary)
        total_time = int(time.time() - start_time) // 60
        status = "🟡 В процессе" if running else "✅ Завершена"

        payload = {
            "total_accounts": len(accounts),
            "total_groups": len(links),
            "success_joins": success_joins,
            "captcha_joins": captcha_joins,
            "pending_joins": pending_joins,
            "failed_joins": failed_joins,
            "frozen_accounts": len(frozen_account_ids | banned_account_ids),
            "avg_delay": delay,
            "total_time": f"{total_time} мин",
            "status": status,
            "task_id": task_id
        }
        update_task_payload(task_id, payload)
     

    async def join_groups_for_account(curr_account, curr_links):
        log_blocks = {"no_captcha": [], "with_captcha": [], "requested": [], "fail": []}
        if not curr_account or not curr_links:
            return (curr_account["id"] if curr_account else "-", log_blocks, curr_links)

        # запуск клиента
        try:
            proxy = {
                "proxy_host": curr_account.get("proxy_host"),
                "proxy_port": curr_account.get("proxy_port"),
                "proxy_username": curr_account.get("proxy_username"),
                "proxy_password": curr_account.get("proxy_password"),
            } if curr_account.get("proxy_host") else None
            client = await get_client(curr_account["session_string"], proxy)
            await client.start()
        except Exception as e:
            for link in curr_links:
                insert_join_groups_log(task_id, curr_account["id"], link, "fail", f"Ошибка запуска клиента/прокси: {e}")
                log_blocks["fail"].append((link, f"Ошибка запуска клиента/прокси: {e}"))
            return (curr_account["id"], log_blocks, curr_links)

        # отметим бан из БД (если есть)
        if curr_account.get("status") in ("ban", "banned"):
            banned_account_ids.add(curr_account["id"])

        groups_left = list(curr_links)
        try:
            skip_account = False
            for link in curr_links:
                max_attempts = 5
                attempts = 0
                while attempts < max_attempts:
                    attempts += 1
                    try:
                        entity = await client.get_entity(link)
                        await client(JoinChannelRequest(entity))
                        # ждём возможную капчу
                        if await wait_for_captcha_robust(client, entity, timeout=20):
                            insert_join_groups_log(task_id, curr_account["id"], link, "with_captcha", "Вступление с капчей")
                            log_blocks["with_captcha"].append(link)
                        else:
                            insert_join_groups_log(task_id, curr_account["id"], link, "no_captcha", "Вступление без капчи")
                            log_blocks["no_captcha"].append(link)
                        groups_left.remove(link)
                        break
                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds + delay)
                    except Exception as e:
                        err = str(e).lower()
                        if (
                            "no user has" in err
                            or "the user is deleted" in err
                            or "the user has been deleted" in err
                            or "user deactivated" in err
                            or "user not found" in err
                            or ("not found" in err and "username" in err)
                        ):
                            frozen_account_ids.add(curr_account["id"])
                            for l in groups_left:
                                insert_join_groups_log(task_id, curr_account["id"], l, "fail", f"Аккаунт заморожен/удалён. {err}")
                                log_blocks["fail"].append((l, f"Аккаунт заморожен/удалён. {err}"))
                            skip_account = True
                            break
                        elif "banned" in err or "ban" in err:
                            banned_account_ids.add(curr_account["id"])
                            for l in groups_left:
                                insert_join_groups_log(task_id, curr_account["id"], l, "fail", f"Аккаунт забанен. {err}")
                                log_blocks["fail"].append((l, f"Аккаунт забанен. {err}"))
                            skip_account = True
                            break
                        if "successfully requested to join this chat" in err:
                            insert_join_groups_log(
                                task_id, curr_account["id"], link, "requested",
                                "Заявка на вступление подана, требуется одобрение администратора."
                            )
                            log_blocks["requested"].append(link)
                        else:
                            insert_join_groups_log(task_id, curr_account["id"], link, "fail", f"Ошибка вступления: {e}")
                            log_blocks["fail"].append((link, f"Ошибка вступления: {e}"))
                        groups_left.remove(link)
                        break
                else:
                    insert_join_groups_log(task_id, curr_account["id"], link, "fail", "Превышено число попыток (FloodWait)")
                    log_blocks["fail"].append((link, "Превышено число попыток (FloodWait)"))

                await update_progress_card(running=True)
                await asyncio.sleep(delay)

            return (curr_account["id"], log_blocks, groups_left)
        finally:
            try: await client.disconnect()
            except Exception: pass

    tasks = [join_groups_for_account(acc, grps) for acc, grps in account_groups if acc and grps]
    results = await asyncio.gather(*tasks)
    for acc_id, blocks, not_done in results:
        summary.append((acc_id, blocks))
        if not_done:
            remaining_groups.extend(not_done)

    await update_progress_card(running=False)

    # Итоговый лог
    lines = []
    lines.append(f"📝 <b>Всего вступлений без капчи: {sum(len(b['no_captcha']) for _, b in summary)}</b>\n")
    lines.append(f"🤖 С капчей: {sum(len(b['with_captcha']) for _, b in summary)}")
    lines.append(f"⏳ Заявок отправлено: {sum(len(b['requested']) for _, b in summary)}")
    lines.append(f"❌ Ошибок: {sum(len(b['fail']) for _, b in summary)}\n")
    fb = len(frozen_account_ids | banned_account_ids)
    lines.append(f"🚫 Аккаунтов заморожено/забанено: {fb}")
    if frozen_account_ids:
        lines.append(f"Заморожены: {', '.join(map(str, sorted(frozen_account_ids)))}")
    if banned_account_ids:
        lines.append(f"Забанены: {', '.join(map(str, sorted(banned_account_ids)))}")
    for acc_id, blocks in summary:
        lines.append(f"\n<b>Аккаунт ID {acc_id}</b>:\n")
        if blocks["no_captcha"]:
            lines.append("✅ Без капчи:\n" + "\n".join(blocks["no_captcha"]))
        if blocks["with_captcha"]:
            lines.append("🤖 С капчей:\n" + "\n".join(blocks["with_captcha"]))
        if blocks["requested"]:
            lines.append("⏳ Заявка на вступление (ожидание одобрения):\n" + "\n".join(blocks["requested"]))
        if blocks["fail"]:
            lines.append("❌ Ошибки:\n" + "\n".join(f"{l} — {e}" for l, e in blocks["fail"]))
    if remaining_groups:
        lines.append("\n❌ <b>Не обработаны (не хватило рабочих аккаунтов):</b>")
        lines += remaining_groups

    buf = BufferedInputFile("\n".join(lines).encode("utf-8"), filename="join_groups_log.txt")
    await message.answer_document(buf, caption="Лог задачи", reply_markup=join_groups_log_keyboard())
    await state.clear()


@router.callback_query(F.data.startswith("join_refresh_"))
async def join_refresh(cb: types.CallbackQuery):
    try:
        task_id = int(cb.data.split("_")[-1])
    except Exception:
        await cb.answer("Некорректный ID задачи", show_alert=True)
        return

    task = get_task_by_id(task_id)
    if not task:
        await cb.answer("Задача не найдена", show_alert=True)
        return

    payload = task.get("payload") or {}
    data = {
        "task_id":        task_id,
        "status":         payload.get("status", "🟡 В процессе"),
        "total_accounts": int(payload.get("total_accounts", 0) or 0),
        "total_groups":   int(payload.get("total_groups", 0) or 0),
        "success_joins":  int(payload.get("success_joins", 0) or 0),
        "captcha_joins":  int(payload.get("captcha_joins", 0) or 0),
        "pending_joins":  int(payload.get("pending_joins", 0) or 0),
        "failed_joins":   int(payload.get("failed_joins", 0) or 0),
        "frozen_accounts":int(payload.get("frozen_accounts", 0) or 0),
        "avg_delay":      int(payload.get("avg_delay", 0) or 0),
        "total_time":     payload.get("total_time", "0 мин"),
    }

    text, kb = create_join_groups_task_card(data)

    # на всякий случай — телега ограничивает ~4096 символов
    if len(text) > 4000:
        text = text[:3980] + "\n…(укорочено)"

    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await cb.answer("Обновлено")
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            await cb.answer("Уже актуально ✨")
            return
        # любые прочие ошибки — короткий ответ, чтобы не словить MESSAGE_TOO_LONG
        await cb.answer(_cb_text(f"Не удалось обновить: {e}"), show_alert=False)
    except Exception as e:
        await cb.answer(_cb_text(f"Ошибка: {e}"), show_alert=False)