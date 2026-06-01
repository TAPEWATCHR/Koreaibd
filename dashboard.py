# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import sqlite3
import streamlit.components.v1 as components
import os
import altair as alt
from streamlit_gsheets import GSheetsConnection # 💡 구글 시트 연동 라이브러리 유지

def init_db():
    conn = sqlite3.connect('kr_ibd_system.db')
    # 호환성을 위해 유지
    conn.execute("CREATE TABLE IF NOT EXISTS favorites (symbol TEXT PRIMARY KEY)")
    conn.close()

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
    except: 
        hist = pd.DataFrame()
    conn.close()
    return hist

# --- ☁️ 구글 시트 기반 즐겨찾기 시스템 (기존 틀 유지) ---
def get_gsheet_conn():
    return st.connection("gsheets", type=GSheetsConnection)

def get_favorites_from_gsheet():
    try:
        conn = get_gsheet_conn()
        df = conn.read(worksheet="시트1", ttl=0) 
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
        conn.update(worksheet="시트1", data=new_df)
        st.cache_data.clear() 
        return True
    except Exception as e:
        st.error(f"🚨 구글 시트 저장 실패: {e}")
        return False
# ----------------------------------------------------

# --- 🇰🇷 한국 시장 맞춤형 포맷팅 함수들 ---
def format_currency_krw(val):
    try:
        return f"{int(val):,}원"
    except: 
        return "0원"

def format_adv_krw(val):
    """원화 거래대금을 '억원' 단위로 보기 쉽게 포맷팅"""
    try:
        val = float(val)
        if val >= 1e12:
            return f"{val/1e12:.2f}조원"
        elif val >= 1e8:
            return f"{val/1e8:.1f}억원"
        return f"{val:,.0f}원"
    except: 
        return "0원"

# ================= UI 디자인 (기존의 유려한 다크 테마 유지) =================
st.set_page_config(layout="wide", page_title="KR Market Leaders Terminal", page_icon="🇰🇷")
st.markdown("""
<style>
    .stApp { background-color: #161C27 !important; }
    
    /* 메인 화면 기본 글씨는 하얗게 */
    .block-container p, .block-container span, .block-container h1, .block-container h2, 
    .block-container h3, .block-container h4, .block-container label { color: #FFFFFF !important; }
    
    /* 사이드바 글씨는 어둡게 */
    [data-testid="stSidebar"] { background-color: #F8F9FA !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label { color: #1E293B !important; font-size: 13px; }
    
    /* 버튼 배경 및 테두리 */
    .stButton > button { 
        background-color: #FFFFFF !important; 
        border: 1px solid #CBD5E1 !important; 
    }
    
    /* 버튼 안의 글씨를 어두운 남색으로 강제 지정 */
    .stButton > button p, .stButton > button span, .stButton > button div {
        color: #1E293B !important; 
        font-weight: bold !important;
    }

    .overview-panel { background: #2A3143; padding: 1.2rem; border-radius: 8px; color: #FFFFFF !important; line-height: 1.6;}
    .check-box { padding: 10px; margin-bottom: 5px; border-radius: 5px; background-color: #1E293B; border-left: 5px solid #3b82f6; color: #D1D5DB !important; }
    .check-pass { border-left-color: #10b981; }
    .check-fail { border-left-color: #ef4444; }
</style>
""", unsafe_allow_html=True)

init_db()
df = get_data()
fav_list = get_favorites_from_gsheet()

if not df.empty:
    # 안전 장치 컬럼 초기화
    if 'adv_50' not in df.columns: df['adv_50'] = 0.0
    if 'industry_rs_score' not in df.columns: df['industry_rs_score'] = 0
    if 'ad_grade' not in df.columns: df['ad_grade'] = 'C'
    if 'smr_grade' not in df.columns: df['smr_grade'] = 'C'
    if 'industry' not in df.columns: df['industry'] = 'Unknown'
    if 'per' not in df.columns: df['per'] = 0.0
    if 'roe' not in df.columns: df['roe'] = 0.0

    with st.sidebar:
        is_mobile = st.toggle("📱 모바일 화면 최적화", value=False)
        st.divider()

        st.header("필터")
        # 🇰🇷 한국 시장에 맞는 기본값 셋팅 (최소 주가 1,000원 / 최소 거래대금 10억원)
        min_p = st.number_input("최소 주가 (원)", value=1000)
        min_adv_m = st.number_input("최소 거래대금 (억원)", value=10)
        rs_m = st.slider("최소 RS 점수", 1, 99, 80)
        ind_rs_m = st.slider("최소 시장 점수", 1, 99, 70)
        
        with st.expander("🏭 소속 시장 필터"):
            all_inds = sorted(df['industry'].unique().tolist()) # KOSPI, KOSDAQ 추출
            if 'ind_sel' not in st.session_state: st.session_state.ind_sel = all_inds
            
            c_all = st.columns(1)
            is_all = len(st.session_state.ind_sel) == len(all_inds)
            if st.button(f"{'●' if is_all else '○'} 전체 선택/해제", key="all_ind_btn"):
                st.session_state.ind_sel = [] if is_all else all_inds
                st.rerun()
            
            cols = st.columns(2)
            for idx, ind in enumerate(all_inds):
                with cols[idx % 2]:
                    is_sel = ind in st.session_state.ind_sel
                    if st.button(f"{'●' if is_sel else '○'} {str(ind)}", key=f"ind_{ind}", use_container_width=True):
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

        smr_sel = btn_filter("SMR 등급 (실적 우량도)", "smr_sel")
        ad_sel = btn_filter("AD 수급 등급 (매집 강도)", "ad_sel")
        show_fav_only = st.checkbox("⭐ 관심종목만 보기", value=False)

    # 필터 마스킹 연산 (원화 억원 단위를 위해 100,000,000 곱해줌)
    mask = (df['price'] >= min_p) & (df['rs_score'] >= rs_m) & \
           (df['adv_50'] >= min_adv_m * 100000000) & (df['industry_rs_score'] >= ind_rs_m) & \
           (df['smr_grade'].isin(smr_sel)) & (df['ad_grade'].isin(ad_sel)) & \
           (df['industry'].isin(st.session_state.ind_sel))
    
    f_df = df[mask].sort_values('rs_score', ascending=False).copy()
    if show_fav_only: f_df = f_df[f_df['symbol'].isin(fav_list)]

    display_df = f_df.copy()
    display_df['price'] = display_df['price'].apply(format_currency_krw)
    display_df['adv_50'] = display_df['adv_50'].apply(format_adv_krw)

    if is_mobile:
        display_df = display_df[['symbol', 'price', 'rs_score', 'smr_grade', 'ad_grade']]
        display_df.rename(columns={'symbol': '종목', 'price': '가격', 'rs_score': 'RS점수', 'smr_grade': 'SMR등급', 'ad_grade': 'AD등급'}, inplace=True)
    else:
        display_df = display_df[['symbol', 'price', 'rs_score', 'industry_rs_score', 'smr_grade', 'ad_grade', 'adv_50', 'industry']]
        display_df.rename(columns={
            'symbol': '종목명', 'price': '현재가', 'adv_50': '50일 평균 거래대', 
            'rs_score': 'RS점수', 'industry_rs_score': '시장점수', 
            'smr_grade': 'SMR등급', 'ad_grade': 'AD등급', 'industry': '소속시장'
        }, inplace=True)

    if is_mobile:
        st.subheader(f"Leaders List ({len(display_df)})")
        sel_row = st.dataframe(display_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=350, use_container_width=True)
        st.divider()
        detail_container = st.container()
    else:
        col_l, col_r = st.columns([4, 5])
        with col_l:
            st.subheader(f"Leaders List ({len(display_df)})")
            sel_row = st.dataframe(display_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=800, use_container_width=True)
        detail_container = col_r

    with detail_container:
        if len(sel_row.selection.rows) > 0:
            target = f_df.iloc[sel_row.selection.rows[0]]
            if isinstance(target, pd.DataFrame): target = target.iloc[0] 
            full_symbol = target.get('symbol', 'UNKNOWN')
            
            c1, c2 = st.columns([4, 2] if is_mobile else [4, 1])
            with c1: st.markdown(f"## {full_symbol} <span style='font-size:18px; color:#9CA3AF;'>{target.get('industry', 'Unknown')}</span>", unsafe_allow_html=True)
            with c2:
                is_fav = full_symbol in fav_list
                if st.button("★ 관심해제" if is_fav else "☆ 관심저장", use_container_width=True):
                    success = toggle_favorite_gsheet(full_symbol)
                    if success: st.rerun()
            
            # 🌟 두 개의 탭으로 정제 (차트, 🛡️ 체크리스트 & 펀더멘탈)
            t_chart, t_check = st.tabs(["📊 실시간 차트", "🛡️ 투자 캔슬림 검증 시스템"])
            
            with t_chart:
                chart_height = 350 if is_mobile else 500
                
                # 🌟 [트레이딩뷰 해결 핵심] "005930 (삼성전자)"에서 앞의 '005930'만 추출하여 KRX 심볼 완성
                ticker_only = full_symbol.split(' ')[0].strip()
                tradingview_symbol = f"KRX:{ticker_only}"
                
                tv_widget = f"""
                <div class="tradingview-widget-container" style="height: {chart_height}px; width: 100%;">
                  <div id="tradingview_{ticker_only}" style="height: calc(100% - 32px); width: 100%;"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                  <script type="text/javascript">
                  new TradingView.widget({{"autosize": true, "symbol": "{tradingview_symbol}", "interval": "D", "timezone": "Asia/Seoul", "theme": "dark", "style": "1", "locale": "kr", "enable_publishing": false, "backgroundColor": "#161C27", "gridColor": "#2A3143", "hide_top_toolbar": false, "save_image": false, "container_id": "tradingview_{ticker_only}"}});
                  </script>
                </div>
                """
                components.html(tv_widget, height=chart_height)

                # 역사적 RS 히스토리 선형 차트 출력부
                rs_hist_df = get_rs_history(full_symbol)
                if not rs_hist_df.empty and len(rs_hist_df) > 1:
                    rs_hist_df['date'] = pd.to_datetime(rs_hist_df['date'])
                    
                    if 'industry_rs_score' in rs_hist_df.columns:
                        rs_hist_df['industry_rs_score'] = rs_hist_df['industry_rs_score'].replace(0, pd.NA)
                        melted_df = rs_hist_df.melt('date', value_vars=['rs_score', 'industry_rs_score'], var_name='Type', value_name='Score')
                        melted_df = melted_df.dropna(subset=['Score'])
                        melted_df['Type'] = melted_df['Type'].map({'rs_score': '개별 RS 점수', 'industry_rs_score': '시장 점수'})
                        
                        rs_chart = alt.Chart(melted_df).mark_line(strokeWidth=2).encode(
                            x=alt.X('date:T', title='날짜'), 
                            y=alt.Y('Score:Q', title='점수', scale=alt.Scale(domain=[1, 100])),
                            color=alt.Color('Type:N', title='지표', scale=alt.Scale(domain=['개별 RS 점수', '시장 점수'], range=['#64ffda', '#f59e0b']))
                        ).properties(height=240)
                    else:
                        rs_chart = alt.Chart(rs_hist_df).mark_line(color="#64ffda", strokeWidth=2).encode(
                            x=alt.X('date:T', title='날짜'), y=alt.Y('rs_score:Q', title='RS 점수', scale=alt.Scale(domain=[1, 100]))
                        ).properties(height=240)
                        
                    st.altair_chart(rs_chart, use_container_width=True)

            with t_check:
                price_val = float(target.get('price', 0))
                rs_val = int(target.get('rs_score', 0))
                smr_val = str(target.get('smr_grade', 'C'))
                ad_val = str(target.get('ad_grade', 'C'))
                adv_val = float(target.get('adv_50', 0))
                ind_rs_val = int(target.get('industry_rs_score', 0))
                per_val = float(target.get('per', 0))
                roe_val = float(target.get('roe', 0))

                # 📊 핵심 계량 재무 데이터 정보창 우선 배치
                st.markdown("#### 📊 실시간 수집 재무 데이터 요약")
                m_c1, m_c2, m_c3, m_c4 = st.columns(4)
                with m_c1: st.metric("현재가", format_currency_krw(price_val))
                with m_c2: st.metric("ROE (자기자본이익률)", f"{roe_val}%" if roe_val != 0 else "N/A")
                with m_c3: st.metric("PER (주가수익비율)", f"{per_val}배" if per_val != 0 else "N/A")
                with m_c4: st.metric("50일 평균 거래대금", format_adv_krw(adv_val))
                st.divider()

                # 🇰🇷 원화 유동성 기준 및 국내 시장 맞춤형 검증 체크리스트
                st.markdown("#### 캔슬림 (CAN SLIM) 전략 검증")
                canslim = [
                    {"name": "C (현재 실적 우량성): SMR 등급 A 또는 B (ROE 기반)", "pass": smr_val in ['A', 'B']},
                    {"name": "A (연간 이익 지속성): SMR 등급 A 또는 B", "pass": smr_val in ['A', 'B']},
                    {"name": "N (신고가/모멘텀 상태): RS 점수 80 이상 강력 유지", "pass": rs_val >= 80},
                    {"name": "S (수요와 공급): 50일 평균 거래대금 20억원 이상 유동성 확보", "pass": adv_val >= 2000000000},
                    {"name": "L (시장 주도성): 코스피/코스닥 시장 분위기 점수 70 이상", "pass": ind_rs_val >= 70},
                    {"name": "I (기관의 매집 동향): AD 수급 등급 A 또는 B (거래량 동반 상승 축적일 분석)", "pass": ad_val in ['A', 'B']},
                ]
                for c in canslim:
                    st.markdown(f'<div class="check-box {"check-pass" if c["pass"] else "check-fail"}">{"✅" if c["pass"] else "❌"} {c["name"]}</div>', unsafe_allow_html=True)

                st.markdown("#### 마크 미너비니 (Minervini VCP) 전략 검증")
                minervini = [
                    {"name": "최소 주가 필터: 주가 3,000원 이상 (소형 잡주 제외)", "pass": price_val >= 3000},
                    {"name": "주도주 모멘텀 일치도: RS 점수 70 이상 우상향 추세", "pass": rs_val >= 70},
                    {"name": "펀더멘탈 등급 만족도: SMR 등급 A, B (재무 건전)", "pass": smr_val in ['A', 'B']},
                    {"name": "매집 흔적 유효성: 최근 20일 AD 수급 등급 A, B, C 이내 안착", "pass": ad_val in ['A', 'B', 'C']},
                    {"name": "기관 진입 유동성: 50일 평균 거래대금 10억원 이상 충족", "pass": adv_val >= 1000000000}
                ]
                for c in minervini:
                    st.markdown(f'<div class="check-box {"check-pass" if c["pass"] else "check-fail"}">{"✅" if c["pass"] else "❌"} {c["name"]}</div>', unsafe_allow_html=True)
                
        else: 
            st.info("👈 왼쪽 리스트에서 주도주 종목을 선택해 주세요.")
else:
    st.warning("데이터베이스가 비어있습니다. 먼저 `kr_update_data.py`를 실행해서 데이터를 쌓아주세요.")
