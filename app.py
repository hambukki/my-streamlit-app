
%%writefile app.py

# 28번 셀: AIVLE School 학습 도우미 고도화 (기본 백서 자동 연결)
# 기존 19번 셀/30번 배포 셀을 바꾸지 않고 이 셀에서 app.py를 제작합니다.
# 백서는 Colab 17번 셀에서 Google Drive 파일로 미리 벡터화한 chroma_db를 사용합니다.

import os
import hashlib
import tempfile
from uuid import uuid4
from operator import itemgetter

import streamlit as st
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_pymupdf4llm import PyMuPDF4LLMLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ── 1. 페이지 설정: Streamlit 기본 사이드바 토글로 열고 닫을 수 있습니다.
st.set_page_config(
    page_title="AIVLE School | 학습 도우미",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 기존 화면 레퍼런스의 남색 사이드바 / 흰색 본문 / 민트 강조를 적용합니다.
st.markdown("""
<style>
:root { --navy:#18293d; --navy2:#243951; --mint:#18aa9e; --ink:#192638; }
[data-testid="stAppViewContainer"] { background:#fbfcfd; }
section[data-testid="stSidebar"] { background:linear-gradient(180deg,#16283d,#20374e); }
section[data-testid="stSidebar"] * { color:#f4f8fc; }
section[data-testid="stSidebar"] [data-testid="stTextInput"] input {
    background:#31465c !important; color:#fff !important; border:1px solid #66778a !important;
}
section[data-testid="stSidebar"] [data-testid="stTextInput"] input::placeholder { color:#c5d1da; }
section[data-testid="stSidebar"] [data-testid="stButton"] button {
    border:1px solid #547084; color:#f9fbff !important; background:#28465a;
}
section[data-testid="stSidebar"] [data-testid="stButton"] button:hover {
    border-color:#52dbcb; background:#285c65;
}
section[data-testid="stSidebar"] a { color:#7ce1d8 !important; }
.block-container { max-width:1150px; padding-top:1.2rem; }
.aivle-eyebrow { color:#168c82;font-weight:750;letter-spacing:.1em;font-size:.8rem; }
.aivle-hero { text-align:center; padding:2.4rem 0 1.3rem 0; }
.aivle-robot { font-size:3.7rem; line-height:1.2; margin-bottom:0.5rem; }
.aivle-hero h1 { color:#152337; font-size:2.45rem; font-weight:800; margin:.3rem 0 .6rem; }
.aivle-hero p { color:#58697a;font-size:1.04rem;line-height:1.8; }
.aivle-mint { color:#0b988e; }
.aivle-status { background:#e8f6f3; border:1px solid #c6e8e2;
    border-radius:12px; padding:12px 16px; color:#18695f; font-size:.94rem; }
.aivle-section-title { font-weight:750; color:#172940; font-size:1.06rem; margin-top:1rem; }
[data-testid="stChatMessage"] { border-radius:14px; }
[data-testid="stChatInput"] { border-radius:14px; }
</style>
""", unsafe_allow_html=True)

# ── 2. API 키: Colab에서 읽은 api_key.txt가 Cloud로 전달되지는 않습니다.
if not os.getenv("OPENAI_API_KEY"):
    try:
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
    except Exception:
        st.error("Streamlit Community Cloud의 Secrets에 OPENAI_API_KEY를 등록해 주세요.")
        st.stop()

# ── 3. 기존 교안과 동일한 모델 및 기본 백서 Chroma 설정
CHROMA_DIR = "chroma_db"
COLLECTION = "aivle_docs"  # 17번 셀에서 생성한 이름과 같아야 합니다.
EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"


def format_docs(docs):
    """검색한 문서 조각을 출처 메타데이터와 함께 연결합니다."""
    sections = []
    for doc in docs:
        page = doc.metadata.get("page", None)
        page_label = f"PDF {int(page) + 1}쪽" if isinstance(page, int) else "백서 본문"
        sections.append(f"[{page_label}]\n{doc.page_content}")
    return "\n\n".join(sections)


def make_chain(retriever):
    """기존 28번 셀의 검색기 → 프롬프트 → LLM → 파서 흐름을 유지합니다."""
    system_msg = """당신은 KT AIVLE School의 교육생활과 학습을 안내하는 도우미입니다.
반드시 아래 [검색된 자료]의 내용으로만 한국어로 답변하세요.
지원·출결·훈련장려금·교육 운영 정보는 기수, 적용 대상, 기한, 예외 조건을 함께 설명하세요.
과거 기수 정보나 10기 기록을 현재 모든 기수에 그대로 적용되는 규정처럼 말하지 마세요.
검색 자료에 근거가 부족하면 '현재 학습 자료에서 확인할 수 없습니다.'라고 분명히 말하세요.
질문자가 실제로 무엇을 하면 좋을지도 자료에 근거해 친절하고 구체적으로 설명하세요.
근거에 표시된 PDF 쪽수를 인용할 수 있을 때에는 답변 말미에 표시하세요.
문서에 없는 날짜, 조건, 성과, 취업 보장 등을 만들어내지 마세요.

[검색된 자료]
{context}"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("human", "{input}")
    ])
    llm = ChatOpenAI(model=CHAT_MODEL, temperature=0, streaming=True)
    return (
        {
            "context": itemgetter("input") | retriever | format_docs,
            "input": itemgetter("input"),
        }
        | prompt | llm | StrOutputParser()
    )


# ── 4. 기존 rag_pipeline(filepath): 별도 문서 업로드 검증 시에만 실행
# 기본 AIVLE 백서는 여기서 재벡터화하지 않습니다.
def rag_pipeline(filepath):
    loader = PyMuPDF4LLMLoader(filepath)
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    chunks = splitter.split_documents(docs)
    if not chunks:
        raise ValueError("PDF에서 검색할 텍스트를 찾지 못했습니다.")

    embedding = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    # 업로드별 독립 메모리 컬렉션: 기본 Chroma DB를 지우거나 덮어쓰지 않습니다.
    vectorstore = Chroma(
        collection_name="extra_" + uuid4().hex[:16],
        embedding_function=embedding,
    )
    vectorstore.add_documents(chunks)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
    return make_chain(retriever)


# ── 5. 기본 백서 DB는 Colab 17번 셀에서 이미 만든 것을 읽어옵니다.
@st.cache_resource(show_spinner="AIVLE School 백서를 연결하고 있습니다...")
def get_default_chain():
    if not os.path.isdir(CHROMA_DIR):
        raise FileNotFoundError(
            "chroma_db 폴더가 없습니다. Colab 17번 셀로 Google Drive 백서를 벡터화하고 "
            "기존 25번 셀로 저장소를 GitHub에 업로드해 주세요."
        )
    embedding = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    vectorstore = Chroma(
        collection_name=COLLECTION,
        embedding_function=embedding,
        persist_directory=CHROMA_DIR,
    )
    # 빈 저장소로 '준비 완료'라고 표시하지 않도록 검사합니다.
    if vectorstore._collection.count() == 0:
        raise ValueError("기본 백서 벡터 저장소가 비어 있습니다. 17번 셀의 생성 결과를 확인해 주세요.")
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
    return make_chain(retriever)


# ── 6. 세션 상태: 기본 체인과 선택 업로드 체인을 분리합니다.
if "conversations" not in st.session_state:
    st.session_state.conversations = {}
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = uuid4().hex
    st.session_state.conversations[st.session_state.active_chat_id] = {
        "title": "새로운 채팅", "messages": [],
    }
if "extra_pdf_hash" not in st.session_state:
    st.session_state.extra_pdf_hash = None
if "extra_chain" not in st.session_state:
    st.session_state.extra_chain = None
if "base_chain" not in st.session_state:
    st.session_state.base_chain = None


def new_chat():
    chat_id = uuid4().hex
    st.session_state.conversations[chat_id] = {"title": "새로운 채팅", "messages": []}
    st.session_state.active_chat_id = chat_id


def reset_current_chat():
    chat = st.session_state.conversations[st.session_state.active_chat_id]
    chat["messages"] = []
    chat["title"] = "새로운 채팅"


try:
    st.session_state.base_chain = get_default_chain()
    base_error = None
except Exception as exc:
    base_error = str(exc)

# ── 7. 사이드바. 기본 Streamlit '>'/'<' 컨트롤로 클릭하여 접고 펼칩니다.
with st.sidebar:
    st.markdown("## ◈ AIVLE School")
    st.caption("RAG 학습 도우미 | 4조 백서")
    st.divider()
    if st.button("＋ 새 채팅 시작", use_container_width=True, key="sidebar_new"):
        new_chat()
        st.rerun()

    search_text = st.text_input("대화 검색", placeholder="지금까지 한 채팅 검색", key="chat_search")
    st.markdown("**내 채팅 라이브러리**")
    for chat_id, chat in reversed(list(st.session_state.conversations.items())):
        title = chat["title"]
        if search_text.lower() not in title.lower():
            continue
        mark = "● " if chat_id == st.session_state.active_chat_id else "▢ "
        if st.button(mark + title[:24], key="select_" + chat_id, use_container_width=True):
            st.session_state.active_chat_id = chat_id
            st.rerun()

    st.divider()
    st.markdown("**학습 자료**")
    if base_error is None:
        st.success("📚 4조 통합 백서 연결됨")
        st.caption("기본 백서가 자동으로 검색됩니다. 별도 업로드는 필요 없습니다.")
    else:
        st.warning("기본 백서 DB 연결 확인 필요")

    # 교안의 문서 직접 업로드 요구사항: 기본 백서와는 분리된 선택 기능입니다.
    with st.expander("다른 PDF로 질문하기 · 선택", expanded=False):
        st.caption("교안 30·44·46쪽의 문서 업로드 기능입니다. 4조 백서는 업로드하지 않아도 됩니다.")
        extra_file = st.file_uploader("추가 PDF 선택", type=["pdf"], key="optional_extra_pdf")

    st.divider()
    if st.button("🗑️ 현재 대화 삭제", use_container_width=True, key="clear_chat"):
        reset_current_chat()
        st.rerun()
    st.markdown("[🌐 AIVLE School 공식 사이트](https://aivle.kt.co.kr/)")
    st.caption("대화 기록은 현재 브라우저 세션에서만 유지됩니다.")

# ── 8. PDF 추가 업로드를 선택한 때만 rag_pipeline()을 호출합니다.
if extra_file is not None:
    extra_data = extra_file.getvalue()
    extra_hash = hashlib.sha256(extra_data).hexdigest()
    if extra_hash != st.session_state.extra_pdf_hash:
        temp_path = None
        try:
            with st.spinner("추가 PDF를 읽고 RAG 검색기를 준비하는 중입니다..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(extra_data)
                    temp_path = tmp.name
                chain = rag_pipeline(temp_path)
                st.session_state.extra_chain = chain
                st.session_state.extra_pdf_hash = extra_hash
                new_chat()  # 서로 다른 PDF 질문 기록 혼합 방지
        except Exception as exc:
            st.session_state.extra_chain = None
            st.session_state.extra_pdf_hash = None
            st.error("추가 PDF 처리 실패: " + str(exc))
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
else:
    if st.session_state.extra_pdf_hash is not None:
        st.session_state.extra_pdf_hash = None
        st.session_state.extra_chain = None
        new_chat()

active_chain = st.session_state.extra_chain or st.session_state.base_chain
current_chat = st.session_state.conversations[st.session_state.active_chat_id]

# ── 9. 레퍼런스 스타일의 상단 및 중앙 시작 화면
header_left, header_right = st.columns([5, 1])
with header_left:
    st.markdown('<div class="aivle-eyebrow">AIVLE SCHOOL · KNOWLEDGE ASSISTANT</div>', unsafe_allow_html=True)
with header_right:
    if st.button("＋ 새 채팅", use_container_width=True, key="top_new"):
        new_chat()
        st.rerun()

if base_error and extra_file is None:
    st.error("기본 백서 연결 오류: " + base_error)

if not current_chat["messages"]:
    st.markdown("""
    <div class="aivle-hero">
      <div class="aivle-robot">🤖</div>
      <div class="aivle-eyebrow">AIVLE School <span class="aivle-mint">학습 도우미</span></div>
      <h1>무엇을 도와드릴까요?</h1>
      <p>지원부터 교육생활, 프로젝트와 취업 준비까지<br>
      4조 통합 백서의 내용을 바탕으로 질문에 답해 드려요.</p>
    </div>""", unsafe_allow_html=True)
    if st.session_state.extra_chain is not None:
        st.info("지금은 추가 PDF를 검색하고 있어요. 업로드를 해제하면 4조 백서로 돌아갑니다.")
    elif base_error is None:
        st.markdown('<div class="aivle-status">✓ 4조 AIVLE School 백서가 연결되어 있어요. 별도로 PDF를 올릴 필요 없이 바로 질문하세요.</div>', unsafe_allow_html=True)

questions = [
    ("지원·선발", "지원 자격과 AI·DX 트랙은 어떻게 다른가요?"),
    ("교육·출결", "출석 인정 신청 기한과 절차는 어떻게 되나요?"),
    ("미니프로젝트", "미니프로젝트를 시작할 때 무엇을 준비하면 좋을까요?"),
    ("취업·진로", "프로젝트 경험을 포트폴리오에 어떻게 정리하면 좋을까요?"),
]
selected = None
if not current_chat["messages"]:
    st.markdown('<div class="aivle-section-title">이런 질문으로 시작해 보세요</div>', unsafe_allow_html=True)
    cards = st.columns(4)
    for i, (category, q) in enumerate(questions):
        with cards[i]:
            with st.container(border=True):
                st.markdown("**" + ["👤", "🗓️", "📚", "💼"][i] + " " + category + "**")
                st.caption(q)
                if st.button("질문하기", key=f"q_{i}", use_container_width=True, disabled=active_chain is None):
                    selected = q

# ── 10. 메시지와 입력 (기존 미니프로젝트 코드 방식 유지)
for msg in current_chat["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

text_input = st.chat_input(
    "에이블스쿨에 관해 무엇이든 물어보세요...",
    disabled=active_chain is None,
)
question = selected or text_input
if question and active_chain is not None:
    if current_chat["title"] == "새로운 채팅":
        current_chat["title"] = question[:28]
    with st.chat_message("user"):
        st.markdown(question)
    current_chat["messages"].append({"role": "user", "content": question})
    with st.chat_message("assistant"):
        try:
            answer = st.write_stream(active_chain.stream({"input": question}))
        except Exception:
            answer = "답변을 불러오는 데 문제가 발생했습니다. 잠시 후 다시 질문해 주세요."
            st.error(answer)
    current_chat["messages"].append({"role": "assistant", "content": answer})
