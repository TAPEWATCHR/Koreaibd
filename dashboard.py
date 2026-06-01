# -*- coding: utf-8 -*-
import streamlit as st
import sqlite3
import pandas as pd
import streamlit.components.v1 as components

# 1. 페이지 기본 설정
st.set_page_config(layout="wide", page_title="한국 주식 IBD 주도주 시스템", page_icon="🇰🇷")

st.title("🇰🇷 한국형 IBD 주도주 스크리너")
st.markdown("---")

# 2. 데이터베이스 로드 함수
def load_data():
    conn = sqlite3.connect('kr_ibd_system.db')
    try:
        # 최신 스크리닝 결과 가져오기
        query = "SELECT * FROM repo_results"
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df

df = load_data()

if df.empty:
    st.error("🚨 데이터베이스가 비어있거나 올바르지 않습니다. GitHub Actions 가동 후 1분 뒤에 새로고침 해주세요.")
else:
    # 3. 🎛️ 사이드바 필터 시스템 구축
    st.sidebar.header("🔍 주도주 필터 옵션")
    
    # 시장 대분류 필터
    markets = sorted(df['industry'].unique().tolist())
    selected_markets = st.sidebar.multiselect("시장 선택", markets, default=markets)
    
    # RS 점수 컷오프 (CANSLIM 기준 기본 80점 이상 권장)
    min_rs = st.sidebar.slider("최저 RS 점수 (주가 모멘텀)", 1, 99, 80)
    
    # SMR 등급 필터 (A가 가장 우량)
    smr_grades = sorted(df['smr_grade'].unique().tolist())
    selected_smr = st.sidebar.multiselect("SMR 등급 (분기 실적 우량도)", smr_grades, default=['A', 'B', 'C'])
    
    # AD 등급 필터 (A가 기관 매집 강함)
    ad_grades = sorted(df['ad_grade'].unique().tolist())
    selected_ad = st.sidebar.multiselect("AD 등급 (최근 기관 수급 강도)", ad_grades, default=['A', 'B', 'C'])
    
    # 4. 🽵 필터링 데이터 연산
    filtered_df = df[
        (df['industry'].isin(selected_markets)) &
        (df['rs_score'] >= min_rs) &
        (df['smr_grade'].isin(selected_smr)) &
        (df['ad_grade'].isin(selected_ad))
    ].sort_values(by="rs_score", ascending=False)
    
    # 5. 🖥️ 메인 화면 레이아웃 분할 (좌측: 표 / 우측: 실시간 차트)
    col1, col2 = st.columns([1.1, 1.3])
    
    with col1:
        st.subheader(f"📊 스크리닝 결과 ({len(filtered_df)}개 종목)")
        
        # 유저에게 보여주기 위한 컬럼명 및 포맷 정제
        display_df = filtered_df.copy()
        display_df.columns = ['종목명', '현재가', 'RS 점수', '시장 점수', 'SMR 등급', 'AD 등급', '50일 평균 거래대금', '소속 시장']
        
        # 보기 편하게 단위 변환 및 포맷팅
        display_df['현재가'] = display_df['현재가'].map('{:,}원'.format)
        display_df['50일 평균 거래대금'] = (display_df['50일 평균 거래대금'] / 100000000).round(1).map('{:,}억원'.format)
        
        # 테이블 출력
        st.dataframe(display_df, use_container_width=True, height=520)
        
        # 차트 연동을 위한 종목 선택창
        stock_list = filtered_df['symbol'].tolist()
        if stock_list:
            selected_stock = st.selectbox("🎯 실시간 차트를 볼 종목을 선택하세요", stock_list)
        else:
            selected_stock = None
            st.warning("필터 조건에 맞는 종목이 없습니다. 사이드바 조건을 완화해 보세요.")
            
    with col2:
        if selected_stock:
            st.subheader(f"📈 {selected_stock} 실시간 차트")
            
            # 🌟 [트레이딩뷰 해결 핵심] "005930 (삼성전자)"에서 공백 기준으로 앞의 '005930'만 추출
            ticker_only = selected_stock.split(' ')[0].strip()
            tradingview_symbol = f"KRX:{ticker_only}"
            
            # TradingView Embed HTML Widget
            tv_widget_html = f"""
            <div class="tradingview-widget-container" style="height:550px; width:100%;">
              <div id="tradingview_chart_kr"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
              new TradingView.widget({{
                "autosize": true,
                "symbol": "{tradingview_symbol}",
                "interval": "D",
                "timezone": "Asia/Seoul",
                "theme": "dark",
                "style": "1",
                "locale": "ko",
                "toolbar_bg": "#f1f3f6",
                "enable_publishing": false,
                "hide_side_toolbar": false,
                "allow_symbol_change": false,
                "container_id": "tradingview_chart_kr"
              }});
              </script>
            </div>
            """
            # 스트림릿 컴포넌트로 HTML 주입
            components.html(tv_widget_html, height=560)
        else:
            st.info("왼쪽 테이블에서 종목을 발굴하면 여기에 트레이딩뷰 차트가 로드됩니다.")
