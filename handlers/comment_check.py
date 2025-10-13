import asyncio, json, re, os, time
from typing import List, Dict, Any
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from utils.check_access import admin_only
from utils.comment_check_utils import run_comment_check, safe_run_comment_check
from app.db import (
    get_all_accounts,
    get_account_groups_with_count,
    create_comment_check_task,
    update_task_status,
    save_task_result,
    get_connection,
    get_task_by_id, 
    get_comment_check_logs,
)
from keyboards.comment_check_accounts_keyboard import cchk_accounts_keyboard
from aiogram.exceptions import TelegramBadRequest

router = Router()

class CChkStates(StatesGroup):
    picking_accounts = State()
    waiting_channels  = State()
    confirming       = State()

MAX_TEXT_LINES = 200
TEMP_DIR = "/tmp"
TEMP_DIR = os.getenv("TMPDIR", "/tmp")


async def _read_txt_lines(path: str) -> list[str]:
    """
    Читает .txt в отдельном потоке, возвращает список непустых строк без переводов.
    """
    import asyncio
    def _read():
        out = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s:
                    out.append(s)
        return out
    return await asyncio.to_thread(_read)

def _ok_delete_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ ОК (удалить)", callback_data="cchk_delete_log_message")]]
    )

async def _read_txt_lines(path: str) -> list[str]:
    def _read():
        out = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s:
                    out.append(s)
        return out
    import asyncio
    return await asyncio.to_thread(_read)

def _norm_channel(ch: str) -> str:
    ch = (ch or "").strip()
    if not ch:
        return ""
    ch = ch.replace("https://t.me/", "").replace("http://t.me/", "")
    if ch.startswith("@"):
        ch = ch[1:]
    # обрезаем хвосты /?...
    ch = ch.split("?")[0].split("/")[0]
    return ch



def _normalize_channel(s: str) -> str:
    s = s.strip()
    if not s:
        return ""
    s = s.replace("https://t.me/","").replace("http://t.me/","").replace("@","")
    return s.split("?")[0].strip()

# === sticky UI helpers (локальная копия для чекера) ===
async def ui_get_ids(state) -> tuple[int | None, int | None]:
    d = await state.get_data()
    return d.get("ui_chat_id"), d.get("ui_message_id")

async def ui_set_ids(state, chat_id: int, message_id: int):
    await state.update_data(ui_chat_id=chat_id, ui_message_id=message_id)

async def ui_edit(bot, chat_id: int | None, message_id: int | None,
                  text: str, kb: InlineKeyboardMarkup | None = None):
    # если идентификаторов нет — не падаем
    if not chat_id or not message_id:
        raise RuntimeError("ui_edit: no message to edit (chat_id/message_id is None)")

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception as e:
        s = str(e).lower()
        if "message is not modified" in s:
            return
        # пробрасываем дальше — пусть хендлер сделает фоллбек
        raise


async def delete_user_message(msg: types.Message):
    try:
        await msg.delete()
    except Exception:
        pass

def _cchk_card_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"cchk_refresh:{task_id}")],
        [InlineKeyboardButton(text="📤 Экспорт (с обсуждениями)", callback_data=f"cchk_export_yes:{task_id}")],
        [InlineKeyboardButton(text="📜 Полный лог", callback_data=f"cchk_export_all:{task_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
    ])

def _cchk_build_card_text(task_id: int) -> str:
    t = get_task_by_id(task_id) or {}
    status = t.get("status", "-")
    payload = t.get("payload") or {}
    if isinstance(payload, str):
        import json
        try: payload = json.loads(payload)
        except: payload = {}
    total = int(payload.get("total_channels") or 0)
    checked = int(payload.get("checked") or 0)

    # сводка по логам
    rows = get_comment_check_logs(task_id)
    yes = sum(1 for r in rows if r[2] is True)
    no  = sum(1 for r in rows if r[2] is False)
    unk = sum(1 for r in rows if r[2] is None)

    lines = [
        f"🧪 <b>Проверка обсуждений</b>",
        f"Задача #{task_id}",
        "",
        f"Статус: <b>{status}</b>",
        f"Прогресс: <b>{checked}/{total}</b>",
        f"Есть обсуждения: <b>{yes}</b>",
        f"Нет обсуждений: <b>{no}</b>",
        f"Неопределено/ошибки: <b>{unk}</b>",
    ]
    return "\n".join(lines)

async def render_cchk_task(bot, chat_id: int, message_id: int, task_id: int):
    text = _cchk_build_card_text(task_id)
    kb = _cchk_card_kb(task_id)
    await ui_edit(bot, chat_id, message_id, text, kb)

@router.callback_query(F.data == "menu_check_comments")
@admin_only
async def cchk_entry(cb: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts()
    groups = get_account_groups_with_count()

    # was: await state.set_state(CChkStates.selecting_accounts)
    await state.set_state(CChkStates.picking_accounts)

    await ui_set_ids(state, cb.message.chat.id, cb.message.message_id)
    await state.update_data(cchk_accounts=accounts, cchk_selected=[], cchk_page=0)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выберите аккаунты для проверки каналов:",
        cchk_accounts_keyboard(accounts, set(), page=0, groups=groups)
    )
    await cb.answer()


# переключение одного аккаунта
@router.callback_query(F.data.startswith("cchk_toggle:"), CChkStates.picking_accounts)
@admin_only
async def cchk_toggle(cb: types.CallbackQuery, state: FSMContext):
    acc_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("cchk_selected", []))
    accounts = data.get("cchk_accounts", [])
    page = int(data.get("cchk_page", 0))

    if acc_id in selected:
        selected.remove(acc_id)
    else:
        selected.add(acc_id)
    await state.update_data(cchk_selected=list(selected))

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выберите аккаунты:",
        cchk_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
    )
    await cb.answer()

# пагинация
@router.callback_query(F.data.startswith("cchk_page:"),   CChkStates.picking_accounts)
@admin_only
async def cchk_page(cb: types.CallbackQuery, state: FSMContext):
    page = int(cb.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get("cchk_accounts", [])
    selected = set(data.get("cchk_selected", []))
    await state.update_data(cchk_page=page)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выберите аккаунты:",
        cchk_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
    )
    await cb.answer()
    
# выбрать все
@router.callback_query(F.data == "cchk_select_all",       CChkStates.picking_accounts)
@admin_only
async def cchk_select_all(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("cchk_accounts", [])
    all_ids = [a["id"] for a in accounts]
    page = int(data.get("cchk_page", 0))
    await state.update_data(cchk_selected=all_ids)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Все аккаунты выбраны. Нажмите «Далее».",
        cchk_accounts_keyboard(accounts, set(all_ids), page=page, groups=get_account_groups_with_count())
    )
    await cb.answer("✅ Выбраны все")

# снять все
@router.callback_query(F.data == "cchk_clear_all",        CChkStates.picking_accounts)
@admin_only
async def cchk_clear_all(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("cchk_accounts", [])
    page = int(data.get("cchk_page", 0))
    await state.update_data(cchk_selected=[])

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выбор очищен. Отметьте нужные аккаунты:",
        cchk_accounts_keyboard(accounts, set(), page=page, groups=get_account_groups_with_count())
    )
    await cb.answer("♻️ Сброшен выбор")

@router.callback_query(F.data == "cchk_proceed", CChkStates.picking_accounts)
@admin_only
async def cchk_proceed(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = list(data.get("cchk_selected") or [])
    if not selected:
        await callback.answer("Выбери хотя бы один аккаунт", show_alert=True)
        return

    await state.update_data(cchk_selected=selected)
    # делаем текущее сообщение «липким»
    await ui_set_ids(state, callback.message.chat.id, callback.message.message_id)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        callback.message.bot, chat_id, message_id,
        "📥 <b>Пришли список каналов</b> (по одному в строке, @username или ссылка):\n\n"
        "<i>Пример:\n@durov\nhttps://t.me/somechannel</i>",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")]
        ])
    )

    await state.set_state(CChkStates.waiting_channels)
    await callback.answer()


# выбор группы
@router.callback_query(F.data.startswith("cchk_group:"),  CChkStates.picking_accounts)
@admin_only
async def cchk_group_pick(cb: types.CallbackQuery, state: FSMContext):
    group_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get("cchk_accounts", [])
    page = int(data.get("cchk_page", 0))

    # соберём id аккаунтов этой группы
    ids_in_group = {a["id"] for a in accounts if a.get("group_id") == group_id}
    if not ids_in_group:
        await cb.answer("В этой группе нет аккаунтов")
        return

    await state.update_data(cchk_selected=list(ids_in_group))

    # была ли смена на текущей странице?
    start = page * 10
    page_ids = {a["id"] for a in accounts[start:start+10]}
    changed_on_page = bool(ids_in_group & page_ids)

    chat_id, message_id = await ui_get_ids(state)
    kb = cchk_accounts_keyboard(accounts, ids_in_group, page=page, groups=get_account_groups_with_count())
    if changed_on_page:
        await ui_edit(cb.message.bot, chat_id, message_id, "👤 Выберите аккаунты:", kb)

    await cb.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")

@router.message(CChkStates.waiting_channels)
@admin_only
async def cchk_channels_input(message: types.Message, state: FSMContext):
    channels: list[str] = []

    # 1) Если прислали .txt файлом
    if message.document and (message.document.file_name or "").lower().endswith(".txt"):
        ts = int(time.time())
        tmp_path = os.path.join(TEMP_DIR, f"cchk_channels_{message.from_user.id}_{ts}.txt")
        try:
            # aiogram v3: скачиваем файл через bot
            await message.bot.download(message.document, destination=tmp_path)
        except Exception as e:
            await delete_user_message(message)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(message.bot, chat_id, message_id, f"❌ Не удалось скачать файл: {e}")
            return

        try:
            channels = await _read_txt_lines(tmp_path)
        except Exception as e:
            await delete_user_message(message)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(message.bot, chat_id, message_id, f"❌ Не удалось прочитать файл: {e}")
            return
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    # 2) Если прислали обычным текстом
    elif (message.text or "").strip():
        lines = [s for s in (message.text or "").splitlines() if s.strip()]
        if len(lines) > MAX_TEXT_LINES:
            await delete_user_message(message)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(
                message.bot, chat_id, message_id,
                f"⚠️ В тексте {len(lines)} строк (> {MAX_TEXT_LINES}). "
                "Пожалуйста, пришлите список каналов одним .txt файлом (по одному в строке)."
            )
            return
        channels = lines

    else:
        # Ничего подходящего не прислали
        await delete_user_message(message)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(
            message.bot, chat_id, message_id,
            "📥 Пришли список каналов (по одному в строке, @username или ссылка) или один .txt файл."
        )
        return

    # Нормализуем → username без @, фильтруем пустые/повторы, сохраняем порядок
    channels = [_normalize_channel(c) for c in channels]
    channels = [c for c in channels if c]                   # убрать пустые после нормализации
    channels = list(dict.fromkeys(channels))                # uniq, порядок сохраняем

    if not channels:
        await delete_user_message(message)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(message.bot, chat_id, message_id, "⚠️ Не найдено ни одного валидного канала. Пришли список ещё раз.")
        return

    # Успех: сохраняем в state, удаляем юзерское сообщение, рисуем подтверждение
    await state.update_data(cchk_channels=channels)
    await delete_user_message(message)

    preview = "\n".join(f"• {c}" for c in channels[:30])
    tail = f"\n… и ещё {len(channels)-30}" if len(channels) > 30 else ""
    text = f"✅ Каналы загружены ({len(channels)}):\n{preview}{tail}"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить проверку", callback_data="cchk_start")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_main")],
    ])

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(message.bot, chat_id, message_id, text, kb)

    # переходим к подтверждению
    await state.set_state(CChkStates.confirming)



# реестр задач (чтобы GC не прибил и чтобы можно было отменять при желании)
_CCHK_WORKERS: dict[int, asyncio.Task] = {}

@router.callback_query(CChkStates.confirming, F.data == "cchk_start")
@admin_only
async def cchk_start(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_ids: list[int] = list(data["cchk_selected"])
    all_accounts = data["cchk_accounts"]
    acc_map = {a["id"]: a for a in all_accounts}
    accounts = [{"id": i, "username": acc_map[i].get("username")} for i in selected_ids]
    channels = data["cchk_channels"]

    # создаём задачу
    try:
        task_id = create_comment_check_task(
            created_by=callback.from_user.id,
            channels=channels,
            accounts=accounts,
            # concurrency можно пробросить из state позже
        )
    except Exception as e:
        await callback.message.answer(f"❌ Не удалось создать задачу: {e}")
        return

    # закрепляем «липкое» сообщение
    await ui_set_ids(state, callback.message.chat.id, callback.message.message_id)
    chat_id, message_id = await ui_get_ids(state)

    # временный тост на 1–2 сек
    await ui_edit(callback.message.bot, chat_id, message_id,
                  f"🚀 Задача #{task_id} создана. Начинаю проверку…")

    # через 1.5 сек превращаем тост в карточку
    async def _swap_to_card():
        await asyncio.sleep(1.5)
        try:
            await render_cchk_task(callback.message.bot, chat_id, message_id, task_id)
        except Exception:
            pass
    asyncio.create_task(_swap_to_card())

    # кастомное notify: не шлём «✅», а перерисовываем карточку и можем отдать лог
    async def _notify(_: str):
        try:
            await render_cchk_task(callback.message.bot, chat_id, message_id, task_id)
            # опционально — сразу прислать файл со списком каналов «с обсуждениями»
            # await cchk_send_yes_export(callback.message, task_id)
        except Exception:
            pass

    # запускаем воркер
    t = asyncio.create_task(safe_run_comment_check(task_id, notify=_notify))
    _CCHK_WORKERS[task_id] = t
    t.add_done_callback(lambda fut: _CCHK_WORKERS.pop(task_id, None))

    await callback.answer("Стартануло ✅")




@router.callback_query(F.data.startswith("cchk_refresh:"))
@admin_only
async def cchk_refresh(cb: types.CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    text = _cchk_build_card_text(task_id)
    kb = _cchk_card_kb(task_id)

    # 1) Пытаемся отредактировать текущее сообщение карточки
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await cb.answer("Обновлено")
        return
    except TelegramBadRequest as e:
        # безопасно игнорируем «не изменилось», остальное — пробуем фоллбек
        if "message is not modified" in str(e).lower():
            await cb.answer("Без изменений")
            return

    # 2) Фоллбек: пробуем по «липким» id из state
    chat_id, message_id = await ui_get_ids(state)
    if chat_id and message_id:
        try:
            await ui_edit(cb.message.bot, chat_id, message_id, text, kb)
            await cb.answer("Обновлено")
            return
        except Exception:
            pass

    # 3) Совсем крайний случай — шлём новое сообщение
    await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer("Обновлено")


@router.callback_query(F.data.startswith("cchk_export_yes:"))
@admin_only
async def cchk_export_yes(cb: types.CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT channel
        FROM comment_check_log
        WHERE task_id=%s AND can_comment IS TRUE
        GROUP BY channel
        ORDER BY channel
    """, (task_id,))
    chans = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()

    if not chans:
        await cb.answer("Нет каналов с обсуждениями", show_alert=True); return

    content = "\n".join("@" + c if not c.startswith("@") else c for c in chans)
    buf = BufferedInputFile(content.encode("utf-8"), filename=f"cchk_yes_{task_id}.txt")

    await cb.message.answer_document(
        document=buf,
        caption=f"📄 Каналы с обсуждениями • #{task_id}",
        reply_markup=_ok_delete_kb()
    )
    await cb.answer()

@router.callback_query(F.data.startswith("cchk_export_all:"))
@admin_only
async def cchk_export_all(cb: types.CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split(":")[1])
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT account_id, channel, can_comment, mode, COALESCE(message,''), checked_at
        FROM comment_check_log
        WHERE task_id=%s
        ORDER BY checked_at
    """, (task_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()

    if not rows:
        await cb.answer("Лог пуст", show_alert=True); return

    lines = ["timestamp\taccount_id\tchannel\tcan_comment\tmode\tmessage"]
    for a,ch,can,mode,msg,ts in rows:
        can_s = "1" if can is True else ("0" if can is False else "")
        lines.append(f"{ts}\t{a}\t{ch}\t{can_s}\t{mode}\t{msg}")

    content = "\n".join(lines)
    buf = BufferedInputFile(content.encode("utf-8"), filename=f"cchk_log_{task_id}.tsv")

    await cb.message.answer_document(
        document=buf,
        caption=f"📜 Полный лог • #{task_id}",
        reply_markup=_ok_delete_kb()
    )
    await cb.answer()
    
@router.callback_query(F.data == "cchk_delete_log_message")
@admin_only
async def cchk_delete_log_message(cb: types.CallbackQuery):
    # Удаляем сообщение с документом (где нажата кнопка)
    try:
        await cb.message.delete()
        await cb.answer("✅ Удалено")
    except Exception:
        # если удалить нельзя (например, нет прав) — хотя бы снимем клавиатуру
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.answer("⚠️ Не удалось удалить, убрал кнопки.")

