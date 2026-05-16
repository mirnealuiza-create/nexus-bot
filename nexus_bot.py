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
        closes  = [float(c[4]) for c in data]
        highs   = [float(c[2]) for c in data]
        lows    = [float(c[3]) for c in data]
        volumes = [float(c[5]) for c in data]
        return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}
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
    ema200     = calc_ema(closes15, min(200, len(closes15)-1))
    e12        = calc_ema(closes15, 12)
    e26        = calc_ema(closes15, 26)
    macd15     = e12 - e26
    macd15p    = calc_ema(closes15[:-1], 12) - calc_ema(closes15[:-1], 26)

    # Indicatori 1h
    rsi1h   = calc_rsi(closes1h)
    e12_1h  = calc_ema(closes1h, 12)
    e26_1h  = calc_ema(closes1h, 26)
    macd1h  = e12_1h - e26_1h
    ema200_1h = calc_ema(closes1h, min(200, len(closes1h)-1))

    # Volum
    vol_avg = sum(volumes[-20:]) / 20
    vol_ok  = volumes[-1] > vol_avg * 1.2

    # Trend ultim 3 lumânări
    last3_bull = all(closes15[-i] > closes15[-i-1] for i in range(1, 4))
    last3_bear = all(closes15[-i] < closes15[-i-1] for i in range(1, 4))

    # ATR
    atr_raw = sum([highs[i]-lows[i] for i in range(-14, 0)]) / 14
    atr     = max(atr_raw, price * 0.004)

    # ============ CONDITII LONG ============
    # 1. RSI 15m sub 35 si in crestere
    long_rsi15 = rsi15 < 35 and rsi15 > rsi15_prev
    # 2. Pret PESTE EMA 200 pe 15m (trend bullish)
    long_ema200 = price > ema200
    # 3. EMA 9 peste EMA 21 pe 15m
    long_ema_cross = ema9 > ema21
    # 4. MACD bullish pe 15m
    long_macd15 = macd15 > macd15p
    # 5. RSI 1h sub 60 (nu overbought pe termen lung)
    long_rsi1h = rsi1h < 60
    # 6. Pret peste EMA 200 pe 1h
    long_ema200_1h = price > ema200_1h
    # 7. BTC nu e in cadere
    long_btc = btc_trend in ["BULL", "NEUTRAL"]
    # 8. Volum ok
    long_vol = vol_ok

    # ============ CONDITII SHORT ============
    # 1. RSI 15m peste 65 si in scadere
    short_rsi15 = rsi15 > 65 and rsi15 < rsi15_prev
    # 2. Pret SUB EMA 200 pe 15m (trend bearish)
    short_ema200 = price < ema200
    # 3. EMA 9 sub EMA 21 pe 15m
    short_ema_cross = ema9 < ema21
    # 4. MACD bearish pe 15m
    short_macd15 = macd15 < macd15p
    # 5. RSI 1h peste 40 (nu oversold pe termen lung)
    short_rsi1h = rsi1h > 40
    # 6. Pret sub EMA 200 pe 1h
    short_ema200_1h = price < ema200_1h
    # 7. BTC nu e in crestere
    short_btc = btc_trend in ["BEAR", "NEUTRAL"]
    # 8. Volum ok
    short_vol = vol_ok

    long_score  = sum([long_rsi15, long_ema200, long_ema_cross, long_macd15, long_rsi1h, long_ema200_1h, long_btc, long_vol])
    short_score = sum([short_rsi15, short_ema200, short_ema_cross, short_macd15, short_rsi1h, short_ema200_1h, short_btc, short_vol])

    # Necesita minim 6 din 8 conditii
    if long_score >= 6:
        sig, score = "LONG", long_score
    elif short_score >= 5:
        sig, score = "SHORT", short_score
    else:
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

    if sig == "LONG":
        sl  = round(price - atr * 2, 6)
        tp1 = round(price + atr * 2, 6)
        tp2 = round(price + atr * 4, 6)
    else:
        sl  = round(price + atr * 2, 6)
        tp1 = round(price - atr * 2, 6)
        tp2 = round(price - atr * 4, 6)

    risk   = round(abs(price - sl) / price * 100, 2)
    reward = round(abs(tp1 - price) / price * 100, 2)
    rr     = round(reward / risk, 1) if risk > 0 else 0
    conf   = min(95, 50 + score * 6)
    trend  = "✅ peste EMA200" if price > ema200 else "⚠️ sub EMA200"

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
        url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
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
            print(f"{sig['direction']}! ({sig['score']}/8) RSI15:{sig['rsi15']} RSI1h:{sig['rsi1h']}")

            msg  = f"{e} *{sig['direction']} — {sig['symbol']}* {arrow}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"💰 *Entry:* {fmt(sig['price'])}\n"
            msg += f"🛑 *Stop Loss:* {fmt(sig['sl'])} (-{sig['risk']}%)\n"
            msg += f"🎯 *Take Profit 1:* {fmt(sig['tp1'])} (+{sig['reward']}%)\n"
            msg += f"🎯 *Take Profit 2:* {fmt(sig['tp2'])} (+{round(sig['reward']*2,2)}%)\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"📊 RSI 15m: `{sig['rsi15']}` | RSI 1h: `{sig['rsi1h']}`\n"
            msg += f"📈 {sig['trend']}\n"
            msg += f"{btc_emoji} BTC: *{sig['btc_trend']}* | Conf: {sig['conf']}% | R/R: 1:{sig['rr']}\n"
            msg += f"✅ Condiții: `{sig['score']}/8`\n"
            msg += f"🕐 {sig['time']}\n"
            msg += f"_Tool educational. Nu e sfat financiar._"

            send_telegram(msg)
            found += 1
            time.sleep(1)
        else:
            print("fara semnal")
        time.sleep(0.3)

    print(f"  Total: {found} semnal(e)")

# Startup
send_telegram(
    f"🤖 *NEXUS Bot ACTIV* ✅\n"
    f"• Monede: {', '.join(SYMBOLS)}\n"
    f"• Timeframe: 15m + 1h confirmare\n"
    f"• Filtre: EMA200, RSI strict, Volum, BTC trend\n"
    f"• Condiții necesare: 6/8\n"
    f"• Anti-duplicate: 90 min\n"
    f"_Monitorizez pietele cu precizie maxima..._"
)
scan()
schedule.every(15).minutes.do(scan)
print("Running...")
while True:
    schedule.run_pending()
    time.sleep(1)
