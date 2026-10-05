import io
import json
import re
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
import openai

# ==========================================
# 페이지 기본 설정 & 프리미엄 CSS
# ==========================================
st.set_page_config(
    page_title="SellOmni Pro - 커머스 SEO & 마진 솔루션",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS (전문가용 대시보드 스타일)
st.markdown("""
<style>
    /* 메인 배경 및 폰트 정의 */
    .main {
        background-color: #f8fafc;
    }
    
    /* 카드 스타일링 */
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        margin-bottom: 12px;
    }
    .metric-title {
        font-size: 0.85rem;
        color: #64748b;
        font-weight: 600;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.4rem;
        color: #0f172a;
        font-weight: 700;
    }
    
    /* SEO 코드 박스 컨테이너 */
    .seo-box {
        background-color: #f1f5f9;
        border-left: 4px solid #3b82f6;
        padding: 12px;
        border-radius: 6px;
        font-weight: 600;
    }
    
    /* Primary 버튼 스타일 */
    .stButton>button {
        border-radius: 8px;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 바이트 계산 및 절삭 함수
# ==========================================
def calculate_byte(text: str) -> int:
    count = 0
    for char in text:
        if ord(char) > 127:
            count += 2
        else:
            count += 1
    return count

def truncate_by_byte(text: str, max_bytes: int) -> str:
    current_bytes = 0
    truncated_text = ""
    for char in text:
        char_byte = 2 if ord(char) > 127 else 1
        if current_bytes + char_byte > max_bytes:
            break
        current_bytes += char_byte
        truncated_text += char
    return truncated_text.strip()

# ==========================================
# 실시간 환율 가져오기 함수 (USD, EUR, CNY)
# ==========================================
@st.cache_data(ttl=3600)
def get_realtime_exchange_rates():
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        response = requests.get(url, timeout=5)
        data = response.json()
        
        usd_to_krw = data["rates"]["KRW"]
        usd_to_eur = data["rates"]["EUR"]
        usd_to_cny = data["rates"]["CNY"]
        
        eur_to_krw = usd_to_krw / usd_to_eur if usd_to_eur else 1480.0
        cny_to_krw = usd_to_krw / usd_to_cny if usd_to_cny else 195.0
        
        return round(usd_to_krw, 2), round(eur_to_krw, 2), round(cny_to_krw, 2)
    except Exception:
        return 1380.0, 1480.0, 195.0

realtime_usd, realtime_eur, realtime_cny = get_realtime_exchange_rates()

# ==========================================
# 웹 크롤링 함수
# ==========================================
def fetch_product_info_from_url(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    extracted_title = ""
    extracted_price = 0.0
    detected_currency = "CNY"
    
    try:
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=10, allow_redirects=True)
        final_url = response.url.lower()
        
        if "amazon.de" in final_url or ".de" in final_url or ".eu" in final_url or "amazon.fr" in final_url or "amazon.it" in final_url:
            detected_currency = "EUR"
        elif "taobao" in final_url or "1688" in final_url or "tmall" in final_url:
            detected_currency = "CNY"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title_tag = soup.find("id", "productTitle") or soup.find("meta", property="og:title")
        if title_tag:
            extracted_title = title_tag.get("content", "") if title_tag.name == "meta" else title_tag.get_text()
        elif soup.title and soup.title.string:
            extracted_title = soup.title.string
            
        price_span = soup.find("span", class_="a-offscreen") or soup.find("span", id="priceblock_ourprice") or soup.find("span", class_="
