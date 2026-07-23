import json
from pathlib import Path

from product_image_batch.core.metadata import MetadataWriter, read_jsonl
from product_image_batch.core.models import ErrorRecord, MetadataRecord


def _record(status="success", task_id="t1"):
    return MetadataRecord(
        task_id=task_id, status=status, provider="mock", model="mock-v1",
        prompt_id="p001", prompt_text="hello",
        output_files=["images/a.png"], parameters={"size": "1024x1024"},
    )


def test_jsonl_valid_on_success_and_error(tmp_path: Path):
    w = MetadataWriter(tmp_path)
    w.write_record_sync(_record("success", "t1"))
    w.write_error_sync(ErrorRecord(
        task_id="t2", provider="mock", model="mock-v1", prompt_id="p002",
        error_type="ProviderRateLimitError", http_status=429,
        message="slow down", retryable=True, attempts=2,
    ))
    w.write_record_sync(_record("failed", "t2"))

    md = read_jsonl(tmp_path / "metadata.jsonl")
    errs = read_jsonl(tmp_path / "errors.jsonl")
    assert len(md) == 2
    assert len(errs) == 1
    # every line parses as JSON and has the required keys
    for line in md:
        assert "task_id" in line and "status" in line and "created_at_utc" in line
    assert errs[0]["error_type"] == "ProviderRateLimitError"


def test_csv_finalization(tmp_path: Path):
    w = MetadataWriter(tmp_path)
    w.write_record_sync(_record("success", "t1"))
    csv_path = w.finalize_csv()
    assert csv_path.exists()
    text = csv_path.read_text(encoding="utf-8")
    assert "task_id" in text.splitlines()[0]  # header present
    assert "t1" in text


def test_counts_track_success_and_error(tmp_path: Path):
    w = MetadataWriter(tmp_path)
    w.write_record_sync(_record("success", "t1"))
    w.write_record_sync(_record("success", "t2"))
    w.write_error_sync(ErrorRecord(
        task_id="t3", provider="mock", model="mock-v1", prompt_id="p",
        error_type="X", message="m",
    ))
    assert w.success_count == 2
    assert w.error_count == 1


def test_list_fields_serialized_as_json_in_csv(tmp_path: Path):
    w = MetadataWriter(tmp_path)
    w.write_record_sync(_record("success", "t1"))
    w.finalize_csv()
    # reload csv line and ensure output_files is a JSON string cell
    import csv as _csv

    with (tmp_path / "metadata.csv").open() as fh:
        rows = list(_csv.DictReader(fh))
    assert json.loads(rows[0]["output_files"]) == ["images/a.png"]
