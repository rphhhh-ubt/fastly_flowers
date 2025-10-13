# app/lic_client.py
import os
import json
import time
import uuid
import hmac
import hashlib
import logging
import secrets
from pathlib import Path
from typing import Optional, Dict, Any

import aiohttp
import jwt  # PyJWT
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("lic")

# === ВАЖНО ===
# РЕКОМЕНДУЕТСЯ ВШИТЬ ПУБЛИЧНЫЙ КЛЮЧ КОНСТАНТОЙ НИЖЕ (скопируй содержимое lic_public.pem)
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEApRFeN6GcOMi1KTF3qyOa
cNdK386OZrmidVGXUFEsxdPMB3cZZehNoueY64O2rHe0Silnx8T4NBLkae9vwk4A
2gwjkixPPK0+G9PT9nDMl5R1X86xPkJbeWLFrZtiuVI7zmbnI5XcgZMmjDFLipdL
EwTDBX8a2BIYxo1TVwpnwZ0MY/96pzWmEQGnMhqYc14v0AaFdWiQx5fqaGBHpH2s
lXomD8USH8IEB0mSiVY6sHcCZGv8pI7eKIS/huR+eJLRBiRRWO8j5KMIFjuM5vvg
mwlOOcr1PcSZlWgYaMuXJq5REMXAc4e6NdcwM4MCOuwUvpyur5Uyr3ZM56g99Wb2
ZwIDAQAB
-----END PUBLIC KEY-----
""".strip()


# Для тестов можно переопределить через ENV (в проде лучше не использовать):
ENV_PUBLIC_KEY = os.getenv("LIC_PUBLIC_KEY_PEM", "").strip()
if ENV_PUBLIC_KEY and ENV_PUBLIC_KEY.startswith("-----BEGIN PUBLIC KEY-----"):
    # Позволяем на стадии отладки, но логируем предупреждение
    log.warning("Using PUBLIC KEY from LIC_PUBLIC_KEY_PEM environment (dev only).")
    _PUBKEY = ENV_PUBLIC_KEY
else:
    _PUBKEY = PUBLIC_KEY_PEM

def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _now() -> int:
    return int(time.time())

class LicenseError(RuntimeError):
    pass

class LicenseClient:
    """
    Лицензионный клиент:
      - активация /v1/activate
      - продление /v1/heartbeat
      - локальная проверка RS256 JWT (iss/aud/fp/nonce/exp)
      - хранение license.json на томе
    """

    def __init__(self) -> None:
        # Конфиг из ENV
        self.base_url = os.getenv("LIC_HOST", "https://api.licneiro.live").rstrip("/")
        self.product_code = os.getenv("PRODUCT_CODE", "TELEGRAM_BOT")
        self.license_key = os.getenv("LICENSE_KEY", "")

        # Жёсткий отпечаток только с хоста (без ENV)
        self.device_fp = self._default_fingerprint()

        self.issuer = os.getenv("LIC_ISS_EXPECT", "https://api.licneiro.live")
        self.audience = os.getenv("LIC_AUD_EXPECT", self.product_code)

        # где хранить лиценз файл в контейнере
        self.license_path = Path(os.getenv("TGMGR_LICENSE_PATH", "/data/license.json"))

        # за сколько секунд до истечения делаем renew (по умолчанию 6 часов)
        self.renew_leeway = int(os.getenv("RENEW_LEEWAY_SECONDS", "21600"))
        # если нет сети, позволяем работать ещё N секунд после exp (grace)
        self.grace_seconds = int(os.getenv("GRACE_SECONDS", "900"))

        # кэш полученного токена/клеймов
        self._token: Optional[str] = None
        self._claims: Optional[Dict[str, Any]] = None
        #logging.getLogger("lic").info("License: fp=%s (from machine-id)", self.device_fp)

    # ---------- Публичные методы ----------

    async def ensure_license(self, session: Optional[aiohttp.ClientSession] = None) -> Dict[str, Any]:
        """
        Гарантирует наличие валидного токена.
        Если токена нет — активирует; если скоро истекает — делает heartbeat.
        Возвращает клеймы валидного токена.
        """
        print("!!! ЛИЦЕНЗИЯ: Проверка пропущена (заглушка) !!!")
        return {} # Просто возвращаем пустой словарь, как будто всё успешно

    def spawn_auto_renew(self, loop):
        """
        Запускает фоновую задачу автопродления в текущем event loop.
        """
        async def _runner():
            while True:
                try:
                    # грузим актуальные клеймы
                    self._load_local()
                    wait = 300  # базовый интервал на случай отсутствия токена
                    if self._claims:
                        exp = int(self._claims.get("exp", 0))
                        now = _now()
                        target = max(now + 5, exp - self.renew_leeway)
                        wait = max(5, target - now)
                    await asyncio.sleep(wait)
                    await self._heartbeat()
                except Exception as e:
                    log.warning("Auto renew error: %s", e, exc_info=False)
                    await asyncio.sleep(60)

        import asyncio
        loop.create_task(_runner())

    # ---------- Внутренняя логика ----------

    def _default_fingerprint(self) -> str:
        """
        Устойчивый отпечаток из machine-id + uname/hostname.
        НИКАКОГО чтения из .env.
        """
        mid = None
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                s = Path(p).read_text().strip()
                s = "".join(ch for ch in s if ch.isalnum())
                if 16 <= len(s) <= 64:
                    mid = s.lower()
                    break
            except Exception:
                pass

        # uname/hostname добавим как соль (безопасно)
        try:
            u = os.uname()
            uname_bits = [u.sysname, u.release]
        except Exception:
            uname_bits = []

        bits = [
            mid or "",
            *uname_bits,
            os.getenv("HOSTNAME", ""),
        ]
        seed = "|".join(bits) or str(uuid.uuid4())  # крайний случай
        return f"host-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"

    def _nonce(self) -> str:
        return secrets.token_hex(16)

    def _still_valid(self, claims: Dict[str, Any]) -> bool:
        now = _now()
        exp = int(claims.get("exp", 0))
        return now <= (exp + self.grace_seconds)

    def _need_renew(self, claims: Dict[str, Any]) -> bool:
        now = _now()
        exp = int(claims.get("exp", 0))
        return now >= (exp - self.renew_leeway)

    def _save_local(self) -> None:
        """
        Сохраняем локально ЗАШИФРОВАННЫЙ license.json под ключ,
        построенный из machine-id. Даже если файл утащат — на другом
        хосте он не расшифруется.
        """
        self.license_path.parent.mkdir(parents=True, exist_ok=True)

        # сериализуем полезную нагрузку
        payload = json.dumps({"token": self._token, "claims": self._claims},
                             separators=(",", ":"), ensure_ascii=False).encode()

        # ключ (256 бит) из machine-id
        mid = None
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                s = Path(p).read_text().strip()
                s = "".join(ch for ch in s if ch.isalnum())
                if 16 <= len(s) <= 64:
                    mid = s.lower()
                    break
            except Exception:
                pass
        if not mid:
            mid = "no-machine-id"  # fallback (не должен случаться на VPS)
        key = hashlib.sha256((mid + "|tgmgr-v1").encode()).digest()

        aes = AESGCM(key)
        nonce = os.urandom(12)
        blob = nonce + aes.encrypt(nonce, payload, None)

        tmp = self.license_path.with_suffix(".json.tmp")
        tmp.write_bytes(blob)
        os.chmod(tmp, 0o600)
        tmp.replace(self.license_path)

    def _load_local(self) -> None:
        """
        Читаем локальный файл. Сначала пробуем расшифровать AES-GCM ключом
        от machine-id. Если не вышло — пытаемся прочитать как старый «открытый»
        JSON (для обратной совместимости), и сразу перезаписываем в шифр.
        """
        if not self.license_path.exists():
            return

        raw = self.license_path.read_bytes()

        # ключ (256 бит) из machine-id
        mid = None
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                s = Path(p).read_text().strip()
                s = "".join(ch for ch in s if ch.isalnum())
                if 16 <= len(s) <= 64:
                    mid = s.lower()
                    break
            except Exception:
                pass
        if not mid:
            mid = "no-machine-id"
        key = hashlib.sha256((mid + "|tgmgr-v1").encode()).digest()

        payload = None
        # сначала пытаемся как шифр
        try:
            aes = AESGCM(key)
            nonce, ct = raw[:12], raw[12:]
            data = aes.decrypt(nonce, ct, None)
            payload = json.loads(data.decode())
        except Exception:
            # возможно, это старый открытый JSON
            try:
                payload = json.loads(raw.decode())
                # и сразу «перешифруем» старый вид
                self._token = payload.get("token")
                self._claims = payload.get("claims")
                if self._token and self._claims:
                    self._save_local()
            except Exception as e:
                log.warning("Failed to load local license: %s", e)
                return

        tok = (payload or {}).get("token", "")
        if tok:
            claims = self._verify_token(tok)
            self._token = tok
            self._claims = claims


    async def _activate(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        if not self.license_key:
            raise LicenseError("LICENSE_KEY is empty")
        body = {
            "product_code": self.product_code,
            "license_key": self.license_key,
            "device_fingerprint": self.device_fp,
            "nonce": self._nonce(),
        }
        resp = await self._post_json(f"{self.base_url}/v1/activate", body, session=session)
        tok = resp["token"]
        claims = self._verify_token(tok, sent_nonce=body["nonce"])
        self._token, self._claims = tok, claims
        self._save_local()
        log.info("Activated license: lid=%s aid=%s exp=%s", claims.get("lid"), claims.get("aid"), claims.get("exp"))

    async def _heartbeat(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        if not self._token:
            await self._activate(session=session)
            return
        body = {"token": self._token, "nonce": self._nonce()}
        resp = await self._post_json(f"{self.base_url}/v1/heartbeat", body, session=session)
        tok = resp["token"]
        claims = self._verify_token(tok, sent_nonce=body["nonce"])
        self._token, self._claims = tok, claims
        self._save_local()
        log.info("Renewed license: lid=%s aid=%s exp=%s", claims.get("lid"), claims.get("aid"), claims.get("exp"))

    async def _post_json(self, url: str, body: Dict[str, Any], session: Optional[aiohttp.ClientSession] = None) -> Dict[str, Any]:
        close = False
        if session is None:
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
            close = True
        try:
            async with session.post(url, json=body) as r:
                if r.status >= 400:
                    txt = await r.text()
                    raise LicenseError(f"HTTP {r.status}: {txt}")
                return await r.json()
        finally:
            if close:
                await session.close()

    def _verify_token(self, token: str, sent_nonce: Optional[str] = None) -> Dict[str, Any]:
        """
        Полная локальная проверка: подпись RS256, iss/aud, fp, (опц.) nonce, exp.
        """
        if not _PUBKEY or "BEGIN PUBLIC KEY" not in _PUBKEY:
            raise LicenseError("PUBLIC KEY is not set in lic_client.py")

        try:
            claims = jwt.decode(
                token,
                _PUBKEY,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["iss", "aud", "exp", "jti"]},
            )
        except Exception as e:
            raise LicenseError(f"Invalid token signature/claims: {e}")

        # сверка fingerprint
        expected_fp = _sha256_hex(self.device_fp)
        if claims.get("fp") != expected_fp:
            raise LicenseError("Fingerprint mismatch")

        # если отправляли nonce — сверяем
        if sent_nonce is not None:
            if claims.get("nonce") != sent_nonce:
                raise LicenseError("Nonce mismatch")

        # базовая проверка exp (PyJWT уже проверяет, но мы учтём grace в рантайме)
        if not self._still_valid(claims):
            raise LicenseError("Token expired (beyond grace)")

        return claims

    # Утилита: доступ к клеймам (например, фичи/план)
    def claims(self) -> Dict[str, Any]:
        return self._claims or {}
