from dotenv import load_dotenv
load_dotenv()
from mt5_connector import connect, get_balance, disconnect

if connect():
    print("SUCCESS! Connected to MT5")
    print(f"Balance: ${get_balance():.2f}")
    disconnect()
else:
    print("FAILED! Check your .env file credentials")
