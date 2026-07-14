import streamlit as st
import os
import tempfile
import pandas as pd

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from src.extract import extract_file
from src.validate import validate, summarize_with_ai
from src.normalize import normalize_records
from src.rag_core import upsert_records, generate_answer, list_loaded_files, delete_loaded_file, reset_collection


@st.cache_resource
def get_cfg():
    return Config()


@st.cache_resource
def init_session():
    cfg = get_cfg()
    return cfg


def _format_source(source: dict) -> str:
    details = []
    if source.get("sheet"):
        details.append(f"sheet {source['sheet']}")
    if source.get("row"):
        details.append(f"dòng {source['row']}")
    if source.get("page"):
        details.append(f"trang {source['page']}")
    suffix = f" — {', '.join(details)}" if details else ""
    return f"📄 {source['file']} ({source['loai']}){suffix}"


st.set_page_config(page_title="Demo RAG Chatbot", layout="wide")
st.title("Demo RAG Chatbot — Training 120'")

cfg = init_session()

# Sidebar
with st.sidebar:
    st.header("Trạng thái")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        st.success("✓ API key đã cấu hình")
    else:
        st.error("✗ Thiếu GEMINI_API_KEY (.env)")

    cfg.ai_validate = st.checkbox(
        "Bật AI audit khi validate",
        value=cfg.ai_validate,
        disabled=not bool(api_key),
        help="Rule engine vẫn chạy trước. AI audit chỉ phân tích thêm theo rulebook và có thể không ổn định tuyệt đối.",
    )

    st.divider()
    st.subheader("File đã nạp")
    loaded_files = list_loaded_files(cfg)
    if loaded_files:
        for f in loaded_files:
            col_file, col_delete = st.columns([4, 1])
            with col_file:
                st.text(f"📄 {f}")
            with col_delete:
                if st.button("Xóa", key=f"delete_source_{f}", help=f"Xóa riêng source {f}"):
                    deleted = delete_loaded_file(cfg, f)
                    st.toast(f"Đã xóa {deleted} chunks từ '{f}'")
                    st.rerun()
    else:
        st.text("Chưa có file nào")

    if st.button("🗑 Xoá toàn bộ dữ liệu", type="secondary"):
        reset_collection(cfg)
        st.rerun()

# Main area
uploaded_files = st.file_uploader(
    "Tải lên file Excel (.xlsx) hoặc PDF (.pdf)",
    type=["xlsx", "pdf"],
    accept_multiple_files=True,
)

if uploaded_files:
    for uploaded_file in uploaded_files:
        file_ext = os.path.splitext(uploaded_file.name)[1].lower()

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            records = extract_file(tmp_path)
            findings = validate(tmp_path, cfg) if file_ext == ".xlsx" else []

            if findings:
                with st.expander(f"🔍 Kiểm tra đầu vào — {uploaded_file.name}", expanded=True):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        df_findings = pd.DataFrame(findings)
                        st.dataframe(df_findings, width="stretch")

                    with col2:
                        loai_counts = df_findings["loai_loi"].value_counts()
                        for loai, cnt in loai_counts.items():
                            st.metric(label=loai, value=cnt)

                    summary = summarize_with_ai(findings, cfg)
                    if summary:
                        st.info(summary)

                    csv = df_findings.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "Tải CSV báo cáo lỗi",
                        data=csv,
                        file_name=f"validate_{uploaded_file.name}.csv",
                        mime="text/csv",
                    )

            if st.button(f"📥 Nạp '{uploaded_file.name}' vào cơ sở tri thức", key=f"ingest_{uploaded_file.name}"):
                with st.spinner("Đang chuẩn hoá dữ liệu..."):
                    normalized = normalize_records(records, cfg)
                with st.spinner("Đang nạp vào ChromaDB..."):
                    chunks = upsert_records(normalized, cfg)
                st.success(f"✅ Đã nạp {chunks} chunks từ '{uploaded_file.name}'")
                st.rerun()

        except Exception as e:
            st.error(f"Lỗi xử lý file '{uploaded_file.name}': {e}")
        finally:
            os.unlink(tmp_path)

# Chat
st.divider()
st.subheader("💬 Hỏi đáp")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg and msg["sources"]:
            with st.expander("Nguồn"):
                for s in msg["sources"]:
                    st.text(_format_source(s))

if prompt := st.chat_input("Nhập câu hỏi của bạn..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.spinner("Đang tìm kiếm..."):
        try:
            result = generate_answer(prompt, cfg)
            answer = result["answer"]
            sources = result.get("sources", [])
        except Exception as e:
            answer = f"Lỗi: {e}"
            sources = []

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources,
    })
    with st.chat_message("assistant"):
        st.markdown(answer)
        if sources:
            with st.expander("Nguồn"):
                for s in sources:
                    st.text(_format_source(s))
