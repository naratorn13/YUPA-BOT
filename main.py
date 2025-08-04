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

import os

API_KEY = os.environ.get("OKX_API_KEY") or "a056674a-3669-4cb6-9de2-5e217fe15d5f"
API_SECRET = os.environ.get("OKX_API_SECRET") or "YD16E1DC09230BFC2EB8B4047BD8164ADE"
API_PASSPHRASE = os.environ.get("OKX_API_PASSPHRASE") or "13112535DOdo.ee"

BASE_URL = 'https://www.okx.com'
print("✅ DEBUG ENV LOADED:", API_KEY, API_SECRET, API_PASSPHRASE)

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
    data_list = result.get("data", [])
    if not data_list:
        print("❌ [get_balance] No data in balance response")
        return 0.0

    for item in data_list[0].get("details", []):
        if item.get("ccy") == token:
            return float(item.get("availEq"))
    return 0.0


# === GET MARKET PRICE ===
def get_market_price(symbol):
    result = okx_request('GET', f'/api/v5/market/ticker?instId={symbol}')
    data_list = result.get("data", [])
    if not data_list:
        print("❌ [get_market_price] No data in ticker response")
        return 0.0
    return float(data_list[0].get("last", 0))


# === SEND ORDER ===
def send_order_to_okx(data):
    symbol = data.get("symbol")
    side = data.get("side")
    percent = data.get("percent", 25)
    leverage = data.get("leverage", 10)

    print(f"🚀 Preparing to send order {side.upper()} {percent}% of balance on {symbol} with {leverage}x")

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

    print("✅ Order body ready, sending to OKX...")

    try:
        response = okx_request("POST", "/api/v5/trade/order", body)
        print(f"✅ Order sent! Response: {response}")
        return response
    except Exception as e:
        print(f"❌ Error while sending order: {str(e)}")
        return None


# === HOME ===
@app.route("/")
def home():
    return "Bot is running!"
# === ENV CHECK ===
@app.route("/envcheck")
def env_check():
    return jsonify({
        "API_KEY": API_KEY,
        "API_SECRET": API_SECRET,
        "API_PASSPHRASE": API_PASSPHRASE,
        "BASE_URL": BASE_URL
    })

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook_handler():
    data = request.get_json()
    print(f"📩 Webhook received: {data}")

    try:
        symbol = data.get("symbol")
        side = data.get("side")
        strategy = data.get("strategy", "N/A")
        comment = data.get("comment", "")
        timestamp = data.get("timestamp")

        print(f"📊 Strategy: {strategy}, Timestamp: {timestamp}, Comment: {comment}")

        send_order_to_okx(data)

        return jsonify({"status": "success", "message": "Order sent"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# === RUN APP ===
from waitress import serve
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)

@app.route("/envcheck")
def env_check():
    return jsonify({
        "API_KEY": API_KEY,
        "API_SECRET": API_SECRET,
        "API_PASSPHRASE": API_PASSPHRASE,
        "BASE_URL": BASE_URL
    })
