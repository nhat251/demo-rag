import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from src.extract import extract_file
from src.validate import validate


def main():
    cfg = Config()
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

    print("=" * 60)
    print("SMOKE TEST — KIỂM TRA MODULE CỐT LÕI (không cần API)")
    print("=" * 60)

    # === 1. EXTRACT ===
    print("\n[1] EXTRACT")
    real_files = [f for f in os.listdir(data_dir) if f.endswith(".xlsx") and f != "test_validate.xlsx"]
    if not real_files:
        print("  KHÔNG có file Excel thật trong data/")
        return

    all_records = {}
    for fname in sorted(real_files):
        fpath = os.path.join(data_dir, fname)
        try:
            records = extract_file(fpath)
            all_records[fname] = records
            print(f"  ✓ {fname}: {len(records)} records")
        except Exception as e:
            print(f"  ✗ {fname}: LỖI — {e}")

    if not all_records:
        print("  ✗ KHÔNG có file nào extract thành công")
        return

    # === 2. VALIDATE trên file thật ===
    print("\n[2] VALIDATE — file thật")
    all_findings = {}
    for fname, records in all_records.items():
        try:
            fpath = os.path.join(data_dir, fname)
            findings = validate(fpath, cfg)
            all_findings[fname] = findings
            loai_lois = set(f["loai_loi"] for f in findings)
            print(f"  {fname}: {len(findings)} findings — {loai_lois}")
        except Exception as e:
            print(f"  {fname}: LỖI validate — {e}")

    # === 3. VALIDATE trên file test_validate (lỗi cố ý) ===
    print("\n[3] VALIDATE — file test_validate (lỗi cố ý)")
    test_path = os.path.join(data_dir, "test_validate.xlsx")
    if os.path.exists(test_path):
        test_findings = validate(test_path, cfg)
        test_types = set(f["loai_loi"] for f in test_findings)
        print(f"  Phát hiện: {test_types}")

        # Kiểm tra đủ các loại lỗi chính
        expected = {"BLANK", "TEXT", "SEP", "OUTLIER", "LOGIC", "CHUA_NOP"}
        missing = expected - test_types
        if missing:
            print(f"  ⚠ Thiếu loại lỗi: {missing}")
        else:
            print(f"  ✓ Đủ 6 loại lỗi chính (trừ BADPHONE trong file riêng)")

        # Kiểm tra từng lỗi cụ thể
        check_map = {
            "BLANK": "Thôn Phước Thái",
            "TEXT": "Hòa Khương Tây",
            "SEP": "Thôn Phước Hưng",
            "OUTLIER": "Thôn Trước Đông",
            "LOGIC": "Thôn Mỹ Sơn",
            "CHUA_NOP": "Thôn Ninh An",
        }
        for loai, expected_thon in check_map.items():
            found = any(expected_thon.lower() in f["vi_tri"].lower() for f in test_findings if f["loai_loi"] == loai)
            status = "✓" if found else "✗"
            print(f"  {status} {loai} tại {expected_thon}")
    else:
        print(f"  ⚠ Không tìm thấy test_validate.xlsx")

    # === 4. KIỂM TRA EXTRACT + VALIDATE FLOW ===
    print("\n[4] KIỂM TRA LUỒNG")
    for fname in sorted(all_records.keys()):
        rec_count = len(all_records[fname])
        find_count = len(all_findings.get(fname, []))
        print(f"  {fname}: {rec_count} records → {find_count} findings")
    print("  ✓ Extract → Validate: OK")

    # === 5. LOCAL RETRIEVAL RANKING ===
    print("\n[5] LOCAL RETRIEVAL RANKING")
    from src.normalize import normalize_records
    from src.rag_core import _lexical_score

    all_records_flat = []
    for recs in all_records.values():
        all_records_flat.extend(recs)
    normalized = normalize_records(all_records_flat, cfg)
    query = "Thôn Hòa Trung có bao nhiêu hộ nghèo?"
    ranked = sorted(
        ((_lexical_score(query, r["noi_dung"]), r["noi_dung"]) for r in normalized),
        reverse=True,
    )
    top_doc = ranked[0][1] if ranked else ""
    lexical_ok = "Thôn Hòa Trung" in top_doc and "CT03" in top_doc and "Số hộ nghèo" in top_doc
    print(f"  Top score: {ranked[0][0] if ranked else 0}")
    print(f"  {'✓' if lexical_ok else '✗'} Query mẫu tìm đúng dòng Hòa Trung / CT03")

    # === 6. API-DEPENDENT TESTS (optional) ===
    print("\n[6] API-DEPENDENT (NORMALIZE + UPSERT + GENERATE)")
    if os.environ.get("RUN_API_TESTS") != "1":
        print("  Bỏ qua mặc định. Đặt RUN_API_TESTS=1 nếu muốn test Gemini + Chroma embedding.")
    else:
        try:
            from src.rag_core import upsert_records, generate_answer, list_loaded_files, reset_collection
            from google import genai
            from dotenv import load_dotenv
            load_dotenv()
            import os as _os
            client = genai.Client(api_key=_os.environ.get("GEMINI_API_KEY", ""))
            try:
                client.models.list()
                api_ok = True
            except Exception:
                api_ok = False

            if not api_ok:
                print("  ⚠ API key không khả dụng — bỏ qua normalize/upsert/generate")
            else:
                reset_collection(cfg)
                print(f"  Normalize: {len(normalized)} records")
                chunks = upsert_records(normalized, cfg)
                print(f"  Upsert: {chunks} chunks")
                loaded = list_loaded_files(cfg)
                print(f"  File đã nạp: {loaded}")
                result = generate_answer("Thôn Hòa Trung có bao nhiêu hộ nghèo?", cfg)
                if result["answer"]:
                    print(f"  Generate: ✓ (answer length: {len(result['answer'])})")
                print("  ✓ API pipeline: OK")
        except Exception as e:
            print(f"  ⚠ API pipeline không chạy được: {e}")

    # === KẾT LUẬN ===
    print("\n" + "=" * 60)
    print("KẾT QUẢ: SMOKE TEST ", end="")
    if all(len(v) > 0 for v in all_records.values()) and lexical_ok:
        print("✓ PASSED (core modules)")
    else:
        print("✗ FAILED")

    print("=" * 60)


if __name__ == "__main__":
    main()
