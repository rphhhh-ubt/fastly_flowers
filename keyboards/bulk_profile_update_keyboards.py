# keyboards/bulk_profile_update_keyboards.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def select_accounts_keyboard(accounts, selected_ids=None):
    if selected_ids is None:
        selected_ids = []

    keyboard = []

    for acc in accounts:
        acc_id = acc["id"]
        phone = acc.get("phone", "-")
        username = acc.get("username", "")

        label = f"{phone}" if not username else f"{phone} | @{username}"

        is_selected = "✅" if acc_id in selected_ids else "☑️"
        button_text = f"{is_selected} {label}"

        keyboard.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"toggle_account_{acc_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(text="✅ Выбрать всех", callback_data="select_all_accounts"),
        InlineKeyboardButton(text="➡️ Далее", callback_data="proceed_after_selecting_accounts"),
    ])
    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад к созданию задач", callback_data="menu_tasks"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def skip_firstname_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚫 Не обновлять Имя", callback_data="skip_firstname"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад к созданию задач", callback_data="menu_tasks"),
            ]
        ]
    )

def skip_lastname_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚫 Не обновлять Фамилию", callback_data="skip_lastname"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад к созданию задач", callback_data="menu_tasks"),
            ]
        ]
    )

def skip_bio_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚫 Не менять BIO", callback_data="skip_bio")],
            [InlineKeyboardButton(text="🧹 Очистить BIO", callback_data="clear_bio")],
            [InlineKeyboardButton(text="⬅️ Назад к созданию задач", callback_data="menu_tasks")]
        ]
    )



def run_now_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Запустить сразу", callback_data="run_now"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад к созданию задач", callback_data="menu_tasks"),
            ]
        ]
    )

def confirm_task_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить запуск", callback_data="confirm_bulk_profile_update"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад к созданию задач", callback_data="menu_tasks"),
            ]
        ]
    )


def ok_to_delete_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ ОК", callback_data="delete_log_message"),
            ]
        ]
    )

def skip_avatar_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Не менять аватарки", callback_data="skip_avatar")]
    ])

def skip_username_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Не менять username", callback_data="skip_username")]
    ])

def select_accounts_keyboard_groupcheck(accounts, selected_ids=None):
    # Просто копия select_accounts_keyboard, только меняем prefix
    return select_accounts_keyboard(accounts, selected_ids, prefix="groupcheck_")
