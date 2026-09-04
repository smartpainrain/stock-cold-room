import streamlit as st
import pandas as pd
import datetime
import yfinance as yf

# 1. 상단 타이틀 (미니멀하게 정돈)
st.markdown("### stock-cold-room", unsafe_allow_html=True)

# 2. 실시간 코스피 지수 연동 함수 (안정형)
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

# 상단 인포메이션 바
col1, col2 = st.columns([2, 1])
with col1:
    st.markdown(f"**{kospi_str}**")
with col2:
    now = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
    st.markdown(f"<div style='text-align: right; color: gray; font-size: 14px;'>갱신 {now}</div>", unsafe_allow_html=True)

st.divider()

# 3. 핵심 관제탑 데이터 프레임 (알파 분석 대상 목록)
@st.cache_data
def get_control_tower_data():
    return pd.DataFrame({
        "종목명": ["아난티", "한화에어로스페이스", "대아티아이", "마이크로컨텍솔", "삼양식품", "셀트리온"],
        "현재가": ["5,500", "1,164,000", "3,455", "40,900", "1,341,000", "194,600"],
        "초과수익(α)": ["+1.953%", "+1.424%", "+1.538%", "+2.702%", "+0.969%", "+0.657%"],
        "매집단계": ["L1", "L4", "L1", "L1", "L4", "L6"]
    })

df = get_control_tower_data()

# 테이블 출력
st.dataframe(df, use_container_width=True, hide_index=True)
