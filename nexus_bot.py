import requests
import time
import schedule
from datetime import datetime
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT"]
INTERVAL_FAST = "15m"
INTERVAL_SLOW = "1h"

last_signals = {}

def get_klines(symbol, interval, limit=150):
    try:
        url = "https://api.binance.us/api/v3/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        data = r.json()
        if not isinstance(data, list) or len(data) < 50:
            return None
        return {
            "closes":  [float(c[4]) for c in data],
            "highs":   [float(c[2]) for c in data],
            "lows":    [float(c[3]) for c in data],
            "volumes": [float(c[5]) for c in data],
        }
    except Exception as e:
        print(f"eroare date: {e}")
        return None

def calc_rsi(closes, period=14):
    gains  = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
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
    try:
        d = get_klines("BTCUSDT", "1h", 50)
        if not d:
            return "NEUTRAL"
        closes = d["closes"]
        ema20  = calc_ema(closes, 20)
        ema50  = calc_ema(closes, 50)
        price  = closes[-1]
        rsi    = calc_rsi(closes)
        if price > ema20 and ema20 > ema50 and rsi > 52:
            return "BULL"
        elif price < ema20 and ema20 < ema50 and rsi < 48:
            return "BEAR"
        return "NEUTRAL"
    except:
        return "NEUTRAL"

def analyze(symbol, btc_trend):
    d15 = get_klines(symbol, INTERVAL_FAST)
    d1h = get_klines(symbol, INTERVAL_SLOW)
    if not d15 or not d1h:
        return None

    closes15 = d15["closes"]
    closes1h = d1h["closes"]
    highs    = d15["highs"]
    lows     = d15["lows"]
    volumes  = d15["volumes"]
    price    = closes15[-1]

    # Indicatori 15m
    rsi15      = calc_rsi(closes15)
    rsi15_prev = calc_rsi(closes15[:-1])
    ema9       = calc_ema(closes15, 9)
    ema21      = calc_ema(closes15, 21)
    ema200_15  = calc_ema(closes15, min(200, len(closes15)-1))
    e12        = calc_ema(closes15, 12)
    e26        = calc_ema(closes15, 26)
    macd15     = e12 - e26
    macd15p    = calc_ema(closes15[:-1], 12) - calc_ema(closes15[:-1], 26)

    # Indicatori 1h
    rsi1h      = calc_rsi(closes1h)
    rsi1h_prev = calc_rsi(closes1h[:-1])
    e12_1h     = calc_ema(closes1h, 12)
    e26_1h     = calc_ema(closes1h, 26)
    macd1h     = e12_1h - e26_1h
    macd1h_prev = calc_ema(closes1h[:-1], 12) - calc_ema(closes1h[:-1], 26)
    ema200_1h  = calc_ema(closes1h, min(200, len(closes1h)-1))

    # Volum — confirmare obligatorie
    vol_avg = sum(volumes[-20:]) / 20
    vol_ok  = volumes[-1] > vol_avg * 1.3

    # ATR
    atr_raw = sum([highs[i]-lows[i] for i in range(-14, 0)]) / 14
    atr     = max(atr_raw, price * 0.004)

    # ===== CONDITII LONG (stricte) =====
    long_cond = [
        rsi15 < 32,                          # RSI 15m oversold strict
        rsi15 > rsi15_prev,                  # RSI 15m in crestere
        rsi1h < 50,                          # RSI 1h nu e overbought
        rsi1h > rsi1h_prev,                  # RSI 1h in crestere
        price > ema200_15,                   # Pret peste EMA200 pe 15m
        price > ema200_1h,                   # Pret peste EMA200 pe 1h
        macd15 > macd15p,                    # MACD bullish pe 15m
        btc_trend == "BULL",                 # BTC in crestere
    ]

    # ===== CONDITII SHORT (stricte) =====
    short_cond = [
        rsi15 > 68,                          # RSI 15m overbought strict
        rsi15 < rsi15_prev,                  # RSI 15m in scadere
        rsi1h > 50,                          # RSI 1h nu e oversold
        rsi1h < rsi1h_prev,                  # RSI 1h in scadere
        price < ema200_15,                   # Pret sub EMA200 pe 15m
        price < ema200_1h,                   # Pret sub EMA200 pe 1h
        macd15 < macd15p,                    # MACD bearish pe 15m
        btc_trend == "BEAR",                 # BTC in scadere
    ]

    long_score  = sum(long_cond)
    short_score = sum(short_cond)

    # Necesita MINIM 6/8 conditii
    if long_score >= 6 and vol_ok:
        sig, score = "LONG", long_score
    elif short_score >= 6 and vol_ok:
        sig, score = "SHORT", short_score
    else:
        return None

    # Calcul SL/TP cu R/R minim 1:1.5
    if sig == "LONG":
        sl  = round(price - atr * 2, 6)
        tp1 = round(price + atr * 3, 6)   # R/R 1:1.5
        tp2 = round(price + atr * 5, 6)   # R/R 1:2.5
    else:
        sl  = round(price + atr * 2, 6)
        tp1 = round(price - atr * 3, 6)
        tp2 = round(price - atr * 5, 6)

    risk   = round(abs(price - sl) / price * 100, 2)
    reward = round(abs(tp1 - price) / price * 100, 2)
    rr     = round(reward / risk, 1) if risk > 0 else 0

    # Verificare R/R minim 1:1.5
    if rr < 1.4:
        print(f"R/R insuficient ({rr}) — semnal ignorat")
        return None

    # Anti-duplicat 90 minute
    key = f"{symbol}_{sig}"
    now = datetime.now()
    if key in last_signals:
        diff = (now - last_signals[key]).total_seconds() / 60
        if diff < 90:
            print(f"duplicat ignorat ({diff:.0f} min)")
            return None
    last_signals[key] = now

    conf  = min(95, 50 + score * 7)
    trend = "✅ peste EMA200" if price > ema200_15 else "⚠️ sub EMA200"

    return {
        "symbol": symbol, "direction": sig, "price": price,
        "sl": sl, "tp1": tp1, "tp2": tp2,
        "rsi15": round(rsi15, 1), "rsi1h": round(rsi1h, 1),
        "risk": risk, "reward": reward, "rr": rr,
        "conf": conf, "score": score, "trend": trend,
        "btc_trend": btc_trend,
        "time": now.strftime("%H:%M %d.%m.%Y")
    }

def fmt(p):
    if p > 100:
        return f"${p:,.2f}"
    elif p > 1:
        return f"${p:.4f}"
    else:
        return f"${p:.5f}"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print(f"Telegram: {'OK' if r.status_code==200 else r.text}")
    except Exception as e:
        print(f"Eroare Telegram: {e}")

def scan():
    print(f"\nScanare {datetime.now().strftime('%H:%M:%S')}")
    btc_trend = get_btc_trend()
    btc_emoji = "🟢" if btc_trend=="BULL" else "🔴" if btc_trend=="BEAR" else "🟡"
    print(f"  BTC trend: {btc_trend}")

    found = 0
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        sig = analyze(sym, btc_trend)
        if sig:
            e     = "🟢" if sig["direction"]=="LONG" else "🔴"
            arrow = "⬆️" if sig["direction"]=="LONG" else "⬇️"
            print(f"{sig['direction']}! ({sig['score']}/8) RSI15:{sig['rsi15']} RSI1h:{sig['rsi1h']} RR:{sig['rr']}")

            msg  = f"{e} *{sig['direction']} — {sig['symbol']}* {arrow}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"💰 *Entry:* {fmt(sig['price'])}\n"
            msg += f"🛑 *Stop Loss:* {fmt(sig['sl'])} (-{sig['risk']}%)\n"
            msg += f"🎯 *Take Profit 1:* {fmt(sig['tp1'])} (+{sig['reward']}%)\n"
            msg += f"🎯 *Take Profit 2:* {fmt(sig['tp2'])} (+{round(sig['reward']*5/3, 2)}%)\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"📊 RSI 15m: `{sig['rsi15']}` | RSI 1h: `{sig['rsi1h']}`\n"
            msg += f"📈 {sig['trend']}\n"
            msg += f"{btc_emoji} BTC: *{sig['btc_trend']}* | Conf: {sig['conf']}%\n"
            msg += f"📐 R/R: *1:{sig['rr']}* | Condiții: `{sig['score']}/8`\n"
            msg += f"🕐 {sig['time']}\n"
            msg += f"_Tool educational. Nu e sfat financiar._"

            send_telegram(msg)
            found += 1
            time.sleep(1)
        else:
            print("fara semnal")
        time.sleep(0.3)

    print(f"  Total: {found} semnal(e)")

send_telegram(
    f"🤖 *NEXUS Bot v2.0 ACTIV* ✅\n"
    f"• Monede: {', '.join(SYMBOLS)}\n"
    f"• Timeframe: 15m + 1h confirmare\n"
    f"• RSI strict: LONG <32 | SHORT >68\n"
    f"• EMA200 pe ambele TF obligatorie\n"
    f"• R/R minim: 1:1.5\n"
    f"• Condiții necesare: 6/8 + volum\n"
    f"• Anti-duplicate: 90 min\n"
    f"_Calitate peste cantitate..._"
)
scan()
schedule.every(15).minutes.do(scan)
print("Running...")
while True:
    schedule.run_pending()
    time.sleep(1)
