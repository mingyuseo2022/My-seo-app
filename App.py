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
""", unsafe_allow_shortcut=True)

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
            
        price_span = soup.find("span", class_="a-offscreen") or soup.find("span", id="priceblock_ourprice") or soup.find("span", class_="a-price-whole")
        if price_span:
            p_text = price_span.get_text().replace(',', '.').replace('€', '').replace('¥', '').strip()
            match = re.search(r'[\d.]+', p_text)
            if match:
                try:
                    extracted_price = float(match.group(0))
                except:
                    extracted_price = 0.0
                    
        if extracted_price == 0.0:
            price_meta = soup.find("meta", property="product:price:amount") or soup.find("meta", property="og:price:amount")
            if price_meta and price_meta.get("content"):
                try:
                    extracted_price = float(re.sub(r'[^0-9.]', '', price_meta["content"]))
                except:
                    extracted_price = 0.0

        return extracted_title.strip(), extracted_price, detected_currency
    except Exception:
        return "", 0.0, "CNY"

def clean_and_validate_title(title: str) -> str:
    cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
    words = cleaned.split()
    seen = set()
    unique_words = []
    for word in words:
        if word not in seen:
            seen.add(word)
            unique_words.append(word)
    return " ".join(unique_words).strip()

def process_seo_title_by_bytes(client: openai.OpenAI, original_title: str, model_name: str) -> dict:
    prompt = f"""
너는 한국 최고의 이커머스 MD이자 SEO 상품명 최적화 전문가야.
아래 해외 상품명을 바탕으로 국내 오픈마켓 규격에 맞춘 2가지 버전의 자연스러운 한국어 상품명을 작성해 줘.

[해외 원본 상품명]
{original_title}

[핵심 작성 규칙]
1. **50Byte 전용 상품명 (네이버 스마트스토어용):**
   - **목표 길이: 44Byte ~ 50Byte (한글 22자~25자 내외로 꽉 채울 것)**
   - 메인 카테고리 + 핵심 대표 키워드를 조합하여 소비자가 읽기 자연스러운 문장 구조로 작성.

2. **100Byte 전용 상품명 (쿠팡, 11번가, G마켓용):**
   - **목표 길이: 88Byte ~ 100Byte (한글 44자~50자 내외로 꽉 채울 것)**
   - 메인 키워드 + 세부 중소형 키워드, 사용 용도, 핵심 특징/디자인 속성을 풍부하게 조합하여 문맥이 자연스럽게 이어지도록 작성.

3. **공통 지침:**
   - 어색한 키워드 단순 나열 금지. 소비자가 바로 이해할 수 있는 자연스러운 어순 지키기.
   - 특수문자, 혜택어(무료배송, 최저가 등), 중복 단어 배제.

[응답 형식 (JSON 규격)]
{{
  "title_50byte": "44~50바이트 목표의 자연스러운 상품명",
  "title_100byte": "88~100바이트 목표의 풍부한 자연스러운 상품명",
  "small_medium_keywords": ["중소형 키워드1", "중소형 키워드2", "중소형 키워드3"]
}}
"""
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.4
        )
        data = json.loads(response.choices[0].message.content)
        
        t50 = clean_and_validate_title(data.get("title_50byte", ""))
        t100 = clean_and_validate_title(data.get("title_100byte", ""))
        
        data["title_50byte_clean"] = truncate_by_byte(t50, 50)
        data["title_100byte_clean"] = truncate_by_byte(t100, 100)
        
        return data
    except Exception as e:
        return {
            "title_50byte_clean": f"에러 발생: {str(e)}",
            "title_100byte_clean": "",
            "small_medium_keywords": []
        }

def calculate_margin(sourcing_price_foreign, curr_symbol, target_sell_price_krw, ex_rate, usd_rate, ship_cost, extra):
    sourcing_cost_krw = sourcing_price_foreign * ex_rate
    price_in_usd = (sourcing_cost_krw / usd_rate) if usd_rate > 0 else 0.0
    
    if price_in_usd > 150.0:
        customs_duty = sourcing_cost_krw * 0
