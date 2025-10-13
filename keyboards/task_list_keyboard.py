# keyboards/task_list_keyboard.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def task_list_keyboard(tasks):
    keyboard = []

    for idx, task in enumerate(tasks, start=1):
        keyboard.append([
            InlineKeyboardButton(
                text=f"📄 Задача #{idx}",
                callback_data=f"view_task_{idx}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_task_execution")
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def back_to_task_list_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Назад к списку задач", callback_data="tasktype_bulk_profile_update"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад в главное меню", callback_data="menu_main"),
            ]
        ]
    )
