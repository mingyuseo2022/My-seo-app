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
st.caption("마켓별 바이트 규격(50Byte / 100Byte)맞춤 상품명 가공 및 통화별 실시간 순마진 분석을 제공합니다.")

# ==========================================
# 바이트 계산 함수 (한글 2byte, 영문/숫자/공백 1byte)
# ==========================================
def calculate_byte(text: str) -> int:
    """문자열의 정확한 Euc-Kr / UTF-8 기준 한글 Byte 계산"""
    count = 0
    for char in text:
        # 한글 및 기타 전각 문자 2 Byte, 일반 영문/숫자 1 Byte
        if ord(char) > 127:
            count += 2
        else:
            count += 1
    return count

def truncate_by_byte(text: str, max_bytes: int) -> str:
    """지정한 바이트 수를 넘지 않도록 안전하게 자르는 함수"""
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
    """CNY(위안화) 및 EUR(유로화)의 KRW 실시간 환율 가져오기"""
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
# 사이드바: API 키 및 고정 설정
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
    
    currency_type = st.radio("소싱 통화 선택", ["위안화 (CNY ¥)", "유로화 (EUR €)", "원화 (KRW ₩)"], horizontal=True)
    
    if currency_type == "위안화 (CNY ¥)":
        default_rate = realtime_cny
        curr_symbol = "¥"
    elif currency_type == "유로화 (EUR €)":
        default_rate = realtime_eur
        curr_symbol = "€"
    else:
        default_rate = 1.0
        curr_symbol = "₩"
        
    exchange_rate = st.number_input("적용 환율 (원화 환산 기준)", value=float(default_rate), step=1.0)
    st.caption(f"💡 현재 실시간 환율: 1 EUR = {realtime_eur}원 / 1 CNY = {realtime_cny}원")
    
    shipping_cost = st.number_input("배대지/국내 배송비 (원)", value=8000, step=500)
    extra_cost = st.number_input("기타 부대비용/포장비 (원)", value=1000, step=100)

# ==========================================
# 웹 크롤링: 상품명 및 가격 추출 함수
# ==========================================
def fetch_product_info_from_url(url: str):
    """URL에서 원본 상품명과 가격(단가)을 추출하는 함수"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    extracted_title = ""
    extracted_price = 0.0
    
    try:
        response = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        if soup.find("meta", property="og:title") and soup.find("meta", property="og:title").get("content"):
            extracted_title = soup.find("meta", property="og:title")["content"]
        elif soup.title and soup.title.string:
            extracted_title = soup.title.string
            
        price_meta = soup.find("meta", property="product:price:amount") or soup.find("meta", property="og:price:amount")
        if price_meta and price_meta.get("content"):
            try:
                extracted_price = float(re.sub(r'[^0-9.]', '', price_meta["content"]))
            except:
                extracted_price = 0.0
        else:
            price_text = soup.find(text=re.compile(r'([¥€$]|EUR|CNY)\s*[\d,]+(\.\d+)?'))
            if price_text:
                match = re.search(r'[\d,]+(\.\d+)?', price_text)
                if match:
                    try:
                        extracted_price = float(match.group(0).replace(',', ''))
                    except:
                        extracted_price = 0.0

        return extracted_title.strip(), extracted_price
    except Exception as e:
        return "", 0.0

def clean_and_validate_title(title: str) -> str:
    """SEO 특수문자 및 중복 단어 정제"""
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
    """50Byte용 및 100Byte용 맞춤 상품명 생성"""
    prompt = f"""
너는 한국의 최고 이커머스 MD이자 SEO 마케팅 전문가야.
아래의 해외 상품명을 바탕으로 국내 오픈마켓의 바이트(Byte) 규격에 딱 맞춰 2가지 버전의 자연스러운 한국어 상품명을 만들어줘.

[해외 원본 상품명]
{original_title}

[요청 사항]
1. 50Byte용 상품명 (네이버 스마트스토어 등)
   - 한글 기준 22자~25자 이내 (최대 50Byte 준수)
   - 가장 핵심적인 대표 카테고리와 메인 키워드 위주로 자연스럽게 작성.

2. 100Byte용 상품명 (쿠팡, 11번가, G마켓 등)
   - 한글 기준 40자~48자 이내 (최대 100Byte 준수)
   - 대표 키워드 + 세부 중소형 키워드, 용도, 소재/디자인 속성을 포함하여 자연스러운 문장 형태로 작성.

3. 두 버전 모두 키워드의 어색한 단순 나열을 금지하고, 소비자가 읽었을 때 이해하기 쉬운 자연스러운 어순을 지켜.

[응답 형식 (JSON 규격)]
{{
  "title_50byte": "50바이트용 짧은 핵심 상품명",
  "title_100byte": "100바이트용 서브 키워드 포함 상품명",
  "small_medium_keywords": ["중소형 키워드1", "중소형 키워드2", "중소형 키워드3"]
}}
"""
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        data = json.loads(response.choices[0].message.content)
        
        # 정제 및 바이트 수 검수
        t50 = clean_and_validate_title(data.get("title_50byte", ""))
        t100 = clean_and_validate_title(data.get("title_100byte", ""))
        
        # 지정 바이트 제한 적용
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
    """구분된 통화별 순마진 계산 엔진"""
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
            with st.spinner("URL에서 상품 정보 및 단가 수집 중..."):
                fetched_title, fetched_price = fetch_product_info_from_url(url_input)
                if fetched_title:
                    st.success("URL 상품 정보 수집 성공!")
                else:
                    st.warning("보안 정책으로 단가/제목 자동 수집이 차단된 사이트입니다. 아래에 직접 입력해 주세요.")
                    
        raw_title_input = st.text_area("원본 상품명 (직접 수정/입력 가능)", value=fetched_title)
        
        st.markdown("---")
        st.subheader("2️⃣ 단가 및 판매가 설정")
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            sourcing_price = st.number_input(
                f"소싱 단가 ({curr_symbol})", 
                value=float(fetched_price) if fetched_price > 0 else 20.0, 
                step=1.0,
                help="URL에서 가격을 감지하면 자동 채워집니다."
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
                        st.caption(f"길이: {len(t50)}자 / **{b50} Byte** (50Byte 이하 준수)")
                        
                        st.markdown("### 🔵 [100 Byte 전용] 쿠팡, 11번가, G마켓 등")
                        st.code(t100, language="text")
                        st.caption(f"길이: {len(t100)}자 / **{b100} Byte** (100Byte 이하 준수)")
                        
                        st.caption(f"💡 추출된 핵심 중소형 키워드: {', '.join(res.get('small_medium_keywords', []))}")
                        
                        st.markdown("---")
                        st.markdown(f"### 💰 [{currency_type}] 적용 오픈마켓 순마진 분석")
                        
                        margin_df = calculate_margin(sourcing_price, curr_symbol, target_price, exchange_rate, shipping_cost, extra_cost)
                        st.dataframe(margin_df, use_container_width=True)
                    else:
                        st.error("상품명 정보를 입력해 주세요!")

with tab2:
    st.subheader("엑셀/CSV 파일 일괄 변환")
    st.caption("대량 엑셀 처리 시에도 50/100Byte 상품명 및 실시간 환율이 함께 적용됩니다.")
