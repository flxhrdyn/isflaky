from isflaky.core.models import Failure, Label, LabeledFailure, Provenance
from isflaky.mine.dataset import read_dataset, write_dataset


def make_record(test_id: str, label: Label) -> LabeledFailure:
    return LabeledFailure(
        failure=Failure(test_id, "boom", "trace", "context", 12),
        label=label,
        provenance=Provenance("acme/proj", 101, 1, "aaa111", "https://example.test/101"),
    )


def test_roundtrip_preserves_every_field(tmp_path):
    path = tmp_path / "dataset.jsonl"
    written = write_dataset([make_record("tests/a.py::test_x", Label.FLAKY)], path)
    assert written == 1

    restored = read_dataset(path)
    assert restored[0].failure.test_id == "tests/a.py::test_x"
    assert restored[0].failure.traceback == "trace"
    assert restored[0].label is Label.FLAKY
    assert restored[0].provenance.head_sha == "aaa111"


def test_one_json_object_per_line(tmp_path):
    path = tmp_path / "dataset.jsonl"
    write_dataset(
        [make_record("tests/a.py::test_x", Label.FLAKY), make_record("tests/b.py::test_y", Label.REAL)],
        path,
    )
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_write_is_resumable_by_appending(tmp_path):
    path = tmp_path / "dataset.jsonl"
    write_dataset([make_record("tests/a.py::test_x", Label.FLAKY)], path)
    write_dataset([make_record("tests/b.py::test_y", Label.REAL)], path)
    assert len(read_dataset(path)) == 2
