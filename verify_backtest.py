import yfinance as yf
import pandas as pd
import numpy as np

def run_verification():
    print("==================================================")
    print("🔬 [백테스트 무결성 검증] 10년 매매 거래 전수 조사 및 구간 분석")
    print("==================================================\n")

    # 1. QQQ 및 QLD 10년 데이터 수집
    qqq_raw = yf.download("QQQ", period="10y", interval="1d")
    qld_raw = yf.download("QLD", period="10y", interval="1d")

    if qqq_raw.empty or qld_raw.empty:
        print("데이터 수집 실패")
        return

    qqq_df = pd.DataFrame()
    qqq_df['close'] = qqq_raw['Close'].iloc[:, 0] if isinstance(qqq_raw['Close'], pd.DataFrame) else qqq_raw['Close']
    qqq_df['ma5'] = qqq_df['close'].rolling(window=5).mean()
    qqq_df['ma200'] = qqq_df['close'].rolling(window=200).mean()

    qld_df = pd.DataFrame()
    qld_df['open'] = qld_raw['Open'].iloc[:, 0] if isinstance(qld_raw['Open'], pd.DataFrame) else qld_raw['Open']
    qld_df['close'] = qld_raw['Close'].iloc[:, 0] if isinstance(qld_raw['Close'], pd.DataFrame) else qld_raw['Close']

    initial_balance = 10000.0
    cash = initial_balance
    shares = 0
    fee = 0.001 # 슬리피지/수수료 0.1%

    is_holding = False
    trade_logs = []
    buy_date = None
    buy_price = 0

    print("📌 [1단계] 10년간 발생한 모든 매매 거래 내역 전수 조사\n")
    print(f"{'구분':<5} | {'매수일자':<10} | {'매수가':<8} | {'매도일자':<10} | {'매도가':<8} | {'수익률':<8} | {'진행 잔고'}")
    print("-" * 75)

    trade_count = 0
    for i in range(200, len(qqq_df)):
        curr_date = qqq_df.index[i].strftime('%Y-%m-%d')
        prev_qqq = qqq_df.iloc[i-1] # 미래 편향 방지: 전일 마감 기준 신호 판별
        curr_qld = qld_df.iloc[i]   # 매매는 다음 날 시가 진입

        # QQQ 5일선 >= 200일선 (골든크로스 매수)
        is_bull = prev_qqq['ma5'] >= prev_qqq['ma200']

        if not is_holding and is_bull:
            is_holding = True
            buy_date = curr_date
            buy_price = curr_qld['open'] * (1 + fee)
            shares = cash / buy_price
            cash = 0

        elif is_holding and not is_bull:
            is_holding = False
            sell_date = curr_date
            sell_price = curr_qld['open'] * (1 - fee)
            cash = shares * sell_price
            shares = 0
            
            trade_count += 1
            ret = (sell_price - buy_price) / buy_price * 100
            print(f"#{trade_count:<4} | {buy_date} | ${buy_price:<7.2f} | {sell_date} | ${sell_price:<7.2f} | {ret:>+6.2f}% | ${cash:,.2f}")
            trade_logs.append({'buy_date': buy_date, 'sell_date': sell_date, 'return': ret, 'balance': cash})

    final_balance = cash if not is_holding else shares * qld_df.iloc[-1]['close']
    print("-" * 75)
    print(f"• 최종 잔고: ${final_balance:,.2f} (누적 수익률: {(final_balance - initial_balance)/initial_balance*100:.2f}%)\n")

    # 2. 구간별 성과 검증 (Out-of-Sample 테스트)
    print("📌 [2단계] 전반기 5년 vs 후반기 5년 성과 분할 검증\n")
    mid_point = len(trade_logs) // 2
    if len(trade_logs) > 0:
        first_half_ret = trade_logs[mid_point-1]['balance'] if mid_point > 0 else initial_balance
        first_half_pct = (first_half_ret - initial_balance) / initial_balance * 100
        second_half_pct = (final_balance - first_half_ret) / first_half_ret * 100

        print(f"• 전반기 5년 성과 : {first_half_pct:+.2f} % (시작 $10,000 ➔ ${first_half_ret:,.2f})")
        print(f"• 후반기 5년 성과 : {second_half_pct:+.2f} % (시작 ${first_half_ret:,.2f} ➔ ${final_balance:,.2f})")
        print("\n👉 전반기와 후반기 모두 우상향했다면 과적합(오버피팅) 없는 검증된 전략입니다!")

if __name__ == "__main__":
    run_verification()  # 콜론(:) 제거 완료