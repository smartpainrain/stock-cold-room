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

st.set_page_config(page_title="Stock Cold Room", layout="wide")

# -------------------------------------------------------------
# 1. 설정 및 GitHub / 텔레그램 연동
# -------------------------------------------------------------
def get_config(key):
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
        elif "mysql" in st.secrets and key in st.secrets["mysql"]:
            return str(st.secrets["mysql"][key]).strip()
        return None
    except Exception:
        return None

def send_telegram_alert(msg):
    token = get_config("TELEGRAM_TOKEN")
    chat_id = get_config("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=3)
        except Exception:
            pass

def load_portfolio():
    token, repo = get_config("GITHUB_TOKEN"), get_config("GITHUB_REPO")
    df = pd.DataFrame()
    
    if token and repo:
        url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}?ref=main&t={datetime.datetime.now().timestamp()}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                parsed = json.loads(base64.b64decode(res.json()["content"]).decode("utf-8"))
                if parsed:
                    df = pd.DataFrame(parsed)
        except Exception:
            pass

    if df.empty and os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                parsed = json.load(f)
                if parsed:
                    df = pd.DataFrame(parsed)
        except Exception:
            pass

    if df.empty:
        return pd.DataFrame(columns=["종목명", "코드", "매수가"])
    
    return df[["종목명", "코드", "매수가"]].copy()

def save_to_github(df):
    clean_df = df[["종목명", "코드", "매수가"]].copy()
    json_content = json.dumps(clean_df.to_dict(orient="records"), ensure_ascii=False, indent=2)
    
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write(json_content)
    except Exception:
        pass

    token, repo = get_config("GITHUB_TOKEN"), get_config("GITHUB_REPO")
    if not token or not repo:
        return False

    url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    try:
        res = requests.get(f"{url}?ref=main&t={datetime.datetime.now().timestamp()}", headers=headers, timeout=5)
        sha = res.json().get("sha") if res.status_code == 200 else None
        
        payload = {
            "message": f"Update portfolio: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": base64.b64encode(json_content.encode("utf-8")).decode("utf-8"),
            "branch": "main"
        }
        if sha:
            payload["sha"] = sha
        
        put_res = requests.put(url, headers=headers, json=payload, timeout=5)
        if put_res.status_code in [200, 201]:
            st.session_state["last_sync_time"] = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S")
            return True
        return False
    except Exception:
        return False

# -------------------------------------------------------------
# 2. 실시간 종합 분석 엔진 (초고속 데스크톱 API)
# -------------------------------------------------------------
TICKER_DICT = {
    "삼성전자": "005930", "sk하이닉스": "000660", "한화에어로스페이스": "012450", 
    "삼양식품": "003230", "현대차": "005380", "네이버": "035420", 
    "sk이노베이션": "096770", "한미반도체": "042700"
}

def resolve_code(name_or_code):
    cleaned = name_or_code.strip().lower().replace(" ", "")
    if len(cleaned) == 6 and cleaned.isdigit():
        return cleaned
    for k, v in TICKER_DICT.items():
        if k.lower().replace(" ", "") == cleaned:
            return v
    try:
        search_url = f"https://ac.finance.naver.com/ac?q={requests.utils.quote(name_or_code.strip())}&target=stock"
        headers = {"User-Agent": "Mozilla/5.0"}
        items = requests.get(search_url, headers=headers, timeout=3).json().get("items", [[]])[0]
        for item in items:
            if cleaned in str(item[1]).replace(" ", "").lower():
                return str(item[0])
    except Exception:
        pass
    return ""

@st.cache_data(ttl=30)
def fetch_full_stock_analysis(code: str, buy_price: int):
    default_res = {
        "현재가": 0, "수익": "-", "수급": "관망", "실적": "-", 
        "20일이격": "-", "RSI": 50.0, "추천": "🟡 관망"
    }
    if not code:
        return default_res

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # 1. 네이버 실시간 체결 데이터
    cur_p = 0
    try:
        url_rt = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
        rt_json = requests.get(url_rt, headers=headers, timeout=3).json()
        if "datas" in rt_json and rt_json["datas"]:
            cur_p = int(rt_json["datas"][0]["closePrice"].replace(",", ""))
            default_res["현재가"] = cur_p
    except Exception:
        pass

    # 2. 네이버 기본적 지표 (PER / EPS)
    try:
        url_basic = f"https://m.stock.naver.com/api/stock/{code}/basic"
        b_json = requests.get(url_basic, headers=headers, timeout=3).json()
        stock_info = b_json.get("stockItemTotalInfos", [{}])[0]
        per = stock_info.get("per", "")
        eps = stock_info.get("eps", "")
        if per and eps:
            default_res["실적"] = f"PER {per} / EPS {eps}"
    except Exception:
        pass

    # 3. 최근 5거래일 외인/기관 순매수 수급 트래커
    try:
        url_inv = f"https://m.stock.naver.com/api/stock/{code}/trend"
        t_json = requests.get(url_inv, headers=headers, timeout=3).json()
        biz_days = t_json.get("bizDays", [])[:5]
        
        frgn_sum = sum(int(str(d.get('frgnPureBuyQuant', '0')).replace(',', '')) for d in biz_days)
        orgn_sum = sum(int(str(d.get('organPureBuyQuant', '0')).replace(',', '')) for d in biz_days)

        if frgn_sum > 0 and orgn_sum > 0:
            default_res["수급"] = "🔥 쌍끌이 매수"
        elif frgn_sum < 0 and orgn_sum < 0:
            default_res["수급"] = "❄️ 양매도"
        elif frgn_sum > 0:
            default_res["수급"] = "📈 외인 순매수"
        elif orgn_sum > 0:
            default_res["수급"] = "🏢 기관 순매수"
    except Exception:
        pass

    # 4. 차트 기술적 분석 (RSI 및 20일 이격도)
    try:
        ticker = f"{code}.KS"
        hist = yf.Ticker(ticker).history(period="3mo")
        if hist.empty or len(hist) < 20:
            ticker = f"{code}.KQ"
            hist = yf.Ticker(ticker).history(period="3mo")
            
        if not hist.empty and len(hist) >= 20:
            close = hist['Close']
            current_p = cur_p if cur_p > 0 else int(close.iloc[-1])
            default_res["현재가"] = current_p
            
            ma20 = close.rolling(window=20).mean().iloc[-1]
            disp20 = (current_p / ma20) * 100
            default_res["20일이격"] = f"{disp20:.1f}%"

            delta = close.diff()
            rs = delta.clip(lower=0).rolling(14).mean() / (-delta.clip(upper=0)).rolling(14).mean().replace(0, 0.0001)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])
            default_res["RSI"] = round(rsi, 1)

            if rsi <= 30:
                default_res["추천"] = "🔥 강력 매수"
            elif rsi >= 75:
                default_res["추천"] = "🔴 매도"
            elif current_p >= ma20 and 35.0 <= rsi <= 55.0:
                default_res["추천"] = "🟢 매수"
    except Exception:
        pass

    # 5. 수익률 계산
    if buy_price > 0 and default_res["현재가"] > 0:
        ret = ((default_res["현재가"] - buy_price) / buy_price) * 100
        default_res["수익"] = f"🔺 +{ret:.2f}%" if ret > 0 else (f"🔻 {ret:.2f}%" if ret < 0 else "0.00%")

    # 6. 스나이퍼 텔레그램 발송 (당일 중복 발송 방지)
    alert_key = f"alert_{code}_{datetime.datetime.now().strftime('%Y%m%d')}"
    if default_res["추천"] == "🔥 강력 매수" and alert_key not in st.session_state:
        send_telegram_alert(f"🎯 [Stock Cold-Room 시그널]\n종목코드: {code}\n상태: 🔥 강력 매수 구간 (RSI: {default_res['RSI']})\n수급: {default_res['수급']}")
        st.session_state[alert_key] = True

    return default_res

# -------------------------------------------------------------
# 3. 화면 렌더링
# -------------------------------------------------------------
st.markdown("### 📡 Stock Cold-Room Terminal", unsafe_allow_html=True)

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
        return "KOSPI 통신 지연"

col_h1, col_h2 = st.columns([2, 1])
with col_h1:
    st.markdown(f"**{get_kospi_data()}**")
with col_h2:
    now = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m-%d %H:%M:%S")
    st.markdown(f"<div style='text-align: right; color: gray; font-size: 14px;'>갱신 {now} (KST)</div>", unsafe_allow_html=True)

st.divider()

if 'stock_df' not in st.session_state:
    st.session_state.stock_df = load_portfolio()

# 신규 종목 등록 폼
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
            st.error("종목을 찾을 수 없습니다. 올바른 6자리 코드를 입력하세요.")
        else:
            new_row = pd.DataFrame([{"종목명": input_name.strip(), "코드": code, "매수가": int(input_buy)}])
            st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
            save_to_github(st.session_state.stock_df)
            st.rerun()

# 테이블 데이터 생성
display_rows = []
for idx, row in st.session_state.stock_df.iterrows():
    code = str(row['코드'])
    buy_p = int(row["매수가"])
    analyzed = fetch_full_stock_analysis(code, buy_p)

    display_rows.append({
        "선택": False,
        "종목명": row["종목명"],
        "코드": code,
        "현재가": analyzed["현재가"],
        "매수가": buy_p,
        "수익": analyzed["수익"],
        "수급(5일)": analyzed["수급"],
        "실적전망": analyzed["실적"],
        "20일이격": analyzed["20일이격"],
        "RSI": analyzed["RSI"],
        "추천": analyzed["추천"]
    })

display_df = pd.DataFrame(display_rows)

last_sync = st.session_state.get("last_sync_time")
sync_label = f" | 💾 GitHub 동기화 완료: {last_sync}" if last_sync else ""
st.caption(f"⚡ 네이버 금융 초고속 수급/실적 엔진 연동 완료{sync_label}")

# 체크박스 기반 통합 데이터 에디터
edited_df = st.data_editor(
    display_df,
    key="stock_editor",
    column_config={
        "선택": st.column_config.CheckboxColumn("삭제", help="삭제할 종목을 체크하세요", default=False),
        "종목명": st.column_config.TextColumn(disabled=True),
        "코드": st.column_config.TextColumn(disabled=True),
        "현재가": st.column_config.NumberColumn(format="%d 원", disabled=True),
        "매수가": st.column_config.NumberColumn(format="%d 원", min_value=0, step=100),
        "수익": st.column_config.TextColumn(disabled=True),
        "수급(5일)": st.column_config.TextColumn(disabled=True),
        "실적전망": st.column_config.TextColumn(disabled=True),
        "20일이격": st.column_config.TextColumn(disabled=True),
        "RSI": st.column_config.NumberColumn(disabled=True),
        "추천": st.column_config.TextColumn(disabled=True),
    },
    use_container_width=True,
    hide_index=True
)

# 매수가 변경 실시간 반영
if "stock_editor" in st.session_state and "edited_rows" in st.session_state["stock_editor"]:
    edited_rows = st.session_state["stock_editor"]["edited_rows"]
    modified = False
    for row_idx, changes in edited_rows.items():
        if "매수가" in changes:
            st.session_state.stock_df.at[int(row_idx), "매수가"] = int(changes["매수가"])
            modified = True
    if modified:
        save_to_github(st.session_state.stock_df)

# 선택 종목 삭제 버튼
selected_rows = edited_df[edited_df["선택"] == True]
col_del_btn, _ = st.columns([2, 5])
with col_del_btn:
    if st.button(f"🗑️ 선택 종목 삭제 ({len(selected_rows)}개)", disabled=(len(selected_rows) == 0)):
        codes_to_remove = selected_rows["코드"].tolist()
        st.session_state.stock_df = st.session_state.stock_df[~st.session_state.stock_df["코드"].isin(codes_to_remove)].reset_index(drop=True)
        save_to_github(st.session_state.stock_df)
        if "stock_editor" in st.session_state:
            del st.session_state["stock_editor"]
        st.rerun()

# -------------------------------------------------------------
# 4. 개별 종목 3개월 종가 추이 차트 복원
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
