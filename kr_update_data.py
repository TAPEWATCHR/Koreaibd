# -*- coding: utf-8 -*-
import FinanceDataReader as fdr
import OpenDartReader
import pandas as pd
import numpy as np
import sqlite3
import datetime
import time
import os

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
    # 코스피, 코스닥 전체 시장 목록 및 업종(Sector) 데이터 추출
    df_krx = fdr.StockListing('KRX')
    df_krx = df_krx[df_krx['Market'].isin(['KOSPI', 'KOSDAQ'])].copy()
    df_krx = df_krx.dropna(subset=['Sector']) # 세부 섹터 정보가 없는 종목 제외
    
    print(f"총 {len(df_krx)}개 종목의 기술적 지표 연산을 시작합니다.")
    
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=450) # 200일선 및 1년치 수익률 확보용 계산 범위
    
    results = []
    today_str = today.strftime('%Y-%m-%d')
    
    # 계산 가속화를 위해 룹 돌며 연산 실행
    for idx, row in df_krx.iterrows():
        ticker = row['Symbol']
        name = row['CodeName'] if 'CodeName' in row else row['Name']
        sector = row['Sector']
        
        try:
            df_hist = fdr.DataReader(ticker, start=start_date, end=today)
            if len(df_hist) < 240: # 최소 거래일수 미달 종목 패스
                continue
                
            close = df_hist['Close']
            volume = df_hist['Volume']
            
            current_price = float(close.iloc[-1])
            
            # --- [요청 사항 4] 가중 RS 점수 산식 구현 ---
            # 1개월(20거래일), 3개월(60거래일), 6개월(120거래일), 12개월(240거래일) 전 종가 기준 수익률 계산
            ret_1m = (current_price / close.iloc[-20]) - 1 if len(close) >= 20 else 0
            ret_3m = (current_price / close.iloc[-60]) - 1 if len(close) >= 60 else 0
            ret_6m = (current_price / close.iloc[-120]) - 1 if len(close) >= 120 else 0
            ret_12m = (current_price / close.iloc[-240]) - 1 if len(close) >= 240 else 0
            
            # 지정된 가중치 적용 (1m 35%, 3m 25%, 6m 20%, 12m 20%)
            weighted_momentum = (ret_1m * 0.35) + (ret_3m * 0.25) + (ret_6m * 0.20) + (ret_12m * 0.20)
            
            # --- [요청 사항 4] AD 등급 산식 고도화 ---
            # 50일 평균 거래량 계산
            vol_avg50 = volume.rolling(50).mean()
            df_ad = pd.DataFrame({'Close': close, 'Volume': volume, 'AvgVol': vol_avg50}).tail(50)
            df_ad['PrevClose'] = df_ad['Close'].shift(1)
            df_ad = df_ad.dropna()
            
            # 50일 평균 거래량보다 낮은 거래량은 철저히 무시 (순수 기관 자금만 필터링)
            df_ad['ExcessVol'] = df_ad['Volume'] - df_ad['AvgVol']
            df_ad.loc[df_ad['ExcessVol'] < 0, 'ExcessVol'] = 0
            
            # 초과 거래량이 터진 날의 상승/하락 누적 연산
            accum_vol = df_ad[(df_ad['Close'] > df_ad['PrevClose'])]['ExcessVol'].sum()
            dist_vol = df_ad[(df_ad['Close'] < df_ad['PrevClose'])]['ExcessVol'].sum()
            
            ad_ratio = accum_vol / (accum_vol + dist_vol + 1e-5)
            adv_50_val = float(vol_avg50.iloc[-1] * current_price) # 대금 환산용 기준값
            
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
    
    # AD 비율에 따른 5단계 상대평가 등급 배정 (상위 20% A ~ 하락 최하위 E)
    ad_labels = ['E', 'D', 'C', 'B', 'A']
    df_res['ad_grade'] = pd.qcut(df_res['ad_ratio'].rank(method='first'), 5, labels=ad_labels)
    
    # --- [요청 사항 3] 세부 섹터 기반의 산업군 RS 점수 재계산 ---
    industry_means = df_res.groupby('industry')['rs_score'].transform('mean')
    df_res['industry_rs_score'] = pd.qcut(industry_means.rank(method='first'), 99, labels=False) + 1
    
    # SMR 등급 임시 기본값 매핑 (추후 DART 재무 연동 시 고도화 가속)
    df_res['smr_grade'] = 'C'
    
    # 정산된 기술 데이터 수치를 로컬 DB에 반영 및 역사적 히스토리 축적
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
        print("⚠️ DART 인증키가 설정되지 않았거나 데이터가 없어 재무 업데이트를 건너뜁니다.")
        return
        
    dart = OpenDartReader(DART_API_KEY)
    # 효율적인 호출 제어를 위해 연산 결과 중 상위 RS 스코어 주도주 150개만 타겟 압축 수행
    target_stocks = df_res.sort_values('rs_score', ascending=False).head(150)['symbol'].tolist()
    
    current_year = datetime.date.today().year
    target_years = [str(current_year - 1), str(current_year - 2)]
    
    # DART 계정과목 Taxonomy 표준화 매핑 사전 (FMP 표준 형식 스키마 준수)
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
        time.sleep(0.15) # 오픈다트 서버 트래픽 차단 제한 방지용 딜레이
        for y in target_years:
            # 1분기(11013), 반기(11012), 3분기(11014), 사업보고서(11011) 순차 수집
            for q_code, q_name in [('11011', 'ANNUAL'), ('11013', '1Q'), ('11012', '2Q'), ('11014', '3Q')]:
                try:
                    df_fin = dart.finstate_all(ticker, y, repr_t_code='OFS', bsns_year=q_code)
                    if df_fin is None or df_fin.empty:
                        continue
                        
                    # 필수 항목만 정밀 필터링 후 가공
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
