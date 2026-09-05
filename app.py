import streamlit as st
import pandas as pd
import datetime
from zoneinfo import ZoneInfo
import requests
import yfinance as yf
import json
import base64
import os

DATA_FILE = "portfolio.json"

# -------------------------------------------------------------
# GitHub API 연동 함수 (Secrets 하위 섹션 방어 로직 적용)
# -------------------------------------------------------------
def get_github_config():
    token = None
    repo = None
    try:
        # 1. 최상단 키 조회 시도
        if "GITHUB_TOKEN" in st.secrets:
            token = str(st.secrets["GITHUB_TOKEN"]).strip()
        # 2. mysql 등 하위 섹션에 잘못 묶였을 경우 대비
        elif "mysql" in st.secrets and "GITHUB_TOKEN" in st.secrets["mysql"]:
            token = str(st.secrets["mysql"]["GITHUB_TOKEN"]).strip()

        if "GITHUB_REPO" in st.secrets:
            repo = str(st.secrets["GITHUB_REPO"]).strip()
        elif "mysql" in st.secrets and "GITHUB_REPO" in st.secrets["mysql"]:
            repo = str(st.secrets["mysql"]["GITHUB_REPO"]).strip()
            
        return token, repo
    except Exception:
        return None, None

def load_portfolio():
    token, repo = get_github_config()
    
    # 1. GitHub API 원격 로드 (타임스탬프 파라미터로 캐시 원천 차단)
    if token and repo:
        url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}?ref=main&t={datetime.datetime.now().timestamp()}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        }
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                file_data = res.json()
                decoded_content = base64.b64decode(file_data["content"]).decode("utf-8")
                parsed_json = json.loads(decoded_content)
                if parsed_json:
                    return pd.DataFrame(parsed_json)
            elif res.status_code != 404:
                st.error(f"🚨 GitHub 파일 불러오기 실패 (HTTP {res.status_code}): {res.text}")
        except Exception as e:
            st.error(f"🚨 GitHub API 연결 실패: {e}")

    # 2. 로컬 파일 확인
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data:
                    return pd.DataFrame(data)
        except Exception:
            pass

    # 3. GitHub 연결 실패 시 빈 데이터프레임 반환 (기존 하드코딩 종목 부활 방지)
    st.warning("⚠️ GitHub에 저장된 종목 데이터를 가져오지 못했습니다. Secrets 설정과 portfolio.json을 확인하세요.")
    return pd.DataFrame(columns=["종목명", "코드", "매수가"])

def save_to_github(df):
    data_dict = df.to_dict(orient="records")
    json_content = json.dumps(data_dict, ensure_ascii=False, indent=2)
    
    # 로컬 파일 즉시 백업
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write(json_content)
    except Exception:
        pass

    token, repo = get_github_config()
    if not token or not repo:
        st.error("🚨 Streamlit Secrets에 GITHUB_TOKEN 또는 GITHUB_REPO가 설정되어 있지 않습니다.")
        return False

    url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    try:
        # 최신 SHA 조회
        res = requests.get(f"{url}?ref=main&t={datetime.datetime.now().timestamp()}", headers=headers, timeout=5)
        sha = res.json().get("sha") if res.status_code == 200 else None

        encoded_content = base64.b64encode(json_content.encode("utf-8")).decode("utf-8")
        payload = {
            "message": f"Update portfolio: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": encoded_content,
            "branch": "main"
        }
        if sha:
            payload["sha"] = sha

        put_res = requests.put(url, headers=headers, json=payload, timeout=5)
        if put_res.status_code in [200, 201]:
            st.toast("✅ GitHub 동기화 성공!", icon="💾")
            return True
        else:
            st.error(f"🚨 GitHub 저장 실패 (HTTP {put_res.status_code}): {put_res.json().get('message')}")
            return False
    except Exception as e:
        st.error(f"🚨 GitHub 저장 요청 에러: {e}")
        return False

# -------------------------------------------------------------
# 1. 상단 타이틀 및 실시간 KOSPI
# -------------------------------------------------------------
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

# -------------------------------------------------------------
# 2. 종목 자동 매칭 로직 (사전 + 네이버 금융 자동 검색)
# -------------------------------------------------------------
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
    "네이버": "035420",
    "sk이노베이션": "096770",
    "한미반도체": "042700"
}

def resolve_code(name_or_code: str) -> str:
    cleaned = name_or_code.strip().lower().replace(" ", "")
    if len(cleaned) == 6 and cleaned.isdigit():
        return cleaned
    for k, v in TICKER_DICT.items():
        if k.lower().replace(" ", "") == cleaned:
            return v
    try:
        search_url = f"https://ac.finance.naver.com/ac?q={requests.utils.quote(name_or_code.strip())}&target=stock"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(search_url, headers=headers, timeout=3).json()
        items = res.get("items", [[]])[0]
        for item in items:
            code_cand = str(item[0])
            name_cand = str(item[1]).replace(" ", "").lower()
            if cleaned == name_cand or cleaned in name_cand:
                return code_cand
    except Exception:
        pass
    return ""

@st.cache_data(ttl=15)
def fetch_naver_realtime_price(code: str) -> int:
    if not code:
        return 0
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
    if not code:
        return default_res
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

        return {"RSI": round(current_rsi, 1), "20일이격": round(disp20, 1), "추천": rec}
    except Exception:
        return default_res

# -------------------------------------------------------------
# 3. 포트폴리오 세션 초기화
# -------------------------------------------------------------
if 'stock_df' not in st.session_state:
    st.session_state.stock_df = load_portfolio()

# -------------------------------------------------------------
# 4. 신규 종목 추가
# -------------------------------------------------------------
st.markdown("#### 🎯 종목 모니터링 (네이버 실시간 시세 연동)")

with st.form("add_stock_form", clear_on_submit=True):
    col_input, col_buy, col_btn = st.columns([3, 2, 1])
    with col_input:
        input_name = st.text_input("종목명 또는 종목코드(6자리)", placeholder="예: 한미반도체 또는 042700")
    with col_buy:
        input_buy = st.number_input("매수가 (원)", min_value=0, value=0, step=100)
    with col_btn:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        submitted = st.form_submit_button("신규 종목 추가")
    
    if submitted and input_name.strip():
        code = resolve_code(input_name)
        if not code:
            st.error("종목코드를 찾을 수 없습니다. 올바른 6자리 종목코드를 직접 입력해 주세요.")
        else:
            new_row = pd.DataFrame([{"종목명": input_name.strip(), "코드": code, "매수가": int(input_buy)}])
            st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
            save_to_github(st.session_state.stock_df)
            st.rerun()

# -------------------------------------------------------------
# 5. 데이터 에디터 (매수가 수정 감지 및 즉시 동기화)
# -------------------------------------------------------------
if "stock_editor" in st.session_state and "edited_rows" in st.session_state["stock_editor"]:
    edited_rows = st.session_state["stock_editor"]["edited_rows"]
    modified = False
    for row_idx, changes in edited_rows.items():
        if "매수가" in changes:
            st.session_state.stock_df.at[int(row_idx), "매수가"] = int(changes["매수가"])
            modified = True
    if modified:
        save_to_github(st.session_state.stock_df)

display_rows = []
for idx, row in st.session_state.stock_df.iterrows():
    code = str(row['코드'])
    cur_p = fetch_naver_realtime_price(code)
    sig = analyze_technical_signals(code, cur_p)
    buy_p = int(row["매수가"])
    
    if buy_p > 0 and cur_p > 0:
        ret_rate = ((cur_p - buy_p) / buy_p) * 100
        ret_display = f"🔺 +{ret_rate:.2f}%" if ret_rate > 0 else (f"🔻 {ret_rate:.2f}%" if ret_rate < 0 else "0.00%")
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

st.caption("⚡ 네이버페이 증권 실시간 체결가 기준으로 자동 갱신됩니다. 수정 사항은 GitHub 원격 저장소에 즉시 동기화됩니다.")

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

# -------------------------------------------------------------
# 6. 종목 삭제 관리
# -------------------------------------------------------------
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
                save_to_github(st.session_state.stock_df)
                if "stock_editor" in st.session_state:
                    del st.session_state["stock_editor"]
                st.rerun()

# -------------------------------------------------------------
# 7. 개별 종목 3개월 차트
# -------------------------------------------------------------
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("#### 📈 종목별 3개월 종가 추이")
current_stocks = st.session_state.stock_df["종목명"].dropna().tolist()
if current_stocks:
    selected_stock = st.selectbox("차트를 확인할 종목을 선택하세요", current_stocks)
    matched_row = st.session_state.stock_df[st.session_state.stock_df["종목명"] == selected_stock]
    target_code = str(matched_row["코드"].values[0]) if not matched_row.empty else "005930"
    
    if target_code:
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
