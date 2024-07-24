This is a telegram trading assistant bot.
Uses telethon with Telegram Core API.
Uses Binance Futures.

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
    TEL_API_ID = tel_api_id_int
    TEL_API_HASH = "tel_api_hash"
    BI_API_KEY = "binance_api_key"
    BI_API_SECRET = "binance_api_secret"
    TEL_CHAT = "Username/ChatID" 

4. Run the bot
    ```bash
    python assist.py