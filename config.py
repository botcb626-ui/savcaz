# config.py

# --- НАСТРОЙКИ БОТА ---
TOKEN = '8464671001:AAFxikyogiZXrVmzJ5R1QnNAkc0mEi7E7LQ'                    # Токен Telegram бота берётся из переменной окружения
API_CRYPTOBOT = '534705:AAb8W3NhO7JxjTY3mvYUDjGixYfnhLxBaMo'    # Токен из Crypto Bot (@CryptoBot) — для создания инвойсов
CHANNEL_USERNAME = "gamesshades"                     # ID вашего игрового канала (начинается с -100)
CHANNEL_ID = -1003755720528
ADMIN_IDS = [8035506201]                        # Список ID администраторов через запятую (например, ваш ID)

# --- ССЫЛКИ (НОВЫЕ) ---
SUPPORT_USERNAME = "dspiq"                     # Юзернейм поддержки (без @)
BOT_USERNAME = "casshadebot"                    # Юзернейм вашего бота (без @)
WIN_IMAGE_URL = "https://i.postimg.cc/9f0DYZ2h/win.jpg"
LOSE_IMAGE_URL = "https://i.postimg.cc/WzLtVykq/lose.jpg"

# --- ЛИМИТЫ СТАВОК ---
MIN_BET = 0.2      # Минимальная ставка (0.20 USDT)
MAX_BET = 30       # Максимальная ставка

# --- КОЭФФИЦИЕНТЫ ИГР ---
COEF = {
    'dice_over': 1.7,
    'dice_under': 1.7,
    'dice_even': 1.7,
    'dice_odd': 1.7,
    'football_goal': 1.2,
    'football_miss': 1.7,
    'basketball_goal': 1.2,
    'basketball_miss': 1.7,
}

# --- НАСТРОЙКИ ПОПОЛНЕНИЯ ЧЕРЕЗ ЗВЁЗДЫ ---
STARS_PER_CENT = 2                     # 1 цент = 2 звезды
MIN_STARS_DEPOSIT_CENTS = 20            # Минимальная сумма пополнения в центах (20 центов = 40 звёзд)
