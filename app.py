import streamlit as st
import pandas as pd
import datetime
from zoneinfo import ZoneInfo
import yfinance as yf

# 1. 상단 타이틀 및 KST 실시간 시각
st.markdown("### stock-cold-room", unsafe_allow_html=True)

@st.cache_data(ttl=60)
def get_kospi_data():
    try:
        kospi = yf.Ticker("^KS11")
        df_k = kospi.history(period="2d")
        if len(df_k) >= 2:
            cur = df_k['Close'].iloc[-1]
            prev = df_k['Close'].iloc[-2]
            chg = cur - prev
            chg_pct = (chg / prev) * 100
            sign = "+" if chg > 0 else ""
            return f"KOSPI: {cur:,.2f} ({sign}{chg:,.2f}, {sign}{chg_pct:.2f}%)"
        elif len(df_k) == 1:
            cur = df_k['Close'].iloc[-1]
            return f"KOSPI: {cur:,.2f}"
    except Exception:
        pass
    return "KOSPI 통신 지연"

kospi_str = get_kospi_data()

col_h1, col_h2 = st.columns([2, 1])
with col_h1:
    st.markdown(f"**{kospi_str}**")
with col_h2:
    now = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m-%d %H:%M:%S")
    st.markdown(f"<div style='text-align: right; color: gray; font-size: 14px;'>갱신 {now} (KST)</div>", unsafe_allow_html=True)

st.divider()

# 티커 사전 및 헬퍼
TICKER_DICT = {
    "삼성전자": "005930.KS",
    "sk하이닉스": "000660.KS",
    "아난티": "025980.KS",
    "한화에어로스페이스": "012450.KS",
    "대아티아이": "045390.KQ",
    "마이크로컨텍솔": "098120.KQ",
    "삼양식품": "003230.KS",
    "셀트리온": "068270.KS",
    "lg에너지솔루션": "373220.KS",
    "현대차": "005380.KS",
    "기아": "000270.KS",
    "카카오": "035720.KS",
    "네이버": "035420.KS"
}

def resolve_ticker(name_or_code: str) -> str:
    cleaned = name_or_code.strip().lower().replace(" ", "")
    for k, v in TICKER_DICT.items():
        if k.lower().replace(" ", "") == cleaned:
            return v
    if len(cleaned) == 6 and cleaned.isdigit():
        return f"{cleaned}.KS"
    if cleaned.endswith(".ks") or cleaned.endswith(".kq"):
        return cleaned.upper()
    return f"{cleaned}.KS"

# 기술적 분석 연산 함수 (캐시 60초)
@st.cache_data(ttl=60)
def analyze_technical_signals(ticker: str):
    default_res = {"현재가": 0, "RSI": 50.0, "20일이격": 100.0, "추천": "🟡 관망"}
    try:
        hist = yf.Ticker(ticker).history(period="3mo")
        if hist.empty or len(hist) < 20:
            if ticker.endswith(".KS"):
                alt_ticker = ticker.replace(".KS", ".KQ")
                hist = yf.Ticker(alt_ticker).history(period="3mo")
            if hist.empty or len(hist) < 20:
                return default_res

        close = hist['Close']
        volume = hist['Volume']
        current_price = int(close.iloc[-1])

        # 이동평균선
        ma20 = close.rolling(window=20).mean().iloc[-1]
        ma60 = close.rolling(window=60).mean().iloc[-1] if len(close) >= 60 else ma20
        disp20 = (current_price / ma20) * 100

        # RSI 14
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0, 0.0001)
        rsi_series = 100 - (100 / (1 + rs))
        current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0

        # 거래량 배수 (당일 vs 5일 평균)
        vol_ma5 = volume.iloc[-6:-1].mean() if len(volume) >= 6 else volume.mean()
        vol_ratio = (volume.iloc[-1] / vol_ma5) if vol_ma5 > 0 else 1.0

        # 정량 스코어링
        rec = "🟡 관망"
        if current_rsi >= 75:
            rec = "🔴 매도"
        elif current_price < ma20 and current_price < ma60 and current_rsi > 50:
            rec = "🔴 매도"
        elif current_rsi <= 30:
            rec = "🔥 강력 매수"
        elif (current_price >= ma60) and (98.0 <= disp20 <= 103.0) and (vol_ratio >= 1.5):
            rec = "🔥 강력 매수"
        elif (current_price >= ma20) and (35.0 <= current_rsi <= 55.0):
            rec = "🟢 매수"
        elif current_rsi <= 38:
            rec = "🟢 매수"

        return {
            "현재가": current_price,
            "RSI": round(current_rsi, 1),
            "20일이격": round(disp20, 1),
            "추천": rec
        }
    except Exception:
        return default_res

# 2. 세션 상태 초기화
BASE_COLUMNS = ["종목명", "티커", "매수가"]
if 'stock_df' not in st.session_state or any(c not in st.session_state.stock_df.columns for c in BASE_COLUMNS):
    st.session_state.stock_df = pd.DataFrame([
        {"종목명": "삼성전자", "티커": "005930.KS", "매수가": 72000},
        {"종목명": "SK하이닉스", "티커": "000660.KS", "매수가": 165000},
        {"종목명": "한화에어로스페이스", "티커": "012450.KS", "매수가": 310000},
    ])

# 3. 신규 종목 등록 폼
st.markdown("#### 🎯 종목 모니터링")

with st.form("add_stock_form", clear_on_submit=True):
    col_input, col_buy, col_btn = st.columns([3, 2, 1])
    with col_input:
        input_name = st.text_input("종목명 또는 종목코드(6자리)", placeholder="예: SK하이닉스 또는 000660")
    with col_buy:
        input_buy = st.number_input("매수가 (원)", min_value=0, value=0, step=100)
    with col_btn:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        submitted = st.form_submit_button("신규 종목 추가")
    
    if submitted and input_name.strip():
        resolved = resolve_ticker(input_name)
        new_row = pd.DataFrame([{
            "종목명": input_name.strip(),
            "티커": resolved,
            "매수가": int(input_buy)
        }])
        st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
        st.rerun()

# 4. 데이터 에디터 변경사항 선반영 처리
# 이전 렌더링에서 st.data_editor를 통해 수정된 매수가가 있다면 세션 df에 즉각 반영
if "stock_editor" in st.session_state and "edited_rows" in st.session_state["stock_editor"]:
    edited_rows = st.session_state["stock_editor"]["edited_rows"]
    for row_idx, changes in edited_rows.items():
        if "매수가" in changes:
            st.session_state.stock_df.at[int(row_idx), "매수가"] = int(changes["매수가"])

# 5. 기술적 지표 및 수익률 연산 (수정된 매수가 기반)
display_rows = []
for idx, row in st.session_state.stock_df.iterrows():
    sig = analyze_technical_signals(row['티커'])
    cur_p = sig["현재가"]
    buy_p = int(row["매수가"])
    
    # 수익률 계산 (상승: 🔺 빨간색 느낌, 하락: 🔻 파란색 느낌)
    if buy_p > 0 and cur_p > 0:
        ret_rate = ((cur_p - buy_p) / buy_p) * 100
        if ret_rate > 0:
            ret_display = f"🔺 +{ret_rate:.2f}%"
        elif ret_rate < 0:
            ret_display = f"🔻 {ret_rate:.2f}%"
        else:
            ret_display = "0.00%"
    else:
        ret_display = "-"

    display_rows.append({
        "종목명": row["종목명"],
        "티커": row["티커"],
        "현재가": cur_p,
        "매수가": buy_p,
        "수익": ret_display,
        "20일이격": f"{sig['20일이격']}%",
        "RSI": sig["RSI"],
        "추천": sig["추천"]
    })

display_df = pd.DataFrame(display_rows)

st.caption("매수가 셀을 더블클릭하여 수정 후 엔터를 누르면 수익률과 추천이 즉시 갱신·보존됩니다.")

# 데이터 에디터에 key='stock_editor' 연결
edited_output = st.data_editor(
    display_df,
    key="stock_editor",
    column_config={
        "종목명": st.column_config.TextColumn(disabled=True),
        "티커": st.column_config.TextColumn(disabled=True),
        "현재가": st.column_config.NumberColumn(format="%d 원", disabled=True),
        "매수가": st.column_config.NumberColumn(format="%d 원", min_value=0, step=100),
        "수익": st.column_config.TextColumn(disabled=True),
        "20일이격": st.column_config.TextColumn(disabled=True),
        "RSI": st.column_config.NumberColumn(disabled=True),
        "추천": st.column_config.TextColumn(disabled=True),
    },
    use_container_width=True,
    hide_index=True
)

# 6. 종목 삭제 관리
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("#### 🗑️ 종목 삭제")
if not st.session_state.stock_df.empty:
    valid_stocks = st.session_state.stock_df["종목명"].dropna().tolist()
    if valid_stocks:
        del_col1, del_col2 = st.columns([3, 1])
        with del_col1:
            stock_to_delete = st.selectbox("삭제할 종목 선택", valid_stocks, key="del_select")
        with del_col2:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            if st.button("선택 종목 삭제"):
                st.session_state.stock_df = st.session_state.stock_df[st.session_state.stock_df["종목명"] != stock_to_delete].reset_index(drop=True)
                if "stock_editor" in st.session_state:
                    del st.session_state["stock_editor"]
                st.rerun()

# 7. 개별 종목 3개월 시계열 차트
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("#### 📈 종목별 3개월 종가 추이")
current_stocks = st.session_state.stock_df["종목명"].dropna().tolist()
if current_stocks:
    selected_stock = st.selectbox("차트를 확인할 종목을 선택하세요", current_stocks)
    matched_row = st.session_state.stock_df[st.session_state.stock_df["종목명"] == selected_stock]
    target_ticker = matched_row["티커"].values[0] if not matched_row.empty else "005930.KS"
    
    try:
        chart_data = yf.Ticker(str(target_ticker)).history(period="3mo")['Close']
        if not chart_data.empty:
            st.line_chart(chart_data)
        else:
            st.info("시세 데이터를 가져올 수 없습니다.")
    except Exception:
        st.info("차트 통신 지연 중입니다.")
