import requests
import time
import schedule
from datetime import datetime

TELEGRAM_BOT_TOKEN = "8671954962:AAGY7YKVfnRJCBaW2lYZpMPWVOoFhX7fRs4"
TELEGRAM_CHAT_ID = "7814466236"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "CHZUSDT", "ADAUSDT"]
INTERVAL = "15m"

def get_klines(symbol):
    try:
        r = requests.get("https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": INTERVAL, "limit": 100}, timeout=10)
        data = r.json()
        if not isinstance(data, list) or len(data) < 30:
            return None
        return {
            "closes": [float(c[4]) for c in data],
            "highs": [float(c[2]) for c in data],
            "lows": [float(c[3]) for c in data],
        }
    except:
        return None

def rsi(closes):
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-14:]) / 14
    al = sum(losses[-14:]) / 14
    return 100 if al == 0 else 100 - (100 / (1 + ag/al))

def ema(closes, p):
    e = sum(closes[:p]) / p
    k = 2 / (p + 1)
    for c in closes[p:]:
        e = c * k + e * (1 - k)
    return e

def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print("  Telegram: OK")
    except Exception as e:
        print(f"  Eroare: {e}")

def scan():
    print(f"\n Scanare {datetime.now().strftime('%H:%M:%S')}")
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        d = get_klines(sym)
        if not d:
            print("eroare date")
            continue
        closes = d["closes"]
        price = closes[-1]
        r1 = rsi(closes)
        r2 = rsi(closes[:-1])
        e12 = ema(closes, 12)
        e26 = ema(closes, 26)
        macd = e12 - e26
        e12p = ema(closes[:-1], 12)
        e26p = ema(closes[:-1], 26)
        macdp = e12p - e26p
        ema200 = ema(closes, min(200, len(closes)-1))
        trend = "peste EMA200" if price > ema200 else "sub EMA200"

        if r1 < 40 and r1 > r2 and macd > macdp:
            sig = "LONG"
        elif r1 > 60 and r1 < r2 and macd < macdp:
            sig = "SHORT"
        else:
            print("fara semnal")
            continue

        atr = sum([d["highs"][i]-d["lows"][i] for i in range(-14,0)]) / 14
        if sig == "LONG":
            sl = round(price - atr * 1.5, 6)
            tp = round(price + atr * 3, 6)
        else:
            sl = round(price + atr * 1.5, 6)
            tp = round(price - atr * 3, 6)

        print(f"{sig}!")
        msg = f"{'🟢' if sig=='LONG' else '🔴'} *{sig} — {sym}*\n"
        msg += f"💰 Pret: `${price:.5f}` | {trend}\n"
        msg += f"🎯 Stop: `${sl:.5f}` | Target: `${tp:.5f}`\n"
        msg += f"📊 RSI: `{r1:.1f}` | {datetime.now().strftime('%H:%M %d.%m')}\n"
        msg += f"_Tool educational. Nu e sfat financiar._"
        send(msg)
        time.sleep(1)

send(f"🤖 *NEXUS Bot ACTIV* ✅\nMonede: {', '.join(SYMBOLS)}\nScanare la 15 minute")
scan()
schedule.every(15).minutes.do(scan)
print("Running...")
while True:
    schedule.run_pending()
    time.sleep(1)
