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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiocryptopay import AioCryptoPay, Networks

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

# ========== FSM СОСТОЯНИЯ ==========
class GameStates(StatesGroup):
    choosing_game = State()
    choosing_dice_type = State()
    waiting_bet = State()
    waiting_withdraw = State()
    waiting_deposit_custom = State()

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
    builder.button(text="🔙 Назад", callback_data="play_menu")
    builder.adjust(2, 2, 1)
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
    # Формируем полную подпись: описание результата + строка о выигрыше/проигрыше
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
        # Пытаемся отправить фото
        await bot.send_photo(
            chat_id=config.CHANNEL_ID,
            photo=photo_url,
            caption=caption,
            reply_markup=keyboard,
            reply_to_message_id=bet_msg_id
        )
    except Exception as e:
        print(f"Ошибка отправки результата с фото: {e}. Отправляю текст.")
        # Если фото не отправилось, отправляем просто текст с той же подписью
        try:
            await bot.send_message(
                config.CHANNEL_ID,
                caption,
                reply_markup=keyboard,
                reply_to_message_id=bet_msg_id
            )
        except Exception as e2:
            print(f"Критическая ошибка отправки результата в канал: {e2}")

# ========== ФОНОВАЯ ЗАДАЧА ПРОВЕРКИ ИНВОЙСОВ ==========
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
    get_user(message.from_user.id)
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\nДобро пожаловать в казино!",
        reply_markup=main_keyboard()
    )

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    await show_profile(message)

# ---- АДМИН-КОМАНДЫ ----
@dp.message(Command("checkprofile"))
async def cmd_checkprofile(message: types.Message, command: CommandObject):
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
async def cmd_takemoney(message: types.Message, command: CommandObject):
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
async def cmd_addmoney(message: types.Message, command: CommandObject):
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
async def cmd_sendnote(message: types.Message, command: CommandObject):
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
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🎰 Главное меню:", reply_markup=main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def show_profile(callback_or_message):
    if isinstance(callback_or_message, types.CallbackQuery):
        user_id = callback_or_message.from_user.id
        message = callback_or_message.message
        answer_method = callback_or_message.answer
    else:
        user_id = callback_or_message.from_user.id
        message = callback_or_message
        answer_method = None
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

# --- ПОПОЛНЕНИЕ ---
@dp.callback_query(F.data == "deposit")
async def deposit(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for amount in [5, 10, 25, 50, 100]:
        builder.button(text=f"{amount} USDT", callback_data=f"deposit_{amount}")
    builder.button(text="🔢 Другая сумма", callback_data="deposit_custom")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(3, 2, 1, 1)
    await callback.message.edit_text(
        "💰 <b>Пополнение баланса</b>\n\nВыберите сумму пополнения в USDT или введите свою:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data == "deposit_custom")
async def deposit_custom(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💰 Введите сумму пополнения в USDT (минимум 1 USDT, целое число):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_deposit_custom)
    await callback.answer()

@dp.message(GameStates.waiting_deposit_custom)
async def process_deposit_custom(message: types.Message, state: FSMContext):
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
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
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

@dp.callback_query(F.data.startswith("deposit_"))
async def deposit_button_handler(callback: types.CallbackQuery):
    amount = float(callback.data.split("_")[1])
    await process_deposit_amount(callback, None, amount)

@dp.callback_query(F.data.startswith("check_invoice_"))
async def check_invoice(callback: types.CallbackQuery):
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

# --- ВЫВОД ---
@dp.callback_query(F.data == "withdraw")
async def withdraw(callback: types.CallbackQuery, state: FSMContext):
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
async def process_withdraw(message: types.Message, state: FSMContext):
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

# --- ИГРЫ ---
@dp.callback_query(F.data == "play_menu")
async def play_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.choosing_game)
    await callback.message.edit_text("🎮 Выберите игру:", reply_markup=play_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "game_dice", GameStates.choosing_game)
async def choose_dice(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.choosing_dice_type)
    await callback.message.edit_text("🎲 Выберите тип игры в кости:", reply_markup=dice_type_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("dice_"), GameStates.choosing_dice_type)
async def choose_dice_type(callback: types.CallbackQuery, state: FSMContext):
    game_type = callback.data
    await state.update_data(game=game_type, emoji="🎲")
    await callback.message.edit_text(
        f"🎲 Введите сумму ставки (мин. {config.MIN_BET} USDT, макс. {config.MAX_BET}):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_bet)
    await callback.answer()

@dp.callback_query(F.data == "game_football", GameStates.choosing_game)
async def choose_football(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="⚽ Гол (x1.2)", callback_data="football_goal")
    builder.button(text="🥅 Промах (x1.7)", callback_data="football_miss")
    builder.button(text="🔙 Назад", callback_data="play_menu")
    builder.adjust(2, 1)
    await callback.message.edit_text("⚽ На что ставим?", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("football_"))
async def choose_football_outcome(callback: types.CallbackQuery, state: FSMContext):
    outcome = callback.data
    await state.update_data(game=outcome, emoji="⚽")
    await callback.message.edit_text(
        f"⚽ Введите сумму ставки (мин. {config.MIN_BET} USDT, макс. {config.MAX_BET}):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_bet)
    await callback.answer()

@dp.callback_query(F.data == "game_basketball", GameStates.choosing_game)
async def choose_basketball(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="🏀 Попадание (x1.2)", callback_data="basketball_goal")
    builder.button(text="🧱 Промах (x1.7)", callback_data="basketball_miss")
    builder.button(text="🔙 Назад", callback_data="play_menu")
    builder.adjust(2, 1)
    await callback.message.edit_text("🏀 На что ставим?", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("basketball_"))
async def choose_basketball_outcome(callback: types.CallbackQuery, state: FSMContext):
    outcome = callback.data
    await state.update_data(game=outcome, emoji="🏀")
    await callback.message.edit_text(
        f"🏀 Введите сумму ставки (мин. {config.MIN_BET} USDT, макс. {config.MAX_BET}):",
        reply_markup=back_keyboard()
    )
    await state.set_state(GameStates.waiting_bet)
    await callback.answer()

@dp.message(GameStates.waiting_bet)
async def process_bet(message: types.Message, state: FSMContext):
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
    coef = config.COEF.get(game, 1.0)
    game_names = {
        'dice_over': 'Кости: больше 3.5',
        'dice_under': 'Кости: меньше 3.5',
        'dice_even': 'Кости: четное',
        'dice_odd': 'Кости: нечетное',
        'football_goal': 'Футбол: гол',
        'football_miss': 'Футбол: промах',
        'basketball_goal': 'Баскетбол: попадание',
        'basketball_miss': 'Баскетбол: промах'
    }
    game_name = game_names.get(game, game)
    await send_to_channel(emoji, message.from_user.full_name, bet, game_name, coef)
    try:
        dice_msg = await bot.send_dice(config.CHANNEL_ID, emoji=emoji)
        dice_value = dice_msg.dice.value
    except Exception as e:
        await message.answer("❌ Ошибка отправки игры в канал. Проверьте права бота.")
        update_balance(message.from_user.id, bet)
        await state.clear()
        return

    # Определяем исход игры и выигрыш
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
        is_goal = dice_value in (1, 3, 5)
        if game == 'football_goal':
            win = is_goal
            result_text = f"{'ГОЛ' if is_goal else 'ПРОМАХ'} (выпало {dice_value})"
        else:  # football_miss
            win = not is_goal
            result_text = f"{'ГОЛ' if is_goal else 'ПРОМАХ'} (выпало {dice_value})"
    elif game.startswith('basketball_'):
        is_goal = dice_value in (1, 3, 5)
        if game == 'basketball_goal':
            win = is_goal
            result_text = f"{'ПОПАДАНИЕ' if is_goal else 'ПРОМАХ'} (выпало {dice_value})"
        else:  # basketball_miss
            win = not is_goal
            result_text = f"{'ПОПАДАНИЕ' if is_goal else 'ПРОМАХ'} (выпало {dice_value})"

    win_amount = 0
    if win:
        win_amount = bet * coef
        update_balance(message.from_user.id, win_amount)
        user_result = f"✅ {result_text}\n💰 Вы выиграли {win_amount:.2f} USDT!"
    else:
        user_result = f"❌ {result_text}\n💸 Вы проиграли {bet:.2f} USDT."

    await message.answer(user_result)
    # Отправляем результат в канал
    await send_result_to_channel(dice_msg.message_id, message.from_user.full_name, result_text, win_amount, win)
    update_stats(message.from_user.id, win)
    await state.clear()
    await message.answer("Выберите действие:", reply_markup=main_keyboard())

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