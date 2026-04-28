import requests
import time
import schedule
from datetime import datetime

TELEGRAM_BOT_TOKEN = "8671954962:AAGY7YKVfnRJCBaW2lYZpMPWVOoFhX7fRs4"
TELEGRAM_CHAT_ID = "7814466236"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT"]
INTERVAL = "15m"

def get_klines(symbol):
    try:
        url = "https://api.binance.us/api/v3/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": INTERVAL, "limit": 100}, timeout=10)
        data = r.json()
        if not isinstance(data, list) or len(data) < 30:
            return None
        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]
        return {"closes": closes, "highs": highs, "lows": lows}
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

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print("Telegram OK")
    except Exception as e:
        print(f"Eroare telegram: {e}")

def fmt(price):
    if price > 100:
        return f"${price:,.2f}"
    elif price > 1:
        return f"${price:.4f}"
    else:
        return f"${price:.5f}"

def scan():
    print(f"\nScanare {datetime.now().strftime('%H:%M:%S')}")
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ", flush=True)
        d = get_klines(sym)
        if not d:
            print("eroare date")
            continue
        closes = d["closes"]
        highs = d["highs"]
        lows = d["lows"]
        price = closes[-1]
        r1 = calc_rsi(closes)
        r2 = calc_rsi(closes[:-1])
        e12 = calc_ema(closes, 12)
        e26 = calc_ema(closes, 26)
        macd = e12 - e26
        e12p = calc_ema(closes[:-1], 12)
        e26p = calc_ema(closes[:-1], 26)
        macdp = e12p - e26p
        ema200 = calc_ema(closes, min(200, len(closes)-1))
        trend = "✅ peste EMA200" if price > ema200 else "⚠️ sub EMA200"

        if r1 < 40 and r1 > r2 and macd > macdp:
            sig = "LONG"
        elif r1 > 60 and r1 < r2 and macd < macdp:
            sig = "SHORT"
        else:
            print(f"fara semnal (RSI:{r1:.1f})")
            continue

        # ATR bazat pe ultimele 14 lumânări - minim 0.3% din pret
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

        print(f"{sig}! RSI:{r1:.1f}")
        e = "🟢" if sig == "LONG" else "🔴"
        arrow = "⬆️" if sig == "LONG" else "⬇️"

        msg = f"{e} *{sig} — {sym}* {arrow}\n"
        msg += f"━━━━━━━━━━━━━━━━\n"
        msg += f"💰 *Entry:* {fmt(price)}\n"
        msg += f"🛑 *Stop Loss:* {fmt(sl)} (-{risk_pct}%)\n"
        msg += f"🎯 *Take Profit 1:* {fmt(tp1)} (+{reward_pct}%)\n"
        msg += f"🎯 *Take Profit 2:* {fmt(tp2)} (+{round(reward_pct*2, 2)}%)\n"
        msg += f"━━━━━━━━━━━━━━━━\n"
        msg += f"📊 RSI: `{r1:.1f}` | R/R: 1:{rr}\n"
        msg += f"📈 Trend: {trend}\n"
        msg += f"🕐 {datetime.now().strftime('%H:%M %d.%m.%Y')}\n"
        msg += f"_Tool educational. Nu e sfat financiar._"
        send_telegram(msg)
        time.sleep(1)

send_telegram(f"🤖 *NEXUS Bot ACTIV* ✅\nMonede: {', '.join(SYMBOLS)}\nScanare la 15 minute")
scan()
schedule.every(15).minutes.do(scan)
print("Running...")
while True:
    schedule.run_pending()
    time.sleep(1)
