This is price near 7 day High/Low notifier bot.

## Setup

1. Create a virtual environment and activate it:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`

2. Install dependencies:
    ```bash
    pip install -r requirements.txt

3. Create a .env file and add your Telegram API key:
    ```bash
    TELEGRAM_TOKEN = 'telegram_bot_token'
    CHAT_ID = 'chat_id'
    BINANCE_API_KEY = "binance_api_key"
    BINANCE_API_SECRET = 'binance_api_secret'

4. Run the bot
    ```bash
    python high_low_bot.py