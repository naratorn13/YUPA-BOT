from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import base64
import requests
import json
from datetime import datetime, timezone

app = Flask(__name__)

# === OKX API CONFIG ===
API_KEY = '3f9195c4-0485-4ebf-abc8-161d85857005'
API_SECRET = 'DC9F9093F03F8791D098C5CF80A54921'
API_PASSPHRASE = '13112535DODo.'
BASE_URL = 'https://www.okx.com'

# === SIGNATURE GENERATOR ===
def generate_signature(timestamp, method, request_path, body=''):
    message = f'{timestamp}{method.upper()}{request_path}{body}'
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    d = mac.digest()
    return base64.b64encode(d).decode()

# === SEND REQUEST TO OKX ===
def send_order_to_okx(data):
    print("[⏳] Sending order to OKX:", data)

    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    method = "POST"
    endpoint = "/api/v5/trade/order"

    body_dict = {
        "instId": data["symbol"],
        "tdMode": "isolated",
        "side": data["side"],
        "ordType": "market",
        "sz": str(data["percent"]),
        "lever": str(data["leverage"])
    }
    body = json.dumps(body_dict)
    sign = generate_signature(timestamp, method, endpoint, body)

    headers = {
        "Content-Type": "application/json",
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "x-simulated-trading": "1"  # ใส่ "1" ถ้าเป็น testnet / ลองเอาออกถ้าใช้เงินจริง
    }

    response = requests.post(BASE_URL + endpoint, headers=headers, data=body)

    print("[✅] OKX Response:", response.text)
    return response.text

# === WEBHOOK ROUTE ===
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("[📥] Webhook Received:", data)

    # ส่งไป OKX เลย
    send_order_to_okx(data)

    return jsonify({'status': 'received'}), 200

# === MAIN ===
if __name__ == '__main__':
    app.run(debug=True)
