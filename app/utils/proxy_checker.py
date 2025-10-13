# app/utils/proxy_checker.py

from telethon.sessions import StringSession
from app.db import get_available_api_key
import asyncio
import socks
import socket
import traceback
from telethon import TelegramClient, functions
from telethon.sessions import StringSession

# Список одного DC для “сырой” проверки CONNECT (можно расширить при желании)
TG_DC_IP = "149.154.167.51"
TG_DC_PORT = 443

def _mask(s: str | None) -> str:
    if not s:
        return ""
    return s[:1] + "***" if len(s) > 1 else "***"

def raw_socks5_probe(host: str, port: int, username: str | None, password: str | None, timeout: float = 5.0):
    """
    Синхронная проверка через PySocks: пробуем CONNECT к Telegram DC IP:443.
    Это даёт честный SOCKS-код ошибки (типа 0x02: ruleset).
    """
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, host, port, True, username, password)  # rdns=True
    s.settimeout(timeout)
    try:
        s.connect((TG_DC_IP, TG_DC_PORT))
        # Если получилось подключиться — отлично; дальше TLS рукопожатие нам не важно
        s.close()
        return True, "SOCKS CONNECT ok"
    except Exception as e:
        try:
            s.close()
        except:
            pass
        # Возвращаем текст ошибки (и класс) для логов
        return False, f"{e.__class__.__name__}: {e}"



async def is_proxy_working(proxy: dict) -> bool:
    """
    Проверка прокси: быстрый raw SOCKS5 CONNECT -> лёгкий RPC в Telegram.
    API-ключ берём из БД через get_available_api_key().
    """
    host = proxy.get('host')
    port = int(proxy.get('port'))
    user = proxy.get('username') or None
    pwd  = proxy.get('password') or None

    print(f"[PROXY TEST] tuple: SOCKS5 {host}:{port} rdns=True user={bool(user)}")

    # 1) Быстрая проверка сырого соединения через PySocks к DC
    ok_raw, raw_info = await asyncio.to_thread(raw_socks5_probe, host, port, user, pwd, 5.0)
    print(f"[PROXY TEST] raw SOCKS CONNECT → {TG_DC_IP}:{TG_DC_PORT}: {raw_info}")
    if not ok_raw:
        return False

    # 2) Берём API-ключ из БД
    api_key = get_available_api_key()
    if not api_key:
        print("[PROXY TEST] no available api key in DB")
        return False

    proxy_settings = (socks.SOCKS5, host, port, True, user, pwd)

    client = TelegramClient(
        StringSession(""),               # ВРЕМЕННАЯ сессия (не авторизуемся)
        api_key['api_id'],
        api_key['api_hash'],
        proxy=proxy_settings,
        connection_retries=1,
        request_retries=1,
        timeout=10,
        flood_sleep_threshold=0,
    )

    try:
        await client.connect()
        # 3) Лёгкий RPC без авторизации → не триггерит «reuse awaited coroutine»
        await client(functions.help.GetNearestDcRequest())
        print("[PROXY TEST] Telethon check OK")
        return True
    except Exception as e:
        print(f"[PROXY TEST] Telethon check FAILED: {e.__class__.__name__}: {e}")
        print(f"[PROXY TEST] traceback (short):\n{traceback.format_exc(limit=2)}")
        return False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def check_proxies_concurrently(proxies: list[dict], concurrency: int = 20):
    """
    Запускает проверки параллельно, но не более `concurrency` одновременно.
    Возвращает список результатов такой же длины, как `proxies`.
    Каждый элемент — (ok: bool, info: str | None, proxy: dict).
    """
    sem = asyncio.Semaphore(concurrency)

    async def bounded(px: dict):
        async with sem:
            ok = await is_proxy_working(px)
            # можешь вернуть здесь дополнительную инфу, если is_proxy_working её отдаёт
            return ok, None, px

    return await asyncio.gather(*(bounded(px) for px in proxies), return_exceptions=False)
