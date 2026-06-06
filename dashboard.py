# -*- coding: utf-8 -*-
import os
import sqlite3
import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from kr_financials import (
    DB_NAME,
    build_financial_display_table,
    ensure_ticker_financials,
    init_financials_table,
    load_quarterly_df,
)

GRADES = ["A", "B", "C", "D", "E"]

def get_data():
    if not os.path.exists(DB_NAME):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql("SELECT * FROM repo_results", conn)
        if "smr_grade" in df.columns:
            df["smr_grade"] = df["smr_grade"].astype(str)
        if "ad_grade" in df.columns:
            df["ad_grade"] = df["ad_grade"].astype(str)
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df

def get_rs_history(ticker):
    if not os.path.exists(DB_NAME):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        hist = pd.read_sql(
            "SELECT * FROM rs_history WHERE symbol = ? ORDER BY date ASC",
            conn,
            params=(ticker,),
        )
    except Exception:
        hist = pd.DataFrame()
    conn.close()
    return hist

@st.cache_data(ttl=86400)
def _market_by_ticker():
    if not os.path.exists(DB_NAME):
        return {}
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql("SELECT * FROM krx_tickers_cache", conn)
        t_col = "Code" if "Code" in df.columns else "Symbol"
        market_dict = df.set_index(df[t_col].astype(str).str.zfill(6))["Market"].to_dict()
    except Exception:
        market_dict = {}
    finally:
        conn.close()
    return market_dict

def tradingview_symbol(ticker):
    """한국 주식 TradingView 심볼 (KOSPI→KRX, KOSDAQ→KOSDAQ)."""
    code = str(ticker).strip().zfill(6)
    market = _market_by_ticker().get(code, "KOSPI")
    prefix = "KOSDAQ" if market == "KOSDAQ" else "KRX"
    return f"{prefix}:{code}"

def format_adv(val):
    try:
        val = float(val)
        if val >= 1e12:
            return f"{val/1e12:.2f}조 원"
        if val >= 1e8:
            return f"{val/1e8:.2f}억 원"
        return f"{val:,.0f}원"
    except Exception:
        return "0원"

def grade_filter_ui(label, session_key, default=None):
    """A~E 등급을 동그라미 버튼으로 노출·토글."""
    if default is None:
        default = ["A", "B", "C"]
    if session_key not in st.session_state:
        st.session_state[session_key] = list(default)
    st.caption(label)
    cols = st.columns(len(GRADES) + 1)
    for i, g in enumerate(GRADES):
        with cols[i]:
            sel = g in st.session_state[session_key]
            if st.button(f"{'●' if sel else '○'} {g}", key=f"{session_key}_{g}", use_container_width=True):
                if sel:
                    st.session_state[session_key].remove(g)
                else:
                    st.session_state[session_key].append(g)
                st.rerun()
    with cols[-1]:
        all_on = len(st.session_state[session_key]) == len(GRADES)
        if st.button(f"{'●' if all_on else '○'} 전체", key=f"{session_key}_all", use_container_width=True):
            st.session_state[session_key] = [] if all_on else list(GRADES)
            st.rerun()
    return st.session_state[session_key]

def sector_filter_ui(all_sectors):
    """섹터(업종) 멀티 선택 - 접기/펼치기 및 전체선택 기능 적용"""
    if "sector_sel" not in st.session_state:
        st.session_state.sector_sel = list(all_sectors)
        
    # expander를 사용하여 기본적으로 목록을 숨겨둠
    with st.expander("📊 섹터(업종) 필터", expanded=False):
        is_all = len(st.session_state.sector_sel) == len(all_sectors)
        
        # 전체 선택 / 해제 버튼
        if st.button(f"{'●' if is_all else '○'} 전체 선택 / 해제", key="sector_all_btn", use_container_width=True):
            st.session_state.sector_sel = [] if is_all else list(all_sectors)
            st.rerun()
            
        cols = st.columns(2)
        for idx, sec in enumerate(all_sectors):
            with cols[idx % 2]:
                sel = sec in st.session_state.sector_sel
                label = (str(sec)[:14] + "…") if len(str(sec)) > 14 else str(sec)
                if st.button(f"{'●' if sel else '○'} {label}", key=f"sec_{sec}", use_container_width=True):
                    if sel:
                        st.session_state.sector_sel.remove(sec)
                    else:
                        st.session_state.sector_sel.append(sec)
                    st.rerun()
                    
    return st.session_state.sector_sel

def render_tradingview_chart(ticker, height=520):
    tv_sym = tradingview_symbol(ticker)
    safe_id = f"tradingview_{str(ticker).replace('.', '_')}"
    
    html = f"""
    <div class="tradingview-widget-container" style="height:{height}px;width:100%;">
      <div id="{safe_id}" style="height:100%;width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "{tv_sym}",
        "interval": "D",
        "timezone": "Asia/Seoul",
        "theme": "dark",
        "style": "1",
        "locale": "kr",
        "enable_publishing": false,
        "allow_symbol_change": true, 
        "backgroundColor": "#161C27",
        "gridColor": "#2A3143",
        "hide_top_toolbar": false,
        "save_image": false,
        "container_id": "{safe_id}"
      }});
      </script>
    </div>
    """
    components.html(html, height=height)

def get_financial_table(ticker):
    ensure_ticker_financials(ticker, years_back=5)
    conn = sqlite3.connect(DB_NAME)
    init_financials_table(conn)
    df_q = load_quarterly_df(conn, ticker)
    conn.close()
    return build_financial_display_table(df_q, max_quarters=20)

st.set_page_config(layout="wide", page_title="한국 주도주 수급 종합 터미널")

st.markdown(
    """
<style>
    .stApp { background-color: #161C27 !important; }
    .block-container p, .block-container span, .block-container h1, .block-container h2,
    .block-container h3, .block-container h4, .block-container label { color: #FFFFFF !important; }
    [data-testid="stSidebar"] { background-color: #F8F9FA !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label {
        color: #1E293B !important; font-size: 13px;
    }
    .stButton > button { background-color: #FFFFFF !important; border: 1px solid #CBD5E1 !important; }
    .overview-panel { background: #2A3143; padding: 1.2rem; border-radius: 8px; color: #FFFFFF !important; }
    .check-box { padding: 10px; margin-bottom: 5px; border-radius: 5px; background-color: #1E293B; color: #D1D5DB !important; }
    .check-pass { border-left: 5px solid #10b981; }
    .check-fail { border-left: 5px solid #ef4444; }
</style>
""",
    unsafe_allow_html=True,
)

df = get_data()

if not df.empty:
    all_sectors = sorted(df["industry"].dropna().unique().tolist())
    
    with st.sidebar:
        is_mobile = st.toggle(" 📱  모바일 화면 최적화", value=False)
        st.header("필터링 기준 설정")
        min_p = st.number_input("최소 주가 (원)", value=1000.0)
        min_adv_m = st.number_input("최소 거래대금 (억원)", value=10.0)
        rs_m = st.slider("최소 가중 RS 점수", 1, 99, 80)
        ind_rs_m = st.slider("최소 세부 섹터 RS 점수", 1, 99, 70)
        sector_sel = sector_filter_ui(all_sectors)
        smr_sel = grade_filter_ui("SMR 등급", "smr_sel", default=["A", "B", "C"])
        ad_sel = grade_filter_ui("AD 수급 등급", "ad_sel", default=["A", "B", "C", "D", "E"])

    mask = (
        (df["price"] >= min_p)
        & (df["rs_score"] >= rs_m)
        & (df["adv_50"] >= min_adv_m * 100000000)
        & (df["industry_rs_score"] >= ind_rs_m)
        & (df["smr_grade"].isin(smr_sel))
        & (df["ad_grade"].isin(ad_sel))
        & (df["industry"].isin(sector_sel))
    )
    
    f_df = df[mask].sort_values("rs_score", ascending=False).copy()
    display_df = f_df.copy()
    display_df["adv_50"] = display_df["adv_50"].apply(format_adv)
    display_df = display_df[
        [
            "symbol", "name", "price", "rs_score", "industry_rs_score",
            "smr_grade", "ad_grade", "adv_50", "industry",
        ]
    ]
    display_df.rename(
        columns={
            "symbol": "종목코드",
            "name": "종목명",
            "price": "현재가",
            "adv_50": "50일평균대금",
            "rs_score": "가중RS",
            "industry_rs_score": "섹터RS",
            "smr_grade": "SMR",
            "ad_grade": "AD등급",
            "industry": "섹터",
        },
        inplace=True,
    )

    if is_mobile:
        st.subheader(f"주도주 스크리닝 결과 ({len(display_df)})")
        sel_row = st.dataframe(
            display_df, hide_index=True, on_select="rerun",
            selection_mode="single-row", height=300, use_container_width=True,
        )
        detail_container = st.container()
    else:
        col_l, col_r = st.columns([4, 5])
        with col_l:
            st.subheader(f"주도주 스크리닝 결과 ({len(display_df)})")
            sel_row = st.dataframe(
                display_df, hide_index=True, on_select="rerun",
                selection_mode="single-row", height=750, use_container_width=True,
            )
        detail_container = col_r

    with detail_container:
        if len(sel_row.selection.rows) > 0:
            target = f_df.iloc[sel_row.selection.rows[0]]
            ticker = str(target["symbol"]).zfill(6)
            st.markdown(
                f"## {target['name']} ({ticker}) "
                f"<span style='font-size:16px;color:#9CA3AF;'>{target['industry']}</span>",
                unsafe_allow_html=True,
            )
            st.caption(f"TradingView: {tradingview_symbol(ticker)}")

            t_chart, t_check, t_fin = st.tabs([" 📊  TradingView 차트", " 🛡 ️ 캔슬림 검증", " 🧾  재무 (5년 분기)"])

            with t_chart:
                render_tradingview_chart(ticker)
                st.markdown("#### RS 점수 추이")
                rs_hist_df = get_rs_history(ticker)
                if not rs_hist_df.empty and len(rs_hist_df) > 1:
                    rs_hist_df["date"] = pd.to_datetime(rs_hist_df["date"])
                    rs_chart = (
                        alt.Chart(rs_hist_df)
                        .mark_line(color="#64ffda", strokeWidth=2)
                        .encode(
                            x=alt.X("date:T", title="연산일자"),
                            y=alt.Y("rs_score:Q", title="가중 RS", scale=alt.Scale(domain=[1, 100])),
                        )
                        .properties(height=180)
                    )
                    st.altair_chart(rs_chart, use_container_width=True)
                else:
                    st.info("RS 히스토리가 없습니다. `kr_update_data.py` 실행 후 누적됩니다.")

            with t_check:
                st.markdown("#### 수급·모멘텀 진단")
                st.metric("SMR 등급", f"{target['smr_grade']}")
                st.metric("AD 수급 등급", f"{target['ad_grade']}")
                st.metric("개별 RS", f"{int(target['rs_score'])} (상위 약 {100 - int(target['rs_score'])}%)")
                st.metric("섹터 RS", f"{int(target['industry_rs_score'])}")

                canslim = [
                    {"name": "N: 가중 RS 80 이상", "pass": int(target["rs_score"]) >= 80},
                    {"name": "L: 섹터 RS 70 이상", "pass": int(target["industry_rs_score"]) >= 70},
                    {"name": "I: AD 등급 A 또는 B", "pass": target["ad_grade"] in ["A", "B"]},
                    {"name": "S: SMR 등급 A 또는 B", "pass": target["smr_grade"] in ["A", "B"]},
                ]
                for c in canslim:
                    cls = "check-pass" if c["pass"] else "check-fail"
                    icon = " ✅ " if c["pass"] else " ❌ "
                    st.markdown(
                        f'<div class="check-box {cls}">{icon} {c["name"]}</div>',
                        unsafe_allow_html=True,
                    )

            with t_fin:
                with st.spinner("DART 분기 재무 불러오는 중… (최초 1회 수 초 소요)"):
                    fin_table = get_financial_table(ticker)

                if fin_table.empty:
                    st.info(
                        "재무 데이터가 없습니다. DART API 키를 설정한 뒤 "
                        "`kr_update_data.py`를 실행하거나 잠시 후 다시 시도해 주세요."
                    )
                else:
                    st.markdown("#### 최근 5년 분기 재무 (단위: 백만원)")

                    # 백만원 단위로 렌더링하도록 포맷팅 로직 수정
                    def fmt_money(x, is_million=True):
                        if pd.isna(x):
                            return "-"
                        if is_million:
                            return f"{x / 1000000:,.0f}"
                        else:
                            return f"{x:,.0f}"

                    def fmt_pct(x):
                        if pd.isna(x):
                            return "-"
                        return f"{x:+.1f}%"

                    show = fin_table.copy()
                    
                    # 데이터프레임 헤더명 백만원으로 리네임
                    show.rename(columns={
                        "매출액(원)": "매출액(백만원)",
                        "영업이익(원)": "영업이익(백만원)",
                        "당기순이익(원)": "당기순이익(백만원)"
                    }, inplace=True)
                    
                    # 매출, 영업이익, 순이익은 백만원으로 치환 (100만 나누기)
                    for col in ["매출액(백만원)", "영업이익(백만원)", "당기순이익(백만원)"]:
                        if col in show.columns:
                            show[col] = show[col].apply(lambda x: fmt_money(x, is_million=True))
                    
                    # 1주당 가치인 EPS는 원본(원 단위) 유지
                    if "EPS(원)" in show.columns:
                        show["EPS(원)"] = show["EPS(원)"].apply(lambda x: fmt_money(x, is_million=False))

                    # 성장률 퍼센트 포맷팅
                    for col in ["매출 YoY(%)", "영업이익 YoY(%)", "순이익 YoY(%)", "EPS YoY(%)"]:
                        if col in show.columns:
                            show[col] = show[col].apply(fmt_pct)
                            
                    st.dataframe(show, use_container_width=True, hide_index=True)
        else:
            st.info(" 👈  스크리닝 리스트에서 분석할 종목을 선택해 주세요.")
else:
    st.warning(
        "데이터베이스가 비어 있습니다. 터미널에서 `python kr_update_data.py`를 실행해 주세요."
    )
