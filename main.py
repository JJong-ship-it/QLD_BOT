import yfinance as yf
import pandas as pd

def check_trading_signal():
    # 1. 최신 데이터 수집 (QQQ, QLD)
    qqq_raw = yf.download("QQQ", period="1y", interval="1d", progress=False)
    
    if qqq_raw.empty:
        print("데이터 수집 실패")
        return None

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

    # 4. [신규 추가] 이격도 과열 필터 로직
    # 예: 200일선 대비 주가가 15% 이상 폭등해 있으면 '과열(True)'로 판정
    disparity_limit = 1.15  # 1.15 = +15% 과열 기준
    current_disparity = curr_close / ma200
    is_overheated = current_disparity > disparity_limit

    print(f"📊 [시장 상태 진단]")
    print(f" - QQQ 종가: ${curr_close:.2f}")
    print(f" - 5일선: ${ma5:.2f} / 200일선: ${ma200:.2f}")
    print(f" - 이격도(대 200일선): {(current_disparity - 1) * 100:+.2f}%")

    # 5. 최종 매매 신호 결정
    if not is_bull_trend:
        signal = "SELL"
        reason = "🔴 하락장 전환 (데드크로스) - 현금 대피"
    else:
        # 상승장(초록불)이지만 과열 필터에 걸린 경우
        if is_overheated:
            signal = "HOLD_OR_WAIT"
            reason = f"⚠️ 상승장이지만 이격도 과열({(current_disparity - 1) * 100:.1f}%)로 신규 진입 보류"
        else:
            signal = "BUY"
            reason = "🟢 상승장 정상 궤도 - 매수/보유 진입"

    print(f" - 최종 판정: [{signal}] ({reason})\n")
    return signal

if __name__ == "__main__":
    check_trading_signal()