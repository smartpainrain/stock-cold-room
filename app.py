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

# 2. 핵심 지표 요약 카드 (Summary Cards)
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric(label="총 평가 자산", value="142,500,000 원", delta="+1,250,000 원")
col_m2.metric(label="포트폴리오 평균 초과수익(α)", value="+1.53%", delta="+0.12%")
col_m3.metric(label="관제 종목 수", value="6개", delta="Stable")
col_m4.metric(label="최대 낙폭 (MDD)", value="-2.4%", delta="-0.1% 안정")

st.markdown("<br>", unsafe_allow_html=True)

# 3. 관제탑 데이터 및 리스크/비중 관리 데이터 프레임
@st.cache_data
def get_control_tower_data():
    return pd.DataFrame({
        "종목명": ["아난티", "한화에어로스페이스", "대아티아이", "마이크로컨텍솔", "삼양식품", "셀트리온"],
        "현재가": [5500, 1164000, 3455, 40900, 1341000, 194600],
        "보유비중(%)": [10.0, 30.0, 10.0, 15.0, 25.0, 10.0],
        "초과수익(α)": [1.953, 1.424, 1.538, 2.702, 0.969, 0.657],
        "매집단계": ["L1", "L4", "L1", "L1", "L4", "L6"]
    })

df = get_control_tower_data()

st.markdown("#### 🎯 알파 관제탑 및 리스크 모니터링")

def color_alpha(val):
    color = 'color: #ff4b4b;' if val > 1.5 else 'color: #1c83e1;'
    return color

styled_df = df.style.map(color_alpha, subset=['초과수익(α)'])
st.dataframe(styled_df, use_container_width=True, hide_index=True)

st.markdown("<br>", unsafe_allow_html=True)

# 4. 인터랙티브 차트 드릴다운 (Drill-down Charting)
st.markdown("#### 📈 종목별 심층 시계열 분석")
selected_stock = st.selectbox("상세 차트를 확인할 종목을 선택하세요", df["종목명"].tolist())

ticker_map = {
    "아난티": "025980.KS",
    "한화에어로스페이스": "012450.KS",
    "대아티아이": "045390.KQ",
    "마이크로컨텍솔": "098120.KQ",
    "삼양식품": "003230.KS",
    "셀트리온": "068270.KS"
}

target_ticker = ticker_map.get(selected_stock, "005930.KS")

@st.cache_data(ttl=300)
def load_chart_data(ticker):
    try:
        data = yf.Ticker(ticker).history(period="3mo")
        return data['Close']
    except Exception:
        return pd.Series()

chart_data = load_chart_data(target_ticker)

if not chart_data.empty:
    st.line_chart(chart_data)
    st.caption(f"* {selected_stock} ({target_ticker}) 최근 3개월 종가 추이")
else:
    st.info("해당 종목의 시세 데이터를 불러오는 중이거나 지연되고 있습니다.")
