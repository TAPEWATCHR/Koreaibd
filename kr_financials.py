# -*- coding: utf-8 -*-
"""DART 재무 수집·SMR 등급 산출 공통 모듈 (투트랙 한국형 SMR 적용)."""
import os
import time
import sqlite3
import datetime

import pandas as pd
import numpy as np
import OpenDartReader

DB_NAME = os.environ.get("KR_IBD_DB", "kr_ibd_system.db")
DART_API_KEY = os.environ.get("DART_API_KEY", "")

REPRT_CODES = {
    "11013": (1, "1Q"),
    "11012": (2, "2Q"),
    "11014": (3, "3Q"),
    "11011": (4, "ANNUAL"),
}

ACCOUNT_MAPPING = {
    "ifrs-full_Revenue": "revenue",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLoss": "net_income",
    "ifrs-full_BasicEarningsLossPerShare": "eps",
    "ifrs-full_Equity": "equity",
}


def get_dart_api_key():
    key = os.environ.get("DART_API_KEY", "") or DART_API_KEY
    if key and key not in ("YOUR_ACTUAL_DART_API_KEY", ""):
        return key
    return ""


def expected_latest_quarter(today=None):
    """공시 일정 기준 '최신으로 기대되는' 분기 (year, quarter 1~4)."""
    d = today or datetime.date.today()
    y, m = d.year, d.month
    if m <= 4:
        return (y - 1, 4)
    if m <= 5:
        return (y, 1)
    if m <= 8:
        return (y, 2)
    if m <= 11:
        return (y, 3)
    return (y, 3)


def init_financials_table(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dart_financials'"
    ).fetchone()
    if row:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(dart_financials)")}
        if "eps" not in cols or "period_year" not in cols:
            conn.execute("ALTER TABLE dart_financials RENAME TO dart_financials_legacy")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dart_financials (
            symbol TEXT,
            period_type TEXT,
            period_year INTEGER,
            period_quarter INTEGER,
            period_name TEXT,
            revenue REAL,
            operating_income REAL,
            net_income REAL,
            eps REAL,
            equity REAL,
            PRIMARY KEY (symbol, period_type, period_year, period_quarter)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS financial_fetch_meta (
            symbol TEXT PRIMARY KEY,
            quarter_count INTEGER DEFAULT 0,
            latest_year INTEGER,
            latest_quarter INTEGER,
            last_fetched_at TEXT
        )
    """)


def _parse_amount(series):
    return pd.to_numeric(
        series.astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    ).fillna(0)


def extract_fin_dict(df_fin):
    if df_fin is None or df_fin.empty:
        return {}
    df_filtered = df_fin[df_fin["account_id"].isin(ACCOUNT_MAPPING.keys())].copy()
    if df_filtered.empty:
        return {}
    df_filtered["std_key"] = df_filtered["account_id"].map(ACCOUNT_MAPPING)
    df_filtered["amt"] = _parse_amount(df_filtered["thstrm_amount"])
    df_filtered = df_filtered.sort_values("amt", key=lambda s: s.abs(), ascending=False)
    return df_filtered.groupby("std_key")["amt"].first().to_dict()


def _fetch_reports(dart, ticker, years, sleep_sec=0.08):
    rows = []
    for y in years:
        for reprt_code, (q_num, q_label) in REPRT_CODES.items():
            try:
                df_fin = dart.finstate_all(ticker, str(y), reprt_code=reprt_code, fs_div="OFS")
            except Exception:
                continue
            fin = extract_fin_dict(df_fin)
            if not fin.get("revenue") and not fin.get("net_income"):
                continue

            period_type = "ANNUAL" if q_label == "ANNUAL" else "QUARTER"
            period_name = f"{y} {q_label}" if q_label != "ANNUAL" else f"{y} 연간"
            rows.append({
                "symbol": ticker,
                "period_type": period_type,
                "period_year": int(y),
                "period_quarter": q_num,
                "period_name": period_name,
                "revenue": fin.get("revenue", 0),
                "operating_income": fin.get("operating_income", 0),
                "net_income": fin.get("net_income", 0),
                "eps": fin.get("eps", 0),
                "equity": fin.get("equity", 0),
            })
            if sleep_sec:
                time.sleep(sleep_sec)
    return rows


def fetch_symbol_financials(dart, ticker, years_back=5):
    current_year = datetime.date.today().year
    years = list(range(current_year - years_back, current_year + 1))
    return _fetch_reports(dart, ticker, years)


def fetch_symbol_financials_incremental(dart, ticker):
    y = datetime.date.today().year
    return _fetch_reports(dart, ticker, [y, y - 1], sleep_sec=0.06)


def get_symbol_financial_status(conn, ticker):
    row = conn.execute(
        """
        SELECT COUNT(*), MAX(period_year), MAX(period_quarter)
        FROM dart_financials
        WHERE symbol=? AND period_type='QUARTER'
        """,
        (ticker,),
    ).fetchone()
    cnt = row[0] or 0
    if cnt == 0:
        return {"count": 0, "latest_year": None, "latest_quarter": None}
    return {"count": cnt, "latest_year": row[1], "latest_quarter": row[2]}


def needs_financial_update(conn, ticker, min_quarters=12):
    st = get_symbol_financial_status(conn, ticker)
    if st["count"] < min_quarters:
        return "full"

    exp_y, exp_q = expected_latest_quarter()
    ly, lq = st["latest_year"], st["latest_quarter"]
    if ly is None:
        return "full"

    if (ly, lq) >= (exp_y, exp_q):
        return None
    return "incremental"


def update_fetch_meta(conn, ticker):
    st = get_symbol_financial_status(conn, ticker)
    conn.execute(
        """
        INSERT OR REPLACE INTO financial_fetch_meta
        (symbol, quarter_count, latest_year, latest_quarter, last_fetched_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            ticker,
            st["count"],
            st["latest_year"],
            st["latest_quarter"],
            datetime.datetime.now().isoformat(timespec="seconds"),
        ),
    )


def save_financial_rows(conn, rows):
    for r in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO dart_financials
            (symbol, period_type, period_year, period_quarter, period_name,
             revenue, operating_income, net_income, eps, equity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["symbol"], r["period_type"], r["period_year"], r["period_quarter"],
                r["period_name"], r["revenue"], r["operating_income"], r["net_income"],
                r["eps"], r["equity"],
            ),
        )


def load_quarterly_df(conn, ticker):
    df = pd.read_sql(
        """
        SELECT * FROM dart_financials
        WHERE symbol = ? AND period_type = 'QUARTER'
        ORDER BY period_year DESC, period_quarter DESC
        """,
        conn,
        params=(ticker,),
    )
    return df


def _yoy_pct(current, prior):
    if prior is None or prior == 0 or pd.isna(prior):
        return np.nan
    return (current - prior) / abs(prior) * 100


def smr_metrics_from_quarterly(df_q):
    """
    한국형 투트랙(Dual-Track) SMR 점수 산출
    - 트랙 A (복리 성장형): 꾸준한 영업이익 및 순이익 우상향 / 안정성
    - 트랙 B (턴어라운드/가속도형): 적자 흑자전환 및 이익 가속도 폭발
    """
    if df_q.empty or len(df_q) < 5:
        return None
        
    df = df_q.sort_values(["period_year", "period_quarter"]).copy()
    latest = df.iloc[-1]
    
    prior_year_rows = df[
        (df["period_year"] == latest["period_year"] - 1)
        & (df["period_quarter"] == latest["period_quarter"])
    ]
    if prior_year_rows.empty:
        return None
    prior = prior_year_rows.iloc[-1]
    prev_q = df.iloc[-2] if len(df) >= 2 else latest

    rev_growth = _yoy_pct(latest["revenue"], prior["revenue"])
    op_margin_now = latest["operating_income"] / latest["revenue"] if latest["revenue"] else 0
    op_margin_prev = prior["operating_income"] / prior["revenue"] if prior["revenue"] else 0
    margin_delta = (op_margin_now - op_margin_prev) * 100

    roe_now = latest["net_income"] / latest["equity"] if latest["equity"] else 0
    roe_prev = prior["net_income"] / prior["equity"] if prior["equity"] else 0
    roe_growth = _yoy_pct(roe_now, roe_prev)

    if any(pd.isna(x) for x in [rev_growth, margin_delta, roe_growth]):
        return None

    # --- 투트랙 (Dual-Track) 스코어링 시스템 ---
    score_track_a = 0  # 복리 성장형 트랙
    score_track_b = 0  # 턴어라운드 / 가속도형 트랙

    latest_op = latest["operating_income"]
    prior_op = prior["operating_income"]
    prev_q_op = prev_q["operating_income"]

    # 1. 트랙 A: 복리 성장형 (Secular Growth) 평가
    if latest_op > 0 and prior_op > 0:
        op_growth_yoy = _yoy_pct(latest_op, prior_op)
        if op_growth_yoy >= 15:
            score_track_a += 50
        elif op_growth_yoy > 0:
            score_track_a += 25
            
        if rev_growth >= 10:
            score_track_a += 30
        elif rev_growth > 0:
            score_track_a += 15
            
        if roe_now > 0.1:  # 우량 ROE 10% 이상
            score_track_a += 20

    # 2. 트랙 B: 턴어라운드 및 가속도형 (Turnaround & Momentum) 평가
    if prior_op <= 0 and latest_op > 0:
        score_track_b += 70  # 강력한 적자 흑자전환
    elif latest_op > prior_op and latest_op > prev_q_op:
        accel_bonus = _yoy_pct(latest_op, prior_op)
        if not pd.isna(accel_bonus) and accel_bonus > 20:
            score_track_b += 60
        else:
            score_track_b += 30

    # 두 트랙 중 더 유리한 점수를 최종 composite 점수로 반영
    composite = max(score_track_a, score_track_b)

    return {
        "rev_growth": rev_growth,
        "margin_delta": margin_delta,
        "roe_growth": roe_growth,
        "composite": composite,
    }


def assign_smr_grades(metrics_by_symbol, all_symbols=None):
    valid = {s: m for s, m in metrics_by_symbol.items() if m is not None}
    if not valid:
        return {}
    df = pd.DataFrame.from_dict(valid, orient="index")
    labels = ["E", "D", "C", "B", "A"]
    ranks = df["composite"].rank(method="first")
    n = len(df)
    if n < 5:
        order = ranks.sort_values(ascending=False).index.tolist()
        grade_map = {sym: labels[min(i, 4)] for i, sym in enumerate(order)}
    else:
        grades = pd.qcut(ranks, 5, labels=labels)
        grade_map = {sym: str(grades.loc[sym]) for sym in df.index}

    if all_symbols is not None:
        for sym in all_symbols:
            if sym not in grade_map:
                grade_map[sym] = "E"
    return grade_map


def collect_smr_metrics_for_universe(conn, symbols):
    metrics = {}
    for ticker in symbols:
        df_q = load_quarterly_df(conn, ticker)
        m = smr_metrics_from_quarterly(df_q)
        if m:
            metrics[ticker] = m
    return metrics


def build_financial_display_table(df_q, max_quarters=20):
    if df_q.empty:
        return pd.DataFrame()

    df = df_q.sort_values(["period_year", "period_quarter"], ascending=False).head(max_quarters)
    df = df.sort_values(["period_year", "period_quarter"]).copy()
    lookup = df.set_index(["period_year", "period_quarter"])

    rows = []
    for _, r in df.iterrows():
        y, q = int(r["period_year"]), int(r["period_quarter"])
        prior_key = (y - 1, q)
        prior = lookup.loc[prior_key] if prior_key in lookup.index else None

        def yoy(cur, field):
            if prior is None:
                return None
            p = prior[field] if isinstance(prior, pd.Series) else prior
            return _yoy_pct(cur, p)

        rows.append({
            "분기": r["period_name"],
            "매출액(원)": r["revenue"],
            "매출 YoY(%)": yoy(r["revenue"], "revenue"),
            "영업이익(원)": r["operating_income"],
            "영업이익 YoY(%)": yoy(r["operating_income"], "operating_income"),
            "당기순이익(원)": r["net_income"],
            "순이익 YoY(%)": yoy(r["net_income"], "net_income"),
            "EPS(원)": r["eps"],
            "EPS YoY(%)": yoy(r["eps"], "eps"),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.iloc[::-1].reset_index(drop=True)
    return out


def sync_symbol_financials(conn, dart, ticker):
    mode = needs_financial_update(conn, ticker)
    if mode is None:
        return "skip"
    if mode == "full":
        rows = fetch_symbol_financials(dart, ticker, years_back=5)
    else:
        rows = fetch_symbol_financials_incremental(dart, ticker)
    if rows:
        save_financial_rows(conn, rows)
        update_fetch_meta(conn, ticker)
        return "updated"
    return "fail"


def ensure_ticker_financials(ticker, years_back=5):
    api_key = get_dart_api_key()
    if not api_key:
        return False

    conn = sqlite3.connect(DB_NAME)
    init_financials_table(conn)
    if needs_financial_update(conn, ticker) is None:
        conn.close()
        return True

    dart = OpenDartReader(api_key)
    result = sync_symbol_financials(conn, dart, ticker)
    conn.commit()
    conn.close()
    return result in ("updated", "skip")
