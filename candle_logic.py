import yfinance as yf
import pandas as pd
import pandas_ta as ta
import datetime
import time
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
try:
    import config
except ImportError:
    print("Error: config.pyが見つかりません。GMAIL_USERとGMAIL_PASSを記述してください。")

# ==========================================
# 0. 特製ロゴ表示関数 (NEW!)
# ==========================================
def show_logo(mode="start"):
    if mode == "start":
        print("""
    ======================================================
     _______  _______  __    _  ______   ___      _______ 
    |       ||   _   ||  |  | ||      | |   |    |       |
    |       ||  |_|  ||   |_| ||  _    ||   |    |    ___|
    |       ||       ||       || | |   ||   |    |   |___ 
    |      _||       ||  _    || |_|   ||   |___ |    ___|
    |     |_ |   _   || | |   ||       ||       ||   |___ 
    |_______||__| |__||_|  |__||______| |_______||_______|
     ___      _______  _______  ___   _______             
    |   |    |       ||       ||   | |       |            
    |   |    |   _   ||    ___||   | |       |            
    |   |    |  | |  ||   | __ |   | |       |            
    |   |___ |  |_|  ||   ||  ||   | |      _|            
    |       ||       ||   |_| ||   | |     |_             
    |_______||_______||_______||___| |_______|            
                                                          
               >> CANDLE LOGIC <<                    
               (キャンドルロジック)
    ======================================================
        """)
    else:
        print("\n    [ 完了 ] キャンドルロジック スキャニング終了\n")

# ==========================================
# 1. 判定エンジン
# ==========================================
def analyze_candle_logic(symbol, dxy_h4):
    try:
        df = yf.download(symbol, period="1mo", interval="1h", progress=False, auto_adjust=True)
        if df.empty: return None

        # 4時間足と日足のリサンプル
        h4 = df.resample('4h').agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()
        d1 = df.resample('D').agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()

        # インジケータ計算
        h4['EMA20'] = ta.ema(h4['Close'], length=20)
        h4['EMA75'] = ta.ema(h4['Close'], length=75)
        h4['RSI'] = ta.rsi(h4['Close'], length=14)
        d1['Res'] = d1['High'].rolling(window=20).max() # 20日高値
        d1['Sup'] = d1['Low'].rolling(window=20).min()  # 20日安値

        c, p, p2 = h4.iloc[-1], h4.iloc[-2], h4.iloc[-3]
        d1_c = d1.iloc[-1]
        dxy_c = dxy_h4.iloc[-1]

        signal, reason, pattern = "WAIT", "監視中", "なし"

        # トレンド判定
        is_up = (c['Close'] > c['EMA20'] > c['EMA75'])
        is_down = (c['Close'] < c['EMA20'] < c['EMA75'])

        # ローソク足パターン (3-A:包み足, 3-B:インサイドバー)
        p_body = abs(p['Open'] - p['Close'])
        p_low_wick = (p['Open'] if p['Open'] < p['Close'] else p['Close']) - p['Low']
        p_high_wick = p['High'] - (p['Close'] if p['Open'] < p['Close'] else p['Open'])
        
        is_3a_buy = (p_low_wick >= p_body * 2.5) and (c['Close'] > p['High'])
        is_3a_sell = (p_high_wick >= p_body * 2.5) and (c['Close'] < p['Low'])
        is_inside = (p['High'] < p2['High']) and (p['Low'] > p2['Low'])
        is_3b_buy = is_inside and (c['Close'] > p2['High'])
        is_3b_sell = is_inside and (c['Close'] < p2['Low'])

        # RR比計算 (日足レジサポ基準)
        sl = d1_c['Sup'] if is_up else d1_c['Res']
        tp = d1_c['Res'] if is_up else d1_c['Sup']
        risk = abs(c['Close'] - sl)
        reward = abs(tp - c['Close'])
        rr = reward / risk if risk > 0 else 0

        # 判定
        clean_sym = symbol.replace("=X", "")
        if is_up:
            if not (is_3a_buy or is_3b_buy): reason = "ﾊﾟﾀｰﾝ待機"
            elif not (45 <= c['RSI'] <= 60): reason = f"RSI過熱({c['RSI']:.1f})"
            elif not (dxy_c['EMA20'] > dxy_c['EMA50']): reason = "DXY不一致"
            elif rr < 1.5: reason = f"RR不足(1:{rr:.1f})"
            else:
                signal, pattern, reason = "ENTRY(BUY)", ("包み足" if is_3a_buy else "ｲﾝｻｲﾄﾞ"), "全条件合致"
        elif is_down:
            if not (is_3a_sell or is_3b_sell): reason = "ﾊﾟﾀｰﾝ待機"
            elif not (40 <= c['RSI'] <= 55): reason = f"RSI過熱({c['RSI']:.1f})"
            elif not (dxy_c['EMA20'] < dxy_c['EMA50']): reason = "DXY不一致"
            elif rr < 1.5: reason = f"RR不足(1:{rr:.1f})"
            else:
                signal, pattern, reason = "ENTRY(SELL)", ("包み足" if is_3a_sell else "ｲﾝｻｲﾄﾞ"), "全条件合致"
        else:
            reason = "トレンド外"

        return {"sym": clean_sym, "sig": signal, "pat": pattern, "res": reason, "prc": c['Close'], "tp": tp, "sl": sl, "rr": rr}
    except Exception as e:
        return {"sym": symbol, "sig": "ERROR", "res": str(e)}

# ==========================================
# 2. メール送信 (sendmail修正済)
# ==========================================
def send_report(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = config.GMAIL_USER
    msg['To'] = config.GMAIL_USER
    msg['Date'] = formatdate(localtime=True)
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(config.GMAIL_USER, config.GMAIL_PASS)
            server.sendmail(config.GMAIL_USER, [config.GMAIL_USER], msg.as_string())
            print(f"  [Mail] 送信成功: {subject}")
    except Exception as e:
        print(f"  [Mail] 送信失敗: {e}")

# ==========================================
# 3. 実行メイン (16時〜1時限定)
# ==========================================
def main_task():
    show_logo("start") # ロゴを表示 (NEW!)
    now = datetime.datetime.now()
    now_str = now.strftime('%H:%M')
    print(f"\n--- スキャン開始 ({now_str}) ---")
    
    # DXY取得
    dxy_raw = yf.download("DX-Y.NYB", period="1mo", interval="1h", progress=False, auto_adjust=True)
    dxy_h4 = dxy_raw.resample('4h').agg({'Close':'last'}).dropna()
    dxy_h4['EMA20'] = ta.ema(dxy_h4['Close'], length=20)
    dxy_h4['EMA50'] = ta.ema(dxy_h4['Close'], length=50)

    report_list, entry_list = [], []
    SYMBOLS = ["USDJPY=X", "EURUSD=X", "GBPUSD=X", "USDCAD=X", "AUDUSD=X", "NZDUSD=X", "USDCHF=X"]

    for s in SYMBOLS:
        print(f"  [Scan] {s}...")
        res = analyze_candle_logic(s, dxy_h4)
        if res:
            report_list.append(f"{res['sym']}: {res['sig']} | {res['res']}")
            if "ENTRY" in res['sig']: entry_list.append(res)

    # チャンス通知 (★マーク付き)
    for e in entry_list:
        subj = f"【★{e['sig']}】{e['sym']} | {e['pat']} | RR 1:{e['rr']:.1f}"
        body = f"期待値(RR比): 1:{e['rr']:.1f}\n価格: {e['prc']:.3f}\n利確: {e['tp']:.3f}\n損切: {e['sl']:.3f}"
        send_report(subj, body)

    # 定時通知 (1時間おき)
    focus = next((line for line in report_list if "条件合致" in line or "過熱" in line), "チャンス待機中")
    send_report(f"【定時】CLレポート ({now_str}) / {focus[:15]}...", "\n".join(report_list))

    show_logo("end") # 完了ロゴを表示 (NEW!)

if __name__ == "__main__":
    print("CANDLE LOGIC 監視システム (16:00-01:00) 稼働中...")
    while True:
        now = datetime.datetime.now()
        # 16:05 から 深夜 01:05 までの間、毎時05分に実行
        if (now.hour >= 16 or now.hour < 1) and now.minute == 5:
            main_task()
            time.sleep(60)
        time.sleep(30)
