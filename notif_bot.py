"""
BYBIT SIGNAL BOT - Telegram Notifications
==========================================
Analyse les marches toutes les 30s et envoie des alertes Telegram
"""
import time, math, random, os, json
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import URLError

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8626800405:AAG7rECvXAdppW5eFpsUDU-oGxqX6JC3WsQ")
CHAT_ID = os.environ.get("CHAT_ID", "1116990657")

CONFIG = {
    "scan_interval": 30,
    "rsi_low": 35,
    "rsi_high": 65,
    "stop_loss_pct": 3.0,
    "take_profit_pct": 5.0,
    "leverage": 3,
    "min_confidence": 60,
    "pairs": [
        "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
        "DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT",
        "LTCUSDT","UNIUSDT","ATOMUSDT","APTUSDT","ARBUSDT",
        "OPUSDT","INJUSDT","SUIUSDT","FETUSDT","NEARUSDT",
        "SEIUSDT","WLDUSDT","TIAUSDT","BNXUSDT","ETCUSDT"
    ],
}

# ── COOLDOWN: evite d'envoyer le meme signal 2 fois ───────────────────────────
last_signals = {}  # {symbol: (signal, timestamp)}
COOLDOWN_MINUTES = 30

# ── TELEGRAM ──────────────────────────────────────────────────────────────────
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
        print(f"[TELEGRAM] Message envoyé")
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

# ── PRIX REELS VIA BYBIT API PUBLIQUE ─────────────────────────────────────────
def get_klines(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=5&limit=100"
        req = Request(url)
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        if data["retCode"] == 0:
            closes = [float(k[4]) for k in reversed(data["result"]["list"])]
            return closes
        return None
    except Exception as e:
        print(f"[KLINES ERROR] {symbol}: {e}")
        return None

def get_ticker(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}"
        req = Request(url)
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        if data["retCode"] == 0:
            items = data["result"]["list"]
            if items:
                return float(items[0]["lastPrice"]), float(items[0]["price24hPcnt"]) * 100
        return None, None
    except:
        return None, None

# ── INDICATEURS ───────────────────────────────────────────────────────────────
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    deltas = [closes[i]-closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    ag = sum(gains[:period])/period
    al = sum(losses[:period])/period
    for i in range(period, len(gains)):
        ag = (ag*(period-1)+gains[i])/period
        al = (al*(period-1)+losses[i])/period
    if al == 0: return 100
    return round(100-(100/(1+ag/al)), 2)

def calc_ema(closes, period):
    if len(closes) < period: return closes[-1] if closes else 0
    k = 2/(period+1)
    ema = sum(closes[:period])/period
    for p in closes[period:]: ema = p*k + ema*(1-k)
    return round(ema, 4)

def calc_confidence(rsi, signal):
    if signal == "BUY":
        if rsi < 20: return 90
        if rsi < 25: return 80
        if rsi < 30: return 75
        if rsi < 35: return 65
        return 55
    else:
        if rsi > 80: return 90
        if rsi > 75: return 80
        if rsi > 70: return 75
        if rsi > 65: return 65
        return 55

def analyze(symbol):
    closes = get_klines(symbol)
    if not closes or len(closes) < 21:
        return None

    price = closes[-1]
    rsi = calc_rsi(closes)
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    bull = ema9 > ema21

    signal = None
    if rsi < CONFIG["rsi_low"] and bull:
        signal = "BUY"
    elif rsi > CONFIG["rsi_high"] and not bull:
        signal = "SELL"

    if not signal:
        return None

    confidence = calc_confidence(rsi, signal)
    if confidence < CONFIG["min_confidence"]:
        return None

    # Cooldown check
    now = time.time()
    if symbol in last_signals:
        last_sig, last_time = last_signals[symbol]
        if last_sig == signal and (now - last_time) < COOLDOWN_MINUTES * 60:
            return None

    last_signals[symbol] = (signal, now)

    sl = price * (1 - CONFIG["stop_loss_pct"]/100)
    tp = price * (1 + CONFIG["take_profit_pct"]/100)

    # Format price
    if price > 100:
        price_str = f"${price:,.2f}"
        sl_str = f"${sl:,.2f}"
        tp_str = f"${tp:,.2f}"
    elif price > 1:
        price_str = f"${price:.4f}"
        sl_str = f"${sl:.4f}"
        tp_str = f"${tp:.4f}"
    else:
        price_str = f"${price:.6f}"
        sl_str = f"${sl:.6f}"
        tp_str = f"${tp:.6f}"

    trend = "📈 HAUSSIER" if bull else "📉 BAISSIER"
    pair_name = symbol.replace("USDT", "/USDT")

    if signal == "BUY":
        msg = f"""🟢 <b>SIGNAL ACHAT — {pair_name}</b>

💰 <b>Prix entrée :</b> {price_str}
📉 <b>Stop Loss :</b> {sl_str} (-{CONFIG['stop_loss_pct']}%)
🎯 <b>Take Profit :</b> {tp_str} (+{CONFIG['take_profit_pct']}%)

📊 <b>RSI :</b> {rsi} (survente)
📈 <b>Tendance EMA :</b> {trend}
⚡ <b>Levier suggéré :</b> x{CONFIG['leverage']}
🔥 <b>Confiance :</b> {confidence}%

⏰ {datetime.now().strftime('%H:%M:%S')}
⚠️ Pas un conseil financier — décide toi-même"""
    else:
        msg = f"""🔴 <b>SIGNAL VENTE — {pair_name}</b>

💰 <b>Prix entrée :</b> {price_str}
📉 <b>Stop Loss :</b> {tp_str} (+{CONFIG['stop_loss_pct']}%)
🎯 <b>Take Profit :</b> {sl_str} (-{CONFIG['take_profit_pct']}%)

📊 <b>RSI :</b> {rsi} (surachat)
📉 <b>Tendance EMA :</b> {trend}
⚡ <b>Levier suggéré :</b> x{CONFIG['leverage']}
🔥 <b>Confiance :</b> {confidence}%

⏰ {datetime.now().strftime('%H:%M:%S')}
⚠️ Pas un conseil financier — décide toi-même"""

    return {"signal": signal, "symbol": symbol, "price": price, "rsi": rsi, "confidence": confidence, "msg": msg}

# ── BOUCLE PRINCIPALE ─────────────────────────────────────────────────────────
def main():
    print(f"[BOT] Démarrage — {len(CONFIG['pairs'])} paires · scan toutes les {CONFIG['scan_interval']}s")

    # Message de démarrage
    send_telegram(f"""🤖 <b>TradeBot démarré !</b>

📡 Surveillance de {len(CONFIG['pairs'])} paires crypto
⏱ Scan toutes les {CONFIG['scan_interval']} secondes
📊 Stratégie : RSI({CONFIG['rsi_low']}/{CONFIG['rsi_high']}) + EMA(9/21)
🎯 TP : +{CONFIG['take_profit_pct']}% | SL : -{CONFIG['stop_loss_pct']}%

Tu recevras des alertes dès qu'un signal fort est détecté !""")

    scan_count = 0

    while True:
        scan_count += 1
        signals_found = 0
        print(f"[SCAN #{scan_count}] {datetime.now().strftime('%H:%M:%S')} — analyse {len(CONFIG['pairs'])} paires...")

        for symbol in CONFIG["pairs"]:
            try:
                result = analyze(symbol)
                if result:
                    signals_found += 1
                    print(f"[SIGNAL] {result['signal']} {symbol} @ {result['price']:.4f} RSI:{result['rsi']} conf:{result['confidence']}%")
                    send_telegram(result["msg"])
                    time.sleep(1)  # Petit délai entre les messages
            except Exception as e:
                print(f"[ERROR] {symbol}: {e}")

        print(f"[SCAN #{scan_count}] Terminé — {signals_found} signal(s) trouvé(s)")

        # Résumé toutes les heures
        if scan_count % (3600 // CONFIG["scan_interval"]) == 0:
            send_telegram(f"""📊 <b>Résumé heure</b>

🔍 {scan_count} scans effectués
📡 {len(CONFIG['pairs'])} paires surveillées
⏰ {datetime.now().strftime('%H:%M:%S')}

Bot toujours actif ✅""")

        time.sleep(CONFIG["scan_interval"])

if __name__ == "__main__":
    main()
