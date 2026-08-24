import json
import os
import sys
import pandas as pd
import requests
import yfinance as yf

# ==========================================
# 1. 설정 및 상태 파일 경로
# ==========================================
STATE_FILE = "state.json"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "8832709732:AAEhrq3lVI1nVwp5uLwV0uE_Zegrd9pTAwA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5763039504")


def load_state():
    """이전 매매 상태를 불러옵니다."""
    default_state = {
        "position_state": "HOLDING",  # 현재 이미 보유 중이므로 HOLDING으로 시작
        "overheated_flag": False
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"상태 파일 로드 실패 (기본값 사용): {e}")
            return default_state
    return default_state


def save_state(state):
    """현재 매매 상태를 파일에 저장합니다."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"상태 파일 저장 실패: {e}")


def send_telegram(message):
    """텔레그램 메시지 발송 함수"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "로컬테스트용토큰":
        print("⚠️ 텔레그램 토큰이 설정되지 않았습니다.")
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
            print("📲 텔레그램 알림 전송 성공!")
        else:
            print(f"❌ 텔레그램 전송 실패: {res.text}")
    except Exception as e:
        print(f"❌ 텔레그램 전송 에러: {e}")


# ==========================================
# 2. 데이터 수집 및 지표 계산
# ==========================================
def get_market_data():
    """QQQ, QLD, TQQQ 일봉 데이터를 가져와 지표를 계산합니다."""
    qqq = yf.download("QQQ", period="2y", interval="1d", progress=False)
    qld = yf.download("QLD", period="5d", interval="1d", progress=False)
    tqqq = yf.download("TQQQ", period="5d", interval="1d", progress=False)

    if qqq.empty or qld.empty or tqqq.empty:
        raise ValueError("데이터 다운로드에 실패했습니다.")

    for df in [qqq, qld, tqqq]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # 지표 계산 (QQQ 기준)
    qqq["MA5"] = qqq["Close"].rolling(window=5).mean()
    qqq["MA20"] = qqq["Close"].rolling(window=20).mean()
    qqq["MA200"] = qqq["Close"].rolling(window=200).mean()
    qqq["Disparity"] = qqq["Close"] / qqq["MA200"]

    latest_qqq = qqq.iloc[-1]
    latest_qld_close = float(qld["Close"].iloc[-1])
    latest_tqqq_close = float(tqqq["Close"].iloc[-1])

    return {
        "date": qqq.index[-1].strftime("%Y-%m-%d"),
        "qqq_close": float(latest_qqq["Close"]),
        "ma5": float(latest_qqq["MA5"]),
        "ma20": float(latest_qqq["MA20"]),
        "ma200": float(latest_qqq["MA200"]),
        "disparity": float(latest_qqq["Disparity"]),
        "qld_close": latest_qld_close,
        "tqqq_close": latest_tqqq_close,
    }


# ==========================================
# 3. 매매 전략 판정 로직 (2안: QLD 70% + TQQQ 30%)
# ==========================================
def evaluate_strategy(data, state):
    pos = state.get("position_state", "HOLDING")
    overheated = state.get("overheated_flag", False)

    close = data["qqq_close"]
    ma5 = data["ma5"]
    ma20 = data["ma20"]
    disp = data["disparity"]

    is_bull = ma5 >= data["ma200"]
    is_above_ma20 = close > ma20

    action_desc = ""

    # [1] 대세 하락 탈출: MA5 < MA200
    if not is_bull:
        if pos == "HOLDING":
            action_desc = "🔴 <b>[대세 매도]</b> MA5 < MA200 데드크로스 발생 (QLD / TQQQ 전량 매도 후 현금화)"
        else:
            action_desc = "⚪ <b>[하락장 대기]</b> MA5 < MA200 역배열 구간 (현금 100% 관망)"

        pos = "CASH_AFTER_BEAR"
        overheated = False

    # [2] 대세 상승장 (MA5 >= MA200)
    else:
        if pos == "CASH_AFTER_BEAR":
            if disp <= 1.15 and is_above_ma20:
                action_desc = "🟢 <b>[1차 신규 매수]</b> 골든크로스 + 이격 115% 이하 + 20일선 안착\n👉 <b>매수 비중: QLD 70% / TQQQ 30%</b>"
                pos = "HOLDING"
                overheated = False
            else:
                action_desc = "⚠️ <b>[1차 진입 관망]</b> 골든크로스 상태이나 20일선 미회복 또는 이격 과열"

        elif pos == "HOLDING":
            if disp >= 1.18:
                overheated = True

            if overheated and (not is_above_ma20):
                action_desc = "🔥 <b>[고점 조기 익절]</b> 118% 과열 후 20일선 이탈 (QLD / TQQQ 전량 매도 후 현금화)"
                pos = "CASH_AFTER_EARLY_EXIT"
                overheated = False
            else:
                flag_text = "🔥 ON (과열 주의)" if overheated else "OFF (안정)"
                action_desc = f"🔵 <b>[보유 유지]</b> 상승 추세 지속 중 (과열 플래그: {flag_text})\n👉 <b>포트폴리오: QLD 70% + TQQQ 30%</b>"

        elif pos == "CASH_AFTER_EARLY_EXIT":
            if is_above_ma20 and (disp <= 1.15):
                action_desc = "🟢 <b>[눌림목 재매수]</b> 20일선 상향 돌파 & 이격도 115% 이하 충족\n👉 <b>매수 비중: QLD 70% / TQQQ 30%</b>"
                pos = "HOLDING"
                overheated = False
            else:
                action_desc = "⚠️ <b>[재매수 관망]</b> 조기 매도 후 대기 중 (20일선 미돌파 또는 과열 상태)"

    new_state = {
        "position_state": pos,
        "overheated_flag": overheated,
    }

    return action_desc, new_state


# ==========================================
# 4. 메인 실행 및 알림 포맷팅
# ==========================================
def main():
    state = load_state()
    data = get_market_data()

    action_desc, new_state = evaluate_strategy(data, state)
    save_state(new_state)

    msg = (
        f"📊 <b>QLD/TQQQ 추세 추종 리포트 ({data['date']})</b>\n\n"
        f"• <b>판정 결과</b>: {action_desc}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• <b>QQQ 종가</b>: ${data['qqq_close']:.2f}\n"
        f"• <b>QLD 종가 (70%)</b>: ${data['qld_close']:.2f}\n"
        f"• <b>TQQQ 종가 (30%)</b>: ${data['tqqq_close']:.2f}\n"
        f"• <b>MA5 / MA20 / MA200</b>: ${data['ma5']:.2f} / ${data['ma20']:.2f} / ${data['ma200']:.2f}\n"
        f"• <b>200일선 이격도</b>: {data['disparity']*100:.2f}%\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• <b>포지션 상태</b>: {new_state['position_state']}\n"
        f"• <b>과열 플래그</b>: {'🔥 ON' if new_state['overheated_flag'] else 'OFF'}\n"
    )

    print(msg.replace("<b>", "").replace("</b>", ""))
    send_telegram(msg)


if __name__ == "__main__":
    main()
