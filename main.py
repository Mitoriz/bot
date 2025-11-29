import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

# ====================== НАСТРОЙКИ ======================
BOT_TOKEN = "8091062881:AAE7-cTUQch5f-QoKoCphY1VhH4lk0OpWh0"
CHANNEL_ID = -1002233445566
ADMINS = {1343976371}

DB_FILE = "moderation_bot.db"
# =====================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# ====================== КЛАВИАТУРЫ С ЭМОДЗИ ======================
def main_menu(is_admin: bool = False):
    b = ReplyKeyboardBuilder()
    b.row(types.KeyboardButton(text="Профиль"))
    if is_admin:
        b.row(types.KeyboardButton(text="Сохранённые"), types.KeyboardButton(text="Забаненные"))
    return b.as_markup(resize_keyboard=True)

def moderation_kb(user_id: int):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Опубликовать", callback_data=f"approve_{user_id}"),
        InlineKeyboardButton(text="Отклонить", callback_data=f"reject_{user_id}")
    )
    b.row(
        InlineKeyboardButton(text="Сохранить", callback_data=f"save_{user_id}"),
        InlineKeyboardButton(text="Забанить", callback_data=f"ban_{user_id}")
    )
    return b.as_markup()

def saved_kb(idx: int, total: int):
    b = InlineKeyboardBuilder()
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="Назад", callback_data=f"saved_prev_{idx}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="Вперёд", callback_data=f"saved_next_{idx}"))
    if nav:
        b.row(*nav)

    b.row(
        InlineKeyboardButton(text=f"{idx + 1}/{total}", callback_data="saved_nop"),
        InlineKeyboardButton(text="Удалить", callback_data=f"saved_del_{idx}")
    )
    b.row(InlineKeyboardButton(text="Закрыть", callback_data="saved_close"))
    return b.as_markup()

# ====================== БАЗА ======================
async def init_db() -> None:
    if os.path.exists(DB_FILE):
        try:
            async with aiosqlite.connect(DB_FILE) as db:
                await db.execute("SELECT 1 FROM saved_posts LIMIT 1")
        except:
            os.remove(DB_FILE)

    async with aiosqlite.connect(DB_FILE) as db:
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS saved_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                from_chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                UNIQUE(admin_id, from_chat_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS user_stats (user_id INTEGER PRIMARY KEY, posts_sent INTEGER DEFAULT 0);
        ''')
        await db.commit()

async def is_banned(uid: int) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT 1 FROM banned_users WHERE user_id=?", (uid,)) as c:
            return await c.fetchone() is not None

async def ban_user(uid: int) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO banned_users VALUES (?)", (uid,))
        await db.commit()

async def save_post(admin_id: int, chat_id: int, msg_id: int) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO saved_posts (admin_id,from_chat_id,message_id) VALUES (?,?,?)",
                         (admin_id, chat_id, msg_id))
        await db.commit()

async def delete_saved(admin_id: int, offset: int) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""DELETE FROM saved_posts WHERE admin_id=? AND id = (
                            SELECT id FROM saved_posts WHERE admin_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)""",
                         (admin_id, admin_id, offset))
        await db.commit()

async def get_saved(admin_id: int, offset: int = 0):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT from_chat_id, message_id FROM saved_posts WHERE admin_id=? ORDER BY id DESC LIMIT 1 OFFSET ?",
                              (admin_id, offset)) as c:
            return await c.fetchone()

async def get_saved_count(admin_id: int) -> int:
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT COUNT(*) FROM saved_posts WHERE admin_id=?", (admin_id,)) as c:
            return (await c.fetchone())[0]

async def increment_posts(uid: int) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO user_stats(user_id,posts_sent)VALUES(?,1) ON CONFLICT DO UPDATE SET posts_sent=posts_sent+1", (uid,))
        await db.commit()

# ====================== КОМАНДЫ ======================
@dp.message(CommandStart())
async def start(m: types.Message):
    await m.answer(
        f"Привет, <b>{m.from_user.full_name}</b>!\nОтправляй контент — он уйдёт на модерацию.",
        reply_markup=main_menu(m.from_user.id in ADMINS)
    )

@dp.message(lambda m: m.text == "Профиль")
async def profile(m: types.Message):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT posts_sent FROM user_stats WHERE user_id=?", (m.from_user.id,)) as c:
            r = await c.fetchone()
    posts = r[0] if r else 0
    await m.answer(f"<b>Профиль</b>\n\nИмя: {m.from_user.full_name}\nID: <code>{m.from_user.id}</code>\nПостов: <b>{posts}</b>",
                   reply_markup=main_menu(m.from_user.id in ADMINS))

@dp.message(lambda m: m.text == "Сохранённые")
async def show_saved(m: types.Message):
    if m.from_user.id not in ADMINS:
        return await m.answer("Ты не админ")

    total = await get_saved_count(m.from_user.id)
    if total == 0:
        return await m.answer("Нет сохранённых постов")

    row = await get_saved(m.from_user.id, 0)
    fwd = await bot.forward_message(m.chat.id, row[0], row[1])
    await bot.send_message(m.chat.id, "Управление:", reply_to_message_id=fwd.message_id, reply_markup=saved_kb(0, total))

@dp.message(lambda m: m.text == "Забаненные")
async def show_banned(m: types.Message):
    if m.from_user.id not in ADMINS: return
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT user_id FROM banned_users") as c:
            rows = await c.fetchall()
    if not rows:
        return await m.answer("Забаненных нет")
    text = "<b>Забаненные:</b>\n\n"
    kb = InlineKeyboardBuilder()
    for uid in [r[0] for r in rows]:
        try:
            name = (await bot.get_chat(uid)).full_name or "Без имени"
        except:
            name = "Удалён"
        text += f"• <code>{uid}</code> — {name}\n"
        kb.row(InlineKeyboardButton(text=f"Разбанить {name[:15]}...", callback_data=f"unban_{uid}"))
    kb.row(InlineKeyboardButton(text="Назад", callback_data="back_menu"))
    await m.answer(text, reply_markup=kb.as_markup())

# ====================== КОНТЕНТ ======================
@dp.message()
async def content(m: types.Message):
    if m.text and m.text in ["Профиль", "Сохранённые", "Забаненные"]: return
    if await is_banned(m.from_user.id):
        return await m.reply("Вы забанены")
    await increment_posts(m.from_user.id)
    for a in ADMINS:
        try:
            f = await m.forward(a)
            await f.reply(f"Пост от <a href='tg://user?id={m.from_user.id}'>{m.from_user.full_name}</a>",
                          reply_markup=moderation_kb(m.from_user.id))
        except: pass
    await m.answer("Отправлено на модерацию", reply_markup=main_menu(m.from_user.id in ADMINS))

# ====================== МОДЕРАЦИЯ ======================
@dp.callback_query(lambda c: c.data and c.data.startswith(("approve_", "reject_", "save_", "ban_")))
async def mod(c: types.CallbackQuery):
    act, uid = c.data.split("_", 1)
    uid = int(uid)
    msg = c.message.reply_to_message
    if not msg: return await c.answer("Ошибка")

    if act == "approve":
        await bot.copy_message(CHANNEL_ID, msg.chat.id, msg.message_id)
        await c.message.edit_text("Опубликовано")
        await bot.send_message(uid, "Ваш пост опубликован!")

    elif act == "reject":
        await c.message.edit_text("Отклонено")
        await bot.send_message(uid, "Пост не прошёл")

    elif act == "ban":
        await ban_user(uid)
        await c.message.edit_text("Забанен")
        await bot.send_message(uid, "Вы забанены")

    elif act == "save":
        await save_post(c.from_user.id, msg.chat.id, msg.message_id)
        await c.message.edit_text("Сохранено")

    await c.answer()

# ====================== СОХРАНЁННЫЕ ======================
@dp.callback_query(lambda c: c.data and c.data.startswith("saved_"))
async def saved_handler(c: types.CallbackQuery):
    d = c.data

    if d == "saved_close":
        try:
            await c.message.delete()
            if c.message.reply_to_message:
                await c.message.reply_to_message.delete()
        except: pass
        return await c.answer()

    if d.startswith("saved_del_"):
        idx = int(d.split("_")[2])
        await delete_saved(c.from_user.id, idx)
        total = await get_saved_count(c.from_user.id)
        try:
            await c.message.delete()
            if c.message.reply_to_message:
                await c.message.reply_to_message.delete()
        except: pass
        if total == 0:
            return await c.answer("Очищено")
        row = await get_saved(c.from_user.id, 0)
        f = await bot.forward_message(c.message.chat.id, row[0], row[1])
        await bot.send_message(c.message.chat.id, "Управление:", reply_to_message_id=f.message_id,
                               reply_markup=saved_kb(0, total))
        return await c.answer("Удалено")

    if d.startswith(("saved_prev_", "saved_next_")):
        parts = d.split("_")
        idx = int(parts[2])
        new_idx = idx - 1 if parts[1] == "prev" else idx + 1
        total = await get_saved_count(c.from_user.id)
        if new_idx < 0 or new_idx >= total:
            return await c.answer("Конец", show_alert=True)
        row = await get_saved(c.from_user.id, new_idx)
        try:
            await c.message.delete()
            if c.message.reply_to_message:
                await c.message.reply_to_message.delete()
        except: pass
        f = await bot.forward_message(c.message.chat.id, row[0], row[1])
        await bot.send_message(c.message.chat.id, "Управление:", reply_to_message_id=f.message_id,
                               reply_markup=saved_kb(new_idx, total))

    await c.answer()

# ====================== РАЗБАН ======================
@dp.callback_query(lambda c: c.data and c.data.startswith("unban_"))
async def unban(c: types.CallbackQuery):
    uid = int(c.data.split("_")[1])
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM banned_users WHERE user_id=?", (uid,))
        await db.commit()
    await c.answer("Разбанен!")
    await show_banned(c.message)

@dp.callback_query(lambda c: c.data == "back_menu")
async def back(c: types.CallbackQuery):
    await c.message.edit_text("Готово", reply_markup=main_menu(True))

# ====================== ЗАПУСК ======================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
