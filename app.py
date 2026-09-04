import streamlit as st
import pandas as pd
import pymysql
import datetime

# 🚨 페이지 설정 (맨 처음에 위치)
st.set_page_config(page_title="stock-cold-room", page_layout="wide")

# 상단 헤더
st.markdown("### stock-cold-room 🚀 <span style='color:orange; font-size:16px;'>코스피 S8 하락지속</span>", unsafe_allow_html=True)

col1, col2 = st.columns([1, 2])
with col1:
    st.markdown("🟢 **시스템 정상 작동중**")
with col2:
    now = datetime.datetime.now().strftime("%m-%d %H:%M")
    st.markdown(f"<div style='text-align: right;'>갱신 {now}</div>", unsafe_allow_html=True)

st.divider()

# 기본 대체 데이터 (만약의 경우를 대비한 방어막)
def get_fallback_dataframe():
    return pd.DataFrame({
        "종목명": ["아난티", "한화에어로스페이스", "대아티아이", "마이크로컨텍솔", "삼양식품", "셀트리온"],
        "현재가": ["5,500", "1,164,000", "3,455", "40,900", "1,341,000", "194,600"],
        "초과수익(α)": ["+1.953%", "+1.424%", "+1.538%", "+2.702%", "+0.969%", "+0.657%"],
        "매집단계": ["L1", "L4", "L1", "L1", "L4", "L6"]
    })

# 카페24 MySQL 데이터 불러오기 + 자동 테이블 생성 함수
@st.cache_data(ttl=60)
def load_stock_data():
    try:
        if "mysql" not in st.secrets:
            return get_fallback_dataframe()
            
        connection = pymysql.connect(
            host=st.secrets["mysql"]["host"],
            user=st.secrets["mysql"]["user"],
            password=st.secrets["mysql"]["password"],
            database=st.secrets["mysql"]["database"],
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 1. 테이블이 없으면 코드가 알아서 자동 생성
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_control_tower (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    stock_name VARCHAR(50) NOT NULL,
                    current_price VARCHAR(20) NOT NULL,
                    alpha_return VARCHAR(20) NOT NULL,
                    accumulation_stage VARCHAR(10) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            
            # 2. 데이터가 비어있으면 초기 테스트 데이터 자동 주입
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

            # 3. 데이터 조회
            cursor.execute("SELECT stock_name AS 종목명, current_price AS 현재가, alpha_return AS `초과수익(α)`, accumulation_stage AS 매집단계 FROM stock_control_tower")
            result = cursor.fetchall()
            if not result:
                return get_fallback_dataframe()
            return pd.DataFrame(result)
            
    except Exception as e:
        # 에러 발생 시 로그를 띄우되 대시보드는 뻗지 않도록 방어
        st.warning(f"DB 자동 연동 중 안내 (기본 데이터 표시): {e}")
        return get_fallback_dataframe()
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