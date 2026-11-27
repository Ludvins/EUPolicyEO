import pytest

from eupolicyeo.discovery import CHUNK_OVERLAP, CHUNK_WORDS, description_passages
from eupolicyeo.measurements import catalogue_measurements
from eupolicyeo.storage import file_hash, write_json


def test_passages_keep_relevant_evidence_beyond_first_encoder_input():
    words = [str(i) for i in range(CHUNK_WORDS * 2)]
    chunks = list(description_passages(" ".join(words)))
    assert all(0 < len(chunk.split()) <= CHUNK_WORDS for chunk in chunks)
    assert chunks[0].split()[-CHUNK_OVERLAP:] == chunks[1].split()[:CHUNK_OVERLAP]
    assert chunks[-1].split()[-1] == words[-1]


def test_public_measurement_labels_require_archived_variable_evidence(tmp_path):
    raw = tmp_path / "cdse-002.raw"
    write_json(
        raw,
        {
            "collections": [
                {
                    "id": "measurement",
                    "bands": [{"description": "Mean concentration of chlorophyll-a"}],
                },
                {"id": "uncertainty", "bands": [{"description": "Uncertainty in chlorophyll-a"}]},
                {"id": "description-only", "description": "chlorophyll-a", "bands": None},
            ]
        },
    )
    write_json(
        tmp_path / "manifest.json",
        {
            "snapshot_id": tmp_path.name,
            "status": "success",
            "pages": [{"source": "cdse", "path": raw.name, "sha256": file_hash(raw)}],
        },
    )
    terms = catalogue_measurements(tmp_path)
    assert list(terms) == ["cdse:measurement"]
    assert terms["cdse:measurement"][0].label == "chlorophyll-a concentration"
    raw.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        catalogue_measurements(tmp_path)
