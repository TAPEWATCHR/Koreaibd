# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import sqlite3
import os
import requests
import altair as alt
import streamlit.components.v1 as components
from streamlit_gsheets import GSheetsConnection

def get_data():
    if not os.path.exists('kr_ibd_system.db'): return pd.DataFrame()
    conn = sqlite3.connect('kr_ibd_system.db')
    df = pd.read_sql("SELECT * FROM repo_results", conn)
    conn.close()
    return df

def get_rs_history(ticker):
    if not os.path.exists('kr_ibd_system.db'): return pd.DataFrame()
    conn = sqlite3.connect('kr_ibd_system.db')
    try: hist = pd.read_sql("SELECT * FROM rs_history WHERE symbol = ? ORDER BY date ASC", conn, params=(ticker,))
    except: hist = pd.DataFrame()
    conn.close()
    return hist

# --- ☁️ 네이버 금융 실시간 분기 실적 크롤러 ---
@st.cache_data(ttl=1800)
def get_naver_financials(ticker_code):
    """네이버 금융에서 연도별/분기별 상세 실적 표를 크롤링"""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker_code}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, headers=headers)
        res.encoding = 'euc-kr'
        
        dfs = pd.read_html(res.text)
        for df in dfs:
            # 주요재무정보가 포함된 테이블 탐색
            if any('매출액' in str(cell) for cell in df.iloc[:, 0]):
                # 멀티 인덱스 컬럼 정리
                df.columns = [f"{col[0]}_{col[1]}" if isinstance(col, tuple) else col for col in df.columns]
                df.rename(columns={df.columns[0]: '주요재무지표'}, inplace=True)
                return df
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- ☁️ 구글 시트 즐겨찾기 연동 (시트2) ---
def get_gsheet_conn():
    return st.connection("gsheets", type=GSheetsConnection)

def get_favorites_from_gsheet():
    try:
        conn = get_gsheet_conn()
        df = conn.read(worksheet="시트2", ttl=0) 
        if 'symbol' in df.columns: return df['symbol'].dropna().tolist()
        return []
    except: return []

def toggle_favorite_gsheet(symbol):
    try:
        conn = get_gsheet_conn()
        favs = get_favorites_from_gsheet()
        if symbol in favs: favs.remove(symbol)
        else: favs.append(symbol)
        new_df = pd.DataFrame(favs, columns=['symbol'])
        conn.update(worksheet="시트2", data=new_df)
        st.cache_data.clear() 
        return True 
    except Exception as e:
        st.error(f"🚨 구글 시트 저장 실패: {e}")
        return False

def format_krw(val):
    try: return f"{int(val):,}원"
    except: return "0원"

def format_adv_krw(val):
    try: return f"{val/1e8:.1f}억원" if val >= 1e8 else f"{val:,.0f}원"
    except: return "0원"

# ================= UI 레이아웃 =================
st.set_page_config(layout="wide", page_title="국내주식 Market Leaders Terminal")
st.markdown("""
<style>
    .stApp { background-color: #161C27 !important; }
    .block-container p, .block-container span, .block-container h1, .block-container h2, 
    .block-container h3, .block-container h4, .block-container label { color: #FFFFFF !important; }
    [data-testid="stSidebar"] { background-color: #F8F9FA !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label { color: #1E293B !important; font-size: 13px; }
    .stButton > button { background-color: #FFFFFF !important; border: 1px solid #CBD5E1 !important; }
    .stButton > button p, .stButton > button span { color: #1E293B !important; font-weight: bold !important; }
    .check-box { padding: 10px; margin-bottom: 5px; border-radius: 5px; background-color: #1E293B; border-left: 5px solid #3b82f6; color: #D1D5DB !important; }
    .check-pass { border-left-color: #10b981; }
    .check-fail { border-left-color: #ef4444; }
</style>
""", unsafe_allow_html=True)

df = get_data()
fav_list = get_favorites_from_gsheet()

if not df.empty:
    with st.sidebar:
        is_mobile = st.toggle("📱 모바일 화면 최적화", value=False)
        st.divider()
        st.header("필터 스크리닝")
        min_p = st.number_input("최소 주가 (원)", value=1000)
        min_adv_m = st.number_input("최소 거래대금 (억원)", value=5)
        rs_m = st.slider("최소 RS 점수 (모멘텀)", 1, 99, 80)
        
        all_inds = sorted(df['industry'].unique().tolist())
        if 'ind_sel' not in st.session_state: st.session_state.ind_sel = all_inds
        show_fav_only = st.checkbox("⭐ 관심종목만 필터링", value=False)

    mask = (df['price'] >= min_p) & (df['rs_score'] >= rs_m) & (df['adv_50'] >= min_adv_m * 100000000)
    f_df = df[mask].sort_values('rs_score', ascending=False).copy()
    if show_fav_only: f_df = f_df[f_df['symbol'].isin(fav_list)]

    display_df = f_df.copy()
    display_df['price_formatted'] = display_df['price'].apply(format_krw)
    display_df['adv_50_formatted'] = display_df['adv_50'].apply(format_adv_krw)

    display_df = display_df[['symbol', 'price_formatted', 'rs_score', 'industry_rs_score', 'smr_grade', 'adv_50_formatted', 'industry']]
    display_df.rename(columns={'symbol': '종목명', 'price_formatted': '가격', 'adv_50_formatted': '거래대금', 'rs_score': 'RS점수', 'industry_rs_score': '시장점수', 'smr_grade': 'SMR등급', 'industry': '시장'}, inplace=True)

    col_l, col_r = st.columns([1, 1] if is_mobile else [4, 5])
    with col_l:
        st.subheader(f"👑 주도주 리스트 ({len(display_df)}개)")
        sel_row = st.dataframe(display_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=750, use_container_width=True)

    with col_r:
        if len(sel_row.selection.rows) > 0:
            target = f_df.iloc[sel_row.selection.rows[0]]
            full_symbol_str = target.get('symbol', 'UNKNOWN')
            ticker_code = full_symbol_str.split('(')[0].strip()
            
            c1, c2 = st.columns([3, 1])
            with c1: st.markdown(f"## {full_symbol_str}")
            with c2:
                is_fav = full_symbol_str in fav_list
                if st.button("★ 관심해제" if is_fav else "☆ 관심저장", use_container_width=True):
                    if toggle_favorite_gsheet(full_symbol_str): st.rerun()
            
            t_chart, t_fin, t_check = st.tabs(["📊 차트 분석", "🧾 분기/연간 재무제표", "🛡️ 조건 검증"])
            
            with t_chart:
                tv_widget = f"""
                <div class="tradingview-widget-container" style="height: 420px; width: 100%;">
                  <div id="tradingview_chart" style="height: 100%; width: 100%;"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                  <script type="text/javascript">
                  new TradingView.widget({{"autosize": true, "symbol": "KRX:{ticker_code}", "interval": "D", "timezone": "Asia/Seoul", "theme": "dark", "style": "1", "locale": "kr", "container_id": "tradingview_chart"}});
                  </script>
                </div>
                """
                components.html(tv_widget, height=420)

            with t_fin:
                st.markdown("#### 🔍 네이버 금융 실시간 연간/분기 실적")
                fin_df = get_naver_financials(ticker_code)
                if not fin_df.empty:
                    st.dataframe(fin_df, hide_index=True, use_container_width=True)
                    st.caption("※ 정보 제공: 네이버 금융 (최근 4개년 연간 및 최근 6개 분기 실적 계정)")
                else:
                    st.info("해당 종목의 실적 표를 가져오지 못했습니다.")

            with t_check:
                rs_val = int(target.get('rs_score', 0))
                smr_val = str(target.get('smr_grade', 'C'))
                adv_val = float(target.get('adv_50', 0))

                st.markdown("#### 캔슬림(CAN SLIM) 주도주 스코어보드")
                canslim = [
                    {"name": "Current Earnings (분기 실적): 재무제표 탭에서 최근 분기 YoY 25%↑ 확인 필요", "pass": smr_val in ['A', 'B']},
                    {"name": "New Highs (신고가 모멘텀): RS 점수 80 이상 초우량 모멘텀", "pass": rs_val >= 80},
                    {"name": "Supply & Demand (유동성 규모): 일 거래대금 10억원 이상 확인", "pass": adv_val >= 1000000000},
                ]
                for c in canslim:
                    st.markdown(f'<div class="check-box {"check-pass" if c["pass"] else "check-fail"}">{"✅" if c["pass"] else "❌"} {c["name"]}</div>', unsafe_allow_html=True)
        else:
            st.info("👈 주도주 리스트에서 기업을 선택하면 실시간 분기 실적과 차트가 열립니다.")
else:
    st.warning("데이터베이스가 비어있습니다. 로컬 터미널에서 `python kr_update_data.py`를 먼저 실행해 주세요.")
