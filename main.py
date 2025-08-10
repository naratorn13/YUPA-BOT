
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

def okx_request(method, path, body=None, timeout=15):
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
    r = requests.request(method, url, headers=headers, data=payload, timeout=timeout)
    try:
        data = r.json()
    except Exception:
        data = {"code": str(r.status_code), "msg": r.text}
    return data

# --- Account/Market utils ---
def get_pos_mode():
    res = okx_request("GET", "/api/v5/account/config")
    try:
        return (res.get("data") or [{}])[0].get("posMode")  # 'long_short_mode' or 'net_mode'
    except Exception:
        return None

def ensure_long_short_mode():
    # Set position mode to long/short (idempotent) — NOTE: OKX จะตั้งค่าไม่ได้ถ้ามีโพสิชันค้างอยู่
    current = get_pos_mode()
    if current == "long_short_mode":
        return {"ok": True, "posMode": current, "skipped": True}
    body = {"posMode": "long_short_mode"}
    res = okx_request("POST", "/api/v5/account/set-position-mode", body)
    res["posMode_before"] = current
    return res

def set_leverage(instId, lever=10, mgnMode="cross"):
    body = {"instId": instId, "lever": str(lever), "mgnMode": mgnMode}
    return okx_request("POST", "/api/v5/account/set-leverage", body)

def get_balance(ccy="USDT"):
    res = okx_request("GET", "/api/v5/account/balance")
    details = (res.get("data") or [{}])[0].get("details") or []
    for d in details:
        if d.get("ccy") == ccy:
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

def list_positions(instId=None):
    res = okx_request("GET", "/api/v5/account/positions")
    data = res.get("data", [])
    if instId:
        data = [p for p in data if p.get("instId") == instId]
    return data

def get_open_position_size(instId, pos_side):
    # pos_side: "long" or "short"
    for p in list_positions(instId):
        if p.get("posSide") == pos_side:
            try:
                return float(p.get("pos", p.get("sz", 0)))  # fallback to 'pos' if available
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
def order_market(instId, side, posSide, sz, reduce_only=False):
    body = {
        "instId": instId,
        "tdMode": "cross",
        "side": side,              # 'buy' or 'sell'
        "ordType": "market",
        "sz": str(sz)
    }
    if posSide:
        body["posSide"] = posSide  # 'long' or 'short'
    if reduce_only:
        body["reduceOnly"] = "true"
    return okx_request("POST", "/api/v5/trade/order", body)

def close_position_whole(instId, pos_side):
    # ใช้ endpoint เฉพาะเพื่อปิดทั้งโพสิชัน — ไม่ต้องระบุขนาด
    body = {
        "instId": instId,
        "mgnMode": "cross",
        "posSide": pos_side
    }
    res = okx_request("POST", "/api/v5/trade/close-position", body)
    return res

def close_position_safe(instId, pos_side, sz):
    # 1) ลองใช้ close-position ทั้งโพสิชันก่อน
    res1 = close_position_whole(instId, pos_side)
    code = str(res1.get("code", ""))
    if code == "0":
        return {"method": "close-position", "resp": res1}

    # 2) ถ้าปิดไม่สำเร็จ ใช้ market order แบบ reduceOnly ปิดให้หมด
    side = "sell" if pos_side == "long" else "buy"
    res2 = order_market(instId, side=side, posSide=pos_side, sz=sz, reduce_only=True)
    return {"method": "reduceOnly", "resp": res2}

def open_position(instId, direction, sz):
    side = "buy" if direction == "long" else "sell"
    return order_market(instId, side=side, posSide=direction, sz=sz, reduce_only=False)

# --- Orchestrator ---
def wait_until_closed(instId, pos_side, timeout_sec=2.0):
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        time.sleep(0.2)
        if get_open_position_size(instId, pos_side) <= 0:
            return True
    return False

def flip_if_needed_and_open(instId, want_direction, percent, lever):
    # Read-only check mode (อย่าพยายามเปลี่ยนถ้ายังมีโพสิชันค้างอยู่)
    pos_mode = get_pos_mode()

    # 1) Set leverage (idempotent)
    set_leverage(instId, lever=lever, mgnMode="cross")

    # 2) Close opposite side if exists
    opposite = "short" if want_direction == "long" else "long"
    opp_sz = get_open_position_size(instId, opposite)

    closed = None
    if opp_sz > 0:
        closed = close_position_safe(instId, opposite, opp_sz)
        # รอจนกว่าปิดจริง
        wait_until_closed(instId, opposite, timeout_sec=3.0)

    # 3) Compute fresh size from latest balance
    size, meta = calc_size_from_percent(instId, percent, lever)
    if size <= 0:
        return {
            "ok": False,
            "reason": "SIZE_ZERO",
            "meta": meta,
            "posMode": pos_mode,
            "positions": list_positions(instId),
            "closed": closed
        }

    # 4) Open desired side
    opened = open_position(instId, want_direction, size)
    return {
        "ok": True,
        "meta": meta,
        "posMode": pos_mode,
        "positions": list_positions(instId),
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
    # {"action":"long","symbol":"SOL-USDT-SWAP","percent":50,"leverage":10}
    action = (data.get("action") or "").lower()
    instId = data.get("symbol", "SOL-USDT-SWAP")
    percent = float(data.get("percent", 50))
    lever = int(data.get("leverage", 10))

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
