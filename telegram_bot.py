import requests
from signal_engine import sinyal_üretici  # aynı klasörde olsun

TOKEN = "SENİN_BOT_TOKEN"
CHANNEL = "@ictsmartpro"

def send(msg):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  data={"chat_id": CHANNEL, "text": msg, "parse_mode": "HTML"})

while True:
    for sym, tf, mod in [("BTC/USDT","15m","serbest"), ("ETH/USDT","15m","serbest")]:
        s = sinyal_üretici(sym, tf, mod)
        if s:
            text = f"<b>{'ALIŞ' if s['direction']=='BUY' else 'SATIŞ'} {s['symbol']}</b>\nFiyat: ${s['price']}\n{s['reasons']}"
            send(text)
    time.sleep(15)