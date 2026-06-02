# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import sqlite3
import os
import altair as alt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import FinanceDataReader as fdr
from streamlit_gsheets import GSheetsConnection

DB_NAME = "kr_ibd_system.db"

def get_data():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql("SELECT * FROM repo_results", conn)
    except:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df

def get_rs_history(ticker):
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        hist = pd.read_sql("SELECT * FROM rs_history WHERE symbol = ? ORDER BY date ASC", conn, params=(ticker,))
    except: 
        hist = pd.DataFrame()
    conn.close()
    return hist

def get_dart_financials_from_db(ticker):
    if not os.path.exists(DB_NAME): return pd.DataFrame(), pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        df_fin = pd.read_sql("SELECT * FROM dart_financials WHERE symbol = ?", conn, params=(ticker,))
    except:
        df_fin = pd.DataFrame()
    conn.close()
    
    if df_fin.empty:
        return pd.DataFrame(), pd.DataFrame()
        
    df_fin = df_fin.rename(columns={
        'period_name': '제무분기', 'revenue': '매출액(원)', 'operating_income': '영업이익(원)',
        'net_income': '당기순이익(원)', 'current_assets': '유동자산(원)', 'total_liabilities': '부채총계(원)'
    })
    
    ann_df = df_fin[df_fin['period_type'] == 'ANNUAL'].drop(columns=['symbol', 'period_type']).set_index('제무분기').T
    qtr_df = df_fin[df_fin['period_type'] == 'QUARTER'].drop(columns=['symbol', 'period_type']).set_index('제무분기').T
    return ann_df, qtr_df

def format_adv(val):
    try:
        val = float(val)
        if val >= 1e12: return f"{val/1e12:.2f}조 원"
        elif val >= 1e8: return f"{val/1e8:.2f}억 원"
        return f"{val:,.0f}원"
    except: return "0원"

# ================= UI 레이아웃 구성 =================
st.set_page_config(layout="wide", page_title="한국 주도주 수급 종합 터미널")
st.markdown("""
<style>
    .stApp { background-color: #161C27 !important; }
    .block-container p, .block-container span, .block-container h1, .block-container h2, 
    .block-container h3, .block-container h4, .block-container label { color: #FFFFFF !important; }
    [data-testid="stSidebar"] { background-color: #F8F9FA !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label { color: #1E293B !important; font-size: 13px; }
    .stButton > button { background-color: #FFFFFF !important; border: 1px solid #CBD5E1 !important; }
    .overview-panel { background: #2A3143; padding: 1.2rem; border-radius: 8px; color: #FFFFFF !important; }
    .check-box { padding: 10px; margin-bottom: 5px; border-radius: 5px; background-color: #1E293B; color: #D1D5DB !important; }
    .check-pass { border-left: 5px solid #10b981; }
    .check-fail { border-left: 5px solid #ef4444; }
</style>
""", unsafe_allow_html=True)

df = get_data()

if not df.empty:
    with st.sidebar:
        is_mobile = st.toggle("📱 모바일 화면 최적화", value=False)
        st.header("필터링 기준 설정")
        min_p = st.number_input("최소 주가 (원)", value=1000.0)
        min_adv_m = st.number_input("최소 거래대금 (억원)", value=10.0)
        rs_m = st.slider("최소 가중 RS 점수", 1, 99, 80)
        ind_rs_m = st.slider("최소 세부 섹터 RS 점수", 1, 99, 70)
        
        # 주도주 등급 멀티 선택 필터 구조 정의
        smr_sel = st.multiselect("SMR 등급 선택", ["A", "B", "C", "D", "E"], default=["A", "B", "C"])
        ad_sel = st.multiselect("기관 AD 수급등급 선택", ["A", "B", "C", "D", "E"], default=["A", "B"])

    mask = (df['price'] >= min_p) & (df['rs_score'] >= rs_m) & \
           (df['adv_50'] >= min_adv_m * 100000000) & (df['industry_rs_score'] >= ind_rs_m) & \
           (df['smr_grade'].isin(smr_sel)) & (df['ad_grade'].isin(ad_sel))
    
    f_df = df[mask].sort_values('rs_score', ascending=False).copy()

    display_df = f_df.copy()
    display_df['adv_50'] = display_df['adv_50'].apply(format_adv)
    display_df = display_df[['symbol', 'name', 'price', 'rs_score', 'industry_rs_score', 'ad_grade', 'adv_50', 'industry']]
    display_df.rename(columns={'symbol': '종목코드', 'name': '종목명', 'price': '현재가', 'adv_50': '50일평균대금', 'rs_score': '가중RS', 'industry_rs_score': '섹터RS', 'ad_grade': 'AD등급', 'industry': '세부섹터명'}, inplace=True)

    if is_mobile:
        st.subheader(f"주도주 스크리닝 결과 ({len(display_df)})")
        sel_row = st.dataframe(display_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=300, use_container_width=True)
        detail_container = st.container()
    else:
        col_l, col_r = st.columns([4, 5])
        with col_l:
            st.subheader(f"주도주 스크리닝 결과 ({len(display_df)})")
            sel_row = st.dataframe(display_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=750, use_container_width=True)
        detail_container = col_r

    with detail_container:
        if len(sel_row.selection.rows) > 0:
            target = f_df.iloc[sel_row.selection.rows[0]]
            ticker = target.get('symbol', 'UNKNOWN')
            
            st.markdown(f"## {target['name']} ({ticker}) <span style='font-size:16px; color:#9CA3AF;'>{target['industry']}</span>", unsafe_allow_html=True)
            
            t_chart, t_check, t_fin = st.tabs(["📊 로컬 바차트 (수급형)", "🛡️ 캔슬림 검증", "🧾 DART 표준재무"])
            
            with t_chart:
                # --- [요청 사항 1] 로컬 일봉 바차트 & 이동평균선 & 수급 거래량 차트 구현 ---
                try:
                    # 차트용 데이터 실시간 확보
                    df_chart = fdr.DataReader(ticker)
                    df_chart['Prev_Close'] = df_chart['Close'].shift(1)
                    df_chart = df_chart.tail(120) # 최근 120거래일 시각화
                    
                    # 이동평균선 연산
                    df_chart['MA20'] = df_chart['Close'].rolling(20).mean()
                    df_chart['MA50'] = df_chart['Close'].rolling(50).mean()
                    df_chart['MA200'] = df_chart['Close'].rolling(200).mean()
                    
                    # 색상 규칙 지정: 전일비 상승 시 검은색(#000000), 하락 시 빨간색(#FF4136)
                    # 다크 테마 가시성을 위해 차트 배경을 밝게 튜닝하여 검은색 바가 또렷하게 보이게 처리
                    colors = []
                    for idx, r in df_chart.iterrows():
                        if r['Close'] >= r['Prev_Close']:
                            colors.append('#000000')
                        else:
                            colors.append('#FF4136')
                            
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3])
                    
                    # 1. 일봉 바차트 추가
                    fig.add_trace(go.Ohlc(
                        x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'],
                        increasing_line_color='#000000', decreasing_line_color='#FF4136', name='가격일봉'
                    ), row=1, col=1)
                    
                    # 2. 이동평균선 추가
                    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA20'], line=dict(color='#1E3A8A', width=1.5), name='20일선'), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA50'], line=dict(color='#D97706', width=1.5), name='50일선'), row=1, col=1)
                    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA200'], line=dict(color='#7C3AED', width=1.5), name='200일선'), row=1, col=1)
                    
                    # 3. 거래량 바차트 추가 (가격 차트색과 완벽히 동화)
                    fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=colors, name='거래량'), row=2, col=1)
                    
                    # 레이아웃 가시성 확보 조정 작업
                    fig.update_layout(
                        height=500, showlegend=False,
                        paper_bgcolor='#F8F9FA', plot_bgcolor='#FFFFFF', # 검은색 바 표현을 위한 화이트보드 캔버스화
                        margin=dict(l=10, r=10, t=20, b=10),
                        xaxis=dict(gridcolor='#E2E8F0'), yaxis=dict(gridcolor='#E2E8F0'),
                        xaxis2=dict(gridcolor='#E2E8F0'), yaxis2=dict(gridcolor='#E2E8F0')
                    )
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as e:
                    st.error(f"차트 캔버스 빌드 실패: {e}")
                    
                # RS 트렌드선 매핑
                rs_hist_df = get_rs_history(ticker)
                if not rs_hist_df.empty and len(rs_hist_df) > 1:
                    rs_hist_df['date'] = pd.to_datetime(rs_hist_df['date'])
                    rs_chart = alt.Chart(rs_hist_df).mark_line(color="#64ffda", strokeWidth=2).encode(
                        x=alt.X('date:T', title='연산일자'), y=alt.Y('rs_score:Q', title='가중 RS 점수 추이', scale=alt.Scale(domain=[1, 100]))
                    ).properties(height=180)
                    st.altair_chart(rs_chart, use_container_width=True)

            with t_check:
                st.markdown("#### 📊 보정된 수급 계량 스코어 진단")
                st.metric(label="기관 순수 초과수급 AD 등급", value=f"{target['ad_grade']} 등급", delta="50일 거래량 돌파 필터링 적용")
                st.metric(label="섹터 내 가중 모멘텀 상대 순위 (개별 RS)", value=f"상위 {100 - int(target['rs_score'])}%")
                
                st.markdown("<br>", unsafe_allow_html=True)
                canslim = [
                    {"name": "N (신고가/수급 모멘텀): 가중 RS 점수 80 이상", "pass": int(target['rs_score']) >= 80},
                    {"name": "L (주도 섹터 컴포넌트): 세부 섹터 RS 점수 70 이상", "pass": int(target['industry_rs_score']) >= 70},
                    {"name": "I (기관 순수 축적 강도): AD 수급 등급 A 또는 B", "pass": target['ad_grade'] in ['A', 'B']},
                ]
                for c in canslim:
                    st.markdown(f'<div class="check-box {"check-pass" if c["pass"] else "check-fail"}">{"✅" if c["pass"] else "❌"} {c["name"]}</div>', unsafe_allow_html=True)

            with t_fin:
                # --- [요청 사항 2] DART 공시 연동 표준화 정렬 배치 표출 ---
                ann_fin, qtr_fin = get_dart_financials_from_db(ticker)
                
                if ann_fin.empty and qtr_fin.empty:
                    st.info("💡 DART 재무 테이블이 비어있습니다. 백엔드 스크립트에서 DART 수집을 먼저 구동해 주세요.")
                else:
                    if not ann_fin.empty:
                        st.markdown("#### 📅 DART 표준 연간 제무정보 (FMP 포맷)")
                        st.dataframe(ann_fin.style.format("{:,.0f} 원"), use_container_width=True)
                    if not qtr_fin.empty:
                        st.markdown("#### 📊 DART 표준 분기 제무정보 (FMP 포맷)")
                        st.dataframe(qtr_fin.style.format("{:,.0f} 원"), use_container_width=True)
                        
        else: st.info("👈 스크리닝 리스트에서 분석할 대한민국 주도주 종목을 선택해 주세요.")
else:
    st.warning("데이터베이스가 만료되었거나 비어있습니다. `update_data.py`를 터미널에서 구동하여 수급 계산을 동기화하십시오.")
