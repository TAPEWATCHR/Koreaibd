# -*- coding: utf-8 -*-
import os
import sqlite3
import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import FinanceDataReader as fdr
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
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

# --- 📈 시장 지수 수급 데이터 로드 함수 추가 ---
def get_market_distribution_data():
    if not os.path.exists(DB_NAME):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        df_market = pd.read_sql("SELECT * FROM market_index_daily", conn)
    except Exception:
        df_market = pd.DataFrame()
    conn.close()
    if not df_market.empty and 'Date' in df_market.columns:
        df_market['Date'] = pd.to_datetime(df_market['Date'])
        df_market = df_market.sort_values('Date').reset_index(drop=True)
    return df_market

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
    if "sector_sel" not in st.session_state:
        st.session_state.sector_sel = list(all_sectors)
        
    with st.expander("📊 섹터(업종) 필터", expanded=False):
        is_all = len(st.session_state.sector_sel) == len(all_sectors)
        
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

def get_financial_table(ticker):
    ensure_ticker_financials(ticker, years_back=5)
    conn = sqlite3.connect(DB_NAME)
    init_financials_table(conn)
    df_q = load_quarterly_df(conn, ticker)
    conn.close()
    return build_financial_display_table(df_q, max_quarters=20)

def render_custom_plotly_chart(ticker, timeframe):
    end_date = datetime.today()
    start_date = end_date - timedelta(days=365 * 2) 
    
    try:
        price_df = fdr.DataReader(ticker, start=start_date, end=end_date)
    except Exception as e:
        st.error(f"차트용 데이터를 가져오지 못했습니다: {e}")
        return

    if price_df.empty:
        st.warning("차트 데이터가 비어 있습니다.")
        return

    if "주간" in timeframe:
        df_resampled = price_df.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        
        df_resampled['Prev_Close'] = df_resampled['Close'].shift(1)
        df_resampled['Chg_Amt'] = df_resampled['Close'] - df_resampled['Prev_Close']
        df_resampled['Chg_Pct'] = (df_resampled['Chg_Amt'] / df_resampled['Prev_Close']) * 100
        
        df_resampled['MA10'] = df_resampled['Close'].rolling(window=10).mean()
        df_resampled['MA40'] = df_resampled['Close'].rolling(window=40).mean()
        chart_df = df_resampled
    else:
        price_df['Prev_Close'] = price_df['Close'].shift(1)
        price_df['Chg_Amt'] = price_df['Close'] - price_df['Prev_Close']
        price_df['Chg_Pct'] = (price_df['Chg_Amt'] / price_df['Prev_Close']) * 100

        price_df['MA10'] = price_df['Close'].rolling(window=10).mean()
        price_df['MA20'] = price_df['Close'].rolling(window=20).mean()
        price_df['MA50'] = price_df['Close'].rolling(window=50).mean()
        price_df['MA200'] = price_df['Close'].rolling(window=200).mean()
        chart_df = price_df

    one_year_ago = end_date - timedelta(days=365)
    chart_df = chart_df[chart_df.index >= one_year_ago]

    if chart_df.empty:
        st.warning("최근 1년 내 유효한 차트 데이터가 부족합니다.")
        return

    latest_close = chart_df['Close'].iloc[-1]
    period_high = chart_df['High'].max()
    period_low = chart_df['Low'].min()
    drop_from_high = ((latest_close - period_high) / period_high) * 100
    rise_from_low = ((latest_close - period_low) / period_low) * 100

    c1, c2, c3 = st.columns(3)
    c1.metric("현재 차트 종가", f"{int(latest_close):,} 원")
    c2.metric("최근 1년 고점 대비", f"{drop_from_high:.2f} %", delta=f"최고: {int(period_high):,}", delta_color="inverse")
    c3.metric("최근 1년 저점 대비", f"{rise_from_low:.2f} %", delta=f"최저: {int(period_low):,}")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.8, 0.2])

    color_up_fill = '#000000'
    color_up_line = '#D1D5DB'
    color_down = '#FF3B30'    

    hover_text = [
        f"전일대비: {amt:+,.0f}원 ({pct:+.2f}%)<br>거래량: {vol:,.0f}주" 
        for amt, pct, vol in zip(chart_df['Chg_Amt'], chart_df['Chg_Pct'], chart_df['Volume'])
    ]

    fig.add_trace(go.Candlestick(
        x=chart_df.index,
        open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'],
        increasing_line_color=color_up_line, increasing_fillcolor=color_up_fill,
        decreasing_line_color=color_down, decreasing_fillcolor=color_down,
        name="가격",
        text=hover_text,
        hovertemplate="<b>%{x}</b><br>시가: %{open:,.0f}원<br>고가: %{high:,.0f}원<br>저가: %{low:,.0f}원<br>종가: %{close:,.0f}원<br>%{text}<extra></extra>"
    ), row=1, col=1)

    if "주간" in timeframe:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA10'], name="10주선", line=dict(color='#38BDF8', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA40'], name="40주선", line=dict(color='#A855F7', width=1.5)), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA10'], name="10일선", line=dict(color='#38BDF8', width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'], name="20일선", line=dict(color='#3B82F6', width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA50'], name="50일선", line=dict(color='#1E3A8A', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA200'], name="200일선", line=dict(color='#A855F7', width=1.5)), row=1, col=1)

    v_colors = [color_up_line if c >= o else color_down for o, c in zip(chart_df['Open'], chart_df['Close'])]
    fig.add_trace(go.Bar(
        x=chart_df.index,
        y=chart_df['Volume'], marker_color=v_colors, name="거래량",
        hovertemplate="<b>%{x}</b><br>거래량: %{y:,.0f}주<extra></extra>"
    ), row=2, col=1)

    fig.update_layout(
        height=550,
        paper_bgcolor="#161C27",
        plot_bgcolor="#161C27",
        xaxis_rangeslider_visible=False,
        hovermode='x unified',
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color="#FFFFFF")),
        margin=dict(l=40, r=40, t=10, b=10)
    )
    
    fig.update_xaxes(
        gridcolor="#2A3143", 
        tickfont=dict(color="#FFFFFF"),
        rangebreaks=[dict(bounds=["sat", "mon"])] 
    )
    fig.update_yaxes(tickformat=",d", gridcolor="#2A3143", tickfont=dict(color="#FFFFFF"), row=1, col=1)
    fig.update_yaxes(tickformat=",d", gridcolor="#2A3143", tickfont=dict(color="#FFFFFF"), row=2, col=1)

def run_dashboard():
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
            
            # --- 📊 [사이드바] 시장 수급 상태판 추가 ---
            st.divider()
            st.header("📊 시장 수급 상태 (오닐 IBD)")
            df_market = get_market_distribution_data()
            if not df_market.empty:
                recent_25 = df_market.tail(25)
                total_dist_days = int(recent_25['IsDistribution'].sum())
                total_acc_days = int(recent_25['IsAccumulation'].sum())
                
                if total_dist_days >= 5:
                    risk_text = "🚨 위험 (고점경계 / 현금확대)"
                    risk_color = "red"
                elif total_dist_days >= 3:
                    risk_text = "⚠️ 경계 (매수신중 / 보유점검)"
                    risk_color = "orange"
                else:
                    risk_text = "✅ 정상 (상승추세 유지)"
                    risk_color = "green"
                    
                st.markdown(f"**시장 상태:** :{risk_color}[{risk_text}]")
                st.metric("최근 25거래일 분산일(D-Day)", f"{total_dist_days}회", help="4~5회 이상 누적 시 현금 비중 확대 고려")
                st.metric("최근 25거래일 매집일(A-Day)", f"{total_acc_days}회")
            else:
                st.warning("시장 수급 데이터가 없습니다. `kr_update_data.py`를 실행해주세요.")
            st.divider()
            # ----------------------------------------

            st.header("필터링 기준 설정")
            min_p = st.number_input("최소 주가 (원)", value=1000.0)
            min_adv_m = st.number_input("최소 거래대금 (억원)", value=10.0)
            rs_m = st.slider("최소 가중 RS 점수", 1, 99, 80)
            ind_rs_m = st.slider("최소 세부 섹터 RS 점수", 1, 99, 70)
            sector_sel = sector_filter_ui(all_sectors)
            smr_sel = grade_filter_ui("SMR 등급", "smr_sel", default=["A", "B", "C"])
            ad_sel = grade_filter_ui("AD 수급 등급", "ad_sel", default=["A", "B", "C", "D", "E"])

            st.markdown("---")
            st.subheader("🛡️ 하방 지지 & 돌파 대기")
            use_ma50_filter = st.checkbox("50일 이동평균선 상회 (하방 지지)", value=False)
            use_high52w_filter = st.checkbox("52주 신고가 대비 -15% 이내 (돌파 임박)", value=False)

        mask = (
            (df["price"] >= min_p)
            & (df["rs_score"] >= rs_m)
            & (df["adv_50"] >= min_adv_m * 100000000)
            & (df["industry_rs_score"] >= ind_rs_m)
            & (df["smr_grade"].isin(smr_sel))
            & (df["ad_grade"].isin(ad_sel))
            & (df["industry"].isin(sector_sel))
        )
        
        if use_ma50_filter and "ma_50" in df.columns:
            mask = mask & (df["price"] >= df["ma_50"])
        if use_high52w_filter and "high_52w" in df.columns:
            mask = mask & (df["price"] >= df["high_52w"] * 0.85)

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

                t_chart, t_check, t_fin = st.tabs([" 📊  인터랙티브 차트", " 🛡 ️ 캔슬림 검증", " 🧾  재무 (5년 분기)"])

                with t_chart:
                    tf_choice = st.radio("차트 주기 변환", ["일간 (Daily)", "주간 (Weekly)"], horizontal=True, key=f"tf_{ticker}")
                    render_custom_plotly_chart(ticker, tf_choice)
                    
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
                        
                        show.rename(columns={
                            "매출액(원)": "매출액(백만원)",
                            "영업이익(원)": "영업이익(백만원)",
                            "당기순이익(원)": "당기순이익(백만원)"
                        }, inplace=True)
                        
                        for col in ["매출액(백만원)", "영업이익(백만원)", "당기순이익(백만원)"]:
                            if col in show.columns:
                                show[col] = show[col].apply(lambda x: fmt_money(x, is_million=True))
                        
                        if "EPS(원)" in show.columns:
                            show["EPS(원)"] = show["EPS(원)"].apply(lambda x: fmt_money(x, is_million=False))

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

if __name__ == "__main__":
    run_dashboard()
