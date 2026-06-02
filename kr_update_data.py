# -*- coding: utf-8 -*-
import FinanceDataReader as fdr
import OpenDartReader
import pandas as pd
import numpy as np
import sqlite3
import datetime
import time
import os
import requests
import io

# ==============================================================================
# [사용자 필수 변경 항목] 발급받으신 DART API 키를 여기에 입력하세요.
# ==============================================================================
DART_API_KEY = "74338fa9ee91fca6545b4bc7caec0c71d581e84b" 
DB_NAME = "kr_ibd_system.db"

def init_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # 주도주 기술적 연산 결과 테이블
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
    # 차트용 역사적 RS 점수 기록 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rs_history (
            symbol TEXT,
            date TEXT,
            rs_score INTEGER,
            industry_rs_score INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    # DART 기반 FMP 스타일 재무제표 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dart_financials (
            symbol TEXT,
            period_type TEXT, -- 'ANNUAL' 또는 'QUARTER'
            period_name TEXT, -- 예: '2025', '2025 1Q'
            revenue REAL,
            operating_income REAL,
            net_income REAL,
            current_assets REAL,
            total_liabilities REAL,
            PRIMARY KEY (symbol, period_type, period_name)
        )
    """)
    conn.commit()
    conn.close()

def calculate_technical_metrics():
    print("🚀 [1/4] 한국거래소 상장 종목 및 세부 섹터 정보 수집 중...")
    
    # 1. 기본 종목 리스트 수집
    df_krx = fdr.StockListing('KRX')
    
    # FinanceDataReader 버전별 컬럼명 상이 문제 대응 (Code 또는 Symbol 자동 판별)
    t_col = 'Code' if 'Code' in df_krx.columns else 'Symbol'
    n_col = 'Name' if 'Name' in df_krx.columns else 'CodeName'
    
    # 2. [오류 해결] 한국거래소 KIND 시스템에서 업종(Sector) 데이터 직접 추출 및 결합
    try:
        kind_url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(kind_url, headers=headers)
        df_kind = pd.read_html(io.StringIO(res.text), header=0)[0]
        
        # 종목코드 6자리 매칭을 위한 패딩 작업 및 맵 생성
        df_kind['종목코드'] = df_kind['종목코드'].astype(str).str.zfill(6)
        sector_map = df_kind.set_index('종목코드')['업종'].to_dict()
        
        # 불러온 종목 리스트에 실시간 맵핑 방식으로 Sector 컬럼 강제 주입
        df_krx['Sector'] = df_krx[t_col].map(sector_map)
    except Exception as e:
        print(f"⚠️ KIND 업종 정보 매핑 실패 ({e}), 방어 로직 가동 (기본값 대체).")
        df_krx['Sector'] = '기타업종'
        
    # 시장 필터링 및 결측치 방어 처리
    df_krx = df_krx[df_krx['Market'].isin(['KOSPI', 'KOSDAQ'])].copy()
    df_krx['Sector'] = df_krx['Sector'].fillna('기타업종')
    
    print(f"총 {len(df_krx)}개 종목의 기술적 지표 연산을 시작합니다.")
    
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=450)
    
    results = []
    today_str = today.strftime('%Y-%m-%d')
    
    for idx, row in df_krx.iterrows():
        ticker = row[t_col]
        name = row[n_col]
        sector = row['Sector']
        
        try:
            df_hist = fdr.DataReader(ticker, start=start_date, end=today)
            if len(df_hist) < 240:
                continue
                
            close = df_hist['Close']
            volume = df_hist['Volume']
            current_price = float(close.iloc[-1])
            
            # 1개월(35%), 3개월(25%), 6개월(20%), 12개월(20%) 가중 수익률 계산
            ret_1m = (current_price / close.iloc[-20]) - 1 if len(close) >= 20 else 0
            ret_3m = (current_price / close.iloc[-60]) - 1 if len(close) >= 60 else 0
            ret_6m = (current_price / close.iloc[-120]) - 1 if len(close) >= 120 else 0
            ret_12m = (current_price / close.iloc[-240]) - 1 if len(close) >= 240 else 0
            
            weighted_momentum = (ret_1m * 0.35) + (ret_3m * 0.25) + (ret_6m * 0.20) + (ret_12m * 0.20)
            
            # AD 등급용 50일 평균 거래량 이하 무시 및 초과분만 계산
            vol_avg50 = volume.rolling(50).mean()
            df_ad = pd.DataFrame({'Close': close, 'Volume': volume, 'AvgVol': vol_avg50}).tail(50)
            df_ad['PrevClose'] = df_ad['Close'].shift(1)
            df_ad = df_ad.dropna()
            
            df_ad['ExcessVol'] = df_ad['Volume'] - df_ad['AvgVol']
            df_ad.loc[df_ad['ExcessVol'] < 0, 'ExcessVol'] = 0
            
            accum_vol = df_ad[(df_ad['Close'] > df_ad['PrevClose'])]['ExcessVol'].sum()
            dist_vol = df_ad[(df_ad['Close'] < df_ad['PrevClose'])]['ExcessVol'].sum()
            
            ad_ratio = accum_vol / (accum_vol + dist_vol + 1e-5)
            adv_50_val = float(vol_avg50.iloc[-1] * current_price)
            
            results.append({
                'symbol': ticker, 'name': name, 'price': current_price,
                'raw_momentum': weighted_momentum, 'ad_ratio': ad_ratio,
                'adv_50': adv_50_val, 'industry': sector
            })
        except:
            continue

    if not results:
        print("🚨 연산 가능한 종목 데이터가 존재하지 않습니다.")
        return pd.DataFrame()

    df_res = pd.DataFrame(results)
    
    # 전체 시장 내 백분위 순위로 RS 점수 매김 (1 ~ 99)
    df_res['rs_score'] = pd.qcut(df_res['raw_momentum'].rank(method='first'), 99, labels=False) + 1
    
    # AD 비율 기반 5단계 상대평가 등급 배정
    ad_labels = ['E', 'D', 'C', 'B', 'A']
    df_res['ad_grade'] = pd.qcut(df_res['ad_ratio'].rank(method='first'), 5, labels=ad_labels)
    
    # 세부 섹터 기반의 산업군 RS 점수 재계산
    industry_means = df_res.groupby('industry')['rs_score'].transform('mean')
    df_res['industry_rs_score'] = pd.qcut(industry_means.rank(method='first'), 99, labels=False) + 1
    df_res['smr_grade'] = 'C'
    
    conn = sqlite3.connect(DB_NAME)
    df_res[['symbol', 'name', 'price', 'rs_score', 'industry_rs_score', 'smr_grade', 'ad_grade', 'adv_50', 'industry']].to_sql('repo_results', conn, if_exists='replace', index=False)
    
    for _, r in df_res.iterrows():
        try:
            conn.execute("INSERT OR REPLACE INTO rs_history (symbol, date, rs_score, industry_rs_score) VALUES (?, ?, ?, ?)",
                         (r['symbol'], today_str, int(r['rs_score']), int(r['industry_rs_score'])))
        except:
            pass
    conn.commit()
    conn.close()
    print("✅ [2/4] 기술적 모멘텀 및 가중 섹터 RS 연산 DB 저장 완료.")
    return df_res

def update_dart_financials(df_res):
    print("🚀 [3/4] DART 공시 데이터 추출 및 표준 명칭 계정 일치화 작업 시작...")
    if df_res.empty or DART_API_KEY == "YOUR_ACTUAL_DART_API_KEY":
        print("⚠️ DART 인증키가 설정되지 않았거나 기본값 상태여서 재무 업데이트를 건너뜁니다.")
        return
        
    dart = OpenDartReader(DART_API_KEY)
    target_stocks = df_res.sort_values('rs_score', ascending=False).head(150)['symbol'].tolist()
    
    current_year = datetime.date.today().year
    target_years = [str(current_year - 1), str(current_year - 2)]
    
    account_mapping = {
        'ifrs-full_Revenue': 'revenue',
        'ifrs-full_OperatingIncomeLoss': 'operating_income',
        'ifrs-full_ProfitLoss': 'net_income',
        'ifrs-full_CurrentAssets': 'current_assets',
        'ifrs-full_TotalLiabilities': 'total_liabilities',
        'ifrs-full_Liabilities': 'total_liabilities'
    }
    
    conn = sqlite3.connect(DB_NAME)
    
    for ticker in target_stocks:
        time.sleep(0.15)
        for y in target_years:
            for q_code, q_name in [('11011', 'ANNUAL'), ('11013', '1Q'), ('11012', '2Q'), ('11014', '3Q')]:
                try:
                    df_fin = dart.finstate_all(ticker, y, repr_t_code='OFS', bsns_year=q_code)
                    if df_fin is None or df_fin.empty:
                        continue
                        
                    df_filtered = df_fin[df_fin['account_id'].isin(account_mapping.keys())].copy()
                    if df_filtered.empty:
                        continue
                        
                    df_filtered['std_key'] = df_filtered['account_id'].map(account_mapping)
                    df_filtered['amt'] = pd.to_numeric(df_filtered['thstrm_amount'].str.replace(',', ''), errors='coerce').fillna(0)
                    
                    fin_dict = df_filtered.set_index('std_key')['amt'].to_dict()
                    
                    period_type = 'ANNUAL' if q_name == 'ANNUAL' else 'QUARTER'
                    period_label = f"{y} 연간" if q_name == 'ANNUAL' else f"{y} {q_name}"
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO dart_financials 
                        (symbol, period_type, period_name, revenue, operating_income, net_income, current_assets, total_liabilities)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        ticker, period_type, period_label,
                        fin_dict.get('revenue', 0), fin_dict.get('operating_income', 0),
                        fin_dict.get('net_income', 0), fin_dict.get('current_assets', 0),
                        fin_dict.get('total_liabilities', 0)
                    ))
                except:
                    continue
        conn.commit()
    conn.close()
    print("✅ [4/4] DART 데이터 일치화 수집 및 로컬 기지 데이터베이스 동기화 완료.")

if __name__ == "__main__":
    init_database()
    df_metrics = calculate_technical_metrics()
    update_dart_financials(df_metrics)
