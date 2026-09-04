import streamlit as st
import pandas as pd
import datetime
from zoneinfo import ZoneInfo
import requests
import yfinance as yf
import json
import os

DATA_FILE = "portfolio.json"

# 영구 저장소(JSON 파일) 로드 및 저장 함수
def load_portfolio():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return pd.DataFrame(data)
        except Exception:
            pass
    # 파일이 없거나 깨졌을 때 기본값
    default_df = pd.DataFrame([
        {"종목명": "삼성전자", "코드": "005930", "매수가": 72000},
        {"종목명": "SK하이닉스", "코드": "000660", "매수가": 165000},
        {"종목명": "한화에어로스페이스", "코드": "012450", "매수가": 310000},
    ])
    save_portfolio(default_df)
    return default_df

def save_portfolio(df):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(df.to_dict(orient="records"), f, ensure_ascii=False, indent=2)

# 1. 상단 타이틀 및 KST 실시간 시각
st.markdown("### stock-cold-room", unsafe_allow_html=True)

@st.cache_data(ttl=15)
def get_kospi_data():
    try:
        url = "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
        data = res['datas'][0]
        cur = data['closePrice']
        diff = data['compareToPreviousClosePrice']
        rate = data['fluctuationsRatio']
        sign = "+" if float(diff.replace(",", "")) > 0 else ""
        return f"KOSPI: {cur} ({sign}{diff}, {sign}{rate}%)"
    except Exception:
        try:
            k = yf.Ticker("^KS11").history(period="2d")
            if len(k) >= 2:
                cur = k['Close'].iloc[-1]
                prev = k['Close'].iloc[-2]
                chg = cur - prev
                rate = (chg / prev) * 100
                sign = "+" if chg > 0 else ""
                return f"KOSPI: {cur:,.2f} ({sign}{chg:,.2f}, {sign}{rate:.2f}%)"
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

# 종목명/코드 매핑 사전
TICKER_DICT = {
    "삼성전자": "005930",
    "sk하이닉스": "000660",
    "아난티": "025980",
    "한화에어로스페이스": "012450",
    "대아티아이": "045390",
    "마이크로컨텍솔": "098120",
    "삼양식품": "003230",
    "셀트리온": "068270",
    "lg에너지솔루션": "373220",
    "현대차": "005380",
    "기아": "000270",
    "카카오": "035720",
    "네이버": "035420"
}

def resolve_code(name_or_code: str) -> str:
    cleaned = name_or_code.strip().lower().replace(" ", "")
    for k, v in TICKER_DICT.items():
        if k.lower().replace(" ", "") == cleaned:
            return v
    if len(cleaned) == 6 and cleaned.isdigit():
        return cleaned
    cleaned = cleaned.replace(".ks", "").replace(".kq", "")
    return cleaned

@st.cache_data(ttl=15)
def fetch_naver_realtime_price(code: str) -> int:
    try:
        url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
        if "datas" in res and len(res["datas"]) > 0:
            price_str = res["datas"][0]["closePrice"].replace(",", "")
            return int(price_str)
    except Exception:
        pass
    return 0

@st.cache_data(ttl=60)
def analyze_technical_signals(code: str, cur_price: int):
    default_res = {"RSI": 50.0, "20일이격": 100.0, "추천": "🟡 관망"}
    ticker = f"{code}.KS"
    try:
        hist = yf.Ticker(ticker).history(period="3mo")
        if hist.empty or len(hist) < 20:
            ticker = f"{code}.KQ"
            hist = yf.Ticker(ticker).history(period="3mo")
            if hist.empty or len(hist) < 20:
                return default_res

        close = hist['Close']
        volume = hist['Volume']
        current_price = cur_price if cur_price > 0 else int(close.iloc[-1])

        ma20 = close.rolling(window=20).mean().iloc[-1]
        ma60 = close.rolling(window=60).mean().iloc[-1] if len(close) >= 60 else ma20
        disp20 = (current_price / ma20) * 100

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0, 0.0001)
        rsi_series = 100 - (100 / (1 + rs))
        current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0

        vol_ma5 = volume.iloc[-6:-1].mean() if len(volume) >= 6 else volume.mean()
        vol_ratio = (volume.iloc[-1] / vol_ma5) if vol_ma5 > 0 else 1.0

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
            "RSI": round(current_rsi, 1),
            "20일이격": round(disp20, 1),
            "추천": rec
        }
    except Exception:
        return default_res

# 2. 영구 파일 기반 포트폴리오 로드
if 'stock_df' not in st.session_state:
    st.session_state.stock_df = load_portfolio()

# 3. 신규 종목 등록 폼
st.markdown("#### 🎯 종목 모니터링 (네이버 실시간 시세 연동)")

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
        code = resolve_code(input_name)
        new_row = pd.DataFrame([{
            "종목명": input_name.strip(),
            "코드": code,
            "매수가": int(input_buy)
        }])
        st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
        save_portfolio(st.session_state.stock_df)  # 파일 영구 저장
        st.rerun()

# 4. 데이터 에디터 매수가 변경사항 선반영 및 파일 영구 저장
if "stock_editor" in st.session_state and "edited_rows" in st.session_state["stock_editor"]:
    edited_rows = st.session_state["stock_editor"]["edited_rows"]
    modified = False
    for row_idx, changes in edited_rows.items():
        if "매수가" in changes:
            st.session_state.stock_df.at[int(row_idx), "매수가"] = int(changes["매수가"])
            modified = True
    if modified:
        save_portfolio(st.session_state.stock_df)

# 5. 실시간 가격 및 기술적 지표 계산
display_rows = []
for idx, row in st.session_state.stock_df.iterrows():
    code = row['코드']
    cur_p = fetch_naver_realtime_price(code)
    sig = analyze_technical_signals(code, cur_p)
    buy_p = int(row["매수가"])
    
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
        "코드": code,
        "현재가": cur_p,
        "매수가": buy_p,
        "수익": ret_display,
        "20일이격": f"{sig['20일이격']}%",
        "RSI": sig["RSI"],
        "추천": sig["추천"]
    })

display_df = pd.DataFrame(display_rows)

st.caption("⚡ 네이버페이 증권 실시간 체결가 기준으로 자동 갱신됩니다. 매수가 수정/삭제 내역은 새로고침해도 영구 보존됩니다.")

st.data_editor(
    display_df,
    key="stock_editor",
    column_config={
        "종목명": st.column_config.TextColumn(disabled=True),
        "코드": st.column_config.TextColumn(disabled=True),
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

# 6. 종목 삭제 관리 (영구 삭제 적용)
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
                save_portfolio(st.session_state.stock_df)  # 삭제 후 파일 영구 저장
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
    target_code = matched_row["코드"].values[0] if not matched_row.empty else "005930"
    
    try:
        chart_data = yf.Ticker(f"{target_code}.KS").history(period="3mo")['Close']
        if chart_data.empty:
            chart_data = yf.Ticker(f"{target_code}.KQ").history(period="3mo")['Close']
        if not chart_data.empty:
            st.line_chart(chart_data)
        else:
            st.info("시세 데이터를 가져올 수 없습니다.")
    except Exception:
        st.info("차트 통신 지연 중입니다.")
