# app/telegram_client.py
from __future__ import annotations

import asyncio
import re
import socks
from typing import Optional, Tuple, Dict, Any

from telethon import TelegramClient, errors, functions
from telethon.sessions import StringSession, SQLiteSession

from app.db import (
    get_account_by_id,
    get_account_by_phone,
    get_account_by_session_string,
    get_available_api_key,
    increment_api_key_usage,
    update_account_status_to_banned,
)
_CLIENT_CACHE: dict[int, TelegramClient] = {}
_ACCOUNT_LOCKS: dict[int, asyncio.Lock] = {}
META_FIELDS = ("device_model", "system_version", "app_version", "lang_code", "system_lang_code")

# -----------------------------
# Вспомогательные билдеры/утилы
# -----------------------------

# app/telegram_client.py
async def get_or_create_account_client(account_id: int) -> TelegramClient:
    """
    Вернёт подключённый (или переподключённый) клиент для аккаунта.
    Единая точка reuse без дублирования соединений.
    """
    lock = _ACCOUNT_LOCKS.setdefault(account_id, asyncio.Lock())
    async with lock:
        cli = _CLIENT_CACHE.get(account_id)
        if cli is not None:
            try:
                if not cli.is_connected():
                    await cli.connect()
                return cli
            except Exception:
                try:
                    await cli.disconnect()
                except Exception:
                    pass
                _CLIENT_CACHE.pop(account_id, None)
                cli = None

        # создаём новый
        client = create_client_from_account(account_id)  # твоя фабрика
        await client.connect()
        _CLIENT_CACHE[account_id] = client
        return client


async def dispose_account_client(account_id: int):
    """
    Аккуратно убрать клиента из кеша (напр., при бане/фатале).
    В обычной работе лучше НЕ вызывать — reuse лучше.
    """
    lock = _ACCOUNT_LOCKS.setdefault(account_id, asyncio.Lock())
    async with lock:
        cli = _CLIENT_CACHE.pop(account_id, None)
        if cli:
            try:
                await cli.disconnect()
            except Exception:
                pass



def _extract_meta_kwargs(account: dict | None) -> dict:
    """
    Возвращает только те метаполя, которые реально присутствуют и непустые.
    Если аккаунт не найден/поля отсутствуют — вернёт пустой dict.
    """
    if not account:
        return {}
    return {k: account[k] for k in META_FIELDS if account.get(k)}


def _build_proxy_from_account(account: Optional[Dict[str, Any]]) -> Optional[Tuple]:
    """
    Собирает прокси-конфиг Telethon из записи аккаунта.
    """
    if not account:
        return None
    if (
        account.get("proxy_type") == "socks5"
        and account.get("proxy_host")
        and account.get("proxy_port")
    ):
        return (
            socks.SOCKS5,
            account["proxy_host"],
            int(account["proxy_port"]),
            bool(account.get("proxy_username")),
            account.get("proxy_username"),
            account.get("proxy_password"),
        )
    return None


def _build_client_params(api_id, api_hash, proxy, account):
    params = {"api_id": api_id, "api_hash": api_hash, "proxy": proxy}
    if account:
        for k in META_FIELDS:
            v = account.get(k)
            if v:
                params[k] = v
    return params



def _pick_api_key() -> Dict[str, Any]:
    api_key = get_available_api_key()
    if not api_key:
        raise RuntimeError("❌ Нет свободных API ключей")
    return api_key


# ---------------------------------
# ЕДИНАЯ фабрика клиентов с метаданными
# ---------------------------------

def make_client_with_metadata(
    *,
    account_id: Optional[int] = None,
    session_string: Optional[str] = None,
    phone: Optional[str] = None,
    proxy_override: Optional[Tuple] = None,
    increment_usage_after_connect: bool = False,
    sequential_updates: Optional[bool] = None,
) -> Tuple[TelegramClient, int]:
    """
    Универсальная точка создания TelegramClient.
    - Находит аккаунт по id / session_string / phone.
    - Подтягивает прокси и метаданные устройства из БД.
    - Возвращает (client, api_key_id). Если increment_usage_after_connect=False,
      то usage уже проинкрементен; если True — проинкременть после успешного connect().

    Пример:
        client, api_id = make_client_with_metadata(account_id=123, increment_usage_after_connect=True)
        await client.connect()
        increment_api_key_usage(api_id)
    """
    account: Optional[Dict[str, Any]] = None
    if account_id is not None:
        account = get_account_by_id(account_id)
    elif session_string is not None:
        account = get_account_by_session_string(session_string)
    elif phone is not None:
        account = get_account_by_phone(phone)

    # Сессия
    base_session_string = (account or {}).get("session_string") or session_string or ""
    if not base_session_string:
        raise RuntimeError("❌ Не удалось определить StringSession для клиента")

    sess = StringSession(base_session_string)

    # Прокси: override > из аккаунта > None
    proxy = proxy_override if proxy_override is not None else _build_proxy_from_account(account)

    # API ключ
    api_key = _pick_api_key()

    # Параметры клиента
    params = _build_client_params(
        api_id=api_key["api_id"],
        api_hash=api_key["api_hash"],
        proxy=proxy,
        account=account,
    )
    if sequential_updates is not None:
        params["sequential_updates"] = sequential_updates

    client = TelegramClient(sess, **params)

    if not increment_usage_after_connect:
        increment_api_key_usage(api_key["id"])

    return client, api_key["id"]


# ----------------------------
# Публичные хелперы (поверх фабрики)
# ----------------------------

def create_client_from_account(account_id: int) -> TelegramClient:
    """
    Старое поведение: получить клиента по account_id.
    Теперь всегда с метаданными и прокси из БД.
    """
    client, _ = make_client_with_metadata(account_id=account_id)
    return client


async def create_client_from_session(session_path: str, proxy: Optional[Dict[str, Any]] = None) -> TelegramClient:
    """
    Поддержка старого сценария импорта .session с диска.
    Если запись уже есть в БД — подтянет метаданные; если нет — будет без меты.
    """
    # .session → StringSession
    session_name = session_path.replace(".session", "")
    sqlite_session = SQLiteSession(session_name)
    string_session = StringSession.save(sqlite_session)

    proxy_tuple = None
    if proxy:
        proxy_tuple = (
            socks.SOCKS5,
            proxy["proxy_host"],
            proxy["proxy_port"],
            True if proxy.get("proxy_username") else False,
            proxy.get("proxy_username"),
            proxy.get("proxy_password"),
        )

    # Пытаемся создать клиента, инкрементим usage только после удачного connect()
    client, api_key_id = make_client_with_metadata(
        session_string=string_session,
        proxy_override=proxy_tuple,
        increment_usage_after_connect=True,
    )

    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Сессия не авторизована")

    increment_api_key_usage(api_key_id)
    return client


async def get_client(session_string: str, proxy: Optional[Dict[str, Any]] = None) -> TelegramClient:
    """
    Старый универсальный вход: получить клиента по session_string.
    Теперь тоже через фабрику, т.е. с метаданными, если аккаунт есть в БД.
    """
    proxy_tuple = None
    if proxy:
        proxy_tuple = (
            socks.SOCKS5,
            proxy["proxy_host"],
            proxy["proxy_port"],
            True if proxy.get("proxy_username") else False,
            proxy.get("proxy_username"),
            proxy.get("proxy_password"),
        )

    client, _ = make_client_with_metadata(
        session_string=session_string,
        proxy_override=proxy_tuple,
        sequential_updates=True,
    )
    return client


async def verify_account_status(session_string: str, phone: str, proxy: Optional[Dict[str, Any]] = None) -> str:
    """
    Проверка статуса аккаунта (OK / BANNED / PROXY_ERROR / NEEDS_ATTENTION / UNKNOWN).
    Теперь клиент создаётся через фабрику и тоже подхватывает метаданные, если они есть в БД.
    """
    proxy_tuple = None
    if proxy:
        proxy_tuple = (
            socks.SOCKS5,
            proxy["proxy_host"],
            proxy["proxy_port"],
            True if proxy.get("proxy_username") else False,
            proxy.get("proxy_username"),
            proxy.get("proxy_password"),
        )

    client, api_key_id = make_client_with_metadata(
        phone=phone if phone else None,
        session_string=session_string if session_string else None,
        proxy_override=proxy_tuple,
        sequential_updates=True,
        increment_usage_after_connect=True,
    )

    try:
        print(f"🚀 Пытаемся подключиться к аккаунту {phone}...")
        await client.connect()
        increment_api_key_usage(api_key_id)

        if not await client.is_user_authorized():
            print(f"⚠️ Аккаунт {phone} не авторизован. Требуется внимание.")
            return "NEEDS_ATTENTION"

        me = await client.get_me()
        if me:
            print(f"✅ Аккаунт {phone} активный.")
            return "OK"
        else:
            print(f"❗ Не удалось получить профиль для {phone}.")
            return "NEEDS_ATTENTION"

    except Exception as e:
        error_text = str(e).lower()

        if "authorization key" in error_text and "different ip addresses" in error_text:
            print(f"🚫 Сессия {phone} заблокирована из-за смены IP.")
            account = get_account_by_phone(phone)
            if account:
                update_account_status_to_banned(account[0])
            return "BANNED"

        if any(word in error_text for word in [
            "proxy", "timeout", "connection failed", "socks5 authentication failed",
            "connection refused", "network unreachable", "name resolution",
        ]):
            print(f"🛡️ Проблема с прокси или соединением при подключении: {e}")
            return "PROXY_ERROR"

        print(f"❗ Неизвестная ошибка при подключении к {phone}: {e}")
        return "UNKNOWN"

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ----------------------------
# Переавторизация (без изменений по логике, но с единым стилем)
# ----------------------------

def _make_client_from_string(string_session: str, api_id: int, api_hash: str, proxy: Optional[Tuple]):
    return TelegramClient(StringSession(string_session), api_id, api_hash, proxy=proxy)

def _make_client_new_session(api_id: int, api_hash: str, proxy: Optional[Tuple]):
    return TelegramClient(StringSession(), api_id, api_hash, proxy=proxy)

async def _read_latest_login_code_from_777000(client_old: TelegramClient, timeout_sec: int = 30) -> str:
    deadline = asyncio.get_event_loop().time() + timeout_sec
    code_re = re.compile(r'(\d{5,6})')
    while asyncio.get_event_loop().time() < deadline:
        async for msg in client_old.iter_messages(777000, limit=5):
            if msg.message:
                m = code_re.search(msg.message)
                if m:
                    return m.group(1)
        await asyncio.sleep(2)
    raise TimeoutError("Не удалось получить код из 777000 за отведённое время")

async def reauthorize_account_flow(
    api_id: int,
    api_hash: str,
    phone: str,
    old_string_session: str,
    proxy_conf: Optional[Tuple] | Optional[Dict[str, Any]],
    twofa_password: Optional[str],
    kill_other_sessions: bool = True,
):
    """
    Процесс переавторизации:
      - читаем код из 777000 старой сессией
      - логинимся новой сессией
      - (опционально) сбрасываем остальные авторизации
    """
    # Приведём proxy_conf к tuple, если это dict
    if isinstance(proxy_conf, dict):
        proxy_conf = (
            socks.SOCKS5,
            proxy_conf["proxy_host"],
            proxy_conf["proxy_port"],
            True if proxy_conf.get("proxy_username") else False,
            proxy_conf.get("proxy_username"),
            proxy_conf.get("proxy_password"),
        )

    client_old = _make_client_from_string(old_string_session, api_id, api_hash, proxy_conf)
    client_new = _make_client_new_session(api_id, api_hash, proxy_conf)

    await client_old.connect()
    await client_new.connect()
    try:
        if not await client_old.is_user_authorized():
            raise RuntimeError("Старая сессия не авторизована; не сможем прочитать код из 777000")

        await client_new.send_code_request(phone)
        code = await _read_latest_login_code_from_777000(client_old, timeout_sec=60)

        try:
            await client_new.sign_in(phone=phone, code=code)
        except errors.SessionPasswordNeededError:
            if twofa_password:
                await client_new.sign_in(password=twofa_password)
            else:
                raise RuntimeError("Нужен пароль 2FA, но он не указан")

        me = await client_new.get_me()
        new_string = client_new.session.save()
        info = {
            "id": me.id,
            "first_name": getattr(me, "first_name", "") or "",
            "last_name": getattr(me, "last_name", "") or "",
            "username": getattr(me, "username", "") or "",
            "phone": getattr(me, "phone", "") or "",
        }

        if kill_other_sessions:
            try:
                await client_new(functions.account.ResetAuthorizationsRequest())
            except Exception as e:
                return {"ok": True, "string_session": new_string, "user": info, "warn": f"ResetAuthorizations failed: {e}"}

        return {"ok": True, "string_session": new_string, "user": info}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await client_old.disconnect()
        await client_new.disconnect()
