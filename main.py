#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram bot (aiogram v3) + VK Callback (aiohttp)
— Проверка членства в сообществе VK
— Дни подписки через БЫСТРЫЙ бинарный поиск по groups.getMembers (sort=id_asc), без execute и без полного сканирования
— Ввод VK ID: цифры, id123, короткое имя
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
async def vk_is_member(vk_id: int) -> bool | None:
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

# ====== VK: получить общее количество участников ======
async def vk_members_count(session: aiohttp.ClientSession) -> int | None:
    params = {
        "group_id": VK_GROUP_ID,
        "offset": 0,
        "count": 1,
        "sort": "id_asc",
        "v": "5.199",
        "access_token": VK_TOKEN,
    }
    for attempt in range(5):
        async with session.get("https://api.vk.com/method/groups.getMembers", params=params) as resp:
            data = await resp.json()
        if "error" in data:
            code = data["error"].get("error_code")
            if code == 6:
                await asyncio.sleep(0.35 + 0.15 * attempt)
                continue
            logger.error(f"VK API groups.getMembers (count) error: {data}")
            return None
        break
    return int(data.get("response", {}).get("count", 0))

# ====== VK: бинарный поиск по id_asc для получения member_since конкретного пользователя ======
async def vk_get_member_since_days_binary(vk_id: int) -> int | None:
    """
    Быстро находим нужного участника по его ID в отсортированном списке (sort=id_asc),
    не сканируя всю группу. Требует прав админа/модератора, чтобы поле member_since
    возвращалось (если не скрыто приватностью).
    """
    async with aiohttp.ClientSession() as session:
        total = await vk_members_count(session)
        if not total:
            return None

        lo, hi = 0, total - 1

        while lo <= hi:
            mid = (lo + hi) // 2
            params = {
                "group_id": VK_GROUP_ID,
                "offset": mid,
                "count": 1,
                "sort": "id_asc",          # критично для бинарного поиска
                "fields": "member_since",
                "v": "5.199",
                "access_token": VK_TOKEN,
            }

            # rate-limit-aware
            for attempt in range(5):
                async with session.get("https://api.vk.com/method/groups.getMembers", params=params) as resp:
                    data = await resp.json()
                if "error" in data:
                    code = data["error"].get("error_code")
                    if code == 6:
                        await asyncio.sleep(0.35 + 0.15 * attempt)
                        continue
                    logger.error(f"VK API groups.getMembers (bin) error: {data}")
                    return None
                break

            resp = data.get("response") or {}
            items = resp.get("items") or []
            if not items:
                # странно, но на всякий
                return None

            uid = int(items[0].get("id", 0))
            if uid == vk_id:
                ms = items[0].get("member_since")
                if ms:
                    try:
                        dt = datetime.fromtimestamp(int(ms), tz=timezone.utc)
                        return max(0, (datetime.now(tz=timezone.utc) - dt).days)
                    except Exception:
                        return None
                return None  # член найден, но поля нет (приватность или недоступно)
            elif uid < vk_id:
                lo = mid + 1
            else:
                hi = mid - 1

            await asyncio.sleep(0.05)  # щадим лимиты

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

    is_member = await vk_is_member(vk_id)
    if is_member is None:
        await message.answer("Не удалось проверить подписку. Проверьте токен VK и права доступа.")
        return
    if not is_member:
        await message.answer("Вы ещё не с нами ❌")
        return

    # быстро пытаемся достать member_since через бинарный поиск
    days = await vk_get_member_since_days_binary(vk_id)
    if isinstance(days, int):
        await message.answer(f"Вы с нами! ✅\nПодписаны уже {days} дн.")
    else:
        await message.answer("Вы с нами! ✅")

@dp.message(F.text == "Настройки")
async def settings_start(message: types.Message):
    info = user_data.get(message.from_user.id, {})
    info["awaiting_vk"] = True
    user_data[message.from_user.id] = info
    await message.answer("Введите ваш VK ID (число, id123 или короткое имя):")

@dp.message()
async def process_any_message(message: types.Message):
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
