from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import base64
import requests
import json
import os
from datetime import datetime, timezone

app = Flask(__name__)

# === OKX API CONFIG ===
API_KEY = os.environ.get('API_KEY')
API_SECRET = os.environ.get('API_SECRET')
API_PASSPHRASE = os.environ.get('API_PASSPHRASE')
BASE_URL = os.environ.get('BASE_URL')

# === SIGNATURE GENERATOR ===
def generate_signature(timestamp, method, request_path, body=''):
    message = f'{timestamp}{method.upper()}{request_path}{body}'
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    d = mac.digest()
    return base64.b64encode(d).decode()

# === SEND REQUEST TO OKX ===
def okx_request(method, path, body_dict=None):
    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    body = json.dumps(body_dict) if body_dict else ''
    sign = generate_signature(timestamp, method, path, body)

    headers = {
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': sign,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }

    url = f'{BASE_URL}{path}'
    response = requests.request(method, url, headers=headers, data=body)
    return response.json()

# === WEBHOOK ROUTE ===
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("Webhook received:", data)

    try:
        symbol = data['symbol']
        side = data['side']
        size = data['size']
        order_type = data.get('type', 'market')

        order_data = {
            "instId": symbol,
            "tdMode": "isolated",
            "side": side,
            "ordType": order_type,
            "sz": size
        }

        result = okx_request("POST", "/api/v5/trade/order", order_data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# === HEALTH CHECK ===
@app.route('/', methods=['GET'])
def index():
    return "🚀 OKX Webhook Bot is running!"

if __name__ == '__main__':
    from waitress import serve
    serve(app, host='0.0.0.0', port=8000)

