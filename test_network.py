import requests

try:
    r = requests.get("https://api.telegram.org")
    print("Telegram reachable", r.status_code)
except Exception as e:
    print("Error:", e)
