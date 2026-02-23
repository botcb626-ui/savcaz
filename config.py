# config.py

# --- НАСТРОЙКИ БОТА ---
TOKEN = '8506446569:AAGy5op1HFnItC03buk2kXupLl7TCKfMwTw'                    # Токен Telegram бота берётся из переменной окружения
API_CRYPTOBOT = '534704:AAHQevelB7uFHf77O0NynwvzauV813iLl5g'    # Токен из Crypto Bot (@CryptoBot) — для создания инвойсов
CHANNEL_USERNAME = "saveludomoney"                     # ID вашего игрового канала (начинается с -100)
CHANNEL_ID = -1003873600338
ADMIN_IDS = [5559518385]                        # Список ID администраторов через запятую (например, ваш ID)

# --- ССЫЛКИ (НОВЫЕ) ---
SUPPORT_USERNAME = "Save1012"                     # Юзернейм поддержки (без @)
BOT_USERNAME = "saveludobot"                    # Юзернейм вашего бота (без @)
WIN_IMAGE_URL = "https://i.postimg.cc/9f0DYZ2h/win.jpg"
LOSE_IMAGE_URL = "https://i.postimg.cc/WzLtVykq/lose.jpg"

# --- ЛИМИТЫ СТАВОК ---
MIN_BET = 0.2      # Минимальная ставка (0.20 USDT)
MAX_BET = 500       # Максимальная ставка

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
MIN_STARS_DEPOSIT_CENTS = 20 