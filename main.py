import os
import requests
import yfinance as yf
import pandas as pd

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def calculate_indicators(qqq_df):
    """QQQ의 5일선과 200일선 이동평균 연산"""
    qqq_df = qqq_df.copy()
    qqq_df['ma5'] = qqq_df['close'].rolling(window=5).mean()
    qqq_df['ma200'] = qqq_df['close'].rolling(window=200).mean()
    return qqq_df

def is_golden_cross(row):
    """5일선이 200일선 위에 있는지 판별 (상승 추세)"""
    return row['ma5'] >= row['ma200']

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("텔레그램 토큰/ID 미설정 (로컬 테스트 중)")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, data=data)

def check_daily_signal():
    print("QQQ 5일/200일 골든크로스 기준 QLD 추세 스위칭 신호 체크 중...")
    
    qqq_raw = yf.download("QQQ", period="300d", interval="1d")
    qld_raw = yf.download("QLD", period="300d", interval="1d")
    
    if qqq_raw.empty or qld_raw.empty: return

    qqq_df = pd.DataFrame()
    qqq_df['close'] = qqq_raw['Close'].iloc[:, 0] if isinstance(qqq_raw['Close'], pd.DataFrame) else qqq_raw['Close']
    qqq_df = calculate_indicators(qqq_df)

    qld_close = qld_raw['Close'].iloc[-1, 0] if isinstance(qld_raw['Close'], pd.DataFrame) else qld_raw['Close'].iloc[-1]
    
    target_qqq = qqq_df.iloc[-1]
    is_bull = is_golden_cross(target_qqq)

    if is_bull:
        msg = f"🟢 **[QLD 추세 스위칭 - 보유/매수 구간]**\n• QQQ 5일선(${target_qqq['ma5']:.2f}) >= 200일선(${target_qqq['ma200']:.2f})\n• QLD 현재가: ${qld_close:.2f}\n👉 **대세 상승장 유지 중! QLD 보유 유지**"
    else:
        msg = f"🔴 **[QLD 추세 스위칭 - 현금/단기채 대피 구간]**\n• QQQ 5일선(${target_qqq['ma5']:.2f}) < 200일선(${target_qqq['ma200']:.2f})\n• QLD 현재가: ${qld_close:.2f}\n👉 **하락장 진행 중! QLD 매도 후 현금 보유**"

    print(msg)
    send_telegram(msg)

if __name__ == "__main__":
    check_daily_signal()