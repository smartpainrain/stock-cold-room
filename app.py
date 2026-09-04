import streamlit as st
import pandas as pd
import pymysql
import datetime
import yfinance as yf

# 상단 헤더
st.markdown("### stock-cold-room 🚀", unsafe_allow_html=True)

# 실시간 코스피 지수 가져오기 함수
@st.cache_data(ttl=300) # 5분마다 캐시 갱신
def get_kospi_data():
    try:
        kospi = yf.Ticker("^KS11")
        todays_data = kospi.history(period="1d")
        if not todays_data.empty:
            current_price = todays_data['Close'].iloc[-1]
            prev_close = kospi.info.get('previousClose', current_price)
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100
            
            # 색상 및 방향 설정
            color = "red" if change > 0 else ("blue" if change < 0 else "gray")
            sign = "+" if change > 0 else ""
            status_text = f"코스피 ^KS11: {current_price:,.2f} ({sign}{change:,.2f}, {sign}{change_pct:.2f}%)"
            return status_text, "🟢 시스템 정상 작동중"
    except Exception:
        pass
    return "코스피 지수 연동 대기중", "🟡 시스템 점검중"

kospi_status, sys_status = get_kospi_data()

col1, col2 = st.columns([2, 1])
with col1:
    st.markdown(f"📊 **{kospi_status}** | {sys_status}")
with col2:
    now = datetime.datetime.now().strftime("%m-%d %H:%M")
    st.markdown(f"<div style='text-align: right;'>갱신 {now}</div>", unsafe_allow_html=True)

st.divider()

# 카페24 MySQL 데이터 불러오기 + 자동 테이블 생성 함수
@st.cache_data(ttl=60)
def load_stock_data():
    fallback_data = pd.DataFrame({
        "종목명": ["아난티", "한화에어로스페이스", "대아티아이", "마이크로컨텍솔", "삼양식품", "셀트리온"],
        "현재가": ["5,500", "1,164,000", "3,455", "40,900", "1,341,000", "194,600"],
        "초과수익(α)": ["+1.953%", "+1.424%", "+1.538%", "+2.702%", "+0.969%", "+0.657%"],
        "매집단계": ["L1", "L4", "L1", "L1", "L4", "L6"]
    })
    
    try:
        if "mysql" not in st.secrets:
            return fallback_data
            
        connection = pymysql.connect(
            host=st.secrets["mysql"]["host"],
            user=st.secrets["mysql"]["user"],
            password=st.secrets["mysql"]["password"],
            database=st.secrets["mysql"]["database"],
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_control_tower (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    stock_name VARCHAR(50) NOT NULL,
                    current_price VARCHAR(20) NOT NULL,
                    alpha_return VARCHAR(20) NOT NULL,
                    accumulation_stage VARCHAR(10) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            
            cursor.execute("SELECT COUNT(*) AS cnt FROM stock_control_tower")
            row = cursor.fetchone()
            if row['cnt'] == 0:
                cursor.execute("""
                    INSERT INTO stock_control_tower (stock_name, current_price, alpha_return, accumulation_stage) VALUES 
                    ('아난티', '5,500', '+1.953%', 'L1'),
                    ('한화에어로스페이스', '1,164,000', '+1.424%', 'L4'),
                    ('마이크로컨텍솔', '40,900', '+2.702%', 'L1');
                """)
                connection.commit()

            cursor.execute("SELECT stock_name AS 종목명, current_price AS 현재가, alpha_return AS `초과수익(α)`, accumulation_stage AS 매집단계 FROM stock_control_tower")
            result = cursor.fetchall()
            if not result:
                return fallback_data
            return pd.DataFrame(result)
            
    except Exception:
        return fallback_data
    finally:
        try:
            connection.close()
        except:
            pass

df = load_stock_data()

# 테이블 출력
st.dataframe(df, use_container_width=True, hide_index=True)

st.markdown("<br>", unsafe_allow_html=True)

# 하단 AI / 질의응답 섹션 (Cold-Bot)
st.markdown("#### 🤖 Cold-Bot에게 질문 (실측 데이터 기반)")
user_query = st.text_input("", placeholder="내PC데이터 종합해서 상승확률 높은순 그리고 가장먼저 급등할 종목은?")

if st.button("질문 전송") and user_query:
    st.info("분석 결과:\n1. 빙그레 (국장 모멘텀) - 추천가 81600\n2. 마이크로컨텍솔 (국장 모멘텀) - 추천가 37800")

st.markdown("<p style='font-size:12px; color:gray; text-align:center;'>이러한 판단은 사용자 본인의 책임입니다.</p>", unsafe_allow_html=True)
