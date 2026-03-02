import yfinance as yf
import datetime
import time
import re
import os  # システムの環境変数を読み込むために追加
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

# ============================================================
# 1. セキュリティ設定（GitHubの金庫から情報を読み込む）
# ============================================================
# GitHubの Settings > Secrets で設定した名前と一致させます
GMAIL_ADDRESS = os.environ.get('GMAIL_USER')
GMAIL_PASSWORD = os.environ.get('GMAIL_PASS')
TO_ADDRESS = os.environ.get('GMAIL_USER') # 自分に送る設定

# 起動チェック
if not GMAIL_ADDRESS or not GMAIL_PASSWORD:
    print("【警告】メール設定（Secrets）が正しく読み込めていません。")
    # GitHub上ではここで停止するようにします
    if os.environ.get('GITHUB_ACTIONS'): 
        exit(1)

# ============================================================
# 0. ロゴ表示用（ここからは元のコードと同じです）
# ============================================================
LOGO_ART = r"""
##############################################################
#                              #
#  __ __        _    _  _____ __  __ _____ #
#  | \/ |       | |   | | | ___| \ \ / /| ___|#
#  | \ / | __ _ _ __  | | _____| |_| |__  \ \/ / | |__ #
#  | |\/| |/ _` | '__|  | |/ / _ \ __| __|  \ / | __| #
#  | | | | (_| | |   | < __/ |_ | |___  / \ | |___ #
#  |_| |_|\__,_|_|   |_|\_\___|\__|_____| /_/\_\ |_____|#
#                              #
##############################################################
"""

# ============================================================
# 2. 市場データの取得
# ============================================================
def get_market_data():
    tickers = {
        'DXY': 'DX-Y.NYB',
        'USDJPY': 'JPY=X',
        'EURUSD': 'EURUSD=X',
        'US10Y': '^TNX',
        'Nikkei225': '^N225',
        'NikkeiF': 'NIY=F',
        'Dow-F': 'YM=F',
        'S&P500': '^GSPC',
        'VIX': '^VIX',
        'Gold': 'GC=F',
        'BTC': 'BTC-USD',
        'ETH': 'ETH-USD',
        'SOL': 'SOL-USD',
        'XRP': 'XRP-USD',
        'DOGE': 'DOGE-USD',
        'ADA': 'ADA-USD'
    }

    results = {}
    for name, sym in tickers.items():
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="5d")
            if not hist.empty and len(hist) >= 2:
                results[name] = {
                    'price': hist['Close'].iloc[-1],
                    'change': ((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                }
        except:
            continue

    if 'Nikkei225' in results and 'NikkeiF' not in results:
        results['NikkeiF'] = results['Nikkei225']
    if 'NikkeiF' in results and 'Nikkei225' not in results:
        results['Nikkei225'] = results['NikkeiF']

    return results

# ============================================================
# 3. 診断ロジック
# ============================================================
def diagnose(data):
    sp5_c = data.get('S&P500', {}).get('change', 0)
    vix_p = data.get('VIX', {}).get('price', 15)

    alts = ['ETH', 'SOL', 'XRP', 'DOGE', 'ADA']
    alt_vals = [data[c]['change'] for c in alts if c in data]
    alt_avg = sum(alt_vals) / len(alt_vals) if alt_vals else 0

    outliers = []
    for name in alts:
        if name in data:
            c = data[name]['change']
            if c > alt_avg + 4.0:
                outliers.append(f"{name}独歩高({c:+.1f}%)")
            elif c < alt_avg - 4.0:
                outliers.append(f"{name}独歩安({c:+.1f}%)")

    if vix_p >= 22:
        if sp5_c <= -1.5:
            return "🔴 赤信号", "深刻なパニック売りが発生しています。", "キャッシュ確保優先。", alt_avg, outliers

    if sp5_c >= 1.5 and vix_p < 18:
        return "🟢 青信号", "理想的なリスクオン状態です。", "トレンド継続。", alt_avg, outliers

    return "⚪ 巡航速度", "市場は比較的穏やかです。", "淡々とルールを守りましょう。", alt_avg, outliers

# ============================================================
# 4. レポート生成・送信
# ============================================================
def create_body(status, reason, action, data, alt_avg, outliers, urgent_list=None, is_boot=False):
    if urgent_list is None:
        urgent_list = []

    def get_row(name, label):
        if name not in data:
            return ""
        v = data[name]
        mark = " 🚀" if v['change'] >= 3.0 else " ⚠️" if v['change'] <= -3.0 else ""
        return f"・{label:10}: {v['price']:>11,.2f} ({v['change']:+6.2f}%){mark}\n"

    body = ""
    if is_boot:
        body += "【起動時レポート】\nMarket-EYE が起動しました（システムオンライン）\n\n"
    if urgent_list:
        body += "【🚨緊急アラート通知】\n" + "\n".join(urgent_list) + "\n\n"

    body += f"状況：{status}\n解説：{reason}\n行動：{action}\n\n"
    body += "--- 為替・金利 ---\n"
    body += get_row('DXY', 'ドル指数')
    body += get_row('USDJPY', 'ドル円')
    body += get_row('EURUSD', 'ユーロドル')
    body += get_row('US10Y', '米10年債')

    body += "\n--- 株価・指数 ---\n"
    body += get_row('Nikkei225', '日経平均')
    body += get_row('NikkeiF', '日経先物')
    body += get_row('Dow-F', 'ダウ先物')
    body += get_row('S&P500', 'S&P500')
    body += get_row('VIX', 'VIX指数')

    body += "\n--- 仮想通貨・金 ---\n"
    body += get_row('Gold', 'Gold先物')
    body += get_row('BTC', 'BTC')
    body += f"・アルト平均 : {alt_avg:>11.2f}%\n"
    if outliers:
        body += f"・個別異常 : {', '.join(outliers)}\n"
    return body

def send_report(subject_prefix, status, body):
    msg = MIMEText(body)
    msg['Subject'] = f"{subject_prefix}: {status}"
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = TO_ADDRESS
    msg['Date'] = formatdate(localtime=True)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"送信エラー: {e}")
        return False

# ============================================================
# 5. メインループ
# ============================================================
if __name__ == "__main__":
    print(LOGO_ART)
    print(f"[{datetime.datetime.now().strftime('%H:%M')}] Market-EYE 起動...")

    last_sent_date = ""
    sent_alert_levels = {}
    first_run = True

    while True:
        now = datetime.datetime.now()
        m_data = get_market_data()

        if not m_data or 'VIX' not in m_data:
            print(f"[{now.strftime('%H:%M')}] データ取得失敗。待機...")
            time.sleep(30)
            continue

        status, reason, action, alt_avg, outliers = diagnose(m_data)

        urgents = []
        if abs(m_data.get('NikkeiF', {}).get('change', 0)) >= 3.0:
            urgents.append(f"日経激変({m_data['NikkeiF']['change']:+.1f}%)")
        if abs(m_data.get('S&P500', {}).get('change', 0)) >= 3.0:
            urgents.append(f"米株激変({m_data['S&P500']['change']:+.1f}%)")
        if m_data.get('VIX', {}).get('price', 0) >= 22:
            urgents.append(f"VIX危険域({m_data['VIX']['price']:.1f})")
        if abs(m_data.get('USDJPY', {}).get('change', 0)) >= 1.5:
            urgents.append(f"為替激変({m_data['USDJPY']['change']:+.1f}%)")
        if abs(m_data.get('Gold', {}).get('change', 0)) >= 2.0:
            urgents.append(f"Gold激変({m_data['Gold']['change']:+.1f}%)")
        if abs(m_data.get('BTC', {}).get('change', 0)) >= 7.0:
            urgents.append(f"BTC激変({m_data['BTC']['change']:+.1f}%)")

        if first_run:
            body_content = create_body(status, reason, action, m_data, alt_avg, outliers, urgents, is_boot=True)
            print(body_content)
            send_report("【起動時レポート】", status, body_content)
            first_run = False
        else:
            body_content = create_body(status, reason, action, m_data, alt_avg, outliers, urgents, is_boot=False)

        curr_hour = now.strftime("%Y%m%d%H")
        if now.hour in [0, 12] and now.minute < 10 and last_sent_date != curr_hour:
            if send_report("【定時報告】", status, body_content):
                last_sent_date = curr_hour

        trigger_new_alert = False
        triggered_labels = []

        if urgents:
            for u_msg in urgents:
                label = u_msg.split('(')[0]
                try:
                    val_match = re.search(r'([-+]?\d*\.?\d+)', u_msg)
                    current_val = abs(float(val_match.group(1))) if val_match else 0
                except:
                    current_val = 0

                prev_val = sent_alert_levels.get(label, 0)
                if prev_val == 0 or current_val > prev_val + 1.0:
                    trigger_new_alert = True
                    sent_alert_levels[label] = current_val
                    triggered_labels.append(label)

            mapping = {"日経": "NikkeiF", "米株": "S&P500", "VIX": "VIX", "為替": "USDJPY", "Gold": "Gold", "BTC": "BTC"}
            for label in list(sent_alert_levels.keys()):
                actual_key = next((v for k, v in mapping.items() if k in label), None)
                if actual_key and actual_key in m_data:
                    is_calm = False
                    if actual_key == "VIX":
                        if m_data[actual_key]['price'] < 20: is_calm = True
                    elif abs(m_data[actual_key]['change']) < 1.0: is_calm = True
                    if is_calm: del sent_alert_levels[label]

            if trigger_new_alert:
                subject = "【🚨緊急】" + " / ".join(triggered_labels)
                if send_report(subject, status, body_content):
                    print(f"[{now.strftime('%H:%M')}] 緊急メール送信: {triggered_labels}")

        print(f"[{now.strftime('%H:%M')}] {status} / VIX:{m_data['VIX']['price']:.1f} - 監視中...")
        
        # 監視の間隔（600秒 = 10分）
        time.sleep(600)
