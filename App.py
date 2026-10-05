import io
import json
import re
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
import openai

# ==========================================
# 1. 페이지 설정
# ==========================================
st.set_page_config(
    page_title="SellOmni Pro - 커머스 SEO & 마진 솔루션",
    page_icon="🚀",
    layout="wide"
)

# ==========================================
# 2. 핵심 연산 및 유틸리티 함수
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
    """지정한 바이트를 넘지 않도록 절삭"""
    current_bytes = 0
    truncated_text = ""
    for char in text:
        char_byte = 2 if ord(char) > 127 else 1
        if current_bytes + char_byte > max_bytes:
            break
        current_bytes += char_byte
        truncated_text += char
    return truncated_text.strip()

@st.cache_data(ttl=3600)
def get_realtime_exchange_rates():
    """실시간 환율 수집"""
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        res = requests.get(url, timeout=5)
        data = res.json()
        usd_krw = data["rates"]["KRW"]
        usd_eur = data["rates"]["EUR"]
        usd_cny = data["rates"]["CNY"]
        eur_krw = usd_krw / usd_eur if usd_eur else 1480.0
        cny_krw = usd_krw / usd_cny if usd_cny else 195.0
        return round(usd_krw, 2), round(eur_krw, 2), round(cny_krw, 2)
    except Exception:
        return 1380.0, 1480.0, 195.0

realtime_usd, realtime_eur, realtime_cny = get_realtime_exchange_rates()

def fetch_product_info_from_url(url: str):
    """URL에서 정보 추출"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    title = ""
    price = 0.0
    curr = "CNY"
    try:
        session = requests.Session()
        res = session.get(url, headers=headers, timeout=10, allow_redirects=True)
        final_url = res.url.lower()
        
        if "amazon.de" in final_url or ".de" in final_url or ".eu" in final_url:
            curr = "EUR"
        elif "taobao" in final_url or "1688" in final_url or "tmall" in final_url:
            curr = "CNY"
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        t_tag = soup.find(id="productTitle") or soup.find("meta", property="og:title")
        if t_tag:
            title = t_tag.get("content", "") if t_tag.name == "meta" else t_tag.get_text()
        elif soup.title and soup.title.string:
            title = soup.title.string
            
        p_span = soup.find("span", class_="a-offscreen") or soup.find("span", id="priceblock_ourprice")
        if p_span:
            p_text = p_span.get_text().replace(',', '.').replace('€', '').replace('¥', '').strip()
            match = re.search(r'[\d.]+', p_text)
            if match:
                price = float(match.group(0))
        return title.strip(), price, curr
    except Exception:
        return "", 0.0, "CNY"

def clean_title(title: str) -> str:
    cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
    words = cleaned.split()
    seen = set()
    unique = []
    for w in words:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return " ".join(unique).strip()

def process_seo_title_by_bytes(client: openai.OpenAI, original_title: str, model_name: str) -> dict:
    prompt = f"""
너는 한국 최고의 이커머스 MD이자 SEO 전문가야.
아래 해외 상품명을 국내 오픈마켓 규격에 맞춰 2가지 버전으로 자연스럽게 작성해 줘.

[해외 원본 상품명]
{original_title}

[규칙]
1. 50Byte 전용 (스마트스토어용): 44~50Byte 목표 (한글 22~25자 꽉 채움)
2. 100Byte 전용 (쿠팡/11번가/G마켓용): 88~100Byte 목표 (한글 44~50자 꽉 채움)
3. 어색한 단어 나열 금지, 자연스러운 어순 유지.

[JSON 응답]
{{
  "title_50byte": "50바이트 목표 상품명",
  "title_100byte": "100바이트 목표 상품명",
  "small_medium_keywords": ["키워드1", "키워드2", "키워드3"]
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
        t50 = clean_title(data.get("title_50byte", ""))
        t100 = clean_title(data.get("title_100byte", ""))
        data["title_50byte_clean"] = truncate_by_byte(t50, 50)
        data["title_100byte_clean"] = truncate_by_byte(t100, 100)
        return data
    except Exception as e:
        return {
            "title_50byte_clean": f"오류: {str(e)}",
            "title_100byte_clean": "",
            "small_medium_keywords": []
        }

def calculate_margin(sourcing_price, curr_symbol, target_price, ex_rate, usd_rate, ship_cost, extra):
    cost_krw = sourcing_price * ex_rate
    price_usd = (cost_krw / usd_rate) if usd_rate > 0 else 0.0
    
    if price_usd > 150.0:
        duty = cost_krw * 0.08
        vat = (cost_krw + duty) * 0.10
        duty_tax = duty + vat
        duty_text = f"{int(duty_tax):,}원 (과세: ${price_usd:.1f})"
    else:
        duty_tax = 0.0
        duty_text = f"0원 (면세: ${price_usd:.1f})"
        
    total_cost = cost_krw + duty_tax + ship_cost + extra
    
    fee_rates = {
        "네이버 스마트스토어 (약 5.63%)": 0.0563,
        "쿠팡 (약 10.8%)": 0.1080,
        "11번가 / G마켓 (약 13%)": 0.1300
    }
    
    results = []
    for market, fee_rate in fee_rates.items():
        fee = target_price * fee_rate
        net_profit = target_price - total_cost - fee
        margin_rate = (net_profit / target_price * 100) if target_price > 0 else 0
        
        results.append({
            "오픈마켓": market,
            f"현지 원가 ({curr_symbol})": f"{sourcing_price:,.2f} {curr_symbol}",
            "한화 원가": f"{int(cost_krw):,}원",
            "관부가세": duty_text,
            "총 매입원가": f"{int(total_cost):,}원",
            "예상 판매가": f"{int(target_price):,}원",
            "마켓 수수료": f"{int(fee):,}원",
            "순마진(수익)": f"{int(net_profit):,}원",
            "순마진율(%)": f"{margin_rate:.1f}%"
        })
    return pd.DataFrame(results), total_cost, duty_tax

# ==========================================
# 3. 사이드바 UI
# ==========================================
default_api_key = st.secrets.get("OPENAI_API_KEY", "")

with st.sidebar:
    st.title("⚡ SellOmni Pro")
    st.caption("Cross-border E-commerce Suite")
    st.markdown("---")
    
    api_key = st.text_input("OpenAI API Key", value=default_api_key, type="password")
    model_choice = st.selectbox("AI 모델", ["gpt-4o-mini", "gpt-4o"], index=0)
    
    st.markdown("---")
    currency_type = st.radio("소싱 통화", ["위안화 (CNY ¥)", "유로화 (EUR €)", "원화 (KRW ₩)"], horizontal=True)
    
    if "유로화" in currency_type:
        default_rate = realtime_eur
        curr_symbol = "€"
    elif "위안화" in currency_type:
        default_rate = realtime_cny
        curr_symbol = "¥"
    else:
        default_rate = 1.0
        curr_symbol = "₩"
        
    exchange_rate = st.number_input("적용 환율", value=float(default_rate), step=1.0)
    shipping_cost = st.number_input("배송비 (원)", value=12000 if "EUR" in curr_symbol else 8000, step=500)
    extra_cost = st.number_input("기타 부대비용 (원)", value=1000, step=100)

# ==========================================
# 4. 메인 UI
# ==========================================
st.title("⚡ SellOmni Pro :: AI SEO & 마진 분석기")
st.caption("해외 소싱 상품의 최적 SEO 제목 추출부터 $150 관부가세 자동 감지 마진 정산까지")

st.markdown("---")

col_left, col_right = st.columns([1, 1], gap="medium")

with col_left:
    st.subheader("1️⃣ 소싱 데이터 입력")
    url_val = st.text_input("소싱처 URL 입력", placeholder="https://amazon.de 또는 https://detail.1688.com...")
    
    fetched_title = ""
    fetched_price = 0.0
    
    if url_val:
        with st.spinner("URL 분석 중..."):
            fetched_title, fetched_price, detected_curr = fetch_product_info_from_url(url_val)
            
    raw_title = st.text_area("원본 상품명", value=fetched_title, height=100)
    
    st.markdown("---")
    st.subheader("2️⃣ 단가 및 목표 판매가")
    
    c_p1, c_p2 = st.columns(2)
    with c_p1:
        sourcing_price = st.number_input(f"소싱 단가 ({curr_symbol})", value=float(fetched_price) if fetched_price > 0 else 20.0, step=1.0)
    with c_p2:
        target_price = st.number_input("목표 판매가 (KRW ₩)", value=49000, step=1000)

    run_analysis = st.button("📊 마진 및 SEO 분석 실행", type="primary", use_container_width=True)

with col_right:
    st.subheader("3️⃣ 실시간 분석 리포트")
    
    if run_analysis:
        if not api_key:
            st.error("좌측 사이드바에 OpenAI API Key를 등록해 주세요.")
        else:
            client = openai.OpenAI(api_key=api_key)
            
            with st.spinner("SEO 최적화 및 마진 계산 중..."):
                orig_title = raw_title if raw_title else fetched_title
                
                if orig_title:
                    res = process_seo_title_by_bytes(client, orig_title, model_choice)
                    
                    t50 = res.get("title_50byte_clean", "")
                    t100 = res.get("title_100byte_clean", "")
                    b50 = calculate_byte(t50)
                    b100 = calculate_byte(t100)
                    
                    margin_df, total_cost, duty_tax = calculate_margin(
                        sourcing_price, curr_symbol, target_price, exchange_rate, realtime_usd, shipping_cost, extra_cost
                    )
                    
                    m1, m2 = st.columns(2)
                    with m1:
                        st.metric("총 매입 원가 (배송/세금 포함)", f"{int(total_cost):,}원")
                    with m2:
                        st.metric("적용 관부가세", f"{int(duty_tax):,}원")
                    
                    st.markdown("---")
                    st.markdown("#### 🟢 스마트스토어 전용 (50 Byte)")
                    st.code(t50, language="text")
                    st.caption(f"바이트 규격: **{b50} / 50 Byte**")
                    
                    st.markdown("#### 🔵 쿠팡 / 11번가 / G마켓 전용 (100 Byte)")
                    st.code(t100, language="text")
                    st.caption(f"바이트 규격: **{b100} / 100 Byte**")
                    
                    st.markdown("---")
                    st.markdown("#### 💰 마켓별 최종 순마진 정산")
                    st.dataframe(margin_df, use_container_width=True, hide_index=True)
                else:
                    st.warning("상품명 정보 또는 URL을 입력해 주세요.")
    else:
        st.info("👈 상품 정보를 입력한 후 [📊 마진 및 SEO 분석 실행] 버튼을 눌러주세요.")
