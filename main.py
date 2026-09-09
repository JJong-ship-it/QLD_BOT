import os
import json
import requests
import yfinance as yf
import pandas as pd

STATE_FILE = "strategy_state.json"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(message: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("[Error] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 비어있습니다.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # Markdown 대신 문법 충돌이 없는 HTML 모드 사용
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        res_data = res.json()
        if not res_data.get("ok"):
            print(f"[Telegram 전송 실패] HTTP {res.status_code}: {res_data}")
        else:
            print("[Telegram 전송 성공]")
    except Exception as e:
        print(f"[Telegram 통신 에러]: {e}")

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "position": "CASH",
        "entry_date": None,
        "entry_price": 0.0,
        "cooldown_counter": 0,
        "overheated": False
    }

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

def main():
    state = load_state()

    print(">> QQQ 데이터 다운로드 중...")
    qqq = yf.download("QQQ", period="18mo", interval="1d", progress=False)
    if qqq.empty:
        send_telegram("❌ <b>[Macro Gate]</b> QQQ 데이터 다운로드 실패")
        return

    if isinstance(qqq.columns, pd.MultiIndex):
        qqq_c = qqq["Close"]["QQQ"]
        qqq_h = qqq["High"]["QQQ"]
        qqq_l = qqq["Low"]["QQQ"]
    else:
        qqq_c = qqq["Close"]
        qqq_h = qqq["High"]
        qqq_l = qqq["Low"]

    df = pd.DataFrame(index=qqq_c.index)
    df["Close"] = qqq_c
    df["High"] = qqq_h
    df["Low"] = qqq_l

    # 기술적 지표 계산
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()
    df["Disparity"] = df["Close"] / df["MA200"]

    df["Swing_High"] = df["High"].shift(1).rolling(20).max()
    df["Swing_Low"] = df["Low"].shift(1).rolling(20).min()
    df["Eq_Val"] = (df["Swing_High"] + df["Swing_Low"]) / 2

    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.rolling(9).mean()
    df["MACD_Hist"] = macd - signal

    df = df.dropna(subset=["MA200"])
    latest = df.iloc[-1]
    date_str = latest.name.strftime("%Y-%m-%d")

    close_p = float(latest["Close"])
    ma20 = float(latest["MA20"])
    ma50 = float(latest["MA50"])
    ma200 = float(latest["MA200"])
    disp = float(latest["Disparity"])
    eq_val = float(latest["Eq_Val"])
    macd_hist = float(latest["MACD_Hist"])

    current_pos = state["position"]
    cooldown = state["cooldown_counter"]
    overheated = state["overheated"]

    action = "HOLD"
    action_reason = ""

    # 1. 과열 체크
    if disp >= 1.20:
        overheated = True
        state["overheated"] = True

    # 2. 포지션별 로직
    if current_pos == "HOLDING":
        exit_bear = ma20 < ma200
        exit_smc = overheated and (close_p <= ma20) and (close_p < eq_val)

        if exit_bear or exit_smc:
            action = "SELL_ALL"
            action_reason = "SMC 과열 조기 익절" if exit_smc else "거시 하락 탈출 (MA20 &lt; MA200)"
            
            pnl = (close_p - state["entry_price"]) / state["entry_price"] * 100
            state["cooldown_counter"] = 15 if pnl < 0 else 0
            state["position"] = "CASH"
            state["overheated"] = False
            state["entry_date"] = None
            state["entry_price"] = 0.0

    elif current_pos == "CASH":
        if cooldown > 0:
            state["cooldown_counter"] -= 1

        is_macro_bull = (ma50 >= ma200) and (close_p >= ma200)
        is_above_ma20 = close_p > ma20
        macd_bull = macd_hist > 0
        cond_entry = (
            (state["cooldown_counter"] == 0)
            and is_macro_bull
            and (ma20 >= ma200)
            and is_above_ma20
            and (disp <= 1.16)
            and macd_bull
        )

        if cond_entry:
            action = "BUY_ALL"
            action_reason = "정배열 안착 및 매크로 게이트 진입 조건 만족"
            state["position"] = "HOLDING"
            state["entry_date"] = date_str
            state["entry_price"] = close_p
            state["overheated"] = False

    save_state(state)

    # 3. 메시지 조립 (HTML 태그 사용)
    pnl_str = ""
    if current_pos == "HOLDING" and state["entry_price"] > 0:
        cur_pnl = (close_p - state["entry_price"]) / state["entry_price"] * 100
        pnl_str = f"• 진입일: {state['entry_date']} (QQQ ${state['entry_price']:.2f})\n• 현재 평가손익: <b>{cur_pnl:+.2f}%</b>\n"

    status_icon = "🟢" if action == "BUY_ALL" else ("🔴" if action == "SELL_ALL" else "⚪")

    msg = f"""{status_icon} <b>[Macro Gate 포트폴리오 일일 브리핑]</b>
📅 기준일: <code>{date_str}</code>

📊 <b>현재 포지션:</b> <code>{current_pos}</code>
🎯 <b>오늘의 주문:</b> <b>{action}</b>
💡 <b>사유:</b> {action_reason if action_reason else "변동 없음 (기존 상태 유지)"}
{pnl_str}
📈 <b>QQQ 주요 지표 현황</b>
• 종가: ${close_p:.2f}
• 20일선(MA20): ${ma20:.2f}
• 50일선(MA50): ${ma50:.2f}
• 200일선(MA200): ${ma200:.2f}
• 200일선 이격도: {disp:.3f} (과열기준: 1.20)
• MACD Hist: {macd_hist:+.2f}
• 잔여 쿨다운: {state['cooldown_counter']} 거래일

📌 <b>포트폴리오 비중 (매수 시):</b>
QLD 60% / TQQQ 40% (현금 시 SGOV 100%)
"""
    send_telegram(msg)

if __name__ == "__main__":
    main()
