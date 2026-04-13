cat ~/Downloads/bot/server.py
"""
BYBIT FUTURES BOT - Pour deploiement sur Render
================================================
"""
import json, time, threading, math, random, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime

try:
    from pybit.unified_trading import HTTP as BybitHTTP
    PYBIT_OK = True
except ImportError:
    PYBIT_OK = False

CONFIG = {
    "api_key": os.environ.get("BYBIT_API_KEY", ""),
    "api_secret": os.environ.get("BYBIT_API_SECRET", ""),
    "testnet": False,
    "capital_pct": 10,
    "stop_loss_pct": 3.0,
    "take_profit_pct": 5.0,
    "max_positions": 4,
    "leverage": 3,
    "rsi_low": 40,
    "rsi_high": 60,
    "scan_interval": 15,
    "pairs": [
        "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
        "DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT",
        "LTCUSDT","UNIUSDT","ATOMUSDT","ETCUSDT","APTUSDT",
        "ARBUSDT","OPUSDT","INJUSDT","SUIUSDT","FETUSDT",
        "SEIUSDT","WLDUSDT","TIAUSDT","NEARUSDT","BNXUSDT"
    ],
    "timeframe": "5",
}

STATE = {
    "running": False, "mode": None, "pnl": 0.0, "balance": 0.0,
    "positions": {}, "trades": [], "logs": [], "signals": {},
    "indicators": {}, "wins": 0, "losses": 0,
    "next_scan_in": 0, "last_scan": None, "connected": False, "session": None,
}

def log(level, msg):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    STATE["logs"].insert(0, entry)
    if len(STATE["logs"]) > 500: STATE["logs"] = STATE["logs"][:500]
    print(f"[{entry['time']}] [{level.upper()}] {msg}")

def get_session():
    if not PYBIT_OK: return None
    return BybitHTTP(
        testnet=CONFIG["testnet"],
        api_key=CONFIG["api_key"],
        api_secret=CONFIG["api_secret"],
    )

def get_balance():
    try:
        r = STATE["session"].get_wallet_balance(accountType="UNIFIED", coin="USDT")
        if r["retCode"] == 0:
            for coin in r["result"]["list"][0]["coin"]:
                if coin["coin"] == "USDT":
                    return float(coin["walletBalance"])
        return None
    except Exception as e:
        log("error", f"get_balance: {e}")
        return None

def get_klines(symbol):
    try:
        r = STATE["session"].get_kline(
            category="linear", symbol=symbol,
            interval=CONFIG["timeframe"], limit=100
        )
        if r["retCode"] == 0:
            closes = [float(k[4]) for k in reversed(r["result"]["list"])]
            return closes
        return None
    except Exception as e:
        log("error", f"get_klines {symbol}: {e}")
        return None

def set_leverage(symbol):
    try:
        STATE["session"].set_leverage(
            category="linear", symbol=symbol,
            buyLeverage=str(CONFIG["leverage"]),
            sellLeverage=str(CONFIG["leverage"])
        )
    except: pass

def place_order(symbol, side, qty, sl=None, tp=None):
    try:
        params = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": str(qty),
            "timeInForce": "GoodTillCancel",
        }
        if sl: params["stopLoss"] = str(round(sl, 2))
        if tp: params["takeProfit"] = str(round(tp, 2))
        r = STATE["session"].place_order(**params)
        if r["retCode"] == 0:
            return r["result"]["orderId"]
        log("error", f"place_order {symbol}: {r['retMsg']}")
        return None
    except Exception as e:
        log("error", f"place_order {symbol}: {e}")
        return None

def close_position(symbol, qty, side):
    try:
        close_side = "Sell" if side == "Buy" else "Buy"
        STATE["session"].place_order(
            category="linear", symbol=symbol,
            side=close_side, orderType="Market",
            qty=str(qty), reduceOnly=True,
            timeInForce="GoodTillCancel"
        )
    except Exception as e:
        log("error", f"close_position {symbol}: {e}")

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50
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

def get_indicators(symbol):
    closes = get_klines(symbol)
    if not closes or len(closes) < 21: return None
    ef = calc_ema(closes, 9)
    es = calc_ema(closes, 21)
    return {
        "price": closes[-1], "rsi": calc_rsi(closes),
        "ema_fast": ef, "ema_slow": es,
        "trend": "BULL" if ef > es else "BEAR"
    }

def sim_indicators(symbol):
    base = {"BTCUSDT":73000,"ETHUSDT":3200,"SOLUSDT":82,"BNBUSDT":580,"XRPUSDT":0.62,"DOGEUSDT":0.12,"ADAUSDT":0.44,"AVAXUSDT":35,"LINKUSDT":18,"DOTUSDT":8,"LTCUSDT":85,"UNIUSDT":12,"ATOMUSDT":10,"ETCUSDT":28,"APTUSDT":12,"ARBUSDT":1.2,"OPUSDT":2.5,"INJUSDT":35,"SUIUSDT":1.8,"FETUSDT":2.1,"SEIUSDT":0.6,"WLDUSDT":3.5,"TIAUSDT":8,"NEARUSDT":7,"BNXUSDT":1.5}
    price = base.get(symbol, 10) * (1+(random.random()-0.5)*0.03)
    r = random.random()
    rsi = (20+random.random()*20) if r<0.25 else (60+random.random()*25) if r<0.5 else (38+random.random()*25)
    ef = price*(1+(random.random()-0.5)*0.005)
    es = price*(1+(random.random()-0.5)*0.008)
    return {"price":round(price,4),"rsi":round(rsi,1),"ema_fast":round(ef,4),"ema_slow":round(es,4),"trend":"BULL" if ef>es else "BEAR"}

def compute_signal(ind):
    if not ind: return "HOLD"
    bull = ind["ema_fast"] > ind["ema_slow"]
    if ind["rsi"] < CONFIG["rsi_low"] and bull: return "BUY"
    if ind["rsi"] > CONFIG["rsi_high"] and not bull: return "SELL"
    return "HOLD"

def calc_qty(price):
    if STATE["balance"] <= 0: return 0
    notional = STATE["balance"]*(CONFIG["capital_pct"]/100)*CONFIG["leverage"]
    return math.floor((notional/price)*1000)/1000

def bot_loop():
    log("sys", f"Bot {STATE['mode'].upper()} · {len(CONFIG['pairs'])} paires · scan/{CONFIG['scan_interval']}s · x{CONFIG['leverage']}")
    if STATE["mode"] == "live":
        bal = get_balance()
        if bal is not None:
            STATE["balance"] = bal
            log("sys", f"Balance Bybit: {bal:.2f} USDT")
        else:
            log("warn", "Impossible de recuperer le solde")
            STATE["running"] = False
            return
    else:
        STATE["balance"] = 1000.0
        log("sys", "Balance simulee: 1000 USDT")

    while STATE["running"]:
        STATE["last_scan"] = datetime.now().strftime("%H:%M:%S")
        for symbol in CONFIG["pairs"]:
            if not STATE["running"]: break
            ind = sim_indicators(symbol) if STATE["mode"]=="sim" else get_indicators(symbol)
            if not ind: continue
            STATE["indicators"][symbol] = ind
            signal = compute_signal(ind)
            STATE["signals"][symbol] = signal
            open_count = len(STATE["positions"])

            if STATE["mode"] == "live":
                if signal=="BUY" and symbol not in STATE["positions"] and open_count < CONFIG["max_positions"]:
                    qty = calc_qty(ind["price"])
                    if qty > 0:
                        sl = ind["price"]*(1-CONFIG["stop_loss_pct"]/100)
                        tp = ind["price"]*(1+CONFIG["take_profit_pct"]/100)
                        set_leverage(symbol)
                        oid = place_order(symbol, "Buy", qty, sl, tp)
                        if oid:
                            STATE["positions"][symbol] = {"entry":ind["price"],"qty":qty,"side":"Buy","order_id":oid,"time":datetime.now().strftime("%H:%M:%S")}
                            log("buy", f"LONG {symbol} @ {ind['price']:.4f} · qty {qty} · x{CONFIG['leverage']}")
                elif signal=="SELL" and symbol in STATE["positions"]:
                    pos = STATE["positions"][symbol]
                    close_position(symbol, pos["qty"], pos["side"])
                    pct = (ind["price"]-pos["entry"])/pos["entry"]*100
                    amt = pos["qty"]*pos["entry"]*(pct/100)
                    STATE["pnl"] += amt
                    if amt>=0: STATE["wins"]+=1
                    else: STATE["losses"]+=1
                    STATE["trades"].insert(0,{"symbol":symbol,"pnl":round(amt,4),"pnl_pct":round(pct,2),"reason":"SIGNAL","time":datetime.now().strftime("%H:%M:%S")})
                    del STATE["positions"][symbol]
                    log("buy" if amt>=0 else "sell", f"CLOSE {symbol} @ {ind['price']:.4f} · {amt:+.4f} USDT ({pct:+.2f}%)")
            else:
                if signal=="BUY" and symbol not in STATE["positions"] and open_count < CONFIG["max_positions"]:
                    cap = STATE["balance"]*(CONFIG["capital_pct"]/100)
                    STATE["positions"][symbol] = {"entry":ind["price"],"cap":cap,"time":datetime.now().strftime("%H:%M:%S")}
                    log("buy", f"SIM LONG {symbol} @ {ind['price']:.4f} · {cap:.2f} USDT")
                elif symbol in STATE["positions"]:
                    pos = STATE["positions"][symbol]
                    pct = (ind["price"]-pos["entry"])/pos["entry"]*100
                    if pct<=-CONFIG["stop_loss_pct"] or pct>=CONFIG["take_profit_pct"] or signal=="SELL":
                        reason = "TP" if pct>=CONFIG["take_profit_pct"] else "SL" if pct<=-CONFIG["stop_loss_pct"] else "SIGNAL"
                        amt = pos["cap"]*(pct/100)
                        STATE["pnl"]+=amt; STATE["balance"]+=amt
                        if amt>=0: STATE["wins"]+=1
                        else: STATE["losses"]+=1
                        STATE["trades"].insert(0,{"symbol":symbol,"pnl":round(amt,4),"pnl_pct":round(pct,2),"reason":reason,"time":datetime.now().strftime("%H:%M:%S")})
                        del STATE["positions"][symbol]
                        log("buy" if amt>=0 else "sell", f"SIM CLOSE {symbol} [{reason}] {amt:+.4f} USDT ({pct:+.2f}%)")

        if STATE["mode"]=="live":
            bal = get_balance()
            if bal: STATE["balance"]=bal

        for i in range(CONFIG["scan_interval"]):
            if not STATE["running"]: break
            STATE["next_scan_in"] = CONFIG["scan_interval"]-i
            time.sleep(1)

    log("sys", f"Bot arrete · P&L: {STATE['pnl']:+.4f} USDT")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, f, *a): pass
    def send_json(self, data, s=200):
        b=json.dumps(data).encode()
        self.send_response(s); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def send_html(self, html):
        b=html.encode(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self):
        self.send_response(200); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Methods","GET, POST, OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type"); self.end_headers()
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ["/","index.html"]:
            try:
                with open("dashboard.html","r") as f: self.send_html(f.read())
            except: self.send_html("<h1>Bot en ligne</h1><p>dashboard.html introuvable</p>")
            return
        if path=="/api/state":
            total=STATE["wins"]+STATE["losses"]
            self.send_json({"running":STATE["running"],"mode":STATE["mode"],"pnl":round(STATE["pnl"],4),"balance":round(STATE["balance"],2),"positions":STATE["positions"],"signals":STATE["signals"],"indicators":STATE["indicators"],"logs":STATE["logs"][:50],"wins":STATE["wins"],"losses":STATE["losses"],"trades":STATE["trades"][:20],"win_rate":round(STATE["wins"]/total*100) if total>0 else 0,"trade_count":len(STATE["trades"]),"next_scan_in":STATE["next_scan_in"],"last_scan":STATE["last_scan"],"connected":STATE["connected"]})
            return
        if path=="/health": self.send_json({"status":"ok"}); return
        self.send_json({"error":"not found"},404)
    def do_POST(self):
        path=urlparse(self.path).path
        length=int(self.headers.get("Content-Length",0))
        body=json.loads(self.rfile.read(length)) if length else {}
        if path=="/api/start":
            mode=body.get("mode","sim")
            if not STATE["running"]:
                STATE.update({"running":True,"mode":mode,"pnl":0.0,"wins":0,"losses":0,"trades":[],"positions":{},"signals":{}})
                threading.Thread(target=bot_loop,daemon=True).start()
            self.send_json({"ok":True}); return
        if path=="/api/stop":
            STATE["running"]=False; self.send_json({"ok":True}); return
        if path=="/api/config":
            for k,v in body.items():
                if k in CONFIG: CONFIG[k]=v
            self.send_json({"ok":True}); return
        if path=="/api/test_connection":
            key=body.get("api_key",""); secret=body.get("api_secret","")
            testnet=body.get("testnet",False)
            CONFIG["api_key"]=key; CONFIG["api_secret"]=secret; CONFIG["testnet"]=testnet
            if not PYBIT_OK: self.send_json({"ok":False,"msg":"pybit non installe"}); return
            if not key or not secret: self.send_json({"ok":False,"msg":"Cles manquantes"}); return
            try:
                session = BybitHTTP(testnet=testnet, api_key=key, api_secret=secret)
                STATE["session"] = session
                r = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
                if r["retCode"] == 0:
                    bal = 0
                    for coin in r["result"]["list"][0]["coin"]:
                        if coin["coin"] == "USDT":
                            bal = float(coin["walletBalance"])
                    STATE["connected"]=True; STATE["balance"]=bal
                    log("sys", f"Connexion Bybit OK · Balance: {bal:.2f} USDT")
                    self.send_json({"ok":True,"balance":bal})
                else:
                    STATE["connected"]=False
                    log("warn", f"Bybit erreur: {r['retMsg']}")
                    self.send_json({"ok":False,"msg":r["retMsg"]})
            except Exception as e:
                STATE["connected"]=False
                log("warn", f"Connexion echouee: {e}")
                self.send_json({"ok":False,"msg":str(e)})
            return
        self.send_json({"error":"not found"},404)

if __name__=="__main__":
    PORT = int(os.environ.get("PORT", 8765))
    if not PYBIT_OK: print("⚠ pip install pybit")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Bot demarre sur port {PORT}")
    try: server.serve_forever()
    except KeyboardInterrupt: print("Arrete.")
      
