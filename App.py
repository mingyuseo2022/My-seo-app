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
# 옵션을 unsafe_allow_html=True 로 정확히 수정했습니다.
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
        customs_duty = sourcing_cost_krw * 0.08
        vat = (sourcing_cost_krw + customs_duty) * 0.10
        duty_tax_krw = customs_duty + vat
        duty_status_text = f"{int(duty_tax_krw):,}원 (과세: ${price_in_usd:.1f})"
    else:
        duty_tax_krw = 0.0
        duty_status_text = f"0원 (면세: ${price_in_usd:.1f})"
    
    total_cost = sourcing_cost_krw + duty_tax_krw + ship_cost + extra
    
    fee_rates = {
        "네이버 스마트스토어 (약 5.63%)": 0.0563,
        "쿠팡 (약 10.8%)": 0.1080,
        "11번가 / G마켓 (약 13%)": 0.1300
    }
    
    results = []
    for market, fee_rate in fee_rates.items():
        market_fee = target_sell_price_krw * fee_rate
        net_profit = target_sell_price_krw - total_cost - market_fee
        margin_rate = (net_profit / target_sell_price_krw * 100) if target_sell_price_krw > 0 else 0
        
        results.append({
            "오픈마켓": market,
            f"현지 원가 ({curr_symbol})": f"{sourcing_price_foreign:,.2f} {curr_symbol}",
            "한화 원가": f"{int(sourcing_cost_krw):,}원",
            "관부가세": duty_status_text,
            "총 매입원가": f"{int(total_cost):,}원",
            "예상 판매가": f"{int(target_sell_price_krw):,}원",
            "마켓 수수료": f"{int(market_fee):,}원",
            "순마진(수익)": f"{int(net_profit):,}원",
            "순마진율(%)": f"{margin_rate:.1f}%"
        })
    return pd.DataFrame(results), total_cost, duty_tax_krw

# ==========================================
# 사이드바 구성
# ==========================================
default_api_key = st.secrets.get("OPENAI_API_KEY", "")

with st.sidebar:
    st.image("https://img.icons8.com/color/96/lightning-bolt.png", width=50)
    st.title("SellOmni Pro")
    st.caption("Cross-border E-commerce Suite")
    st.markdown("---")
    
    st.subheader("⚙️ API 및 모델 설정")
    api_key = st.text_input(
        "OpenAI API Key", 
        value=default_api_key, 
        type="password", 
        help="API Key를 등록하면 세션 동안 유지됩니다."
    )
    model_choice = st.selectbox("AI 엔진 선택", ["gpt-4o-mini", "gpt-4o"], index=0)
    
    st.markdown("---")
    st.subheader("🧮 마진 파라미터")
    
    currency_index = 0
    if "detected_curr" in st.session_state and st.session_state["detected_curr"] == "EUR":
        currency_index = 1
        
    currency_type = st.radio("소싱 통화", ["위안화 (CNY ¥)", "유로화 (EUR €)", "원화 (KRW ₩)"], index=currency_index, horizontal=True)
    
    if "유로화" in currency_type:
        default_rate = realtime_eur
        curr_symbol = "€"
    elif "위안화" in currency_type:
        default_rate = realtime_cny
        curr_symbol = "¥"
    else:
        default_rate = 1.0
        curr_symbol = "₩"
        
    exchange_rate = st.number_input("적용 환율 (원화)", value=float(default_rate), step=1.0)
    
    shipping_cost = st.number_input("배대지/내륙 배송비 (원)", value=12000 if "EUR" in curr_symbol else 8000, step=500)
    extra_cost = st.number_input("포장 및 기타 부대비용 (원)", value=1000, step=100)

# ==========================================
# 메인 헤더
# ==========================================
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("⚡ SellOmni Pro :: AI SEO & 마진 분석기")
    st.caption("해외 소싱 상품의 최적 SEO 제목 추출부터 $150 관부가세 자동 감지 마진 정산까지 한눈에")
with col_h2:
    st.metric(label="실시간 EUR 환율", value=f"{realtime_eur}원")

st.markdown("---")

# ==========================================
# 초기화 버튼 세션 로직
# ==========================================
if "input_url" not in st.session_state:
    st.session_state["input_url"] = ""
if "input_title" not in st.session_state:
    st.session_state["input_title"] = ""
if "input_price" not in st.session_state:
    st.session_state["input_price"] = 20.0

def reset_fields():
    st.session_state["input_url"] = ""
    st.session_state["input_title"] = ""
    st.session_state["input_price"] = 20.0
    if "detected_curr" in st.session_state:
        del st.session_state["detected_curr"]

# ==========================================
# 메인 레이아웃 (2 칼럼)
# ==========================================
col_left, col_right = st.columns([1.1, 1], gap="medium")

with col_left:
    st.subheader("1️⃣ 소싱 데이터 입력")
    
    url_val = st.text_input("소싱처 URL 입력", value=st.session_state["input_url"], key="url_widget", placeholder="https://amazon.de 또는 https://detail.1688.com...")
    
    fetched_title = ""
    fetched_price = 0.0
    
    if url_val and url_val != st.session_state.get("last_url", ""):
        with st.spinner("URL 데이터 파싱 중..."):
            fetched_title, fetched_price, detected_curr = fetch_product_info_from_url(url_val)
            st.session_state["detected_curr"] = detected_curr
            st.session_state["last_url"] = url_val
            if fetched_title:
                st.session_state["input_title"] = fetched_title
            if fetched_price > 0:
                st.session_state["input_price"] = fetched_price
                
    raw_title = st.text_area("원본 상품명", value=st.session_state["input_title"], height=100, key="title_widget")
    
    st.markdown("---")
    st.subheader("2️⃣ 단가 및 목표 판매가")
    
    c_p1, c_p2 = st.columns(2)
    with c_p1:
        sourcing_price = st.number_input(f"소싱 단가 ({curr_symbol})", value=float(st.session_state["input_price"]), step=1.0)
    with c_p2:
        target_price = st.number_input("목표 판매가 (KRW ₩)", value=49000, step=1000)

    st.markdown("<br>",
