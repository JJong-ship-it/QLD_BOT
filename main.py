import json
import os
import sys
import pandas as pd
import requests
import yfinance as yf

# ==========================================
# 1. 설정 및 상태 파일
# ==========================================
STATE_FILE = "state.json"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def load_state():
    default_state = {
        "position_state": "HOLDING",  # 현재 보유 상태 (초기 세팅값)
        "overheated_flag": False,
        "last_processed_date": ""
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"상태 로드 실패 (기본값 사용): {e}")
            return default_state
    return default_state

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"상태 저장 실패: {e}")

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 텔레그램 환경변수 미설정 (콘솔 출력):")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("📲 텔레그램 알림 전송 완료")
        else:
            print(f"❌ 텔레그램 전송 실패: {res.text}")
    except Exception as e:
        print(f"❌ 텔레그램 전송 에러: {e}")

# ==========================================
# 2. 데이터 수집 및 Dual-Regime 지표 계산
# ==========================================
def get_market_data():
    tickers = ["QQQ", "QLD", "TQQQ"]
    data = yf.download(tickers, period="2y", interval="1d", progress=False)

    if data.empty:
        raise ValueError("데이터 다운로드에 실패했습니다.")

    if isinstance(data.columns, pd.MultiIndex):
        c_df = data["Close"]
        h_df = data["High"]
        l_df = data["Low"]
    else:
        c_df = data
        h_df = data
        l_df = data

    qqq_c = c_df["QQQ"]
    qqq_h = h_df["QQQ"]
    qqq_l = l_df["QQQ"]

    # 1. 거시 추세선 (2022년형 하락장 차단)
    ma5 = qqq_c.rolling(window=5).mean()
    ma20 = qqq_c.rolling(window=20).mean()
    ma200 = qqq_c.rolling(window=200).mean()
    disparity = qqq_c / ma200

    # 2. SMC Equilibrium (최근 20일 스윙 중심값)
    swing_high = qqq_h.rolling(window=20).max()
    swing_low = qqq_l.rolling(window=20).min()
    equilibrium = (swing_high + swing_low) / 2

    # 3. ChrisMoody MACD Histogram
    ema12 = qqq_c.ewm(span=12, adjust=False).mean()
    ema26 = qqq_c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.rolling(window=9).mean()
    macd_hist = macd - signal

    latest_date = qqq_c.index[-1].strftime("%Y-%m-%d")

    return {
        "date": latest_date,
        "qqq_close": float(qqq_c.iloc[-1]),
        "qld_close": float(c_df["QLD"].iloc[-1]),
        "tqqq_close": float(c_df["TQQQ"].iloc[-1]),
        "ma5": float(ma5.iloc[-1]),
        "ma20": float(ma20.iloc[-1]),
        "ma200": float(ma200.iloc[-1]),
        "disparity": float(disparity.iloc[-1]),
        "equilibrium": float(equilibrium.iloc[-1]),
        "macd_hist": float(macd_hist.iloc[-1]),
    }

# ==========================================
# 3. Dual-Regime SMC Apex 매매 판정 엔진
# ==========================================
def evaluate_strategy(data, state):
    pos = state.get("position_state", "HOLDING")
    overheated = state.get("overheated_flag", False)

    close = data["qqq_close"]
    ma5 = data["ma5"]
    ma20 = data["ma20"]
    ma200 = data["ma200"]
    disp = data["disparity"]
    eq = data["equilibrium"]
    macd_hist = data["macd_hist"]

    is_bull = ma5 >= ma200
    above_ma20 = close > ma20
    macd_bull = macd_hist > 0

    action_title = ""
    action_desc = ""

    # [1] 거시 하락장 (MA5 < MA200)
    if not is_bull:
        if pos == "HOLDING":
            action_title = "🔴 [대세 하락 탈출 매도]"
            action_desc = "MA5 < MA200 데드크로스가 발생했습니다.\n👉 <b>전량 매도 후 현금 100% 확보</b>"
        else:
            action_title = "⚪ [하락장 관망 유지]"
            action_desc = "MA5 < MA200 역배열 지속 중입니다.\n👉 <b>현금 100% 관망 유지</b>"
        pos = "CASH_AFTER_BEAR"
        overheated = False

    # [2] 거시 상승장 (MA5 >= MA200)
    else:
        # 이격도 120% 도달 시 과열 플래그 활성화
        if disp >= 1.20:
            overheated = True

        if pos == "HOLDING":
            # 120% 과열 플래그 상태에서 20일선 및 SMC 중심선(Equilibrium) 동시 붕괴 시 조기 익절
            if overheated and (not above_ma20) and (close < eq):
                action_title = "🔥 [SMC 과열 조기 익절]"
                action_desc = "120% 이상 과열 감지 후 20일선 및 SMC 중심선(Eq)이 동시 붕괴되었습니다.\n👉 <b>전량 분할 매도 후 현금화</b>"
                pos = "CASH_AFTER_EARLY_EXIT"
                overheated = False
            else:
                flag_text = "🔥 ON (과열 주의)" if overheated else "OFF (안정)"
                action_title = "🔵 [보유 유지 (Ride the Wave)]"
                action_desc = f"상승 추세가 안정적으로 지속 중입니다.\n👉 <b>포트폴리오 유지 (QLD 60% + TQQQ 40%)</b>\n• 과열 플래그: {flag_text}"

        elif pos in ["CASH_AFTER_BEAR", "CASH_AFTER_EARLY_EXIT"]:
            # 진입 조건: 20일선 위 + 비과열(이격도 1.16 이하) + MACD 히스토그램 양수 확장
            cond_trigger = above_ma20 and (disp <= 1.16) and macd_bull

            if cond_trigger:
                entry_type = "대세 초입 신규 매수" if pos == "CASH_AFTER_BEAR" else "눌림목 재매수"
                action_title = f"🟢 [{entry_type}]"
                action_desc = "골든크로스 상태에서 20일선 안착 및 MACD 모멘텀 상승 확인!\n👉 <b>매수 집행: QLD 60% + TQQQ 40%</b>"
                pos = "HOLDING"
                overheated = False
            else:
                action_title = "⚠️ [진입 타점 대기]"
                action_desc = "대세 상승장이나 20일선 미돌파, MACD 음수 또는 이격도 과열로 대기 중입니다.\n👉 <b>현금 유지하며 타점 관망</b>"

    new_state = {
        "position_state": pos,
        "overheated_flag": overheated,
        "last_processed_date": data["date"]
    }
    return action_title, action_desc, new_state

# ==========================================
# 4. 메인 실행 루틴
# ==========================================
def main():
    state = load_state()
    data = get_market_data()

    # 중복 실행 방지
    if state.get("last_processed_date") == data["date"]:
        print(f"이미 처리된 영업일입니다 ({data['date']}). 프로그램을 종료합니다.")
        return

    action_title, action_desc, new_state = evaluate_strategy(data, state)
    save_state(new_state)

    msg = (
        f"📊 <b>Dual-Regime SMC Apex 리포트 ({data['date']})</b>\n\n"
        f"<b>{action_title}</b>\n"
        f"{action_desc}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• <b>QQQ 종가</b>: ${data['qqq_close']:.2f}\n"
        f"• <b>QLD / TQQQ</b>: ${data['qld_close']:.2f} / ${data['tqqq_close']:.2f}\n"
        f"• <b>MA5 / MA20 / MA200</b>: ${data['ma5']:.2f} / ${data['ma20']:.2f} / ${data['ma200']:.2f}\n"
        f"• <b>SMC 중심선 (Eq)</b>: ${data['equilibrium']:.2f}\n"
        f"• <b>200일선 이격도</b>: {data['disparity']*100:.2f}%\n"
        f"• <b>MACD Hist</b>: {data['macd_hist']:.3f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• <b>현재 포지션</b>: {new_state['position_state']}\n"
        f"• <b>과열 플래그</b>: {'🔥 ON' if new_state['overheated_flag'] else 'OFF'}\n"
    )

    print(msg.replace("<b>", "").replace("</b>", ""))
    send_telegram(msg)

if __name__ == "__main__":
    main()
