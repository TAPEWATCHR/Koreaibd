# -*- coding: utf-8 -*-
import FinanceDataReader as fdr
import pandas as pd
import numpy as np
import sqlite3
import datetime
import time
import os
import requests
import io
from kr_financials import (
    DB_NAME,
    get_dart_api_key,
    init_financials_table,
    assign_smr_grades,
    collect_smr_metrics_for_universe,
    needs_financial_update,
    sync_symbol_financials,
    update_fetch_meta,
)
import OpenDartReader  # 💡 대소문자 오류 방지를 위해 소문자 모듈 사용

# 환경변수 DART_API_KEY 우선, 없으면 로컬 기본값
DART_API_KEY = os.environ.get(
    "DART_API_KEY",
    "74338fa9ee91fca6545b4bc7caec0c71d581e84b",
)

if DART_API_KEY and DART_API_KEY != "YOUR_ACTUAL_DART_API_KEY":
    os.environ.setdefault("DART_API_KEY", DART_API_KEY)

def init_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS repo_results (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            price REAL,
            rs_score INTEGER,
            industry_rs_score INTEGER,
            smr_grade TEXT,
            ad_grade TEXT,
            adv_50 REAL,
            industry TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rs_history (
            symbol TEXT,
            date TEXT,
            rs_score INTEGER,
            industry_rs_score INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    init_financials_table(conn)
    conn.commit()
    conn.close()

def calculate_technical_metrics():
    print(" 🚀  [1/4] 한국거래소 상장 종목 및 세부 섹터 정보 수집 중...")
    conn = sqlite3.connect(DB_NAME)

    try:
        df_krx = fdr.StockListing("KRX")
        # 💡 [핵심 최적화] KRX 서버 차단 방지를 위해 불러온 최신 리스트를 DB에 캐싱(저장)합니다.
        df_krx.to_sql("krx_tickers_cache", conn, if_exists="replace", index=False)
        print("    ✅ KRX 종목 리스트 최신화 및 DB 저장 완료")
    except Exception as e:
        print(f" ⚠️ KRX 서버 응답 차단/지연. DB에 저장된 기존 캐시 리스트를 사용합니다: {e}")
        try:
            df_krx = pd.read_sql("SELECT * FROM krx_tickers_cache", conn)
            print("    ✅ 기존 DB에서 종목 리스트 불러오기 성공")
        except Exception:
            print(" 🚨 기존 캐시 데이터가 없습니다. 연산을 종료합니다.")
            conn.close()
            return pd.DataFrame()

    t_col = "Code" if "Code" in df_krx.columns else "Symbol"
    n_col = "Name" if "Name" in df_krx.columns else "CodeName"

    try:
        kind_url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(kind_url, headers=headers, timeout=60)
        res.raise_for_status()
        df_kind = pd.read_html(io.StringIO(res.text), header=0)[0]
        df_kind["종목코드"] = df_kind["종목코드"].astype(str).str.zfill(6)
        sector_map = df_kind.set_index("종목코드")["업종"].to_dict()
        df_krx["Sector"] = df_krx[t_col].astype(str).str.zfill(6).map(sector_map)
        print(f"    ✅  KIND 업종 매핑 완료 (샘플: {df_krx['Sector'].notna().sum()}개)")
    except Exception as e:
        print(f" ⚠ ️ KIND 업종 정보 매핑 실패 ({e}), 기본값 사용.")
        df_krx["Sector"] = "기타업종"

    df_krx = df_krx[df_krx["Market"].isin(["KOSPI", "KOSDAQ"])].copy()
    df_krx["Sector"] = df_krx["Sector"].fillna("기타업종")

    print(f"총 {len(df_krx)}개 종목의 기술적 지표 연산을 시작합니다.")

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=450)
    results = []
    today_str = today.strftime("%Y-%m-%d")
    fail_count = 0

    for _, row in df_krx.iterrows():
        ticker = str(row[t_col]).zfill(6)
        name = row[n_col]
        sector = row["Sector"]

        try:
            df_hist = fdr.DataReader(ticker, start=start_date, end=today)
            if len(df_hist) < 240:
                continue

            close = df_hist["Close"]
            volume = df_hist["Volume"]
            current_price = float(close.iloc[-1])

            ret_1m = (current_price / close.iloc[-20]) - 1 if len(close) >= 20 else 0
            ret_3m = (current_price / close.iloc[-60]) - 1 if len(close) >= 60 else 0
            ret_6m = (current_price / close.iloc[-120]) - 1 if len(close) >= 120 else 0
            ret_12m = (current_price / close.iloc[-240]) - 1 if len(close) >= 240 else 0
            
            weighted_momentum = (ret_1m * 0.35) + (ret_3m * 0.25) + (ret_6m * 0.20) + (ret_12m * 0.20)

            vol_avg50 = volume.rolling(50).mean()
            df_ad = pd.DataFrame({"Close": close, "Volume": volume, "AvgVol": vol_avg50}).tail(50)
            df_ad["PrevClose"] = df_ad["Close"].shift(1)
            df_ad = df_ad.dropna()

            df_ad["ExcessVol"] = df_ad["Volume"] - df_ad["AvgVol"]
            df_ad.loc[df_ad["ExcessVol"] < 0, "ExcessVol"] = 0

            accum_vol = df_ad[(df_ad["Close"] > df_ad["PrevClose"])]["ExcessVol"].sum()
            dist_vol = df_ad[(df_ad["Close"] < df_ad["PrevClose"])]["ExcessVol"].sum()

            ad_ratio = accum_vol / (accum_vol + dist_vol + 1e-5)
            adv_50_val = float(vol_avg50.iloc[-1] * current_price)

            results.append({
                "symbol": ticker,
                "name": name,
                "price": current_price,
                "raw_momentum": weighted_momentum,
                "ad_ratio": ad_ratio,
                "adv_50": adv_50_val,
                "industry": sector,
            })
        except Exception:
            fail_count += 1
            continue

    if not results:
        print(" 🚨  연산 가능한 종목 데이터가 존재하지 않습니다.")
        conn.close()
        return pd.DataFrame()

    df_res = pd.DataFrame(results)
    df_res["rs_score"] = pd.qcut(df_res["raw_momentum"].rank(method="first"), 99, labels=False) + 1
    ad_labels = ["E", "D", "C", "B", "A"]
    df_res["ad_grade"] = pd.qcut(df_res["ad_ratio"].rank(method="first"), 5, labels=ad_labels).astype(str)
    industry_means = df_res.groupby("industry")["rs_score"].transform("mean")
    df_res["industry_rs_score"] = pd.qcut(industry_means.rank(method="first"), 99, labels=False) + 1
    df_res["smr_grade"] = "C"

    df_res[
        [
            "symbol", "name", "price", "rs_score", "industry_rs_score",
            "smr_grade", "ad_grade", "adv_50", "industry",
        ]
    ].to_sql("repo_results", conn, if_exists="replace", index=False)

    for _, r in df_res.iterrows():
        try:
            conn.execute(
                "INSERT OR REPLACE INTO rs_history (symbol, date, rs_score, industry_rs_score) VALUES (?, ?, ?, ?)",
                (r["symbol"], today_str, int(r["rs_score"]), int(r["industry_rs_score"])),
            )
        except Exception:
            pass
            
    conn.commit()
    conn.close()

    print(f" ✅  [2/4] 기술적 지표 저장 완료: {len(df_res)}종목 (스킵/오류 {fail_count}건)")
    return df_res

def update_dart_financials(df_res):
    print(" 🚀  [3/4] DART 재무 동기화 (청크 분할 적재) 시작...")

    api_key = get_dart_api_key() or DART_API_KEY
    if not api_key or api_key == "YOUR_ACTUAL_DART_API_KEY":
        print(" ⚠ ️ DART 인증키가 없어 재무·SMR 업데이트를 건너뜁니다.")
        return

    if df_res.empty:
        return

    dart = OpenDartReader(api_key) # 💡 여기서 클래스를 소환하도록 변경
    targets = df_res["symbol"].astype(str).str.zfill(6).tolist()

    conn = sqlite3.connect(DB_NAME)
    init_financials_table(conn)

    targets_to_update = []
    for t in targets:
        if needs_financial_update(conn, t) is not None:
            targets_to_update.append(t)

    print(f"   📊 전체 {len(targets)}종목 중 업데이트가 필요한 종목: {len(targets_to_update)}개")

    # 💡 100개로 축소 (안전한 수집)
    targets_to_update = targets_to_update[:100]
    print(f"   🎯 오늘 수집할 대상은 {len(targets_to_update)}종목입니다.")

    updated, skipped, failed = 0, 0, 0

    for i, ticker in enumerate(targets_to_update):
        try:
            result = sync_symbol_financials(conn, dart, ticker)
            if result == "updated":
                updated += 1
                if updated % 20 == 0:
                    conn.commit()
            elif result == "skip":
                skipped += 1
            else:
                failed += 1
        except Exception:
            failed += 1

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"   ... 진행률: {i+1}/{len(targets_to_update)} (갱신 {updated}, 실패 {failed})")

    conn.commit()

    for ticker in targets_to_update:
        try:
            update_fetch_meta(conn, ticker)
        except Exception:
            pass

    conn.commit()
    conn.close()
    print(f" ✅  [3/4] DART 완료: 금일 대상 {len(targets_to_update)}종목 | 갱신 {updated}, 스킵 {skipped}, 실패 {failed}")

def apply_smr_grades(df_res):
    print(" 🚀  [4/4] SMR 등급 산출 (전 종목 비교) 중...")
    if df_res.empty:
        return df_res

    conn = sqlite3.connect(DB_NAME)
    symbols = df_res["symbol"].astype(str).str.zfill(6).tolist()

    metrics = collect_smr_metrics_for_universe(conn, symbols)
    grades = assign_smr_grades(metrics, all_symbols=symbols)

    df_res = df_res.copy()
    df_res["symbol"] = df_res["symbol"].astype(str).str.zfill(6)
    df_res["smr_grade"] = df_res["symbol"].map(grades).fillna("E")

    conn.execute("DELETE FROM repo_results")
    df_res[
        [
            "symbol", "name", "price", "rs_score", "industry_rs_score",
            "smr_grade", "ad_grade", "adv_50", "industry",
        ]
    ].to_sql("repo_results", conn, if_exists="append", index=False)

    conn.commit()
    conn.close()

    dist = df_res["smr_grade"].value_counts().to_dict()
    print(f" ✅  [4/4] SMR 반영: 비교 가능 {len(metrics)}/{len(symbols)}종목 | 분포 {dist}")

    return df_res

if __name__ == "__main__":
    init_database()
    df_metrics = calculate_technical_metrics()
    update_dart_financials(df_metrics)
    apply_smr_grades(df_metrics)
