from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import base64
import requests
import json
from datetime import datetime, timezone
import os

app = Flask(__name__)

# === OKX API CONFIG ===
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
API_PASSPHRASE = os.getenv("API_PASSPHRASE")
BASE_URL = 'https://www.okx.com'

print("DEBUG >> API_KEY:", API_KEY)
print("DEBUG >> API_SECRET:", API_SECRET)
print("DEBUG >> API_PASSPHRASE:", API_PASSPHRASE)

# === SIGNATURE GENERATOR ===
def generate_signature(timestamp, method, request_path, body=''):
    message = f'{timestamp}{method.upper()}{request_path}{body}'
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    d = mac.digest()
    return base64.b64encode(d).decode()

# === OKX REQUEST ===
def okx_request(method, path, body_dict=None):
    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    body = json.dumps(body_dict) if body_dict else ''
    headers = {
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': generate_signature(timestamp, method, path, body),
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }
    url = BASE_URL + path
    response = requests.request(method, url, headers=headers, data=body)
    return response.json()

# === GET BALANCE ===
def get_balance(token="USDT"):
    result = okx_request('GET', '/api/v5/account/balance')
    for item in result.get("data", [])[0].get("details", []):
        if item.get("ccy") == token:
            return float(item.get("availEq"))
    return 0.0

# === GET MARKET PRICE ===
def get_market_price(symbol):
    result = okx_request('GET', f'/api/v5/market/ticker?instId={symbol}')
    return float(result.get("data", [])[0].get("last", 0))

# === SEND ORDER ===
def send_order_to_okx(symbol, side, percent=25, leverage=10):
    balance = get_balance("USDT")
    price = get_market_price(symbol)

    notional = balance * (percent / 100) * leverage
    size = round(notional / price, 3)

    print(f"[DEBUG] Balance: {balance}, Price: {price}, Size: {size}")

    body = {
        "instId": symbol,
        "tdMode": "cross",
        "side": side,
        "ordType": "market",
        "sz": str(size),
        "posSide": "long" if side == "buy" else "short",
        "lever": str(leverage)
    }

    return okx_request("POST", "/api/v5/trade/order", body)

# === HOME ===
@app.route("/")
def home():
    return "Bot is running!"

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("[Webhook] Received:", data)

    action = data.get("action")
    symbol = data.get("symbol", "SOL-USDT-SWAP")
    percent = float(data.get("percent", 25))
    leverage = int(data.get("leverage", 10))

    if action in ["buy", "sell"]:
        response = send_order_to_okx(symbol, action, percent, leverage)
        return jsonify({"status": "order_sent", "response": response})
    else:
        return jsonify({"status": "invalid action", "data": data})

# === RUN APP ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
