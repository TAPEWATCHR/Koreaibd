# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import sqlite3
import requests
import streamlit.components.v1 as components
import os
import altair as alt
from deep_translator import GoogleTranslator
from streamlit_gsheets import GSheetsConnection

# --- 🔑 API 키 로드 방식을 Streamlit Secrets와 환경 변수 모두 지원하도록 고도화 ---
FMP_API_KEY = ""
if "FMP_API_KEY" in st.secrets:
    FMP_API_KEY = st.secrets["FMP_API_KEY"]
elif os.environ.get("FMP_API_KEY"):
    FMP_API_KEY = os.environ.get("FMP_API_KEY")
FMP_API_KEY = FMP_API_KEY.strip()

# --- 🔤 [국내 주식 최적화] 트레이딩뷰와 FMP의 한국 주식 심볼 포맷 변환 함수 ---
def clean_tv_symbol(symbol):
    """트레이딩뷰 위젯용: 한국 주식은 반드시 KRX:6자리코드 형태여야 함 (예: 005930.KS -> KRX:005930)"""
    if not symbol: return ""
    raw = str(symbol).strip().upper()
    # 마침표(.)나 하이픈(-) 뒤의 시장 기호 제거하고 오직 6자리 종목코드만 추출
    base = raw.split('.')[0].split('-')[0]
    if base.isdigit() and len(base) == 6:
        return f"KRX:{base}"
    return raw

def clean_fmp_symbol(symbol):
    """FMP API 요청용: 한국 주식은 마침표 형태를 사용함 (예: 005930-KS -> 005930.KS)"""
    if not symbol: return ""
    raw = str(symbol).strip().upper()
    return raw.replace('-', '.')

def init_db():
    conn = sqlite3.connect('ibd_system.db')
    conn.execute("CREATE TABLE IF NOT EXISTS favorites (symbol TEXT PRIMARY KEY)")
    conn.close()

def get_data():
    if not os.path.exists('ibd_system.db'): return pd.DataFrame()
    conn = sqlite3.connect('ibd_system.db')
    df = pd.read_sql("SELECT * FROM repo_results", conn)
    conn.close()
    return df

def get_rs_history(ticker):
    if not os.path.exists('ibd_system.db'): return pd.DataFrame()
    conn = sqlite3.connect('ibd_system.db')
    try:
        hist = pd.read_sql("SELECT * FROM rs_history WHERE symbol = ? ORDER BY date ASC", conn, params=(ticker,))
    except: 
        hist = pd.DataFrame()
    conn.close()
    return hist

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

# --- 🧾 FMP 한국 주식 심볼 매칭 및 API 에러 메시지 반환 추적 로직 ---
@st.cache_data(ttl=3600)
def get_fin_data(ticker):
    if not FMP_API_KEY: 
        return [], [], [], {}, "FMP_API_KEY를 탐지할 수 없습니다. Secrets 설정을 확인하세요."
    
    # FMP가 인식할 수 있는 규격(005930.KS 형태)으로 심볼 정제
    fmp_ticker = clean_fmp_symbol(ticker)
    
    try:
        url_is_ann = f"https://financialmodelingprep.com/stable/income-statement?symbol={fmp_ticker}&period=annual&limit=5&apikey={FMP_API_KEY}"
        res_is = requests.get(url_is_ann)
        is_ann = res_is.json()
        
        # FMP API가 에러 메시지를 반환한 경우 처리
        if isinstance(is_ann, dict) and ("Error Message" in is_ann or "error" in is_ann):
            msg = is_ann.get("Error Message", is_ann.get("error", "인증 실패 또는 플랜 제한 오류"))
            return [], [], [], {}, f"FMP API 에러: {msg}"
        
        url_bs_ann = f"https://financialmodelingprep.com/stable/balance-sheet-statement?symbol={fmp_ticker}&period=annual&limit=5&apikey={FMP_API_KEY}"
        bs_ann = requests.get(url_bs_ann).json()
        
        url_is_qtr = f"https://financialmodelingprep.com/stable/income-statement?symbol={fmp_ticker}&period=quarter&limit=12&apikey={FMP_API_KEY}"
        is_qtr = requests.get(url_is_qtr).json()
        
        url_prof = f"https://financialmodelingprep.com/stable/profile?symbol={fmp_ticker}&apikey={FMP_API_KEY}"
        p_res = requests.get(url_prof).json()
        info = p_res[0] if p_res and isinstance(p_res, list) else {}
        
        return is_ann, bs_ann, is_qtr, info, None
    except Exception as e: 
        return [], [], [], {}, f"API 요청 중 네트워크 예외 발생: {str(e)}"

def format_currency(val):
    try:
        val = float(val)
        if pd.isna(val) or val == 0: return "0"
        return f"{int(val / 1000):,}"
    except: return "0"

def calc_growth(current, previous):
    try:
        current, previous = float(current), float(previous)
        if pd.isna(current) or pd.isna(previous) or previous == 0: return None
        return ((current - previous) / abs(previous)) * 100
    except: return None

def format_growth(val):
    if pd.isna(val) or val is None: return "-"
    return f"{val:.1f}%"

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

if not FMP_API_KEY:
    st.error("🚨 FMP_API_KEY가 탐지되지 않았습니다. .streamlit/secrets.toml 설정 혹은 환경 변수를 등록해 주세요.")

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

    # 거래대금 단위 환산 반영 (억 원 단위를 원 단위로 매칭할 경우 등의 로직 유지)
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
        display_df.rename(columns={'symbol': '종목', 'price': '가격', 'adv_50': '50일 평균 거래대', 'rs_score': 'RS점수', 'industry_rs_score': '산업군RS점수', 'smr_grade': 'SMR등급', 'ad_grade': 'AD등급', 'industry': '산업군명'}, inplace=True)

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
            
            is_ann_raw, bs_ann_raw, is_qtr_raw, info, fmp_error = get_fin_data(ticker)
            t_chart, t_check, t_fin, t_biz = st.tabs(["📊 차트", "🛡️ 체크리스트", "🧾 재무제표", "🏢 기업 개요"])
            
            with t_chart:
                chart_height = 350 if is_mobile else 500
                # 💡 [핵심 수정] 한국 주식 규격에 맞게 트레이딩뷰 위젯 심볼 자동 정제 (KRX:6자리코드)
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

                st.markdown("#### 마크 미너비니 (Minervini VCP) 전략")
                minervini = [
                    {"name": "최소 주가 필터 통과", "pass": price_val >= min_p},
                    {"name": "주도주 모멘텀: RS 점수 70 이상", "pass": rs_val >= 70},
                    {"name": "펀더멘탈: SMR 등급 A 또는 B", "pass": smr_val in ['A', 'B']},
                    {"name": "매집 흔적: AD 수급 등급 A, B, C", "pass": ad_val in ['A', 'B', 'C']},
                    {"name": "유동성: 거래대금 조건 충족", "pass": adv_val >= min_adv_m * 100000000}
                ]
                for c in minervini:
                    st.markdown(f'<div class="check-box {"check-pass" if c["pass"] else "check-fail"}">{"✅" if c["pass"] else "❌"} {c["name"]}</div>', unsafe_allow_html=True)

            with t_fin:
                if fmp_error:
                    st.error(f"🚨 {fmp_error}")
                    
                st.caption("단위: 보고 통화 기준 (천 단위) / 성장률: %")
                
                def safe_parse(data_list, keys, required_key):
                    if not isinstance(data_list, list) or len(data_list) == 0: return pd.DataFrame()
                    if required_key not in data_list[0]: return pd.DataFrame()
                    parsed = [{k: item.get(k) if item.get(k) is not None else 0 for k in keys} for item in data_list]
                    return pd.DataFrame(parsed)

                req_is_ann = ['calendarYear', 'revenue', 'operatingIncome', 'netIncome', 'ebitda']
                req_bs_ann = ['calendarYear', 'totalAssets', 'totalLiabilities', 'totalStockholdersEquity']
                
                is_ann_df = safe_parse(is_ann_raw, req_is_ann, 'calendarYear')
                bs_ann_df = safe_parse(bs_ann_raw, req_bs_ann, 'calendarYear')

                if not is_ann_df.empty and not bs_ann_df.empty:
                    st.markdown("#### 📅 연간 재무 및 성장률 (최근 5년)")
                    ann_df = is_ann_df.merge(bs_ann_df, on='calendarYear', how='left')
                    for col, growth_col in zip(['revenue', 'operatingIncome', 'netIncome'], ['매출성장률', '영업이익성장률', '순이익성장률']):
                        ann_df[growth_col] = ann_df[col].shift(-1)
                        ann_df[growth_col] = ann_df.apply(lambda row: calc_growth(row[col], row[growth_col]), axis=1)
                    
                    ann_df = ann_df.rename(columns={'calendarYear':'연도', 'revenue':'매출액', 'operatingIncome':'영업이익', 'netIncome':'순이익', 'ebitda':'EBITDA', 'totalAssets':'총자산', 'totalLiabilities':'총부채', 'totalStockholdersEquity':'자본'})
                    for col in ['매출액', '영업이익', '순이익', 'EBITDA', '총자산', '총부채', '자본']: ann_df[col] = ann_df[col].apply(format_currency)
                    for col in ['매출성장률', '영업이익성장률', '순이익성장률']: ann_df[col] = ann_df[col].apply(format_growth)
                    st.dataframe(ann_df[['연도', '매출액', '매출성장률', '영업이익', '영업이익성장률', '순이익', '순이익성장률', 'EBITDA', '총자산', '총부채', '자본']].head(5), hide_index=True, use_container_width=True)
                else:
                    st.info("연간 재무제표 원본 데이터를 파싱할 수 없거나 제공되지 않는 종목입니다.")

                req_is_qtr = ['date', 'period', 'revenue', 'operatingIncome', 'netIncome', 'eps']
                qtr_df = safe_parse(is_qtr_raw, req_is_qtr, 'date')

                if not qtr_df.empty:
                    st.markdown("#### 📊 분기별 재무 및 성장률 (최근 3년)")
                    for col, growth_col in zip(['revenue', 'operatingIncome', 'netIncome'], ['매출성장률(YoY)', '영업이익성장률(YoY)', '순이익성장률(YoY)']):
                        qtr_df[growth_col] = qtr_df[col].shift(-4)
                        qtr_df[growth_col] = qtr_df.apply(lambda row: calc_growth(row[col], row[growth_col]), axis=1)
                    
                    qtr_df = qtr_df.rename(columns={'date':'발표일', 'period':'분기', 'revenue':'매출액', 'operatingIncome':'영업이익', 'netIncome':'순이익', 'eps':'EPS'})
                    for col in ['매출액', '영업이익', '순이익']: qtr_df[col] = qtr_df[col].apply(format_currency)
                    for col in ['매출성장률(YoY)', '영업이익성장률(YoY)', '순이익성장률(YoY)']: qtr_df[col] = qtr_df[col].apply(format_growth)
                    st.dataframe(qtr_df[['발표일', '분기', '매출액', '매출성장률(YoY)', '영업이익', '영업이익성장률(YoY)', '순이익', '순이익성장률(YoY)', 'EPS']].head(12), hide_index=True, use_container_width=True)
                else:
                    st.info("분기별 재무제표 원본 데이터를 파싱할 수 없거나 제공되지 않는 종목입니다.")

            with t_biz:
                desc_en = info.get("description", "")
                if desc_en:
                    st.markdown(f'<div class="overview-panel" style="margin-bottom: 20px;"><strong>[원문 개요]</strong><br><br>{desc_en}</div>', unsafe_allow_html=True)
                    try:
                        with st.spinner("개요 정보 번역 중..."):
                            desc_ko = GoogleTranslator(source='en', target='ko').translate(desc_en)
                        st.markdown(f'<div class="overview-panel"><strong>[🇰🇷 한글 번역]</strong><br><br>{desc_ko}</div>', unsafe_allow_html=True)
                    except:
                        pass
                else:
                    st.info("해당 기업의 개요 정보가 제공되지 않습니다.")
                    
        else: st.info("👈 왼쪽 리스트에서 종목을 선택해 주세요.")
else:
    st.warning("데이터베이스가 비어있습니다. 먼저 `update_data.py`를 실행해주세요.")
