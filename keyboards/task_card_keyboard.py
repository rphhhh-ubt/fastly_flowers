# keyboards/task_card_keyboard.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.task_cards import TASK_CARD_DEFINITIONS


def get_task_card_keyboard(task_type, task_id):
    buttons_config = TASK_CARD_DEFINITIONS.get(task_type, {}).get("buttons", [])
    keyboard = []

    if "show_logs" in buttons_config:
        keyboard.append([InlineKeyboardButton(text="📁 Показать лог", callback_data=f"show_logs_{task_id}")])

    if "repeat_task" in buttons_config:
        keyboard.append([InlineKeyboardButton(text="♻️ Создать такую же задачу", callback_data=f"repeat_task_{task_type}")])

    if "delete_task" in buttons_config:
        keyboard.append([InlineKeyboardButton(text="❌ Удалить", callback_data=f"confirm_delete_task_{task_id}")])

        
    if "back" in buttons_config:
        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"tasktype_{task_type}")])


    return InlineKeyboardMarkup(inline_keyboard=keyboard)
