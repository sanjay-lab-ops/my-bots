"""Test Telegram bot connection."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

token   = os.getenv("TELEGRAM_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

if not token or not chat_id:
    print("ERROR: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID missing in .env")
    exit(1)

url  = f"https://api.telegram.org/bot{token}/sendMessage"
resp = requests.post(url, data={"chat_id": chat_id, "text": "Vishu Bot connected successfully!"})

if resp.status_code == 200:
    print("Telegram OK — message sent to your chat")
else:
    print(f"Telegram FAILED — {resp.text}")
