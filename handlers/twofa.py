# handlers/twofa.py
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from telethon.tl import functions
from app.fsm.twofa_states import TwoFAStates
from app.db import get_all_accounts, get_account_by_id, read_twofa_task, read_twofa_logs, create_twofa_task, count_twofa_logs
from telethon import errors as tl_errors
from .twofa_task_view import create_twofa_task_card
from typing import List, Dict, Any, Set
from aiogram.exceptions import TelegramBadRequest
from app.db import get_account_groups_with_count   # добавь рядом с get_all_accounts

# Исполнитель и создание записи задачи в БД подключим внутри хендлеров, чтобы избежать циклических импортов

twofa_router = Router()

# =========================
# ЛОКАЛЬНЫЕ КЛАВИАТУРЫ
# =========================

async def _safe_edit_markup(msg, kb):
    try:
        await msg.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


def accounts_picker_keyboard(
    accounts: List[Dict[str, Any]],
    selected_ids: Set[int] | list[int] | None = None,
    page: int = 0,
    per_page: int = 10,
    prefix: str = "accpick",
    groups: List[Dict[str, Any]] | None = None,   # ← НОВОЕ
) -> InlineKeyboardMarkup:
    if selected_ids is None:
        selected_ids = set()
    else:
        selected_ids = set(selected_ids)

    start = page * per_page
    chunk = accounts[start:start + per_page]

    rows = []
    for acc in chunk:
        acc_id = acc["id"]
        uname = acc.get("username") or "-"
        phone = acc.get("phone") or "-"
        mark = "✅" if acc_id in selected_ids else "⏹️"
        txt = f"{mark} {acc_id} ▸ @{uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"{prefix}_toggle_{acc_id}")])

    # пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}_page_{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}_page_{page+1}"))
    if nav:
        rows.append(nav)

    # «чипсы» групп (если есть)
    chips: list[InlineKeyboardButton] = []
    if groups:
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue
            name = f"{g.get('emoji', '')} {g.get('name', '')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}_group_{g['id']}"))

    for i in range(0, len(chips), 3):
        rows.append(chips[i:i+3])

    # массовые действия
    rows.append([
        InlineKeyboardButton(text="Выбрать все", callback_data=f"{prefix}_select_all"),
        InlineKeyboardButton(text="Снять все",   callback_data=f"{prefix}_clear_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="Далее ➜", callback_data=f"{prefix}_proceed"),
        InlineKeyboardButton(text="Отмена",   callback_data="menu_tasks"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def kb_mode():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Установить новый 2FA", callback_data="twofa:mode:new")],
        [InlineKeyboardButton(text="♻️ Заменить существующий 2FA", callback_data="twofa:mode:replace")],
        [InlineKeyboardButton(text="🙅 Ничего не делать с паролем", callback_data="twofa:mode:none")],
        [InlineKeyboardButton(text="⬅️ Назад к выбору аккаунтов", callback_data="twofa:back:accounts")],
    ])


def kb_kill_sessions():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить остальные сессии", callback_data="twofa:kill:yes")],
        [InlineKeyboardButton(text="❌ Не удалять", callback_data="twofa:kill:no")],
        [InlineKeyboardButton(text="⬅️ Назад к режиму", callback_data="twofa:back:mode")],
    ])


def kb_confirm():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить", callback_data="twofa:start")],
        [InlineKeyboardButton(text="❎ Отмена", callback_data="twofa:cancel")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="twofa:back:kill")],
    ])


# =========================
# ВХОД В ЗАДАЧУ И ВЫБОР АККАУНТОВ
# =========================
# Запуск 2FA из меню задач (кнопка "tasktype_twofa")
@twofa_router.callback_query(F.data == "tasktype_twofa")
async def twofa_from_tasks_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TwoFAStates.SELECT_ACCOUNTS)
    accounts = get_all_accounts()
    groups = get_account_groups_with_count()   # ← НОВОЕ
    await state.update_data(accounts=accounts, selected_accounts=[], page=0)
    kb = accounts_picker_keyboard(accounts, set(), page=0, groups=groups)  # ← НОВОЕ
    await cb.message.edit_text("🔐 Выбери аккаунты для задачи 2FA:", reply_markup=kb)
    await cb.answer()


# Показ лога из карточки (кнопка "twofa:log:{task_id}")
@twofa_router.callback_query(F.data.startswith("twofa:log:"))
async def twofa_show_log(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[2])
    from app.db import read_twofa_task, read_twofa_logs

    task = read_twofa_task(task_id)
    logs = read_twofa_logs(task_id, limit=5000)

    lines = []
    lines.append(f"Task #{task_id} | mode={task.get('mode')} | kill_other={task.get('kill_other')}")
    lines.append(f"status={task.get('status')} started={task.get('started_at')} finished={task.get('finished_at')}")
    lines.append(f"new_pw={task.get('new_password') or ''}")
    lines.append(f"old_pw={task.get('old_password') or ''}")
    lines.append("")
    for row in logs:
        lines.append(
            f"[{row['ts']}] {row['username'] or row['account_id']}: "
            f"{'OK' if row['ok'] else 'ERR'} | removed={row['removed_other']} | {row['message']}"
        )
    content = "\n".join(lines).encode("utf-8")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ОК (Удалить лог)", callback_data=f"twofa:logdel:{task_id}")]
    ])

    await cb.message.answer_document(
        BufferedInputFile(content, filename=f"twofa_task_{task_id}.log.txt"),
        caption=f"Лог задачи 2FA #{task_id}",
        reply_markup=kb
    )
    await cb.answer()
    
@twofa_router.callback_query(F.data.startswith("twofa:logdel:"))
async def twofa_delete_log_message(cb: CallbackQuery):
    try:
        await cb.message.delete()
        await cb.answer("✅ Лог удалён")
    except Exception:
        # если удалить нельзя (старое сообщение/нет прав) — просто уберём кнопки
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.answer("⚠️ Не удалось удалить сообщение, снял кнопки.")

# Повтор запуска задачи с теми же настройками (кнопка "twofa:repeat:{task_id}")
@twofa_router.callback_query(F.data.startswith("twofa:repeat:"))
async def twofa_repeat(cb: CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split(":")[2])
    
    

    task = read_twofa_task(task_id)
    if not task:
        await cb.answer("Задача не найдена", show_alert=True)
        return

    mode = task.get("mode")
    kill_other = bool(task.get("kill_other"))
    new_pw = task.get("new_password")
    old_pw = task.get("old_password")
    accounts = task.get("accounts_json") or []

    # карточка
    await cb.message.edit_text(
        f"🔐 Повтор 2FA #{task_id}\n"
        f"Аккаунтов: {len(accounts)}\n"
        f"Режим: {('Новый' if mode=='new' else 'Замена')}\n"
        f"Удалить сессии: {'Да' if kill_other else 'Нет'}\n\n"
        "Статус: запускается..."
    )

    # повторное выполнение (можно создавать новую запись в twofa_tasks, если хочешь вести историю повторов отдельно)
    await run_twofa_task(task_id, accounts, mode, new_pw, old_pw, kill_other)
    await cb.answer("Перезапуск выполнен")


@twofa_router.message(F.text == "🔐 2FA (установить/сменить)")
async def twofa_entry(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(TwoFAStates.SELECT_ACCOUNTS)
    accounts = get_all_accounts()
    groups = get_account_groups_with_count()   # ← НОВОЕ
    await state.update_data(accounts=accounts, selected_accounts=[], page=0)
    kb = accounts_picker_keyboard(accounts, set(), page=0, groups=groups)   # ← НОВОЕ
    await message.answer("🔐 Выбери аккаунты для задачи 2FA:", reply_markup=kb)



@twofa_router.callback_query(F.data.startswith("accpick_toggle_"), TwoFAStates.SELECT_ACCOUNTS)
async def accpick_toggle(cb: CallbackQuery, state: FSMContext):
    acc_id = int(cb.data.split("_")[-1])
    data = await state.get_data()
    selected = set(data.get("selected_accounts", []))
    accounts = data.get("accounts", [])
    page = int(data.get("page", 0))

    if acc_id in selected: selected.remove(acc_id)
    else: selected.add(acc_id)

    await state.update_data(selected_accounts=list(selected))
    kb = accounts_picker_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
    await _safe_edit_markup(cb.message, kb)
    await cb.answer()




# пагинация
@twofa_router.callback_query(F.data.startswith("accpick_page_"), TwoFAStates.SELECT_ACCOUNTS)
async def accpick_page(cb: CallbackQuery, state: FSMContext):
    page = int(cb.data.split("_")[-1])
    data = await state.get_data()
    accounts = data.get("accounts", [])
    selected = set(data.get("selected_accounts", []))
    await state.update_data(page=page)
    kb = accounts_picker_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
    await _safe_edit_markup(cb.message, kb)
    await cb.answer()


# выбрать все (без тоггла — просто выбираем всех на всей выборке)
@twofa_router.callback_query(F.data == "accpick_select_all", TwoFAStates.SELECT_ACCOUNTS)
async def accpick_select_all(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    all_ids = [a["id"] for a in accounts]
    page = int(data.get("page", 0))
    await state.update_data(selected_accounts=all_ids)
    kb = accounts_picker_keyboard(accounts, set(all_ids), page=page, groups=get_account_groups_with_count())
    await _safe_edit_markup(cb.message, kb)
    await cb.answer("✅ Выбраны все аккаунты")


# снять все
@twofa_router.callback_query(F.data == "accpick_clear_all", TwoFAStates.SELECT_ACCOUNTS)
async def accpick_clear_all(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    page = int(data.get("page", 0))
    await state.update_data(selected_accounts=[])
    kb = accounts_picker_keyboard(accounts, set(), page=page, groups=get_account_groups_with_count())
    await _safe_edit_markup(cb.message, kb)
    await cb.answer("♻️ Сброшен выбор")




@twofa_router.callback_query(F.data == "accpick_proceed", TwoFAStates.SELECT_ACCOUNTS)
async def accpick_proceed(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_accounts", [])
    if not selected:
        await cb.answer("⚠️ Выбери хотя бы один аккаунт", show_alert=True)
        return
    await state.set_state(TwoFAStates.CHOOSE_MODE)
    await cb.message.edit_text("Режим задачи:", reply_markup=kb_mode())
    await cb.answer()

@twofa_router.callback_query(F.data.startswith("accpick_group_"), TwoFAStates.SELECT_ACCOUNTS)
async def accpick_group_pick(cb: CallbackQuery, state: FSMContext):
    group_id = int(cb.data.split("_")[-1])
    data = await state.get_data()
    accounts = data.get("accounts", [])  # важно: в accounts должны быть group_id
    page = int(data.get("page", 0))

    ids_in_group = {a["id"] for a in accounts if a.get("group_id") == group_id}
    if not ids_in_group:
        await cb.answer("В этой группе нет аккаунтов")
        return

    await state.update_data(selected_accounts=list(ids_in_group))

    # на текущей странице изменилось? (микро-оптимизация)
    start = page * 10
    page_ids = {a["id"] for a in accounts[start:start+10]}
    changed_on_page = bool(ids_in_group & page_ids)

    kb = accounts_picker_keyboard(accounts, ids_in_group, page=page, groups=get_account_groups_with_count())
    if changed_on_page:
        await _safe_edit_markup(cb.message, kb)

    await cb.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")


# =========================
# НАЗАД ПО ШАГАМ
# =========================

@twofa_router.callback_query(F.data.startswith("twofa:back:"))
async def twofa_back(cb: CallbackQuery, state: FSMContext):
    kind = cb.data.split(":")[2]
    if kind == "accounts":
        await state.set_state(TwoFAStates.SELECT_ACCOUNTS)
        data = await state.get_data()
        accounts = data.get("accounts", [])
        selected = data.get("selected_accounts", [])
        page = int(data.get("page", 0))
        kb = accounts_picker_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
        await cb.message.edit_text("🔐 Выбери аккаунты для задачи 2FA:", reply_markup=kb)
    ...
    await cb.answer()



# =========================
# ВЫБОР РЕЖИМА → ВВОД ПАРОЛЕЙ → УДАЛЕНИЕ СЕССИЙ
# =========================

@twofa_router.callback_query(F.data.startswith("twofa:mode:"), TwoFAStates.CHOOSE_MODE)
async def choose_mode(cb: CallbackQuery, state: FSMContext):
    mode = cb.data.split(":")[2]  # new | replace
    await state.update_data(mode=mode)

    # Подготавливаем текст и клавиатуру
    text = ""
    reply_markup = None

    if mode == "replace":
        await state.set_state(TwoFAStates.ASK_OLD)
        text = "Введи СТАРЫЙ 2FA пароль (текстом).\n\n🔒 Сообщение будет удалено после чтения."
    elif mode == "new":
        await state.set_state(TwoFAStates.ASK_NEW)
        text = "Введи НОВЫЙ 2FA пароль (текстом).\n\n🔒 Сообщение будет удалено после чтения."
    else:
        await state.set_state(TwoFAStates.ASK_KILL)
        text = "Пароль трогать не будем.\n\nУдалять остальные сессии?"
        reply_markup = kb_kill_sessions()

    # Редактируем сообщение и СОХРАНЯЕМ его message_id в FSM
    try:
        edited_msg = await cb.message.edit_text(text, reply_markup=reply_markup)
        await state.update_data(
            main_message_id=edited_msg.message_id,
            chat_id=cb.message.chat.id  # на всякий случай сохраняем chat_id
        )
    except Exception as e:
        print(f"[2FA] WARN: не удалось сохранить main_message_id: {e}")
        # Но всё равно продолжаем — fallback будет в хендлерах

    await cb.answer()


@twofa_router.message(TwoFAStates.ASK_OLD)
async def ask_old_handler(message: Message, state: FSMContext):
    old_pw = (message.text or "").strip()
    await state.update_data(old_password=old_pw)
    try:
        await message.delete()  # ✅ удаляем сообщение с паролем — это правильно
    except:
        pass

    # Получаем главное сообщение из FSM
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")

    if main_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=main_msg_id,
                text="Теперь введи НОВЫЙ 2FA пароль.\n\n🔒 Сообщение будет удалено после чтения."
            )
        except Exception as e:
            print(f"[2FA] WARN: не удалось обновить главное сообщение: {e}")
            # fallback — если что-то пошло не так, отправим новое (но лучше избегать)
            await message.answer("Теперь введи НОВЫЙ 2FA пароль.\n\n🔒 Сообщение будет удалено после чтения.")
    else:
        # fallback — если main_message_id не сохранился (например, баг), отправим новое
        await message.answer("Теперь введи НОВЫЙ 2FA пароль.\n\n🔒 Сообщение будет удалено после чтения.")

    await state.set_state(TwoFAStates.ASK_NEW)


@twofa_router.message(TwoFAStates.ASK_NEW)
async def ask_new_handler(message: Message, state: FSMContext):
    new_pw = (message.text or "").strip()
    await state.update_data(new_password=new_pw)
    try:
        await message.delete()  # ✅ удаляем сообщение с паролем
    except:
        pass

    # Получаем главное сообщение из FSM
    data = await state.get_data()
    main_msg_id = data.get("main_message_id")

    if main_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=main_msg_id,
                text="Удалять остальные сессии?",
                reply_markup=kb_kill_sessions()
            )
        except Exception as e:
            print(f"[2FA] WARN: не удалось обновить главное сообщение: {e}")
            await message.answer("Удалять остальные сессии?", reply_markup=kb_kill_sessions())
    else:
        await message.answer("Удалять остальные сессии?", reply_markup=kb_kill_sessions())

    await state.set_state(TwoFAStates.ASK_KILL)


@twofa_router.callback_query(F.data.startswith("twofa:kill:"), TwoFAStates.ASK_KILL)
async def choose_kill(cb: CallbackQuery, state: FSMContext):
    kill = cb.data.endswith(":yes")
    await state.update_data(kill_other=kill)
    data = await state.get_data()
    mode = data.get("mode")

    # 🔒 защита: если выбран режим "ничего не делать" и при этом "не удалять", то возвращаем к выбору режима
    if mode == "none" and not kill:
        await state.set_state(TwoFAStates.CHOOSE_MODE)
        await cb.message.edit_text(
            "Ты выбрал режим «ничего не делать с паролем» и «не удалять сессии» — запускать нечего.\n\nВыбери режим:",
            reply_markup=kb_mode()
        )
        await cb.answer("Нечего выполнять — вернул к выбору режима", show_alert=False)
        return

    masked_old = "•" * len(data.get("old_password", "") or "")
    masked_new = "•" * len(data.get("new_password", "") or "")

    # Текст подтверждения под разные режимы
    if mode == "none":
        details = "• Пароль: без изменений\n"
    elif mode == "new":
        details = f"• Старый 2FA: —\n• Новый 2FA: {masked_new}\n"
    else:
        details = f"• Старый 2FA: {masked_old}\n• Новый 2FA: {masked_new}\n"

    text = (
        "Проверь настройки задачи 2FA:\n"
        f"• Режим: {'🙅‍♂️ Без изменений' if mode=='none' else ('🆕 Новый' if mode=='new' else '♻️ Замена')}\n"
        f"• Удалить прочие сессии: {'Да' if kill else 'Нет'}\n"
        f"{details}\n"
        "Нажми «Запустить», чтобы стартовать."
    )

    await state.set_state(TwoFAStates.CONFIRM)
    await cb.message.edit_text(text, reply_markup=kb_confirm())
    await cb.answer()



@twofa_router.callback_query(F.data == "twofa:cancel", TwoFAStates.CONFIRM)
async def twofa_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Задача 2FA отменена.", reply_markup=None)
    await cb.answer()


# =========================
# СТАРТ ВЫПОЛНЕНИЯ
# =========================
@twofa_router.callback_query(F.data == "twofa:start", TwoFAStates.CONFIRM)
async def twofa_start(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_ids = data.get("selected_accounts", [])
    mode = data["mode"]
    kill_other = bool(data.get("kill_other"))
    new_pw = data.get("new_password")
    old_pw = data.get("old_password")
    
    # доп. защита: если вдруг сюда дошли в режиме "none" и kill_other=False — вернуть на выбор режима
    if mode == "none" and not kill_other:
        await state.set_state(TwoFAStates.CHOOSE_MODE)
        await cb.message.edit_text(
            "Ты выбрал «ничего не делать с паролем» и «не удалять сессии» — выполнять нечего.\n\nВыбери режим:",
            reply_markup=kb_mode()
        )
        await cb.answer()
        return

    # 1) Для БД: лёгкая шапка аккаунтов
    accounts_meta = []
    # 2) Для исполнения: полный набор (session + proxy)
    accounts_runtime = []

    for acc_id in selected_ids:
        acc = get_account_by_id(acc_id)
        if not acc:
            continue

        # в БД
        accounts_meta.append({
            "account_id": acc_id,
            "username": acc.get("username")
        })

        # в исполнитель
        accounts_runtime.append({
            "account_id": acc_id,
            "username": acc.get("username") or acc.get("phone") or f"id:{acc_id}",
            "session_string": acc.get("session_string"),
            # если у тебя другие поля прокси — подставь их здесь
            "proxy_host": acc.get("proxy_host"),
            "proxy_port": acc.get("proxy_port"),
            "proxy_username": acc.get("proxy_username"),
            "proxy_password": acc.get("proxy_password"),
        })

    
    task_id = create_twofa_task(
        user_id=cb.from_user.id,
        mode=mode,
        kill_other=kill_other,
        accounts=accounts_meta,            # <-- в БД уходит лёгкая версия
        new_password=new_pw,
        old_password=old_pw if mode == "replace" else None
    )

    await state.set_state(TwoFAStates.RUNNING)
    # соберём данные для карточки
    task_row = read_twofa_task(task_id)
    logs_cnt = count_twofa_logs(task_id)

    task_for_card = {
        "id": task_row["id"],
        "status": task_row["status"],
        "created_at": task_row["created_at"],
        "started_at": task_row["started_at"],
        "payload": {
            "mode": task_row["mode"],
            "kill_other": task_row["kill_other"],
            "accounts": task_row.get("accounts_json") or [],
            "new_password": task_row.get("new_password"),
            "old_password": task_row.get("old_password"),
            "logs_cnt": logs_cnt,
        }
    }

    text, kb = create_twofa_task_card(task_for_card)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    
    # В исполнитель отдаём ПОЛНУЮ версию
    await _run_twofa_inline(task_id, accounts_runtime, mode, new_pw, old_pw, kill_other, cb.message)
    await state.clear()


async def _run_twofa_inline(task_id: int,
                            accounts: list[dict],
                            mode: str,
                            new_pw: str,
                            old_pw: str | None,
                            kill_other: bool,
                            progress_msg):
    """
    Мини-исполнитель: печатает в консоль, пишет в БД (если есть DAO),
    и обновляет сообщение прогресса.
    """
    print(f"[2FA] START task#{task_id} mode={mode} kill_other={kill_other} accs={len(accounts)}")

    # --- безопасные врапперы для БД (если нет функций — молча пропускаем) ---
    async def _set_status(status: str, started=False, finished=False):
        try:
            from app.db import set_twofa_task_status
            set_twofa_task_status(task_id, status, started, finished)
        except Exception as e:
            print(f"[2FA] WARN set_status({status}) failed: {e}")

    async def _log_row(acc_id: int, username: str, ok: bool, removed_other: bool, message: str):
        try:
            from app.db import add_twofa_log
            add_twofa_log(task_id, acc_id, username, ok, removed_other, message)
        except Exception as e:
            print(f"[2FA] WARN add_twofa_log failed: {e} | {username}: {message}")

    await _set_status("running", started=True)

    # --- помощник: получить Telethon-клиент, работая с разными сигнатурами get_client ---
    async def _get_client_for_account(acc: dict):
        from app.telegram_client import get_client as _gc

        session_string = acc.get("session_string")
        if not session_string:
            raise RuntimeError("session_string is empty for account")

        proxy = None
        if acc.get("proxy_host"):
            proxy = {
                "proxy_host": acc.get("proxy_host"),
                "proxy_port": acc.get("proxy_port"),
                "proxy_username": acc.get("proxy_username"),
                "proxy_password": acc.get("proxy_password"),
            }

        # Предполагаем сигнатуру get_client(session_string, proxy)
        client = _gc(session_string, proxy)
        if asyncio.iscoroutine(client):
            client = await client

        try:
            await client.start()
        except Exception:
            try:
                await client.connect()
            except Exception:
                pass

        return client


    ok_count = 0
    total = len(accounts)
    per_batch = 5
    processed = 0

    # Для итогового локального лога на случай, если в БД логов нет
    local_lines = []

    async def _handle_one(acc: dict) -> bool:
        acc_id = acc.get("account_id") or acc.get("id")
        username = acc.get("username") or f"id:{acc_id}"
        removed = False
        
        if not acc.get("session_string"):
            msg = "session_string is missing"
            print(f"[2FA] [{username}] ERROR: {msg}")
            await _log_row(acc_id, username, False, removed, msg)
            return False
        
        try:
            client = await _get_client_for_account(acc)
            print(f"[2FA] [{username}] client ready")

            # 👇 только если режим не "none" — трогаем 2FA
            if mode == "new":
                await client.edit_2fa(new_password=new_pw)
                print(f"[2FA] [{username}] set NEW 2FA")
            elif mode == "replace":
                await client.edit_2fa(new_password=new_pw, current_password=old_pw)
                print(f"[2FA] [{username}] REPLACE 2FA")
            else:
                print(f"[2FA] [{username}] password unchanged (mode=none)")

            
            if kill_other:
                await client(functions.auth.ResetAuthorizationsRequest())
                removed = True
                print(f"[2FA] [{username}] other sessions RESET")

            try:
                await client.disconnect()
            except Exception:
                pass

            await _log_row(acc_id, username, True, removed, "ok")
            local_lines.append(f"{username}: OK removed={removed}")
            return True
        

        except Exception as e:
            user_friendly = None

            # 1) Неверный старый пароль → FloodWait/PasswordHashInvalid
            if mode == "replace":
                if isinstance(e, tl_errors.FloodWaitError):
                    # после неверного current_password Telegram часто даёт FloodWait на UpdatePasswordSettings
                    user_friendly = (
                        "Введён неверный старый 2FA-пароль. "
                        "Уточните пароль у вашего продавца и попробуйте снова."
                    )
                elif isinstance(e, tl_errors.PasswordHashInvalidError):
                    user_friendly = (
                        "Введён неверный старый 2FA-пароль. "
                        "Уточните пароль у вашего продавца и попробуйте снова."
                    )
                else:
                    # запасной вариант — распознаём по тексту
                    msg_low = str(e).lower()
                    if "updatepasswordsettingsrequest" in msg_low and "wait of" in msg_low:
                        user_friendly = (
                            "Введён неверный старый 2FA-пароль. "
                            "Уточните пароль у вашего продавца и попробуйте снова."
                        )

            # 2) Слишком частые изменения 2FA (на всякий случай)
            if user_friendly is None and isinstance(e, tl_errors.FloodWaitError):
                secs = getattr(e, "seconds", None)
                if secs:
                    mins = round(secs / 60)
                    user_friendly = f"Слишком часто меняете настройки 2FA. Подождите ~{mins} мин. и повторите."
                else:
                    user_friendly = "Слишком частые изменения 2FA. Подождите и повторите попытку."

            # 3) Парсим текст ошибки, если user_friendly всё ещё None
            if user_friendly is None:
                err_text = str(e)
                # Парсим "A wait of X seconds is required..."
                if "A wait of" in err_text and "seconds is required" in err_text and "UpdatePasswordSettingsRequest" in err_text:
                    import re
                    match = re.search(r"A wait of (\d+) seconds is required", err_text)
                    if match:
                        secs = int(match.group(1))
                        mins = round(secs / 60)
                        user_friendly = f"Слишком много попыток, повторите попытку смены пароля через {secs} секунд(ы). (~{mins} мин.)"

                # Парсим "The password ... you entered is invalid..."
                elif "The password (and thus its hash value) you entered is invalid" in err_text and "UpdatePasswordSettingsRequest" in err_text:
                    user_friendly = "Введён неверный старый пароль, уточните пароль у Вашего продавца и попробуйте снова."

            # Если не распознали — оставим оригинальный текст
            msg = user_friendly or str(e)

            print(f"[2FA] [{username}] ERROR: {msg}")
            await _log_row(acc_id, username, False, removed, msg)
            local_lines.append(f"{username}: ERR removed={removed} | {msg}")
            return False

    # --- батч-параллель ---
    for i in range(0, total, per_batch):
        batch = accounts[i:i+per_batch]
        results = await asyncio.gather(*[_handle_one(a) for a in batch], return_exceptions=False)
        ok_count += sum(1 for r in results if r)
        processed = min(i + per_batch, total)
        #try:
            #await progress_msg.edit_text(
                #f"🔐 Задача 2FA #{task_id}\n"
                #f"Прогресс: {processed}/{total}\n"
                #f"Успешно: {ok_count}, Ошибок: {processed - ok_count}"
            #)
        #except Exception:
            #pass

    status = "done" if ok_count == total else ("error" if ok_count == 0 else "done")
    await _set_status(status, finished=True)
    print(f"[2FA] DONE task#{task_id} ok={ok_count}/{total} status={status}")

    # Попробуем вытащить логи/шапку из БД; если нет – пошлём локальный лог
    try:
        
        task_row = read_twofa_task(task_id)
        logs = read_twofa_logs(task_id, limit=5000)
        lines = []
        lines.append(f"Task #{task_id} | mode={task_row.get('mode')} | kill_other={task_row.get('kill_other')}")
        lines.append(f"status={task_row.get('status')} started={task_row.get('started_at')} finished={task_row.get('finished_at')}")
        lines.append(f"new_pw={task_row.get('new_password') or ''}")
        lines.append(f"old_pw={task_row.get('old_password') or ''}")
        lines.append("")
        for row in logs:
            lines.append(f"[{row['ts']}] {row['username'] or row['account_id']}: "
                         f"{'OK' if row['ok'] else 'ERR'} | removed={row['removed_other']} | {row['message']}")
        content = "\n".join(lines).encode("utf-8")
    except Exception as e:
        print(f"[2FA] WARN build DB log failed: {e} -> send local log")
        content = ("\n".join(local_lines)).encode("utf-8")

    # шлём TXT
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ОК (Удалить лог)", callback_data=f"twofa:logdel:{task_id}")]
    ])
    try:
        await progress_msg.answer_document(
            BufferedInputFile(content, filename=f"twofa_task_{task_id}.log.txt"),
            caption=f"Лог задачи 2FA #{task_id}",
            reply_markup=kb
        )
    except Exception as e:
        await progress_msg.answer(f"❌ Не удалось отправить лог: {e}")

    # финалка
    #try:
        #await progress_msg.answer(
            #f"✅ Завершено. Успешно: {ok_count}/{total}. "
            #f"{'Сессии удалены' if kill_other else 'Сессии не удалялись'}."
        #)
    #except Exception:
        #pass

@twofa_router.callback_query(F.data.startswith("refresh_twofa_task_"))
async def refresh_twofa_task(cb: CallbackQuery):
    task_id = int(cb.data.split("_")[-1])
    

    task = read_twofa_task(task_id)
    if not task:
        await cb.answer("⚠️ Задача не найдена.", show_alert=True)
        return

    logs_cnt = count_twofa_logs(task_id)
    task_for_card = {
        "id": task["id"],
        "status": task["status"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "payload": {
            "mode": task["mode"],
            "kill_other": task["kill_other"],
            "accounts": task.get("accounts_json") or [],
            "new_password": task.get("new_password"),
            "old_password": task.get("old_password"),
            "logs_cnt": logs_cnt,
        }
    }
    text, kb = create_twofa_task_card(task_for_card)
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        # безопасно игнорируем "message is not modified"
        pass
    await cb.answer("Обновлено ✅")

# 1) Показываем подтверждение (ловим только twofa:delete:<id>)
@twofa_router.callback_query(F.data.regexp(r"^twofa:delete:\d+$"))
async def twofa_delete_confirm(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[2])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"refresh_twofa_task_{task_id}"),
            InlineKeyboardButton(text="🗑 Подтвердить удаление", callback_data=f"twofa:delete:yes:{task_id}"),
        ]
    ])
    await cb.message.edit_text(
        f"⚠️ Удалить задачу 2FA #{task_id}? Это действие необратимо.",
        reply_markup=kb
    )
    await cb.answer()


# 2) Реальное удаление (ловим только twofa:delete:yes:<id>)
@twofa_router.callback_query(F.data.regexp(r"^twofa:delete:yes:\d+$"))
async def twofa_delete_do(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[3])
    from app.db import get_connection
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM public.twofa_tasks WHERE id=%s", (task_id,))
        deleted = cur.rowcount or 0
        conn.commit()
    finally:
        cur.close(); conn.close()

    if deleted:
        await cb.message.edit_text(
            f"🗑️ Задача 2FA #{task_id} удалена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 К списку задач", callback_data="menu_task_execution")]
            ])
        )
        await cb.answer("Готово ✅")
    else:
        await cb.message.edit_text(
            f"⚠️ Задача 2FA #{task_id} не найдена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_task_execution")]
            ])
        )
        await cb.answer("Не найдено", show_alert=True)





# совместимость с импортом из handlers/__init__.py
router = twofa_router
