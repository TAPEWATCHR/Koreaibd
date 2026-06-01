# -*- coding: utf-8 -*-
import sqlite3
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime

def init_db():
    conn = sqlite3.connect('kr_ibd_system.db')
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS repo_results (
            symbol TEXT PRIMARY KEY, price INTEGER, rs_score INTEGER,
            industry_rs_score INTEGER, smr_grade TEXT, ad_grade TEXT, adv_50 REAL, industry TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rs_history (
            symbol TEXT, date TEXT, rs_score INTEGER, industry_rs_score INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    conn.commit()
    conn.close()

def fetch_market_leaders():
    """네이버 금융 시가총액 상위 페이지에서 주도주 후보군(코스피/코스닥 상위 각 250종목) 추출"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36'}
    candidate_stocks = []
    
    for sosok in [0, 1]:
        market_label = "KOSPI" if sosok == 0 else "KOSDAQ"
        for page in range(1, 6):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}&field=per&field=roe"
            try:
                res = requests.get(url, headers=headers, timeout=10)
                soup = BeautifulSoup(res.text, 'html.parser')
                table = soup.find('table', {'class': 'type_2'})
                if not table: continue
                
                th_tags = table.find_all('th')
                col_map = {th.text.strip(): idx for idx, th in enumerate(th_tags)}
                
                for tr in table.find_all('tr'):
                    a_tag = tr.find('a', {'class': 'tltle'})
                    if not a_tag: continue
                    tds = tr.find_all('td')
                    if len(tds) < len(col_map): continue
                    
                    name = a_tag.text.strip()
                    if "스팩" in name or name.endswith("우") or name.endswith("우B"): continue
                    
                    ticker = a_tag['href'].split('code=')[-1].strip()
                    price = int(tds[col_map['현재가']].text.replace(',', '').strip())
                    
                    per_txt = tds[col_map['PER']].text.replace(',', '').strip()
                    roe_txt = tds[col_map['ROE']].text.replace(',', '').strip()
                    per = float(per_txt) if per_txt and per_txt != 'N/A' else 0.0
                    roe = float(roe_txt) if roe_txt and roe_txt != 'N/A' else 0.0
                    
                    candidate_stocks.append({
                        'ticker': ticker, 'name': name, 'price': price,
                        'per': per, 'roe': roe, 'industry': market_label
                    })
            except Exception as e:
                print(f"⚠️ 네이버 페이지 수집 중 오류 발생 ({market_label} P.{page}): {e}")
                
    return candidate_stocks

def analyze_stock_history(ticker, debug=False):
    """네이버 차트 엔진에서 1년치 일별 데이터를 가져와 RS 및 AD 메트릭 연산"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    }
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count=260&requestType=0"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            if debug: print(f"   ↳ [디버그] {ticker} HTTP 에러 코드: {res.status_code}")
            return None
            
        # 🌟 [인코딩 에러 핵심 해결부] 
        # 1. 바이너리 데이터를 EUC-KR로 명시적 디코딩하여 파이썬 표준 문자열로 변환
        xml_text = res.content.decode('euc-kr', errors='ignore')
        
        # 2. 파서가 거부감을 느끼는 구식 머리말(<?xml ... ?>) 강제 제거
        if xml_text.strip().startswith('<?xml'):
            xml_text = xml_text.split('?>', 1)[1].strip()
            
        if not xml_text or "item" not in xml_text:
            if debug: print(f"   ↳ [디버그] {ticker} 응답 데이터가 올바르지 않음")
            return None

        # 3. 깨끗해진 순수 XML 문자열을 파싱
        root = ET.fromstring(xml_text)
        items = root.findall('.//item')
        
        prices = []
        volumes = []
        for item in items:
            data = item.get('data').split('|')
            if len(data) >= 6:
                prices.append(int(data[4]))  # 종가
                volumes.append(int(data[5])) # 거래량
                
        if len(prices) < 50: 
            if debug: print(f"   ↳ [디버그] {ticker} 데이터 일수 부족 ({len(prices)}일)")
            return None
        
        # 1. 1년 주가 수익률
        one_year_return = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
        
        # 2. 50일 평균 거래대금
        recent_prices = prices[-50:]
        recent_volumes = volumes[-50:]
        adv_50 = np.mean([p * v for p, v in zip(recent_prices, recent_volumes)])
        
        # 3. 기관 매집(AD 수급 등급)
        vol_avg_20 = np.mean(volumes[-20:])
        accum_days = 0
        for i in range(-20, 0):
            if prices[i] > prices[i-1] and volumes[i] > vol_avg_20:
                accum_days += 1
                
        if accum_days >= 7: ad_grade = 'A'
        elif accum_days >= 5: ad_grade = 'B'
        elif accum_days >= 3: ad_grade = 'C'
        elif accum_days >= 1: ad_grade = 'D'
        else: ad_grade = 'E'
        
        return {"return": one_year_return, "adv_50": adv_50, "ad_grade": ad_grade}
    except Exception as e:
        if debug: print(f"   ↳ [디버그] {ticker} 예외 발생: {e}")
        return None

def update_kr_data():
    init_db()
    today = datetime.today().strftime('%Y%m%d')
    print(f"🌐 [클라우드 바이패스 모드] 네이버 인텔리전스 수집 시작 (기준일: {today})")
    
    base_stocks = fetch_market_leaders()
    print(f"🎯 1차 스크리닝 후보군 총 {len(base_stocks)}개 종목 확보 완료.")
    
    valid_results = []
    print("⏳ 종목별 상세 시계열 데이터 분석 중...")
    for idx, s in enumerate(base_stocks):
        debug_mode = True if idx < 3 else False
        hist_metrics = analyze_stock_history(s['ticker'], debug=debug_mode)
        if not hist_metrics: continue
        
        roe = s['roe']
        if roe >= 15: smr_grade = 'A'
        elif roe >= 10: smr_grade = 'B'
        elif roe >= 5: smr_grade = 'C'
        elif roe >= 0: smr_grade = 'D'
        else: smr_grade = 'E'
        
        s.update(hist_metrics)
        s['smr_grade'] = smr_grade
        valid_results.append(s)
        
    if not valid_results:
        print("🚨 유효한 데이터를 정제하지 못했습니다. 모든 종목 분석에 실패했습니다.")
        return
        
    print(f"📊 {len(valid_results)}개 종목 분석 성공. RS 스코어 계산 및 DB 저장 시작...")
    df_final = pd.DataFrame(valid_results)
    df_final['rs_score'] = pd.qcut(df_final['return'].rank(method='first'), 99, labels=False) + 1
    
    final_rows = []
    history_rows = []
    for _, row in df_final.iterrows():
        full_symbol = f"{row['ticker']} ({row['name']})"
        rs = int(row['rs_score'])
        
        final_rows.append((
            full_symbol, int(row['price']), rs, int(rs * 0.96),
            row['smr_grade'], row['ad_grade'], float(row['adv_50']), row['industry']
        ))
        history_rows.append((full_symbol, today, rs, int(rs * 0.96)))
        
    conn = sqlite3.connect('kr_ibd_system.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM repo_results")
    cursor.executemany("INSERT OR REPLACE INTO repo_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)", final_rows)
    cursor.executemany("INSERT OR REPLACE INTO rs_history VALUES (?, ?, ?, ?)", history_rows)
    conn.commit()
    conn.close()
    
    print(f"🎉 성공! 차단벽을 뚫고 {len(final_rows)}개 주도주의 최종 DB 갱신을 완료했습니다.")

if __name__ == "__main__":
    update_kr_data()
