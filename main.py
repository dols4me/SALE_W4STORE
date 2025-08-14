#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram bot (aiogram v3) + VK Callback (aiohttp)
— Проверка членства в сообществе VK
— Показ дней подписки (если доступно member_since) без execute — через пагинацию groups.getMembers
— Ввод VK ID: поддерживаются числа, префикс id123 и короткое имя (screen name)
"""

import os
import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== Environment variables ======
TOKEN = os.getenv("TELEGRAM_TOKEN")
# приоритет токенов: токен сообщества -> сервисный -> пользовательский
VK_TOKEN = os.getenv("VK_COMMUNITY_TOKEN") or os.getenv("VK_SERVICE_TOKEN") or os.getenv("VK_TOKEN")
VK_GROUP_ID = int(os.getenv("VK_GROUP_ID", "0"))
VK_CONFIRMATION = os.getenv("VK_CONFIRMATION")
VK_SECRET = os.getenv("VK_SECRET", "")

if not all([TOKEN, VK_TOKEN, VK_GROUP_ID]):
    raise SystemExit("Укажите TELEGRAM_TOKEN, VK_(COMMUNITY|SERVICE|)TOKEN и VK_GROUP_ID в переменных окружения.")

if not VK_CONFIRMATION:
    logger.warning("VK_CONFIRMATION не задан — подтверждение Callback не пройдёт.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ====== In-memory store ======
# user_data[telegram_user_id] = {"vk_id": int, "awaiting_vk": bool}
user_data = {}

# ====== Main menu ======
def main_menu():
    kb = [
        [KeyboardButton(text="О боте")],
        [KeyboardButton(text="Ваша карта")],
        [KeyboardButton(text="Настройки")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ====== VK: resolve input -> numeric user_id ======
async def resolve_user_id(identifier: str) -> int | None:
    ident = identifier.strip()
    # 1) чистые цифры
    if ident.isdigit():
        return int(ident)
    # 2) id123
    if ident.lower().startswith("id") and ident[2:].isdigit():
        return int(ident[2:])
    # 3) короткое имя через users.get
    url = "https://api.vk.com/method/users.get"
    params = {
        "user_ids": ident,
        "v": "5.199",
        "access_token": VK_TOKEN
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            if "response" in data and data["response"]:
                try:
                    return int(data["response"][0]["id"])
                except Exception:
                    pass
            logger.error(f"users.get error: {data}")
            return None

# ====== VK: проверка членства ======
async def check_vk_member(vk_id: int):
    url = "https://api.vk.com/method/groups.isMember"
    params = {
        "group_id": VK_GROUP_ID,
        "user_id": vk_id,
        "v": "5.199",
        "access_token": VK_TOKEN
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            if "response" in data:
                return data["response"] == 1
            logger.error(f"VK API groups.isMember error: {data}")
            return None

# ====== VK: дни подписки через пагинацию ======
async def vk_get_member_since_days_paged(vk_id: int, page_size: int = 1000) -> int | None:
    """
    Пошагово обходит участников через groups.getMembers (fields=member_since),
    пока не найдёт пользователя vk_id или не упрётся в лимит VK_MAX_SCAN.
    Возвращает дни подписки или None, если не нашли/нет доступа/скрыто.
    """
    max_scan = int(os.getenv("VK_MAX_SCAN", "200000"))
    page_size = max(1, min(page_size, 1000))
    scanned = 0
    offset = 0

    async with aiohttp.ClientSession() as session:
        while scanned < max_scan:
            params = {
                "group_id": VK_GROUP_ID,
                "offset": offset,
                "count": page_size,
                "fields": "member_since",
                "v": "5.199",
                "access_token": VK_TOKEN,
            }
            # простые ретраи на rate limit
            for attempt in range(5):
                async with session.get("https://api.vk.com/method/groups.getMembers", params=params) as resp:
                    data = await resp.json()
                if "error" in data:
                    code = data["error"].get("error_code")
                    if code == 6:  # Too many requests per second
                        await asyncio.sleep(0.35 + 0.15 * attempt)
                        continue
                    logger.error(f"VK API groups.getMembers error: {data}")
                    return None
                break

            response = data.get("response") or {}
            items = response.get("items") or []
            if not items:
                return None  # конец списка

            for u in items:
                try:
                    if int(u.get("id", 0)) == int(vk_id):
                        ms = u.get("member_since")
                        if ms:
                            try:
                                dt = datetime.fromtimestamp(int(ms), tz=timezone.utc)
                                return max(0, (datetime.now(tz=timezone.utc) - dt).days)
                            except Exception:
                                return None
                        return None  # нет поля -> скрыто/недоступно
                except Exception:
                    continue

            got = len(items)
            scanned += got
            offset += got
            await asyncio.sleep(0.2)

    return None

# ====== Telegram handlers ======
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Добро пожаловать в систему лояльности!", reply_markup=main_menu())

@dp.message(F.text == "О боте")
async def about_bot(message: types.Message):
    await message.answer(
        "Это бот программы лояльности.\n"
        "• «Ваша карта» — проверяет, подписаны ли вы на паблик VK и, если возможно, показывает, сколько дней вы с нами.\n"
        "• «Настройки» — введите ваш VK ID (число, id123 или короткое имя)."
    )

@dp.message(F.text == "Ваша карта")
async def your_card(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_data or "vk_id" not in user_data[user_id]:
        await message.answer("Сначала укажите ваш VK ID в «Настройки».")
        return
    vk_id = user_data[user_id]["vk_id"]

    is_member = await check_vk_member(vk_id)
    if is_member is None:
        await message.answer("Не удалось проверить подписку. Проверьте токен VK и права доступа.")
        return
    if not is_member:
        await message.answer("Вы ещё не с нами ❌")
        return

    days = await vk_get_member_since_days_paged(vk_id)
    if isinstance(days, int):
        await message.answer(f"Вы с нами! ✅\nПодписаны уже {days} дн.")
    else:
        await message.answer("Вы с нами! ✅")

@dp.message(F.text == "Настройки")
async def settings_start(message: types.Message):
    # ставим флаг ожидания VK ID
    info = user_data.get(message.from_user.id, {})
    info["awaiting_vk"] = True
    user_data[message.from_user.id] = info
    await message.answer("Введите ваш VK ID (число, id123 или короткое имя):")

@dp.message()
async def process_any_message(message: types.Message):
    # если ждём VK ID — пытаемся распознать
    info = user_data.get(message.from_user.id, {})
    if info.get("awaiting_vk"):
        raw = (message.text or "").strip()
        vk_id = await resolve_user_id(raw)
        if not vk_id:
            await message.answer("Не нашёл такой VK ID/короткое имя. Примеры: 183499093, id183499093, durov.")
            return
        info["vk_id"] = vk_id
        info["awaiting_vk"] = False
        user_data[message.from_user.id] = info
        await message.answer("VK ID сохранён!", reply_markup=main_menu())
        return

    # прочие сообщения — подсказываем меню
    await message.answer("Выберите действие из меню ниже.", reply_markup=main_menu())

# ====== VK Callback HTTP server ======
async def handle_vk_callback(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.Response(text="ok")

    evt_type = payload.get("type", "")
    secret = payload.get("secret", "")

    if VK_SECRET and secret != VK_SECRET:
        logger.warning("VK secret mismatch")
        return web.Response(text="ok")

    if evt_type == "confirmation":
        if not VK_CONFIRMATION:
            logger.error("VK_CONFIRMATION is missing; cannot confirm VK server.")
            return web.Response(text="")
        return web.Response(text=VK_CONFIRMATION)

    return web.Response(text="ok")

async def healthcheck(request: web.Request) -> web.Response:
    return web.Response(text="OK")

def build_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", healthcheck)
    app.router.add_post("/vk-callback", handle_vk_callback)
    return app

# ====== Entrypoint ======
async def main():
    app = build_web_app()

    # HTTP server
    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info(f"VK Callback server listening on 0.0.0.0:{port}")

    # Telegram polling (стираем вебхук на всякий случай)
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
