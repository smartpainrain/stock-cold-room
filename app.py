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

# 2. 핵심 지표 요약 카드
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric(label="총 평가 자산", value="142,500,000 원", delta="+1,250,000 원")
col_m2.metric(label="포트폴리오 평균 초과수익(α)", value="+1.53%", delta="+0.12%")
col_m3.metric(label="관제 종목 수", value="6개", delta="Stable")
col_m4.metric(label="최대 낙폭 (MDD)", value="-2.4%", delta="-0.1% 안정")

st.markdown("<br>", unsafe_allow_html=True)

# 3. 세션 상태 초기화 (종목 데이터)
if 'stock_df' not in st.session_state:
    st.session_state.stock_df = pd.DataFrame({
        "종목명": ["아난티", "한화에어로스페이스", "대아티아이", "마이크로컨텍솔", "삼양식품", "셀트리온"],
        "티커": ["025980.KS", "012450.KS", "045390.KQ", "098120.KQ", "003230.KS", "068270.KS"],
        "현재가": [5500, 1164000, 3455, 40900, 1341000, 194600],
        "보유비중(%)": [10.0, 30.0, 10.0, 15.0, 25.0, 10.0],
        "초과수익(α)": [1.953, 1.424, 1.538, 2.702, 0.969, 0.657],
        "매집단계": ["L1", "L4", "L1", "L1", "L4", "L6"]
    })

st.markdown("#### 🎯 실시간 종목 모니터링 및 간편 등록")
st.caption("주요 종목은 이름만 넣어도 자동 조회되며, 아래 표에서 직접 값을 수정하거나 행을 추가/삭제할 수 있습니다.")

# --- 간편 종목 추가 폼 (자동 매핑 및 수동 보완) ---
# 자주 쓰는 종목 자동 매핑 사전
name_to_ticker = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "아난티": "025980.KS",
    "한화에어로스페이스": "012450.KS",
    "대아티아이": "045390.KQ",
    "마이크로컨텍솔": "098120.KQ",
    "삼양식품": "003230.KS",
    "셀트리온": "068270.KS",
    "LG에너지솔루션": "373220.KS"
}

with st.form("add_stock_form", clear_on_submit=True):
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    
    with f_col1:
        input_name = st.text_input("종목명", placeholder="예: 삼성전자 또는 직접입력")
    with f_col2:
        input_weight = st.number_input("보유비중(%)", min_value=0.0, max_value=100.0, value=10.0)
    with f_col3:
        input_alpha = st.number_input("초과수익(α %)", value=1.0)
    with f_col4:
        input_stage = st.selectbox("매집단계", ["L1", "L2", "L3", "L4", "L5", "L6"])
        
    submitted = st.form_submit_button("종목 추가 및 현재가 자동 조회")
    
    if submitted and input_name:
        # 사전에 있으면 티커 자동 할당, 없으면 사용자가 입력한 값이나 기본값 처리
        ticker = name_to_ticker.get(input_name, "")
        current_price = 0
        
        if ticker:
            try:
                live_data = yf.Ticker(ticker).history(period="1d")
                if not live_data.empty:
                    current_price = int(live_data['Close'].iloc[-1])
            except:
                pass
                
        # 자동 조회가 안 되었을 경우 기본값 지정 (표에서 나중에 직접 수정 가능)
        if current_price == 0:
            ticker = ticker if ticker else "005930.KS"
            current_price = 10000  # 기본 임시가 (표에서 바로 수정 가능)
            
        new_row = pd.DataFrame({
            "종목명": [input_name],
            "티커": [ticker],
            "현재가": [current_price],
            "보유비중(%)": [input_weight],
            "초과수익(α)": [input_alpha],
            "매집단계": [input_stage]
        })
        
        st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
        st.success(f"'{input_name}' 종목이 추가되었습니다! (현재가: {current_price:,}원 - 표에서 직접 수정 가능)")
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# 데이터 편집기 (여기서 현재가, 비중, 매집단계 등을 내 손으로 직접 자유롭게 수정 가능)
edited_df = st.data_editor(st.session_state.stock_df, num_rows="dynamic", use_container_width=True, hide_index=True)
st.session_state.stock_df = edited_df

st.markdown("<br>", unsafe_allow_html=True)

# 4. 인터랙티브 차트 드릴다운
st.markdown("#### 📈 종목별 심층 시계열 분석")

current_stocks = st.session_state.stock_df["종목명"].dropna().tolist()
if current_stocks:
    selected_stock = st.selectbox("상세 차트를 확인할 종목을 선택하세요", current_stocks)
    
    matched_row = st.session_state.stock_df[st.session_state.stock_df["종목명"] == selected_stock]
    if not matched_row.empty and "티커" in matched_row.columns:
        target_ticker = matched_row["티커"].values[0]
    else:
        target_ticker = "005930.KS"
else:
    selected_stock = "삼성전자"
    target_ticker = "005930.KS"

@st.cache_data(ttl=300)
def load_chart_data(ticker):
    try:
        data = yf.Ticker(str(ticker)).history(period="3mo")
        return data['Close']
    except Exception:
        return pd.Series()

chart_data = load_chart_data(target_ticker)

if not chart_data.empty:
    st.line_chart(chart_data)
    st.caption(f"* {selected_stock} ({target_ticker}) 최근 3개월 종가 추이 (실시간 연동)")
else:
    st.info("해당 종목의 시세 데이터를 불러오는 중이거나 유효하지 않은 티커입니다. 표의 '티커' 칸을 올바른 야후 티커(예: 005930.KS)로 수정해 보세요.")
