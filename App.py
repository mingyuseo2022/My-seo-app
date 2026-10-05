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
    page_title="해외 구매대행 SEO 상품명 자동 생성기",
    page_icon="🛍️",
    layout="wide"
)

st.title("🛍️ 해외 구매대행 상품명 번역 & SEO 키워드 생성기")
st.caption("해외 상품 URL을 입력하거나 엑셀로 일괄 업로드하면 AI가 한국어 번역 및 중소형 SEO 키워드가 적용된 상품명을 생성합니다.")

# ==========================================
# 사이드바: API 키 및 설정
# ==========================================
# Secrets에서 API 키가 설정되어 있으면 가져오기
default_api_key = st.secrets.get("OPENAI_API_KEY", "")

with st.sidebar:
    st.header("⚙️ 설정")
    api_key = st.text_input(
        "OpenAI API Key 입력", 
        value=default_api_key, 
        type="password", 
        help="sk-... 로 시작하는 API 키를 입력하세요."
    )

    model_choice = st.selectbox("사용할 AI 모델", ["gpt-4o-mini", "gpt-4o"], index=0)
    st.markdown("---")
    st.markdown("### 💡 안내 사항")
    st.markdown("- **gpt-4o-mini**: 속도가 빠르고 비용이 저렴함 (추천)")
    st.markdown("- **gpt-4o**: 더 정교한 키워드 추출 가능")

# ==========================================
# 핵심 처리 함수
# ==========================================
def fetch_product_title(url: str) -> str:
    """URL에서 원본 상품명/페이지 타이틀 추출"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Meta og:title 또는 title 태그 가져오기
        if soup.find("meta", property="og:title") and soup.find("meta", property="og:title").get("content"):
            title = soup.find("meta", property="og:title")["content"]
        elif soup.title and soup.title.string:
            title = soup.title.string
        else:
            title = "상품명을 자동 수집하지 못했습니다."
        return title.strip()
    except Exception as e:
        return f"수집 실패 (직접 입력 필요)"

def clean_and_validate_title(title: str) -> str:
    """네이버/쿠팡 검색 알고리즘 맞춤 정제 (특수문자 및 중복 단어 제거, 50자 제한)"""
    # 1. 특수문자 제거 (한글, 영문, 숫자, 공백만 허용)
    cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
    
    # 2. 중복 단어 제거
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
    """OpenAI API를 활용한 번역 및 SEO 중소형 키워드 추출/조합"""
    prompt = f"""
너는 해외 구매대행 전문 이커머스 마케터이자 SEO 전문가야.
아래의 해외 상품명을 분석해서 국내 오픈마켓(네이버 스마트스토어, 쿠팡 등)에 가장 최적화된 상품명을 만들어줘.

[해외 원본 상품명]
{original_title}

[요청 사항]
1. 원본 상품명을 직역하지 말고 한국 소비자가 검색하는 자연스러운 한국어로 번역해.
2. 해당 상품과 밀접하지만 경쟁강도가 낮고 검색 전환율이 높은 '중소형 SEO 키워드' 3~5개를 발굴해.
3. 최종 상품명은 다음 알고리즘 규칙을 엄격히 준수해:
   - 전체 길이: 공백 포함 35자~48자 이내 (50자 초과 금지)
   - 중복 단어 포함 금지 (예: '의자 게이밍의자' X -> '게이밍 의자' O)
   - 특수문자, 괄호([]), 무료배송, 최저가 등 금지어 제외
   - 형태: [대표 카테고리명] [중소형 세부키워드 1~3] [주요 속성/소재/용도] [색상/디자인]

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

# ==========================================
# 메인 UI 탭 구성
# ==========================================
tab1, tab2 = st.tabs(["🔗 URL 단건 생성", "📁 엑셀 대량 업로드"])

# ------------------------------------------
# TAB 1: 단건 처리
# ------------------------------------------
with tab1:
    st.subheader("단일 URL / 상품명 처리")
    
    input_type = st.radio("입력 방식 선택", ["상품 URL 입력", "해외 원본 상품명 직접 입력"], horizontal=True)
    
    if input_type == "상품 URL 입력":
        url_input = st.text_input("해외 상품 URL을 입력하세요 (예: 알리익스프레스, 아마존, 타오바오 등)")
        raw_title_input = ""
    else:
        url_input = ""
        raw_title_input = st.text_area("해외 원본 상품명을 입력하세요 (영어/중국어 등)")

    if st.button("🚀 SEO 상품명 생성하기", key="single_btn"):
        if not api_key:
            st.error("좌측 사이드바에 OpenAI API Key를 먼저 입력해 주세요!")
        else:
            client = openai.OpenAI(api_key=api_key)
            
            with st.spinner("상품 정보 수집 및 AI SEO 가공 중..."):
                if url_input:
                    original_title = fetch_product_title(url_input)
                    st.info(f"**수집된 원본 상품명:** {original_title}")
                else:
                    original_title = raw_title_input
                
                if original_title:
                    res = process_seo_title(client, original_title, model_choice)
                    
                    st.success("상품명 가공 완료!")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("### 📝 자연스러운 번역명")
                        st.write(res["translated_name"])
                        st.markdown("### 🔑 발굴된 중소형 키워드")
                        st.write(", ".join(res["small_medium_keywords"]))
                        
                    with col2:
                        st.markdown("### 🏆 최종 노출용 SEO 상품명 (50자 이내 정제)")
                        st.code(res["seo_clean_title"], language="text")
                        st.caption(f"자수: {len(res['seo_clean_title'])}자 / 중복 단어 및 특수문자 검수 완료")

# ------------------------------------------
# TAB 2: 대량 엑셀 처리
# ------------------------------------------
with tab2:
    st.subheader("엑셀/CSV 파일 일괄 변환")
    st.markdown("URL 또는 해외 상품명이 담긴 엑셀(.xlsx) 파일이나 CSV 파일을 업로드하세요.")
    
    uploaded_file = st.file_uploader("파일 선택 (.xlsx 또는 .csv)", type=["xlsx", "csv"])
    
    if uploaded_file:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        st.write("▼ 업로드된 데이터 미리보기")
        st.dataframe(df.head(5))
        
        target_column = st.selectbox("URL 또는 해외 상품명이 들어있는 열(Column) 선택", df.columns)
        
        if st.button("⚡ 대량 일괄 변환 시작", key="batch_btn"):
            if not api_key:
                st.error("좌측 사이드바에 OpenAI API Key를 입력해 주세요!")
            else:
                client = openai.OpenAI(api_key=api_key)
                results = []
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_rows = len(df)
                
                for idx, row in df.iterrows():
                    val = str(row[target_column]).strip()
                    status_text.text(f"진행 중... ({idx+1}/{total_rows}): {val[:30]}...")
                    
                    if val.startswith("http://") or val.startswith("https://"):
                        orig_title = fetch_product_title(val)
                    else:
                        orig_title = val
                        
                    res = process_seo_title(client, orig_title, model_choice)
                    
                    results.append({
                        "입력 값(URL/원본명)": val,
                        "수집/인식된 원본명": orig_title,
                        "직관적 번역명": res.get("translated_name", ""),
                        "추출 중소형 키워드": ", ".join(res.get("small_medium_keywords", [])),
                        "최종 SEO 완성 상품명": res.get("seo_clean_title", "")
                    })
                    
                    progress_bar.progress((idx + 1) / total_rows)
                
                status_text.text("✅ 모든 작업이 완료되었습니다!")
                result_df = pd.DataFrame(results)
                
                st.write("▼ 변환된 결과 데이터")
                st.dataframe(result_df)
                
                # 엑셀 다운로드 생성
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    result_df.to_excel(writer, index=False, sheet_name="SEO_상품명_결과")
                excel_data = output.getvalue()
                
                st.download_button(
                    label="📥 변환 결과 엑셀 파일 다운로드",
                    data=excel_data,
                    file_name="해외구매대행_SEO상품명_결과.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
