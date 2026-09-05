import streamlit as st
import pandas as pd
import datetime
from zoneinfo import ZoneInfo
import requests
import json
import base64
import os
import re
import concurrent.futures

DATA_FILE = "portfolio.json"

st.set_page_config(page_title="Stock Cold-Room", layout="wide", initial_sidebar_state="collapsed")

# =====================================================================
# [반응형 프리미엄 터미널 및 컬럼 정렬 커스텀 CSS]
# =====================================================================
st.markdown("""
<style>
    .stApp { background-color: #0b0f19; }
    .stApp::before {
        content: ""; position: fixed; top: 0; left: 0; width: 100%; height: 4px;
        background: linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899); z-index: 99999;
    }
    header {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden;}
    
    .responsive-title {
        font-family: 'Helvetica Neue', Arial, sans-serif; 
        font-weight: 900; 
        font-size: clamp(24px, 4vw, 36px); 
        color: #f8fafc; margin: 0; letter-spacing: -1.2px;
    }
    .responsive-sub {
        font-family: 'Helvetica Neue', Arial, sans-serif; 
        font-size: clamp(10px, 2vw, 12px); 
        color: #64748b; margin: 4px 0 0 0; text-transform: uppercase; letter-spacing: 1px;
    }
    
    [data-testid="stForm"] {
        border: 1px solid #1e293b; border-radius: 12px; background-color: #0f172a;
    }
    [data-testid="stDataFrame"] {
        border: 1px solid #1e293b; border-radius: 8px; overflow: hidden;
    }

    /* -------------------------------------------------------------
       데이터 에디터 컬럼별 정렬 강제 적용
       ------------------------------------------------------------- */
    div[data-testid="stDataFrame"] th:nth-child(1), div[data-testid="stDataFrame"] td:nth-child(1) { text-align: center !important; }
    div[data-testid="stDataFrame"] th:nth-child(2), div[data-testid="stDataFrame"] td:nth-child(2) { text-align: center !important; }
    div[data-testid="stDataFrame"] th:nth-child(3), div[data-testid="stDataFrame"] td:nth-child(3) { text-align: center !important; }
    div[data-testid="stDataFrame"] th:nth-child(4), div[data-testid="stDataFrame"] td:nth-child(4) { text-align: right !important; }
    div[data-testid="stDataFrame"] th:nth-child(5), div[data-testid="stDataFrame"] td:nth-child(5) { text-align: right !important; }
    div[data-testid="stDataFrame"] th:nth-child(6), div[data-testid="stDataFrame"] td:nth-child(6) { text-align: center !important; }
    div[data-testid="stDataFrame"] th:nth-child(7), div[data-testid="stDataFrame"] td:nth-child(7) { text-align: center !important; }
    div[data-testid="stDataFrame"] th:nth-child(8), div[data-testid="stDataFrame"] td:nth-child(8) { text-align: right !important; }
    div[data-testid="stDataFrame"] th:nth-child(9), div[data-testid="stDataFrame"] td:nth-child(9) { text-align: right !important; }
    div[data-testid="stDataFrame"] th:nth-child(10), div[data-testid="stDataFrame"] td:nth-child(10) { text-align: center !important; }
</style>
""", unsafe_allow_html=True)

http_session = requests.Session()

# -------------------------------------------------------------
# 1. 설정 및 인증 / GitHub 연동
# -------------------------------------------------------------
def get_config(key):
    try:
        if key in st.secrets: return str(st.secrets[key]).strip()
        elif "mysql" in st.secrets and key in st.secrets["mysql"]: return str(st.secrets["mysql"][key]).strip()
    except: pass
    return None

ADMIN_PW = get_config("ADMIN_PASSWORD") or "1234"

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

def load_portfolio():
    token, repo = get_config("GITHUB_TOKEN"), get_config("GITHUB_REPO")
    df = pd.DataFrame()
    if token and repo:
        url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}?ref=main&t={datetime.datetime.now().timestamp()}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        try:
            res = http_session.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                parsed = json.loads(base64.b64decode(res.json()["content"]).decode("utf-8"))
                if parsed: df = pd.DataFrame(parsed)
        except: pass
    if df.empty and os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                parsed = json.load(f)
                if parsed: df = pd.DataFrame(parsed)
        except: pass
    if df.empty:
        return pd.DataFrame(columns=["종목명", "코드", "수동현재가"])
    
    if "수동현재가" not in df.columns:
        df["수동현재가"] = "0"
    df["수동현재가"] = df["수동현재가"].astype(str)
    return df[["종목명", "코드", "수동현재가"]].copy()

def save_to_github(df):
    clean_df = df[["종목명", "코드", "수동현재가"]].copy()
    json_content = json.dumps(clean_df.to_dict(orient="records"), ensure_ascii=False, indent=2)
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f: f.write(json_content)
    except: pass

    token, repo = get_config("GITHUB_TOKEN"), get_config("GITHUB_REPO")
    if not token or not repo: return False
    url = f"https://api.github.com/repos/{repo}/contents/{DATA_FILE}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        res = http_session.get(f"{url}?ref=main&t={datetime.datetime.now().timestamp()}", headers=headers, timeout=5)
        sha = res.json().get("sha") if res.status_code == 200 else None
        payload = {
            "message": f"Update: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": base64.b64encode(json_content.encode("utf-8")).decode("utf-8"),
            "branch": "main"
        }
        if sha: payload["sha"] = sha
        put_res = http_session.put(url, headers=headers, json=payload, timeout=5)
        if put_res.status_code in [200, 201]:
            st.session_state["last_sync_time"] = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S")
            return True
    except: return False
    return False

# -------------------------------------------------------------
# 2. 확실하고 빠른 종목 추가
# -------------------------------------------------------------
TICKER_DICT = {
    "삼성전자": "005930", "SK하이닉스": "000660", "한화에어로스페이스": "012450", 
    "삼양식품": "003230", "현대차": "005380", "네이버": "035420", 
    "SK이노베이션": "096770", "한미반도체": "042700", "삼성전기": "009150",
    "카카오": "035720", "SK스퀘어": "402340"
}

def resolve_stock_info(user_input):
    cleaned = str(user_input).strip()
    if not cleaned: return None, None
    
    if len(cleaned) == 6 and cleaned.isdigit():
        found_name = cleaned
        for k, v in TICKER_DICT.items():
            if v == cleaned:
                found_name = k
                break
        return found_name, cleaned
        
    cleaned_lower = cleaned.lower().replace(" ", "")
    for k, v in TICKER_DICT.items():
        if k.lower().replace(" ", "") == cleaned_lower:
            return k, v
            
    try:
        m_url = f"https://m.stock.naver.com/api/json/search/searchListJson.nhn?keyword={requests.utils.quote(cleaned)}"
        m_res = http_session.get(m_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3).json()
        items = m_res.get("result", {}).get("totallist", [])
        if items:
            for item in items:
                code = str(item.get("itemcode", "")).strip()
                name = str(item.get("name", "")).strip()
                if len(code) == 6 and code.isdigit():
                    return name, code
    except: pass
    
    return cleaned, cleaned

def parse_price_to_int(val):
    if not val: return 0
    s = re.sub(r'[^\d]', '', str(val))
    return int(s) if s else 0

# -------------------------------------------------------------
# 3. 퀀트 분석 엔진
# -------------------------------------------------------------
def fetch_full_stock_analysis(code_or_name, manual_price):
    default_res = {
        "정규장현재가": "0", "수급": "⚠️ 데이터 집계불가", "실적진단": "지표 산출불가", 
        "20일이격": "-", "RSI": 50.0, "종합의견": "🟡 관망 (50점)", "eval_price": 0
    }
    
    code = TICKER_DICT.get(code_or_name, code_or_name)
    m_p = parse_price_to_int(manual_price)

    if not code or not str(code).isdigit() or len(str(code)) != 6:
        default_res["정규장현재가"] = "0"
        default_res["eval_price"] = m_p
        return default_res

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    reg_p = 0
    per_val = None

    try:
        url_main = f"https://finance.naver.com/item/main.naver?code={code}"
        main_res = http_session.get(url_main, headers=headers, timeout=3).text
        
        reg_match = re.search(r'<p class="no_today">\s*<em.*?<span class="blind">([\d,]+)</span>', main_res, re.DOTALL)
        if reg_match: 
            reg_p = int(reg_match.group(1).replace(",", ""))
            
        per_match = re.search(r'id="_per">([0-9\.,]+)<', main_res)
        if per_match:
            try: per_val = float(per_match.group(1).replace(",", ""))
            except: pass
        elif re.search(r'id="_per">\s*N/A\s*<', main_res) or re.search(r'id="_per">\s*-\s*<', main_res):
            per_val = -1.0
    except: pass

    default_res["정규장현재가"] = f"{reg_p:,}" if reg_p > 0 else "0"
    eval_p = m_p if m_p > 0 else reg_p
    default_res["eval_price"] = eval_p

    val_score = 15
    val_label = "지표 산출불가"
    if per_val is not None:
        if per_val <= 0: val_score, val_label = 5, "적자/PER N/A"
        elif per_val <= 10.0: val_score, val_label = 30, f"🟢 초저평가 (PER {per_val:.1f})"
        elif per_val <= 18.0: val_score, val_label = 22, f"적정가치 (PER {per_val:.1f})"
        elif per_val <= 30.0: val_score, val_label = 12, f"성장프리미엄 (PER {per_val:.1f})"
        else: val_score, val_label = 5, f"🔴 고평가 (PER {per_val:.1f})"
    default_res["실적진단"] = val_label

    flow_score = 10
    flow_fetched = False
    frgn_sum, orgn_sum = 0, 0
    try:
        url_trend = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=10"
        t_res = http_session.get(url_trend, headers=headers, timeout=3).json()
        days = t_res if isinstance(t_res, list) else (t_res.get("bizDays") or t_res.get("items") or [])
        if days:
            sub = days[:5]
            frgn_sum = sum(int(str(d.get('frgnPureBuyQuant', 0)).replace(',', '')) for d in sub)
            orgn_sum = sum(int(str(d.get('organPureBuyQuant', 0)).replace(',', '')) for d in sub)
            flow_fetched = True
    except: pass

    if flow_fetched:
        if frgn_sum > 0 and orgn_sum > 0: flow_score, default_res["수급"] = 35, "🔥 쌍끌이 매수"
        elif frgn_sum < 0 and orgn_sum < 0: flow_score, default_res["수급"] = 0, "❄️ 양매도 이탈"
        elif frgn_sum > 0: flow_score, default_res["수급"] = 25, "📈 외인 집중매수"
        elif orgn_sum > 0: flow_score, default_res["수급"] = 20, "🏢 기관 순매수"
        else: flow_score, default_res["수급"] = 15, "⚖️ 수급 균형(중립)"

    tech_score = 15
    try:
        fchart_url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=60&requestType=0"
        f_xml = http_session.get(fchart_url, headers=headers, timeout=3).text
        items = re.findall(r'<item data="(.*?)"', f_xml)
        if len(items) >= 20:
            closes = [float(x.split('|')[4]) for x in items]
            df_c = pd.Series(closes)
            base_p = eval_p if eval_p > 0 else int(df_c.iloc[-1])
            
            ma20 = df_c.rolling(20).mean().iloc[-1]
            disp20 = (base_p / ma20) * 100
            default_res["20일이격"] = f"{disp20:.1f}%"

            delta = df_c.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean().replace(0, 0.0001)
            rs = gain / loss
            base_rsi = float((100 - (100 / (1 + rs))).iloc[-1])
            
            if reg_p > 0 and eval_p > 0:
                price_ratio = eval_p / reg_p
                adjusted_rsi = min(max(base_rsi * price_ratio, 5.0), 98.0)
            else:
                adjusted_rsi = base_rsi
                
            default_res["RSI"] = round(adjusted_rsi, 1)

            if adjusted_rsi <= 30: tech_score = 35
            elif base_p >= ma20 and 38.0 <= adjusted_rsi <= 55.0: tech_score = 30
            elif 55.0 < adjusted_rsi < 70.0: tech_score = 18
            elif adjusted_rsi >= 70: tech_score = 0
    except: pass

    total = val_score + flow_score + tech_score
    if total >= 85: default_res["종합의견"] = f"🔥 강력 매수 ({total}점)"
    elif total >= 70: default_res["종합의견"] = f"🟢 매수 ({total}점)"
    elif total >= 50: default_res["종합의견"] = f"🟡 관망 ({total}점)"
    else: default_res["종합의견"] = f"🔴 매도 ({total}점)"

    return default_res

# -------------------------------------------------------------
# 4. 화면 렌더링 영역
# -------------------------------------------------------------
@st.cache_data(ttl=15)
def get_kospi_html(update_time_str):
    try:
        url = "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI"
        data = http_session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3).json()['datas'][0]
        cur, diff, rate = data['closePrice'], data['compareToPreviousClosePrice'], data['fluctuationsRatio']
        color, sign = ("#ff4b4b", "▲") if float(rate) > 0 else ("#3b82f6", "▼") if float(rate) < 0 else ("#94a3b8", "-")
        c_diff, c_rate = diff.replace("-", "").replace("+", ""), rate.replace("-", "").replace("+", "")
        return f"""
        <div style="background: linear-gradient(145deg, #161b22, #0d1117); padding: 12px 18px; border-radius: 12px; border: 1px solid #30363d; display: flex; flex-direction: column; width: 100%;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="color: #8b949e; font-size: 11px; font-weight: 700;">KOSPI</span>
                <span style="color: #484f58; font-size: 10px;">{update_time_str}</span>
            </div>
            <div style="display: flex; align-items: baseline; gap: 8px;">
                <span style="font-size: clamp(20px, 4vw, 28px); font-weight: 800; color: #ffffff;">{cur}</span>
                <span style="font-size: clamp(12px, 2vw, 14px); font-weight: 600; color: {color};">{sign} {c_diff} ({c_rate}%)</span>
            </div>
        </div>
        """
    except: return "<div style='color: gray;'>KOSPI 통신 지연</div>"

col_t, col_k, col_l = st.columns([6, 3, 1], gap="small")

with col_t:
    st.markdown("""
    <div style="margin-top: 5px;">
        <h1 class="responsive-title">Stock-Cold-Room</h1>
        <p class="responsive-sub">Manual & Multi-Factor Terminal</p>
    </div>
    """, unsafe_allow_html=True)

with col_k:
    now_str = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M KST")
    st.markdown(get_kospi_html(now_str), unsafe_allow_html=True)

with col_l:
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    if not st.session_state.is_admin:
        with st.popover("🔐", use_container_width=True):
            st.markdown("**관리자 인증**")
            pw_input = st.text_input("비밀번호", type="password", label_visibility="collapsed")
            if st.button("Unlock", use_container_width=True):
                if pw_input == ADMIN_PW:
                    st.session_state.is_admin = True
                    st.rerun()
                else: st.error("오류")
    else:
        with st.popover("🔓", use_container_width=True):
            st.success("인증됨")
            if st.button("Logout", use_container_width=True):
                st.session_state.is_admin = False
                st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

if 'stock_df' not in st.session_state:
    st.session_state.stock_df = load_portfolio()

with st.form("add_stock_form", clear_on_submit=True):
    col_in, col_bt = st.columns([4, 1])
    with col_in:
        input_name = st.text_input("종목명/코드", placeholder="예: SK스퀘어 또는 402340", disabled=not st.session_state.is_admin, label_visibility="collapsed")
    with col_bt:
        submitted = st.form_submit_button("➕ 추가", disabled=not st.session_state.is_admin, use_container_width=True)

if submitted:
    if input_name.strip():
        name, code = resolve_stock_info(input_name.strip())
        if code:
            new_stock = pd.DataFrame([{"종목명": name, "코드": code, "수동현재가": "0"}])
            st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_stock], ignore_index=True)
            save_to_github(st.session_state.stock_df)
            st.rerun()
        else:
            st.error("등록 실패. 올바른 종목명이나 6자리 코드를 입력하세요.")

# -------------------------------------------------------------
# 데이터 에디터 테이블 영역
# -------------------------------------------------------------
display_rows = []
codes = st.session_state.stock_df['코드'].tolist()
manual_prices = st.session_state.stock_df['수동현재가'].tolist() if '수동현재가' in st.session_state.stock_df.columns else ["0"]*len(codes)

if codes:
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(codes), 15)) as executor:
        analyzed_results = list(executor.map(fetch_full_stock_analysis, codes, manual_prices))
    
    for idx, row in st.session_state.stock_df.iterrows():
        ans = analyzed_results[idx]
        raw_m_p = parse_price_to_int(row["수동현재가"])
        formatted_m_p = f"{raw_m_p:,}" if raw_m_p > 0 else "0"
        
        display_rows.append({
            "선택": False, 
            "종목명": row["종목명"], 
            "코드": row["코드"],
            "현재가": formatted_m_p,  
            "현재가(정규장)": ans["정규장현재가"], 
            "실적": ans["실적진단"], 
            "수급(5D)": ans["수급"],
            "20일선": ans["20일이격"], 
            "RSI": ans["RSI"], 
            "의견": ans["종합의견"],
            "eval_price": ans["eval_price"] 
        })

display_df = pd.DataFrame(display_rows)
st.caption("⚡ [안내] '현재가' 칸에 원하는 가격을 입력하고 엔터를 치면 즉시 반영 및 브리핑에 적용됩니다.")

column_config = {
    "종목명": st.column_config.TextColumn(disabled=True),
    "코드": st.column_config.TextColumn(disabled=True),
    "현재가": st.column_config.TextColumn("현재가", help="야간장 가격 등을 직접 입력하세요 (0이면 정규장 종가 자동 반영)"),
    "현재가(정규장)": st.column_config.TextColumn("현재가(정규장)", disabled=True),
    "실적": st.column_config.TextColumn(disabled=True),
    "수급(5D)": st.column_config.TextColumn(disabled=True),
    "20일선": st.column_config.TextColumn(disabled=True),
    "RSI": st.column_config.NumberColumn(disabled=True),
    "의견": st.column_config.TextColumn(disabled=True),
    "eval_price": None 
}

column_config["선택"] = st.column_config.CheckboxColumn("삭제", disabled=False, default=False)

# on_change=st.rerun을 통해 체크박스나 셀 수정 시 즉시 반영되도록 수정
edited_df = st.data_editor(
    display_df, 
    key="stock_editor", 
    column_config=column_config, 
    use_container_width=True, 
    hide_index=True,
    on_change=lambda: None
)

# 현재가 수정 즉시 저장
if not edited_df.equals(display_df):
    for idx, row in edited_df.iterrows():
        target_code = row["코드"]
        clean_price = str(parse_price_to_int(row["현재가"]))
        st.session_state.stock_df.loc[st.session_state.stock_df["코드"] == target_code, "수동현재가"] = clean_price
    save_to_github(st.session_state.stock_df)
    st.rerun()

# -------------------------------------------------------------
# 삭제 버튼 영역 (관리자 로그인 시 항상 노출, 체크된 항목이 있을 때만 활성화)
# -------------------------------------------------------------
selected_rows = edited_df[edited_df["선택"] == True]

if st.session_state.is_admin:
    st.markdown("<br>", unsafe_allow_html=True)
    col_del_btn, _ = st.columns([2, 5])
    with col_del_btn:
        delete_disabled = (len(selected_rows) == 0)
        btn_label = f"🗑️ 선택한 종목 삭제 ({len(selected_rows)}개)" if len(selected_rows) > 0 else "🗑️ 삭제할 종목을 체크하세요"
        if st.button(btn_label, use_container_width=True, type="primary", disabled=delete_disabled):
            codes_to_remove = selected_rows["코드"].tolist()
            st.session_state.stock_df = st.session_state.stock_df[~st.session_state.stock_df["코드"].isin(codes_to_remove)].reset_index(drop=True)
            save_to_github(st.session_state.stock_df)
            if "stock_editor" in st.session_state: del st.session_state["stock_editor"]
            st.rerun()

# -------------------------------------------------------------
# 5. 차트 터미널 및 연동형 AI 브리핑
# -------------------------------------------------------------
def get_ai_analyst_opinion(df, code_name, quant_score, quant_status, current_price, ma20):
    if df.empty or len(df) < 60: return ""
    last, prev = df.iloc[-1], df.iloc[-2]
    
    eval_price = current_price if current_price > 0 else last['Close']
    
    is_uptrend = eval_price > ma20 and ma20 > last['MA60']
    is_downtrend = eval_price < ma20 and ma20 < last['MA60']
    trend_status, trend_color = ("정배열 상승 추세", "#ff4b4b") if is_uptrend else ("역배열 하락 추세", "#3b82f6") if is_downtrend else ("추세 전환 및 횡보", "#faca2b")
    
    macd_up = last['MACD'] > last['Signal'] and prev['MACD'] <= prev['Signal']
    macd_dn = last['MACD'] < last['Signal'] and prev['MACD'] >= prev['Signal']
    macd_bull = last['MACD'] > last['Signal']
    macd_status = "🚨 골든크로스 발생" if macd_up else "⚠️ 데드크로스 발생" if macd_dn else "매수 우위 유지" if macd_bull else "매도 우위 지속"
        
    is_upper = eval_price >= last['BB_Upper']
    is_lower = eval_price <= last['BB_Lower']
    bb_status = "상단 도달 (과열)" if is_upper else "하단 이탈 (반등기대)" if is_lower else "밴드 내 안정"

    summary_text = f"현재 적용가(<b>{eval_price:,}원</b>) 기준 퀀트 스코어 <b style='color:#fff;'>{quant_score}점({quant_status})</b>. "
    if quant_score >= 70:
        if is_uptrend: summary_text += "펀더멘털과 기술적 흐름이 완벽히 일치하는 랠리 국면입니다. 수익 극대화를 권장합니다." if not macd_dn else "펀더멘털은 우수하나 단기 과열 징후가 있습니다. 눌림목 분할 매수가 유효합니다."
        elif is_downtrend: summary_text += "우수한 펀더멘털 대비 주가가 과도하게 눌려 있습니다. 바닥 다지기 및 기술적 반등 시 저가 매수를 고려하세요."
        else: summary_text += "강력한 펀더멘털을 바탕으로 횡보 매집 중입니다. 비중 확대를 긍정적으로 검토할 구간입니다."
    else:
        if is_uptrend: summary_text += "차트는 상승세이나 수급/실적 등 펀더멘털 뒷받침이 약합니다. 짧은 단기 트레이딩과 칼같은 손절 대응이 필요합니다."
        elif is_downtrend: summary_text += "펀더멘털과 차트 모두 강력한 매도/위험 시그널을 보이고 있습니다. 섣부른 물타기를 금지하고 관망하세요."
        else: summary_text += "방향성과 수급 동력이 모두 부재한 상황입니다. 확실한 메이저 수급 유입 전까지는 자금을 아끼는 것이 좋습니다."

    return f"""
    <div style="background-color: #1e293b; border-left: 4px solid {trend_color}; padding: 16px; border-radius: 6px; margin-top: 16px;">
        <h5 style="color: #f8fafc; margin-top: 0; font-size: 15px; margin-bottom: 10px;">🤖 AI 퀀트 융합 리포트 : {code_name}</h5>
        <ul style="color: #cbd5e1; font-size: 13px; line-height: 1.6; padding-left: 20px; margin-bottom: 0;">
            <li><b>추세:</b> <span style="color: {trend_color};">{trend_status}</span> &nbsp;|&nbsp; <b>MACD:</b> {macd_status} &nbsp;|&nbsp; <b>Bollinger:</b> {bb_status}</li>
            <li style="margin-top: 8px;"><b>💡 전략:</b> <span style="color: #e2e8f0;">{summary_text}</span></li>
        </ul>
    </div>
    """

st.markdown("<h4 style='color: #e2e8f0; font-weight: 600; margin-top: 20px;'>📈 ADVANCED CHART</h4>", unsafe_allow_html=True)
if codes:
    sel_stock = st.selectbox("종목 선택", st.session_state.stock_df["종목명"].tolist(), label_visibility="collapsed")
    tgt_row = st.session_state.stock_df[st.session_state.stock_df["종목명"] == sel_stock]
    tgt_code = tgt_row["코드"].values[0] if not tgt_row.empty else "005930"
    
    current_active_price = 0
    if not display_df.empty:
        matched_row = display_df[display_df["종목명"] == sel_stock]
        if not matched_row.empty:
            current_active_price = int(matched_row["eval_price"].values[0])
    
    q_score, q_stat = 50, "🟡 관망"
    if not display_df.empty:
        op_str = display_df[display_df["종목명"] == sel_stock]["의견"].values[0]
        m = re.search(r'\((\d+)점\)', op_str)
        if m: q_score = int(m.group(1))
        q_stat = op_str.split('(')[0].strip()
    
    try:
        f_xml = http_session.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={tgt_code}&timeframe=day&count=180&requestType=0", headers={"User-Agent": "Mozilla"}, timeout=3).text
        items = re.findall(r'<item data="(.*?)"', f_xml)
        
        if len(items) > 60:
            df_c = pd.DataFrame([x.split('|') for x in items], columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df_c['Close'] = df_c['Close'].astype(float)
            df_c['Volume'] = df_c['Volume'].astype(float)
            df_c['Date'] = pd.to_datetime(df_c['Date'])
            df_c.set_index('Date', inplace=True)
            
            df_c['MA20'] = df_c['Close'].rolling(20).mean()
            df_c['MA60'] = df_c['Close'].rolling(60).mean()
            std20 = df_c['Close'].rolling(20).std()
            df_c['BB_Upper'], df_c['BB_Lower'] = df_c['MA20'] + (std20*2), df_c['MA20'] - (std20*2)
            
            ema12, ema26 = df_c['Close'].ewm(span=12).mean(), df_c['Close'].ewm(span=26).mean()
            df_c['MACD'] = ema12 - ema26
            df_c['Signal'] = df_c['MACD'].ewm(span=9).mean()
            
            df_v = df_c.iloc[-90:]
            t1, t2, t3 = st.tabs(["💰 가격/밴드", "📉 MACD", "📊 거래량"])
            with t1: st.line_chart(df_v[['Close', 'MA20', 'BB_Upper', 'BB_Lower']])
            with t2: st.line_chart(df_v[['MACD', 'Signal']])
            with t3: st.bar_chart(df_v['Volume'])
            
            latest_ma20 = df_c['MA20'].iloc[-1]
            st.markdown(get_ai_analyst_opinion(df_c, sel_stock, q_score, q_stat, current_active_price, latest_ma20), unsafe_allow_html=True)
    except Exception as e:
        st.info("차트를 로드할 수 없습니다.")
