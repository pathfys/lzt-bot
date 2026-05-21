import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

BOT_TOKEN = "YOUR_BOT_TOKEN"
WEBAPP_URL = "YOUR_MINI_APP_URL"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🟢 Lolz",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )
        ]
    ])

    await message.answer(
        text=(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "<blockquote>🛡️ <b>Lolz Market</b> — надёжный маркетплейс для безопасных сделок!\n"
            "✨ Автоматизировано, быстро и без лишних хлопот!</blockquote>\n\n"
            "💎 Комиссия за услугу: <b>всего 1%</b>\n\n"
            "<blockquote>⏰ Поддержка 24/7: <b>Lolz Support</b></blockquote>\n\n"
            "<blockquote>❤️ Теперь ваши сделки <b>под защитой!</b> 🛡️✅</blockquote>"
        ),
        reply_markup=keyboard,
        parse_mode="HTML"
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
