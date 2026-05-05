import requests
import time
import schedule
from datetime import datetime

TELEGRAM_BOT_TOKEN = "8671954962:AAGY7YKVfnRJCBaW2lYZpMPWVOoFhX7fRs4"
TELEGRAM_CHAT_ID = "7814466236"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT"]
INTERVAL_FAST = "15m"
INTERVAL_SLOW = "1h"

# Memorie semnale anterioare - evita duplicate
last_signals = {}

def get_klines(symbol, interval, limit=100):
    try:
        url = "https://api.binance.us/api/v3/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        data = r.json()
        if not isinstance(data, list) or len(data) < 30:
            return None
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        volumes = [float(c[5]) for c in data]
        return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}
    except Exception as e:
        print(f"eroare: {e}")
        return None

def calc_rsi(closes):
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-14:]) / 14
    al = sum(losses[-14:]) / 14
    if al == 0:
        return 100
    return 100 - (100 / (1 + ag/al))

def calc_ema(closes, p):
    if len(closes) < p:
        return closes[-1]
    e = sum(closes[:p]) / p
    k = 2 / (p + 1)
    for c in closes[p:]:
        e = c * k + e * (1 - k)
    return e

def get_btc_trend():
    """Verifică trendul BTC - returneaza 'BULL', 'BEAR' sau 'NEUTRAL'"""
    try:
        d = get_klines("BTCUSDT", "1h", 50)
        if not d:
            return "NEUTRAL"
        closes = d["closes"]
        ema20 = calc_ema(closes, 20)
        ema50 = calc_ema(closes, 50)
        price = closes[-1]
        rsi = calc_rsi(closes)
        if price > ema20 and ema20 > ema50 and rsi > 50:
            return "BULL"
        elif price < ema20 and ema20 < ema50 and rsi < 50:
            return "BEAR"
        else:
            return "NEUTRAL"
    except:
        return "NEUTRAL"

def analyze(symbol, btc_trend):
    # Analiza pe 15m
    d15 = get_klines(symbol, INTERVAL_FAST)
    if not d15:
        return None
    
    # Analiza pe 1h pentru confirmare
    d1h = get_klines(symbol, INTERVAL_SLOW)
    if not d1h:
        return None

    closes15 = d15["closes"]
    closes1h = d1h["closes"]
    highs = d15["highs"]
    lows = d15["lows"]

    price = closes15[-1]

    # Indicatori 15m
    rsi15 = calc_rsi(closes15)
    rsi15_prev = calc_rsi(closes15[:-1])
    e12_15 = calc_ema(closes15, 12)
    e26_15 = calc_ema(closes15, 26)
    macd15 = e12_15 - e26_15
    macd15_prev = calc_ema(closes15[:-1], 12) - calc_ema(closes15[:-1], 26)

    # Indicatori 1h
    rsi1h = calc_rsi(closes1h)
    e12_1h = calc_ema(closes1h, 12)
    e26_1h = calc_ema(closes1h, 26)
    macd1h = e12_1h - e26_1h

    # EMA 200
    ema200 = calc_ema(closes15, min(200, len(closes15)-1))
    trend = "✅ peste EMA200" if price > ema200 else "⚠️ sub EMA200"

    # LONG conditions
    long_15m = rsi15 < 40 and rsi15 > rsi15_prev and macd15 > macd15_prev
    long_1h = rsi1h < 65
    long_btc = btc_trend in ["BULL", "NEUTRAL"]

    # SHORT conditions  
    short_15m = rsi15 > 60 and rsi15 < rsi15_prev and macd15 < macd15_prev
    short_1h = rsi1h > 35
    short_btc = btc_trend in ["BEAR", "NEUTRAL"]

    if long_15m and long_1h and long_btc:
        sig = "LONG"
    elif short_15m and short_1h and short_btc:
        sig = "SHORT"
    else:
        return None

    # Verifica semnal duplicat - nu trimite acelasi semnal de 2 ori
    key = f"{symbol}_{sig}"
    now = datetime.now()
    if key in last_signals:
        diff = (now - last_signals[key]).total_seconds() / 60
        if diff < 60:  # Nu retrimite acelasi semnal timp de 60 minute
            print(f"semnal duplicat ignorat ({diff:.0f} min)")
            return None
    last_signals[key] = now

    # ATR pentru SL/TP
    atr_raw = sum([highs[i]-lows[i] for i in range(-14, 0)]) / 14
    atr = max(atr_raw, price * 0.003)

    if sig == "LONG":
        sl = round(price - atr * 2, 6)
        tp1 = round(price + atr * 2, 6)
        tp2 = round(price + atr * 4, 6)
        risk_pct = round((price - sl) / price * 100, 2)
        reward_pct = round((tp1 - price) / price * 100, 2)
    else:
        sl = round(price + atr * 2, 6)
        tp1 = round(price - atr * 2, 6)
        tp2 = round(price - atr * 4, 6)
        risk_pct = round((sl - price) / price * 100, 2)
        reward_pct = round((price - tp1) / price * 100, 2)

    rr = round(reward_pct / risk_pct, 1) if risk_pct > 0 else 0

    return {
        "symbol": symbol, "direction": sig, "price": price,
        "sl": sl, "tp1": tp1, "tp2": tp2,
        "rsi15": round(rsi15, 1), "rsi1h": round(rsi1h, 1),
        "risk_pct": risk_pct, "reward_pct": reward_pct,
        "rr": rr, "trend": trend, "btc_trend": btc_trend,
        "time": now.strftime("%H:%M %d.%m.%Y")
    }

def fmt(price):
    if price > 100:
        return f"${price:,.2f}"
    elif price > 1:
        return f"${price:.4f}"
    else:
        return f"${price:.5f}"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print("Telegram OK")
    except Exception as e:
        print(f"Eroare telegram: {e}")

def scan():
    print(f"\nScanare {datetime.now().strftime('%H:%M:%S')}")
    
    # Verifica trendul BTC inainte de orice
    btc_trend = get_btc_trend()
    btc_emoji = "🟢" if btc_trend == "BULL" else "🔴" if btc_trend == "BEAR" else "🟡"
    print(f"  BTC trend: {btc_trend}")

    found = 0
    for sym in SYMBOLS:
        if sym == "BTCUSDT":
            continue  # BTC analizat separat pentru trend
        print(f"  {sym}...", end=" ", flush=True)
        sig = analyze(sym, btc_trend)
        if sig:
            e = "🟢" if sig["direction"] == "LONG" else "🔴"
            arrow = "⬆️" if sig["direction"] == "LONG" else "⬇️"
            print(f"{sig['direction']}! RSI15:{sig['rsi15']} RSI1h:{sig['rsi1h']}")
            
            msg = f"{e} *{sig['direction']} — {sig['symbol']}* {arrow}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"💰 *Entry:* {fmt(sig['price'])}\n"
            msg += f"🛑 *Stop Loss:* {fmt(sig['sl'])} (-{sig['risk_pct']}%)\n"
            msg += f"🎯 *Take Profit 1:* {fmt(sig['tp1'])} (+{sig['reward_pct']}%)\n"
            msg += f"🎯 *Take Profit 2:* {fmt(sig['tp2'])} (+{round(sig['reward_pct']*2, 2)}%)\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"📊 RSI 15m: `{sig['rsi15']}` | RSI 1h: `{sig['rsi1h']}`\n"
            msg += f"📈 {sig['trend']} | R/R: 1:{sig['rr']}\n"
            msg += f"{btc_emoji} BTC Trend: *{sig['btc_trend']}*\n"
            msg += f"🕐 {sig['time']}\n"
            msg += f"_Tool educational. Nu e sfat financiar._"
            
            send_telegram(msg)
            found += 1
            time.sleep(1)
        else:
            print("fara semnal")
        time.sleep(0.3)
    
    # Analizeaza si BTC separat
    print(f"  BTCUSDT...", end=" ", flush=True)
    btc_sig = analyze("BTCUSDT", btc_trend)
    if btc_sig:
        e = "🟢" if btc_sig["direction"] == "LONG" else "🔴"
        arrow = "⬆️" if btc_sig["direction"] == "LONG" else "⬇️"
        print(f"{btc_sig['direction']}!")
        msg = f"{e} *{btc_sig['direction']} — BTCUSDT* {arrow}\n"
        msg += f"━━━━━━━━━━━━━━━━\n"
        msg += f"💰 *Entry:* {fmt(btc_sig['price'])}\n"
        msg += f"🛑 *Stop Loss:* {fmt(btc_sig['sl'])} (-{btc_sig['risk_pct']}%)\n"
        msg += f"🎯 *Take Profit 1:* {fmt(btc_sig['tp1'])} (+{btc_sig['reward_pct']}%)\n"
        msg += f"🎯 *Take Profit 2:* {fmt(btc_sig['tp2'])} (+{round(btc_sig['reward_pct']*2, 2)}%)\n"
        msg += f"━━━━━━━━━━━━━━━━\n"
        msg += f"📊 RSI 15m: `{btc_sig['rsi15']}` | RSI 1h: `{btc_sig['rsi1h']}`\n"
        msg += f"📈 {btc_sig['trend']} | R/R: 1:{btc_sig['rr']}\n"
        msg += f"🕐 {btc_sig['time']}\n"
        msg += f"_Tool educational. Nu e sfat financiar._"
        send_telegram(msg)
        found += 1
    else:
        print("fara semnal")

    print(f"  Total: {found} semnal(e)")

send_telegram(f"🤖 *NEXUS Bot ACTIV* ✅\n• Monede: {', '.join(SYMBOLS)}\n• Timeframe: 15m + 1h confirmare\n• Filtru BTC trend: activ\n• Anti-duplicate: activ\n_Monitorizez pietele..._")
scan()
schedule.every(15).minutes.do(scan)
print("Running...")
while True:
    schedule.run_pending()
    time.sleep(1)
