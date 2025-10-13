# config.py 
# Токен бота от @BotFather 
#BOT_TOKEN = "тут значение бот токена" 

# Список ID пользователей, которым разрешено пользоваться ботом 
# Можно узнать свой ID, написав любому боту типа @userinfobot 
#ADMIN_IDS = [ 
#    123456789, # сюда вставь свой Telegram user ID 
#] 

# При необходимости сюда можно добавить другие настройки проекта 
# Например, DATABASE_URL, настройки логирования и т.п. 

#FINGERPRINT_PROFILES = { 
#    "android": { 
#        "device_model": "Pixel 7 Pro", 
#        "system_version": "Android 13", 
#        "app_version": "Telegram 10.11" 
#    },
#    "ios": { 
#        "device_model": "iPhone 14 Pro", 
#        "system_version": "iOS 17.5", 
#        "app_version": "Telegram iOS 10.11" 
#    }, "pc": { 
#    "device_model": 
#        "Neirotraf Worker 64-bit", 
#        "system_version": "Linux 5.15", 
#        "app_version": "Neirotraf 1.0" 
#    } 
#}


# config.py — ретранслятор переменных из .env
import os, json
from dotenv import load_dotenv


# Загружаем переменные окружения из .env файла
load_dotenv()

def _get_first_value(env_var_name: str, default: str = "") -> str:
    """
    Возвращает только первое значение из переменной окружения.
    Если строка содержит запятые или пробелы — берёт первый элемент.
    """
    raw = os.getenv(env_var_name, default).strip()
    if not raw:
        return default
    # Разделяем по запятым или пробелам и берём первый непустой элемент
    parts = [part.strip() for part in raw.replace(',', ' ').split() if part.strip()]
    return parts[0] if parts else default

def _get_first_int(env_var_name: str, default: int = 0) -> int:
    """
    Возвращает первое целое число из переменной окружения.
    """
    raw = _get_first_value(env_var_name, str(default))
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default

# --- Основные настройки бота ---
BOT_TOKEN = _get_first_value("BOT_TOKEN", "")

# --- Список администраторов (только первый ID!) ---
_ADMIN_ID_RAW = _get_first_value("ADMIN_ID", "0")  # Обрати внимание: ADMIN_ID (единственное число)
ADMIN_IDS = [_get_first_int("ADMIN_ID", 0)]  # Всегда список из одного элемента

# --- FINGERPRINT_PROFILES 

# --- FINGERPRINT_PROFILES: загружаем из .env ---
_RAW_FINGERPRINT_JSON = os.getenv("FINGERPRINT_PROFILES", "{}").strip()

try:
    FINGERPRINT_PROFILES = json.loads(_RAW_FINGERPRINT_JSON)
    if not isinstance(FINGERPRINT_PROFILES, dict):
        raise TypeError("FINGERPRINT_PROFILES must be a JSON object")
except (json.JSONDecodeError, TypeError) as e:
    print(f"[⚠️] Ошибка загрузки FINGERPRINT_PROFILES из .env: {e}")
    print("[ℹ️] Используются значения по умолчанию.")
    FINGERPRINT_PROFILES = {
        "android": {
            "device_model": "Pixel 7 Pro",
            "system_version": "Android 13",
            "app_version": "Telegram 10.11"
        },
        "ios": {
            "device_model": "iPhone 14 Pro",
            "system_version": "iOS 17.5",
            "app_version": "Telegram iOS 10.11"
        },
        "pc": {
            "device_model": "Neirotraf Worker 64-bit",
            "system_version": "Linux 5.15",
            "app_version": "Neirotraf 1.0"
        }
    }
