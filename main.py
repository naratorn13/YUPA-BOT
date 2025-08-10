
# === Standard Library ===
import os
import json
import time
import hmac
import hashlib
import base64
import requests
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, getcontext

# === Third-party ===
from flask import Flask, request, jsonify
from waitress import serve

app = Flask(__name__)

# === ENV ===
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
API_PASSPHRASE = os.getenv("API_PASSPHRASE")
BASE_URL = 'https://www.okx.com'

if not API_KEY or not API_SECRET or not API_PASSPHRASE:
    raise EnvironmentError("❌ Missing API credentials in environment: API_KEY / API_SECRET / API_PASSPHRASE")

# --- Helpers ---
def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

def _sign(ts, method, path, body=''):
    msg = f"{ts}{method.upper()}{path}{body}"
    mac = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def okx_request(method, path, body=None):
    ts = _now_iso()
    payload = json.dumps(body) if body else ''
    headers = {
        'OK-ACCESS-KEY': API_KEY,
        'OK-ACCESS-SIGN': _sign(ts, method, path, payload),
        'OK-ACCESS-TIMESTAMP': ts,
        'OK-ACCESS-PASSPHRASE': API_PASSPHRASE,
        'Content-Type': 'application/json'
    }
    url = BASE_URL + path
    r = requests.request(method, url, headers=headers, data=payload, timeout=15)
    try:
        data = r.json()
    except Exception:
        data = {"code": str(r.status_code), "msg": r.text}
    return data

# --- Account/Market utils ---
def ensure_long_short_mode():
    # Set position mode to long/short (idempotent)
    body = {"posMode": "long_short_mode"}
    res = okx_request("POST", "/api/v5/account/set-position-mode", body)
    return res

def set_leverage(instId, lever=10, mgnMode="cross"):
    body = {"instId": instId, "lever": str(lever), "mgnMode": mgnMode}
    return okx_request("POST", "/api/v5/account/set-leverage", body)

def get_balance(ccy="USDT"):
    res = okx_request("GET", "/api/v5/account/balance")
    details = (res.get("data") or [{}])[0].get("details") or []
    for d in details:
        if d.get("ccy") == ccy:
            # availEq is the available equity in the selected currency
            return float(d.get("availEq", 0.0))
    return 0.0

def get_market_price(instId):
    res = okx_request("GET", f"/api/v5/market/ticker?instId={instId}")
    return float((res.get("data") or [{}])[0].get("last", 0.0))

def get_lot_size(instId):
    res = okx_request("GET", f"/api/v5/public/instruments?instType=SWAP&instId={instId}")
    for it in res.get("data", []):
        if it.get("instId") == instId:
            return float(it.get("lotSz", 0.01))
    return 0.01

def get_open_position_size(instId, pos_side):
    # pos_side: "long" or "short"
    res = okx_request("GET", "/api/v5/account/positions")
    for p in res.get("data", []):
        if p.get("instId") == instId and p.get("posSide") == pos_side:
            # size is contracts, return as float
            try:
                return float(p.get("sz", 0))
            except Exception:
                return 0.0
    return 0.0

# --- Sizing ---
def calc_size_from_percent(instId, percent, lever):
    balance = get_balance("USDT")
    price = get_market_price(instId)
    lot = get_lot_size(instId)

    if balance <= 0 or price <= 0:
        return 0.0, {"balance": balance, "price": price, "lot": lot}

    # notional = balance * percent% * leverage
    notional = balance * (percent / 100.0) * lever
    raw_size = notional / price  # contracts for linear USDT-margined swap

    # round down to lot size
    getcontext().prec = 18
    size = (Decimal(str(raw_size)) / Decimal(str(lot))).to_integral_value(rounding=ROUND_DOWN) * Decimal(str(lot))
    return float(size), {"balance": balance, "price": price, "lot": lot}

# --- Trade primitives ---
def close_position(instId, pos_side, sz):
    # In long/short mode: close LONG => sell with posSide=long; close SHORT => buy with posSide=short
    side = "sell" if pos_side == "long" else "buy"
    body = {
        "instId": instId,
        "tdMode": "cross",
        "side": side,
        "ordType": "market",
        "posSide": pos_side,
        "sz": str(sz)
    }
    res = okx_request("POST", "/api/v5/trade/order", body)
    return res

def open_position(instId, direction, sz):
    # direction: "long" or "short"
    side = "buy" if direction == "long" else "sell"
    body = {
        "instId": instId,
        "tdMode": "cross",
        "side": side,
        "ordType": "market",
        "posSide": direction,  # "long" or "short"
        "sz": str(sz)
    }
    res = okx_request("POST", "/api/v5/trade/order", body)
    return res

# --- Orchestrator ---
def flip_if_needed_and_open(instId, want_direction, percent, lever):
    # 1) Make sure long/short mode and leverage are set (idempotent on OKX)
    ensure_long_short_mode()
    set_leverage(instId, lever=lever, mgnMode="cross")

    # 2) Close opposite side if it exists
    opposite = "short" if want_direction == "long" else "long"
    opp_sz = get_open_position_size(instId, opposite)

    closed = None
    if opp_sz > 0:
        closed = close_position(instId, opposite, opp_sz)

    # 3) Compute fresh size from latest balance
    size, meta = calc_size_from_percent(instId, percent, lever)
    if size <= 0:
        return {
            "ok": False,
            "reason": "SIZE_ZERO",
            "meta": meta,
            "closed": closed
        }

    # 4) Open desired side
    opened = open_position(instId, want_direction, size)
    return {
        "ok": True,
        "meta": meta,
        "closed": closed,
        "opened": opened,
        "size": size,
        "direction": want_direction
    }

# --- API ---
@app.route("/", methods=["GET"])
def health():
    return "✅ OKX Webhook Bot is running. POST /webhook"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    # Expected payload examples:
    # {"action":"long","symbol":"SOL-USDT-SWAP","percent":50,"leverage":10}
    # {"action":"buy","symbol":"SOL-USDT-SWAP"}  # buy==long by default percent=50, leverage=10
    action = (data.get("action") or "").lower()
    instId = data.get("symbol", "SOL-USDT-SWAP")
    percent = float(data.get("percent", 50))
    lever = int(data.get("leverage", 10))

    # Map action to desired direction
    direction = None
    if action in ("long", "buy"):
        direction = "long"
    elif action in ("short", "sell"):
        direction = "short"
    else:
        return jsonify({"ok": False, "error": "Invalid action. Use long/buy or short/sell.", "data": data}), 400

    try:
        result = flip_if_needed_and_open(instId, direction, percent, lever)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)
