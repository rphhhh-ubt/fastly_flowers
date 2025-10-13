import os, time, asyncio, random
import random as _random
from .mass_search_view import send_task_card
from app.telegram_client import get_client
from collections import defaultdict
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from app.db import get_all_accounts, save_group_result, get_group_results_by_task
from app.telegram_client import get_client
from utils.search_groups import search_public_groups
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from states.mass_search import MassSearchStates
from telethon.tl.functions.contacts import SearchRequest
from aiogram.exceptions import TelegramBadRequest
from app.db import (
    get_active_accounts,
    save_group_result,
    get_group_results_by_task,
    update_account_status,
    log_task_event,
    create_task_entry,
    save_task_result,
    update_task_progress,
    update_task_status,
    get_account_groups_with_count,
    get_account_by_id,
)


router = Router()

STATE_ACCS = "ms_accounts"
STATE_SEL  = "ms_selected"
STATE_PAGE = "ms_page"
PER_PAGE   = 10



TEMP_DIR = os.getenv("TMPDIR", "/tmp")

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

async def _safe_edit_markup(msg: types.Message, kb):
    try:
        await msg.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise

def mass_accounts_keyboard(
    accounts: list[dict],
    selected_ids: set[int] | list[int] | None = None,
    page: int = 0,
    per_page: int = 10,
    groups: list[dict] | None = None,
) -> InlineKeyboardMarkup:
    selected = set(selected_ids or [])
    start = page * per_page
    chunk = accounts[start:start+per_page]

    rows = []
    for acc in chunk:
        acc_id = acc["id"]
        uname = acc.get("username") or "-"
        phone = acc.get("phone") or "-"
        mark = "✅" if acc_id in selected else "⏹️"
        txt = f"{mark} {acc_id} ▸ @{uname} ▸ {phone}"
        rows.append([InlineKeyboardButton(text=txt, callback_data=f"ms_toggle:{acc_id}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"ms_page:{page-1}"))
    if start + per_page < len(accounts):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"ms_page:{page+1}"))
    if nav:
        rows.append(nav)

    # чипсы групп 3-в-ряд
    chips = []
    if groups:
        for g in groups:
            cnt = int(g.get("count") or 0)
            if cnt < 1: 
                continue
            name = f"{g.get('emoji','')} {g.get('name','')}".strip()
            label = f"{name} ({cnt})"
            chips.append(InlineKeyboardButton(text=label, callback_data=f"ms_group:{g['id']}"))
        for i in range(0, len(chips), 3):
            rows.append(chips[i:i+3])

    rows.append([
        InlineKeyboardButton(text="Выбрать все", callback_data="ms_select_all"),
        InlineKeyboardButton(text="Снять все",   callback_data="ms_clear_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="Далее ➜", callback_data="ms_proceed"),
        InlineKeyboardButton(text="Отмена",   callback_data="menu_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "mass_search")
async def start_mass_search_task_callback(callback: types.CallbackQuery, state: FSMContext):
    accounts = get_all_accounts() or []
    groups   = get_account_groups_with_count() or []

    # чистим и готовим FSM
    await state.clear()
    await state.update_data(**{
        STATE_ACCS: accounts,
        STATE_SEL: [],
        STATE_PAGE: 0,
    })

    # показываем выбор аккаунтов (редактируем текущее сообщение)
    kb = mass_accounts_keyboard(accounts, set(), page=0, per_page=PER_PAGE, groups=groups)
    try:
        await callback.message.edit_text(
            "👥 Выберите аккаунты, которые будут искать группы:",
            reply_markup=kb
        )
    except Exception:
        # если старое сообщение нельзя править — пошлём новое
        msg = await callback.message.answer(
            "👥 Выберите аккаунты, которые будут искать группы:",
            reply_markup=kb
        )
        await state.update_data(bot_msg_id=msg.message_id)
    else:
        await state.update_data(bot_msg_id=callback.message.message_id)

    await callback.answer()

@router.callback_query(F.data.startswith("ms_toggle:"))
async def ms_toggle(callback: types.CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    selected = set(data.get(STATE_SEL, []))
    page     = int(data.get(STATE_PAGE, 0))

    if acc_id in selected: selected.remove(acc_id)
    else: selected.add(acc_id)
    await state.update_data(**{STATE_SEL: list(selected)})

    kb = mass_accounts_keyboard(accounts, selected, page=page, per_page=PER_PAGE, groups=get_account_groups_with_count())
    await _safe_edit_markup(callback.message, kb)
    await callback.answer()

@router.callback_query(F.data.startswith("ms_page:"))
async def ms_page(callback: types.CallbackQuery, state: FSMContext):
    new_page = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    selected = set(data.get(STATE_SEL, []))
    await state.update_data(**{STATE_PAGE: new_page})

    kb = mass_accounts_keyboard(accounts, selected, page=new_page, per_page=PER_PAGE, groups=get_account_groups_with_count())
    await _safe_edit_markup(callback.message, kb)
    await callback.answer()

@router.callback_query(F.data == "ms_select_all")
async def ms_select_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    all_ids  = [a["id"] for a in accounts]
    await state.update_data(**{STATE_SEL: all_ids})
    page = int(data.get(STATE_PAGE, 0))

    kb = mass_accounts_keyboard(accounts, set(all_ids), page=page, per_page=PER_PAGE, groups=get_account_groups_with_count())
    await _safe_edit_markup(callback.message, kb)
    await callback.answer("✅ Выбраны все аккаунты")

@router.callback_query(F.data == "ms_clear_all")
async def ms_clear_all(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    await state.update_data(**{STATE_SEL: []})
    page = int(data.get(STATE_PAGE, 0))

    kb = mass_accounts_keyboard(accounts, set(), page=page, per_page=PER_PAGE, groups=get_account_groups_with_count())
    await _safe_edit_markup(callback.message, kb)
    await callback.answer("♻️ Сброшен выбор")

@router.callback_query(F.data.startswith("ms_group:"))
async def ms_group(callback: types.CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    accounts = data.get(STATE_ACCS, [])
    page     = int(data.get(STATE_PAGE, 0))

    ids_in_group = {a["id"] for a in accounts if a.get("group_id") == group_id}
    if not ids_in_group:
        await callback.answer("В этой группе нет аккаунтов")
        return

    await state.update_data(**{STATE_SEL: list(ids_in_group)})

    start = page * PER_PAGE
    page_ids = {a["id"] for a in accounts[start:start+PER_PAGE]}
    changed_on_page = bool(ids_in_group & page_ids)

    kb = mass_accounts_keyboard(accounts, ids_in_group, page=page, per_page=PER_PAGE, groups=get_account_groups_with_count())
    if changed_on_page:
        await _safe_edit_markup(callback.message, kb)
    await callback.answer(f"Выбрана группа (аккаунтов: {len(ids_in_group)})")

@router.callback_query(F.data == "ms_proceed")
async def ms_proceed(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected_ids = list(data.get(STATE_SEL, []))
    if not selected_ids:
        await callback.answer("⚠️ Выберите хотя бы один аккаунт!", show_alert=True)
        return

    # сохраняем список выбранных для последующих шагов
    await state.update_data(selected_account_ids=selected_ids)

    # переходим к шагу «ключевые слова»
    msg_id = (await state.get_data()).get("bot_msg_id") or callback.message.message_id
    try:
        await callback.message.edit_text("📋 Пришли список ключей (каждый с новой строки или .txt файл):")
    except Exception:
        sent = await callback.message.answer("📋 Пришли список ключей (каждый с новой строки или .txt файл):")
        msg_id = sent.message_id
    await state.update_data(bot_msg_id=msg_id)
    await state.set_state(MassSearchStates.waiting_for_keywords)
    await callback.answer("✅ Аккаунты выбраны")


# 1. Получение ключей
@router.message(MassSearchStates.waiting_for_keywords)
async def mass_search_receive_keywords(message: types.Message, state: FSMContext):
    print("[DEBUG] Вызван mass_search_receive_keywords")

    # удаляем пользовательское сообщение (и текст, и документ)
    try:
        await message.delete()
    except Exception as e:
        print(f"[WARN] Не удалось удалить сообщение пользователя: {e}")

    # достаём id “липкого” сообщения бота
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")

    keywords: list[str] = []

    if message.document:  # ✅ путь для .txt
        print("[DEBUG] Получен документ:", message.document.file_name)

        # (опционально) проверим расширение
        filename = (message.document.file_name or "").lower()
        if not filename.endswith(".txt"):
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_msg_id,
                text="❗ Пришли файл в формате .txt (по одному ключу в строке)."
            )
            return

        # (опционально) ограничение на размер, чтобы не класть память
        # if message.document.file_size and message.document.file_size > 2_000_000:
        #     ...

        # сохраняем во временный файл и читаем построчно
        ts = int(time.time())
        tmp_path = os.path.join(TEMP_DIR, f"keywords_{message.from_user.id}_{ts}.txt")
        try:
            # aiogram v3: скачиваем через бота
            await message.bot.download(message.document, destination=tmp_path)
        except Exception as e:
            print("[ERROR] Ошибка скачивания файла:", e)
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_msg_id,
                text=f"❗ Не удалось скачать файл: {e}"
            )
            return

        try:
            keywords = await _read_txt_lines(tmp_path)
            print(f"[DEBUG] Считано {len(keywords)} ключей из файла.")
        except Exception as e:
            print("[ERROR] Ошибка чтения файла:", e)
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_msg_id,
                text="❗ Не удалось прочитать файл с ключами. Проверь кодировку/содержимое и попробуй ещё раз."
            )
            return
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    else:  # ✅ путь для текстового ввода
        print("[DEBUG] Получен текст:", message.text)
        keywords = [line.strip() for line in (message.text or "").splitlines() if line.strip()]
        print(f"[DEBUG] Считано {len(keywords)} ключей из текста.")

    if not keywords:
        print("[WARN] Ключевые слова не найдены!")
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=bot_msg_id,
            text="❗ Ключевые слова не найдены. Пришли список ещё раз (текстом или .txt файлом)."
        )
        return

    # сохраняем и двигаемся дальше
    await state.update_data(keywords=keywords)
    await state.set_state(MassSearchStates.waiting_for_min_members)

    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=bot_msg_id,
        text="👥 Пришли минимальное количество участников в группе (например, 100000):"
    )


# 2. Минимальное количество участников
@router.message(MassSearchStates.waiting_for_min_members)
async def mass_search_receive_min_members(message: types.Message, state: FSMContext):
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        print(f"[WARN] Не удалось удалить сообщение пользователя: {e}")

    text = message.text.strip().replace(" ", "")
    try:
        min_members = int(text)
        if min_members < 0:
            raise ValueError
        await state.update_data(min_members=min_members)
    except Exception:
        await message.answer("❗ Формат неверный. Пришли целое число, например <code>100000</code>")
        return

    # Получаем id сообщения бота и обновляем его
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    if bot_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_msg_id,
                text="⏱️ Пришли задержку между аккаунтами (например, 2-5 секунд):"
            )
        except Exception as e:
            print(f"[WARN] Не удалось отредактировать сообщение бота: {e}")
    else:
        new_msg = await message.answer("⏱️ Пришли задержку между аккаунтами (например, 2-5 секунд):")
        await state.update_data(bot_msg_id=new_msg.message_id)

    await state.set_state(MassSearchStates.waiting_for_delay_between_accounts)


# 3. Задержка между аккаунтами
@router.message(MassSearchStates.waiting_for_delay_between_accounts)
async def mass_search_receive_delay_accounts(message: types.Message, state: FSMContext):
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception as e:
        print(f"[WARN] Не удалось удалить сообщение пользователя: {e}")

    text = message.text.strip().replace(" ", "")
    try:
        delay_acc_min, delay_acc_max = map(int, text.split('-'))
        await state.update_data(delay_between_accounts=(delay_acc_min, delay_acc_max))
    except Exception:
        await message.answer("❗ Формат неверный. Пришли как <code>2-5</code>")
        return

    # Получаем id предыдущего сообщения бота
    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    if bot_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_msg_id,
                text="⏱️ Пришли задержку между поисками по ключам (например, 5-10 секунд):"
            )
        except Exception as e:
            print(f"[WARN] Не удалось отредактировать сообщение бота: {e}")
    else:
        new_msg = await message.answer("⏱️ Пришли задержку между поисками по ключам (например, 5-10 секунд):")
        await state.update_data(bot_msg_id=new_msg.message_id)

    await state.set_state(MassSearchStates.waiting_for_delay_between_queries)


# 4. Задержка между поисками по ключам, запуск поиска

@router.message(MassSearchStates.waiting_for_delay_between_queries)
async def mass_search_receive_delay_queries(message: types.Message, state: FSMContext):
    try:
        await message.delete()
    except:
        pass

    text = message.text.strip().replace(" ", "")
    try:
        delay_key_min, delay_key_max = map(int, text.split('-'))
        await state.update_data(delay_between_queries=(delay_key_min, delay_key_max))
    except Exception:
        await message.answer("❗ Формат неверный. Пришли как <code>5-10</code>")
        return

    data = await state.get_data()
    bot_msg_id = data.get("bot_msg_id")
    keywords = data.get("keywords", [])
    min_members = data.get("min_members", 100_000)
    delay_between_accounts = data.get("delay_between_accounts", (2, 5))
    delay_between_queries = data.get("delay_between_queries", (5, 10))

    user_id = message.from_user.id
    params = {
        "keywords": keywords,
        "min_members": min_members,
        "delay_between_accounts": delay_between_accounts,
        "delay_between_queries": delay_between_queries,
    }
    task_id = create_task_entry(
        task_type="mass_group_search",
        created_by=user_id,
        payload=params,
    )
    
    if bot_msg_id:
        try:
            temp_msg = await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=bot_msg_id,
                text=f"📋 Задача #{task_id} запущена, карточка обновляется...",
                parse_mode="HTML"
            )
            # Держим сообщение 1 секунду и удаляем
            await asyncio.sleep(1)
            try:
                await temp_msg.delete()
            except Exception as e:
                print(f"[WARN] Не удалось удалить временное сообщение: {e}")
        except Exception as e:
            print(f"[WARN] Не удалось обновить сообщение бота: {e}")


    
   
    update_task_status(task_id, "running")

    log_task_event(task_id, "Массовый парсинг групп запущен", status="info")
    log_task_event(task_id, f"Ключи поиска: {', '.join(keywords)}", status="info")
    log_task_event(task_id, f"Мин. участников: {min_members}", status="info")
    log_task_event(task_id, f"Задержки: аккаунты {delay_between_accounts} | ключи {delay_between_queries}", status="info")

    # ВАЖНО: state здесь НЕ чистим — из него нужны выбранные аккаунты!
    asyncio.create_task(send_task_card(message.bot, message.from_user.id, task_id))

    # ---- читаем выбранные аккаунты из FSM (поддержка разных ключей хранилища) ----
    data2 = await state.get_data()
    selected_ids = (
        data2.get("ms_selected")               # если вы сохраняли как ms_selected
        or data2.get("selected_account_ids")   # если делали совместимость с другими экранами
        or data2.get("selected_accounts")      # вариант из некоторых ваших хендлеров
        or []
    )
    if not selected_ids:
        update_task_status(task_id, "error", "Не выбраны аккаунты")
        await message.answer("⚠️ Не выбраны аккаунты для поиска.")
        return

    # возьмём полные записи аккаунтов
    all_accounts = data2.get("ms_accounts") or data2.get("crch_accounts") or get_all_accounts()
    acc_by_id = {int(a["id"]): a for a in all_accounts}
    accounts = [acc_by_id[i] for i in map(int, selected_ids) if i in acc_by_id]

    if not accounts:
        update_task_status(task_id, "error", "Не удалось собрать аккаунты")
        await message.answer("⚠️ Не удалось собрать выбранные аккаунты.")
        return

    # для наглядности
    print(f"[MASS_SEARCH] accounts to run: {len(accounts)} | ids={selected_ids}")

    _random.shuffle(accounts)

    acc_count = len(accounts)
    key_map = {a["id"]: [] for a in accounts}
    for idx, kw in enumerate(keywords):
        a = accounts[idx % acc_count]
        key_map[a["id"]].append(kw)

    account_dict = {a["id"]: a for a in accounts}
    
    # ----------- Прогресс ----------
    counters = {"processed": 0, "found": 0}
    total_keywords = len(keywords)

    async def run_account_search(acc):
        
        acc_id = acc["id"]
        if not key_map[acc_id]:
            return
        log_task_event(task_id, f"Акт. {acc['username'] or acc['phone']} ищет: {', '.join(key_map[acc_id])}", status="info", account_id=acc_id)
        
        
        proxy = None
        if acc.get("proxy_host"):
            proxy = {
                "proxy_host": acc.get("proxy_host"),
                "proxy_port": acc.get("proxy_port"),
                "proxy_username": acc.get("proxy_username"),
                "proxy_password": acc.get("proxy_password"),
            }
        client = await get_client(acc["session_string"], proxy)
                
        try:
            await client.connect()
            for key in key_map[acc_id]:
                delay = random.uniform(*delay_between_queries)
                await asyncio.sleep(delay)
                try:
                    result = await client(SearchRequest(q=key, limit=20))
                    found = [
                        {
                            "id": chat.id,
                            "title": chat.title,
                            "username": chat.username,
                            "members": getattr(chat, "participants_count", None),
                        }
                        for chat in result.chats
                        if getattr(chat, "username", None) and hasattr(chat, "broadcast") and not chat.broadcast
                    ]
                    for group in found:
                        save_group_result(task_id, user_id, acc_id, key, group)
                    log_task_event(task_id, f"Ключ '{key}': найдено {len(found)} групп", status="info", account_id=acc_id)
                    counters["found"] += len(found)

                except Exception as e:
                    error_text = str(e)
                    log_task_event(task_id, f"Ошибка поиска по '{key}' у {acc.get('username') or acc.get('phone')}: {error_text}", status="error", account_id=acc_id)
                    await message.answer(f"❌ Ошибка поиска по '{key}' у {acc.get('username') or acc.get('phone')}: {error_text}")
                    update_account_status(acc_id, "Ошибка")
                    log_task_event(task_id, f"Акт. {acc.get('username') or acc.get('phone')} исключён из-за ошибки", status="warning", account_id=acc_id)
                    counters["processed"] += 1
                    update_task_progress(task_id, counters["processed"], total_keywords, counters["found"])
                    update_task_status(task_id, "error", error_text)
                    return

                
                counters["processed"] += 1
                update_task_progress(task_id, counters["processed"], total_keywords, counters["found"])

        finally:
            await client.disconnect()

    # Собираем все задачи и ждём их завершения
    tasks = [run_account_search(acc) for acc in accounts if key_map[acc["id"]]]
    await asyncio.gather(*tasks)

    log_task_event(task_id, "Поиск завершён, формирую файл...", status="success")

    done_msg = await message.answer("✅ Поиск завершён, формирую файл...")
    await asyncio.sleep(1)
    try:
        await done_msg.delete()
    except:
        pass


    results = get_group_results_by_task(task_id, user_id)
    if not results:
        log_task_event(task_id, "Результатов нет", status="warning")
        update_task_status(task_id, "completed", "Результатов нет")
        await message.answer("❌ Ничего не найдено.")
        return

    groups_by_keyword = defaultdict(list)
    for keyword, title, username, members in results:
        groups_by_keyword[keyword].append((title, username, members))

    file_path = f"/tmp/groups_search_{task_id}.txt"
    # Сначала собираем только ссылки по ключам где есть группы больше фильтра
    summary_lines = []
    summary_lines.append("Группы больше фильтра\n")

    for keyword in keywords:
        groups = groups_by_keyword.get(keyword, [])
        high = [g for g in groups if (g[2] or 0) >= min_members]
        if high:
            summary_lines.append(f"Ключ: {keyword}")
            for title, username, members in high:
                url = f"https://t.me/{username}" if username else ""
                if url:
                    summary_lines.append(url)
            summary_lines.append("")  # пустая строка между ключами

    # Записываем summary первым в файл
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))
        f.write("\n" + "="*40 + "\n\n")  # визуальный разделитель

        # Дальше пишем подробный блок как было
        for keyword in keywords:
            groups = groups_by_keyword.get(keyword, [])
            f.write(f"Ключ: {keyword}\n\n")
            if not groups:
                f.write("Ничего не найдено\n\n")
                continue
            high = [g for g in groups if (g[2] or 0) >= min_members]
            low  = [g for g in groups if (g[2] or 0) <  min_members]
            if high:
                f.write(f"Группы с >= {min_members} участников:\n")
                for title, username, members in high:
                    url = f"https://t.me/{username}" if username else "[без username]"
                    mem_str = f"{members:,}".replace(",", " ") if members else ""
                    f.write(f"{title} — {url} ({mem_str})\n")
                f.write("\n")
            if low:
                f.write(f"Меньше фильтра ({min_members}):\n")
                for title, username, members in low:
                    url = f"https://t.me/{username}" if username else "[без username]"
                    mem_str = f"{members:,}".replace(",", " ") if members else ""
                    f.write(f"{title} — {url} ({mem_str})\n")
                f.write("\n")

    with open(file_path, "r", encoding="utf-8") as f:
        result_text = f.read()
    save_task_result(task_id, result_text)



    log_task_event(task_id, "Файл результатов отправлен пользователю", status="success")
    update_task_status(task_id, "completed")

    ok_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ OK (Удалить файл)", callback_data="groupcheck_delete_file_msg")]
        ]
    )

    msg = await message.answer_document(
        FSInputFile(file_path),
        caption="🗂️ Только чаты (группы)",
        reply_markup=ok_keyboard
    )
    os.remove(file_path)
    await state.clear()
    try:
        await state.clear()
    except Exception:
        pass



@router.callback_query(F.data == "groupcheck_delete_file_msg")
async def groupcheck_delete_file_msg(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("✅ Сообщение удалено!", show_alert=False)
