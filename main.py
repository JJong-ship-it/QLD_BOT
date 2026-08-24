import json
import os
import pandas as pd
import requests
import yfinance as yf

# 깃허브 시크릿 이름('TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID')과 동기화
STATE_FILE = "state.json"
TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_TOKEN", "8832709732:AAEhrq3lVI1nVwp5uLwV0uE_Zegrd9pTAwA"
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5763039504")


def load_state():
    """이전 매매 상태를 불러옵니다 (기본값: 현재 보유 중)."""
    default_state = {
        "position_state": "HOLDING",  # CASH_AFTER_BEAR, HOLDING, CASH_AFTER_EARLY_EXIT
        "overheated_flag": False,
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
        print(f"상태 파일 저장 에러: {e}")


def send_telegram_message(message):
    """텔레그램으로 메시지를 전송하는 함수"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "로컬테스트용토큰":
        print("⚠️ 텔레그램 토큰이 설정되지 않았습니다.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("📲 텔레그램 알림 전송 성공!")
        else:
            print(f"❌ 텔레그램 전송 실패: {response.text}")
    except Exception as e:
        print(f"❌ 텔레그램 에러 발생: {e}")


def check_trading_signal():
    # 1. 상태 로드
    state = load_state()
    pos = state.get("position_state", "HOLDING")
    overheated = state.get("overheated_flag", False)

    # 2. 최신 데이터 수집 (QQQ, QLD)
    qqq_raw = yf.download("QQQ", period="1y", interval="1d", progress=False)
    qld_raw = yf.download("QLD", period="5d", interval="1d", progress=False)

    if qqq_raw.empty or qld_raw.empty:
        print("데이터 수집 실패")
        return

    # 데이터프레임 정리 (멀티인덱스 대응)
    qqq_df = pd.DataFrame()
    qqq_df["close"] = (
        qqq_raw["Close"].iloc[:, 0]
        if isinstance(qqq_raw["Close"], pd.DataFrame)
        else qqq_raw["Close"]
    )
    qld_close = (
        float(qld_raw["Close"].iloc[-1, 0])
        if isinstance(qld_raw["Close"], pd.DataFrame)
        else float(qld_raw["Close"].iloc[-1])
    )

    # 3. 이동평균선 및 이격도 계산 (5일선, 20일선, 200일선)
    qqq_df["ma5"] = qqq_df["close"].rolling(window=5).mean()
    qqq_df["ma20"] = qqq_df["close"].rolling(window=20).mean()
    qqq_df["ma200"] = qqq_df["close"].rolling(window=200).mean()

    prev_row = qqq_df.iloc[-1]
    curr_close = float(prev_row["close"])
    ma5 = float(prev_row["ma5"])
    ma20 = float(prev_row["ma20"])
    ma200 = float(prev_row["ma200"])
    current_disparity = curr_close / ma200
    disparity_pct = (current_disparity - 1) * 100

    # 4. 추세 및 상태 판정
    is_bull_trend = ma5 >= ma200
    is_above_ma20 = curr_close > ma20

    action_text = ""

    # [규칙 1] 대세 하락 탈출 (데드크로스)
    if not is_bull_trend:
        if pos == "HOLDING":
            action_text = "🔴 **[대세 매도 / 전량 현금화]**\nMA5 < MA200 데드크로스 발생 (손실 방어)"
        else:
            action_text = "⚪ **[하락장 대기]**\nMA5 < MA200 역배열 구간 (현금 100% 관망 유지)"

        pos = "CASH_AFTER_BEAR"
        overheated = False

    # [규칙 2, 3, 4] 대세 상승장 (MA5 >= MA200)
    else:
        if pos == "CASH_AFTER_BEAR":
            # 1차 신규 매수: 골든크로스 + 이격도 15% 이하 + 20일선 위
            if (current_disparity <= 1.15) and is_above_ma20:
                action_text = "🟢 **[1차 신규 매수]**\n골든크로스 + 이격도 15% 이하 + 20일선 안착 확인 (QLD 100% 매수)"
                pos = "HOLDING"
                overheated = False
            else:
                action_text = f"⚠️ **[1차 진입 관망]**\n골든크로스 상태이나 20일선 아래이거나 이격 과열({disparity_pct:+.1f}%)"

        elif pos == "HOLDING":
            # 18% 과열 도달 시 플래그 ON
            if current_disparity >= 1.18:
                overheated = True

            # 조기 익절: 과열 플래그 ON + 20일선 이탈
            if overheated and (not is_above_ma20):
                action_text = "🔥 **[고점 조기 익절]**\n18% 과열 기록 후 20일선 이탈 (QLD 전량 매도 후 현금화)"
                pos = "CASH_AFTER_EARLY_EXIT"
                overheated = False
            else:
                flag_status = "🔥 ON (과열 주의)" if overheated else "OFF (안정)"
                action_text = (
                    f"🔵 **[보유 유지]**\n상승 추세 지속 중 (과열 플래그: {flag_status})"
                )

        elif pos == "CASH_AFTER_EARLY_EXIT":
            # 눌림목 재매수: 20일선 회복 + 이격도 15% 이하
            if is_above_ma20 and (current_disparity <= 1.15):
                action_text = "🟢 **[눌림목 재매수]**\n20일선 상향 돌파 & 이격도 15% 이하 안착 (QLD 100% 재진입)"
                pos = "HOLDING"
                overheated = False
            else:
                action_text = "⚠️ **[재매수 관망]**\n조기 매도 후 대기 중 (20일선 회복 또는 15% 이하 냉각 대기)"

    # 5. 상태 저장
    new_state = {
        "position_state": pos,
        "overheated_flag": overheated,
    }
    save_state(new_state)

    # 6. 메시지 구성 및 전송
    msg = f"📈 **QLD 추세 추종 봇 리포트**\n\n"
    msg += f"• **판정 행동**: {action_text}\n\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"• QQQ 종가: `${curr_close:.2f}`\n"
    msg += f"• QLD 종가: `${qld_close:.2f}`\n"
    msg += f"• 5일선 / 20일선: `${ma5:.2f}` / `${ma20:.2f}`\n"
    msg += f"• 200일선: `${ma200:.2f}`\n"
    msg += f"• 200일선 이격도: `{disparity_pct:+.2f}%`\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n"
    msg += f"• 포지션 상태: `{pos}`\n"
    msg += f"• 과열 플래그: `{'🔥 ON' if overheated else 'OFF'}`\n"

    print(msg)
    send_telegram_message(msg)


if __name__ == "__main__":
    check_trading_signal()
