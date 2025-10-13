import random, json, os, asyncio, unicodedata, re
from aiogram import Router, F, Bot, types
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import BOT_TOKEN
from utils.check_access import admin_only
from app.db import get_all_accounts, create_task_entry, insert_task_create_log, get_connection, update_task_status, update_task_accounts_count
from app.telegram_client import get_client
from utils.username_generator import generate_valid_username
from telethon.tl.functions.channels import CreateChannelRequest, EditPhotoRequest, UpdateUsernameRequest
from telethon.tl.types import InputChatUploadedPhoto, MessageMediaWebPage
from telethon.tl.functions.messages import DeleteMessagesRequest
from telethon.tl.functions.account import UpdatePersonalChannelRequest
from keyboards.main_menu import start_menu_keyboard
from utils.lock import run_with_lock
from zipfile import ZipFile
from PIL import Image
from keyboards.cancel_keyboard import cancel_keyboard
from telethon import functions as tfunc, types as ttypes



router = Router()
selected_accounts_create = {}
UPLOAD_FOLDER = "./avatar_uploads/"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Глобальные переменные
used_accounts = set()
used_accounts_lock = asyncio.Lock()


class ChannelCreation(StatesGroup):
    waiting_for_titles = State()
    waiting_for_descriptions = State()
    waiting_for_usernames = State()
    waiting_for_avatars = State()
    waiting_for_reactions_mode = State()
    waiting_for_reactions_list = State()
    waiting_for_donor_channels = State()
    waiting_for_copy_limit = State()



# Простейшая эвристика: выкидываем всё, где есть буквы/цифры/пунктуация,
# оставляем одиночные графемные кластеры, похожие на эмодзи.
_EMOJI_RE = re.compile(
    "["                             # широкие диапазоны emoji
    "\U0001F300-\U0001F5FF"         # Misc Symbols and Pictographs
    "\U0001F600-\U0001F64F"         # Emoticons
    "\U0001F680-\U0001F6FF"         # Transport & Map
    "\U0001F700-\U0001F77F"         # Alchemical
    "\U0001F780-\U0001F7FF"         # Geometric Extended
    "\U0001F800-\U0001F8FF"         # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF"         # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FAFF"         # Chess symbols, etc.
    "\u2600-\u26FF"                 # Misc symbols
    "\u2700-\u27BF"                 # Dingbats
    "]"
)

_ZWJ = "\u200D"     # zero width joiner
_VS16 = "\uFE0F"    # variation selector-16

def _is_single_emoji_token(tok: str) -> bool:
    if not tok:
        return False
    tok = tok.strip()
    # убираем variation selector; допускаем ровно один базовый эмодзи
    cleaned = tok.replace(_VS16, "")
    # если есть ZWJ-комбинации (семьи, профы) — отбрасываем (API часто ругается)
    if _ZWJ in cleaned:
        return False
    # токен должен состоять из одного «эмодзи-похожего» символа
    matches = list(_EMOJI_RE.finditer(cleaned))
    # допускаем ровно одну «эмодзи» позицию и без лишних не-эмодзи
    return len(matches) == 1 and matches[0].span() == (0, len(cleaned))

def sanitize_reactions_tokens(raw_tokens: list[str], limit: int = 11):
    """
    Возвращает (valid, rejected):
      valid    — очищенные уникальные эмодзи (до limit штук),
      rejected — то, что отброшено.
    """
    seen = set()
    valid = []
    rejected = []
    for tok in raw_tokens:
        t = tok.strip().strip(",.;:")  # срежем очевидную пунктуацию
        if not t:
            continue
        if _is_single_emoji_token(t):
            if t not in seen:
                seen.add(t)
                valid.append(t)
                if len(valid) >= limit:
                    break
        else:
            rejected.append(tok)
    return valid, rejected

async def load_used_accounts():
    global used_accounts
    try:
        if os.path.exists(USED_ACCOUNTS_FILE):
            with open(USED_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                used_accounts = {line.strip() for line in f if line.strip()}
    except Exception as e:
        print(f"⚠️ Ошибка загрузки использованных аккаунтов: {e}")


def extract_username_or_id(line: str) -> str | None:
    line = line.strip()
    if not line:
        return None

    # Если это ссылка вида https://t.me/... 
    if line.startswith("https://t.me/ "):
        parts = line.split("/")
        if len(parts) >= 4:
            username = parts[3].strip()
            if username.isdigit() or not username.startswith("@"):
                return username
            else:
                return username[1:]  # Убираем @
        return None

    # Если начинается с @
    elif line.startswith("@"):
        return line[1:].strip()

    # Просто username
    else:
        return line.strip()

def get_task_create_logs(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT account_id, log_text FROM task_create WHERE task_id = %s", (task_id,))
    logs = cursor.fetchall()
    cursor.close()
    conn.close()
    return logs

def reactions_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оставить дефолтные", callback_data="react_mode_default")],
        [InlineKeyboardButton(text="🚫 Запретить реакции", callback_data="react_mode_off")],
        #[InlineKeyboardButton(text="✏️ Свой список", callback_data="react_mode_custom")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_to_main_menu")]
    ])


@router.message(Command("create_channels"))
@admin_only
async def create_channels(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await load_used_accounts()
    async with used_accounts_lock:
        used_accounts.clear()
    if os.path.exists(USED_ACCOUNTS_FILE):
        os.remove(USED_ACCOUNTS_FILE)
    async with run_with_lock(f"channel_create_init_{user_id}"):
        await state.clear()
        await state.set_state(ChannelCreation.waiting_for_titles)

        sent_msg = await message.answer(
            "📥 Пришлите файл или текст с названиями каналов (по одному в строке):"
        )
        await state.update_data(bot_message_id=sent_msg.message_id)


@router.message(ChannelCreation.waiting_for_titles)
async def receive_titles(message: Message, state: FSMContext):
    user_id = message.from_user.id
    titles = []

    if message.document:
        file_path = os.path.join(UPLOAD_FOLDER, message.document.file_name)
        await message.bot.download(message.document, destination=file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            titles = [line.strip() for line in f if line.strip()]
        os.remove(file_path)
    else:
        titles = [line.strip() for line in message.text.split("\n") if line.strip()]

    if not titles:
        await message.answer("❗ Не удалось прочитать названия каналов.")
        return

    await state.update_data(titles=titles)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение пользователя: {e}")

    # Получаем ID сообщения бота для редактирования
    data = await state.get_data()
    bot_msg_id = data.get("bot_message_id")

    next_step_text = "📥 Теперь пришлите файл или текст с описаниями каналов:"
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text=next_step_text,
            reply_markup=cancel_keyboard()
        )
    except Exception as e:
        sent_msg = await message.answer(next_step_text, reply_markup=cancel_keyboard())
        await state.update_data(bot_message_id=sent_msg.message_id)

    await state.set_state(ChannelCreation.waiting_for_descriptions)




@router.message(ChannelCreation.waiting_for_descriptions)
async def receive_descriptions(message: Message, state: FSMContext):
    user_id = message.from_user.id
    descriptions = []

    if message.document:
        file_path = os.path.join(UPLOAD_FOLDER, message.document.file_name)
        await message.bot.download(message.document, destination=file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            descriptions = [line.strip() for line in f if line.strip()]
        os.remove(file_path)
    else:
        descriptions = [line.strip() for line in message.text.split("\n") if line.strip()]

    if not descriptions:
        await message.answer("❗ Не удалось прочитать описания.")
        return

    await state.update_data(descriptions=descriptions)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение пользователя: {e}")

    # Получаем ID сообщения бота для редактирования
    data = await state.get_data()
    bot_msg_id = data.get("bot_message_id")

    next_step_text = "📥 Пришлите файл с username’ами (по одному в строке), или напишите 'generate' для генерации:"
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text=next_step_text,
            reply_markup=cancel_keyboard()
        )
    except Exception as e:
        sent_msg = await message.answer(next_step_text, reply_markup=cancel_keyboard())
        await state.update_data(bot_message_id=sent_msg.message_id)

    await state.set_state(ChannelCreation.waiting_for_usernames)



@router.message(ChannelCreation.waiting_for_usernames)
async def receive_usernames(message: Message, state: FSMContext):
    if message.text and message.text.lower() == "generate":
        await state.update_data(generate_usernames=True, usernames=[])
    elif message.document:
        file_path = os.path.join(UPLOAD_FOLDER, message.document.file_name)
        await message.bot.download(message.document, destination=file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            usernames = [line.strip() for line in f if line.strip()]
        os.remove(file_path)
        await state.update_data(generate_usernames=False, usernames=usernames)
    else:
        await message.answer("❗ Ошибка. Пришлите текст 'generate' или файл с username’ами.")
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение пользователя: {e}")

    # Редактируем сообщение бота
    data = await state.get_data()
    bot_msg_id = data.get("bot_message_id")

    next_step_text = "📸 Пришлите ZIP с аватарками (до 50 штук):\n\n⚠️ Важно учитывать:\n\nTelegram поддерживает аватарки размером до 10 МБ и форматов jpg. \n\nЖелательно учитывать размер файлов, если будет много картинок — это скажется на скорости распаковки архива и общем времени выполнения задачи."
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text=next_step_text,
            reply_markup=cancel_keyboard()
        )
    except Exception as e:
        sent_msg = await message.answer(next_step_text, reply_markup=cancel_keyboard())
        await state.update_data(bot_message_id=sent_msg.message_id)

    await state.set_state(ChannelCreation.waiting_for_avatars)



@router.message(ChannelCreation.waiting_for_avatars, F.document)
async def receive_avatars_zip(message: Message, state: FSMContext):
    if not message.document.file_name.lower().endswith(".zip"):
        await message.answer("❗ Пришлите ZIP-архив с аватарками.")
        return

    zip_path = os.path.join(UPLOAD_FOLDER, "avatars.zip")
    await message.bot.download(message.document.file_id, destination=zip_path)
    saved_paths = []

    try:
        with ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(UPLOAD_FOLDER)
            extracted = zip_ref.namelist()
            for i, filename in enumerate(extracted[:50]):
                ext = os.path.splitext(filename)[1].lower()
                if ext in [".jpg", ".jpeg", ".png"]:
                    saved_paths.append(os.path.join(UPLOAD_FOLDER, filename))
    except Exception as e:
        await message.answer("❌ Ошибка при распаковке архива.")
        print(f"[ERROR] Ошибка распаковки ZIP: {e}")
        return
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    random.shuffle(saved_paths)
    if not saved_paths:
        await message.answer("⚠️ В архиве нет подходящих аватарок (только JPG/PNG).")
        return

    await state.update_data(saved_paths=saved_paths)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение пользователя: {e}")

    # Редактируем сообщение бота
    data = await state.get_data()
    bot_msg_id = data.get("bot_message_id")

    next_step_text = (
        "🧩 Реакции на постах канала:\n"
        "• «Оставить дефолтные» — как у Телеграма по умолчанию\n"
        "• «Запретить реакции» — реакции будут выключены\n"
        "• «Свой список» — укажете разрешённые эмодзи\n\n"
        "Выберите режим:"
    )
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text=next_step_text,
            reply_markup=reactions_mode_keyboard()
        )
    except Exception:
        sent_msg = await message.answer(next_step_text, reply_markup=reactions_mode_keyboard())
        await state.update_data(bot_message_id=sent_msg.message_id)

    await state.set_state(ChannelCreation.waiting_for_reactions_mode)

@router.callback_query(F.data.in_({"react_mode_default", "react_mode_off", "react_mode_custom"}))
async def select_reactions_mode(callback: CallbackQuery, state: FSMContext):
    mode_map = {
        "react_mode_default": "default",
        "react_mode_off": "off",
        "react_mode_custom": "custom",
    }
    mode = mode_map[callback.data]
    await state.update_data(reactions_mode=mode)

    data = await state.get_data()
    bot_msg_id = data.get("bot_message_id")

    if mode == "custom":
        txt = (
            "✏️ Пришлите список разрешённых реакций (эмодзи).\n"
            "Можно через пробел или по одному в строке.\n\n"
            "Примеры:\n"
            "👍 😂 🔥 😮\n"
            "или\n"
            "👍\n😂\n🔥\n😮"
        )
        try:
            await callback.message.edit_text(txt, reply_markup=cancel_keyboard())
        except Exception:
            await callback.message.answer(txt, reply_markup=cancel_keyboard())
        await state.set_state(ChannelCreation.waiting_for_reactions_list)
    else:
        # сразу переходим к донорам
        next_step_text = "📥 Пришлите список username’ов или ссылок на каналы-доноры (по одному в строке или .txt файлом):"
        try:
            await callback.message.edit_text(next_step_text, reply_markup=cancel_keyboard())
        except Exception:
            await callback.message.answer(next_step_text, reply_markup=cancel_keyboard())
        await state.set_state(ChannelCreation.waiting_for_donor_channels)

    await callback.answer()


@router.message(ChannelCreation.waiting_for_reactions_list)
async def receive_reactions_list(message: Message, state: FSMContext):
    # собираем сырые токены (поддержим пробелы/запятые/переносы)
    raw = []
    if message.document:
        file_path = os.path.join(UPLOAD_FOLDER, message.document.file_name)
        await message.bot.download(message.document, destination=file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        os.remove(file_path)
    else:
        text = message.text or ""

    # сплитим по пробелам, запятым и переносам
    raw = re.split(r"[\s,]+", text.strip())

    reactions, rejected = sanitize_reactions_tokens(raw, limit=11)

    if not reactions:
        # ничего валидного — попросим пример
        await message.answer(
            "❗ Не удалось прочитать валидные эмодзи.\n"
            "Пришлите ряд стандартных эмодзи, например:\n\n"
            "👍 😂 🔥 😮"
        )
        return

    await state.update_data(reactions=reactions)

    # удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    bot_msg_id = data.get("bot_message_id")

    # короткий фидбек
    feedback = "✅ Приму реакции: " + " ".join(reactions)
    if rejected:
        feedback += f"\n⚠️ Отброшено: {' '.join(rejected[:10])}" + (" …" if len(rejected) > 10 else "")

    next_step_text = (
        f"{feedback}\n\n"
        "📥 Теперь пришлите список username’ов или ссылок на каналы-доноры "
        "(по одному в строке или .txt файлом):"
    )

    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text=next_step_text,
            reply_markup=cancel_keyboard()
        )
    except Exception:
        sent_msg = await message.answer(next_step_text, reply_markup=cancel_keyboard())
        await state.update_data(bot_message_id=sent_msg.message_id)

    await state.set_state(ChannelCreation.waiting_for_donor_channels)



@router.message(ChannelCreation.waiting_for_donor_channels)
async def receive_donor_channels(message: Message, state: FSMContext):
    donor_channels = []
    if message.document:
        file = await message.document.download(destination_dir=UPLOAD_FOLDER)
        with open(file.path, "r", encoding="utf-8") as f:
            donor_channels = [extract_username_or_id(line) for line in f.readlines()]
        os.remove(file.path)
    else:
        lines = message.text.split('\n')
        donor_channels = [extract_username_or_id(line) for line in lines]

    donor_channels = [d for d in donor_channels if d is not None]

    if not donor_channels:
        await message.answer("❗ Список каналов-доноров пуст.")
        return

    await state.update_data(donor_channels=donor_channels)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение пользователя: {e}")

    # Редактируем сообщение бота
    data = await state.get_data()
    bot_msg_id = data.get("bot_message_id")

    next_step_text = "📊 Укажите, сколько постов копировать с донора (число):"
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text=next_step_text,
            reply_markup=cancel_keyboard()
        )
    except Exception as e:
        sent_msg = await message.answer(next_step_text, reply_markup=cancel_keyboard())
        await state.update_data(bot_message_id=sent_msg.message_id)

    await state.set_state(ChannelCreation.waiting_for_copy_limit)



from keyboards.main_menu import start_menu_keyboard  # убедись, что этот импорт есть сверху

@router.message(ChannelCreation.waiting_for_copy_limit)
async def receive_copy_limit(message: Message, state: FSMContext):
    try:
        copy_post_limit = int(message.text.strip())
        if copy_post_limit <= 0:
            raise ValueError
    except:
        await message.answer("❗ Некорректное число.")
        return

    await state.update_data(copy_post_limit=copy_post_limit)

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение пользователя: {e}")

    # Редактируем сообщение бота
    data = await state.get_data()
    bot_msg_id = data.get("bot_message_id")

    start_task_text = "🚀 Начинаю создание каналов, по завершении задачи Вам будет отправлен лог..."

    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text=start_task_text
            
        )
    except Exception as e:
        sent_msg = await message.answer(start_task_text)
        await state.update_data(bot_message_id=sent_msg.message_id)
        bot_msg_id = sent_msg.message_id  # на случай если сообщение новое

    await asyncio.sleep(2)

    # Замена на главное меню бота
    main_menu_text = "👋 Добро пожаловать в панель управления!\n\nВыберите раздел:"
    try:
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text=main_menu_text,
            reply_markup=start_menu_keyboard()
        )
    except Exception as e:
        print(f"⚠️ Не удалось заменить на главное меню: {e}")
        await message.answer(main_menu_text, reply_markup=start_menu_keyboard())

    # Запуск задачи по созданию каналов
    data = await state.get_data()
    await create_channels_process(message, state, data)



# вверху файла НИЧЕГО для файлов больше не нужно

async def create_channels_process(message: Message, state: FSMContext, data: dict):
    titles          = data["titles"]
    descriptions    = data["descriptions"]
    usernames       = data["usernames"]
    generate        = data["generate_usernames"]
    saved_paths     = data["saved_paths"]
    donor_channels  = data["donor_channels"]
    copy_post_limit = data["copy_post_limit"]

    all_accounts    = get_all_accounts()
    selected_ids    = data.get("selected_account_ids", [])
    user_id         = message.from_user.id

    # Берём только выбранные аккаунты
    selected_accounts = [a for a in all_accounts if a["id"] in selected_ids]

    # ⚠️ На всякий: убираем дубли по session_string ещё до запуска задач
    # (если по ошибке в выборке оказались 2 записи с одной сессией)
    unique_by_session = {}
    for acc in selected_accounts:
        ss = acc.get("session_string")
        if ss and ss not in unique_by_session:
            unique_by_session[ss] = acc
    filtered_accounts = list(unique_by_session.values())
    
    reactions_mode   = data.get("reactions_mode", "default")  # default|off|custom
    reactions_list   = data.get("reactions", [])
    payload = {
        "accounts": selected_ids,
        "copy_post_limit": copy_post_limit,
        "generate_usernames": generate,
        "titles": titles,
        "descriptions": descriptions,
        "usernames": usernames,
        "donor_channels": donor_channels,
        "reactions_mode": reactions_mode,
        "reactions": reactions_list,
    }

    task_id = create_task_entry(
        task_type="create_and_set_channel",
        created_by=user_id,
        payload=json.dumps(payload)
    )

    if not filtered_accounts:
        await message.answer("❗ Аккаунты не выбраны.")
        update_task_status(task_id, "completed")
        return

    # ✅ Локальное состояние задачи — без файлов
    used_accounts: set[str] = set()
    used_accounts_lock = asyncio.Lock()
    used_avatars: set[str] = set()
    used_avatars_lock = asyncio.Lock()

    async def process_account(idx: int, account: dict) -> str:
        log = ""
        account_key = account["session_string"]
        acc_username = account.get("username") or f"id{account['id']}"
        account_id = account["id"]

        # Не даём одной сессии попасть в работу дважды в рамках ЭТОЙ задачи
        async with used_accounts_lock:
            if account_key in used_accounts:
                return f"⚠️ Аккаунт {acc_username} уже использован, пропущен\n"
            used_accounts.add(account_key)

        proxy = {
            "proxy_host": account["proxy_host"],
            "proxy_port": account["proxy_port"],
            "proxy_username": account["proxy_username"],
            "proxy_password": account["proxy_password"],
        }

        try:
            client = await get_client(account["session_string"], proxy)
            try:
                await client.connect()
            except Exception as e:
                log += f"❌ Ошибка подключения @{acc_username}: {e}\n"
                return log

            title = titles[idx % len(titles)]
            about = descriptions[idx % len(descriptions)]
            ch_username = generate_valid_username() if generate else usernames[idx % len(usernames)]

            # Создаём канал
            result = await client(CreateChannelRequest(title=title, about=about, megagroup=False))
            channel = result.chats[0]

            # Username с до 5 ретраев
            success = False
            for attempt in range(5):
                try:
                    await client(UpdateUsernameRequest(channel=channel, username=ch_username))
                    success = True
                    break
                except Exception as e:
                    print(f"⚠️ [{acc_username}] попытка {attempt+1}/5 username '{ch_username}': {e}")
                    ch_username = generate_valid_username()
            if not success:
                log += f"❌ Не удалось установить username для @{acc_username}\n"
                await client.disconnect()
                insert_task_create_log(task_id, account_id, log)
                return log

            # Персональный канал
            try:
                await client(UpdatePersonalChannelRequest(channel=channel))
                log += f"👤 Канал установлен как персональный для @{acc_username}\n"
            except Exception as e:
                log += f"⚠️ Не удалось установить канал как персональный: {e}\n"

            # Аватарка (общий пул, чтобы не расходовать одну картинку дважды)
            avatar_set = False
            avatar_path_used = None
            for _ in range(5):
                if avatar_set:
                    break
                async with used_avatars_lock:
                    for photo_path in saved_paths:
                        if photo_path in used_avatars:
                            continue
                        try:
                            with Image.open(photo_path) as img:
                                if img.width < 200 or img.height < 200:
                                    log += f"⚠️ Аватарка {photo_path} слишком маленькая, пропущена\n"
                                    continue
                            uploaded = await client.upload_file(photo_path)
                            input_photo = InputChatUploadedPhoto(uploaded)
                            await client(EditPhotoRequest(channel=channel, photo=input_photo))
                            used_avatars.add(photo_path)
                            avatar_path_used = photo_path
                            avatar_set = True
                            break
                        except Exception as e:
                            log += f"⚠️ Ошибка установки аватарки {photo_path}: {e}\n"
                            used_avatars.discard(photo_path)
                            continue

            if not avatar_set:
                log += f"🖼️ Не удалось установить аватарку для @{acc_username}\n"
            else:
                log += f"🖼️ Аватарка установлена из {avatar_path_used}\n"
                
            # --- Настройка реакций ---

            try:
                mode = payload.get("reactions_mode", "default")
                custom = payload.get("reactions", [])

                if mode == "off":
                    await client(
                        tfunc.messages.SetChatAvailableReactionsRequest(
                            peer=channel,
                            available_reactions=ttypes.ChatReactionsNone()
                        )
                    )
                    log += "🚫 Реакции отключены\n"

                elif mode == "custom":
                    rx = [ttypes.ReactionEmoji(emoticon=e) for e in custom if e]
                    if not rx:
                        await client(
                            tfunc.messages.SetChatAvailableReactionsRequest(
                                peer=channel,
                                available_reactions=ttypes.ChatReactionsAll()
                            )
                        )
                        log += "ℹ️ Список реакций пуст — оставлены дефолтные\n"
                    else:
                        await client(
                            tfunc.messages.SetChatAvailableReactionsRequest(
                                peer=channel,
                                available_reactions=ttypes.ChatReactionsSome(reactions=rx)
                            )
                        )
                        log += f"✅ Разрешённые реакции: {' '.join(custom)}\n"

                else:
                    await client(
                        tfunc.messages.SetChatAvailableReactionsRequest(
                            peer=channel,
                            available_reactions=ttypes.ChatReactionsAll()
                        )
                    )
                    log += "✅ Оставлены дефолтные реакции\n"

            except Exception as e:
                log += f"⚠️ Не удалось применить настройки реакций: {e}\n"



            url = f"https://t.me/{ch_username}"
            log += f"✅ {title} — {url}\n"

            # Удаляем служебные сообщения ("Канал создан", "Фото обновлено", пины и т.п.)
            from telethon import types as tltypes
            try:
                await asyncio.sleep(2.0)  # даём телеге записать сервисные ивенты
                svc_ids = []
                async for m in client.iter_messages(channel, limit=50):
                    action = getattr(m, "action", None)
                    is_service = isinstance(m, tltypes.MessageService)
                    is_known_action = isinstance(action, (
                        tltypes.MessageActionChannelCreate,
                        tltypes.MessageActionChatEditPhoto,
                        tltypes.MessageActionChatEditTitle,
                        tltypes.MessageActionHistoryClear,
                        tltypes.MessageActionPinMessage,
                        tltypes.MessageActionChatJoinedByLink,
                        tltypes.MessageActionChatAddUser,
                    ))
                    # НЕ удаляем медиа/текст — только сервис
                    if is_service or is_known_action:
                        svc_ids.append(m.id)

                if svc_ids:
                    await client.delete_messages(channel, svc_ids)
                    log += f"🗑️ Удалены служебные сообщения: {len(svc_ids)} шт.\n"
                else:
                    log += "🗑️ Служебных сообщений не найдено\n"

            except Exception as e:
                log += f"⚠️ Ошибка удаления служебных сообщений: {e}\n"
                
             
            # Копирование постов
            donor = donor_channels[idx % len(donor_channels)]
            clean_donor = extract_username_or_id(donor)
            if not clean_donor:
                log += f"⚠️ Неверный формат донора: {donor}\n"
                await client.disconnect()
                insert_task_create_log(task_id, account_id, log)
                return log
            try:
                from_channel = await client.get_entity(clean_donor)
            except Exception as e:
                log += f"⚠️ Не удалось найти канал @{clean_donor}: {e}\n"
                await client.disconnect()
                insert_task_create_log(task_id, account_id, log)
                return log

            post_count = 0
            posts = []
            async for msg in client.iter_messages(from_channel, limit=copy_post_limit):
                if msg.message is None and msg.media is None:  # пустяки
                    continue
                if msg.forward or getattr(msg, 'action', None):
                    continue
                if msg.media and isinstance(msg.media, MessageMediaWebPage):
                    continue
                posts.append(msg)

            posts.reverse()
            for msg in posts:
                try:
                    if msg.media and isinstance(msg.media, MessageMediaWebPage):
                        await client.send_message(channel, msg.text or "🔗 Ссылка без медиа")
                        log += "📎 Текстовый пост (web-preview пропущено)\n"
                        post_count += 1
                        continue
                    if msg.text and msg.media:
                        try:
                            await client.send_message(channel, msg.text, file=msg.media)
                            log += "📎 Текст+медиа\n"
                        except Exception as media_err:
                            print(f"[DEBUG] Ошибка отправки медиа: {media_err}")
                            await client.send_message(channel, msg.text)
                            log += "📎 Только текст (медиа не поддерживается)\n"
                    elif msg.text:
                        await client.send_message(channel, msg.text)
                        log += "📎 Только текст\n"
                    elif msg.media:
                        try:
                            await client.send_file(channel, msg.media, caption="")
                            log += "📎 Медиа без текста\n"
                        except Exception as media_err:
                            log += f"⚠️ Нельзя отправить медиа: {media_err}\n"
                            continue
                    post_count += 1
                except Exception as send_err:
                    log += f"⚠️ Ошибка при отправке поста: {send_err}\n"
                    continue

                        
            log += f"📎 Скопировано {post_count} постов из {clean_donor}\n"

            await client.disconnect()
            insert_task_create_log(task_id, account_id, log)
            return log

        except Exception as e:
            log += f"❌ Общая ошибка обработки @{acc_username}: {e}\n"
            insert_task_create_log(task_id, account_id, log)
            return log

    # Параллельный запуск
    results = await asyncio.gather(
        *[process_account(i, acc) for i, acc in enumerate(filtered_accounts)],
        return_exceptions=True
    )

    # Сводка
    accounts_count = len(filtered_accounts)
    update_task_accounts_count(task_id, accounts_count)
    update_task_status(task_id, "completed")

    # Лог из БД (по аккаунтам)
    logs = get_task_create_logs(task_id)
    log_str = "\n\n".join([f"Аккаунт {account_id}:\n{log_text}" for account_id, log_text in logs])

    log_path = os.path.join(UPLOAD_FOLDER, f"create_channels_log_{task_id}.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(log_str)

    ok_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ ОК", callback_data="delete_log_message")]]
    )
    await message.answer_document(
        FSInputFile(log_path),
        caption="📄 Лог создания и установки каналов",
        reply_markup=ok_button
    )
    try:
        os.remove(log_path)
    except FileNotFoundError:
        pass

    await state.clear()




@router.callback_query(F.data == "proceed_create_channel")
@admin_only
async def run_create_channel(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    selected_ids = selected_accounts_create.get(user_id, [])

    if not selected_ids:
        await callback.answer("⚠️ Выберите хотя бы один аккаунт!", show_alert=True)
        return

    await state.clear()
    await state.set_state(ChannelCreation.waiting_for_titles)
    await state.update_data(selected_account_ids=selected_ids)

    # Отправляем сообщение (не edit!), чтобы был bot_message_id
    sent_msg = await callback.message.answer(
        "📥 Пришлите файл или текст с названиями каналов (по одному в строке):",
        reply_markup=cancel_keyboard()
    )

    await state.update_data(bot_message_id=sent_msg.message_id)
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "delete_log_message")
async def delete_log_message_handler(callback: CallbackQuery):
    try:
        await callback.message.delete()
        await callback.answer("✅ Лог удалён!", show_alert=False)
    except Exception as e:
        print(f"⚠️ Ошибка при удалении лога: {e}")
        await callback.answer("❌ Не удалось удалить лог.", show_alert=True)



@router.callback_query(F.data == "cancel_to_main_menu")
async def cancel_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 Вы вернулись в главное меню.\n\nВыберите раздел:",
        reply_markup=start_menu_keyboard()
    )
    await callback.answer("✅ Задача отменена", show_alert=False)
