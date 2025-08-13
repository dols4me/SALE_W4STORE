import os
import asyncio
import logging
import aiohttp
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command

TOKEN = os.getenv("TELEGRAM_TOKEN")  # токен Telegram бота
VK_TOKEN = os.getenv("VK_TOKEN")  # токен VK API
VK_GROUP_ID = os.getenv("VK_GROUP_ID")  # id группы без минуса

if not all([TOKEN, VK_TOKEN, VK_GROUP_ID]):
    raise SystemExit("Укажите TELEGRAM_TOKEN, VK_TOKEN и VK_GROUP_ID в переменных окружения")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Храним данные пользователей в памяти (вместо базы)
user_data = {}

def main_menu():
    kb = [
        [KeyboardButton(text="О боте")],
        [KeyboardButton(text="Ваша карта")],
        [KeyboardButton(text="Настройки")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_vk_days(vk_id: int):
    url = "https://api.vk.com/method/groups.getMembers"
    params = {
        "group_id": VK_GROUP_ID,
        "fields": "member_since",
        "v": "5.199",
        "access_token": VK_TOKEN
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            if "response" not in data:
                return None
            for member in data["response"]["items"]:
                if member["id"] == vk_id:
                    join_ts = member.get("member_since")
                    if join_ts:
                        join_date = datetime.fromtimestamp(join_ts, tz=timezone.utc)
                        return (datetime.now(timezone.utc) - join_date).days
    return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Добро пожаловать в систему лояльности!", reply_markup=main_menu())

@dp.message(F.text == "О боте")
async def about_bot(message: types.Message):
    await message.answer(
        "Это бот программы лояльности.\n"
        "• «Ваша карта» — покажет, сколько дней вы с нами.\n"
        "• «Настройки» — для ввода VK ID и даты рождения."
    )

@dp.message(F.text == "Ваша карта")
async def your_card(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_data or "vk_id" not in user_data[user_id]:
        await message.answer("Сначала укажите ваш VK ID в настройках.")
        return
    vk_id = user_data[user_id]["vk_id"]
    days = await get_vk_days(vk_id)
    if days is None:
        await message.answer("Не удалось получить данные. Проверьте, что вы в группе ВК.")
    else:
        await message.answer(f"Вы с нами {days} дней!")

@dp.message(F.text == "Настройки")
async def settings(message: types.Message):
    await message.answer("Введите ваш VK ID (число):")
    dp.message.register(get_vk_id_step, F.text)

async def get_vk_id_step(message: types.Message):
    try:
        vk_id = int(message.text.strip())
        user_id = message.from_user.id
        user_data.setdefault(user_id, {})["vk_id"] = vk_id
        await message.answer("VK ID сохранен. Теперь введите дату рождения (ДД.ММ.ГГГГ):")
        dp.message.register(get_birthdate_step, F.text)
    except ValueError:
        await message.answer("Некорректный VK ID. Введите число.")

async def get_birthdate_step(message: types.Message):
    try:
        birthdate = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        user_id = message.from_user.id
        user_data[user_id]["birthdate"] = birthdate
        await message.answer("Дата рождения сохранена!", reply_markup=main_menu())
    except ValueError:
        await message.answer("Неверный формат даты. Введите в формате ДД.ММ.ГГГГ.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
