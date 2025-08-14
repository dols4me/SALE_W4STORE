#!/usr/bin/env python3
# -*- coding: utf-8 -*-
<<<<<<< HEAD
"""
Telegram bot (aiogram v3) + VK Callback (aiohttp)
— Проверка членства в сообществе VK
— Показывает, сколько дней подписан (через member_since), используя VK Script (execute) для быстрого поиска
"""

import os
import asyncio
import logging
from datetime import datetime, timezone

=======
import os, asyncio, logging
from datetime import datetime, timezone
>>>>>>> b559938 (Paged member_since (no execute), stable VK days-in-group)
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

<<<<<<< HEAD
# ====== ENV ======
TOKEN = os.getenv("TELEGRAM_TOKEN")

# приоритет токенов VK: токен сообщества -> сервисный -> пользовательский
VK_TOKEN_COMMUNITY = os.getenv("VK_COMMUNITY_TOKEN")
VK_TOKEN_SERVICE   = os.getenv("VK_SERVICE_TOKEN")
VK_TOKEN_USER      = os.getenv("VK_TOKEN")
VK_TOKEN = VK_TOKEN_COMMUNITY or VK_TOKEN_SERVICE or VK_TOKEN_USER

VK_GROUP_ID = int(os.getenv("VK_GROUP_ID", "0"))         # положительный ID сообщества
VK_CONFIRMATION = os.getenv("VK_CONFIRMATION")           # строка подтверждения callback
VK_SECRET = os.getenv("VK_SECRET", "")                   # секрет callback (необязателен, но желательно)

# сколько максимум пользователей просматривать в поиске member_since (шагами по 25k через execute)
VK_MAX_SCAN = int(os.getenv("VK_MAX_SCAN", "200000"))

if not all([TOKEN, VK_TOKEN, VK_GROUP_ID]):
    raise SystemExit("Укажите TELEGRAM_TOKEN, VK_(COMMUNITY|SERVICE|)TOKEN и VK_GROUP_ID в переменных окружения.")

if not VK_CONFIRMATION:
    logger.warning("VK_CONFIRMATION не задан — подтверждение Callback не пройдёт.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# только vk_id у пользователя
user_data = {}

# ====== FSM ======
class Settings(StatesGroup):
    vk_id = State()

# ====== Меню ======
=======
TOKEN = os.getenv("TELEGRAM_TOKEN")
VK_TOKEN = os.getenv("VK_COMMUNITY_TOKEN") or os.getenv("VK_SERVICE_TOKEN") or os.getenv("VK_TOKEN")
VK_GROUP_ID = int(os.getenv("VK_GROUP_ID", "0"))
VK_CONFIRMATION = os.getenv("VK_CONFIRMATION")
VK_SECRET = os.getenv("VK_SECRET", "")

if not all([TOKEN, VK_TOKEN, VK_GROUP_ID]):
    raise SystemExit("Укажите TELEGRAM_TOKEN, VK_(COMMUNITY|SERVICE|)TOKEN и VK_GROUP_ID как переменные окружения.")
if not VK_CONFIRMATION:
    logger.warning("VK_CONFIRMATION не задан — подтверждение Callback не пройдёт.")

bot = Bot(token=TOKEN); dp = Dispatcher(); user_data = {}

>>>>>>> b559938 (Paged member_since (no execute), stable VK days-in-group)
def main_menu():
    kb = [[KeyboardButton(text="О боте")],[KeyboardButton(text="Ваша карта")],[KeyboardButton(text="Настройки")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

<<<<<<< HEAD
# ====== VK: резолв коротких имён ======
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
=======
async def check_vk_member(vk_id: int):
>>>>>>> b559938 (Paged member_since (no execute), stable VK days-in-group)
    url = "https://api.vk.com/method/groups.isMember"
    params = {"group_id": VK_GROUP_ID, "user_id": vk_id, "v": "5.199", "access_token": VK_TOKEN}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()
<<<<<<< HEAD
            if "response" in data:
                return data["response"] == 1
            logger.error(f"VK API groups.isMember error: {data}")
            return None

# ====== VK: быстрый поиск member_since через execute (25k за вызов) ======
async def vk_get_member_since_days_execute(vk_id: int) -> int | None:
    """
    Ищем member_since через VK Script (execute) блоками.
    Адаптивно уменьшаем размер блока при error_code=13 (Too many operations).
    Возвращает количество дней или None.
    """
    from datetime import datetime, timezone

    # настройки сканирования
    hard_limit = int(os.getenv("VK_MAX_SCAN", "200000"))   # максимум просмотренных участников
    # возможные размеры блока за один execute (кол-во элементов = BATCH_CALLS * 1000)
    BATCH_CALLS_CHOICES = [10, 5, 2, 1]  # 10k → 5k → 2k → 1k
    offset = 0

    async with aiohttp.ClientSession() as session:
        while offset < hard_limit:
            # пробуем от большого блока к меньшему
            found_in_this_window = False
            for calls in BATCH_CALLS_CHOICES:
                # VK Script без break/continue
                script = f"""
                var gid = {VK_GROUP_ID};
                var uid = {vk_id};
                var base = {offset};
                var count = 1000;
                var loops = {calls}; // сколько страниц по 1000 за раз
                var i = 0;
                var found = 0;
                var ms = 0;
                var stop = 0;

                while (i < loops && stop == 0 && found == 0) {{
                    var resp = API.groups.getMembers({{
                        "group_id": gid,
                        "offset": base + i * count,
                        "count": count,
                        "fields": "member_since"
                    }});
                    var items = resp.items;
                    var len = items.length;
                    var j = 0;
                    while (j < len && found == 0) {{
                        if (items[j].id == uid) {{
                            found = 1;
                            ms = items[j].member_since;
                        }}
                        j = j + 1;
                    }}
                    if (len < count) {{ stop = 1; }}
                    i = i + 1;
                }}

                return {{"found": found, "member_since": ms, "stop": stop}};
                """

                params = {
                    "code": script,
                    "v": "5.199",
                    "access_token": VK_TOKEN
                }

                async with session.post("https://api.vk.com/method/execute", data=params) as resp:
                    data = await resp.json()

                # обработка ошибок
                if "error" in data:
                    err = data["error"]
                    code = err.get("error_code")
                    # 13 — слишком много операций: пробуем меньший блок
                    if code == 13:
                        logger.warning(f"VK execute: Too many operations on calls={calls}, shrinking batch…")
                        await asyncio.sleep(0.2)  # крошечный бэкофф
                        continue
                    else:
                        logger.error(f"VK API execute error: {data}")
                        return None

                res = data.get("response") or {}
                if res.get("found") == 1:
                    ms = res.get("member_since")
                    if ms:
                        try:
                            dt = datetime.fromtimestamp(int(ms), tz=timezone.utc)
                            return max(0, (datetime.now(tz=timezone.utc) - dt).days)
                        except Exception:
                            return None
                    return None

                # если дошли до конца списка — дальше не ищем
                if res.get("stop") == 1:
                    return None

                # если не нашли и не «стоп», но ошибок нет — значит этот блок успешно просмотрен
                found_in_this_window = True
                # сдвигаем offset на calls*1000 и переходим к следующему окну
                offset += calls * 1000
                break  # выходим из цикла по BATCH_CALLS_CHOICES (успешный просмотр)

            # если ни один размер блока не отработал (все падали на 13) — попробуем ручной микрошаг
            if not found_in_this_window:
                # последний шанс: 1 страница в отдельном execute
                script_single = f"""
                var resp = API.groups.getMembers({{
                    "group_id": {VK_GROUP_ID},
                    "offset": {offset},
                    "count": 1000,
                    "fields": "member_since"
                }});
                var items = resp.items;
                var len = items.length;
                var j = 0;
                var found = 0;
                var ms = 0;
                while (j < len && found == 0) {{
                    if (items[j].id == {vk_id}) {{
                        found = 1;
                        ms = items[j].member_since;
                    }}
                    j = j + 1;
                }}
                var stop = 0;
                if (len < 1000) {{ stop = 1; }}
                return {{"found": found, "member_since": ms, "stop": stop}};
                """
                params_single = {
                    "code": script_single,
                    "v": "5.199",
                    "access_token": VK_TOKEN
                }
                async with session.post("https://api.vk.com/method/execute", data=params_single) as resp:
                    data_single = await resp.json()

                if "error" in data_single:
                    logger.error(f"VK API execute error (single): {data_single}")
                    return None

                res = data_single.get("response") or {}
                if res.get("found") == 1:
                    ms = res.get("member_since")
                    if ms:
                        try:
                            dt = datetime.fromtimestamp(int(ms), tz=timezone.utc)
                            return max(0, (datetime.now(tz=timezone.utc) - dt).days)
                        except Exception:
                            return None
                    return None

                if res.get("stop") == 1:
                    return None

                # двигаемся дальше по 1000
                offset += 1000
                await asyncio.sleep(0.15)  # слегка разгружаем
    return None

# ====== Telegram handlers ======
=======
            if "response" in data: return data["response"] == 1
            logger.error(f"VK API groups.isMember error: {data}"); return None

async def vk_get_member_since_days_paged(vk_id: int, page_size: int = 1000) -> int | None:
    max_scan = int(os.getenv("VK_MAX_SCAN", "200000")); page_size = max(1, min(page_size, 1000))
    scanned = 0; offset = 0
    async with aiohttp.ClientSession() as session:
        while scanned < max_scan:
            params = {"group_id": VK_GROUP_ID, "offset": offset, "count": page_size,
                      "fields": "member_since", "v": "5.199", "access_token": VK_TOKEN}
            for attempt in range(5):
                async with session.get("https://api.vk.com/method/groups.getMembers", params=params) as resp:
                    data = await resp.json()
                if "error" in data:
                    code = data["error"].get("error_code")
                    if code == 6:
                        await asyncio.sleep(0.35 + 0.15 * attempt); continue
                    logger.error(f"VK API groups.getMembers error: {data}"); return None
                break
            response = data.get("response") or {}; items = response.get("items") or []
            if not items: return None
            for u in items:
                try:
                    if int(u.get("id", 0)) == int(vk_id):
                        ms = u.get("member_since")
                        if ms:
                            try:
                                dt = datetime.fromtimestamp(int(ms), tz=timezone.utc)
                                return max(0, (datetime.now(tz=timezone.utc) - dt).days)
                            except Exception: return None
                        return None
                except Exception: continue
            got = len(items); scanned += got; offset += got; await asyncio.sleep(0.2)
    return None

>>>>>>> b559938 (Paged member_since (no execute), stable VK days-in-group)
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Добро пожаловать в систему лояльности!", reply_markup=main_menu())

@dp.message(F.text == "О боте"))
async def about_bot(message: types.Message):
<<<<<<< HEAD
    await message.answer(
        "Это бот программы лояльности.\n"
        "• «Ваша карта» — проверяет, подписаны ли вы на паблик VK и, если возможно, показывает, сколько дней вы с нами.\n"
        "• «Настройки» — введите ваш VK ID (цифры, id123 или короткое имя)."
    )
=======
    await message.answer("Это бот программы лояльности.\n• «Ваша карта» — проверяет подписку и дни.\n• «Настройки» — введите VK ID.")
>>>>>>> b559938 (Paged member_since (no execute), stable VK days-in-group)

@dp.message(F.text == "Ваша карта"))
async def your_card(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_data or "vk_id" not in user_data[user_id]:
<<<<<<< HEAD
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

    days = await vk_get_member_since_days_execute(vk_id)
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

    if VK_SECRET and secret != VK_SECRET:
        logger.warning("VK secret mismatch")
        return web.Response(text="ok")

    if evt_type == "confirmation":
        if not VK_CONFIRMATION:
            logger.error("VK_CONFIRMATION is missing; cannot confirm VK server.")
            return web.Response(text="")
        return web.Response(text=VK_CONFIRMATION)

=======
        await message.answer("Сначала укажите ваш VK ID в «Настройки»."); return
    vk_id = user_data[user_id]["vk_id"]
    is_member = await check_vk_member(vk_id)
    if is_member is None: await message.answer("Не удалось проверить подписку. Проверьте токен VK и права."); return
    if not is_member: await message.answer("Вы ещё не с нами ❌"); return
    days = await vk_get_member_since_days_paged(vk_id)
    if isinstance(days, int): await message.answer(f"Вы с нами! ✅\nПодписаны уже {days} дн.")
    else: await message.answer("Вы с нами! ✅")

@dp.message(F.text == "Настройки"))
async def settings_start(message: types.Message):
    await message.answer("Введите ваш VK ID (число):")

@dp.message()
async def process_vk_id(message: types.Message):
    try:
        vk_id = int(message.text.strip()); user_data[message.from_user.id] = {"vk_id": vk_id}
        await message.answer("VK ID сохранён!", reply_markup=main_menu())
    except ValueError:
        await message.answer("Некорректный VK ID. Введите число.")

async def handle_vk_callback(request: web.Request) -> web.Response:
    try: payload = await request.json()
    except Exception: return web.Response(text="ok")
    evt_type = payload.get("type", ""); secret = payload.get("secret", "")
    if VK_SECRET and secret != VK_SECRET: logger.warning("VK secret mismatch"); return web.Response(text="ok")
    if evt_type == "confirmation":
        if not VK_CONFIRMATION: logger.error("VK_CONFIRMATION is missing"); return web.Response(text="")
        return web.Response(text=VK_CONFIRMATION)
>>>>>>> b559938 (Paged member_since (no execute), stable VK days-in-group)
    return web.Response(text="ok")

async def healthcheck(request: web.Request) -> web.Response: return web.Response(text="OK")

def build_web_app() -> web.Application:
    app = web.Application(); app.router.add_get("/", healthcheck); app.router.add_post("/vk-callback", handle_vk_callback); return app

<<<<<<< HEAD
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

    # Telegram: удаляем вебхук, чтобы polling не конфликтовал
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
=======
async def main():
    app = build_web_app(); port = int(os.getenv("PORT", "8080"))
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port); await site.start()
    logger.info(f"VK Callback server listening on 0.0.0.0:{port}")
    await bot.delete_webhook(drop_pending_updates=True)
    try: await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally: await runner.cleanup()
>>>>>>> b559938 (Paged member_since (no execute), stable VK days-in-group)

if __name__ == "__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): logger.info("Shutting down...")
