import requests
import time
import schedule
from datetime import datetime
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT"]
INTERVAL = "1h"

last_signals = {}
btc_trend = "neutral"

def get_klines(symbol, interval=INTERVAL, limit=100):
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

def calc_rsi_series(closes, period=14):
    rsi_values = []
    for i in range(period + 1, len(closes) + 1):
        rsi_values.append(calc_rsi(closes[:i], period))
    return rsi_values

def calc_ema(closes, p):
    if len(closes) < p:
        return closes[-1]
    e = sum(closes[:p]) / p
    k = 2 / (p + 1)
    for c in closes[p:]:
        e = c * k + e * (1 - k)
    return e

def find_swings(data, lookback=5):
    highs = data["highs"]
    lows  = data["lows"]
    swing_highs = []
    swing_lows  = []
    for i in range(lookback, len(highs) - lookback):
        if highs[i] == max(highs[i-lookback:i+lookback+1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i-lookback:i+lookback+1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows

def calc_fibonacci_levels(high, low):
    diff = high - low
    return {
        "0.236": high - diff * 0.236,
        "0.382": high - diff * 0.382,
        "0.500": high - diff * 0.500,
        "0.618": high - diff * 0.618,
        "0.786": high - diff * 0.786,
    }

def check_rsi_divergence(closes, lows, highs, rsi_series, lookback=10):
    if len(rsi_series) < lookback + 5:
        return None

    recent_lows  = lows[-lookback:]
    recent_highs = highs[-lookback:]
    recent_rsi   = rsi_series[-lookback:]

    min1_idx = recent_lows.index(min(recent_lows[:lookback//2]))
    min2_idx = lookback//2 + recent_lows[lookback//2:].index(min(recent_lows[lookback//2:]))
    price_low1 = recent_lows[min1_idx]
    price_low2 = recent_lows[min2_idx]
    rsi_low1   = recent_rsi[min1_idx]
    rsi_low2   = recent_rsi[min2_idx]

    max1_idx = recent_highs.index(max(recent_highs[:lookback//2]))
    max2_idx = lookback//2 + recent_highs[lookback//2:].index(max(recent_highs[lookback//2:]))
    price_high1 = recent_highs[max1_idx]
    price_high2 = recent_highs[max2_idx]
    rsi_high1   = recent_rsi[max1_idx]
    rsi_high2   = recent_rsi[max2_idx]

    if price_low2 < price_low1 * 0.998 and rsi_low2 > rsi_low1 + 2:
        strength = round(rsi_low2 - rsi_low1, 1)
        return {"type": "BULLISH", "strength": strength,
                "rsi_low1": round(rsi_low1, 1), "rsi_low2": round(rsi_low2, 1)}

    if price_high2 > price_high1 * 1.002 and rsi_high2 < rsi_high1 - 2:
        strength = round(rsi_high1 - rsi_high2, 1)
        return {"type": "BEARISH", "strength": strength,
                "rsi_high1": round(rsi_high1, 1), "rsi_high2": round(rsi_high2, 1)}

    return None

def check_fibonacci_zone(price, swing_highs, swing_lows, tolerance=0.01):
    if len(swing_highs) < 1 or len(swing_lows) < 1:
        return None

    last_high = swing_highs[-1][1]
    last_low  = swing_lows[-1][1]

    # LONG — retragere bullish (de la high la low)
    if last_high > last_low:
        fibs = calc_fibonacci_levels(last_high, last_low)
        for level_name in ["0.618", "0.500", "0.382"]:
            fib_price = fibs[level_name]
            if abs(price - fib_price) / price < tolerance:
                return {"level": level_name, "direction": "LONG",
                        "fib_price": fib_price, "swing_high": last_high, "swing_low": last_low}

    # SHORT — retragere bearish (de la low la high)
    fibs_up = {
        "0.382": last_low + (last_high - last_low) * 0.382,
        "0.500": last_low + (last_high - last_low) * 0.500,
        "0.618": last_low + (last_high - last_low) * 0.618,
    }
    for level_name in ["0.618", "0.500", "0.382"]:
        fib_price = fibs_up[level_name]
        if abs(price - fib_price) / price < tolerance:
            return {"level": level_name, "direction": "SHORT",
                    "fib_price": fib_price, "swing_high": last_high, "swing_low": last_low}

    return None

def update_btc_trend():
    global btc_trend
    d = get_klines("BTCUSDT", INTERVAL, 100)
    if not d:
        btc_trend = "neutral"
        return
    closes = d["closes"]
    price  = closes[-1]
    ema200 = calc_ema(closes, min(200, len(closes)-1))
    ema50  = calc_ema(closes, 50)
    if price > ema200 * 1.01 and price > ema50:
        btc_trend = "bullish"
    elif price < ema200 * 0.99 and price < ema50:
        btc_trend = "bearish"
    else:
        btc_trend = "neutral"
    print(f"  BTC trend: {btc_trend} | Price: {price:.0f} | EMA200: {ema200:.0f}")

def analyze(symbol):
    d = get_klines(symbol, INTERVAL, 100)
    if not d:
        return None

    closes  = d["closes"]
    highs   = d["highs"]
    lows    = d["lows"]
    volumes = d["volumes"]
    price   = closes[-1]

    rsi_now    = calc_rsi(closes)
    rsi_series = calc_rsi_series(closes)

    ema200 = calc_ema(closes, min(200, len(closes)-1))
    ema50  = calc_ema(closes, 50)
    ema20  = calc_ema(closes, 20)

    swing_highs, swing_lows = find_swings(d, lookback=5)

    vol_avg = sum(volumes[-20:]) / 20
    vol_ok  = volumes[-1] > vol_avg * 1.1

    atr_raw = sum([highs[i]-lows[i] for i in range(-14, 0)]) / 14
    atr     = max(atr_raw, price * 0.005)

    divergence = check_rsi_divergence(closes, lows, highs, rsi_series)
    fib_zone   = check_fibonacci_zone(price, swing_highs, swing_lows)

    sig      = None
    strategy = None
    score    = 0

    # ===== STRATEGIA 1: DIVERGENTA RSI =====

    # LONG — Divergenta Bullish (toleranta 7% sub EMA200)
    if divergence and divergence["type"] == "BULLISH":
        if rsi_now < 70 and price > ema200 * 0.93:
            confirmations = [
                rsi_now < 55,
                rsi_now > 25,
                vol_ok,
                price > lows[-1],
            ]
            score = sum(confirmations)
            if score >= 3:
                sig      = "LONG"
                strategy = (f"📐 Divergență RSI Bullish (forță: +{divergence['strength']})\n"
                            f"   RSI: {divergence['rsi_low1']} → {divergence['rsi_low2']} | Preț: ↓↓ RSI: ↑↑")

    # SHORT — Divergenta Bearish (toleranta 7% peste EMA200)
    elif divergence and divergence["type"] == "BEARISH":
        if rsi_now > 30 and price < ema200 * 1.07:
            confirmations = [
                rsi_now > 45,
                rsi_now < 75,
                vol_ok,
                price < highs[-1],
            ]
            score = sum(confirmations)
            if score >= 3:
                sig      = "SHORT"
                strategy = (f"📐 Divergență RSI Bearish (forță: -{divergence['strength']})\n"
                            f"   RSI: {divergence['rsi_high1']} → {divergence['rsi_high2']} | Preț: ↑↑ RSI: ↓↓")

    # ===== STRATEGIA 2: FIBONACCI =====

    # LONG — la nivel Fibonacci (toleranta 7% sub EMA200)
    if not sig and fib_zone and fib_zone["direction"] == "LONG":
        if rsi_now < 65 and price > ema200 * 0.93:
            confirmations = [
                rsi_now < 55,
                rsi_now > rsi_series[-2] if len(rsi_series) >= 2 else False,
                price > ema20,
                vol_ok,
            ]
            score = sum(confirmations)
            if score >= 3:
                sig      = "LONG"
                strategy = (f"🔢 Fibonacci {fib_zone['level']} (LONG)\n"
                            f"   Zona: ${fib_zone['fib_price']:.4f} | "
                            f"Swing: ${fib_zone['swing_low']:.4f} - ${fib_zone['swing_high']:.4f}")

    # SHORT — la nivel Fibonacci (toleranta 7% peste EMA200)
    elif not sig and fib_zone and fib_zone["direction"] == "SHORT":
        if rsi_now > 35 and price < ema200 * 1.07:
            confirmations = [
                rsi_now > 45,
                rsi_now < rsi_series[-2] if len(rsi_series) >= 2 else False,
                price < ema20,
                vol_ok,
            ]
            score = sum(confirmations)
            if score >= 3:
                sig      = "SHORT"
                strategy = (f"🔢 Fibonacci {fib_zone['level']} (SHORT)\n"
                            f"   Zona: ${fib_zone['fib_price']:.4f} | "
                            f"Swing: ${fib_zone['swing_low']:.4f} - ${fib_zone['swing_high']:.4f}")

    if not sig:
        return None

    # Filtru BTC trend pe altcoins
    if symbol != "BTCUSDT":
        if sig == "LONG" and btc_trend == "bearish":
            print(f"filtrat (BTC bearish)")
            return None
        if sig == "SHORT" and btc_trend == "bullish":
            print(f"filtrat (BTC bullish)")
            return None

    # Anti-duplicat 60 minute
    key = f"{symbol}_{sig}"
    now = datetime.now()
    if key in last_signals:
        diff = (now - last_signals[key]).total_seconds() / 60
        if diff < 60:
            print(f"duplicat ({diff:.0f} min)")
            return None
    last_signals[key] = now

    # SL/TP cu R/R 1:1.5 si 1:2.5
    if sig == "LONG":
        sl  = round(price - atr * 2, 6)
        tp1 = round(price + atr * 3, 6)
        tp2 = round(price + atr * 5, 6)
    else:
        sl  = round(price + atr * 2, 6)
        tp1 = round(price - atr * 3, 6)
        tp2 = round(price - atr * 5, 6)

    risk   = round(abs(price - sl) / price * 100, 2)
    reward = round(abs(tp1 - price) / price * 100, 2)
    rr     = round(reward / risk, 1) if risk > 0 else 0
    trend  = "✅ peste EMA200" if price > ema200 else "⚠️ sub EMA200"

    return {
        "symbol": symbol, "direction": sig, "price": price,
        "sl": sl, "tp1": tp1, "tp2": tp2,
        "rsi": round(rsi_now, 1),
        "risk": risk, "reward": reward, "rr": rr,
        "trend": trend, "strategy": strategy, "score": score,
        "btc_trend": btc_trend,
        "time": now.strftime("%H:%M %d.%m.%Y")
    }

def fmt(p):
    if p > 100:
        return f"${p:,.2f}"
    elif p > 1:
        return f"${p:.4f}"
    else:
        return f"${p:.6f}"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print(f"Telegram: {'OK' if r.status_code==200 else r.text}")
    except Exception as e:
        print(f"Eroare Telegram: {e}")

def scan():
    print(f"\nScanare {datetime.now().strftime('%H:%M:%S')}")
    update_btc_trend()
    found = 0

    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        sig = analyze(sym)
        if sig:
            e     = "🟢" if sig["direction"] == "LONG" else "🔴"
            arrow = "⬆️" if sig["direction"] == "LONG" else "⬇️"
            print(f"{sig['direction']}! RSI:{sig['rsi']} RR:{sig['rr']}")

            btc_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}[sig["btc_trend"]]

            msg  = f"{e} *{sig['direction']} — {sig['symbol']}* {arrow}\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"💰 *Entry:* {fmt(sig['price'])}\n"
            msg += f"🛑 *Stop Loss:* {fmt(sig['sl'])} (-{sig['risk']}%)\n"
            msg += f"🎯 *Take Profit 1:* {fmt(sig['tp1'])} (+{sig['reward']}%)\n"
            msg += f"🎯 *Take Profit 2:* {fmt(sig['tp2'])} (+{round(sig['reward']*5/3, 2)}%)\n"
            msg += f"━━━━━━━━━━━━━━━━\n"
            msg += f"📊 RSI: `{sig['rsi']}` | {sig['trend']}\n"
            msg += f"{btc_emoji} BTC: *{sig['btc_trend']}*\n"
            msg += f"📐 R/R: *1:{sig['rr']}*\n"
            msg += f"🧠 *Strategie:*\n{sig['strategy']}\n"
            msg += f"🕐 {sig['time']}\n"
            msg += f"_Tool educational. Nu e sfat financiar._"

            send_telegram(msg)
            found += 1
            time.sleep(1)
        else:
            print("fara semnal")
        time.sleep(0.5)

    print(f"  Total: {found} semnal(e)")

send_telegram(
    f"🤖 *NEXUS Bot v3.2 ACTIV* ✅\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"• Monede: {', '.join(SYMBOLS)}\n"
    f"• Timeframe: 1H\n"
    f"• Strategie 1: Divergență RSI\n"
    f"• Strategie 2: Fibonacci 0.382/0.5/0.618\n"
    f"• Toleranță EMA200: ±7%\n"
    f"• Toleranță Fibonacci: 1%\n"
    f"• Filtru BTC trend: activ\n"
    f"• Anti-duplicate: 60 min\n"
    f"━━━━━━━━━━━━━━━━\n"
    f"_Calitate peste cantitate..._"
)
scan()
schedule.every(15).minutes.do(scan)
print("Running...")
while True:
    schedule.run_pending()
    time.sleep(1)
