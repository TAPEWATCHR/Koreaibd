# -*- coding: utf-8 -*-
"""데이터 수집 파이프라인 스모크 테스트 (전체 시장 스캔 없이 샘플 검증)."""
import io
import sqlite3

import FinanceDataReader as fdr
import pandas as pd
import requests

from kr_financials import (
    DB_NAME,
    get_dart_api_key,
    fetch_symbol_financials,
    build_financial_display_table,
    init_financials_table,
    save_financial_rows,
)
import OpenDartReader


def main():
    print("=== 한국 주식 데이터 검증 ===\n")
    ok = True

    # 1. 종목·섹터
    df_krx = fdr.StockListing("KRX")
    t_col = "Code" if "Code" in df_krx.columns else "Symbol"
    n = len(df_krx[df_krx["Market"].isin(["KOSPI", "KOSDAQ"])])
    print(f"[1] KRX 상장 종목: {n}개 → {'OK' if n > 500 else 'FAIL'}")
    ok &= n > 500

    kind_url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download"
    res = requests.get(kind_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    df_kind = pd.read_html(io.StringIO(res.text), header=0)[0]
    df_kind["종목코드"] = df_kind["종목코드"].astype(str).str.zfill(6)
    sector = df_kind[df_kind["종목코드"] == "005930"]["업종"].iloc[0]
    print(f"[2] KIND 섹터(삼성전자): {sector} → OK")

    # 2. 가격·거래량
    hist = fdr.DataReader("005930")
    has_ohlcv = len(hist) >= 240 and "Close" in hist and "Volume" in hist
    print(f"[3] OHLCV(005930): {len(hist)}일, 종가 {hist['Close'].iloc[-1]:,.0f} → {'OK' if has_ohlcv else 'FAIL'}")
    ok &= has_ohlcv

    # 3. DART 재무
    key = get_dart_api_key()
    if not key:
        print("[4] DART API 키 없음 → SKIP")
    else:
        dart = OpenDartReader(key)
        rows = fetch_symbol_financials(dart, "005930", years_back=5)
        q_rows = [r for r in rows if r["period_type"] == "QUARTER"]
        print(f"[4] DART 분기 재무(005930): {len(q_rows)}건 → {'OK' if len(q_rows) >= 8 else 'FAIL'}")
        ok &= len(q_rows) >= 8

        conn = sqlite3.connect(":memory:")
        init_financials_table(conn)
        save_financial_rows(conn, rows)
        df_q = pd.read_sql(
            "SELECT * FROM dart_financials WHERE symbol='005930' AND period_type='QUARTER'",
            conn,
        )
        table = build_financial_display_table(df_q)
        print(f"[5] 재무표시 샘플 행수: {len(table)} → {'OK' if not table.empty else 'FAIL'}")
        if not table.empty:
            print(table.head(3).to_string(index=False))
        ok &= not table.empty

    # 4. DB 존재 시 요약
    if __import__("os").path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        n_repo = pd.read_sql("SELECT COUNT(*) c FROM repo_results", conn).iloc[0]["c"]
        n_fin = pd.read_sql("SELECT COUNT(DISTINCT symbol) c FROM dart_financials", conn).iloc[0]["c"]
        conn.close()
        print(f"\n[DB] repo_results: {n_repo}종목 | dart_financials: {n_fin}종목")
    else:
        print(f"\n[DB] {DB_NAME} 없음 (kr_update_data.py 실행 후 생성됨)")

    print("\n=== 결과:", "PASS" if ok else "일부 FAIL ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
