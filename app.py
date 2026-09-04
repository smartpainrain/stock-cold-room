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

# 2. 세션 상태 초기화
if 'stock_df' not in st.session_state:
    st.session_state.stock_df = pd.DataFrame({
        "종목명": ["아난티", "한화에어로스페이스", "대아티아이", "마이크로컨텍솔", "삼양식품", "셀트리온"],
        "티커": ["025980.KS", "012450.KS", "045390.KQ", "098120.KQ", "003230.KS", "068270.KS"],
        "현재가": [5500, 1164000, 3455, 40900, 1341000, 194600],
        "매수 단가": [5200, 1100000, 3300, 40000, 1300000, 190000],
        "매수 수량": [100, 10, 200, 50, 5, 20],
        "추천": ["매수", "관망", "매수", "매수", "관망", "매도"]
    })

# 데이터 연산 및 파생 컬럼 생성 (평가금액, 손익, 수익률)
df = st.session_state.stock_df.copy()
try:
    df['현재가'] = pd.to_numeric(df['현재가'], errors='coerce').fillna(0)
    df['매수 단가'] = pd.to_numeric(df['매수 단가'], errors='coerce').fillna(0)
    df['매수 수량'] = pd.to_numeric(df['매수 수량'], errors='coerce').fillna(0)
    
    df['평가금액'] = df['현재가'] * df['매수 수량']
    df['투자원금'] = df['매수 단가'] * df['매수 수량']
    df['평가손익'] = df['평가금액'] - df['투자원금']
    df['수익률(%)'] = ((df['평가손익'] / df['투자원금']) * 100).round(2)
    
    total_eval = df['평가금액'].sum()
    total_invest = df['투자원금'].sum()
    total_profit = df['평가손익'].sum()
    total_return_pct = (total_profit / total_invest * 100) if total_invest > 0 else 0.0
except:
    total_eval, total_invest, total_profit, total_return_pct = 0, 0, 0, 0.0

# 요약 카드 렌더링
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric(label="총 평가 자산", value=f"{total_eval:,.0f} 원", delta=f"{total_profit:+,.0f} 원")
col_m2.metric(label="총 투자 원금", value=f"{total_invest:,.0f} 원")
col_m3.metric(label="포트폴리오 총 수익률", value=f"{total_return_pct:+.2f}%")
col_m4.metric(label="관제 종목 수", value=f"{len(df)}개")

st.markdown("<br>", unsafe_allow_html=True)

# 3. 실시간 종목 모니터링 및 관리 테이블
st.markdown("#### 🎯 실시간 종목 모니터링 및 관리")
st.caption("표에서 매수 단가, 수량, 추천 상태 등을 직접 수정할 수 있습니다.")

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

# 종목 추가 폼
with st.form("add_stock_form", clear_on_submit=True):
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        input_name = st.text_input("종목명", placeholder="예: 삼성전자")
    with f_col2:
        input_buy_price = st.number_input("매수 단가 (원)", min_value=0, value=10000, step=100)
    with f_col3:
        input_qty = st.number_input("매수 수량", min_value=1, value=10)
    with f_col4:
        input_recommend = st.selectbox("추천 상태", ["매수", "관망", "매도"])
        
    submitted = st.form_submit_button("신규 종목 추가 (현재가 자동 조회)")
    
    if submitted and input_name:
        ticker = name_to_ticker.get(input_name, "005930.KS")
        current_price = input_buy_price
        try:
            live_data = yf.Ticker(ticker).history(period="1d")
            if not live_data.empty:
                current_price = int(live_data['Close'].iloc[-1])
        except:
            pass
            
        new_row = pd.DataFrame({
            "종목명": [input_name],
            "티커": [ticker],
            "현재가": [current_price],
            "매수 단가": [input_buy_price],
            "매수 수량": [input_qty],
            "추천": [input_recommend]
        })
        
        st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
        st.success(f"'{input_name}' 종목이 추가되었습니다! (실시간 현재가: {current_price:,}원)")
        st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# 데이터 편집기
edited_df = st.data_editor(st.session_state.stock_df, num_rows="dynamic", use_container_width=True, hide_index=True)
st.session_state.stock_df = edited_df

# 종목 삭제 영역
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("#### 🗑️ 종목 삭제 관리")
if not st.session_state.stock_df.empty:
    del_col1, del_col2 = st.columns([3, 1])
    with del_col1:
        stock_to_delete = st.selectbox("삭제할 종목 선택", st.session_state.stock_df["종목명"].tolist(), key="del_select")
    with del_col2:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        if st.button("선택 종목 삭제"):
            st.session_state.stock_df = st.session_state.stock_df[st.session_state.stock_df["종목명"] != stock_to_delete].reset_index(drop=True)
            st.success(f"'{stock_to_delete}' 종목이 삭제되었습니다.")
            st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# 4. 고급 포트폴리오 다차원 분석 시각화
st.markdown("#### 📊 포트폴리오 다차원 분석")
an_col1, an_col2 = st.columns(2)

with an_col1:
    st.markdown("**종목별 자산 비중 (평가금액 기준)**")
    if not df.empty and total_eval > 0:
        df['비중(%)'] = (df['평가금액'] / total_eval * 100).round(1)
        allocation_chart_data = df.set_index("종목명")["비중(%)"]
        st.bar_chart(allocation_chart_data)
    else:
        st.info("데이터가 부족합니다.")

with an_col2:
    st.markdown("**종목별 평가 손익 (원)**")
    if not df.empty:
        pnl_chart_data = df.set_index("종목명")["평가손익"]
        st.bar_chart(pnl_chart_data)
    else:
        st.info("데이터가 부족합니다.")

st.markdown("<br>", unsafe_allow_html=True)

# 5. 인터랙티브 차트 드릴다운
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
    st.info("해당 종목의 시세 데이터를 불러오는 중이거나 유효하지 않은 티커입니다.")
