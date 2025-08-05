from flask import Flask, request, jsonify
import time
import hmac
import hashlib
import base64
import requests
import json
import traceback
from datetime import datetime, timezone
from settings import API_KEY, API_SECRET, API_PASSPHRASE, BASE_URL

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
        'OK-ACCESS-SIGN': generate_signature(timestamp, method, path, body),
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }
    response = requests.request(method, BASE_URL + path, headers=headers, data=body)
    return response.json()

def send_order(symbol, action, size):
    inst_id = symbol.upper()
    side = 'buy' if action == 'buy' else 'sell'
    order_data = {
        "instId": inst_id,
        "tdMode": "isolated",
        "side": side,
        "ordType": "market",
        "sz": str(size)
    }
    return okx_request('POST', '/api/v5/trade/order', order_data)

def set_position_mode():
    data = {"posMode": "long_short_mode"}
    return okx_request("POST", "/api/v5/account/set-position-mode", data)

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

        return jsonify({
            "status": "success",
            "position_mode": position_mode_res,
            "leverage": leverage_res,
            "order": order_res
        })

    except Exception as e:
        print("ERROR:", str(e))
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)
