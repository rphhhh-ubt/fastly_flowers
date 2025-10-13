# ---------- 1) Базовый рантайм ----------
FROM python:3.10-slim-bookworm AS runtime
ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates tzdata curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# ❗ ВАЖНО: сначала копируем и даём права — ПОКА ЕЩЁ ROOT
# (USER tgmgr будет в самом конце)

# ---------- 2) Builder: Python + deps + Nuitka ----------
FROM python:3.10-slim-bookworm AS builder
ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make libpq-dev libffi-dev libssl-dev zlib1g-dev patchelf \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# кэш pip между сборками
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -U pip wheel
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 \
    pip install --prefer-binary -r requirements.txt

# Nuitka
RUN --mount=type=cache,target=/root/.cache/pip pip install nuitka==2.4

# исходники проекта
COPY . .

# гарантируем, что каталоги — настоящие пакеты
RUN set -eux; for d in app handlers keyboards utils states tasks; do \
      [ -d "$d" ] && [ -f "$d/__init__.py" ] || { mkdir -p "$d"; touch "$d/__init__.py"; }; \
    done

# ---------- 3) Компиляция ТОЛЬКО utils/, tasks/, states/ в .so ----------
# ---------- 3) Компиляция ТОЛЬКО utils/, tasks/, states/ в .so ----------
RUN set -eux; \
  find utils tasks states -type f -name "*.py" ! -name "__init__.py" | while read -r f; do \
    echo ">>> Compiling $f"; \
    python -m nuitka \
      --module "$f" \
      --output-dir="$(dirname "$f")" \
      --jobs="$(nproc)" \
      --nofollow-import-to=tests; \
  done; \
  echo "=== CHECK: .so рядом с исходниками ==="; \
  find utils tasks states -type f -name "*.so" | head -25 || echo "⚠️ No .so found"; \
  echo "=== CLEAN SOURCES (кроме __init__.py) ==="; \
  find utils tasks states -type f -name "*.py" ! -name "__init__.py" -delete; \
  find utils tasks states -type f -name "*.pyc" -delete
  
# маленький лаунчер
RUN printf '%s\n' \
 'import asyncio, bot' \
 'asyncio.run(bot.main())' > /app/entry.py

# ---------- 4) Финальный образ ----------
FROM runtime AS app

# переносим интерпретатор и site-packages
COPY --from=builder /usr/local /usr/local

# копируем проект
COPY --from=builder /app/ /app/

# 🔥 1. Создаём пользователя
RUN useradd -r -u 10001 -g users tgmgr

# 🔥 2. Даём права (пользователь уже существует!)
RUN chown -R tgmgr:users /app

# 🔥 3. Переключаемся на него
USER tgmgr

# запуск
CMD ["python", "-u", "/app/entry.py"]