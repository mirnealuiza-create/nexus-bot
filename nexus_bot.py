import requests
import time
import schedule
from datetime import datetime

TELEGRAM_BOT_TOKEN = "8671954962:AAGY7YKVfnRJCBaW2lYZpMPWVOoFhX7fRs4"
TELEGRAM_CHAT_ID   = "7814466236"

SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "CHZUSDT", "ADAUSDT"]
INTERVAL = "15m"

def get_klines(symbol, interval="15m", limit=250):
    try:
        url = "https://api.binance.com/api/v3/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        data = r.json()
        if not isinstance(data, list) or len(data) < 50:
            return None, None, None, None
        closes  = [float(c[4]) for c in data if len(c) > 5]
        highs   = [float(c[2]) for c in data if len(c) > 5]
        lows    = [float(c[3]) for c in data if len(c) > 5]
        volumes = [float(c[5]) for c in data if len(c) > 5]
        return closes, highs, lows, volumes
    except Exception as e:
        print(f"  Eroare date {symbol}: {e}")
        return None, None, None, None

def calc_rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1]
    ema = sum(closes[:period]) / period
    k = 2 / (period + 1)
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema

def analyze(symbol):
    closes, highs, lows, volumes = get_klines(symbol, INTERVAL)
    if not closes or len(closes) < 50:
        return None

    price     = closes[-1]
    rsi       = calc_rsi(closes)
    rsi_prev  = calc_rsi(closes[:-1])
    ema200    = calc_ema(closes, min(200, len(closes)-1))
    ema12     = calc_ema(closes, 12)
    ema26     = calc_ema(closes, 26)
    macd      = ema12 - ema26
    ema12p    = calc_ema(closes[:-1], 12)
    ema26p    = calc_ema(closes[:-1], 26)
    macd_prev = ema12p - ema26p

    trend = "↑ peste EMA200" if price > ema200 else "↓ sub EMA200"

    long_cond  = [rsi < 38, rsi > rsi_prev, macd > macd_prev]
    short_cond = [rsi > 62, rsi < rsi_prev, macd < macd_prev]

    ls = sum(long_cond)
    ss = sum(short_cond)

    if ls >= 2:
        direction, score = "LONG", ls
    elif ss >= 2:
        direction, score = "SHORT", ss
    else:
        return None

    atr_vals = [highs[i] - lows[i] for i in range(-14, 0)]
    atr = sum(atr_vals) / 14

    if direction == "LONG":
        stop = round(min(lows[-20:]) - atr * 0.2, 6)
        t1   = round(price + atr * 2, 6)
        t2   = round(price + atr * 4, 6)
    else:
        stop = round(max(highs[-20:]) + atr * 0.2, 6)
        t1   = round(price - atr * 2, 6)
        t2   = round(price - atr * 4, 6)

    risk   = round(abs(price - stop) / price * 100, 2)
    reward = round(abs(t1 - price) / price * 100, 2)
    rr     = round(reward / risk, 2) if risk > 0 else 0
    conf   = min(90, 50 + score * 15)

    return {
        "symbol": symbol, "direction": direction, "price": price,
        "stop": stop, "t1": t1, "t2": t2, "rsi": round(rsi, 1),
        "score": score, "conf": conf, "rr": rr, "risk": risk,
        "reward": reward, "trend": trend,
        "time": datetime.now().strftime("%H:%M %d.%m.%Y")
    }

def send_telegram(msg):
    url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=data, timeout=10)
        print(f"  Telegram: {'OK' if r.status_code == 200 else r.text}")
    except Exception as e:
        print(f"  Eroare Telegram: {e}")

def format_msg(s):
    e = "🟢" if s["direction"] == "LONG" else "🔴"
    a = "⬆️" if s["direction"] == "LONG" else "⬇️"
    return f"""{e} *SEMNAL {s['direction']} — {s['symbol']}* {a}
━━━━━━━━━━━━━━━━━━
🕐 *{s['time']}* | {INTERVAL}
💰 *Preț:* ${s['price']:,.5f}

🎯 *SETUP*
• Entry: `${s['price']:,.5f}`
• Stop-Loss: `${s['stop']:,.5f}` (-{s['risk']}%)
• Target 1: `${s['t1']:,.5f}` (+{s['reward']}%)
• Target 2: `${s['t2']:,.5f}`

📊 RSI: `{s['rsi']}` | {s['trend']} | Condiții: `{s['score']}/3`
⚡ *Confidence: {s['conf']}%* | R/R: 1:{s['rr']}

⚠️ _Tool educațional. Nu constituie sfat financiar._"""

def scan():
    print(f"\n🔍 Scanare — {datetime.now().strftime('%H:%M:%S')}")
    found = 0
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        sig = analyze(sym)
        if sig:
            print(f"→ {sig['direction']} ({sig['conf']}%)")
            send_telegram(format_msg(sig))
            found += 1
            time.sleep(1)
        else:
            print("→ fara semnal")
        time.sleep(0.3)
    print(f"  Total: {found} semnal(e)")

def startup():
    msg = f"🤖 *NEXUS Bot — ACTIV* ✅\n• Monede: {', '.join(SYMBOLS)}\n• Interval: {INTERVAL}\n• Scanare: la fiecare 15 minute\n_Monitorizez pietele..._"
    send_telegram(msg)

if __name__ == "__main__":
    print("🚀 NEXUS Bot pornit!")
    startup()
    scan()
    schedule.every(15).minutes.do(scan)
    print("⏰ Running...\n")
    while True:
        schedule.run_pending()
        time.sleep(1)
