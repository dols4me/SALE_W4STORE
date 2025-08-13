#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram bot (aiogram v3) + VK Callback (aiohttp)
— Проверка: состоит ли пользователь в сообществе VK
— Если возможно, показывает, сколько дней пользователь подписан (по member_since)
— Без даты рождения, только VK ID
"""

import os
import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== ENV ======
TOKEN = os.getenv("TELEGRAM_TOKEN")  # Telegram bot token

# выбираем VK-токен по приоритету: токен сообщества -> сервисный -> пользовательский
VK_TOKEN_COMMUNITY = os.getenv("VK_COMMUNITY_TOKEN")
VK_TOKEN_SERVICE   = os.getenv("VK_SERVICE_TOKEN")
VK_TOKEN_USER      = os.getenv("VK_TOKEN")
VK_TOKEN = VK_TOKEN_COMMUNITY or VK_TOKEN_SERVICE or VK_TOKEN_USER

VK_GROUP_ID = int(os.getenv("VK_GROUP_ID", "0"))                # ID сообщества (положительное число)
VK_CONFIRMATION = os.getenv("VK_CONFIRMATION")                  # строка подтверждения для Callback
VK_SECRET = os.getenv("VK_SECRET", "")                          # секрет для Callback (желательно задать)

if not all([TOKEN, VK_TOKEN, VK_GROUP_ID]):
    raise SystemExit("Укажите TELEGRAM_TOKEN, VK_(COMMUNITY|SERVICE|)TOKEN и VK_GROUP_ID в переменных окружения.")

if not VK_CONFIRMATION:
    logger.warning("VK_CONFIRMATION не задан — подтверждение Callback не пройдёт.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Храним только vk_id пользователя
user_data = {}

# ====== FSM ======
class Settings(StatesGroup):
    vk_id = State()

# ====== Меню ======
def main_menu():
    kb = [
        [KeyboardButton(text="О боте")],
        [KeyboardButton(text="Ваша карта")],
        [KeyboardButton(text="Настройки")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ====== VK: резолв коротких имён в числовой user_id ======
async def resolve_user_id(identifier: str) -> int | None:
    ident = identifier.strip()
    if ident.isdigit():
        return int(ident)
    if ident.lower().startswith("id") and ident[2:].isdigit():
        return int(ident[2:])

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
    """True/False — членство; None — ошибка VK API"""
    url = "https://api.vk.com/method/groups.isMember"
    params = {
        "group_id": VK_GROUP_ID,   # положительный ID, без минуса/club
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

# ====== VK: попытка получить member_since (с пагинацией) ======
async def vk_get_member_since_days(vk_id: int, max_scan: int = 5000, page_size: int = 1000) -> int | None:
    """
    Пытается найти пользователя в списке участников, запрашивая страницы
    groups.getMembers с fields=member_since. Возвращает количество дней
    с момента вступления или None, если не нашли/нет доступа.
    max_scan — максимум пользователей, которых просмотрим (ради производительности).
    """
    url = "https://api.vk.com/method/groups.getMembers"
    scanned = 0
    offset = 0

    # защита от невалидных параметров
    page_size = max(1, min(page_size, 1000))
    max_scan = max(page_size, max_scan)

    async with aiohttp.ClientSession() as session:
        while scanned < max_scan:
            params = {
                "group_id": VK_GROUP_ID,
                "offset": offset,
                "count": page_size,
                "fields": "member_since",
                "v": "5.199",
                "access_token": VK_TOKEN
            }
            async with session.get(url, params=params) as resp:
                data = await resp.json()
            if "error" in data:
                logger.error(f"VK API groups.getMembers error: {data}")
                return None
            resp_obj = data.get("response") or {}
            items = resp_obj.get("items") or []
            if not items:
                # конец списка
                break

            for u in items:
                try:
                    if int(u.get("id")) == int(vk_id):
                        member_since = u.get("member_since")
                        if member_since:
                            try:
                                dt = datetime.fromtimestamp(int(member_since), tz=timezone.utc)
                                days = (datetime.now(tz=timezone.utc) - dt).days
                                return max(0, days)
                            except Exception:
                                return None
                        else:
                            return None
                except Exception:
                    continue

            scanned += len(items)
            offset += len(items)

            if scanned >= max_scan:
                break

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
        "• «Настройки» — для ввода вашего VK ID (цифры, id123 или короткое имя)."
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
        await message.answer("Не удалось проверить подписку. Проверьте VK токен/доступы в Railway.")
        return

    if not is_member:
        await message.answer("Вы ещё не с нами ❌")
        return

    # состоит — пытаемся узнать 'сколько дней'
    days = await vk_get_member_since_days(vk_id)
    if isinstance(days, int):
        await message.answer(f"Вы с нами! ✅\nПодписаны уже {days} дн.")
    else:
        await message.answer("Вы с нами! ✅")

@dp.message(F.text == "Настройки")
async def settings_start(message: types.Message, state: FSMContext):
    await message.answer("Введите ваш VK ID (цифры) или короткое имя (например, durov или id123):")
    await state.set_state(Settings.vk_id)

@dp.message(Settings.vk_id)
async def process_vk_id(message: types.Message, state: FSMContext):
    raw = message.text.strip()
    vk_id = await resolve_user_id(raw)
    if not vk_id:
        await message.answer("Не нашёл такой VK ID/короткое имя. Пример: 183499093, id183499093, durov.")
        return
    await state.update_data(vk_id=vk_id)
    data = await state.get_data()
    user_data[message.from_user.id] = data
    await message.answer("VK ID сохранён!", reply_markup=main_menu())
    await state.clear()

# ====== VK Callback HTTP server ======
async def handle_vk_callback(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.Response(text="ok")

    evt_type = payload.get("type", "")
    secret = payload.get("secret", "")

    # Проверка секрета (если задан)
    if VK_SECRET and secret != VK_SECRET:
        logger.warning("VK secret mismatch")
        return web.Response(text="ok")

    if evt_type == "confirmation":
        if not VK_CONFIRMATION:
            logger.error("VK_CONFIRMATION is missing; cannot confirm VK server.")
            return web.Response(text="")
        # вернуть ровно строку подтверждения
        return web.Response(text=VK_CONFIRMATION)

    # прочие события подтверждаем
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

    # HTTP server for VK
    port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info(f"VK Callback server listening on 0.0.0.0:{port}")

    # Telegram: стираем вебхук, чтобы polling не конфликтовал
    await bot.delete_webhook(drop_pending_updates=True)

    # Telegram polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
