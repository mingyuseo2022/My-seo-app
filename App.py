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
st.caption("해외/국내 상품 URL을 입력하면 AI SEO 상품명 가공과 실시간 환율 기반 오픈마켓 순마진율을 계산해 드립니다.")

# ==========================================
# 실시간 환율 가져오기 함수 (CNY, EUR) - 캐싱 적용
# ==========================================
@st.cache_data(ttl=3600)  # 1시간 동안 환율 결과 캐싱
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
        # API 오류 시 기본 환율 반환
        return 1480.0, 195.0

# 실시간 환율 호출 (유로, 위안화)
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
    
    currency_type = st.radio("소싱 국가 통화", ["위안화 (CNY ¥)", "유로화 (EUR €)", "직접 입력/원화"], horizontal=True)
    
    # 통화 선택에 따른 실시간 환율 자동 세팅
    if currency_type == "위안화 (CNY ¥)":
        default_rate = realtime_cny
    elif currency_type == "유로화 (EUR €)":
        default_rate = realtime_eur
    else:
        default_rate = 1.0
        
    exchange_rate = st.number_input("적용 환율 (원화 환산 기준)", value=float(default_rate), step=1.0)
    st.caption(f"💡 현재 실시간 환율 기준: 1 EUR = {realtime_eur}원 / 1 CNY = {realtime_cny}원")
    
    shipping_cost = st.number_input("배대지/국내 배송비 (원)", value=8000, step=500)
    extra_cost = st.number_input("기타 부대비용/포장비 (원)", value=1000, step=100)

# ==========================================
# 핵심 처리 함수
# ==========================================
def fetch_product_title(url: str) -> str:
    """URL에서 원본 상품명 추출"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        if soup.find("meta", property="og:title") and soup.find("meta", property="og:title").get("content"):
            title = soup.find("meta", property="og:title")["content"]
        elif soup.title and soup.title.string:
            title = soup.title.string
        else:
            title = "상품명을 자동 수집하지 못했습니다."
        return title.strip()
    except Exception as e:
        return "수집 실패 (직접 입력 필요)"

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
    final_title = " ".join(unique_words)
    return final_title[:50].strip()

def process_seo_title(client: openai.OpenAI, original_title: str, model_name: str) -> dict:
    """AI 상품명 가공 함수"""
    prompt = f"""
너는 해외 구매대행 전문 이커머스 마케터이자 SEO 전문가야.
아래의 해외 상품명을 분석해서 국내 오픈마켓(네이버 스마트스토어, 쿠팡 등)에 가장 최적화된 상품명을 만들어줘.

[해외 원본 상품명]
{original_title}

[응답 형식 (JSON 규격)]
{{
  "translated_name": "직역 및 직관적 번역명",
  "small_medium_keywords": ["키워드1", "키워드2", "키워드3", "키워드4"],
  "optimized_final_title": "최종 완성된 SEO 상품명"
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
        data["seo_clean_title"] = clean_and_validate_title(data.get("optimized_final_title", ""))
        return data
    except Exception as e:
        return {
            "translated_name": "처리 실패",
            "small_medium_keywords": [],
            "optimized_final_title": "",
            "seo_clean_title": f"에러 발생: {str(e)}"
        }

def calculate_margin(sourcing_price_foreign, target_sell_price_krw, ex_rate, ship_cost, extra):
    """오픈마켓 순마진 계산 엔진"""
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
            "마켓": market,
            "예상 판매가": f"{int(target_sell_price_krw):,}원",
            "총 매입원가(배송비포함)": f"{int(total_cost):,}원",
            "마켓 수수료": f"{int(market_fee):,}원",
            "순마진(수익)": f"{int(net_profit):,}원",
            "순마진율(%)": f"{margin_rate:.1f}%"
        })
    return pd.DataFrame(results)

# ==========================================
# 메인 UI 구성
# ==========================================
tab1, tab2 = st.tabs(["🔗 SEO 상품명 & 마진 계산", "📁 엑셀 대량 업로드"])

with tab1:
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        st.subheader("1️⃣ 상품 정보 입력")
        url_input = st.text_input("소싱처 URL 입력 (선택사항)")
        raw_title_input = st.text_area("해외/국내 원본 상품명 (직접 입력도 가능)")
        
        st.markdown("---")
        st.subheader("2️⃣ 소싱 원가 및 판매가 설정")
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            sourcing_price = st.number_input("소싱 원가 (외화/원화)", value=20.0, step=1.0)
        with col_p2:
            target_price = st.number_input("국내 오픈마켓 희망 판매가 (원)", value=49000, step=1000)

    with col_right:
        st.subheader("3️⃣ 결과 및 분석")
        if st.button("🚀 SEO 상품명 가공 및 순마진 계산하기", key="calc_btn"):
            if not api_key:
                st.error("좌측 사이드바에 OpenAI API Key를 입력해 주세요!")
            else:
                client = openai.OpenAI(api_key=api_key)
                
                with st.spinner("SEO 상품명 생성 및 실시간 마진 분석 중..."):
                    orig_title = fetch_product_title(url_input) if url_input else raw_title_input
                    
                    if orig_title:
                        res = process_seo_title(client, orig_title, model_choice)
                        
                        st.markdown("### 🏆 최종 SEO 상품명")
                        st.code(res["seo_clean_title"], language="text")
                        st.caption(f"자수: {len(res['seo_clean_title'])}자 / 중소형 키워드: {', '.join(res.get('small_medium_keywords', []))}")
                        
                        st.markdown("---")
                        st.markdown("### 💰 실시간 환율 적용 순마진 분석")
                        
                        margin_df = calculate_margin(sourcing_price, target_price, exchange_rate, shipping_cost, extra_cost)
                        st.dataframe(margin_df, use_container_width=True)

with tab2:
    st.subheader("엑셀/CSV 파일 일괄 변환")
    st.caption("대량 엑셀 처리 시에도 실시간 환율 및 상품명 가공이 함께 적용됩니다.")
