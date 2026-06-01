# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import sqlite3
import requests
from bs4 import BeautifulSoup
import streamlit.components.v1 as components
import os
import altair as alt
from streamlit_gsheets import GSheetsConnection

# --- 🔤 [한국 주식 심볼 최적화] ---
def clean_tv_symbol(symbol):
    """트레이딩뷰용: 한국 주식은 KRX:6자리코드 규격을 맞추어야 차트가 나옴"""
    if not symbol: return ""
    raw = str(symbol).strip().upper()
    base = raw.split('.')[0].split('-')[0]
    if base.isdigit() and len(base) == 6:
        return f"KRX:{base}"
    return raw

# --- 💾 [데이터베이스 설정] 소문자 kr_ibd_system.db 반영 및 안정성 강화 ---
def init_db():
    conn = sqlite3.connect('kr_ibd_system.db')
    conn.execute("CREATE TABLE IF NOT EXISTS favorites (symbol TEXT PRIMARY KEY)")
    conn.close()

def get_data():
    if not os.path.exists('kr_ibd_system.db'): 
        return pd.DataFrame()
    
    conn = sqlite3.connect('kr_ibd_system.db')
    try:
        # 테이블이 없거나 데이터가 꼬여있어도 대시보드가 죽지 않도록 예외 처리
        df = pd.read_sql("SELECT * FROM repo_results", conn)
    except Exception as e:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df

def get_rs_history(ticker):
    if not os.path.exists('kr_ibd_system.db'): 
        return pd.DataFrame()
        
    conn = sqlite3.connect('kr_ibd_system.db')
    try:
        hist = pd.read_sql("SELECT * FROM rs_history WHERE symbol = ? ORDER BY date ASC", conn, params=(ticker,))
    except: 
        hist = pd.DataFrame()
    conn.close()
    return hist

# --- ☁️ [구글 시트 연동] ---
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

# --- 🧾 [안정성 확보] 야후 대신 네이버 금융 '기업실적분석' 테이블 크롤링 ---
@st.cache_data(ttl=3600)
def get_fin_data_naver(ticker):
    # [수정 완료] TypeError를 유발하던 괄호 분쟁이 없는 안전한 방식으로 변경
    code = "".join([c for c in str(ticker) if c.isdigit()])
    
    if not code or len(code) != 6:
        return pd.DataFrame(), pd.DataFrame(), {}, "올바른 6자리 대한민국 종목코드가 아닙니다."
    
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    # Cloud 서버 차단 방지를 위한 브라우저 우회 헤더 설정
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'euc-kr' # 네이버 한글 인코딩 깨짐 방지
        
        # HTML 내의 테이블들을 데이터프레임 리스트로 파싱
        dfs = pd.read_html(response.text)
        
        fin_df = None
        for df_item in dfs:
            # 첫 번째 열에 '매출액'이 적혀있는 '기업실적분석' 표 색출
            if not df_item.empty and any('매출액' in str(s) for s in df_item.iloc[:, 0].values):
                fin_df = df_item
                break
                
        if fin_df is None:
            return pd.DataFrame(), pd.DataFrame(), {}, "네이버 금융에서 재무 분석 테이블을 찾지 못했습니다."
            
        # 재무 지표 항목명을 인덱스로 배치
        fin_df = fin_df.set_index(fin_df.columns[0])
        
        # 멀티인덱스 여부에 따른 연간/분기 컬럼 슬라이싱 분기 처리
        if isinstance(fin_df.columns, pd.MultiIndex):
            annual_cols = [col for col in fin_df.columns if '연간' in str(col[0])]
            quarter_cols = [col for col in fin_df.columns if '분기' in str(col[0])]
            
            annual_df = fin_df[annual_cols].copy()
            annual_df.columns = [col[1] for col in annual_df.columns]
            
            quarter_df = fin_df[quarter_cols].copy()
            quarter_df.columns = [col[1] for col in quarter_df.columns]
        else:
            annual_cols = [col for col in fin_df.columns if '연간' in str(col)]
            quarter_cols = [col for col in fin_df.columns if '분기' in str(col)]
            
            annual_df = fin_df[annual_cols].copy()
            annual_df.columns = [str(col).split('_')[-1] for col in annual_df.columns]
            
            quarter_df = fin_df[quarter_cols].copy()
            quarter_df.columns = [str(col).split('_')[-1] for col in quarter_df.columns]
            
        annual_df.index.name = "주요재무지표"
        quarter_df.index.name = "주요재무지표"
        
        # 보조 기업정보 파싱
        soup = BeautifulSoup(response.text, 'html.parser')
        info_dict = {}
        h4_ind = soup.find('h4', string=lambda t: t and '업종' in t)
        if h4_ind:
            a_tag = h4_ind.find_next('a')
            if a_tag:
                info_dict['industry'] = a_tag.text.strip()
                
        return annual_df, quarter_df, info_dict, None
        
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), {}, f"데이터 호출 실패: {str(e)}"

def format_adv(val):
    try:
        val = float(val)
        if val >= 1e12: return f"{val/1e12:.2f}조 원"
        elif val >= 1e8: return f"{val/1e8:.2f}억 원"
        return f"{val:,.0f}원"
    except: return "0원"

# ================= UI 디자인 =================
st.set_page_config(layout="wide", page_title="한국 주식 주도주 터미널")
st.markdown("""
<style>
    .stApp { background-color: #161C27 !important; }
    .block-container p, .block-container span, .block-container h1, .block-container h2, 
    .block-container h3, .block-container h4, .block-container label { color: #FFFFFF !important; }
    [data-testid="stSidebar"] { background-color: #F8F9FA !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label { color: #1E293B !important; font-size: 13px; }
    .stButton > button { background-color: #FFFFFF !important; border: 1px solid #CBD5E1 !important; }
    .stButton > button p, .stButton > button span, .stButton > button div { color: #1E293B !important; font-weight: bold !important; }
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
    if 'adv_50' not in df.columns: df['adv_50'] = 0.0
    if 'industry_rs_score' not in df.columns: df['industry_rs_score'] = 0
    if 'ad_grade' not in df.columns: df['ad_grade'] = 'C'
    if 'smr_grade' not in df.columns: df['smr_grade'] = 'C'
    if 'industry' not in df.columns: df['industry'] = 'Unknown'

    with st.sidebar:
        is_mobile = st.toggle("📱 모바일 화면 최적화", value=False)
        st.divider()
        st.header("필터")
        min_p = st.number_input("최소 주가 (원)", value=1000.0)
        min_adv_m = st.number_input("최소 거래대금 (억원)", value=10.0)
        rs_m = st.slider("최소 RS 점수", 1, 99, 80)
        ind_rs_m = st.slider("최소 산업군 RS 점수", 1, 99, 70)
        
        with st.expander("🏭 산업군 필터"):
            all_inds = sorted(df['industry'].unique().tolist())
            if 'ind_sel' not in st.session_state: st.session_state.ind_sel = all_inds
            
            is_all = len(st.session_state.ind_sel) == len(all_inds)
            if st.button(f"{'●' if is_all else '○'} 전체 선택/해제", key="all_ind_btn"):
                st.session_state.ind_sel = [] if is_all else all_inds
                st.rerun()
            
            cols = st.columns(2)
            for idx, ind in enumerate(all_inds):
                with cols[idx % 2]:
                    is_sel = ind in st.session_state.ind_sel
                    if st.button(f"{'●' if is_sel else '○'} {str(ind)[:12]}..", key=f"ind_{ind}", use_container_width=True):
                        if is_sel: st.session_state.ind_sel.remove(ind)
                        else: st.session_state.ind_sel.append(ind)
                        st.rerun()

        def btn_filter(label, key):
            if key not in st.session_state: st.session_state[key] = ["A", "B"]
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

    mask = (df['price'] >= min_p) & (df['rs_score'] >= rs_m) & \
           (df['adv_50'] >= min_adv_m * 100000000) & (df['industry_rs_score'] >= ind_rs_m) & \
           (df['smr_grade'].isin(smr_sel)) & (df['ad_grade'].isin(ad_sel)) & \
           (df['industry'].isin(st.session_state.ind_sel))
    
    f_df = df[mask].sort_values('rs_score', ascending=False).copy()
    if show_fav_only: f_df = f_df[f_df['symbol'].isin(fav_list)]

    display_df = f_df.copy()
    display_df['adv_50'] = display_df['adv_50'].apply(format_adv)

    if is_mobile:
        display_df = display_df[['symbol', 'price', 'rs_score', 'smr_grade', 'ad_grade']]
        display_df.rename(columns={'symbol': '종목', 'price': '가격', 'rs_score': 'RS점수', 'smr_grade': 'SMR등급', 'ad_grade': 'AD등급'}, inplace=True)
    else:
        display_df = display_df[['symbol', 'price', 'rs_score', 'industry_rs_score', 'smr_grade', 'ad_grade', 'adv_50', 'industry']]
        display_df.rename(columns={'symbol': '종목', 'price': '가격', 'adv_50': '50일 평균 거래대금', 'rs_score': 'RS점수', 'industry_rs_score': '산업군RS점수', 'smr_grade': 'SMR등급', 'ad_grade': 'AD등급', 'industry': '산업군명'}, inplace=True)

    if is_mobile:
        st.subheader(f"주도주 리스트 ({len(display_df)})")
        sel_row = st.dataframe(display_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=350, use_container_width=True)
        st.divider()
        detail_container = st.container()
    else:
        col_l, col_r = st.columns([4, 5])
        with col_l:
            st.subheader(f"주도주 리스트 ({len(display_df)})")
            sel_row = st.dataframe(display_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=800, use_container_width=True)
        detail_container = col_r

    with detail_container:
        if len(sel_row.selection.rows) > 0:
            target = f_df.iloc[sel_row.selection.rows[0]]
            if isinstance(target, pd.DataFrame): target = target.iloc[0] 
            ticker = target.get('symbol', 'UNKNOWN')
            
            c1, c2 = st.columns([4, 2] if is_mobile else [4, 1])
            with c1: st.markdown(f"## {ticker} <span style='font-size:18px; color:#9CA3AF;'>{target.get('industry', 'Unknown')}</span>", unsafe_allow_html=True)
            with c2:
                is_fav = ticker in fav_list
                if st.button("★ 관심해제" if is_fav else "☆ 관심저장", use_container_width=True):
                    if toggle_favorite_gsheet(ticker): st.rerun()
            
            # 네이버 금융에서 원화 재무제표 로드
            ann_fin, qtr_fin, info, naver_error = get_fin_data_naver(ticker)
            t_chart, t_check, t_fin, t_biz = st.tabs(["📊 차트", "🛡️ 체크리스트", "🧾 재무제표", "🏢 기업 개요"])
            
            with t_chart:
                chart_height = 350 if is_mobile else 500
                tv_ticker = clean_tv_symbol(ticker)
                tv_widget = f"""
                <div class="tradingview-widget-container" style="height: {chart_height}px; width: 100%;">
                  <div id="tradingview_{tv_ticker.replace(':', '_')}" style="height: calc(100% - 32px); width: 100%;"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                  <script type="text/javascript">
                  new TradingView.widget({{"autosize": true, "symbol": "{tv_ticker}", "interval": "D", "timezone": "Asia/Seoul", "theme": "dark", "style": "1", "locale": "kr", "enable_publishing": false, "backgroundColor": "#161C27", "gridColor": "#2A3143", "hide_top_toolbar": false, "save_image": false, "container_id": "tradingview_{tv_ticker.replace(':', '_')}"}});
                  </script>
                </div>
                """
                components.html(tv_widget, height=chart_height)

                rs_hist_df = get_rs_history(ticker)
                if not rs_hist_df.empty and len(rs_hist_df) > 1:
                    rs_hist_df['date'] = pd.to_datetime(rs_hist_df['date'])
                    if 'industry_rs_score' in rs_hist_df.columns:
                        rs_hist_df['industry_rs_score'] = rs_hist_df['industry_rs_score'].replace(0, pd.NA)
                        melted_df = rs_hist_df.melt('date', value_vars=['rs_score', 'industry_rs_score'], var_name='Type', value_name='Score').dropna(subset=['Score'])
                        melted_df['Type'] = melted_df['Type'].map({'rs_score': '개별 RS 점수', 'industry_rs_score': '산업군 RS 점수'})
                        rs_chart = alt.Chart(melted_df).mark_line(strokeWidth=2).encode(
                            x=alt.X('date:T', title='날짜'), y=alt.Y('Score:Q', title='점수', scale=alt.Scale(domain=[1, 100])),
                            color=alt.Color('Type:N', title='지표', scale=alt.Scale(domain=['개별 RS 점수', '산업군 RS 점수'], range=['#64ffda', '#f59e0b']))
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

                st.markdown("#### 캔슬림 (CAN SLIM) 전략")
                canslim = [
                    {"name": "C (현재 실적): SMR 등급 A 또는 B", "pass": smr_val in ['A', 'B']},
                    {"name": "A (연간 실적): SMR 등급 A 또는 B", "pass": smr_val in ['A', 'B']},
                    {"name": "N (신제품/신고가): RS 점수 80 이상", "pass": rs_val >= 80},
                    {"name": "S (수요와 공급): 주도주 거래대금 필터 통과", "pass": adv_val >= min_adv_m * 100000000},
                    {"name": "L (주도주): 산업군 RS 점수 70 이상", "pass": ind_rs_val >= 70},
                    {"name": "I (기관 수급): AD 수급 등급 A 또는 B", "pass": ad_val in ['A', 'B']},
                ]
                for c in canslim:
                    st.markdown(f'<div class="check-box {"check-pass" if c["pass"] else "check-fail"}">{"✅" if c["pass"] else "❌"} {c["name"]}</div>', unsafe_allow_html=True)

            with t_fin:
                if naver_error:
                    st.error(f"🚨 {naver_error}")
                else:
                    st.caption("출처: 네이버 금융 (기업실적분석) 단위 일치")
                    
                    if not ann_fin.empty:
                        st.markdown("#### 📅 연간 실적 지표 (최근 4년)")
                        st.dataframe(ann_fin, use_container_width=True)
                    else:
                        st.info("연간 재무 분석 테이블 데이터를 구성할 수 없습니다.")

                    if not qtr_fin.empty:
                        st.markdown("#### 📊 분기별 실적 지표 (최근 6분기)")
                        st.dataframe(qtr_fin, use_container_width=True)
                    else:
                        st.info("분기별 재무 분석 테이블 데이터가 존재하지 않습니다.")

            with t_biz:
                st.markdown(f"""
                <div class="overview-panel">
                    <strong>[네이버 연동 기본 정보]</strong><br><br>
                    - 종목 마스터 코드: {ticker}<br>
                    - 크롤링 매칭 섹터: {info.get('industry', target.get('industry', '분석 중'))}<br>
                    - 데이터 소스 상태: <span style="color:#10b981;">정상 (Naver Engine Bypass)</span>
                </div>
                """, unsafe_allow_html=True)
                    
        else: st.info("👈 왼쪽 리스트에서 종목을 선택해 주세요.")
else:
    st.warning("데이터베이스가 비어있습니다. 먼저 `update_data.py`를 실행해서 데이터를 채우고 깃허브에 push 해주세요.")
