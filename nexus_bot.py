import requests
import time
try:
    import schedule
except ImportError:
    import os
    os.system("pip install schedule")
    import schedule
from datetime import datetime
import pandas as pd
import numpy as np

# ============================================================
# CONFIGURARE — completează cu datele tale
# ============================================================
TELEGRAM_BOT_TOKEN = "8671954962:AAGY7YKVfnRJCBaW2lYZpMPWVOoFhX7fRs4"
TELEGRAM_CHAT_ID   = "7814466236"

# Monede monitorizate
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT"]

# Interval timeframe (15m, 1h, 4h)
INTERVAL = "15m"

# Parametri indicatori
RSI_PERIOD        = 14
RSI_OVERSOLD      = 35   # sub acest nivel = potențial LONG
RSI_OVERBOUGHT    = 65   # peste acest nivel = potențial SHORT
EMA_FAST          = 9
EMA_SLOW          = 21
EMA_TREND         = 200
MIN_VOLUME_FACTOR = 1.5  # volumul curent trebuie să fie de 1.5x media

# ============================================================

BINANCE_URL = "https://api.binance.com/api/v3/klines"

def get_klines(symbol, interval="15m", limit=250):
    """Ia datele OHLCV de la Binance."""
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(BINANCE_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "time","open","high","low","close","volume",
            "close_time","quote_vol","trades","taker_base","taker_quote","ignore"
        ])
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return df
    except Exception as e:
        print(f"Eroare Binance {symbol}: {e}")
        return None

def calc_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(window=period).mean()
    loss  = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast   = calc_ema(series, fast)
    ema_slow   = calc_ema(series, slow)
    macd_line  = ema_fast - ema_slow
    signal_line= calc_ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram

def analyze(symbol):
    """Analizează un simbol și returnează un semnal dacă există."""
    df = get_klines(symbol, INTERVAL)
    if df is None or len(df) < 220:
        return None

    close  = df["close"]
    volume = df["volume"]
    price  = close.iloc[-1]

    # Indicatori
    rsi        = calc_rsi(close, RSI_PERIOD)
    ema_fast   = calc_ema(close, EMA_FAST)
    ema_slow   = calc_ema(close, EMA_SLOW)
    ema_trend  = calc_ema(close, EMA_TREND)
    macd, macd_sig, macd_hist = calc_macd(close)

    rsi_now       = rsi.iloc[-1]
    rsi_prev      = rsi.iloc[-2]
    ema_fast_now  = ema_fast.iloc[-1]
    ema_slow_now  = ema_slow.iloc[-1]
    ema_trend_now = ema_trend.iloc[-1]
    macd_now      = macd.iloc[-1]
    macd_sig_now  = macd_sig.iloc[-1]
    macd_prev     = macd.iloc[-2]
    macd_sig_prev = macd_sig.iloc[-2]
    vol_now       = volume.iloc[-1]
    vol_avg       = volume.iloc[-20:].mean()

    # Confirmare volum
    vol_ok = vol_now > (vol_avg * MIN_VOLUME_FACTOR)

    # ---- SEMNAL LONG ----
    long_conditions = [
        rsi_now < RSI_OVERSOLD,                          # RSI oversold
        rsi_now > rsi_prev,                              # RSI în creștere
        price > ema_trend_now,                           # Preț peste EMA 200
        ema_fast_now > ema_slow_now,                     # EMA fast > EMA slow
        macd_now > macd_sig_now and macd_prev <= macd_sig_prev,  # MACD crossover bullish
        vol_ok,                                          # Volum confirmat
    ]

    # ---- SEMNAL SHORT ----
    short_conditions = [
        rsi_now > RSI_OVERBOUGHT,                        # RSI overbought
        rsi_now < rsi_prev,                              # RSI în scădere
        price < ema_trend_now,                           # Preț sub EMA 200
        ema_fast_now < ema_slow_now,                     # EMA fast < EMA slow
        macd_now < macd_sig_now and macd_prev >= macd_sig_prev,  # MACD crossover bearish
        vol_ok,                                          # Volum confirmat
    ]

    long_score  = sum(long_conditions)
    short_score = sum(short_conditions)

    # Necesită minim 4 din 6 condiții
    if long_score >= 4:
        direction  = "LONG"
        score      = long_score
    elif short_score >= 4:
        direction  = "SHORT"
        score      = short_score
    else:
        return None

    # Calcul nivele
    recent_lows  = df["low"].iloc[-20:]
    recent_highs = df["high"].iloc[-20:]
    atr          = (df["high"] - df["low"]).iloc[-14:].mean()

    if direction == "LONG":
        entry      = price
        stop_loss  = round(recent_lows.min() - atr * 0.2, 4)
        target1    = round(price + atr * 2, 4)
        target2    = round(price + atr * 4, 4)
        risk_pct   = round((entry - stop_loss) / entry * 100, 2)
        reward_pct = round((target1 - entry) / entry * 100, 2)
    else:
        entry      = price
        stop_loss  = round(recent_highs.max() + atr * 0.2, 4)
        target1    = round(price - atr * 2, 4)
        target2    = round(price - atr * 4, 4)
        risk_pct   = round((stop_loss - entry) / entry * 100, 2)
        reward_pct = round((entry - target1) / entry * 100, 2)

    rr_ratio     = round(reward_pct / risk_pct, 2) if risk_pct > 0 else 0
    confidence   = min(95, 50 + score * 8)

    return {
        "symbol":     symbol,
        "direction":  direction,
        "price":      price,
        "entry":      entry,
        "stop_loss":  stop_loss,
        "target1":    target1,
        "target2":    target2,
        "rsi":        round(rsi_now, 1),
        "macd":       round(macd_now, 4),
        "confidence": confidence,
        "rr_ratio":   rr_ratio,
        "risk_pct":   risk_pct,
        "reward_pct": reward_pct,
        "score":      score,
        "interval":   INTERVAL,
        "time":       datetime.now().strftime("%H:%M %d.%m.%Y"),
    }

def format_message(sig):
    """Formatează mesajul Telegram."""
    emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
    arrow = "⬆️" if sig["direction"] == "LONG" else "⬇️"

    msg = f"""
{emoji} *SEMNAL {sig['direction']} — {sig['symbol']}* {arrow}
━━━━━━━━━━━━━━━━━━━━
🕐 *{sig['time']}* | TF: {sig['interval']}
💰 *Preț curent:* ${sig['price']:,.4f}

🎯 *SETUP*
• Entry: `${sig['entry']:,.4f}`
• Stop-Loss: `${sig['stop_loss']:,.4f}` (-{sig['risk_pct']}%)
• Target 1: `${sig['target1']:,.4f}` (+{sig['reward_pct']}%)
• Target 2: `${sig['target2']:,.4f}`

📊 *INDICATORI*
• RSI: `{sig['rsi']}`
• MACD crossover: ✅
• Condiții: `{sig['score']}/6`

⚡ *Confidence: {sig['confidence']}%*
📐 *Risk/Reward: 1:{sig['rr_ratio']}*

⚠️ _Tool educațional. Nu constituie sfat financiar._
"""
    return msg.strip()

def send_telegram(message):
    """Trimite mesaj pe Telegram."""
    url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown",
    }
    try:
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            print(f"✅ Mesaj trimis pe Telegram")
        else:
            print(f"❌ Eroare Telegram: {r.text}")
    except Exception as e:
        print(f"❌ Eroare trimitere: {e}")

def scan_markets():
    """Scanează toate simbolurile și trimite semnale."""
    print(f"\n🔍 Scanare piețe — {datetime.now().strftime('%H:%M:%S')}")
    signals_found = 0

    for symbol in SYMBOLS:
        print(f"  Analizez {symbol}...", end=" ")
        sig = analyze(symbol)
        if sig:
            print(f"→ {sig['direction']} (conf: {sig['confidence']}%)")
            msg = format_message(sig)
            send_telegram(msg)
            signals_found += 1
            time.sleep(1)  # Pauza intre mesaje
        else:
            print("→ Fără semnal")
        time.sleep(0.3)

    if signals_found == 0:
        print("  Niciun semnal valid găsit.")
    else:
        print(f"  {signals_found} semnal(e) trimis(e)!")

def send_startup_message():
    """Mesaj de pornire bot."""
    msg = f"""
🤖 *NEXUS Trading Bot — ACTIV*
━━━━━━━━━━━━━━━━━━
• Monede: {', '.join(SYMBOLS)}
• Interval: {INTERVAL}
• Scanare: la fiecare 15 minute
• RSI oversold < {RSI_OVERSOLD} | overbought > {RSI_OVERBOUGHT}
• Volum minim: {MIN_VOLUME_FACTOR}x media

_Botul rulează și monitorizează piețele..._
"""
    send_telegram(msg.strip())

if __name__ == "__main__":
    print("🚀 NEXUS Trading Bot pornit!")
    send_startup_message()

    # Scanare imediată la pornire
    scan_markets()

    # Programează scanarea la fiecare 15 minute
    schedule.every(15).minutes.do(scan_markets)

    print(f"\n⏰ Scanare automată la fiecare 15 minute. Ctrl+C pentru oprire.\n")
    while True:
        schedule.run_pending()
        time.sleep(1)
