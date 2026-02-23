# main.py
import asyncio
import random
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, PreCheckoutQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiocryptopay import AioCryptoPay, Networks
from aiogram.exceptions import TelegramBadRequest

import config

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=config.TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

crypto = None  # будет инициализирован в main()

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('casino.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0,
            total_bets INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            registered_date TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect('casino.db')
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        cur.execute('''
            INSERT INTO users (user_id, balance, registered_date) 
            VALUES (?, ?, ?)
        ''', (user_id, 0, datetime.now().isoformat()))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
    conn.close()
    return user

def update_balance(user_id: int, amount: float):
    conn = sqlite3.connect('casino.db')
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def update_stats(user_id: int, win: bool):
    conn = sqlite3.connect('casino.db')
    cur = conn.cursor()
    cur.execute("UPDATE users SET total_bets = total_bets + 1 WHERE user_id = ?", (user_id,))
    if win:
        cur.execute("UPDATE users SET total_wins = total_wins + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def save_invoice(invoice_id: str, user_id: int, amount: float):
    conn = sqlite3.connect('casino.db')
    cur = conn.cursor()
    cur.execute("INSERT INTO invoices (invoice_id, user_id, amount) VALUES (?, ?, ?)",
                (invoice_id, user_id, amount))
    conn.commit()
    conn.close()

def get_pending_invoices():
    conn = sqlite3.connect('casino.db')
    cur = conn.cursor()
    cur.execute("SELECT invoice_id, user_id, amount FROM invoices WHERE status = 'pending'")
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_invoice_paid(invoice_id: str):
    conn = sqlite3.connect('casino.db')
    cur = conn.cursor()
    cur.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('casino.db')
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def check_subscription(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал."""
    try:
        member = await bot.get_chat_member(chat_id=f"@{config.CHANNEL_USERNAME}", user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramBadRequest as e:
        print(f"Ошибка проверки подписки: {e}")
        return False
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
        return False

def subscription_required(handler):
    """Декоратор для проверки подписки перед выполнением хендлера."""
    async def wrapper(event, *args, **kwargs):
        user_id = None
        if isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
        elif isinstance(event, types.Message):
            user_id = event.from_user.id
        if not user_id:
            return
        if not await check_subscription(user_id):
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Канал", url=f"https://t.me/{config.CHANNEL_USERNAME}")],
                [InlineKeyboardButton(text="✅ ПРОВЕРИТЬ ПОДПИСКУ", callback_data="check_sub")]
            ])
            if isinstance(event, types.CallbackQuery):
                await event.message.answer(
                    "❌ Вы должны подписаться на канал, чтобы пользоваться ботом.\n\n"
                    "Подпишитесь и нажмите «ПРОВЕРИТЬ ПОДПИСКУ».",
                    reply_markup=markup
                )
                await event.answer()
            else:
                await event.answer(
                    "❌ Вы должны подписаться на канал, чтобы пользоваться ботом.\n\n"
                    "Подпишитесь и нажмите «ПРОВЕРИТЬ ПОДПИСКУ».",
                    reply_markup=markup
                )
            return
        return await handler(event, *args, **kwargs)
    return wrapper

# ========== FSM СОСТОЯНИЯ ==========
class GameStates(StatesGroup):
    choosing_game = State()
    choosing_dice_type = State()
    waiting_bet = State()
    waiting_withdraw = State()
    waiting_deposit_custom = State()
    waiting_stars_deposit = State()

# ========== КЛАВИАТУРЫ ==========
def main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎮 ИГРАТЬ", callback_data="play_menu")
    builder.button(text="💰 ПОПОЛНИТЬ", callback_data="deposit")
    builder.button(text="💸 ВЫВОД", callback_data="withdraw")
    builder.button(text="👤 ПРОФИЛЬ", callback_data="profile")
    builder.button(text="🆘 ПОДДЕРЖКА", url=f"https://t.me/{config.SUPPORT_USERNAME}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def play_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Кости", callback_data="game_dice")
    builder.button(text="⚽ Футбол", callback_data="game_football")
    builder.button(text="🏀 Баскетбол", callback_data="game_basketball")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(2, 1)
    return builder.as_markup()

def dice_type_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴 Больше 3.5 (x1.7)", callback_data="dice_over")
    builder.button(text="🔵 Меньше 3.5 (x1.7)", callback_data="dice_under")
    builder.button(text="🟢 Четное (x1.7)", callback_data="dice_even")
    builder.button(text="🟡 Нечетное (x1.7)", callback_data="dice_odd")
    builder.button(text="⚔️ Дуэль (x1.7)", callback_data="dice_duel")
    builder.button(text="🔙 Назад", callback_data="play_menu")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()

def duel_choice_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴 Больше (чем бот)", callback_data="duel_over")
    builder.button(text="🔵 Меньше (чем бот)", callback_data="duel_under")
    builder.button(text="🔙 Назад", callback_data="game_dice")
    builder.adjust(2, 1)
    return builder.as_markup()

def back_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    return builder.as_markup()

def play_again_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 СДЕЛАТЬ СТАВКУ", url=f"https://t.me/{config.BOT_USERNAME}")
    return builder.as_markup()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ КАНАЛА ==========
async def send_to_channel(game_emoji: str, user_name: str, bet: float, game_name: str, coef: float):
    text = (
        f"{game_emoji} <b>Новая ставка!</b>\n"
        f"Игрок: {user_name}\n"
        f"Игра: {game_name}\n"
        f"Ставка: <b>{bet:.2f} USDT</b>\n"
        f"Коэффициент: {coef}x\n"
        f"Возможный выигрыш: <b>{bet * coef:.2f} USDT</b>"
    )
    try:
        await bot.send_message(config.CHANNEL_ID, text)
    except Exception as e:
        print(f"Ошибка отправки в канал: {e}")

async def send_result_to_channel(bet_msg_id: int, user_name: str, result_text: str, win_amount: float, win: bool):
    photo_url = config.WIN_IMAGE_URL if win else config.LOSE_IMAGE_URL
    if win:
        result_line = f"💰 Выигрыш: {win_amount:.2f} USDT"
    else:
        result_line = "💸 Проигрыш"
    caption = (
        f"🎲 <b>Результат</b>\n"
        f"Игрок: {user_name}\n"
        f"{result_text}\n"
        f"{result_line}"
    )
    keyboard = play_again_keyboard()
    try:
        await bot.send_photo(
            chat_id=config.CHANNEL_ID,
            photo=photo_url,
            caption=caption,
            reply_markup=keyboard,
            reply_to_message_id=bet_msg_id
        )
    except Exception as e:
        print(f"Ошибка отправки результата с фото: {e}. Отправляю текст.")
        try:
            await bot.send_message(
                config.CHANNEL_ID,
                caption,
                reply_markup=keyboard,
                reply_to_message_id=bet_msg_id
            )
        except Exception as e2:
            print(f"Критическая ошибка отправки результата в канал: {e2}")

# ========== ФОНОВАЯ ЗАДАЧА ПРОВЕРКИ ИНВОЙСОВ (CRYPTOBOT) ==========
async def check_invoices_background():
    global crypto
    while True:
        try:
            pending = get_pending_invoices()
            for invoice_id, user_id, amount in pending:
                invoices = await crypto.get_invoices(invoice_ids=invoice_id)
                if invoices and invoices[0].status == 'paid':
                    update_balance(user_id, amount)
                    mark_invoice_paid(invoice_id)
                    try:
                        await bot.send_message(
                            user_id,
                            f"✅ Ваш платёж на {amount:.2f} USDT подтверждён!\nБаланс пополнен."
                        )
                    except:
                        pass
        except Exception as e:
            print(f"Ошибка в фоновой проверке: {e}")
        await asyncio.sleep(60)

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if await check_subscription(user_id):
        get_user(user_id)
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\nДобро пожаловать в казино!",
            reply_markup=main_keyboard()
        )
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Канал", url=f"https://t.me/{config.CHANNEL_USERNAME}")],
            [InlineKeyboardButton(text="✅ ПРОВЕРИТЬ ПОДПИСКУ", callback_data="check_sub")]
        ])
        await message.answer(
            "❌ Вы должны подписаться на канал, чтобы пользоваться ботом.\n\n"
            "Подпишитесь и нажмите «ПРОВЕРИТЬ ПОДПИСКУ».",
            reply_markup=markup
        )

@dp.message(Command("profile"))
@subscription_required
async def cmd_profile(message: types.Message, **kwargs):
    await show_profile(message)

# ---- АДМИН-КОМАНДЫ ----
@dp.message(Command("checkprofile"))
@subscription_required
async def cmd_checkprofile(message: types.Message, command: CommandObject, **kwargs):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ У вас нет прав администратора.")
        return
    args = command.args
    if not args:
        await message.answer("Использование: /checkprofile <ID пользователя>")
        return
    try:
        target_id = int(args.strip())
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    user = get_user(target_id)
    text = (
        f"👤 <b>Профиль пользователя {target_id}</b>\n"
        f"💰 Баланс: <b>{user[1]:.2f} USDT</b>\n"
        f"🎲 Всего игр: {user[2]}\n"
        f"🏆 Побед: {user[3]}"
    )
    await message.answer(text)

@dp.message(Command("takemoney"))
@subscription_required
async def cmd_takemoney(message: types.Message, command: CommandObject, **kwargs):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ У вас нет прав администратора.")
        return
    args = command.args
    if not args:
        await message.answer("Использование: /takemoney <ID пользователя> <сумма>")
        return
    parts = args.split()
    if len(parts) != 2:
        await message.answer("Неверный формат. Нужно: /takemoney <ID> <сумма>")
        return
    try:
        target_id = int(parts[0])
        amount = float(parts[1])
    except ValueError:
        await message.answer("❌ ID и сумма должны быть числами.")
        return
    if amount <= 0:
        await message.answer("❌ Сумма должна быть положительной.")
        return
    user = get_user(target_id)
    current_balance = user[1]
    if current_balance < amount:
        await message.answer(f"❌ Недостаточно средств на балансе пользователя. Доступно: {current_balance:.2f} USDT")
        return
    update_balance(target_id, -amount)
    await message.answer(f"✅ С баланса пользователя {target_id} списано {amount:.2f} USDT. Новый баланс: {current_balance - amount:.2f} USDT")
    try:
        await bot.send_message(target_id, f"💰 Администратор списал с вашего баланса {amount:.2f} USDT.")
    except:
        pass

@dp.message(Command("addmoney"))
@subscription_required
async def cmd_addmoney(message: types.Message, command: CommandObject, **kwargs):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ У вас нет прав администратора.")
        return
    args = command.args
    if not args:
        await message.answer("Использование: /addmoney <сумма> <ID пользователя>\nНапример: /addmoney 100 123456789")
        return
    parts = args.split()
    if len(parts) != 2:
        await message.answer("Неверный формат. Нужно: /addmoney <сумма> <ID>")
        return
    try:
        amount = float(parts[0])
        user_id = int(parts[1])
    except ValueError:
        await message.answer("Сумма должна быть числом, ID — целым числом.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть положительной.")
        return
    get_user(user_id)
    update_balance(user_id, amount)
    await message.answer(f"✅ Добавлено {amount:.2f} USDT пользователю {user_id}.")
    try:
        await bot.send_message(user_id, f"💰 Вам начислено {amount:.2f} USDT администратором.")
    except:
        pass

@dp.message(Command("sendnote"))
@subscription_required
async def cmd_sendnote(message: types.Message, command: CommandObject, **kwargs):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ У вас нет прав администратора.")
        return
    text = command.args
    if not text:
        await message.answer("❌ Укажите сообщение для рассылки.\nИспользование: /sendnote Текст сообщения")
        return
    users = get_all_users()
    if not users:
        await message.answer("❌ Нет пользователей в базе.")
        return
    sent = 0
    failed = 0
    await message.answer(f"📢 Начинаю рассылку... Всего пользователей: {len(users)}")
    for uid in users:
        try:
            await bot.send_message(uid, f"📢 <b>Рассылка от администратора:</b>\n\n{text}")
            sent += 1
        except Exception as e:
            failed += 1
            print(f"Ошибка отправки пользователю {uid}: {e}")
        await asyncio.sleep(0.05)
    await message.answer(f"✅ Рассылка завершена.\nУспешно: {sent}\nНе удалось: {failed}")

# ========== ОБРАБОТЧИКИ КОЛЛБЭКОВ ==========
@dp.callback_query(F.data == "back_to_main")
@subscription_required
async def back_to_main(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    await state.clear()
    await callback.message.edit_text("🎰 Главное меню:", reply_markup=main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "profile")
@subscription_required
async def show_profile(callback_or_message, **kwargs):
    if isinstance(callback_or_message, types.CallbackQuery):
        user_id = callback_or_message.from_user.id
        message = callback_or_message.message
    else:
        user_id = callback_or_message.from_user.id
        message = callback_or_message
    user = get_user(user_id)
    text = (
        f"👤 <b>Ваш профиль</b>\n"
        f"ID: {user_id}\n"
        f"💰 Баланс: <b>{user[1]:.2f} USDT</b>\n"
        f"🎲 Всего игр: {user[2]}\n"
        f"🏆 Побед: {user[3]}"
    )
    if isinstance(callback_or_message, types.CallbackQuery):
        await message.edit_text(text, reply_markup=back_keyboard())
        await callback_or_message.answer()
    else:
        await message.answer(text, reply_markup=back_keyboard())

# --- ПОПОЛНЕНИЕ (общее меню) ---
@dp.callback_query(F.data == "deposit")
@subscription_required
async def deposit(callback: types.CallbackQuery, **kwargs):
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Пополнить Stars", callback_data="deposit_stars")
    builder.button(text="💳 Пополнить USDT (CryptoBot)", callback_data="deposit_usdt")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(2, 1)
    await callback.message.edit_text(
        "💰 <b>Выберите способ пополнения:</b>",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# --- ПОПОЛНЕНИЕ USDT (CryptoBot) ---
@dp.callback_query(F.data == "deposit_usdt")
@subscription_required
async def deposit_usdt(callback: types.CallbackQuery, **kwargs):
    builder = InlineKeyboardBuilder()
    for amount in [5, 10, 25, 50, 100]:
        builder.button(text=f"{amount} USDT", callback_data=f"deposit_{amount}")
    builder.button(text="🔢 Другая сумма", callback_data="deposit_custom")
    builder.button(text="🔙 Назад", callback_data="deposit")
    builder.adjust(3, 2, 1, 1)
    await callback.message.edit_text(
        "💰 <b>Пополнение через CryptoBot</b>\n\nВыберите сумму в USDT или введите свою:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit_custom")
@subscription_required
async def deposit_custom(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    await callback.message.edit_text(
        "💰 Введите сумму пополнения в USDT (минимум 1 USDT, целое число):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_deposit_custom)
    await callback.answer()

@dp.message(GameStates.waiting_deposit_custom)
@subscription_required
async def process_deposit_custom(message: types.Message, state: FSMContext, **kwargs):
    try:
        amount = float(message.text)
    except ValueError:
        await message.answer("❌ Введите число!")
        return
    if amount < 1:
        await message.answer("❌ Минимальная сумма пополнения 1 USDT")
        return
    if amount > 1000:
        await message.answer("❌ Максимальная сумма пополнения 1000 USDT")
        return
    await process_deposit_amount(message, state, amount)

async def process_deposit_amount(event: types.CallbackQuery | types.Message, state: FSMContext, amount: float):
    global crypto
    if isinstance(event, types.CallbackQuery):
        user_id = event.from_user.id
        target_message = event.message
        is_callback = True
    else:
        user_id = event.from_user.id
        target_message = event
        is_callback = False

    try:
        invoice = await crypto.create_invoice(
            amount=amount,
            currency_type='crypto',
            asset='USDT',
            description="Пополнение счёта в казино",
            payload=str(user_id)
        )
        if not invoice:
            raise Exception("Не удалось создать инвойс (пустой ответ)")

        pay_url = (
            getattr(invoice, 'bot_invoice_url', None) or
            getattr(invoice, 'web_app_invoice_url', None) or
            getattr(invoice, 'mini_app_invoice_url', None) or
            getattr(invoice, 'pay_url', None) or
            getattr(invoice, 'url', None)
        )
        if not pay_url:
            raise Exception(f"Не найдена ссылка на оплату в ответе: {invoice}")

        save_invoice(invoice.invoice_id, user_id, amount)

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_invoice_{invoice.invoice_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
        ])

        success_text = (
            f"💰 <b>Счёт на {amount} USDT создан!</b>\n\n"
            f"1. Нажмите «Оплатить» и завершите платёж в CryptoBot.\n"
            f"2. После оплаты нажмите «✅ Я оплатил» для проверки.\n"
            f"Средства будут зачислены автоматически в течение минуты."
        )

        if is_callback:
            await target_message.edit_text(success_text, reply_markup=markup)
        else:
            await target_message.answer(success_text, reply_markup=markup)

    except Exception as e:
        error_text = f"❌ Ошибка создания счёта: {str(e)}"
        if is_callback:
            try:
                await target_message.edit_text(error_text, reply_markup=back_keyboard())
            except:
                await target_message.answer(error_text, reply_markup=back_keyboard())
        else:
            await target_message.answer(error_text, reply_markup=back_keyboard())
        print(f"Ошибка создания инвойса: {e}")

    if is_callback:
        await event.answer()
    else:
        await state.clear()

@dp.callback_query(F.data.regexp(r'^deposit_\d+$'))
@subscription_required
async def deposit_button_handler(callback: types.CallbackQuery, **kwargs):
    parts = callback.data.split("_")
    amount = float(parts[1])
    await process_deposit_amount(callback, None, amount)

@dp.callback_query(F.data.startswith("check_invoice_"))
@subscription_required
async def check_invoice(callback: types.CallbackQuery, **kwargs):
    global crypto
    invoice_id = callback.data.replace("check_invoice_", "")
    user_id = callback.from_user.id
    try:
        invoices = await crypto.get_invoices(invoice_ids=invoice_id)
        if invoices and invoices[0].status == 'paid':
            conn = sqlite3.connect('casino.db')
            cur = conn.cursor()
            cur.execute("SELECT status FROM invoices WHERE invoice_id = ?", (invoice_id,))
            row = cur.fetchone()
            if row and row[0] == 'pending':
                update_balance(user_id, invoices[0].amount)
                cur.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
                conn.commit()
                await callback.message.edit_text(
                    f"✅ Платёж подтверждён! Ваш баланс пополнен на {invoices[0].amount} USDT.",
                    reply_markup=back_keyboard()
                )
            else:
                await callback.message.edit_text(
                    "✅ Этот платёж уже был обработан ранее.",
                    reply_markup=back_keyboard()
                )
            conn.close()
        else:
            await callback.answer("❌ Счёт ещё не оплачен. Попробуйте позже или проверьте статус в CryptoBot.", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка проверки: {e}", show_alert=True)
    await callback.answer()

# --- ПОПОЛНЕНИЕ ЧЕРЕЗ ЗВЁЗДЫ ---
@dp.callback_query(F.data == "deposit_stars")
@subscription_required
async def deposit_stars(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    await callback.message.answer(
        f"⭐️ <b>Пополнение через Telegram Stars</b>\n\n"
        f"Курс: 1 цент = {config.STARS_PER_CENT} звёзд\n"
        f"Минимальная сумма: {config.MIN_STARS_DEPOSIT_CENTS} центов "
        f"(= {config.MIN_STARS_DEPOSIT_CENTS * config.STARS_PER_CENT} звёзд)\n\n"
        f"Отправьте число — сколько центов хотите пополнить (целое число):\n"
        f"Например: 20",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_stars_deposit)
    await callback.answer()

@dp.message(GameStates.waiting_stars_deposit)
@subscription_required
async def process_stars_deposit(message: types.Message, state: FSMContext, **kwargs):
    if not message.text.isdigit():
        await message.answer("❌ Введите целое число (количество центов).")
        return
    cents = int(message.text)
    if cents < config.MIN_STARS_DEPOSIT_CENTS:
        await message.answer(f"❌ Минимальная сумма: {config.MIN_STARS_DEPOSIT_CENTS} центов "
                             f"(= {config.MIN_STARS_DEPOSIT_CENTS * config.STARS_PER_CENT} звёзд).")
        return
    if cents > 10000:
        await message.answer("❌ Максимальная сумма: 10000 центов (100 USDT).")
        return
    stars = cents * config.STARS_PER_CENT
    user_id = message.from_user.id
    prices = [LabeledPrice(label="Пополнение баланса казино", amount=stars)]
    await message.answer_invoice(
        title="Пополнение через ⭐️ Звёзды",
        description=f"Пополнение баланса на {cents} центов (эквивалент {cents/100:.2f} USDT)",
        prices=prices,
        provider_token="",
        payload=f"stars:{user_id}:{cents}",
        currency="XTR"
    )
    await state.clear()

# --- Обработка предварительного запроса (pre_checkout) ---
@dp.pre_checkout_query()
async def pre_checkout_handler(pre: PreCheckoutQuery):
    await pre.answer(ok=True)

# --- Обработка успешного платежа ---
@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("stars:"):
        parts = payload.split(":")
        if len(parts) == 3:
            user_id = int(parts[1])
            cents = int(parts[2])
            amount_usd = cents / 100.0
            update_balance(user_id, amount_usd)
            await message.answer(f"✅ Баланс пополнен на {amount_usd:.2f} USDT через звёзды.")
            return
    await message.answer("❌ Не удалось обработать платёж. Обратитесь в поддержку.")

# --- ВЫВОД ---
@dp.callback_query(F.data == "withdraw")
@subscription_required
async def withdraw(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    user = get_user(callback.from_user.id)
    if user[1] <= 0:
        await callback.answer("❌ У вас нет средств для вывода!", show_alert=True)
        return
    await callback.message.edit_text(
        "💸 <b>Вывод средств</b>\n\nВведите сумму в USDT (минимум 1, целое число):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_withdraw)
    await callback.answer()

@dp.message(GameStates.waiting_withdraw)
@subscription_required
async def process_withdraw(message: types.Message, state: FSMContext, **kwargs):
    global crypto
    try:
        amount = float(message.text)
    except ValueError:
        await message.answer("❌ Введите число!")
        return
    if amount < 1:
        await message.answer("❌ Минимальная сумма вывода 1 USDT")
        return
    if amount > 1000:
        await message.answer("❌ Максимальная сумма вывода 1000 USDT")
        return
    user = get_user(message.from_user.id)
    if user[1] < amount:
        await message.answer("❌ Недостаточно средств!")
        await state.clear()
        return
    try:
        check = await crypto.create_check(
            asset='USDT',
            amount=amount,
            pin_to_user_id=message.from_user.id
        )
        check_url = (
            getattr(check, 'bot_check_url', None) or
            getattr(check, 'web_app_check_url', None) or
            getattr(check, 'mini_app_check_url', None) or
            getattr(check, 'pay_url', None) or
            getattr(check, 'url', None)
        )
        if not check_url:
            raise Exception("Не удалось получить ссылку на чек")
        update_balance(message.from_user.id, -amount)
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Получить чек", url=check_url)]
        ])
        await message.answer(
            f"✅ Чек на {amount:.2f} USDT создан!\nНажмите кнопку ниже, чтобы активировать его в CryptoBot.",
            reply_markup=markup
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка создания чека: {e}")
        update_balance(message.from_user.id, amount)
    finally:
        await state.clear()

# --- ИГРЫ (с корректной фильтрацией) ---
def football_is_goal(value: int) -> bool:
    return value in (3, 4, 5)

def basketball_is_goal(value: int) -> bool:
    return value in (4, 5)

@dp.callback_query(F.data == "play_menu")
@subscription_required
async def play_menu(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    await state.set_state(GameStates.choosing_game)
    await callback.message.edit_text("🎮 Выберите игру:", reply_markup=play_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "game_dice", GameStates.choosing_game)
@subscription_required
async def choose_dice(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    await state.set_state(GameStates.choosing_dice_type)
    await callback.message.edit_text("🎲 Выберите тип игры в кости:", reply_markup=dice_type_keyboard())
    await callback.answer()

# Обработчики для обычных игр в кости (кроме дуэли)
@dp.callback_query(F.data.startswith("dice_"), GameStates.choosing_dice_type)
@subscription_required
async def choose_dice_type(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    game_type = callback.data
    if game_type == "dice_duel":
        await callback.message.edit_text(
            "⚔️ Выберите условие победы над ботом:",
            reply_markup=duel_choice_keyboard()
        )
        await state.set_state(GameStates.choosing_dice_type)
        await callback.answer()
        return
    await state.update_data(game=game_type, emoji="🎲", duel=False)
    await callback.message.edit_text(
        f"🎲 Введите сумму ставки (мин. {config.MIN_BET} USDT, макс. {config.MAX_BET}):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_bet)
    await callback.answer()

# Обработчики для выбора направления дуэли
@dp.callback_query(F.data.startswith("duel_"), GameStates.choosing_dice_type)
@subscription_required
async def choose_duel_direction(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    direction = callback.data
    await state.update_data(game=direction, emoji="🎲", duel=True)
    await callback.message.edit_text(
        f"⚔️ Введите сумму ставки на дуэль (мин. {config.MIN_BET} USDT, макс. {config.MAX_BET}):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_bet)
    await callback.answer()

@dp.callback_query(F.data == "game_football", GameStates.choosing_game)
@subscription_required
async def choose_football(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    builder = InlineKeyboardBuilder()
    builder.button(text="⚽ Гол (x1.2)", callback_data="football_goal")
    builder.button(text="🥅 Промах (x1.7)", callback_data="football_miss")
    builder.button(text="🔙 Назад", callback_data="play_menu")
    builder.adjust(2, 1)
    await callback.message.edit_text("⚽ На что ставим?", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("football_"))
@subscription_required
async def choose_football_outcome(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    outcome = callback.data
    await state.update_data(game=outcome, emoji="⚽", duel=False)
    await callback.message.edit_text(
        f"⚽ Введите сумму ставки (мин. {config.MIN_BET} USDT, макс. {config.MAX_BET}):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_bet)
    await callback.answer()

@dp.callback_query(F.data == "game_basketball", GameStates.choosing_game)
@subscription_required
async def choose_basketball(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    builder = InlineKeyboardBuilder()
    builder.button(text="🏀 Попадание (x1.2)", callback_data="basketball_goal")
    builder.button(text="🧱 Промах (x1.7)", callback_data="basketball_miss")
    builder.button(text="🔙 Назад", callback_data="play_menu")
    builder.adjust(2, 1)
    await callback.message.edit_text("🏀 На что ставим?", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("basketball_"))
@subscription_required
async def choose_basketball_outcome(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    outcome = callback.data
    await state.update_data(game=outcome, emoji="🏀", duel=False)
    await callback.message.edit_text(
        f"🏀 Введите сумму ставки (мин. {config.MIN_BET} USDT, макс. {config.MAX_BET}):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_bet)
    await callback.answer()

@dp.message(GameStates.waiting_bet)
@subscription_required
async def process_bet(message: types.Message, state: FSMContext, **kwargs):
    try:
        bet = float(message.text)
    except ValueError:
        await message.answer("❌ Введите число!")
        return
    if bet < config.MIN_BET:
        await message.answer(f"❌ Минимальная ставка {config.MIN_BET} USDT")
        return
    if bet > config.MAX_BET:
        await message.answer(f"❌ Максимальная ставка {config.MAX_BET} USDT")
        return

    user = get_user(message.from_user.id)
    if user[1] < bet:
        await message.answer("❌ Недостаточно средств!")
        await state.clear()
        return

    update_balance(message.from_user.id, -bet)

    data = await state.get_data()
    game = data['game']
    emoji = data['emoji']
    duel = data.get('duel', False)

    if duel:
        coef = config.COEF.get('dice_over_under', 1.7)
    else:
        coef = config.COEF.get(game, 1.0)

    game_names = {
        'dice_over': 'Кости: больше 3.5',
        'dice_under': 'Кости: меньше 3.5',
        'dice_even': 'Кости: четное',
        'dice_odd': 'Кости: нечетное',
        'football_goal': 'Футбол: гол',
        'football_miss': 'Футбол: промах',
        'basketball_goal': 'Баскетбол: попадание',
        'basketball_miss': 'Баскетбол: промах',
    }

    if duel:
        if game == 'duel_over':
            game_name = "Дуэль: больше (против бота)"
        else:
            game_name = "Дуэль: меньше (против бота)"
    else:
        game_name = game_names.get(game, game)

    await send_to_channel(emoji, message.from_user.full_name, bet, game_name, coef)

    try:
        if duel:
            dice_msg1 = await bot.send_dice(config.CHANNEL_ID, emoji=emoji)
            dice_msg2 = await bot.send_dice(config.CHANNEL_ID, emoji=emoji)
            user_value = dice_msg1.dice.value
            bot_value = dice_msg2.dice.value
            if game == 'duel_over':
                win = user_value > bot_value
                result_text = f"Ваш кубик: {user_value}, кубик бота: {bot_value}"
            else:
                win = user_value < bot_value
                result_text = f"Ваш кубик: {user_value}, кубик бота: {bot_value}"
            if user_value == bot_value:
                win = False
                result_text += " — ничья, вы проиграли."
            else:
                result_text += f" — {'вы победили' if win else 'вы проиграли'}."
        else:
            dice_msg = await bot.send_dice(config.CHANNEL_ID, emoji=emoji)
            dice_value = dice_msg.dice.value
            win = False
            result_text = ""
            if game.startswith('dice_'):
                if game == 'dice_over':
                    win = dice_value > 3.5
                    result_text = f"Выпало {dice_value} {'(больше 3.5)' if win else '(меньше или равно 3.5)'}"
                elif game == 'dice_under':
                    win = dice_value < 3.5
                    result_text = f"Выпало {dice_value} {'(меньше 3.5)' if win else '(больше или равно 3.5)'}"
                elif game == 'dice_even':
                    win = dice_value % 2 == 0
                    result_text = f"Выпало {dice_value} {'(четное)' if win else '(нечетное)'}"
                elif game == 'dice_odd':
                    win = dice_value % 2 != 0
                    result_text = f"Выпало {dice_value} {'(нечетное)' if win else '(четное)'}"
            elif game.startswith('football_'):
                is_goal = football_is_goal(dice_value)
                if game == 'football_goal':
                    win = is_goal
                else:
                    win = not is_goal
                result_text = f"{'ГОЛ' if is_goal else 'ПРОМАХ'} (выпало {dice_value})"
            elif game.startswith('basketball_'):
                is_goal = basketball_is_goal(dice_value)
                if game == 'basketball_goal':
                    win = is_goal
                else:
                    win = not is_goal
                result_text = f"{'ПОПАДАНИЕ' if is_goal else 'ПРОМАХ'} (выпало {dice_value})"
    except Exception as e:
        await message.answer("❌ Ошибка отправки игры в канал. Проверьте права бота.")
        update_balance(message.from_user.id, bet)
        await state.clear()
        return

    win_amount = 0
    if win:
        win_amount = bet * coef
        update_balance(message.from_user.id, win_amount)
        user_result = f"✅ {result_text}\n💰 Вы выиграли {win_amount:.2f} USDT!"
    else:
        user_result = f"❌ {result_text}\n💸 Вы проиграли {bet:.2f} USDT."

    await message.answer(user_result)

    if duel:
        await send_result_to_channel(dice_msg1.message_id, message.from_user.full_name, result_text, win_amount, win)
    else:
        await send_result_to_channel(dice_msg.message_id, message.from_user.full_name, result_text, win_amount, win)

    update_stats(message.from_user.id, win)
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=main_keyboard())

# --- Обработчик кнопки "ПРОВЕРИТЬ ПОДПИСКУ" ---
@dp.callback_query(F.data == "check_sub")
async def check_subscription_callback(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    user_id = callback.from_user.id
    if await check_subscription(user_id):
        get_user(user_id)
        await callback.message.edit_text(
            f"✅ Подписка подтверждена! Добро пожаловать в казино!",
            reply_markup=main_keyboard()
        )
        await callback.answer()
    else:
        await callback.answer("❌ Вы ещё не подписались. Подпишитесь и нажмите снова.", show_alert=True)

# ========== ЗАПУСК ==========
async def main():
    global crypto
    crypto = AioCryptoPay(token=config.API_CRYPTOBOT, network=Networks.MAIN_NET)
    print("Бот запущен...")
    init_db()
    asyncio.create_task(check_invoices_background())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
