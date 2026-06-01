# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import sqlite3
import os
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
    try:
        hist = pd.read_sql("SELECT * FROM rs_history WHERE symbol = ? ORDER BY date ASC", conn, params=(ticker,))
    except: hist = pd.DataFrame()
    conn.close()
    return hist

# --- ☁️ [구글 시트 연동] 시트2 (한국주식 전용) 설정 ---
def get_gsheet_conn():
    return st.connection("gsheets", type=GSheetsConnection)

def get_favorites_from_gsheet():
    try:
        conn = get_gsheet_conn()
        df = conn.read(worksheet="시트2", ttl=0) 
        if 'symbol' in df.columns:
            return df['symbol'].dropna().tolist()
        return []
    except Exception as e:
        return []

def toggle_favorite_gsheet(symbol):
    try:
        conn = get_gsheet_conn()
        favs = get_favorites_from_gsheet()
        
        if symbol in favs:
            favs.remove(symbol)
        else:
            favs.append(symbol)
        
        new_df = pd.DataFrame(favs, columns=['symbol'])
        conn.update(worksheet="시트2", data=new_df)
        st.cache_data.clear() 
        return True 
    except Exception as e:
        st.error(f"🚨 구글 시트 저장 실패: {e}")
        return False
# ----------------------------------------------------

def format_krw(val):
    try:
        val = float(val)
        if pd.isna(val) or val == 0: return "0원"
        return f"{int(val):,}원"
    except: return "0원"

def format_adv_krw(val):
    try:
        val = float(val)
        if val >= 1e8: return f"{val/1e8:.1f}억원"
        return f"{val:,.0f}원"
    except: return "0원"

# ================= UI 디자인 =================
st.set_page_config(layout="wide", page_title="국내주식 Market Leaders Terminal")
st.markdown("""
<style>
    .stApp { background-color: #161C27 !important; }
    .block-container p, .block-container span, .block-container h1, .block-container h2, 
    .block-container h3, .block-container h4, .block-container label { color: #FFFFFF !important; }
    [data-testid="stSidebar"] { background-color: #F8F9FA !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label { color: #1E293B !important; font-size: 13px; }
    .stButton > button { background-color: #FFFFFF !important; border: 1px solid #CBD5E1 !important; }
    .stButton > button p, .stButton > button span, .stButton > button div { color: #1E293B !important; font-weight: bold !important; }
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

        st.header("필터 조건")
        min_p = st.number_input("최소 주가 (원)", value=1000)
        min_adv_m = st.number_input("최소 거래대금 (억원)", value=10)
        rs_m = st.slider("최소 RS 점수", 1, 99, 80)
        ind_rs_m = st.slider("최소 시장군 RS 점수", 1, 99, 70)
        
        with st.expander("🏭 시장 구분 필터"):
            all_inds = sorted(df['industry'].unique().tolist())
            if 'ind_sel' not in st.session_state: st.session_state.ind_sel = all_inds
            
            is_all = len(st.session_state.ind_sel) == len(all_inds)
            if st.button(f"{'●' if is_all else '○'} 전체 선택/해제", key="all_ind_btn"):
                st.session_state.ind_sel = [] if is_all else all_inds
                st.rerun()
            
            for ind in all_inds:
                is_sel = ind in st.session_state.ind_sel
                if st.button(f"{'●' if is_sel else '○'} {ind}", key=f"ind_{ind}", use_container_width=True):
                    if is_sel: st.session_state.ind_sel.remove(ind)
                    else: st.session_state.ind_sel.append(ind)
                    st.rerun()

        def btn_filter(label, key):
            if key not in st.session_state: st.session_state[key] = ["A", "B", "C"]
            st.caption(label)
            cols = st.columns(3)
            for i, g in enumerate(["A", "B", "C", "D", "E", "전체"]):
                with cols[i%3]:
                    sel = g in st.session_state[key] if g != "전체" else len(st.session_state[key]) == 5
                    if st.button(f"{'●' if sel else '○'} {g}", key=f"{key}_{g}"):
                        if g == "전체": st.session_state[key] = ["A","B","C","D","E"] if not sel else []
                        else:
                            if g in st.session_state[key]: st.session_state[key].remove(g)
                            else: st.session_state[key].append(g)
                        st.rerun()
            return st.session_state[key]

        smr_sel = btn_filter("SMR 등급", "smr_sel")
        ad_sel = btn_filter("AD 수급 등급", "ad_sel")
        show_fav_only = st.checkbox("⭐ 관심종목만 보기", value=False)

    # 필터 마스킹 작업
    mask = (df['price'] >= min_p) & (df['rs_score'] >= rs_m) & \
           (df['adv_50'] >= min_adv_m * 100000000) & (df['industry_rs_score'] >= ind_rs_m) & \
           (df['smr_grade'].isin(smr_sel)) & (df['ad_grade'].isin(ad_sel)) & \
           (df['industry'].isin(st.session_state.ind_sel))
    
    f_df = df[mask].sort_values('rs_score', ascending=False).copy()
    if show_fav_only: f_df = f_df[f_df['symbol'].isin(fav_list)]

    display_df = f_df.copy()
    display_df['price_formatted'] = display_df['price'].apply(format_krw)
    display_df['adv_50_formatted'] = display_df['adv_50'].apply(format_adv_krw)

    if is_mobile:
        display_df = display_df[['symbol', 'price_formatted', 'rs_score', 'smr_grade', 'ad_grade']]
        display_df.rename(columns={'symbol': '종목명', 'price_formatted': '가격', 'rs_score': 'RS', 'smr_grade': 'SMR', 'ad_grade': 'AD'}, inplace=True)
    else:
        display_df = display_df[['symbol', 'price_formatted', 'rs_score', 'industry_rs_score', 'smr_grade', 'ad_grade', 'adv_50_formatted', 'industry']]
        display_df.rename(columns={'symbol': '종목명', 'price_formatted': '가격', 'adv_50_formatted': '50일 평거래대금', 'rs_score': 'RS점수', 'industry_rs_score': '시장RS점수', 'smr_grade': 'SMR등급', 'ad_grade': 'AD등급', 'industry': '시장구분'}, inplace=True)

    col_l, col_r = st.columns([1, 1] if is_mobile else [4, 5])
    with col_l:
        st.subheader(f"국내 주도주 리스트 ({len(display_df)}개)")
        sel_row = st.dataframe(display_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=750, use_container_width=True)

    with col_r:
        if len(sel_row.selection.rows) > 0:
            target = f_df.iloc[sel_row.selection.rows[0]]
            full_symbol_str = target.get('symbol', 'UNKNOWN')
            
            # 종목코드 추출 (예: "005930 (삼성전자)" 구조에서 숫자 6자리만 파싱)
            ticker_code = full_symbol_str.split('(')[0].strip()
            
            c1, c2 = st.columns([3, 1])
            with c1: st.markdown(f"## {full_symbol_str} <span style='font-size:16px; color:#9CA3AF;'>{target.get('industry', '')}</span>", unsafe_allow_html=True)
            with c2:
                is_fav = full_symbol_str in fav_list
                if st.button("★ 관심해제" if is_fav else "☆ 관심저장", use_container_width=True):
                    if toggle_favorite_gsheet(full_symbol_str):
                        st.rerun()
            
            t_chart, t_check = st.tabs(["📊 주가 차트", "🛡️ 돌파 체크리스트"])
            
            with t_chart:
                # TradingView 한국 주식 연동을 위한 KRX: 접두사 바인딩
                tv_widget = f"""
                <div class="tradingview-widget-container" style="height: 450px; width: 100%;">
                  <div id="tradingview_chart" style="height: calc(100% - 32px); width: 100%;"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                  <script type="text/javascript">
                  new TradingView.widget({{"autosize": true, "symbol": "KRX:{ticker_code}", "interval": "D", "timezone": "Asia/Seoul", "theme": "dark", "style": "1", "locale": "kr", "enable_publishing": false, "backgroundColor": "#161C27", "gridColor": "#2A3143", "container_id": "tradingview_chart"}});
                  </script>
                </div>
                """
                components.html(tv_widget, height=450)

                # RS 스코어 변화 트렌드 차트 생성
                rs_hist_df = get_rs_history(full_symbol_str)
                if not rs_hist_df.empty and len(rs_hist_df) > 1:
                    rs_hist_df['date'] = pd.to_datetime(rs_hist_df['date'])
                    rs_chart = alt.Chart(rs_hist_df).mark_line(color="#64ffda", strokeWidth=2).encode(
                        x=alt.X('date:T', title='날짜'), y=alt.Y('rs_score:Q', title='RS 점수', scale=alt.Scale(domain=[1, 100]))
                    ).properties(height=200, title="최근 RS 점수 변동 추이")
                    st.altair_chart(rs_chart, use_container_width=True)

            with t_check:
                price_val = float(target.get('price', 0))
                rs_val = int(target.get('rs_score', 0))
                smr_val = str(target.get('smr_grade', 'C'))
                ad_val = str(target.get('ad_grade', 'C'))
                adv_val = float(target.get('adv_50', 0))

                st.markdown("#### 한국형 캔슬림(CAN SLIM) 기준 판단")
                canslim = [
                    {"name": "C/A (실적 우량도): SMR 등급 A 또는 B", "pass": smr_val in ['A', 'B']},
                    {"name": "N (신고가 모멘텀): RS 점수 80 이상", "pass": rs_val >= 80},
                    {"name": "S (시장 유동성 규모): 평거래대금 50억원 이상", "pass": adv_val >= 5000000000},
                    {"name": "I (수급 상태): AD 수급 등급 A 또는 B", "pass": ad_val in ['A', 'B']},
                ]
                for c in canslim:
                    st.markdown(f'<div class="check-box {"check-pass" if c["pass"] else "check-fail"}">{"✅" if c["pass"] else "❌"} {c["name"]}</div>', unsafe_allow_html=True)
        else:
            st.info("👈 왼쪽 리스트에서 종목을 선택하시면 상세 차트와 전략 체크리스트가 표시됩니다.")
else:
    st.warning("데이터베이스가 비어있습니다. 터미널에서 `python kr_update_data.py`를 먼저 실행해주세요.")
