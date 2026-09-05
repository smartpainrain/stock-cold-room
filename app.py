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
import concurrent.futures

DATA_FILE = "portfolio.json"

st.set_page_config(page_title="Stock Cold-Room", layout="wide")

# =====================================================================
# [글로벌 탑티어 터미널 커스텀 CSS 디자인 적용]
# =====================================================================
st.markdown("""
<style>
    /* 전체 배경 및 폰트 세팅 */
    .stApp {
        background-color: #0b0f19;
    }
    
    /* 최상단 프리미엄 그라데이션 라인 */
    .stApp::before {
        content: "";
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 4px;
        background: linear-gradient(90deg, #3b82f6, #8b5cf6, #ec4899);
        z-index: 99999;
    }
    
    /* 기본 헤더/푸터 숨김 처리로 앱 느낌 극대화 */
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 입력 폼 컨테이너 고급화 */
    [data-testid="stForm"] {
        border: 1px solid #1e293b;
        border-radius: 12px;
        background-color: #0f172a;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    
    /* 데이터 에디터(테이블) 테두리 세팅 */
    [data-testid="stDataFrame"] {
        border: 1px solid #1e293b;
        border-radius: 8px;
        overflow: hidden;
    }
</style>
""", unsafe_allow_html=True)

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
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

    # 2. 밸류에이션 팩터
    val_score = 15
    val_label = "적자/PER N/A"
    per_val = None

    try:
        url_basic = f"https://finance.naver.com/item/main.naver?code={code}"
        basic_res = requests.get(url_basic, headers=headers, timeout=3).text
        
        per_match = re.search(r'id="_per">([^<]+)<', basic_res)
        if per_match:
            raw_per = per_match.group(1).replace(",", "").strip()
            if raw_per and raw_per != '-':
                try:
                    per_val = float(raw_per)
                except ValueError:
                    per_val = -1.0 
            else:
                per_val = -1.0
                
        if per_val is None and 'intg_res' in locals():
            consensus = intg_res.get("consensusInfo", {})
            raw_per = consensus.get("per")
            if raw_per:
                try:
                    per_val = float(str(raw_per).replace(",", ""))
                except ValueError:
                    per_val = -1.0
            if per_val is None:
                for item in intg_res.get("totalInfos", []):
                    if "PER" in item.get("key", ""):
                        try:
                            per_val = float(str(item.get("value")).replace(",", ""))
                        except ValueError:
                            per_val = -1.0
                        break

        if per_val is not None:
            if per_val <= 0:
                val_score = 5
                val_label = "적자/PER N/A"
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
            val_score = 5
            val_label = "적자/PER N/A"
            
        default_res["실적진단"] = val_label
    except Exception:
        default_res["실적진단"] = "적자/PER N/A"

    # 3. 수급 팩터
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
            f"🎯 [Stock-Cold-Room 퀀트 포착]\n"
            f"종목코드: {code}\n"
            f"종합점수: {total_score}점 (최상위 등급)\n"
            f"실적: {default_res['실적진단']}\n"
            f"수급: {default_res['수급']}\n"
            f"RSI: {default_res['RSI']}"
        )
        st.session_state[alert_key] = True

    return default_res

# -------------------------------------------------------------
# 3. 화면 렌더링 (병렬 처리 및 프리미엄 디자인 적용)
# -------------------------------------------------------------
@st.cache_data(ttl=15)
def get_kospi_html(update_time_str):
    try:
        url = "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
        data = res['datas'][0]
        cur = data['closePrice']
        diff = data['compareToPreviousClosePrice']
        rate = data['fluctuationsRatio']
        
        rate_val = float(rate)
        if rate_val > 0:
            color = "#ff4b4b" 
            sign = "▲"
        elif rate_val < 0:
            color = "#3b82f6" 
            sign = "▼"
        else:
            color = "#94a3b8" 
            sign = "-"
            
        clean_diff = diff.replace("-", "").replace("+", "")
        clean_rate = rate.replace("-", "").replace("+", "")
        
        html = f"""
        <div style="background: linear-gradient(145deg, #161b22, #0d1117); padding: 16px 24px; border-radius: 12px; border: 1px solid #30363d; display: inline-block; box-shadow: 0 8px 16px rgba(0,0,0,0.4); text-align: left;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="color: #8b949e; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;">KOSPI Index</span>
                <span style="color: #484f58; font-size: 10px;">{update_time_str}</span>
            </div>
            <div style="display: flex; align-items: baseline; gap: 12px;">
                <span style="font-size: 32px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">{cur}</span>
                <span style="font-size: 16px; font-weight: 600; color: {color};">
                    {sign} {clean_diff} ({clean_rate}%)
                </span>
            </div>
        </div>
        """
        return html
    except Exception:
        return "<div style='color: gray; font-size: 12px;'>KOSPI 통신 지연</div>"


col_title, col_kospi = st.columns([1, 1])

with col_title:
    st.markdown("""
    <div style="margin-top: 15px; margin-bottom: 30px;">
        <h1 style="font-family: 'Helvetica Neue', Arial, sans-serif; font-weight: 900; font-size: 36px; color: #f8fafc; margin: 0; letter-spacing: -1.2px;">
            Stock-Cold-Room
        </h1>
        <p style="font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 12px; color: #64748b; margin: 4px 0 0 0; text-transform: uppercase; letter-spacing: 2px;">
            Institutional-Grade Multi-Factor Equity Dashboard
        </p>
    </div>
    """, unsafe_allow_html=True)

with col_kospi:
    now_str = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S KST")
    st.markdown(f"<div style='text-align: right;'>{get_kospi_html(now_str)}</div>", unsafe_allow_html=True)

# 사이드바 관리자 인증 영역
with st.sidebar:
    st.markdown("### 🔐 SYSTEM LOGIN")
    if not st.session_state.is_admin:
        pw_input = st.text_input("Administrator Password", type="password", placeholder="Enter Password")
        if st.button("UNLOCK", use_container_width=True):
            if pw_input == ADMIN_PW:
                st.session_state.is_admin = True
                st.success("Access Granted.")
                st.rerun()
            else:
                st.error("Access Denied.")
    else:
        st.success("🔓 Administrator Mode Active")
        if st.button("LOGOUT", use_container_width=True):
            st.session_state.is_admin = False
            st.rerun()

if 'stock_df' not in st.session_state:
    st.session_state.stock_df = load_portfolio()

# 신규 종목 등록 폼
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

# 멀티스레딩(병렬 처리) 데이터 수집
display_rows = []
codes = st.session_state.stock_df['코드'].tolist()
analyzed_results = []

if codes:
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(codes), 15)) as executor:
        analyzed_results = list(executor.map(fetch_full_stock_analysis, codes))

for idx, row in st.session_state.stock_df.iterrows():
    code = str(row['코드'])
    analyzed = analyzed_results[idx]

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
sync_label = f" | 💾 Data Synced: {last_sync}" if last_sync else ""
st.caption(f"⚡ 퀀트 팩터 엔진 가동 중{sync_label}")

column_config = {
    "종목명": st.column_config.TextColumn(disabled=True),
    "코드": st.column_config.TextColumn(disabled=True),
    "현재가": st.column_config.NumberColumn(format="%d 원", disabled=True),
    "실적진단": st.column_config.TextColumn("실적/가치 팩터", disabled=True),
    "수급(5일)": st.column_config.TextColumn("수급 팩터 (5D)", disabled=True),
    "20일이격": st.column_config.TextColumn("모멘텀 (20D)", disabled=True),
    "RSI": st.column_config.NumberColumn("RSI (14D)", disabled=True),
    "종합의견": st.column_config.TextColumn("퀀트 종합 산출", disabled=True),
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

st.markdown(
    """
    <div style='background-color: #0f172a; padding: 16px 20px; border-radius: 8px; font-size: 13px; color: #94a3b8; margin-top: 8px; margin-bottom: 24px; border: 1px solid #1e293b; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);'>
        <b style="color: #e2e8f0; font-size: 14px; letter-spacing: 0.5px;">📊 MULTI-FACTOR SCORING MODEL (MAX 100)</b><br>
        <div style="margin-top: 8px;">
            • <b>가중치</b>: 가치/실적 (30%) + 메이저 수급 (35%) + 기술적 모멘텀 (35%)<br>
            • <b>등급컷</b>: 
            <span style='color: #ff4b4b; font-weight: 600;'>🔥 강력 매수 (85+)</span> &nbsp;|&nbsp; 
            <span style='color: #21c354; font-weight: 600;'>🟢 매수 (70+)</span> &nbsp;|&nbsp; 
            <span style='color: #faca2b; font-weight: 600;'>🟡 관망 (50+)</span> &nbsp;|&nbsp; 
            <span style='color: #808495; font-weight: 600;'>🔴 매도 (-50)</span><br>
            • <b>수급구분</b>: 🔥 쌍끌이매수 / ❄️ 양매도이탈 / 📈 외인매수 / 🏢 기관매수 / ⚖️ 수급 균형(중립)
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

selected_rows = edited_df[edited_df["선택"] == True]
col_del_btn, _ = st.columns([2, 5])
with col_del_btn:
    delete_disabled = (not st.session_state.is_admin) or (len(selected_rows) == 0)
    del_label = f"🗑️ 선택 종목 삭제 ({len(selected_rows)}개)" if st.session_state.is_admin else "🔒 종목 삭제 (관리자 인증 필요)"
    if st.button(del_label, disabled=delete_disabled):
        codes_to_remove = selected_rows["코드"].tolist()
        st.session_state.stock_df = st.session_state.stock_df[~st.session_state.stock_df["코드"].isin(codes_to_remove)].reset_index(drop=True)
        save_to_github(st.session_state.stock_df)
        if "stock_editor" in st.session_state:
            del st.session_state["stock_editor"]
        st.rerun()

# -------------------------------------------------------------
# 4. 차트 터미널 및 지능형 AI 애널리스트 브리핑 (기능 대폭 강화)
# -------------------------------------------------------------
def get_ai_analyst_opinion(df, code_name):
    """3가지 지표(추세, 모멘텀, 변동성)의 교차 분석을 통해 동적으로 요약 리포트를 생성합니다."""
    if df.empty or len(df) < 60:
        return "<div style='color: #94a3b8;'>데이터가 부족하여 분석할 수 없습니다.</div>"
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 1. 추세 분석 (이동평균선)
    is_uptrend = last['Close'] > last['MA20'] and last['MA20'] > last['MA60']
    is_downtrend = last['Close'] < last['MA20'] and last['MA20'] < last['MA60']
    
    if is_uptrend:
        trend_status = "정배열 상승 추세"
        trend_color = "#ff4b4b"
    elif is_downtrend:
        trend_status = "역배열 하락 추세"
        trend_color = "#3b82f6"
    else:
        trend_status = "추세 전환 및 혼조 구간"
        trend_color = "#faca2b"
        
    # 2. 모멘텀 분석 (MACD)
    macd_cross_up = last['MACD'] > last['Signal'] and prev['MACD'] <= prev['Signal']
    macd_cross_down = last['MACD'] < last['Signal'] and prev['MACD'] >= prev['Signal']
    macd_bull = last['MACD'] > last['Signal']
    
    if macd_cross_up:
        macd_status = "🚨 MACD 골든크로스 발생 (단기 상승 모멘텀 강화)"
    elif macd_cross_down:
        macd_status = "⚠️ MACD 데드크로스 발생 (단기 하락 주의)"
    elif macd_bull:
        macd_status = "MACD 매수 우위 유지 (시그널 상회)"
    else:
        macd_status = "MACD 매도 우위 (시그널 하회)"
        
    # 3. 변동성 분석 (Bollinger Bands)
    is_upper = last['Close'] >= last['BB_Upper']
    is_lower = last['Close'] <= last['BB_Lower']
    
    if is_upper:
        bb_status = "볼린저 밴드 상단 도달 (과열 경계)"
    elif is_lower:
        bb_status = "볼린저 밴드 하단 이탈 (기술적 반등 기대)"
    else:
        bb_status = "밴드 내 안정적 주가 흐름"

    # --- 동적 AI 종합 요약 생성 로직 ---
    summary_text = ""
    if is_uptrend:
        if macd_cross_down or (not macd_bull and is_upper):
            summary_text = "기존의 상승 추세가 이어지고 있으나, 모멘텀 지표의 하락 반전(데드크로스) 또는 밴드 상단 저항으로 인해 단기 조정 리스크가 부각되고 있습니다. 추격 매수는 자제하고 일부 차익 실현을 통한 리스크 관리를 권장합니다."
        elif macd_bull:
            summary_text = "이평선 정배열의 견조한 상승 추세 속에서 MACD 매수 모멘텀이 잘 유지되고 있습니다. 밴드 상단 돌파 시 추가 랠리가 가능하므로, 20일선을 주요 지지선으로 설정하고 추세 추종(Trend-following) 관점을 유지하는 것이 유리합니다."
        else:
            summary_text = "상승 추세 내에서 단기 숨고르기가 진행 중입니다. 주요 지지선(20일선) 이탈 여부를 확인하며 차분히 대응하시기 바랍니다."
    elif is_downtrend:
        if macd_cross_up or (macd_bull and is_lower):
            summary_text = "단기 낙폭 과대에 따른 기술적 반등 시그널(골든크로스 및 밴드 하단 지지)이 포착되었습니다. 다만 중장기 이평선이 역배열 상태이므로, 본격적인 추세 전환보다는 짧은 호흡의 단기 트레이딩 관점 접근이 바람직합니다."
        else:
            summary_text = "완연한 역배열 하락 추세 속에서 하방 압력이 지속되고 있습니다. 아직 뚜렷한 바닥 확인 시그널이 부재하므로, 이른 물타기나 신규 진입을 철저히 지양하고 관망하는 것을 강력히 권장합니다."
    else:
        if macd_cross_up:
            summary_text = "주가가 이평선 밀집 수렴 구간을 지나며 골든크로스를 동반한 상방 턴어라운드 시도를 하고 있습니다. 새로운 상승 추세 형성의 초입일 가능성이 있으므로 분할 매수로 대응해 볼 만한 유의미한 변곡점입니다."
        elif macd_cross_down:
            summary_text = "혼조세 속에서 모멘텀이 약화되며 하단 지지력을 테스트하고 있습니다. 밴드 하단 이탈 시 실망 매물이 출회될 수 있으므로 지지선 붕괴 시 리스크 관리에 만전을 기하시기 바랍니다."
        else:
            summary_text = "뚜렷한 방향성을 상실한 채 이평선 부근에서 에너지를 응축하는 횡보 국면입니다. 향후 MACD 모멘텀의 방향과 볼린저 밴드 이탈(상향/하향) 방향에 따라 새로운 추세가 결정될 것이므로 확인 후 진입하는 박스권 트레이딩이 유효합니다."

    html = f"""
    <div style="background-color: #1e293b; border-left: 4px solid {trend_color}; padding: 18px; border-radius: 6px; margin-top: 16px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
        <h5 style="color: #f8fafc; margin-top: 0; font-size: 16px; margin-bottom: 12px;">🤖 AI 퀀트 차트 분석 리포트 : {code_name}</h5>
        <ul style="color: #cbd5e1; font-size: 14px; line-height: 1.8; margin-bottom: 0; padding-left: 20px;">
            <li><b>현재 추세:</b> <span style="color: {trend_color}; font-weight: 600;">{trend_status}</span></li>
            <li><b>모멘텀 (MACD):</b> {macd_status}</li>
            <li><b>변동성 (Bollinger):</b> {bb_status}</li>
            <li style="margin-top: 8px;"><b>AI 종합 요약:</b> <span style="color: #f1f5f9;">{summary_text}</span></li>
        </ul>
    </div>
    """
    return html

st.markdown("<h4 style='color: #e2e8f0; font-weight: 600; margin-top: 30px;'>📈 ADVANCED CHART TERMINAL</h4>", unsafe_allow_html=True)
current_stocks = st.session_state.stock_df["종목명"].dropna().tolist()

if current_stocks:
    selected_stock = st.selectbox("종목 선택", current_stocks, label_visibility="collapsed")
    matched_row = st.session_state.stock_df[st.session_state.stock_df["종목명"] == selected_stock]
    target_code = str(matched_row["코드"].values[0]) if not matched_row.empty else "005930"
    
    if target_code:
        try:
            # 6개월치 데이터 로드 (이동평균 등 보조지표 계산을 위해 넉넉히 가져옴)
            hist = yf.Ticker(f"{target_code}.KS").history(period="6mo")
            if hist.empty:
                hist = yf.Ticker(f"{target_code}.KQ").history(period="6mo")
                
            if not hist.empty and len(hist) > 60:
                # 보조지표 계산
                df_chart = hist[['Close', 'Volume']].copy()
                df_chart['MA20'] = df_chart['Close'].rolling(window=20).mean()
                df_chart['MA60'] = df_chart['Close'].rolling(window=60).mean()
                
                # 볼린저 밴드
                std20 = df_chart['Close'].rolling(window=20).std()
                df_chart['BB_Upper'] = df_chart['MA20'] + (std20 * 2)
                df_chart['BB_Lower'] = df_chart['MA20'] - (std20 * 2)
                
                # MACD
                ema12 = df_chart['Close'].ewm(span=12, adjust=False).mean()
                ema26 = df_chart['Close'].ewm(span=26, adjust=False).mean()
                df_chart['MACD'] = ema12 - ema26
                df_chart['Signal'] = df_chart['MACD'].ewm(span=9, adjust=False).mean()
                
                # 최근 3개월 데이터만 슬라이싱하여 시각화 (초기 계산 왜곡 방지)
                df_view = df_chart.last("90D")
                
                # 차트 탭 구성
                tab1, tab2, tab3 = st.tabs(["💰 가격 및 이평선 (Price & Bands)", "📉 모멘텀 (MACD)", "📊 거래량 (Volume)"])
                
                with tab1:
                    st.line_chart(df_view[['Close', 'MA20', 'MA60', 'BB_Upper', 'BB_Lower']])
                with tab2:
                    st.line_chart(df_view[['MACD', 'Signal']])
                with tab3:
                    st.bar_chart(df_view['Volume'])
                
                # 하단 추론형 AI 애널리스트 브리핑 출력
                st.markdown(get_ai_analyst_opinion(df_chart, selected_stock), unsafe_allow_html=True)
                
            else:
                st.info("차트 및 지표를 계산하기 위한 시세 데이터가 부족합니다.")
        except Exception:
            st.info("차트 통신 지연 중입니다.")
