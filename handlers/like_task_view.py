from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def create_like_task_card(task_data: dict) -> tuple[str, InlineKeyboardMarkup]:
    task_id = task_data.get("id", 0)
    status = task_data.get("status", "unknown")

    # 🚨 КЛЮЧЕВАЯ ЛОГИКА: СТАТУС "running" — приоритетный!
    if status == "active":
        status_emoji = "⏳"
        status_text = "В процессе"
        last_error = None  # Не показываем ошибку, пока идёт работа
    else:
        # Только если НЕ "running" — смотрим на error/completed
        last_error = task_data.get("last_error", None)
        if status == "error":
            status_emoji = "🔴"
            status_text = "Ошибка"
        elif status == "completed":
            status_emoji = "🟢"
            status_text = "Завершена"
        else:
            status_emoji = "🟡"
            status_text = status.capitalize()
            last_error = None  # Не показываем неизвестные статусы как ошибки

    # Формируем подсказку об ошибке (если есть и статус не "running")
    error_hint = f"\n\n<code>{last_error}</code>" if last_error else ""

    total_accounts = task_data.get("total_accounts", len(task_data.get("selected_accounts", [])))
    total_posts = task_data.get("total_posts", 0)
    likes_done = task_data.get("likes_done", 0)
    skipped = task_data.get("skipped", 0)
    errors = task_data.get("errors", 0)
    try:
        joins_total = int(task_data.get("joins_total", 0) or 0)
    except Exception:
        joins_total = 0
           
    channels = task_data.get("channels", [])
    channels_count = len(channels) if isinstance(channels, list) else 0
    
    # ⚙️ Параллельность (читает из task_data, а не из payload!)
    
    parallel_cfg = (task_data.get("parallel") or {})
    concurrency = int(
        parallel_cfg.get("max_clients")
        or task_data.get("total_accounts")
        or len(task_data.get("selected_accounts", []))
        or 1
    )
    stagger = float(parallel_cfg.get("start_stagger_sec", 0.0) or 0.0)

    # ⏳ строку со стаггером готовим ОТДЕЛЬНО (чтобы не было '\n' внутри {...} у f-строки)
    stagger_line = f"⏳ Стаггер старта: {stagger}с\n" if stagger > 0 else ""


    card_text = (
        f"❤️ <b>Задача: Лайкинг комментариев</b>\n"
        f"<b>ID:</b> <code>{task_id}</code>\n"
        f"<b>Статус:</b> {status_emoji} {status_text}{error_hint}\n\n"
        f"👥 Аккаунтов: {total_accounts}\n"
        f"⚙️ Параллельных клиентов: {concurrency}\n"
        f"{stagger_line}"
        f"📡 Загружено каналов: {channels_count}\n\n"
        f"📝 Постов всего: {total_posts}\n"
        f"👍 Лайков проставлено: {likes_done}\n"
        f"🙋 Вступили в группы: {joins_total}\n\n"
        f"⏭️ Скипнуто: {skipped}\n"
        f"❌ Ошибок: {errors}"
    )

    keyboard_buttons = [
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_like_task_{task_id}")],
        [InlineKeyboardButton(text="📄 Лог задачи", callback_data=f"show_like_log_{task_id}")],
        [InlineKeyboardButton(text="📤 Выгрузить каналы с лайками", callback_data=f"like_export_{task_id}")],
        [InlineKeyboardButton(text="🔄 Создать такую же задачу", callback_data="start_like_comments_task")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_like_task_{task_id}")],
        [InlineKeyboardButton(text="⏹ Стоп карусели", callback_data=f"like_loop_stop_{task_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_like_tasks")]
    ]

    # 💥 Добавляем кнопку "Перезапустить" ТОЛЬКО если задача завершилась с ошибкой
    if status == "error":
        keyboard_buttons.insert(0, [
            InlineKeyboardButton(
                text="🔄 Перезапустить задачу",
                callback_data=f"retry_task_{task_id}"
            )
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    return card_text, keyboard