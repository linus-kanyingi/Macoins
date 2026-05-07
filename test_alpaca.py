import os
from dotenv import load_dotenv
import requests

load_dotenv()
api_key = os.getenv("ALPACA_API_KEY")
api_secret = os.getenv("ALPACA_SECRET_KEY")
base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

print("Key:", api_key[:4] if api_key else None)
print("URL:", base_url)

try:
    res = requests.get(
        f"{base_url}/v2/account", 
        headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
        timeout=5
    )
    print("Status:", res.status_code)
    print("Response:", res.text[:100])
except Exception as e:
    print("Error:", str(e))
