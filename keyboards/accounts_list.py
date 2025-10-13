from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from math import ceil

PAGE_SIZE = 20

STATUS_ICONS = {
    "active": "🟢",
    "new": "🆕",
    "banned": "🔴",
    "freeze": "❄️",  # статус в БД 'freeze'
    "needs_login": "🟡",
    "proxy_error": "🛡️",
    "unknown": "⚠️",
}

def _slice_page(items, page: int, page_size: int):
    """Безопасный слайс страницы."""
    total = len(items)
    pages = max(1, ceil(total / page_size)) if total else 1
    page = max(1, min(page, pages))  # clamp
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], page, pages, total

def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default

def accounts_list_keyboard(accounts, page: int = 1, page_size: int = PAGE_SIZE) -> InlineKeyboardMarkup:
    """
    Рисует клавиатуру со списком аккаунтов и пагинацией.
    accounts: list[dict] (поля id, phone, username, status)
    """
    # 🔽 ключевая строка — сортируем по id по возрастанию
    accounts_sorted = sorted(accounts, key=lambda a: _safe_int(a.get("id"), 0))

    page_items, page, pages, total = _slice_page(accounts_sorted, page, page_size)
    kb = []

    for acc in page_items:
        phone = acc.get('phone', '-')
        username = acc.get('username') or ''
        acc_id = acc.get('id')
        status = acc.get('status', 'unknown')
        status_icon = STATUS_ICONS.get(status, "⚪️")

        parts = [f"{status_icon}", f"ID:{acc_id}", phone]
        if username:
            parts.append(f"@{username}")
        label = " | ".join(parts)

        kb.append([InlineKeyboardButton(text=label, callback_data=f"account_{acc_id}")])

    if pages > 1:
        nav_row = []
        if page > 1:
            nav_row += [
                InlineKeyboardButton(text="⏮️", callback_data="accpg:1"),
                InlineKeyboardButton(text="⬅️", callback_data=f"accpg:{page-1}")
            ]
        else:
            nav_row += [
                InlineKeyboardButton(text="⏮️", callback_data="noop"),
                InlineKeyboardButton(text="⬅️", callback_data="noop")
            ]
        nav_row.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data="noop"))
        if page < pages:
            nav_row += [
                InlineKeyboardButton(text="➡️", callback_data=f"accpg:{page+1}"),
                InlineKeyboardButton(text="⏭️", callback_data=f"accpg:{pages}")
            ]
        else:
            nav_row += [
                InlineKeyboardButton(text="➡️", callback_data="noop"),
                InlineKeyboardButton(text="⏭️", callback_data="noop")
            ]
        kb.append(nav_row)

    kb.append([InlineKeyboardButton(text="🧩 Массовая проверка", callback_data="update_all_profiles")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_accounts")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


