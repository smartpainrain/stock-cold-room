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
# [반응형 프리미엄 터미널 커스텀 CSS]
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
</style>
""", unsafe_allow_html=True)

http_session = requests.Session()

# -------------------------------------------------------------
# 1. 설정 및 인증 / GitHub / 텔레그램
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
            http_session.post(url, json={"chat_id": chat_id, "text": msg}, timeout=3)
        except:
            pass

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
        return pd.DataFrame(columns=["종목명", "코드"])
    return df[["종목명", "코드"]].copy()

def save_to_github(df):
    clean_df = df[["종목명", "코드"]].copy()
    json_content = json.dumps(clean_df.to_dict(orient="records"), ensure_ascii=False, indent=2)
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write(json_content)
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
# 2. 퀀트 분석 엔진 (NXT 야간장 반영 & 실적 파싱 완벽 복구)
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
        items = http_session.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3).json().get("items", [[]])[0]
        for item in items:
            if cleaned in str(item[1]).replace(" ", "").lower(): return str(item[0])
    except: pass
    return ""

def fetch_full_stock_analysis(code: str):
    default_res = {
        "현재가": 0, "수급": "⚠️ 데이터 집계불가", "실적진단": "지표 산출불가", 
        "20일이격": "-", "RSI": 50.0, "종합의견": "🟡 관망 (50점)"
    }
    if not code: return default_res
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    # 1. NXT 장외체결가 및 실시간 체결가 다중 추적
    cur_p = 0
    # 1-1. polling API 실시간 응답 (NXT/시간외 필드 우선 추출)
    try:
        url_rt = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
        rt_json = http_session.get(url_rt, headers=headers, timeout=3).json()
        if "datas" in rt_json and rt_json["datas"]:
            d0 = rt_json["datas"][0]
            # overMarketPriceInfo 객체 또는 overMarketPrice 필드 우선 확인
            over_p = d0.get("overMarketPrice") or d0.get("nxtPrice")
            if not over_p and isinstance(d0.get("overMarketPriceInfo"), dict):
                over_p = d0["overMarketPriceInfo"].get("overMarketPrice") or d0["overMarketPriceInfo"].get("closePrice")
            if over_p:
                cur_p = int(str(over_p).replace(",", ""))
            elif d0.get("closePrice"):
                cur_p = int(str(d0["closePrice"]).replace(",", ""))
    except: pass

    # 1-2. 모바일 통합 API (NXT 2차 보완)
    if cur_p == 0:
        try:
            url_intg = f"https://m.stock.naver.com/api/stock/{code}/integration"
            intg_res = http_session.get(url_intg, headers=headers, timeout=3).json()
            deal = intg_res.get("dealInfo", {})
            nxt_p = deal.get("overMarketPrice") or deal.get("nxtPrice")
            if nxt_p:
                cur_p = int(str(nxt_p).replace(",", ""))
            elif deal.get("closePrice"):
                cur_p = int(str(deal.get("closePrice")).replace(",", ""))
        except: pass

    default_res["현재가"] = cur_p

    # 2. 밸류에이션 팩터 (네이버 공식 페이지 직접 파싱으로 정상 복구)
    val_score = 15
    val_label = "지표 산출불가"
    per_val = None

    try:
        url_main = f"https://finance.naver.com/item/main.naver?code={code}"
        main_res = http_session.get(url_main, headers=headers, timeout=3).text
        
        # 1순위: 메인 페이지의 _per 요소 직접 추출
        per_match = re.search(r'id="_per">([0-9\.,]+)<', main_res)
        if per_match:
            try:
                per_val = float(per_match.group(1).replace(",", ""))
            except: pass
            
        # 2순위: N/A 또는 적자 표기인지 확인
        if per_val is None:
            if re.search(r'id="_per">\s*N/A\s*<', main_res) or re.search(r'id="_per">\s*-\s*<', main_res):
                per_val = -1.0
                
        # 3순위: 모바일 integration API 보조 탐색
        if per_val is None:
            url_intg = f"https://m.stock.naver.com/api/stock/{code}/integration"
            intg_res = http_session.get(url_intg, headers=headers, timeout=3).json()
            raw_per = intg_res.get("consensusInfo", {}).get("per") or intg_res.get("dealInfo", {}).get("per")
            if raw_per:
                try:
                    per_val = float(str(raw_per).replace(",", ""))
                except:
                    per_val = -1.0
            else:
                for item in intg_res.get("totalInfos", []):
                    if "PER" in item.get("key", ""):
                        try:
                            per_val = float(str(item.get("value")).replace(",", ""))
                        except:
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
        default_res["실적진단"] = val_label
    except:
        default_res["실적진단"] = "지표 산출불가"

    # 3. 수급 팩터 (최근 5일 외인/기관)
    flow_score, frgn_sum, orgn_sum = 10, 0, 0
    flow_fetched = False
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

    if not flow_fetched:
        try:
            url_frgn = f"https://finance.naver.com/item/frgn.naver?code={code}"
            f_res = http_session.get(url_frgn, headers=headers, timeout=3)
            f_res.encoding = 'euc-kr'
            rows = re.findall(r'<tr[^>]*>.*?<td class="tc"[^>]*>.*?[0-9]{4}\.[0-9]{2}\.[0-9]{2}.*?</tr>', f_res.text, re.DOTALL)
            po, pf = [], []
            for r in rows[:5]:
                tds = re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)
                if len(tds) >= 7:
                    o = re.sub(r'<[^>]+>', '', tds[5]).replace(',', '').strip()
                    f = re.sub(r'<[^>]+>', '', tds[6]).replace(',', '').strip()
                    if o.lstrip('+-').isdigit(): po.append(int(o))
                    if f.lstrip('+-').isdigit(): pf.append(int(f))
            if len(po) >= 3:
                orgn_sum, frgn_sum = sum(po), sum(pf)
                flow_fetched = True
        except: pass

    if flow_fetched:
        if frgn_sum > 0 and orgn_sum > 0: flow_score, default_res["수급"] = 35, "🔥 쌍끌이 매수"
        elif frgn_sum < 0 and orgn_sum < 0: flow_score, default_res["수급"] = 0, "❄️ 양매도 이탈"
        elif frgn_sum > 0: flow_score, default_res["수급"] = 25, "📈 외인 집중매수"
        elif orgn_sum > 0: flow_score, default_res["수급"] = 20, "🏢 기관 순매수"
        else: flow_score, default_res["수급"] = 15, "⚖️ 수급 균형(중립)"

    # 4. 차트 모멘텀
    tech_score = 15
    try:
        fchart_url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=60&requestType=0"
        f_xml = http_session.get(fchart_url, headers=headers, timeout=3).text
        items = re.findall(r'<item data="(.*?)"', f_xml)
        if len(items) >= 20:
            closes = [float(x.split('|')[4]) for x in items]
            df_c = pd.Series(closes)
            
            last_close = df_c.iloc[-1]
            if cur_p == 0:
                cur_p = int(last_close)
                default_res["현재가"] = cur_p
            
            ma20 = df_c.rolling(20).mean().iloc[-1]
            disp20 = (cur_p / ma20) * 100
            default_res["20일이격"] = f"{disp20:.1f}%"

            delta = df_c.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean().replace(0, 0.0001)
            rs = gain / loss
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])
            default_res["RSI"] = round(rsi, 1)

            if rsi <= 30: tech_score = 35
            elif cur_p >= ma20 and 38.0 <= rsi <= 55.0: tech_score = 30
            elif 55.0 < rsi < 70.0: tech_score = 18
            elif rsi >= 75: tech_score = 0
    except: pass

    # 5. 복합 점수 산출
    total = val_score + flow_score + tech_score
    if total >= 85: default_res["종합의견"] = f"🔥 강력 매수 ({total}점)"
    elif total >= 70: default_res["종합의견"] = f"🟢 매수 ({total}점)"
    elif total >= 50: default_res["종합의견"] = f"🟡 관망 ({total}점)"
    else: default_res["종합의견"] = f"🔴 매도 ({total}점)"

    return default_res

# -------------------------------------------------------------
# 3. 화면 렌더링
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
        <div style="background: linear-gradient(145deg, #161b22, #0d1117); padding: 12px 18px; border-radius: 12px; border: 1px solid #30363d; display: flex; flex-direction: column; width: 100%; box-shadow: 0 4px 6px rgba(0,0,0,0.3);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="color: #8b949e; font-size: 11px; font-weight: 700; letter-spacing: 1px;">KOSPI</span>
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
        <p class="responsive-sub">Multi-Factor Equity Dashboard</p>
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
                else:
                    st.error("오류")
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
        input_name = st.text_input("종목명/코드", placeholder="예: 한미반도체 (인증 필요)" if not st.session_state.is_admin else "예: 한미반도체", disabled=not st.session_state.is_admin, label_visibility="collapsed")
    with col_bt:
        submitted = st.form_submit_button("➕ 추가", disabled=not st.session_state.is_admin, use_container_width=True)
    
    if submitted:
        if input_name.strip():
            code = resolve_code(input_name)
            if code:
                st.session_state.stock_df = pd.concat([st.session_state.stock_df, pd.DataFrame([{"종목명": input_name.strip(), "코드": code}])], ignore_index=True)
                save_to_github(st.session_state.stock_df)
                st.rerun()

# 멀티스레딩 병렬 처리
display_rows = []
codes = st.session_state.stock_df['코드'].tolist()

if codes:
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(codes)) as executor:
        analyzed_results = list(executor.map(fetch_full_stock_analysis, codes))
    
    for idx, row in st.session_state.stock_df.iterrows():
        ans = analyzed_results[idx]
        display_rows.append({
            "선택": False, "종목명": row["종목명"], "코드": row["코드"],
            "현재가": ans["현재가"], "실적": ans["실적진단"], "수급(5D)": ans["수급"],
            "20일선": ans["20일이격"], "RSI": ans["RSI"], "의견": ans["종합의견"]
        })

display_df = pd.DataFrame(display_rows)
st.caption("⚡ 퀀트 팩터 엔진 가동 중 (NXT 야간장 및 공식 실적 동기화)")

column_config = {
    "종목명": st.column_config.TextColumn(disabled=True),
    "코드": st.column_config.TextColumn(disabled=True),
    "현재가": st.column_config.NumberColumn(format="%d", disabled=True),
    "실적": st.column_config.TextColumn(disabled=True),
    "수급(5D)": st.column_config.TextColumn(disabled=True),
    "20일선": st.column_config.TextColumn(disabled=True),
    "RSI": st.column_config.NumberColumn(disabled=True),
    "의견": st.column_config.TextColumn(disabled=True),
}

column_config["선택"] = st.column_config.CheckboxColumn("삭제", disabled=not st.session_state.is_admin, default=False)

edited_df = st.data_editor(display_df, key="stock_editor", column_config=column_config, use_container_width=True, hide_index=True)

selected_rows = edited_df[edited_df["선택"] == True]
if st.session_state.is_admin and len(selected_rows) > 0:
    if st.button(f"🗑️ 선택 삭제 ({len(selected_rows)})"):
        codes_to_remove = selected_rows["코드"].tolist()
        st.session_state.stock_df = st.session_state.stock_df[~st.session_state.stock_df["코드"].isin(codes_to_remove)].reset_index(drop=True)
        save_to_github(st.session_state.stock_df)
        if "stock_editor" in st.session_state: del st.session_state["stock_editor"]
        st.rerun()

# -------------------------------------------------------------
# 4. 차트 터미널 및 퀀트 융합 AI 브리핑
# -------------------------------------------------------------
def get_ai_analyst_opinion(df, code_name, quant_score, quant_status):
    if df.empty or len(df) < 60: return ""
    last, prev = df.iloc[-1], df.iloc[-2]
    
    is_uptrend = last['Close'] > last['MA20'] > last['MA60']
    is_downtrend = last['Close'] < last['MA20'] < last['MA60']
    trend_status, trend_color = ("정배열 상승 추세", "#ff4b4b") if is_uptrend else ("역배열 하락 추세", "#3b82f6") if is_downtrend else ("추세 전환 및 횡보", "#faca2b")
    
    macd_up = last['MACD'] > last['Signal'] and prev['MACD'] <= prev['Signal']
    macd_dn = last['MACD'] < last['Signal'] and prev['MACD'] >= prev['Signal']
    macd_bull = last['MACD'] > last['Signal']
    macd_status = "🚨 골든크로스 발생" if macd_up else "⚠️ 데드크로스 발생" if macd_dn else "매수 우위 유지" if macd_bull else "매도 우위 지속"
        
    is_upper, is_lower = last['Close'] >= last['BB_Upper'], last['Close'] <= last['BB_Lower']
    bb_status = "상단 도달 (과열)" if is_upper else "하단 이탈 (반등기대)" if is_lower else "밴드 내 안정"

    summary_text = f"퀀트 스코어 <b style='color:#fff;'>{quant_score}점({quant_status})</b>. "
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
    tgt_code = st.session_state.stock_df[st.session_state.stock_df["종목명"] == sel_stock]["코드"].values[0]
    
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
            
            st.markdown(get_ai_analyst_opinion(df_c, sel_stock, q_score, q_stat), unsafe_allow_html=True)
    except Exception as e:
        st.info("차트를 로드할 수 없습니다.")
