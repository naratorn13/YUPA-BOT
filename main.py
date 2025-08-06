# === Standard Library ===
import os
import json
import time
import hmac
import hashlib
import base64
import requests
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, getcontext

# === Third-party ===
from flask import Flask, request, jsonify
from waitress import serve

app = Flask(__name__)


API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
API_PASSPHRASE = os.getenv("API_PASSPHRASE")

if not API_SECRET:
    raise EnvironmentError("❌ API_SECRET ไม่ถูกโหลดจาก environment variable!")

BASE_URL = 'https://www.okx.com'

print("[DEBUG] API_KEY:", API_KEY)
print("[DEBUG] API_SECRET:", "SET" if API_SECRET else "NOT SET")
print("[DEBUG] API_PASSPHRASE:", API_PASSPHRASE)

def generate_signature(timestamp, method, request_path, body='', api_secret=''):
    assert api_secret, "API_SECRET is not set"
    message = f'{timestamp}{method.upper()}{request_path}{body}'
    mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


# === OKX REQUEST ===
def okx_request(method, path, body_dict=None):
    API_KEY = os.getenv("API_KEY")
    API_SECRET = os.getenv("API_SECRET")
    API_PASSPHRASE = os.getenv("API_PASSPHRASE")

    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    body = json.dumps(body_dict) if body_dict else ''
    headers = {
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': generate_signature(timestamp, method, path, body, API_SECRET),
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

# === GET LOT SIZE ===
def get_lot_size(symbol):
    result = okx_request('GET', f'/api/v5/public/instruments?instType=SWAP&instId={symbol}')
    for item in result.get("data", []):
        if item["instId"] == symbol:
            return float(item["lotSz"])
    return 0.01  # fallback เผื่อ error
# === CLOSE POSITION ก่อนเปิดใหม่ ===
def close_position(symbol, side):
    opposite_side = "short" if side == "buy" else "long"
    close_body = {
        "instId": symbol,
        "tdMode": "cross",
        "side": "sell" if side == "buy" else "buy",  # ปิดฝั่งตรงข้าม
        "ordType": "market",
        "posSide": opposite_side,
        "sz": "9999"  # ปิดทั้งหมด
    }
    response = okx_request("POST", "/api/v5/trade/order", close_body)
    print(f"[DEBUG] Close opposite position → {opposite_side}: {response}")

# === SEND ORDER ===
def send_order_to_okx(symbol, side, percent=25, leverage=10):
    balance = get_balance("USDT")
    price = get_market_price(symbol)
    lot_size = get_lot_size(symbol)

    notional = balance * (percent / 100) * leverage
    raw_size = notional / price
    getcontext().prec = 18  # ความละเอียดของทศนิยม
    lot_size_decimal = Decimal(str(lot_size))
    raw_size_decimal = Decimal(str(raw_size))
    size = (raw_size_decimal / lot_size_decimal).to_integral_value(rounding=ROUND_DOWN) * lot_size_decimal
    size = float(size)
    

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

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("[Webhook] Received:", data)

    action = data.get("action", "").lower()
    symbol = data.get("symbol", "SOL-USDT-SWAP")
    percent = float(data.get("percent", 25))
    leverage = int(data.get("leverage", 10))

    if action in ["buy", "sell"]:
        response = send_order_to_okx(symbol, action, percent, leverage)
        return jsonify({"status": "order_sent", "response": response})
    else:
        return jsonify({"status": "invalid action", "data": data})

# === HOME ROUTE ===
@app.route("/", methods=["GET"])
def home():
    return "✅ Bot is running! Webhook is ready at /webhook"

# === RUN APP ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)
