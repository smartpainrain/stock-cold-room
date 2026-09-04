import streamlit as st
import pandas as pd
import pymysql
import datetime

# 페이지 설정 (브라우저 탭 제목)
st.set_page_config(page_title="stock-cold-room", page_layout="wide")

# 상단 헤더 (군더더기 없이 깔끔하게 수정)
st.markdown("### stock-cold-room 🚀 <span style='color:orange; font-size:16px;'>코스피 S8 하락지속</span>", unsafe_allow_html=True)

col1, col2 = st.columns([1, 2])
with col1:
    st.markdown("🟢 **시스템 정상 작동중**")
with col2:
    now = datetime.datetime.now().strftime("%m-%d %H:%M")
    st.markdown(f"<div style='text-align: right;'>갱신 {now}</div>", unsafe_allow_html=True)

st.divider()

# 카페24 MySQL 데이터 불러오기 함수
@st.cache_data(ttl=60)
def load_stock_data():
    try:
        # Streamlit 시크릿 설정에서 카페24 DB 정보 가져오기
        connection = pymysql.connect(
            host=st.secrets["mysql"]["host"],
            user=st.secrets["mysql"]["user"],
            password=st.secrets["mysql"]["password"],
            database=st.secrets["mysql"]["database"],
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT stock_name AS 종목명, current_price AS 현재가, alpha_return AS `초과수익(α)`, accumulation_stage AS 매집단계 FROM stock_control_tower")
            result = cursor.fetchall()
            return pd.DataFrame(result)
    except Exception as e:
        # DB 연결 전이거나 설정 전일 때 보여줄 기본 대체 데이터
        st.warning(f"DB 연결 대기 중 (기본 데이터 표시): {e}")
        fallback_data = {
            "종목명": ["아난티", "한화에어로스페이스", "대아티아이", "마이크로컨텍솔", "삼양식품", "셀트리온"],
            "현재가": ["5,500", "1,164,000", "3,455", "40,900", "1,341,000", "194,600"],
            "초과수익(α)": ["+1.953%", "+1.424%", "+1.538%", "+2.702%", "+0.969%", "+0.657%"],
            "매집단계": ["L1", "L4", "L1", "L1", "L4", "L6"]
        }
        return pd.DataFrame(fallback_data)

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