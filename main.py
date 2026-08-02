import os
import requests
import yfinance as yf
import pandas as pd

# 깃허브 시크릿 이름('TELEGRAM_TOKEN')과 정확히 일치시킵니다
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "8832709732:AAEhrq3lVI1nVwp5uLwV0uE_Zegrd9pTAwA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5763039504")

def send_telegram_message(message):
    """텔레그램으로 메시지를 전송하는 함수"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "로컬테스트용토큰":
        print("⚠️ 텔레그램 토큰이 설정되지 않았습니다.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("📲 텔레그램 알림 전송 성공!")
        else:
            print(f"❌ 텔레그램 전송 실패: {response.text}")
    except Exception as e:
        print(f"❌ 텔레그램 에러 발생: {e}")

def check_trading_signal():
    # 1. 최신 데이터 수집 (QQQ)
    qqq_raw = yf.download("QQQ", period="1y", interval="1d", progress=False)
    
    if qqq_raw.empty:
        print("데이터 수집 실패")
        return

    # 데이터프레임 정리 (멀티인덱스 대응)
    qqq_df = pd.DataFrame()
    qqq_df['close'] = qqq_raw['Close'].iloc[:, 0] if isinstance(qqq_raw['Close'], pd.DataFrame) else qqq_raw['Close']
    
    # 2. 이동평균선 계산 (5일선, 200일선)
    qqq_df['ma5'] = qqq_df['close'].rolling(window=5).mean()
    qqq_df['ma200'] = qqq_df['close'].rolling(window=200).mean()

    # 가장 최근(전일 기준) 지표 값 추출
    prev_row = qqq_df.iloc[-1]
    curr_close = prev_row['close']
    ma5 = prev_row['ma5']
    ma200 = prev_row['ma200']

    # 3. 기본 추세 판정 (상승장 여부)
    is_bull_trend = ma5 >= ma200

    # 4. 이격도 과열 필터 로직 (+15% 이상 과열 판정)
    disparity_limit = 1.15  
    current_disparity = curr_close / ma200
    is_overheated = current_disparity > disparity_limit

    # 5. 메시지 본문 구성
    msg = f"📈 **QLD 자동매매 봇 리포트**\n\n"
    msg += f"• QQQ 종가: `${curr_close:.2f}`\n"
    msg += f"• 5일선: `${ma5:.2f}`\n"
    msg += f"• 200일선: `${ma200:.2f}`\n"
    msg += f"• 이격도: `{(current_disparity - 1) * 100:+.2f}%`\n\n"

    if not is_bull_trend:
        msg += "🔴 **[매도 / 현금 대피]**\n하락장 전환 (데드크로스 발생)"
    else:
        if is_overheated:
            msg += f"⚠️ **[관망 / 진입 보류]**\n상승장이지만 이격도 과열({(current_disparity - 1) * 100:.1f}%) 상태입니다."
        else:
            msg += "🟢 **[매수 / 보유 유효]**\n정상 상승장 궤도 진입 완료!"

    print(msg)
    
    # 6. 텔레그램으로 최종 메시지 쏘기
    send_telegram_message(msg)

if __name__ == "__main__":
    check_trading_signal()