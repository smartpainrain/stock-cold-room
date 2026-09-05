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
# 1. 시스템 설정 및 텔레그램 / GitHub API
# -------------------------------------------------------------
st.set_page_config(page_title="Stock Cold Room", layout="wide")

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
                if parsed: df = pd.DataFrame(parsed)
        except Exception:
            pass

    if df.empty and os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                parsed = json.load(f)
                if parsed: df = pd.DataFrame(parsed)
        except Exception:
            pass

    if df.empty:
        df = pd.DataFrame(columns=["그룹", "종목명", "코드", "매수가"])
    
    # 레거시 데이터 호환성 유지 (그룹 컬럼이 없으면 자동 생성)
    if "그룹" not in df.columns:
        df.insert(0, "그룹", "본인 주력")
    
    return df

def save_to_github(df):
    clean_df = df[["그룹", "종목명", "코드", "매수가"]].copy()
    json_content = json.dumps(clean_df.to_dict(orient="records"), ensure_ascii=False, indent=2)
    
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write(json_content)
    except Exception:
        pass

    token, repo = get_config("GITHUB_TOKEN"), get_config("GITHUB_REPO")
    if not token or not repo: return False

    url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    try:
        res = requests.get(f"{url}?ref=main", headers=headers, timeout=5)
        sha = res.json().get("sha") if res.status_code == 200 else None
        
        payload = {
            "message": f"Auto-sync: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": base64.b64encode(json_content.encode("utf-8")).decode("utf-8"),
            "branch": "main"
        }
        if sha: payload["sha"] = sha
        
        put_res = requests.put(url, headers=headers, json=payload, timeout=5)
        if put_res.status_code in [200, 201]:
            st.session_state["last_sync_time"] = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S")
            return True
        return False
    except Exception:
        return False

# -------------------------------------------------------------
# 2. 강력하고 빠른 데이터 수집 엔진 (Naver Mobile API + yfinance)
# -------------------------------------------------------------
TICKER_DICT = {
    "삼성전자": "005930", "sk하이닉스": "000660", "한화에어로스페이스": "012450", 
    "삼양식품": "003230", "현대차": "005380", "네이버": "035420", 
    "sk이노베이션": "096770", "한미반도체": "042700"
}

def resolve_code(name_or_code):
    cleaned = name_or_code.strip().lower().replace(" ", "")
    if len(cleaned) == 6 and cleaned.isdigit(): return cleaned
    for k, v in TICKER_DICT.items():
        if k.lower().replace(" ", "") == cleaned: return v
    try:
        search_url = f"https://ac.finance.naver.com/ac?q={requests.utils.quote(name_or_code.strip())}&target=stock"
        items = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3).json().get("items", [[]])[0]
        for item in items:
            if cleaned in str(item[1]).replace(" ", "").lower(): return str(item[0])
    except Exception:
        pass
    return ""

@st.cache_data(ttl=60)
def analyze_full_stock(code, buy_price):
    headers = {"User-Agent": "Mozilla/5.0"}
    res_data = {
        "현재가": 0, "수익": "-", "RSI": 50.0, "20일이격": "-", "추천": "🟡 관망", 
        "수급": "데이터 없음", "EPS/PER": "-"
    }
    if not code: return res_data

    # 1. 기술적 분석 (yfinance)
    try:
        hist = yf.Ticker(f"{code}.KS").history(period="3mo")
        if hist.empty or len(hist) < 20: hist = yf.Ticker(f"{code}.KQ").history(period="3mo")
        if not hist.empty and len(hist) >= 20:
            close, volume = hist['Close'], hist['Volume']
            cur_p = int(close.iloc[-1])
            ma20 = close.rolling(20).mean().iloc[-1]
            disp20 = (cur_p / ma20) * 100
            
            delta = close.diff()
            rs = delta.clip(lower=0).rolling(14).mean() / (-delta.clip(upper=0)).rolling(14).mean().replace(0, 0.0001)
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])
            
            res_data["현재가"] = cur_p
            res_data["RSI"] = round(rsi, 1)
            res_data["20일이격"] = f"{round(disp20, 1)}%"

            if rsi <= 30: res_data["추천"] = "🔥 강력 매수"
            elif rsi >= 75: res_data["추천"] = "🔴 매도"
            elif cur_p >= ma20 and 35 <= rsi <= 55: res_data["추천"] = "🟢 매수"
    except Exception:
        pass

    # 2. 네이버 모바일 통합 API (실시간 가격, 실적 컨센서스)
    try:
        url_intg = f"https://m.stock.naver.com/api/stock/{code}/integration"
        intg_json = requests.get(url_intg, headers=headers, timeout=3).json()
        if intg_json and "dealInfo" in intg_json:
            res_data["현재가"] = int(intg_json.get("recentInfo", {}).get("closePrice", "0").replace(",", ""))
            eps = intg_json.get("consensusInfo", {}).get("eps", "")
            per = intg_json.get("consensusInfo", {}).get("per", "")
            if eps and per:
                res_data["EPS/PER"] = f"EPS {eps} / PER {per}배"
    except Exception:
        pass

    # 3. 네이버 투자자 API (최근 5일 외인/기관 쌍끌이 수급)
    try:
        url_inv = f"https://m.stock.naver.com/api/stock/{code}/investor/days?pageSize=5&page=1"
        inv_json = requests.get(url_inv, headers=headers, timeout=3).json()
        frgn_buy = sum(int(item.get('foreignerPureBuyQuant', '0').replace(',', '')) for item in inv_json)
        org_buy = sum(int(item.get('organPureBuyQuant', '0').replace(',', '')) for item in inv_json)
        
        if frgn_buy > 0 and org_buy > 0: res_data["수급"] = "🔥 쌍끌이 매수"
        elif frgn_buy < 0 and org_buy < 0: res_data["수급"] = "❄️ 양매도"
        elif frgn_buy > 0: res_data["수급"] = "📈 외인 매수"
        elif org_buy > 0: res_data["수급"] = "🏢 기관 매수"
        else: res_data["수급"] = "관망"
    except Exception:
        pass

    # 4. 수익률 및 텔레그램 스나이퍼 알림
    cur_p = res_data["현재가"]
    if buy_price > 0 and cur_p > 0:
        rate = ((cur_p - buy_price) / buy_price) * 100
        res_data["수익"] = f"🔺 +{rate:.2f}%" if rate > 0 else (f"🔻 {rate:.2f}%" if rate < 0 else "0.00%")
    
    alert_key = f"alerted_{code}_{datetime.datetime.now().strftime('%Y%m%d')}"
    if res_data["추천"] == "🔥 강력 매수" and alert_key not in st.session_state:
        send_telegram_alert(f"🎯 [스나이퍼 포착]\n종목: {code}\n상태: 강력 매수 구간 진입 (RSI {res_data['RSI']})\n수급: {res_data['수급']}")
        st.session_state[alert_key] = True

    return res_data

# -------------------------------------------------------------
# 3. UI 렌더링
# -------------------------------------------------------------
st.markdown("### 📡 Stock Cold-Room Terminal", unsafe_allow_html=True)

if 'stock_df' not in st.session_state:
    st.session_state.stock_df = load_portfolio()

# 에러 방어: 기존 세션이나 원격 데이터에 '그룹' 컬럼이 누락되어 있다면 즉시 채워넣음
if "그룹" not in st.session_state.stock_df.columns:
    st.session_state.stock_df.insert(0, "그룹", "본인 주력")
    
# 신규 종목 추가 폼 (다중 포트폴리오 그룹핑 지원)
with st.form("add_stock_form", clear_on_submit=True):
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    with c1:
        # 온 가족 계좌 관리를 위한 태그 시스템
        group_val = st.selectbox("포트폴리오", ["본인 주력", "첫째 딸 계좌", "둘째 딸 계좌", "단기 트레이딩"])
    with c2:
        input_name = st.text_input("종목명/코드", placeholder="예: 한미반도체")
    with c3:
        input_buy = st.number_input("매수가 (원)", min_value=0, step=100)
    with c4:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        if st.form_submit_button("추가"):
            code = resolve_code(input_name)
            if code:
                new_row = pd.DataFrame([{"그룹": group_val, "종목명": input_name.strip(), "코드": code, "매수가": int(input_buy)}])
                st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
                save_to_github(st.session_state.stock_df)
                st.rerun()
            elif input_name:
                st.error("종목을 찾을 수 없습니다.")

# 에디터 매수가 변경 감지 및 저장
if "stock_editor" in st.session_state and "edited_rows" in st.session_state["stock_editor"]:
    modified = False
    for r_idx, changes in st.session_state["stock_editor"]["edited_rows"].items():
        if "매수가" in changes:
            # 원본 데이터프레임의 실제 인덱스를 찾아 업데이트해야 함
            actual_idx = st.session_state.view_indices[int(r_idx)]
            st.session_state.stock_df.at[actual_idx, "매수가"] = int(changes["매수가"])
            modified = True
    if modified:
        save_to_github(st.session_state.stock_df)

# 다중 포트폴리오 탭 구성
groups = st.session_state.stock_df["그룹"].unique().tolist()
if not groups: groups = ["본인 주력"]
tabs = st.tabs(groups)

st.session_state.view_indices = [] # 뷰포트용 인덱스 매핑

for i, group_name in enumerate(groups):
    with tabs[i]:
        group_df = st.session_state.stock_df[st.session_state.stock_df["그룹"] == group_name]
        display_rows = []
        
        for idx, row in group_df.iterrows():
            st.session_state.view_indices.append(idx)
            analyzed = analyze_full_stock(row['코드'], row["매수가"])
            display_rows.append({
                "선택": False,
                "종목명": row["종목명"],
                "코드": row["코드"],
                "현재가": analyzed["현재가"],
                "매수가": row["매수가"],
                "수익": analyzed["수익"],
                "수급(5일)": analyzed["수급"],
                "실적전망": analyzed["EPS/PER"],
                "20일이격": analyzed["20일이격"],
                "RSI": analyzed["RSI"],
                "시그널": analyzed["추천"]
            })
        
        if display_rows:
            view_df = pd.DataFrame(display_rows)
            edited_df = st.data_editor(
                view_df,
                key=f"stock_editor_{group_name}",
                column_config={
                    "선택": st.column_config.CheckboxColumn("삭제", default=False),
                    "종목명": st.column_config.TextColumn(disabled=True),
                    "코드": st.column_config.TextColumn(disabled=True),
                    "현재가": st.column_config.NumberColumn(format="%d 원", disabled=True),
                    "매수가": st.column_config.NumberColumn(format="%d 원", min_value=0, step=100),
                    "수익": st.column_config.TextColumn(disabled=True),
                    "수급(5일)": st.column_config.TextColumn(disabled=True),
                    "실적전망": st.column_config.TextColumn(disabled=True),
                    "20일이격": st.column_config.TextColumn(disabled=True),
                    "RSI": st.column_config.NumberColumn(disabled=True),
                    "시그널": st.column_config.TextColumn(disabled=True),
                },
                use_container_width=True,
                hide_index=True
            )
            
            # 탭별 삭제 로직
            selected = edited_df[edited_df["선택"] == True]
            if not selected.empty:
                if st.button(f"🗑️ {group_name} 선택 종목 삭제", key=f"del_{group_name}"):
                    codes_to_remove = selected["코드"].tolist()
                    st.session_state.stock_df = st.session_state.stock_df[
                        ~((st.session_state.stock_df["그룹"] == group_name) & (st.session_state.stock_df["코드"].isin(codes_to_remove)))
                    ].reset_index(drop=True)
                    save_to_github(st.session_state.stock_df)
                    st.rerun()
        else:
            st.info("등록된 종목이 없습니다.")

last_sync = st.session_state.get("last_sync_time", "")
st.caption(f"⚡ 네이버 은닉 API 연동 완벽 적용 | 💾 최근 동기화: {last_sync}")
