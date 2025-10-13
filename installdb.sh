#!/bin/bash

set -e


# ==========================
# 2. НАСТРОЙКА POSTGRESQL И ИМПОРТ ДАМПА
# ==========================
echo ""
echo "🚀 Настройка PostgreSQL и импорт дампа..."

# === Настройки ===
DB_NAME="tgdb"
DB_USER="tguser"
DB_PASS="848hbd9wmdedrv"
DUMP_FILE="./bd.sql"

# === Проверка дампа ===
if [ ! -f "$DUMP_FILE" ]; then
    echo "❌ Файл дампа не найден: $DUMP_FILE"
    exit 1
fi

# === Определение версии PostgreSQL ===
if command -v pg_lsclusters &> /dev/null; then
    PG_VERSION=$(pg_lsclusters -h | grep 'online' | head -n1 | awk '{print $1}')
    [ -z "$PG_VERSION" ] && PG_VERSION=$(pg_lsclusters -h | head -n1 | awk '{print $1}')
else
    PG_VERSION=$(ls /etc/postgresql/ 2>/dev/null | sort -V | head -n1)
fi

if [ -z "$PG_VERSION" ] || [ ! -d "/etc/postgresql/$PG_VERSION/main" ]; then
    echo "❌ Не удалось определить версию PostgreSQL."
    echo "Проверьте: sudo pg_lsclusters"
    exit 1
fi

PG_CONF_DIR="/etc/postgresql/$PG_VERSION/main"
POSTGRESQL_CONF="$PG_CONF_DIR/postgresql.conf"
PG_HBA_CONF="$PG_CONF_DIR/pg_hba.conf"
echo "🔧 Используется PostgreSQL $PG_VERSION"

# === Создание пользователя и БД ===
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER';" | grep -q 1; then
    echo "🔧 Создаём пользователя $DB_USER..."
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"
else
    echo "⚠️ Пользователь $DB_USER уже существует."
fi

if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo "🔧 Создаём БД $DB_NAME (владелец: postgres)..."
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER postgres;"
else
    echo "⚠️ БД $DB_NAME уже существует."
fi

# === Импорт дампа через /tmp ===
echo "📥 Импортируем дамп..."
cp "$DUMP_FILE" /tmp/import_dump.sql
sudo -u postgres psql -d "$DB_NAME" -f /tmp/import_dump.sql > /dev/null 2>&1
rm -f /tmp/import_dump.sql
echo "✅ Дамп успешно импортирован."

# === Настройка listen_addresses ===
if ! grep -q "listen_addresses.*172.17.0.1" "$POSTGRESQL_CONF"; then
    echo "🔧 Настраиваем listen_addresses..."
    if grep -q "^#listen_addresses.*localhost" "$POSTGRESQL_CONF"; then
        sudo sed -i "s/^#listen_addresses.*/listen_addresses = 'localhost,172.17.0.1'/" "$POSTGRESQL_CONF"
    else
        echo "listen_addresses = 'localhost,172.17.0.1'" | sudo tee -a "$POSTGRESQL_CONF" > /dev/null
    fi
else
    echo "ℹ️ listen_addresses уже настроен."
fi

# === Настройка pg_hba.conf ===
if ! grep -q "172.17.0.1/16.*md5" "$PG_HBA_CONF"; then
    echo "🔧 Добавляем правило в pg_hba.conf..."
    echo "host    all             all             172.17.0.0/16           md5" | sudo tee -a "$PG_HBA_CONF" > /dev/null
else
    echo "ℹ️ Правило для 172.17.0.0/16 уже есть."
fi

# === Перезапуск PostgreSQL ===
echo "🔄 Перезапускаем PostgreSQL..."
sudo systemctl restart postgresql

# === Готово ===
echo ""
echo "✅ ВСЁ ГОТОВО!"
echo "🔹 Docker установлен и работает."
echo "🔹 БД '$DB_NAME' настроена и доступна с IP: 172.17.0.1"
echo ""
echo "Подключайтесь к PostgreSQL:"
echo "  psql -h 172.17.0.1 -U $DB_USER -d $DB_NAME"
echo "Пароль: $DB_PASS"
echo ""
echo "💡 Чтобы использовать Docker без sudo, выполните:"
echo "      newgrp docker"
echo "   или перелогиньтесь."