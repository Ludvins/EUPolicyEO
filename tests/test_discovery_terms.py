from eupolicyeo.discovery_terms import (
    DISCOVERY_TERMS,
    MAX_DISCOVERY_TERMS,
    project_discovery_terms,
)


def test_normalizes_method_mentions_to_fixed_discovery_labels():
    objective = (
        "We plan passive acoustic-recording and Ｆｉｅｌｄ sampling, with e‑DNA "
        "and airborne laser scanning. The work explores soil-organic-carbon stocks "
        "and catchment modeling."
    )
    assert project_discovery_terms(objective) == [
        "LiDAR",
        "acoustic monitoring",
        "catchment modelling",
        "environmental DNA",
        "field sampling",
        "soil carbon stocks",
        "soil organic carbon",
    ]


def test_omits_unmatched_text_and_partial_word_matches():
    objective = (
        "Project contact Example Person. glimmeredna aqUiferous LiDARdetector. "
        "We analyze sound recordings of music and use laser scanning microscopy."
    )
    assert project_discovery_terms(objective) == []
    assert project_discovery_terms(None) == []
    assert project_discovery_terms("   ") == []


def test_discovery_labels_are_unique_sorted_and_bounded():
    terms = sorted(DISCOVERY_TERMS, reverse=True)
    labels = project_discovery_terms(" / ".join(terms + terms))
    assert len(labels) == MAX_DISCOVERY_TERMS
    assert labels == sorted(set(labels))
    assert set(labels) <= DISCOVERY_TERMS
