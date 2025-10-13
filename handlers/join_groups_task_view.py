from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def create_join_groups_task_card(task_data: dict) -> tuple[str, InlineKeyboardMarkup]:
    total_accounts  = task_data.get("total_accounts", 0)
    total_groups    = task_data.get("total_groups", 0)
    success_joins   = task_data.get("success_joins", 0)
    captcha_joins   = task_data.get("captcha_joins", 0)
    pending_joins   = task_data.get("pending_joins", 0)
    failed_joins    = task_data.get("failed_joins", 0)
    frozen_accounts = task_data.get("frozen_accounts", 0)
    avg_delay       = task_data.get("avg_delay", 0)
    total_time      = task_data.get("total_time", "0 мин")
    task_id         = task_data.get("task_id", 0)
    status          = task_data.get("status", "🟡 В процессе")

    done_joins = success_joins + captcha_joins + pending_joins + failed_joins
    progress_percent = round((done_joins / total_groups) * 100) if total_groups else 0
    progress_bar = f"[{'█' * (progress_percent // 5)}{'▒' * (20 - (progress_percent // 5))}] {progress_percent}%"

    card_text = (
        f"📋 <b>Задача: Вступление в группы</b>\n"
        f"<b>ID задачи:</b> <code>{task_id}</code>\n"
        f"<b>Статус:</b> <b>{status}</b>\n\n"
        f"👥 <b>Аккаунтов задействовано:</b> {total_accounts}\n"
        f"📌 <b>Групп в задаче:</b> {total_groups}\n\n"
        f"✅ <b>Успешных вступлений:</b> {success_joins}\n"
        f"🤖 <b>Вступлений с капчей:</b> {captcha_joins}\n"
        f"⏳ <b>Ожидают одобрения:</b> {pending_joins}\n"
        f"❌ <b>Ошибок при вступлении:</b> {failed_joins}\n\n"
        f"🚫 <b>Аккаунтов заморожено/забанено:</b> {frozen_accounts}\n"
        f"🕓 <b>Средняя задержка между вступлениями:</b> {avg_delay} сек\n"
        f"⏱ <b>Время выполнения задачи:</b> {total_time}\n\n"
        f"🔄 <b>Прогресс:</b>\n{progress_bar}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"join_refresh_{task_id}")],
        [InlineKeyboardButton(text="📄 Показать подробный лог", callback_data=f"show_join_task_log_{task_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить задачу", callback_data=f"delete_join_task_{task_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_join_groups_tasks")]
    ])
    return card_text, keyboard


