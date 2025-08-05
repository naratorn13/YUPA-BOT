from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import base64
import requests
import json
from datetime import datetime, timezone

app = Flask(__name__)

API_KEY = "d3d445c4-bf8c-4122-88d0-f6db7dfaf931"
API_SECRET = "E801F1565A76E5C2D22B9B9294E8BA75"
API_PASSPHRASE = "13112535!DOdo"
BASE_URL = "https://www.okx.com"

def generate_signature(timestamp, method, request_path, body=''):
    message = f'{timestamp}{method.upper()}{request_path}{body}'
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    d = mac.digest()
    return base64.b64encode(d).decode()

# === OKX REQUEST ===
def okx_request(method, path, body_dict=None):
    from datetime import timezone
    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    body = json.dumps(body_dict) if body_dict else ''
    signature = generate_signature(timestamp, method, path, body)

    headers = {
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }

    url = BASE_URL + path

    # ✅✅✅ เพิ่มบรรทัด debug ตรงนี้เลย
    print("\n📤 [OKX REQUEST]")
    print("→ Method:", method)
    print("→ URL:", url)
    print("→ Headers:", {k: (v if k != 'OK-ACCESS-KEY' else v[:6] + '...') for k, v in headers.items()})
    print("→ Body:", body)

    response = requests.request(method, url, headers=headers, data=body)

    print("📥 [OKX RESPONSE]")
    print("→ Status Code:", response.status_code)
    print("→ Response Body:", response.text)
    print("------------------------------------------------------")

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
@app.route("/order", methods=["POST"])
def place_order():
    try:
        data = request.json
        result = send_order_to_okx(data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# === RUN APP ===
from waitress import serve
import os

if __name__ == "__main__":
    # ✅ ทดสอบดึง balance ที่นี่ (ตอนนี้ okx_request ถูกประกาศแล้ว)
    status, data = okx_request("GET", "/api/v5/account/balance")
    print(f"Status: {status}")
    print("Response:", data)

    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)

