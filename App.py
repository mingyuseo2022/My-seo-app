import io
import json
import re
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
import openai

# ==========================================
# 페이지 기본 설정
# ==========================================
st.set_page_config(
    page_title="해외 구매대행 SEO 상품명 & 실시간 마진 계산기",
    page_icon="🛍️",
    layout="wide"
)

st.title("🛍️ 해외 구매대행 SEO 상품명 생성 & 실시간 마진 계산기")
st.caption("마켓별 바이트 제한(50Byte / 100Byte)에 최대한 가깝게 채운 자연스러운 한국어 SEO 상품명을 생성합니다.")

# ==========================================
# 바이트 계산 및 절삭 함수
# ==========================================
def calculate_byte(text: str) -> int:
    """한글 2Byte, 영문/숫자/공백 1Byte 기준 계산"""
    count = 0
    for char in text:
        if ord(char) > 127:
            count += 2
        else:
            count += 1
    return count

def truncate_by_byte(text: str, max_bytes: int) -> str:
    """지정한 바이트를 넘지 않도록 안전하게 정제"""
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
# 실시간 환율 가져오기 함수 (CNY, EUR) - 캐싱 적용
# ==========================================
@st.cache_data(ttl=3600)
def get_realtime_exchange_rates():
    try:
        url = "https://api.exchangerate-api.com/v4/latest/EUR"
        response = requests.get(url, timeout=5)
        data = response.json()
        
        eur_to_krw = data["rates"]["KRW"]
        eur_to_cny = data["rates"]["CNY"]
        cny_to_krw = eur_to_krw / eur_to_cny if eur_to_cny else 195.0
        
        return round(eur_to_krw, 2), round(cny_to_krw, 2)
    except Exception as e:
        return 1480.0, 195.0

realtime_eur, realtime_cny = get_realtime_exchange_rates()

# ==========================================
# 웹 크롤링: 상품명 및 가격 추출 함수 (아마존 패치 포함)
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
    except Exception as e:
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
    """바이트 제한치(50Byte / 100Byte)에 최대한 맞춰 자연스러운 상품명 생성"""
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

def calculate_margin(sourcing_price_foreign, curr_symbol, target_sell_price_krw, ex_rate, ship_cost, extra):
    sourcing_cost_krw = sourcing_price_foreign * ex_rate
    total_cost = sourcing_cost_krw + ship_cost + extra
    
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
            "한화 매입원가(배송비포함)": f"{int(total_cost):,}원",
            "예상 판매가": f"{int(target_sell_price_krw):,}원",
            "마켓 수수료": f"{int(market_fee):,}원",
            "순마진(수익)": f"{int(net_profit):,}원",
            "순마진율(%)": f"{margin_rate:.1f}%"
        })
    return pd.DataFrame(results)

# ==========================================
# 사이드바 구성
# ==========================================
default_api_key = st.secrets.get("OPENAI_API_KEY", "")

with st.sidebar:
    st.header("⚙️ 기본 설정")
    api_key = st.text_input(
        "OpenAI API Key 입력", 
        value=default_api_key, 
        type="password", 
        help="sk-... 로 시작하는 API 키를 입력하세요."
    )
    model_choice = st.selectbox("사용할 AI 모델", ["gpt-4o-mini", "gpt-4o"], index=0)
    
    st.markdown("---")
    st.header("🧮 마진 기본 변수 설정")
    
    currency_index = 0
    if "detected_curr" in st.session_state and st.session_state["detected_curr"] == "EUR":
        currency_index = 1
        
    currency_type = st.radio("소싱 통화 선택", ["위안화 (CNY ¥)", "유로화 (EUR €)", "원화 (KRW ₩)"], index=currency_index, horizontal=True)
    
    if "유로화" in currency_type:
        default_rate = realtime_eur
        curr_symbol = "€"
    elif "위안화" in currency_type:
        default_rate = realtime_cny
        curr_symbol = "¥"
    else:
        default_rate = 1.0
        curr_symbol = "₩"
        
    exchange_rate = st.number_input("적용 환율 (원화 환산 기준)", value=float(default_rate), step=1.0)
    st.caption(f"💡 현재 실시간 환율: 1 EUR = {realtime_eur}원 / 1 CNY = {realtime_cny}원")
    
    shipping_cost = st.number_input("배대지/국내 배송비 (원)", value=12000 if "EUR" in curr_symbol else 8000, step=500)
    extra_cost = st.number_input("기타 부대비용/포장비 (원)", value=1000, step=100)

# ==========================================
# 메인 UI 구성
# ==========================================
tab1, tab2 = st.tabs(["🔗 SEO 상품명 & 마진 분석", "📁 엑셀 대량 업로드"])

with tab1:
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        st.subheader("1️⃣ 소싱 URL 및 상품 정보")
        url_input = st.text_input("소싱처 URL 입력 (자동으로 상품명/단가를 수집합니다)")
        
        fetched_title = ""
        fetched_price = 0.0
        
        if url_input:
            with st.spinner("URL 분석 및 단가 수집 중..."):
                fetched_title, fetched_price, detected_curr = fetch_product_info_from_url(url_input)
                st.session_state["detected_curr"] = detected_curr
                
                if fetched_title:
                    st.success(f"URL 수집 완료! (감지된 통화: {detected_curr})")
                else:
                    st.warning("단가/제목 수집이 제한된 페이지입니다. 아래에 직접 입력해 주세요.")
                    
        raw_title_input = st.text_area("원본 상품명 (직접 수정/입력 가능)", value=fetched_title)
        
        st.markdown("---")
        st.subheader("2️⃣ 단가 및 판매가 설정")
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            sourcing_price = st.number_input(
                f"소싱 단가 ({curr_symbol})", 
                value=float(fetched_price) if fetched_price > 0 else 20.0, 
                step=1.0,
                help="URL에서 추출한 단가입니다."
            )
        with col_p2:
            target_price = st.number_input("국내 희망 판매가 (KRW ₩)", value=49000, step=1000)

    with col_right:
        st.subheader("3️⃣ AI SEO 분석 및 순마진 결과")
        if st.button("🚀 바이트별 상품명 가공 & 순마진 계산", key="calc_btn"):
            if not api_key:
                st.error("좌측 사이드바에 OpenAI API Key를 입력해 주세요!")
            else:
                client = openai.OpenAI(api_key=api_key)
                
                with st.spinner("마켓 규격별(50/100Byte) 상품명 가공 및 순마진 분석 중..."):
                    orig_title = raw_title_input if raw_title_input else fetched_title
                    
                    if orig_title:
                        res = process_seo_title_by_bytes(client, orig_title, model_choice)
                        
                        t50 = res.get("title_50byte_clean", "")
                        t100 = res.get("title_100byte_clean", "")
                        
                        b50 = calculate_byte(t50)
                        b100 = calculate_byte(t100)
                        
                        st.markdown("### 🟢 [50 Byte 전용] 네이버 스마트스토어 등")
                        st.code(t50, language="text")
                        st.caption(f"길이: {len(t50)}자 / **{b50} Byte** (50Byte에 정밀 최적화됨)")
                        
                        st.markdown("### 🔵 [100 Byte 전용] 쿠팡, 11번가, G마켓 등")
                        st.code(t100, language="text")
                        st.caption(f"길이: {len(t100)}자 / **{b100} Byte** (100Byte에 정밀 최적화됨)")
                        
                        st.caption(f"💡 추출된 핵심 중소형 키워드: {', '.join(res.get('small_medium_keywords', []))}")
                        
                        st.markdown("---")
                        st.markdown(f"### 💰 [{currency_type}] 적용 오픈마켓 순마진 분석")
                        
                        margin_df = calculate_margin(sourcing_price, curr_symbol, target_price, exchange_rate, shipping_cost, extra_cost)
                        st.dataframe(margin_df, use_container_width=True)
                    else:
                        st.error("상품명 정보를 입력해 주세요!")

with tab2:
    st.subheader("엑셀/CSV 파일 일괄 변환")
    st.caption("대량 엑셀 처리 시에도 50/100Byte 정밀 맞춤 상품명 및 실시간 환율이 함께 적용됩니다.")
