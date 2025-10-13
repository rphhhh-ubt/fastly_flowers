from aiogram import Router, types, F
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from app.db import (
    insert_like_log,
    get_all_accounts,
    get_account_by_id,
    create_like_comments_task,
    update_task_payload,
    get_ok_channels_for_task,
)
import asyncio, json, time, random, os, re
from utils.like_worker import start_carousel_worker, stop_carousel_worker
from utils.comment_reactor import run_like_job  # исполнитель
from .tasks_view import render_like_task
from typing import List, Dict, Any
from app.db import get_account_groups_with_count






router = Router()

class LikeFSM(StatesGroup):
    selecting_accounts = State()
    waiting_for_channels = State()
    choosing_reactions_mode = State()
    waiting_for_reactions_input = State()
    waiting_for_mode = State()
    waiting_for_settings = State()
    waiting_for_parallel = State()
    waiting_for_interval = State()
    processing = State()

MAX_TEXT_LINES = 200
TEMP_DIR = os.getenv("TMPDIR", "/tmp")

# 👇 новая клавиатура в стиле реавторизации


def like_accounts_keyboard(
    accounts: List[Dict[str, Any]],
    selected_ids: set[int] | list[int] | None = None,
    page: int = 0,
    per_page: int = 10,
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
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"like_toggle:{acc_id}")])

    # пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"like_page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"like_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп (если есть)
    chips: list[InlineKeyboardButton] = []
    if groups:
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1:
                continue
            name = f"{g.get('emoji', '')} {g.get('name', '')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"like_group:{g['id']}"))

    for i in range(0, len(chips), 3):
        rows.append(chips[i:i+3])

    # массовые действия
    rows.append([
        InlineKeyboardButton(text="Выбрать все", callback_data="like_select_all"),
        InlineKeyboardButton(text="Снять все",   callback_data="like_clear_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="Далее ➜", callback_data="like_proceed"),
        InlineKeyboardButton(text="Отмена",   callback_data="menu_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def like_mode_keyboard():
    kb = [
        [
            InlineKeyboardButton(text="▶️ Разовый прогон", callback_data="like_mode_once"),
            InlineKeyboardButton(text="🔁 Карусель", callback_data="like_mode_loop"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def reactions_mode_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Дефолтные эмодзи", callback_data="rx_use_default")],
        [InlineKeyboardButton(text="🎯 Свой список эмодзи", callback_data="rx_custom")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")]
    ])


# === helpers for sticky UI ===
async def _safe_delete(msg: types.Message):
    try:
        await msg.delete()
    except Exception:
        pass

async def _safe_edit(bot_msg: types.Message, text: str, kb: InlineKeyboardMarkup | None = None):
    try:
        await bot_msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        s = str(e).lower()
        if "message is not modified" in s:
            return
        # если сообщение потеряли (например, было удалено) — просто игнор
        if "message to edit not found" in s or "message can't be edited" in s:
            return
        raise

async def _ensure_ui_message(msg_or_cb: types.Message, state: FSMContext) -> types.Message:
    """
    Гарантирует, что у нас есть одно "липкое" сообщение бота, которое мы редактируем.
    Возвращает объект Message, который нужно редактировать.
    """
    data = await state.get_data()
    ui_mid = data.get("ui_mid")
    ui_chat = data.get("ui_chat")
    if ui_mid and ui_chat == msg_or_cb.chat.id:
        try:
            # получим текущее сообщение по id через бот
            bot_msg = await msg_or_cb.bot.edit_message_text(
                chat_id=ui_chat, message_id=ui_mid, text=".", reply_markup=None
            )
            # сразу вернём объект Message (aiogram вернёт bool/Message в зависимости от API),
            # поэтому достанем как msg_or_cb.bot.get…
        except Exception:
            bot_msg = None
        if bot_msg is None:
            # не удалось отредактировать — создадим новое
            new_msg = await msg_or_cb.answer("⋯")
            await state.update_data(ui_mid=new_msg.message_id, ui_chat=new_msg.chat.id)
            return new_msg
        else:
            # мы уже что-то отредактировали на ".", это не очень — починим далее реальным текстом
            return types.Message(model=bot_msg.model_copy()) if hasattr(bot_msg, "model_copy") else msg_or_cb  # fallback
    # если ещё нет ui-сообщения — создадим
    new_msg = await msg_or_cb.answer("⋯")
    await state.update_data(ui_mid=new_msg.message_id, ui_chat=new_msg.chat.id)
    return new_msg
    


async def ui_get_ids(state) -> tuple[int | None, int | None]:
    d = await state.get_data()
    return d.get("ui_chat_id"), d.get("ui_message_id")

async def ui_set_ids(state, chat_id: int, message_id: int):
    await state.update_data(ui_chat_id=chat_id, ui_message_id=message_id)

async def ui_ensure(cb_or_msg, state) -> tuple[int, int]:
    """
    Гарантирует наличие одного сообщения-«карты».
    Возвращает (chat_id, message_id) этого сообщения.
    """
    chat_id, message_id = await ui_get_ids(state)
    if chat_id and message_id:
        return chat_id, message_id
    # нет закреплённого — создадим
    if isinstance(cb_or_msg, types.CallbackQuery):
        sent = await cb_or_msg.message.answer("⋯")
        await ui_set_ids(state, sent.chat.id, sent.message_id)
        return sent.chat.id, sent.message_id
    else:
        sent = await cb_or_msg.answer("⋯")
        await ui_set_ids(state, sent.chat.id, sent.message_id)
        return sent.chat.id, sent.message_id

async def ui_edit(bot, chat_id: int, message_id: int, text: str, kb: InlineKeyboardMarkup | None = None):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception as e:
        s = str(e).lower()
        if "message is not modified" in s:
            return
        # если вдруг сообщение недоступно, можно отправить новое и обновить ids (опционально)
        raise

async def delete_user_message(msg: types.Message):
    try:
        await msg.delete()
    except Exception:
        pass

def _norm_channel(ch: str) -> str:
    ch = ch.strip()
    if not ch:
        return ""
    ch = ch.replace("https://t.me/", "").replace("http://t.me/", "")
    if ch.startswith("@"):
        ch = ch[1:]
    return ch

async def _read_txt_lines(path: str) -> list[str]:
    """
    Читает файл построчно в отдельном потоке, чтобы не блокировать event-loop.
    Возвращает список уже очищенных строк (без пустых).
    """
    def _read():
        out = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s:
                    out.append(s)
        return out
    return await asyncio.to_thread(_read)

@router.callback_query(F.data == "start_like_comments_task")
async def start_like_comments_task(cb: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts()
    groups = get_account_groups_with_count()  # ← добавили
    await state.set_state(LikeFSM.selecting_accounts)

    # закрепляем карту на текущем сообщении
    await ui_set_ids(state, cb.message.chat.id, cb.message.message_id)

    await state.update_data(accounts=accounts, selected_accounts=[], page=0)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot,
        chat_id, message_id,
        "👤 Выберите аккаунты для лайкинга комментариев:",
        like_accounts_keyboard(accounts, set(), page=0, groups=groups)  # ← groups
    )
    await cb.answer()






@router.callback_query(F.data.startswith("like_toggle:"), LikeFSM.selecting_accounts)
async def like_toggle(cb: types.CallbackQuery, state: FSMContext):
    acc_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected_accounts", []))
    accounts = data.get("accounts", [])
    page = int(data.get("page", 0))

    if acc_id in selected:
        selected.remove(acc_id)
    else:
        selected.add(acc_id)
    await state.update_data(selected_accounts=list(selected))

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выберите аккаунты:",
        like_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
    )
    await cb.answer()




@router.callback_query(F.data.startswith("like_page:"), LikeFSM.selecting_accounts)
async def like_page(cb: types.CallbackQuery, state: FSMContext):
    page = int(cb.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get("accounts", [])
    selected = set(data.get("selected_accounts", []))
    await state.update_data(page=page)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выберите аккаунты:",
        like_accounts_keyboard(accounts, selected, page=page, groups=get_account_groups_with_count())
    )
    await cb.answer()


@router.callback_query(F.data == "like_select_all", LikeFSM.selecting_accounts)
async def like_select_all(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    all_ids = [a["id"] for a in accounts]
    page = int(data.get("page", 0))
    await state.update_data(selected_accounts=all_ids)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Все аккаунты выбраны. Нажмите «Далее».",
        like_accounts_keyboard(accounts, set(all_ids), page=page, groups=get_account_groups_with_count())
    )
    await cb.answer("✅ Выбраны все")


@router.callback_query(F.data == "like_clear_all", LikeFSM.selecting_accounts)
async def like_clear_all(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    page = int(data.get("page", 0))
    await state.update_data(selected_accounts=[])

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "👤 Выбор очищен. Отметьте нужные аккаунты:",
        like_accounts_keyboard(accounts, set(), page=page, groups=get_account_groups_with_count())
    )
    await cb.answer("♻️ Сброшен выбор")

@router.callback_query(F.data.startswith("like_group:"), LikeFSM.selecting_accounts)
async def like_group_pick(cb: types.CallbackQuery, state: FSMContext):
    group_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get("accounts", [])
    page = int(data.get("page", 0))

    # все id из выбранной группы
    ids_in_group = {a["id"] for a in accounts if a.get("group_id") == group_id}
    if not ids_in_group:
        await cb.answer("В этой группе нет аккаунтов")
        return

    await state.update_data(selected_accounts=list(ids_in_group))

    # микро-оптимизация: было ли изменение на текущей странице
    start = page * 10
    page_ids = {a["id"] for a in accounts[start:start+10]}
    changed_on_page = bool(ids_in_group & page_ids)

    chat_id, message_id = await ui_get_ids(state)
    kb = like_accounts_keyboard(accounts, ids_in_group, page=page, groups=get_account_groups_with_count())
    if changed_on_page:
        await ui_edit(cb.message.bot, chat_id, message_id, "👤 Выберите аккаунты:", kb)

    await cb.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")



@router.callback_query(F.data == "like_proceed", LikeFSM.selecting_accounts)
async def like_proceed(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected_accounts"):
        await cb.answer("⚠️ Выберите хотя бы один аккаунт!", show_alert=True)
        return

    await state.set_state(LikeFSM.waiting_for_channels)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "📋 Пришлите список каналов (@username или t.me/...), по одному в строке или .txt файлом."
    )
    await cb.answer()




@router.message(LikeFSM.waiting_for_channels)
async def like_receive_channels(msg: types.Message, state: FSMContext):
    channels: list[str] = []

    # 1) Если пользователь прислал текст
    if msg.text and not msg.document:
        lines = [s for s in (msg.text or "").splitlines() if s.strip()]
        # Telegram режет большие сообщения; если строк много — попросим .txt
        if len(lines) > MAX_TEXT_LINES:
            await delete_user_message(msg)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(
                msg.bot, chat_id, message_id,
                f"⚠️ В тексте {len(lines)} строк (> {MAX_TEXT_LINES}). "
                "Пожалуйста, пришлите список каналов одним .txt файлом (по одному в строке)."
            )
            return
        channels = lines

    # 2) Если прислали документ (.txt)
    elif msg.document:
        # сохраняем во временный файл и читаем построчно
        ts = int(time.time())
        tmp_path = os.path.join(TEMP_DIR, f"channels_{msg.from_user.id}_{ts}.txt")
        try:
            # aiogram v3: скачиваем документ через бот
            await msg.bot.download(msg.document, destination=tmp_path)
        except Exception as e:
            await delete_user_message(msg)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(msg.bot, chat_id, message_id, f"❌ Не удалось скачать файл: {e}")
            return

        try:
            channels = await _read_txt_lines(tmp_path)
        except Exception as e:
            await delete_user_message(msg)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(msg.bot, chat_id, message_id, f"❌ Не удалось прочитать файл: {e}")
            return
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    else:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(
            msg.bot, chat_id, message_id,
            "⚠️ Пришлите список каналов текстом (до 200 строк) или одним .txt файлом."
        )
        return

    if not channels:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id, "⚠️ Не найдено ни одного канала. Пришлите список ещё раз.")
        return

    # нормализуем, удаляем дубли
    channels = [_norm_channel(c) for c in channels]
    channels = [c for c in channels if c]             # убрать пустые после нормализации
    #channels = list(dict.fromkeys(channels))          # быстрый uniq с сохранением порядка
    random.shuffle(channels)
    await msg.answer(f"🔍 Отладка: получено {len(channels)} строк. Примеры: {channels[:3]}")

    await state.update_data(channels=channels)
    await state.set_state(LikeFSM.choosing_reactions_mode)

    await delete_user_message(msg)

    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        msg.bot, chat_id, message_id,
        "❤️ Выбери набор реакций:\n\n"
        "• <b>Дефолтные</b> — стандартный набор (лайк/огонь/сердце и т.п.).\n"
        "• <b>Свой список</b> — отправь эмодзи вручную.",
        reactions_mode_keyboard()
    )

@router.callback_query(F.data == "rx_use_default", LikeFSM.choosing_reactions_mode)
async def rx_use_default(cb: types.CallbackQuery, state: FSMContext):
    # ничего не пишем в state: run_for_account сам возьмёт дефолтный пул
    await state.update_data(reactions=None)
    await state.set_state(LikeFSM.waiting_for_mode)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "🕹 Выберите режим лайкинга:\n\n"
        "• <b>Разовый прогон</b>\n"
        "• <b>Карусель</b>",
        like_mode_keyboard()
    )
    await cb.answer()

@router.callback_query(F.data == "rx_custom", LikeFSM.choosing_reactions_mode)
async def rx_custom(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(LikeFSM.waiting_for_reactions_input)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "Введи свой список эмодзи.\n\n"
        "Формат: через пробел/запятую/с новой строки. Примеры:\n"
        "<code>👍 🔥 😍 ✨ 👏</code>\n"
        "или построчно в .txt файле.\n\n"
        "Совет: 3–10 эмодзи обычно достаточно."
    )
    await cb.answer()

def _parse_emoji_list(text: str) -> list[str]:
    # Разделяем по пробелам, запятым и переводам строки.
    raw = [t.strip() for t in re.split(r"[\s,]+", text or "") if t.strip()]
    # Убираем дубликаты с сохранением порядка
    seen, out = set(), []
    for t in raw:
        if t not in seen:
            seen.add(t)
            out.append(t)
    # Ограничим разумно (напр., до 25)
    return out[:25]

@router.message(LikeFSM.waiting_for_reactions_input)
async def rx_receive_custom(msg: types.Message, state: FSMContext):
    import re
    emojis: list[str] = []

    if msg.document:
        # читаем файл как текст (как в обработчике каналов)
        ts = int(time.time())
        path = os.path.join(TEMP_DIR, f"reactions_{msg.from_user.id}_{ts}.txt")
        try:
            await msg.bot.download(msg.document, destination=path)
            text = "\n".join(await _read_txt_lines(path))
        except Exception as e:
            await delete_user_message(msg)
            chat_id, message_id = await ui_get_ids(state)
            await ui_edit(msg.bot, chat_id, message_id, f"❌ Не удалось прочитать файл: {e}")
            return
        finally:
            try: os.remove(path)
            except Exception: pass
        emojis = _parse_emoji_list(text)
    else:
        emojis = _parse_emoji_list(msg.text or "")

    if not emojis:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id, "⚠️ Не удалось распознать эмодзи. Введи ещё раз.")
        return

    await state.update_data(reactions=emojis)
    await delete_user_message(msg)

    # дальше — выбор режима
    await state.set_state(LikeFSM.waiting_for_mode)
    chat_id, message_id = await ui_get_ids(state)
    pretty = " ".join(emojis)
    await ui_edit(
        msg.bot, chat_id, message_id,
        f"✅ Ваш набор реакций: {pretty}\n\n"
        "Теперь выберите режим работы:",
        like_mode_keyboard()
    )



@router.callback_query(F.data == "like_mode_once", LikeFSM.waiting_for_mode)
async def like_mode_once(cb: types.CallbackQuery, state: FSMContext):
    await state.update_data(mode="once")
    await state.set_state(LikeFSM.waiting_for_settings)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "⚙️ Настройки (разовый):\n"
        "• Сколько последних постов смотреть на каждом канале? (например: 5)\n"
        "• Сколько комментов лайкать на посте (кроме первого и последнего)? (например: 2)\n"
        "• Базовая задержка между реакциями в секундах (например: 9)\n\n"
        "Отправь в одной строке через пробел: 5 2 9"
    )
    await cb.answer()

@router.callback_query(F.data == "like_mode_loop", LikeFSM.waiting_for_mode)
async def like_mode_loop(cb: types.CallbackQuery, state: FSMContext):
    await state.update_data(mode="loop")
    await state.set_state(LikeFSM.waiting_for_settings)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        cb.message.bot, chat_id, message_id,
        "⚙️ Настройки (карусель):\n"
        "• Сколько последних постов проверять на <i>каждом цикле</i> (обычно 1–3).\n"
        "• Сколько комментов лайкать на посте (кроме первого и последнего)?\n"
        "• Базовая задержка между реакциями в секундах.\n\n"
        "Отправь в одной строке через пробел: 3 2 9"
    )
    await cb.answer()

@router.message(LikeFSM.waiting_for_settings)
async def like_receive_settings(msg: types.Message, state: FSMContext):
    data0 = await state.get_data()
    mode = data0.get("mode", "once")

    try:
        parts = msg.text.split()
        posts_last = max(1, int(parts[0]))
        extra_random = max(0, int(parts[1]))
        per_reaction = max(3, int(parts[2]))
    except Exception:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        fmt = "3 2 9" if mode == "loop" else "5 2 9"
        await ui_edit(msg.bot, chat_id, message_id, f"⚠️ Формат: {fmt}  (постов, доп.случайных, задержка)")
        return

    await state.update_data(
        posts_last=posts_last,
        extra_random=extra_random,
        per_reaction=per_reaction
    )

    await delete_user_message(msg)

    await state.set_state(LikeFSM.waiting_for_parallel)
    chat_id, message_id = await ui_get_ids(state)
    await ui_edit(
        msg.bot, chat_id, message_id,
        "⚙️ Параллельность:\n"
        "• Сколько аккаунтов запускать одновременно? (целое число)\n"
        "• (необязательно) задержка старта между клиентами в секундах.\n\n"
        "Примеры: <code>2</code> или <code>3 0.5</code>",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")]
        ])
    )
    
@router.message(LikeFSM.waiting_for_parallel)
async def like_receive_parallel(msg: types.Message, state: FSMContext):
    txt = (msg.text or "").strip().replace(",", ".")
    parts = txt.split()
    try:
        user_max_raw   = max(1, int(parts[0]))
        start_stagger  = float(parts[1]) if len(parts) > 1 else 0.0
        start_stagger  = max(0.0, start_stagger)
    except Exception:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id, "⚠️ Формат: <code>2</code> или <code>3 0.5</code>")
        return

    data = await state.get_data()
    selected_accounts = data.get("selected_accounts", [])
    allowed_max = max(1, len(selected_accounts))
    max_clients = min(user_max_raw, allowed_max)   # ← клэмп тут

    await state.update_data(parallel_max=max_clients, parallel_stagger=start_stagger)
    await delete_user_message(msg)

    data = await state.get_data()
    if data.get("mode") == "loop":
        await state.set_state(LikeFSM.waiting_for_interval)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(
            msg.bot, chat_id, message_id,
            "⏲ Укажи интервал проверки (в минутах), например 5.\n"
            "Бот будет каждые N минут проверять новые посты и лайкать свежие комменты."
        )
    else:
        await _create_like_task_and_show_card(msg, state)


@router.message(LikeFSM.waiting_for_interval)
async def like_receive_interval(msg: types.Message, state: FSMContext):
    try:
        interval_min = max(1, int(msg.text.strip()))
    except Exception:
        await delete_user_message(msg)
        chat_id, message_id = await ui_get_ids(state)
        await ui_edit(msg.bot, chat_id, message_id, "⚠️ Введи целое число минут, например 5.")
        return

    await state.update_data(loop_interval_min=interval_min)
    await delete_user_message(msg)
    await _create_like_task_and_show_card(msg, state)


async def _create_like_task_and_show_card(msg_or_cb: types.Message | types.CallbackQuery, state: FSMContext):
    # поддержка и для Message, и для CallbackQuery
    bot = msg_or_cb.bot if isinstance(msg_or_cb, types.Message) else msg_or_cb.message.bot
    chat_id, message_id = await ui_get_ids(state)
    data = await state.get_data()
    user_id = (msg_or_cb.from_user.id if isinstance(msg_or_cb, types.Message) else msg_or_cb.from_user.id)
    selected_accounts = data["selected_accounts"]
    user_max = int(data.get("parallel_max", 2))
    user_stagger = float(data.get("parallel_stagger", 0.0))
    max_clients = max(1, min(user_max, len(selected_accounts)))

    payload = {
        "channels": data["channels"],
        "posts_last": data["posts_last"],
        "comments_per_post": {
            "first_and_last": True,
            "extra_random_from_top": data["extra_random"],
            "random_pool_top": 25
        },
        #"reactions": ["👍","🔥","😍","👏","✨"],
        "unique_per_account": False,
        "max_reactions_per_account": 300,
        "max_reactions_per_post": 10,
        "antiduplicate": "off",
        "delays": {"per_reaction_sec": data["per_reaction"], "jitter": 0.5, "between_posts_sec": 5},
        "parallel": {
            "max_clients": max_clients,
            "start_stagger_sec": user_stagger,
            "flood_grace_sec": 60
        },
        "safety": {"hourly_rate_limit": 40, "shuffle_everywhere": True},
        "mode": data.get("mode", "once"),
        "watch": {
            "poll_interval_sec": max(60, int(data.get("loop_interval_min", 5)) * 60) if data.get("mode") == "loop" else 0,
            "only_new_posts": True
        },
        "selected_accounts": selected_accounts,
        "join_discussion_if_needed": True,
        "leave_after": False,
        "join_limits": {"per_account": 3, "cooldown_sec": 2},
    }
    payload["total_posts"] = len(payload["channels"]) * payload["posts_last"]
    payload["total_accounts"] = len(payload["selected_accounts"])
    payload["likes_done"] = 0
    payload["skipped"] = 0
    payload["errors"] = 0
    
    # если пользователь выбрал свой список — добавим его
    user_rx = data.get("reactions")
    if isinstance(user_rx, list) and user_rx:
        payload["reactions"] = list(dict.fromkeys(str(x) for x in user_rx))
    # иначе ключ не пишем — в run_for_account используется дефолтный пул

    task_id = create_like_comments_task(created_by=user_id, payload=payload)
    await state.update_data(task_id=task_id, settings=payload)

    mode_human = "карусель (циклично)" if payload["mode"] == "loop" else "разовый прогон"
    text = (
        f"❤️ <b>Лайкинг комментариев</b>\n"
        f"Задача #{task_id}\n\n"
        f"👥 Аккаунтов: {len(payload['selected_accounts'])}\n"
        f"📡 Каналов: {len(payload['channels'])}\n"
        f"📝 Постов/канал: {payload['posts_last']}\n"
        f"💬 Комментов/пост: 1-й, последний + {payload['comments_per_post']['extra_random_from_top']} рандом\n"
        f"⏱ Задержка: ~{payload['delays']['per_reaction_sec']}с ±{int(payload['delays']['jitter']*100)}%\n"
        f"🕹 Режим: {mode_human}\n"
    )
    if payload["mode"] == "loop":
        text += f"⏲ Интервал проверки: {data.get('loop_interval_min', 5)} мин\n"
    if payload.get("reactions"):
        text += f"🤍 Реакции: {' '.join(payload['reactions'])}\n"
    else:
        text += "🤍 Реакции: дефолтные\n"


    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Запустить", callback_data=f"like_start_{task_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_main")],
    ])

    await ui_edit(bot, chat_id, message_id, text, kb)




@router.callback_query(F.data.startswith("like_start_"))
async def like_start(cb: types.CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split("_")[-1])
    data = await state.get_data()
    if data.get("task_id") != task_id:
        await cb.answer("⚠️ Контекст задачи потерян, начни заново.", show_alert=True)
        return

    settings = data.get("settings", {})
    mode = settings.get("mode", "once")
    poll_interval_sec = int(settings.get("watch", {}).get("poll_interval_sec", 0) or 0)

    toast = await cb.message.answer(f"🚀 Задача #{task_id} запущена.")

    if mode == "loop":
        # стартуем карусель через воркер (он сам не допустит дубликатов)
        start_carousel_worker(task_id, state, poll_interval_sec or 300)
    else:
        # разовый прогон — как и раньше
        asyncio.create_task(run_like_job(state, mode="once"))

    # подчистить тост и перерисовать карточку
    async def _after():
        await asyncio.sleep(0.5)
        try:
            await toast.delete()
        except Exception:
            pass
        await render_like_task(cb.message, task_id)

    asyncio.create_task(_after())
    await cb.answer()



@router.callback_query(F.data.startswith("like_loop_start_"))
async def like_loop_start(cb: types.CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split("_")[-1])
    data = await state.get_data()
    if data.get("task_id") != task_id:
        await cb.answer("⚠️ Контекст задачи потерян. Открой задачу заново.", show_alert=True); return

    settings = data.get("settings", {})
    interval = int(settings.get("watch", {}).get("poll_interval_sec", 300))

    # стартуем воркер
    start_carousel_worker(task_id, state, interval)
    await cb.answer("🔁 Карусель запущена.")
    # тут можешь обновить карточку / статус
    # await render_like_task(cb.message, task_id)

@router.callback_query(F.data.startswith("like_loop_stop_"))
async def like_loop_stop(cb: types.CallbackQuery, state: FSMContext):
    task_id = int(cb.data.split("_")[-1])
    await stop_carousel_worker(task_id)
    await cb.answer("⏹ Карусель остановлена.")
    # опционально обновить карточку
    # await render_like_task(cb.message, task_id)





@router.callback_query(F.data.startswith("like_export_"))
async def like_export_channels(cb: types.CallbackQuery, state: FSMContext):
    try:
        task_id = int(cb.data.split("_")[-1])
    except Exception:
        await cb.answer("⚠️ Некорректный ID задачи.", show_alert=True)
        return

    try:
        channels = get_ok_channels_for_task(task_id)
    except Exception as e:
        await cb.answer(f"❌ Ошибка выборки: {e}", show_alert=True)
        return

    import re

    def to_at(s: str) -> str | None:
        s = (s or "").strip()
        if not s:
            return None

        # t.me/… → username
        m = re.match(r'^(?:https?://)?t\.me/(.+)$', s, flags=re.IGNORECASE)
        if m:
            path = m.group(1)
            # приватные инвайты/чаты в @ не конвертируем — пропустим
            if path.startswith(("+", "joinchat/")) or path.startswith(("c/", "s/")):
                return None
            s = path

        # убрать хвосты типа /123?foo=bar
        s = s.split("?")[0].split("/")[0].lstrip("@")

        # оставить только валидные юзернеймы (буквы/цифры/подчёрки)
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", s):
            return None

        return "@" + s

    # нормализуем → @username, удаляем пустые и дубли с сохранением порядка
    norm = []
    seen = set()
    for c in channels:
        at = to_at(c)
        if at and at not in seen:
            seen.add(at)
            norm.append(at)

    if not norm:
        await cb.answer("Пока нет ни одного канала в формате @username.", show_alert=True)
        return

    content = "\n".join(norm)
    buf = BufferedInputFile(content.encode("utf-8"),
                            filename=f"liked_channels_task_{task_id}.txt")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ ОК (удалить)", callback_data="like_delete_log_message")]]
    )

    await cb.message.answer_document(
        document=buf,
        caption=f"📄 Каналы (@username) • {len(norm)} шт.",
        reply_markup=kb
    )
    await cb.answer()


@router.callback_query(F.data == "like_delete_log_message")
async def like_delete_log_message(cb: types.CallbackQuery):
    try:
        await cb.message.delete()              # ← удаляем именно это сообщение (с файлом)
        await cb.answer("✅ Лог удалён")
    except Exception as e:
        # если не смогли удалить (редкий случай), просто уберём кнопки
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.answer(f"⚠️ Не удалось удалить: {e}", show_alert=True)

