import streamlit as st
import pandas as pd
import datetime
from zoneinfo import ZoneInfo
import requests
import yfinance as yf
import json
import base64
import os
import re

DATA_FILE = "portfolio.json"

st.set_page_config(page_title="Stock Cold Room", layout="wide")

# -------------------------------------------------------------
# 1. 설정 및 인증 / GitHub / 텔레그램 연동
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

ADMIN_PW = get_config("ADMIN_PASSWORD") or "1234"

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

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
        return pd.DataFrame(columns=["종목명", "코드"])
    
    return df[["종목명", "코드"]].copy()

def save_to_github(df):
    clean_df = df[["종목명", "코드"]].copy()
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
# 2. 퀀트 멀티 팩터 분석 엔진
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
def fetch_full_stock_analysis(code: str):
    default_res = {
        "현재가": 0, "수급": "⚠️ 데이터 집계불가", "실적진단": "-", 
        "20일이격": "-", "RSI": 50.0, "종합의견": "🟡 관망 (50점)"
    }
    if not code:
        return default_res

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 1. NXT 및 실시간 가격 탐색
    cur_p = 0
    try:
        url_intg = f"https://m.stock.naver.com/api/stock/{code}/integration"
        intg_res = requests.get(url_intg, headers=headers, timeout=3).json()
        
        deal_info = intg_res.get("dealInfo", {})
        nxt_p = deal_info.get("overMarketPrice") or deal_info.get("nxtPrice")
        if nxt_p:
            cur_p = int(str(nxt_p).replace(",", ""))
        
        if cur_p == 0:
            recent_p = intg_res.get("recentInfo", {}).get("closePrice") or deal_info.get("closePrice")
            if recent_p:
                cur_p = int(str(recent_p).replace(",", ""))
    except Exception:
        pass

    if cur_p == 0:
        try:
            url_rt = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
            rt_json = requests.get(url_rt, headers=headers, timeout=3).json()
            if "datas" in rt_json and rt_json["datas"]:
                cur_p = int(rt_json["datas"][0]["closePrice"].replace(",", ""))
        except Exception:
            pass
            
    default_res["현재가"] = cur_p

    # 2. 밸류에이션 팩터 (PER / EPS)
    val_score = 15
    val_label = "보통"
    per_val = None

    try:
        url_basic = f"https://finance.naver.com/item/main.naver?code={code}"
        basic_res = requests.get(url_basic, headers=headers, timeout=3).text
        
        per_match = re.search(r'id="_per">([0-9\.,]+)<', basic_res)
        if per_match:
            per_val = float(per_match.group(1).replace(",", ""))
            
        if per_val is None and 'intg_res' in locals():
            consensus = intg_res.get("consensusInfo", {})
            raw_per = consensus.get("per")
            if raw_per:
                per_val = float(str(raw_per).replace(",", ""))
            for item in intg_res.get("totalInfos", []):
                if "PER" in item.get("key", ""):
                    per_val = float(str(item.get("value")).replace(",", ""))
                    break

        if per_val is not None:
            if per_val <= 0:
                val_score = 5
                val_label = f"적자기업 (PER {per_val:.1f})"
            elif per_val <= 10.0:
                val_score = 30
                val_label = f"🟢 초저평가 (PER {per_val:.1f})"
            elif per_val <= 18.0:
                val_score = 22
                val_label = f"적정가치 (PER {per_val:.1f})"
            elif per_val <= 30.0:
                val_score = 12
                val_label = f"성장프리미엄 (PER {per_val:.1f})"
            else:
                val_score = 5
                val_label = f"🔴 고평가부담 (PER {per_val:.1f})"
        else:
            val_label = "PER 산출불가"
            
        default_res["실적진단"] = val_label
    except Exception:
        default_res["실적진단"] = "지표 산출불가"

    # 3. 수급 팩터 (네이버 공식 매매동향 직접 파싱)
    flow_score = 10
    flow_fetched = False
    frgn_sum = 0
    orgn_sum = 0

    try:
        url_frgn = f"https://finance.naver.com/item/frgn.naver?code={code}"
        f_res = requests.get(url_frgn, headers=headers, timeout=4)
        f_res.encoding = 'euc-kr'
        f_html = f_res.text

        row_matches = re.findall(r'<tr[^>]*>.*?<td class="tc"[^>]*>.*?[0-9]{4}\.[0-9]{2}\.[0-9]{2}.*?</tr>', f_html, re.DOTALL)
        parsed_orgn, parsed_frgn = [], []

        for row in row_matches[:5]:
            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(tds) >= 7:
                raw_orgn = re.sub(r'<[^>]+>', '', tds[5]).replace(',', '').strip()
                raw_frgn = re.sub(r'<[^>]+>', '', tds[6]).replace(',', '').strip()
                if raw_orgn.lstrip('+-').isdigit():
                    parsed_orgn.append(int(raw_orgn))
                if raw_frgn.lstrip('+-').isdigit():
                    parsed_frgn.append(int(raw_frgn))

        if len(parsed_orgn) >= 3 and len(parsed_frgn) >= 3:
            orgn_sum = sum(parsed_orgn)
            frgn_sum = sum(parsed_frgn)
            flow_fetched = True
    except Exception:
        pass

    if not flow_fetched:
        try:
            url_trend = f"https://m.stock.naver.com/api/stock/{code}/trend?pageSize=10"
            trend_res = requests.get(url_trend, headers=headers, timeout=3).json()
            days_data = trend_res if isinstance(trend_res, list) else (trend_res.get("bizDays") or trend_res.get("items") or [])
            if days_data:
                sub_days = days_data[:5]
                frgn_sum = sum(int(str(d.get('frgnPureBuyQuant', 0)).replace(',', '')) for d in sub_days)
                orgn_sum = sum(int(str(d.get('organPureBuyQuant', 0)).replace(',', '')) for d in sub_days)
                flow_fetched = True
        except Exception:
            pass

    if flow_fetched:
        if frgn_sum > 0 and orgn_sum > 0:
            flow_score = 35
            default_res["수급"] = "🔥 쌍끌이 매수"
        elif frgn_sum < 0 and orgn_sum < 0:
            flow_score = 0
            default_res["수급"] = "❄️ 양매도 이탈"
        elif frgn_sum > 0 and orgn_sum <= 0:
            flow_score = 25
            default_res["수급"] = "📈 외인 집중매수"
        elif orgn_sum > 0 and frgn_sum <= 0:
            flow_score = 20
            default_res["수급"] = "🏢 기관 순매수"
        else:
            flow_score = 15
            default_res["수급"] = "⚖️ 수급 균형(중립)"
    else:
        flow_score = 10
        default_res["수급"] = "⚠️ 데이터 집계불가"

    # 4. 모멘텀 & 타이밍 팩터
    tech_score = 15
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
                tech_score = 35
            elif current_p >= ma20 and 38.0 <= rsi <= 55.0:
                tech_score = 30
            elif 55.0 < rsi < 70.0:
                tech_score = 18
            elif rsi >= 75:
                tech_score = 0
            else:
                tech_score = 15
    except Exception:
        pass

    # 5. 복합 점수 산출
    total_score = val_score + flow_score + tech_score

    if total_score >= 85:
        recommendation = f"🔥 강력 매수 ({total_score}점)"
    elif total_score >= 70:
        recommendation = f"🟢 매수 ({total_score}점)"
    elif total_score >= 50:
        recommendation = f"🟡 관망 ({total_score}점)"
    else:
        recommendation = f"🔴 매도 ({total_score}점)"

    default_res["종합의견"] = recommendation

    # 6. 스나이퍼 텔레그램 발송
    alert_key = f"alert_{code}_{datetime.datetime.now().strftime('%Y%m%d')}"
    if total_score >= 85 and alert_key not in st.session_state:
        send_telegram_alert(
            f"🎯 [Stock Cold-Room 퀀트 포착]\n"
            f"종목코드: {code}\n"
            f"종합점수: {total_score}점 (최상위 등급)\n"
            f"실적: {default_res['실적진단']}\n"
            f"수급: {default_res['수급']}\n"
            f"RSI: {default_res['RSI']}"
        )
        st.session_state[alert_key] = True

    return default_res

# -------------------------------------------------------------
# 3. 화면 렌더링
# -------------------------------------------------------------
st.markdown("### 📡 Stock Cold-Room", unsafe_allow_html=True)

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

# 사이드바 관리자 인증 영역
with st.sidebar:
    st.markdown("### 🔐 관리자 인증")
    if not st.session_state.is_admin:
        pw_input = st.text_input("비밀번호", type="password", placeholder="비밀번호 입력")
        if st.button("잠금 해제", use_container_width=True):
            if pw_input == ADMIN_PW:
                st.session_state.is_admin = True
                st.success("인증되었습니다.")
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
    else:
        st.success("🔓 관리자 모드 활성화됨")
        if st.button("로그아웃", use_container_width=True):
            st.session_state.is_admin = False
            st.rerun()

if 'stock_df' not in st.session_state:
    st.session_state.stock_df = load_portfolio()

# 신규 종목 등록 폼 (관리자 인증 시에만 등록 가능)
with st.form("add_stock_form", clear_on_submit=True):
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        input_name = st.text_input(
            "종목명 또는 종목코드(6자리)", 
            placeholder="예: 한미반도체 또는 042700 (관리자 인증 필요)" if not st.session_state.is_admin else "예: 한미반도체 또는 042700",
            disabled=not st.session_state.is_admin
        )
    with col_btn:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        submitted = st.form_submit_button("신규 종목 추가", disabled=not st.session_state.is_admin)
    
    if submitted:
        if not st.session_state.is_admin:
            st.error("종목 추가 권한이 없습니다. 좌측 사이드바에서 관리자 인증을 완료하세요.")
        elif input_name.strip():
            code = resolve_code(input_name)
            if not code:
                st.error("종목을 찾을 수 없습니다. 올바른 6자리 코드를 입력하세요.")
            else:
                new_row = pd.DataFrame([{"종목명": input_name.strip(), "코드": code}])
                st.session_state.stock_df = pd.concat([st.session_state.stock_df, new_row], ignore_index=True)
                save_to_github(st.session_state.stock_df)
                st.rerun()

# 테이블 데이터 구성
display_rows = []
for idx, row in st.session_state.stock_df.iterrows():
    code = str(row['코드'])
    analyzed = fetch_full_stock_analysis(code)

    display_rows.append({
        "선택": False,
        "종목명": row["종목명"],
        "코드": code,
        "현재가": analyzed["현재가"],
        "실적진단": analyzed["실적진단"],
        "수급(5일)": analyzed["수급"],
        "20일이격": analyzed["20일이격"],
        "RSI": analyzed["RSI"],
        "종합의견": analyzed["종합의견"]
    })

display_df = pd.DataFrame(display_rows)

last_sync = st.session_state.get("last_sync_time")
sync_label = f" | 💾 GitHub 동기화 완료: {last_sync}" if last_sync else ""
st.caption(f"⚡ 멀티 팩터 분석{sync_label}")

# 통합 데이터 테이블 (관리자 미인증 시 체크박스 컬럼 비활성화)
column_config = {
    "종목명": st.column_config.TextColumn(disabled=True),
    "코드": st.column_config.TextColumn(disabled=True),
    "현재가": st.column_config.NumberColumn(format="%d 원", disabled=True),
    "실적진단": st.column_config.TextColumn("실적/가치 진단", disabled=True),
    "수급(5일)": st.column_config.TextColumn(disabled=True),
    "20일이격": st.column_config.TextColumn(disabled=True),
    "RSI": st.column_config.NumberColumn(disabled=True),
    "종합의견": st.column_config.TextColumn("퀀트 종합 의견", disabled=True),
}

if st.session_state.is_admin:
    column_config["선택"] = st.column_config.CheckboxColumn("삭제", help="삭제할 종목을 체크하세요", default=False)
else:
    column_config["선택"] = st.column_config.CheckboxColumn("삭제", help="관리자 인증 후 삭제 가능", disabled=True, default=False)

edited_df = st.data_editor(
    display_df,
    key="stock_editor",
    column_config=column_config,
    use_container_width=True,
    hide_index=True
)

# 표 하단: 종합의견 및 수급 기준 안내
st.markdown(
    """
    <div style='background-color: #1e2129; padding: 12px 16px; border-radius: 8px; font-size: 13px; color: #d0d4dc; margin-top: 6px; margin-bottom: 12px; border: 1px solid #2d3139;'>
        <b>📊 퀀트 종합의견 산출 기준 (100점 만점)</b><br>
        • <b>팩터 가중치</b>: 가치/실적 (30점) + 5일 메이저 수급 (35점) + 기술적 모멘텀/RSI (35점)<br>
        • <b>등급 구분</b>: 
        <span style='color: #ff4b4b;'>🔥 <b>강력 매수</b> (85점 이상)</span> &nbsp;|&nbsp; 
        <span style='color: #21c354;'>🟢 <b>매수</b> (70~84점)</span> &nbsp;|&nbsp; 
        <span style='color: #faca2b;'>🟡 <b>관망</b> (50~69점)</span> &nbsp;|&nbsp; 
        <span style='color: #808495;'>🔴 <b>매도</b> (50점 미만)</span><br>
        • <b>수급 진단 구분</b>: 🔥 쌍끌이매수 / ❄️ 양매도이탈 / 📈 외인매수 / 🏢 기관매수 / ⚖️ 수급 균형(중립) / ⚠️ 데이터 집계불가
    </div>
    """,
    unsafe_allow_html=True
)

# 종목 삭제 버튼 (관리자 인증 및 1개 이상 선택 시 활성화)
selected_rows = edited_df[edited_df["선택"] == True]
col_del_btn, _ = st.columns([2, 5])
with col_del_btn:
    delete_disabled = (not st.session_state.is_admin) or (len(selected_rows) == 0)
    del_label = f"🗑️ 선택 종목 삭제 ({len(selected_rows)}개)" if st.session_state.is_admin else "🔒 종목 삭제 (관리자 전용)"
    if st.button(del_label, disabled=delete_disabled):
        codes_to_remove = selected_rows["코드"].tolist()
        st.session_state.stock_df = st.session_state.stock_df[~st.session_state.stock_df["코드"].isin(codes_to_remove)].reset_index(drop=True)
        save_to_github(st.session_state.stock_df)
        if "stock_editor" in st.session_state:
            del st.session_state["stock_editor"]
        st.rerun()

# -------------------------------------------------------------
# 4. 개별 종목 3개월 종가 추이 차트
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
