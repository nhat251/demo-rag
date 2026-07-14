# KẾ HOẠCH: Đập bỏ & xây lại pipeline Validate + RAG

> **Một câu tóm tắt**: Thay hệ rule hardcode CT01–CT14 bằng **rule động dạng JSON do AI đề xuất, người dùng chỉ tick duyệt**, chạy qua engine deterministic; lưu profile theo loại báo cáo để lần sau upload là tự nhận; UI làm lại thành wizard 4 bước tiếng Việt cho người lớn tuổi; phần RAG (Chroma + Gemini) giữ nguyên.

---

## 1. BỐI CẢNH — Tại sao phải đập bỏ

**Vấn đề hiện tại:**
- 6 rule validate trong `src/validation_rules.py` + 7 rule logic (CT03 ≤ CT01...) **hardcode cứng cho đúng 1 loại báo cáo thôn/xã**. Upload báo cáo khác (hoá đơn, bảng lương, báo cáo tài chính...) → rule vô dụng, phải sửa code.
- `src/schema_infer.py` chỉ nhận diện được 3 layout cố định gắn với mã CT.
- Chưa có kiểm tra **lỗi tính toán** (Thành tiền = Số lượng × Đơn giá, dòng Tổng = tổng chi tiết).
- Không có chỗ nào cho người dùng xem/duyệt/bật-tắt rule.
- Header detection bị viết trùng 2 nơi (`extract.py` và `schema_infer.py`) với keyword CT hardcode.

**Yêu cầu mới (đã chốt với user):**
1. Upload Excel → phát hiện: thiếu dữ liệu, sai định dạng, lỗi logic, **lỗi tính toán** → hiển thị rõ ràng.
2. Index xong → hỏi đáp RAG (giữ như hiện tại).
3. **AI tự suy luận rule từ file, người dùng chỉ duyệt** (đối tượng: cán bộ lớn tuổi, không rành máy tính).
4. Upload loại báo cáo mới → cấu hình đúng 1 lần, lần sau tự nhận.
5. Phạm vi: **đập bỏ phần validate, giữ phần RAG còn tốt**.

**Giữ nguyên (đã kiểm tra kỹ, đang chạy tốt):**
- `src/rag_core.py` (387 dòng): chunking, embedding batch + retry, Chroma upsert theo file, hybrid retrieval (vector + lexical bỏ dấu tiếng Việt), generate answer kèm nguồn.
- `src/normalize.py`: làm sạch text.
- Stack: Streamlit, ChromaDB local, `gemini-3.1-flash-lite`, `gemini-embedding-001`.

---

## 2. KIẾN TRÚC MỚI — Luồng tổng thể

```
┌──────────────┐
│ Upload .xlsx │
└──────┬───────┘
       ▼
┌─────────────────────┐    table_extract.py
│ Parse → ParsedSheet │    (header detection generic, dòng tổng, metadata)
└──────┬──────────────┘
       ▼
┌─────────────────────────────┐    profile_store.py
│ Fingerprint header → match? │
└──┬──────────────────────┬───┘
   │ ĐÃ CÓ profile        │ CHƯA CÓ (loại báo cáo mới)
   │ → tự load rule       ▼
   │              ┌──────────────────────┐   rule_infer.py
   │              │ Heuristic baseline    │   (offline, luôn chạy)
   │              │ + AI đề xuất rule     │   (1 call Gemini)
   │              │ + verify trên dữ liệu │   (rule sai → bat=false)
   │              └──────────┬───────────┘
   ▼                         ▼
┌────────────────────────────────────┐   UI Bước 2
│ Người dùng DUYỆT rule (checkbox)   │   → save profile
└──────┬─────────────────────────────┘
       ▼
┌─────────────────────┐   rule_engine.py — deterministic 100%,
│ Chạy engine → lỗi   │   AI KHÔNG sinh finding trực tiếp
└──────┬──────────────┘
       ▼
┌─────────────────────┐   UI Bước 3: bảng lỗi màu, đếm theo mức độ, CSV
│ Hiển thị kết quả    │
└──────┬──────────────┘
       ▼
┌─────────────────────┐   normalize.py + rag_core.py (GIỮ NGUYÊN)
│ Index → Chat RAG    │   UI Bước 4
└─────────────────────┘
```

**Nguyên tắc vàng**: *AI đề xuất — code thực thi.* Mọi finding đều do rule engine deterministic sinh ra. AI chỉ đề xuất rule (JSON) và rule đó bị verify trên dữ liệu thật trước khi hiện cho người dùng. Không bao giờ có finding "bịa" từ LLM (trừ lớp AI audit phụ, tách riêng, mặc định tắt).

---

## 3. BỐ CỤC FILE — Giữ / Sửa / Mới / Xoá

| File | Hành động | Ghi chú |
|---|---|---|
| `src/rag_core.py` | **GIỮ nguyên** | Không đụng |
| `src/normalize.py` | **GIỮ nguyên** | Không đụng |
| `config.py` | SỬA | Thêm `profiles_dir="./profiles"`, `formula_tolerance=0.01`, `rule_infer_sample_rows=8`, `ai_rule_infer=True`; bỏ các field validate cũ không dùng |
| `src/textutil.py` | **MỚI** | Helper thuần: `norm_text`, `is_blankish`, `to_float`, `is_thousand_sep_value`, `is_total_label` — gom từ `schema_infer.py` + `validation_rules.py` cũ |
| `src/table_extract.py` | **MỚI** | Excel → `list[ParsedSheet]`. Header detection generic (không keyword CT), phát hiện dòng tổng, metadata trước header |
| `src/extract.py` | VIẾT LẠI | Mỏng: gọi `table_extract` → build text record RAG theo format flatten `" | "` cũ; giữ `read_pdf_text` nguyên bản. Xoá `_detect_header_row` (keyword CT) |
| `src/rules_schema.py` | **MỚI** | `Rule` dataclass, validate/serialize JSON, template mô tả tiếng Việt cho từng loại rule |
| `src/rule_engine.py` | **MỚI** | 12 executor deterministic, dispatch theo `loai`, Finding kèm địa chỉ ô Excel |
| `src/rule_infer.py` | **MỚI** | Baseline heuristic + gọi Gemini đề xuất rule + verify rule trên dữ liệu mẫu |
| `src/profile_store.py` | **MỚI** | Fingerprint header, save/load/match `profiles/*.json` |
| `src/ai_validator.py` | VIẾT LẠI | AI audit phụ generic (bỏ enum CT cũ); giữ lại `_parse_json_array`, `_normalize_ai_finding` |
| `src/validate.py` | VIẾT LẠI | Orchestrator mỏng: parse → profile → engine → (AI audit) → dedupe → sort |
| `app/streamlit_app.py` | VIẾT LẠI | Wizard 4 bước tiếng Việt (chi tiết mục 8) |
| `src/schema_infer.py` | **XOÁ** | Thay bằng `table_extract.py` |
| `src/validation_rules.py` | **XOÁ** | Thay bằng `rule_engine.py`; 7 logic rule cũ → chuyển thành data trong profile |
| `profiles/bao-cao-thon-ct.json` | **MỚI** | Profile ship sẵn: 7 rule CT cũ + phone/blank/sep/outlier dưới dạng JSON |
| `data/test_hoa_don.xlsx` | **MỚI** | Fixture test lỗi tính toán (sinh bằng script openpyxl) |
| `tests/smoke_test.py` | VIẾT LẠI | Chi tiết mục 9 |
| `requirements.txt` | SỬA | Thêm `xlrd>=2.0` (đọc .xls) |
| `README.md` | SỬA | Cập nhật luồng mới |

---

## 4. RULE SCHEMA — JSON khai báo (trái tim hệ thống)

Mỗi rule là 1 object JSON, lưu trong profile, do AI/heuristic/người dùng tạo:

```json
{
  "id": "R007",
  "loai": "formula",
  "mo_ta": "Cột 'Thành tiền' phải bằng 'Số lượng' nhân 'Đơn giá'",
  "sheet": "Tong hop",
  "muc_do": "cao",
  "bat": true,
  "nguon": "ai",
  "tham_so": { "ket_qua": "Thành tiền", "toan_hang": ["Số lượng", "Đơn giá"], "phep": "nhan", "dung_sai": 0.01 }
}
```

**Field chung:**
- `id`: duy nhất trong profile (R001, R002...)
- `loai`: 1 trong 12 loại bên dưới
- `mo_ta`: **câu tiếng Việt thuần** hiện lên checkbox cho người dùng — sinh từ template trong `rules_schema.py`; nếu AI trả mô tả quá kỹ thuật thì override bằng template
- `sheet`: tên sheet hoặc `null` (= áp dụng mọi sheet resolve được cột đích)
- `muc_do`: `"cao"` 🔴 / `"vua"` 🟡 / `"thap"` 🔵
- `bat`: bật/tắt (chính là checkbox ở UI Bước 2)
- `nguon`: `"he_thong"` (heuristic) / `"ai"` / `"nguoi_dung"`

**12 loại rule + `tham_so`:**

| # | `loai` | `tham_so` | Bắt lỗi gì | `loai_loi` sinh ra |
|---|---|---|---|---|
| 1 | `not_blank` | `{"cot": ["Thôn", "CT01"]}` | Ô bắt buộc bị trống | `THIEU` |
| 2 | `numeric` | `{"cot": [...], "kieu": "so_nguyen"\|"so_thuc", "bao_phan_cach_nghin": true}` | Chữ trong cột số; "1.000" kiểu phân cách nghìn | `SAI_DINH_DANG` |
| 3 | `value_range` | `{"cot": [...], "min": 0, "max": null}` | Số âm, vượt ngưỡng | `SAI_LOGIC` |
| 4 | `allowed_values` | `{"cot": ["Trạng thái nộp"], "gia_tri": ["Đúng hạn", "Trễ hạn", "Chưa nộp"]}` | Giá trị ngoài danh sách cho phép | `SAI_DINH_DANG` |
| 5 | `date_format` | `{"cot": [...], "dinh_dang": ["%d/%m/%Y", "%d/%m/%Y %H:%M"]}` | Ngày sai định dạng | `SAI_DINH_DANG` |
| 6 | `phone` | `{"cot": ["SĐT"], "regex": "^0\\d{9}$"}` | SĐT sai format | `SAI_DINH_DANG` |
| 7 | `unique` | `{"cot": ["Thôn"]}` | Trùng lặp định danh | `SAI_LOGIC` |
| 8 | `cross_field` | `{"trai": "CT03", "phep": "<=", "phai": "CT01"}` — phep ∈ `<= >= < > ==` | Hộ nghèo > tổng số hộ | `SAI_LOGIC` |
| 9 | `formula` | `{"ket_qua": "Thành tiền", "toan_hang": ["Số lượng", "Đơn giá"], "phep": "nhan"\|"cong"\|"tru"\|"chia", "dung_sai": 0.01}` | **Lỗi tính toán** từng dòng. Toán hạng có cấu trúc — **KHÔNG eval chuỗi biểu thức** (không có bề mặt injection) | `SAI_CONG_THUC` |
| 10 | `totals_row` | `{"cot": ["CT01"] hoặc null (= mọi cột số), "dung_sai": 0}` | Dòng "Tổng cộng" ≠ tổng các dòng chi tiết | `SAI_CONG_THUC` |
| 11 | `outlier` | `{"cot": [...], "phuong_phap": "iqr"\|"zscore", "k": 3.0}` | Số liệu bất thường thống kê | `BAT_THUONG` |
| 12 | `chua_nop` | `{"cot_dinh_danh": "Thôn", "cot_kiem_tra": ["CT01", ...]}` | Cả dòng trống → "đơn vị chưa nộp" (1 finding/dòng, **suppress** các lỗi THIEU từng ô của dòng đó) | `CHUA_NOP` |

**Resolve tên cột** (quan trọng — header thực tế bẩn):
1. So `norm_text(rule_cot) == norm_text(header)` (bỏ dấu, lowercase, gộp space).
2. Fallback: match token đầu / mã — để rule ghi `"CT01"` khớp được header thật `"CT01\nTổng số hộ dân"`.
3. Không resolve được → sinh finding mức `thap`: *"Quy tắc R007 không áp dụng được: không tìm thấy cột 'Thành tiền' trong sheet X"* — **không bao giờ skip im lặng**.

---

## 5. PARSE LAYER — `src/table_extract.py`

```python
@dataclass
class ParsedSheet:
    sheet_name: str
    header_row_idx: int | None       # 0-based trong grid gốc
    header: list[str]                # đã làm sạch, đã join header 2 dòng
    df: pd.DataFrame                 # CHỈ dòng dữ liệu chi tiết, dtype=str,
                                     # index = số dòng Excel gốc (0-based)
    context_lines: list[str]         # metadata trước header: "Kỳ báo cáo: T17..."
    total_row_idxs: list[int]        # các dòng tổng (loại khỏi df chi tiết)
    kv_rows: list[tuple[str, str]]   # cặp key-value ("Đơn vị báo cáo:", "Thôn Hòa Trung")

def parse_workbook(path_or_buffer) -> list[ParsedSheet]: ...
```

**Header detection generic** (thay heuristic keyword CT cũ) — chấm điểm ~30 dòng đầu mỗi sheet:
- (a) số ô không rỗng, text ngắn, đa số không phải số
- (b) độ nhất quán fill của 5 dòng ngay bên dưới
- (c) độ distinct của giá trị các ô
- Dòng điểm cao nhất thắng. Nếu dòng thắng có ô trống mà dòng ngay dưới cũng nhiều text (dấu hiệu merged cell 2 tầng) → **join 2 dòng bằng `" "`** + forward-fill ngang. Header sâu hơn 2 tầng: ngoài scope v1, profile lưu `dong_tieu_de` để sau này override tay.

**Phát hiện dòng tổng**: ô text đầu tiên normalize bắt đầu bằng `tong` / `cong` / `tong cong` **VÀ** đa số ô còn lại là số. (2 điều kiện cùng lúc → tránh false positive thôn tên "Tổng...").

**Nguyên tắc**: cell giữ nguyên string, KHÔNG parse số ở tầng này — parse số chỉ xảy ra trong executor qua `textutil.to_float` (xử lý `1234,5` phẩy thập phân; pattern `2.450` phân cách nghìn detect riêng).

**`src/extract.py` mới** build record RAG từ `ParsedSheet` theo đúng format flatten cũ (`File: X | Sheet: Y | Dòng Excel: N | Cột: Giá trị | ...`) → **một đường parse duy nhất** cho cả validate lẫn index. `read_pdf_text` giữ nguyên.

---

## 6. RULE ENGINE — `src/rule_engine.py`

```python
def run_rules(sheets: list[ParsedSheet], rules: list[Rule], cfg: Config) -> list[dict]:
    # chỉ chạy rule bat=True; dispatch: EXECUTORS = {"not_blank": _exec_not_blank, ...}
```

- Engine chạy trên **`ParsedSheet.df` (bảng structured)** — KHÔNG chạy trên text record flatten (cái đó chỉ để index RAG).
- **Finding** — dict phẳng, hiển thị thẳng lên DataFrame:

```json
{
  "rule_id": "R007", "loai_loi": "SAI_CONG_THUC", "muc_do": "cao",
  "sheet": "Tong hop", "dong": 7, "cot": "Thành tiền", "o": "E7",
  "gia_tri": "1.200.000",
  "vi_tri": "Sheet 'Tong hop', dòng 7, cột 'Thành tiền' (ô E7)",
  "mo_ta": "Thành tiền = 1.200.000 nhưng Số lượng × Đơn giá = 1.250.000",
  "nguon": "quy_tac"
}
```

- Dòng Excel = df.index + 1; chữ cột qua `openpyxl.utils.get_column_letter`.
- **Tái dùng code đã test kỹ** từ `validation_rules.py` cũ: `to_float`, regex phân cách nghìn, thân hàm IQR/z-score — chỉ đổi nguồn tham số từ `Config` sang `tham_so` của rule.
- **Chống noise (bắt buộc):**
  - `formula` / `totals_row` / `cross_field` **skip** ô đã fail `numeric` cùng dòng (tránh 1 ô chữ sinh 3 lỗi cascade).
  - Dòng trong `total_row_idxs` loại khỏi `not_blank` / `outlier` / `unique`.
  - `chua_nop` suppress các finding `THIEU` từng ô của dòng đó.
  - Dedupe theo key `(o hoặc vi_tri, loai_loi, rule_id)`.

---

## 7. AI ĐỀ XUẤT RULE + PROFILE

### 7a. `src/rule_infer.py` — 4 bước

**Bước 1 — Baseline heuristic (offline, LUÔN chạy, không cần API key):**
| Điều kiện phát hiện | Rule sinh ra |
|---|---|
| Cột fill > 90% | `not_blank` |
| Cột ≥ `numeric_ratio_threshold` (0.6) giá trị là số | `numeric` (kèm cờ phân cách nghìn) |
| Header khớp keyword phone (`điện thoại`, `sđt`...) | `phone` |
| Cột text ≤ 5 giá trị distinct trên ≥ 8 dòng | `allowed_values` |
| Cột số | `outlier` |
| Có cột định danh (text, unique cao, bên trái) | `chua_nop`, `unique` |
| Phát hiện dòng tổng | `totals_row` |

Tag `nguon="he_thong"`. → **App dùng được đầy đủ không cần API key.**

**Bước 2 — AI đề xuất (1 call Gemini duy nhất / workbook MỚI):**
- Payload mỗi sheet: tên sheet, `context_lines`, header, 8 dòng mẫu + dòng tổng nếu có, thống kê fill/numeric từng cột.
- Prompt tiếng Việt, nội dung bắt buộc:
  - Catalog 12 loại rule + shape `tham_so` chính xác + 1 ví dụ mỗi loại.
  - *"Chỉ đề xuất `formula` / `cross_field` / `totals_row` khi dữ liệu mẫu xác nhận quan hệ đó trên ≥ 80% dòng."*
  - *"`mo_ta` phải là MỘT câu tiếng Việt đơn giản cho người không rành máy tính."*
  - *"Chỉ trả về JSON array, không giải thích."*
- Gọi với `temperature=0.0, response_mime_type="application/json"`. Parse bằng `_parse_json_array` (salvage). **Validate từng rule qua `rules_schema`** — loại unknown type/field.

**Bước 3 — Verify deterministic rule AI:**
- Chạy thử từng rule `formula`/`cross_field`/`totals_row`/`value_range` do AI đề xuất trên dữ liệu đã parse.
- Fail > 30% dòng → vẫn hiện nhưng `bat=false` + nối vào `mo_ta`: *"(AI đề xuất — dữ liệu mẫu không khớp, hãy cân nhắc)"*.

**Bước 4 — Merge** baseline + AI, dedupe theo `(loai, sheet, sorted(cột đích), params)`.

### 7b. `src/profile_store.py`

- **Fingerprint sheet** = `md5("|".join(norm_text(h) for h in header))`. **Fingerprint workbook** = md5 của các fingerprint sheet đã sort.
- File `profiles/<slug>.json`:

```json
{
  "phien_ban": 1,
  "ten": "Báo cáo tổng hợp thôn",
  "ngay_tao": "2026-07-14T...", "ngay_cap_nhat": "...",
  "sheets": [{"ten_sheet": "Tong hop", "van_tay": "ab12...", "tieu_de": ["Thôn", "CT01", ...], "dong_tieu_de": 3}],
  "quy_tac": [ /* rule JSON như mục 4 */ ]
}
```

- **Thứ tự match khi upload:**
  1. Trùng fingerprint workbook → load im lặng, hiện "Đã nhận diện mẫu 'Báo cáo tổng hợp thôn'".
  2. Trùng fingerprint 1 sheet → load profile đó, sheet lạ chạy inference bổ sung.
  3. Fuzzy: Jaccard trên token header đã normalize ≥ 0.85 → load kèm banner *"Có vẻ giống mẫu 'X' — đang dùng quy tắc đã lưu. Bấm 'Đề xuất lại' nếu không đúng."*
  4. Không match → chạy inference (7a) → người dùng duyệt 1 lần ở Bước 2 → save profile.
- → **Re-upload cùng loại báo cáo = 0 thao tác cấu hình** (yêu cầu #4).
- **Ship sẵn `profiles/bao-cao-thon-ct.json`**: 7 logic rule CT cũ chuyển thành `cross_field` + rule phone/blank/sep/outlier → tri thức hardcode cũ thành data, smoke test offline vẫn deterministic.

### 7c. `src/ai_validator.py` (viết lại — lớp phụ, mặc định TẮT)

AI audit bổ sung sau engine: input = sample sheet compact + rule đang bật + finding đã có; output giới hạn enum `{THIEU, SAI_DINH_DANG, SAI_LOGIC, SAI_CONG_THUC, BAT_THUONG, KHAC}`, normalize qua whitelist `_normalize_ai_finding` (giữ pattern cũ), tag `nguon="ai_audit"`, UI hiển thị tách riêng kèm nhãn "AI phát hiện thêm (cần kiểm chứng)".

---

## 8. UI WIZARD — `app/streamlit_app.py` (viết lại toàn bộ)

**Session state**: `step: int(1-4)`, `file_bytes_hash`, `file_name`, `parsed_sheets`, `profile_match: {profile, kieu: "chinh_xac"|"gan_giong"|"moi"}`, `rules: list[dict]`, `findings`, `ingested: bool`, `messages`.
**Chống rerun đắt tiền**: parse + AI inference cache theo `file_bytes_hash` trong session_state — mọi click widget của Streamlit rerun cả script, KHÔNG được gọi lại Gemini.

Thanh bước trên cùng: `① Tải file → ② Duyệt quy tắc → ③ Kết quả kiểm tra → ④ Hỏi đáp` (badge màu, bước hiện tại đậm).

**Bước 1 — Tải file lên**
- 1 `st.file_uploader` to, `type=["xlsx","xls"]`, 1 file/lần (đơn giản cho người lớn tuổi). PDF chuyển vào expander nhỏ "Tài liệu khác (PDF)" → đi thẳng index, không qua validate.
- Upload xong: parse → fingerprint → match/infer, spinner *"AI đang đọc file và đề xuất quy tắc kiểm tra…"*
- Card kết quả: *"✅ Đã nhận file BC_T17.xlsx — 3 trang tính, 22 dòng dữ liệu"* + dòng trạng thái profile (nhận diện mẫu cũ / mẫu mới).
- Nút primary to: **"Tiếp tục ▶"**.

**Bước 2 — Duyệt quy tắc kiểm tra**
- Nhóm theo sheet. Mỗi rule = 1 dòng: `st.checkbox("🔴 Cột 'Thành tiền' phải bằng 'Số lượng' nhân 'Đơn giá'", value=rule["bat"])` — không JSON, không thuật ngữ.
- Nút "Chọn tất cả" / "Bỏ chọn tất cả".
- Nếu là mẫu mới: `st.text_input("Tên mẫu báo cáo", value=<tên gợi ý từ tên file/sheet>)`.
- 1 nút primary to: **"✅ Kiểm tra dữ liệu"** → chạy engine + save/update profile → sang Bước 3.

**Bước 3 — Kết quả kiểm tra**
- Hàng `st.metric`: 🔴 Nghiêm trọng: N | 🟡 Cần xem: N | 🔵 Lưu ý: N.
- 0 lỗi → `st.success("Không phát hiện lỗi nào 🎉")` to.
- `st.dataframe` với `column_config` nhãn tiếng Việt: Vị trí / Mô tả lỗi / Mức độ; `st.selectbox` lọc theo loại lỗi.
- **CSV export encode `utf-8-sig`** (fix bug hiện tại: `utf-8` không BOM mở Excel vỡ font tiếng Việt).
- Nút "◀ Sửa quy tắc" và "Tiếp tục: Đưa vào hệ thống ▶". Còn lỗi 🔴 → `st.warning` cảnh báo nhưng **không chặn** (giữ hành vi hiện tại).

**Bước 4 — Đưa vào hệ thống & Hỏi đáp**
- Nút **"📥 Đưa dữ liệu vào hệ thống"** → `normalize_records` → `upsert_records` (code cũ).
- Block chat giữ gần nguyên bản hiện tại (messages + expander Nguồn).
- Nút "➕ Kiểm tra file khác" → reset state bước 1–3, **giữ** `messages`.
- Sidebar rút gọn: trạng thái API key, danh sách file đã nạp + nút xoá từng file, nút xoá toàn bộ, toggle AI audit.

---

## 9. THỨ TỰ TRIỂN KHAI — mỗi bước có tiêu chí nghiệm thu

| # | Việc | Nghiệm thu (chạy được mới sang bước sau) |
|---|---|---|
| 1 | `src/textutil.py` + `src/table_extract.py` | Script scratchpad in ParsedSheet của cả 4 file `data/*.xlsx`. **Kỳ vọng**: sheet "Tong hop" header row 3 (0-based), sheet "Phiếu báo cáo" header row 12, kv metadata bắt được. ⚠️ Chạy với `PYTHONIOENCODING=utf-8` (console Windows cp1252 crash tiếng Việt) |
| 2 | `src/rules_schema.py` + `src/rule_engine.py` | Viết tay 1 profile JSON, chạy engine trên `data/test_validate.xlsx` → bắt đủ **6 lỗi cũ**: Phước Thái (THIEU), Hòa Khương Tây (chữ trong cột số), Phước Hưng (1.000), Trước Đông (outlier), Mỹ Sơn (CT03>CT01), Ninh An (chưa nộp). Đáp án ở sheet "Loi co y (dap an)" trong `TONG_HOP...xlsx` |
| 3 | `src/profile_store.py` + ship `profiles/bao-cao-thon-ct.json` | Round-trip save/load; đổi 1 header rồi upload lại → fuzzy match ≥ 0.85 vẫn nhận ra |
| 4 | Sinh `data/test_hoa_don.xlsx` (script openpyxl một lần) | File có cột Số lượng / Đơn giá / Thành tiền + dòng "Tổng cộng"; cài sẵn 2 lỗi formula + 1 sai tổng + 1 ô trống |
| 5 | `src/rule_infer.py` (baseline trước, AI sau) + `src/ai_validator.py` | Baseline offline trên `test_hoa_don.xlsx` ra được not_blank/numeric/totals_row. Có API key: AI phải đề xuất được rule `formula` Thành tiền = SL × Đơn giá |
| 6 | Viết lại `src/validate.py` + `src/extract.py` | Record RAG giữ đúng format flatten cũ — spot-check chuỗi "Thôn Hòa Trung … CT03 …" |
| 7 | Viết lại `app/streamlit_app.py` (wizard) | `streamlit run app/streamlit_app.py`: đi đủ 4 bước với `TONG_HOP...xlsx` (đường auto-match profile) và `test_hoa_don.xlsx` (đường AI infer); chat thử *"Thôn Hòa Trung có bao nhiêu hộ nghèo?"* |
| 8 | Viết lại `tests/smoke_test.py` | `python tests/smoke_test.py` pass offline: parse 4+1 file, validate bằng shipped profile (6 lỗi cũ) + baseline (test_hoa_don), giữ lexical ranking check cũ. Phần cần API sau `RUN_API_TESTS=1`, thêm 1 call rule-inference |
| 9 | Dọn: xoá `schema_infer.py` + `validation_rules.py`, cập nhật `config.py`, `requirements.txt` (+xlrd), `README.md` | Smoke test vẫn pass sau khi xoá; grep không còn import 2 file cũ |

---

## 10. RỦI RO & CÁCH XỬ LÝ

| Rủi ro | Xử lý trong v1 |
|---|---|
| **Merged cell / header nhiều tầng** (failure mode #1 của Excel hành chính VN) | Join header 2 dòng + forward-fill ngang; sâu hơn → profile có `dong_tieu_de` cho phép override tay sau này |
| `2.450` nhập nhằng nghìn/thập phân | Cờ per-rule `bao_phan_cach_nghin`; dữ liệu hành chính VN đa số số nguyên; sai thì người dùng bỏ tick rule |
| AI đề xuất rule sai | 3 lớp chặn: catalog loại cố định + schema validation → verify trên dữ liệu mẫu (fail >30% → `bat=false`) → người dùng duyệt. Finding luôn từ engine |
| Nhận nhầm dòng tổng (thôn tên "Tổng...") | Điều kiện kép: keyword **và** dòng đa số là số; `totals_row` không thấy dòng tổng → note mức thấp, không đoán |
| Fingerprint gãy khi user sửa 1 header | Fuzzy Jaccard ≥ 0.85 fallback + banner hiển thị rõ + nút "Đề xuất lại" |
| Streamlit rerun gọi lại Gemini tốn quota | Mọi artifact đắt (parse/inference/findings) nằm trong session_state key theo file hash; chỉ 1 call inference / loại báo cáo mới |
| File .xls cũ | Thêm `xlrd`; ô công thức Excel đọc giá trị cache — rule formula validate trên giá trị cache là đúng hành vi, ghi chú README |
| Không có API key | Baseline heuristic vẫn cho validate đầy đủ mức cơ bản; chỉ mất phần AI đề xuất formula/cross_field |
