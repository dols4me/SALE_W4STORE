#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram loyalty bot + VK Callback API confirmation endpoint for Railway.
- Telegram bot built with aiogram v3
- VK Callback server implemented with aiohttp (confirmation + events)
- Designed to run BOTH: HTTP server (for VK) and Telegram polling in the same process
"""

import os
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== Environment variables ======
TOKEN = os.getenv("TELEGRAM_TOKEN")                    # Telegram bot token
VK_TOKEN = os.getenv("VK_SERVICE_TOKEN") or os.getenv("VK_TOKEN")                      # VK user token with groups permission
VK_GROUP_ID = int(os.getenv("VK_GROUP_ID", "0"))       # VK public group ID (integer)
VK_CONFIRMATION = os.getenv("VK_CONFIRMATION")         # <-- paste the confirmation string from VK Callback settings (e.g. 576c75ac)
VK_SECRET = os.getenv("VK_SECRET", "")                 # optional: set the same 'Secret key' as in VK settings

if not all([TOKEN, VK_TOKEN, VK_GROUP_ID]):
    raise SystemExit("Укажите TELEGRAM_TOKEN, VK_TOKEN и VK_GROUP_ID как переменные окружения.")

if not VK_CONFIRMATION:
    logger.warning("VK_CONFIRMATION не задан. Для подтверждения сервера VK вернет ошибку 'Invalid response code'. "
                   "Установите VK_CONFIRMATION из раздела Callback API вашего паблика.")

bot = Bot(token=TOKEN)
dp = Dispatcher()
user_data = {}

# ====== FSM for settings ======
class Settings(StatesGroup):
    vk_id = State()
    birthdate = State()

# ====== Main menu ======
def main_menu():
    kb = [
        [KeyboardButton(text="О боте")],
        [KeyboardButton(text="Ваша карта")],
        [KeyboardButton(text="Настройки")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# ====== VK groups.isMember check ======
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
            logger.error(f"Ошибка VK API: {data}")
            return None

# ====== Telegram bot handlers ======
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Добро пожаловать в систему лояльности!", reply_markup=main_menu())

@dp.message(F.text == "О боте")
async def about_bot(message: types.Message):
    await message.answer(
        "Это бот программы лояльности.\n"
        "• «Ваша карта» — проверяет, подписаны ли вы на паблик VK.\n"
        "• «Настройки» — для ввода VK ID и даты рождения."
    )

@dp.message(F.text == "Ваша карта")
async def your_card(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_data or "vk_id" not in user_data[user_id]:
        await message.answer("Сначала укажите ваш VK ID в настройках.")
        return
    vk_id = user_data[user_id]["vk_id"]
    is_member = await check_vk_member(vk_id)
    if is_member is None:
        await message.answer("Не удалось проверить подписку. Проверьте VK ID.")
    elif is_member:
        await message.answer("Вы с нами! ✅")
    else:
        await message.answer("Вы ещё не с нами ❌")

@dp.message(F.text == "Настройки")
async def settings_start(message: types.Message, state: FSMContext):
    await message.answer("Введите ваш VK ID (число):")
    await state.set_state(Settings.vk_id)

@dp.message(Settings.vk_id)
async def process_vk_id(message: types.Message, state: FSMContext):
    try:
        vk_id = int(message.text.strip())
        await state.update_data(vk_id=vk_id)
        await message.answer("VK ID сохранен. Теперь введите дату рождения (ДД.MM.ГГГГ):")
        await state.set_state(Settings.birthdate)
    except ValueError:
        await message.answer("Некорректный VK ID. Введите число.")

@dp.message(Settings.birthdate)
async def process_birthdate(message: types.Message, state: FSMContext):
    try:
        birthdate = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        await state.update_data(birthdate=birthdate.isoformat())
        data = await state.get_data()
        user_data[message.from_user.id] = data
        await message.answer("Дата рождения сохранена!", reply_markup=main_menu())
        await state.clear()
    except ValueError:
        await message.answer("Неверный формат даты. Введите в формате ДД.MM.ГГГГ.")

# ====== VK Callback HTTP server ======
# VK will send POST requests with JSON { type, object, group_id, secret, ... }

async def handle_vk_callback(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        # VK expects plain "ok" even if content parsing fails (but confirmation must be exact string)
        return web.Response(text="ok")
    
    evt_type = payload.get("type", "")
    group_id = payload.get("group_id")
    secret = payload.get("secret", "")

    # Optional secret check
    if VK_SECRET and secret != VK_SECRET:
        logger.warning("VK secret mismatch")
        return web.Response(text="ok")

    if evt_type == "confirmation":
        # IMPORTANT: must return the EXACT confirmation string (e.g., 576c75ac) as plain text with HTTP 200
        # No quotes, no JSON, no spaces, no newline.
        if not VK_CONFIRMATION:
            logger.error("VK_CONFIRMATION is missing; cannot confirm VK server.")
            return web.Response(text="")
        return web.Response(text=VK_CONFIRMATION)

    # Here you can handle other event types if needed (message_new, group_join, etc.)
    # For now, just acknowledge
    return web.Response(text="ok")

async def healthcheck(request: web.Request) -> web.Response:
    return web.Response(text="OK")

def build_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", healthcheck)
    app.router.add_post("/vk-callback", handle_vk_callback)
    return app

# ====== Entrypoint: run Telegram polling and Web server together ======
async def main():
    app = build_web_app()

    # Start HTTP server
    port = int(os.getenv("PORT", "8080"))  # Railway provides PORT
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info(f"VK Callback server listening on 0.0.0.0:{port}")

    # Start Telegram bot polling concurrently
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
