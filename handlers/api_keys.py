from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from app.db import get_connection

import os, datetime, asyncio

from aiogram.types import FSInputFile
from app.db import get_all_api_keys ,  get_all_api_keys_for_checker
from utils.api_key_checker import check_many



router = Router()

# опционально: общий прокси для проверки (если нужно)
PROXY = None
# PROXY = ('socks5', '127.0.0.1', 9050)  # пример, если надо

class AddApiKeyStates(StatesGroup):
    waiting_for_api_data = State()

class DeleteApiKeyStates(StatesGroup):
    waiting_for_key_ids = State()

def back_to_api_keys_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к списку ключей API", callback_data="show_api_keys")]
    ])

@router.callback_query(F.data == "show_api_keys")
async def show_api_keys(callback: types.CallbackQuery):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, api_id, api_hash, requests_today, daily_limit FROM api_keys ORDER BY id")
    keys = cur.fetchall()
    cur.execute("SELECT COUNT(*), SUM(requests_today), SUM(daily_limit - requests_today) FROM api_keys")
    total_count, total_requests, total_left = cur.fetchone()
    cur.close()
    conn.close()

    msg = f"🔑 <b>Ключи API</b>\n\n"
    msg += f"Общее количество ключей: <b>{total_count or 0}</b>\n"
    #msg += f"Всего запросов в сутки: <b>{total_requests or 0}</b>\n"
    #msg += f"Запросов осталось: <b>{total_left or 0}</b>\n\n"

    if not keys:
        msg += "Ключей нет. Добавьте хотя бы один.\n"
    else:
        msg += "<b>ID | API ID | Hash</b>\n"
        #msg += "<b>ID | API ID | Hash | Запросов сегодня</b>\n"
        for id_, api_id, api_hash, today, limit in keys:
            msg += f"<code>{id_}</code> | <code>{api_id}</code> | <code>{str(api_hash)[:5]}***</code>\n"
            #msg += f"<code>{id_}</code> | <code>{api_id}</code> | <code>{str(api_hash)[:5]}***</code> | <code>{today}/{limit}</code>\n"

    buttons = [
        #[InlineKeyboardButton(text="⚙️ Обновить данные", callback_data="refresh_api_keys")],
        [InlineKeyboardButton(text="❌ Удалить по ID", callback_data="delete_api_key")],
        [InlineKeyboardButton(text="➕ Добавить ключ", callback_data="add_api_key")],
        [InlineKeyboardButton(text="🧪 Проверить API", callback_data="check_api_keys")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_stats")],
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(msg, parse_mode="HTML", reply_markup=markup)
    await callback.answer()

@router.callback_query(F.data == "delete_api_key")
async def ask_delete_api_key(callback: types.CallbackQuery, state: FSMContext):
    sent = await callback.message.edit_text(
        "Введите <b>ID ключа</b> или несколько ID через запятую (например: <code>1, 3, 7</code>) для удаления:",
        parse_mode="HTML"
    )
    # Сохраняем ID сообщения для дальнейшего редактирования
    await state.update_data(prompt_msg_id=sent.message_id)
    await state.set_state(DeleteApiKeyStates.waiting_for_key_ids)
    await callback.answer()

@router.message(DeleteApiKeyStates.waiting_for_key_ids)
async def do_delete_api_keys(message: types.Message, state: FSMContext):
    # Удаляем сообщение пользователя с ID
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")

    text = message.text.replace(" ", "")
    ids = []
    for part in text.split(","):
        if part.isdigit():
            ids.append(int(part))
    if not ids:
        if prompt_msg_id:
            try:
                await message.bot.edit_message_text(
                    "❗ Не найдено ни одного ID. Попробуйте снова.",
                    chat_id=message.chat.id, message_id=prompt_msg_id,
                    reply_markup=back_to_api_keys_keyboard()
                )
            except Exception:
                await message.answer("❗ Не найдено ни одного ID. Попробуйте снова.", reply_markup=back_to_api_keys_keyboard())
        else:
            await message.answer("❗ Не найдено ни одного ID. Попробуйте снова.", reply_markup=back_to_api_keys_keyboard())
        await state.clear()
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM api_keys")
    existing_ids = {row[0] for row in cur.fetchall()}
    removed = 0
    for key_id in ids:
        if key_id in existing_ids:
            cur.execute("DELETE FROM api_keys WHERE id=%s", (key_id,))
            removed += 1
    conn.commit()
    cur.close()
    conn.close()

    # Редактируем приглашение на результат удаления
    if prompt_msg_id:
        try:
            await message.bot.edit_message_text(
                f"✅ Удалено ключей: {removed}",
                chat_id=message.chat.id, message_id=prompt_msg_id,
                reply_markup=back_to_api_keys_keyboard()
            )
        except Exception:
            await message.answer(f"✅ Удалено ключей: {removed}", reply_markup=back_to_api_keys_keyboard())
    else:
        await message.answer(f"✅ Удалено ключей: {removed}", reply_markup=back_to_api_keys_keyboard())
    await state.clear()

@router.callback_query(F.data == "add_api_key")
async def add_api_key(callback: types.CallbackQuery, state: FSMContext):
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад к списку ключей API", callback_data="show_api_keys")]
        ]
    )
    
    sent = await callback.message.edit_text(
        "Пришлите новый ключ в формате:\n<code>api_id:api_hash</code>\n(один на строку, можно сразу несколько)",
        parse_mode="HTML",
        reply_markup=markup
    )
    await state.set_state(AddApiKeyStates.waiting_for_api_data)
    # Если нужно — сохрани sent.message_id чтобы потом что-то редактировать (по аналогии)
    await callback.answer()

@router.message(AddApiKeyStates.waiting_for_api_data)
async def save_api_keys(message: types.Message, state: FSMContext):
    try:
        await message.delete()
    except Exception:
        pass

    lines = [line.strip() for line in message.text.splitlines() if line.strip()]
    count = 0
    conn = get_connection()
    cur = conn.cursor()
    for line in lines:
        if ':' in line:
            api_id, api_hash = line.split(':', 1)
            cur.execute(
                "INSERT INTO api_keys (api_id, api_hash, daily_limit, requests_today, last_reset) VALUES (%s, %s, %s, %s, NOW())",
                (api_id.strip(), api_hash.strip(), 1000, 0))
            count += 1
    conn.commit()
    cur.close()
    conn.close()
    await message.answer(f"✅ Добавлено ключей: {count}", reply_markup=back_to_api_keys_keyboard())
    await state.clear()

@router.callback_query(F.data == "refresh_api_keys")
async def refresh_api_keys(callback: types.CallbackQuery):
    try:
        await show_api_keys(callback)
    except Exception as e:
        # Если причина — message is not modified, просто молчим
        if "message is not modified" not in str(e):
            raise
    await callback.answer("Данные обновлены!")



@router.callback_query(F.data == "check_api_keys")
async def check_api_keys_cb(cb: types.CallbackQuery):
    await cb.answer("Запустил проверку…", show_alert=False)

    keys = get_all_api_keys_for_checker()  # [{'api_id':..., 'api_hash':..., 'name':...}]
    if not keys:
        return await cb.message.answer("⚠️ В таблице api_keys нет записей.")

    info = await cb.message.answer(f"🔍 Проверяю {len(keys)} API ключей…")

    # Параллельная проверка (аккуратно с лимитами DC)
    results = await check_many(keys, proxy=PROXY, concurrency=5)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = f"/tmp/api_keys_check_{ts}.txt"

    ok_cnt = 0
    lines = []
    lines.append("api_id\tstatus\treason\tlatency_ms\tdc_this/nearest\tname\n")
    for src, r in zip(keys, results):
        status = "OK" if r.ok else "FAIL"
        if r.ok:
            ok_cnt += 1
        dc_part = f"{r.dc_this}/{r.nearest_dc}" if r.dc_this else ""
        lat = str(r.latency_ms or "")
        name = (src.get("name") or "").replace("\t", " ").strip()
        lines.append(f"{r.api_id}\t{status}\t{r.reason}\t{lat}\t{dc_part}\t{name}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    await cb.message.answer_document(
        FSInputFile(path),
        caption=f"Готово: {ok_cnt}/{len(results)} ключей OK"
    )
    try:
        os.remove(path)
    except Exception:
        pass

    try:
        await info.delete()
    except Exception:
        pass