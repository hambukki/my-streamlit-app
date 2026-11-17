
# 28번 셀: 고도화된 Streamlit 앱 (미션 3·4)
# 기존 19번 셀은 그대로 두고, 이 셀을 실행하여 app.py를 덮어씁니다.

import os
import hashlib
import tempfile
from uuid import uuid4
from operator import itemgetter

import streamlit as st
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_pymupdf4llm import PyMuPDF4LLMLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma

# 1. 기본 화면
st.set_page_config(page_title="AIVLE School 학습 도우미", page_icon="📘", layout="wide")
st.title("📘 AIVLE School 학습 도우미")
st.caption("업로드한 AIVLE School 백서에서 관련 내용을 찾아 답변합니다.")

# 2. OpenAI API Key (Cloud에서는 앱 설정 > Secrets에 등록)
# Colab의 api_key.txt는 Streamlit Cloud에 자동 전달되지 않습니다.
if not os.getenv("OPENAI_API_KEY"):
    try:
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
    except Exception:
        st.error("OPENAI_API_KEY를 설정해 주세요. Streamlit Cloud의 Secrets에 등록해야 합니다.")
        st.stop()

# 3. 검색된 문서 조각을 하나의 문자열로 연결
# 기존 28번 셀에서 누락되었던 format_docs 함수도 이곳에 포함합니다.
def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

# 4. PDF 경로를 입력하면 RAG 체인을 반환하는 함수
# 01번 노트북에서 학습한 함수의 처리 순서를 유지합니다.
def rag_pipeline(filepath):
    # PDF 로딩
    loader = PyMuPDF4LLMLoader(filepath)
    docs = loader.load()

    # 텍스트 분할: 기존 교안 설정 유지
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    chunks = splitter.split_documents(docs)
    if not chunks:
        raise ValueError("PDF에서 검색 가능한 텍스트를 찾지 못했습니다.")

    # 임베딩 + 벡터 저장소
    embedding = OpenAIEmbeddings(model="text-embedding-3-small")
    vectorstore = Chroma(
        collection_name="aivle_" + uuid4().hex[:16],
        embedding_function=embedding
    )
    # reset_collection()을 사용하지 않아 다른 문서나 사용자의 데이터를 삭제하지 않음
    vectorstore.add_documents(chunks)

    # 검색기 + 언어 모델
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, streaming=True)

    # 학습 도우미 역할과 답변 기준
    s_msg = """당신은 KT AIVLE School 교육생활 학습 도우미입니다.
반드시 [문서]에 제시된 내용에 근거하여 한국어로 정확하고 친절하게 답하세요.
출결, 지원금, 교육 일정 등에는 적용 대상, 기한, 예외 조건이 있다면 빠뜨리지 마세요.
백서에 기록된 기수와 날짜는 현재 정책이라고 단정하지 말고 해당 기준 시점을 밝혀주세요.
문서에 없는 사실이나 수치를 추측해서 만들지 마세요.
문서에서 확인할 수 없으면 '업로드된 문서에서 확인되지 않습니다.'라고 답하세요.
필요할 때는 간단한 순서나 항목으로 정리하되 지나치게 장황하게 작성하지 마세요.

[문서]
{context}"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", s_msg),
        ("human", "{input}")
    ])

    rag_chain = (
        {
            "context": itemgetter("input") | retriever | format_docs,
            "input": itemgetter("input")
        }
        | prompt
        | llm
        | StrOutputParser()
    )
    return rag_chain

# 5. Streamlit 세션 상태 준비: 문서가 같으면 체인 재사용
if "rag_chain" not in st.session_state:
    st.session_state.rag_chain = None
if "pdf_hash" not in st.session_state:
    st.session_state.pdf_hash = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# 6. PDF 업로드 (필수 기능)
with st.sidebar:
    st.header("📂 학습 자료")
    uploaded_file = st.file_uploader("백서 PDF를 선택하세요", type=["pdf"])

if uploaded_file is None:
    # 업로드를 취소하면 다른 PDF의 답변을 보여주지 않도록 초기화
    if st.session_state.pdf_hash is not None:
        st.session_state.pdf_hash = None
        st.session_state.rag_chain = None
        st.session_state.messages = []
    st.info("왼쪽에서 AIVLE School 백서 PDF를 업로드하면 질문할 수 있습니다.")
else:
    contents = uploaded_file.getvalue()
    current_hash = hashlib.sha256(contents).hexdigest()

    # PDF가 변경된 경우에만 벡터화하고, 같은 파일이면 기존 체인을 사용
    if current_hash != st.session_state.pdf_hash:
        temp_path = None
        try:
            with st.spinner("PDF 문서를 읽고 벡터 저장소를 준비하는 중입니다..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                    temp_file.write(contents)
                    temp_path = temp_file.name

                new_chain = rag_pipeline(temp_path)
                st.session_state.rag_chain = new_chain
                st.session_state.pdf_hash = current_hash
                st.session_state.messages = []
            st.success("문서 준비 완료! 질문을 입력해 주세요.")
        except Exception as error:
            st.session_state.rag_chain = None
            st.session_state.pdf_hash = None
            st.session_state.messages = []
            st.error(f"PDF 처리 중 오류가 발생했습니다: {error}")
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

# 7. 추천 질문과 대화 초기화 (선택 기능)
suggested_questions = [
    "AIVLE School AI 개발자 트랙과 DX 컨설턴트 트랙은 어떻게 다른가요?",
    "출석인정 신청 방법과 기한은 어떻게 되나요?",
    "미니프로젝트를 시작할 때 무엇부터 준비하면 좋을까요?",
    "코딩 초보자는 어떤 방식으로 복습하면 좋을까요?"
]
selected_question = None

with st.sidebar:
    if st.session_state.rag_chain is not None:
        st.success("✅ 문서 검색 준비 완료")
    st.divider()
    st.subheader("💡 추천 질문")
    for i, question in enumerate(suggested_questions):
        if st.button(question, key=f"suggested_{i}", use_container_width=True,
                     disabled=st.session_state.rag_chain is None):
            selected_question = question
    st.divider()
    if st.button("🗑️ 대화 내용 삭제", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# 8. 기존 대화 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 9. 질문 입력 → RAG 체인 실행 → 답변 표시
user_input = st.chat_input(
    "AIVLE School에 대해 질문해 보세요...",
    disabled=st.session_state.rag_chain is None
)
question = selected_question or user_input

if question and st.session_state.rag_chain is not None:
    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.messages.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        try:
            response = st.write_stream(
                st.session_state.rag_chain.stream({"input": question})
            )
        except Exception as error:
            response = "답변을 생성하는 중 오류가 발생했습니다. 다시 시도해 주세요."
            st.error(f"{response} ({error})")
    st.session_state.messages.append({"role": "assistant", "content": response})
