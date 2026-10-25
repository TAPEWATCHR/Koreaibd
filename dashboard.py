# -*- coding: utf-8 -*-
import os
import sqlite3
import datetime
import pandas as pd
import streamlit as st
from kr_financials import (
    DB_NAME,
    load_quarterly_df,
    build_financial_display_table,
    ensure_ticker_financials,
)

st.set_page_config(
    page_title="한국형 IBD CAN SLIM 스크리너",
    page_icon="📈",
    layout="wide"
)

@st.cache_data(ttl=600)
def load_repo_results():
    if not os.path.exists(DB_NAME):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql("SELECT * FROM repo_results", conn)
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df

st.title("📈 한국형 IBD (CAN SLIM) 종목 스크리너")
st.caption("투트랙 SMR + 65일 CLV 수급 + 중기 RS 가중치 및 하방 지지 조건 반영")

df = load_repo_results()

if df.empty:
    st.error("데이터베이스(repo_results)가 비어있거나 존재하지 않습니다. 먼저 `kr_update_data.py`를 실행하세요.")
    st.stop()

# --- 사이드바 필터 설정 ---
st.sidebar.header("🔍 스크리닝 조건 설정")

min_rs = st.sidebar.slider("최소 RS 점수 (1~99)", 1, 99, 80)
smr_filter = st.sidebar.multiselect("SMR 등급 선택", ["A", "B", "C", "D", "E"], default=["A", "B"])
ad_filter = st.sidebar.multiselect("AD (수급) 등급 선택", ["A", "B", "C", "D", "E"], default=["A", "B"])

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ 하방 지지 & 돌파 대기 필터")
use_ma50_filter = st.sidebar.checkbox("50일 이동평균선 상회 (하방 지지)", value=True)
use_high52w_filter = st.sidebar.checkbox("52주 신고가 대비 -15% 이내 (돌파 임박)", value=False)

# --- 필터링 로직 ---
filtered_df = df[
    (df["rs_score"] >= min_rs) &
    (df["smr_grade"].isin(smr_filter)) &
    (df["ad_grade"].isin(ad_filter))
].copy()

if use_ma50_filter and "ma_50" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["price"] >= filtered_df["ma_50"]]

if use_high52w_filter and "high_52w" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["price"] >= filtered_df["high_52w"] * 0.85]

# 거래대금 단위 환산 (억원)
if "adv_50" in filtered_df.columns:
    filtered_df["adv_50_eok"] = (filtered_df["adv_50"] / 1e8).round(1)

# --- 메인 대시보드 화면 ---
col1, col2, col3 = st.columns(3)
col1.metric("전체 종목 수", f"{len(df)}개")
col2.metric("조건 만족 종목 수", f"{len(filtered_df)}개")
col3.metric("최소 RS 기준", f"{min_rs}점 이상")

st.markdown("---")
st.subheader("📋 스크리닝 결과 리스트")

display_cols = ["symbol", "name", "price", "rs_score", "industry_rs_score", "smr_grade", "ad_grade", "adv_50_eok", "industry"]
display_names = {
    "symbol": "종목코드",
    "name": "종목명",
    "price": "현재가(원)",
    "rs_score": "RS 점수",
    "industry_rs_score": "업종 RS",
    "smr_grade": "SMR",
    "ad_grade": "AD(수급)",
    "adv_50_eok": "50일 평균거래대금(억)",
    "industry": "업종"
}

available_cols = [c for c in display_cols if c in filtered_df.columns]
show_df = filtered_df[available_cols].rename(columns=display_names)

st.dataframe(
    show_df.sort_values(by="RS 점수", ascending=False),
    use_container_width=True,
    hide_index=True
)

# --- 종목 세부 재무 분석 ---
st.markdown("---")
st.subheader("🔎 종목 상세 분석 (DART 분기 재무)")

selected_symbol = st.selectbox(
    "상세 재무를 확인할 종목을 선택하세요",
    options=filtered_df["symbol"].tolist(),
    format_func=lambda x: f"{x} - {filtered_df[filtered_df['symbol']==x]['name'].values[0]}" if not filtered_df[filtered_df['symbol']==x].empty else x
)

if selected_symbol:
    with st.spinner("DART 재무제표 로딩 중..."):
        ensure_ticker_financials(selected_symbol)
        conn = sqlite3.connect(DB_NAME)
        df_q = load_quarterly_df(conn, selected_symbol)
        conn.close()

        df_display = build_financial_display_table(df_q)

        if not df_display.empty:
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.info("해당 종목의 분기 재무제표 데이터가 아직 수집되지 않았습니다.")
