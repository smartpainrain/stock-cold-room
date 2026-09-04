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

# 티커 변환 헬퍼 함수
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
    # 딕셔너리 매핑 확인
    for k, v in TICKER_DICT.items():
        if k.lower().replace(" ", "") == cleaned:
            return v
    # 6자리 숫자 코드 직접 입력 시 (.KS 우선 시도)
    if len(cleaned) == 6 and cleaned.isdigit():
        return f"{cleaned}.KS"
    if cleaned.endswith(".ks") or cleaned.endswith(".kq"):
        return cleaned.upper()
    return f"{cleaned}.KS"

def fetch_live_price(ticker: str):
    try:
        data = yf.Ticker(ticker).history(period="1d")
        if not data.empty:
            return int(data['Close'].iloc[-1])
    except Exception:
        pass
    # KS 실패 시 KQ 시도
    if ticker.endswith(".KS"):
        try:
            alt_ticker = ticker.replace(".KS", ".KQ")
            data = yf.Ticker(alt_ticker).history(period="1d")
            if not data.empty:
                return int(data['Close'].iloc[-1])
        except Exception:
            pass
    return 0

# 2. 세션 상태 초기화 (불필요한 컬럼 완전 제거)
TARGET_COLUMNS = ["종목명", "티커", "현재가"]

if 'stock_df' not in st.session_state or any(c not in st.session_state.stock_df.columns for c in TARGET_COLUMNS) or "보유비중(%)" in st.session_state.stock_df.columns:
    st.session_state.stock_df = pd.DataFrame([
        {"종목명": "삼성전자", "티커": "005930.KS", "현재가": fetch_live_price("005930.KS")},
        {"종목명": "SK하이닉스", "티커": "000660.KS", "현재가": fetch_live_price("000660.KS")},
        {"종목명": "한화에어로스페이스", "티커": "012450.KS", "현재가": fetch_live_price("012450.KS")},
    ])

# 3. 실시간 종목 등록 폼 (종목명만 입력)
st.markdown("#### 🎯 실시간 종목 모니터링")

with st.form("add_stock_form", clear_on_submit=True):
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        input_name = st.text_input("종목명 또는 종목코드(6자리)", placeholder="예: SK하이닉스 또는 000660")
    with col_btn:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        submitted = st.form_submit_button("신규 종목 추가")
    
    if submitted and input_name.strip():
        resolved = resolve_ticker(input_name)
        price = fetch_live_price(resolved)
        
        # 코스닥 대체 확인으로 티커 조정
        if price > 0 and resolved.endswith(".KS"):
            test_data = yf.Ticker(resolved).history(period="1d")
            if test_data.empty:
                resolved = resolved.replace(".KS", ".KQ")

        new_row = pd.DataFrame([{
            "종목명": input_name.strip(),
            "티커": resolved,
            "현재가": price
        }])
        
        st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
        st.rerun()

# 4. 종목 모니터링 표 (종목명, 티커, 현재가만 표시)
display_df = st.session_state.stock_df[TARGET_COLUMNS].copy()
edited_df = st.data_editor(display_df, num_rows="dynamic", use_container_width=True, hide_index=True)
st.session_state.stock_df = edited_df

# 5. 종목 삭제 영역
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
                st.rerun()

# 6. 개별 종목 3개월 종가 추이 차트
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
