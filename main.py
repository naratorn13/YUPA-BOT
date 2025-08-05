from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import base64
import requests
import json
import traceback
from datetime import datetime, timezone
from config import API_KEY, API_SECRET, API_PASSPHRASE, BASE_URL

app = Flask(__name__)

def generate_signature(timestamp, method, request_path, body=''):
    message = f'{timestamp}{method.upper()}{request_path}{body}'
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    d = mac.digest()
    return base64.b64encode(d).decode()

def okx_request(method, path, body_dict=None):
    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    body = json.dumps(body_dict) if body_dict else ''
    headers = {
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }
    response = requests.request(method, BASE_URL + path, headers=headers, data=body)
    return response.json()

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


    balance = get_balance("USDT")

    body = {
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
def set_leverage(symbol):
    data = {
        "instId": symbol.upper(),
        "lever": "10",
        "mgnMode": "isolated"
    }
    return okx_request("POST", "/api/v5/account/set-leverage", data)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        action = data.get("action")
        symbol = data.get("symbol")
        size = data.get("size")

        if not all([action, symbol, size]):
            return jsonify({"status": "error", "msg": "Missing fields"})

        position_mode_res = set_position_mode()
        leverage_res = set_leverage(symbol)
        order_res = send_order(symbol, action, size)

if __name__ == "__main__":
    # ✅ ทดสอบดึง balance ที่นี่ (ตอนนี้ okx_request ถูกประกาศแล้ว)
    status, data = okx_request("GET", "/api/v5/account/balance")
    print(f"Status: {status}")
    print("Response:", data)

    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)

