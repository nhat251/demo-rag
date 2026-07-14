from dataclasses import dataclass, field

@dataclass
class Config:
    # Models
    gen_model: str = "gemini-3.1-flash-lite"
    embed_model: str = "gemini-embedding-001"
    # Chroma
    persist_dir: str = "./chroma_db"
    collection_name: str = "kb_db"
    # Chunking / Retrieval
    max_chunk_chars: int = 1200
    top_k: int = 4
    # Validation (rule cụ thể — HARDCODE là chấp nhận được)
    enable_validation: bool = True
    numeric_ratio_threshold: float = 0.6
    outlier_method: str = "iqr"
    outlier_k: float = 3.0
    phone_regex: str = r"^0\d{9}$"
    phone_header_keywords: list = field(default_factory=lambda: ["điện thoại", "sđt", "phone"])
    thousand_sep_pattern: str = r"^\d{1,3}([.,]\d{3})+$"
    ai_explain: bool = True
