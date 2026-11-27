from datetime import UTC, datetime

from eupolicyeo.requirements import extract
from eupolicyeo.schemas import LegalSection, Provenance


def test_timing_queries_reference_topics_and_coordinated_actions():
    provenance = Provenance(
        source="cellar",
        source_id="32024R1991",
        source_url="https://eur-lex.europa.eu",
        retrieved_at=datetime.now(UTC),
        raw_sha256="0" * 64,
        snapshot_id="fixture",
    )
    base = "32024R1991:eng:20"

    def section(paragraph, body, point=None, parent=None):
        suffix = f":{point}" if point else ""
        return LegalSection(
            id=f"{base}:{paragraph}{suffix}",
            celex="32024R1991",
            language="eng",
            article="20",
            paragraph=paragraph,
            point=point,
            parent_id=parent,
            raw_xpath="/test",
            text=body,
            provenance=provenance,
        )

    candidate = [
        section("1", "Member States shall monitor the following:"),
        section("1", "canopy cover within urban ecosystem areas;", "a", f"{base}:1"),
        section("1", "soil carbon;", "b", f"{base}:1"),
        section(
            "2",
            "The monitoring in accordance with paragraph 1, points (a) and (b), shall start on 18 August 2024.",
        ),
        section(
            "3",
            "The monitoring shall be carried out every year and shall be coordinated with the reporting cycle.",
        ),
    ]
    rows = extract(candidate)
    assert rows[2].deadline_text == "on 18 August 2024"
    assert rows[2].actor == "Member States"
    assert rows[2].referenced_sections == [f"{base}:1:a", f"{base}:1:b"]
    assert rows[2].area_text is None
    assert "canopy cover" in rows[2].query and "soil carbon" in rows[2].query
    assert "18 August 2024" not in rows[2].query
    assert [row.action for row in rows[3:]] == ["be carried out", "be coordinated"]
    assert rows[3].frequency_text == "every year"
    assert all(
        next(s for s in candidate if s.id == row.section_id).text[
            row.evidence_start : row.evidence_end
        ]
        == row.verbatim_evidence
        for row in rows
    )


def test_grouped_references_conditions_and_inherited_permission():
    provenance = Provenance(
        source="cellar",
        source_id="32024R1991",
        source_url="https://eur-lex.europa.eu",
        retrieved_at=datetime.now(UTC),
        raw_sha256="0" * 64,
        snapshot_id="fixture",
    )
    base = "32024R1991:eng:20"

    def section(suffix, body, **structure):
        return LegalSection(
            id=f"{base}:{suffix}",
            celex="32024R1991",
            language="eng",
            article="20",
            title="Monitoring",
            raw_xpath="/test",
            text=body,
            provenance=provenance,
            **structure,
        )

    provisions = [
        section("1", "Member States shall monitor the following:", paragraph="1"),
        section(
            "1:a",
            "the areas where habitat types referred to in Articles 4 and 5 have changed, using Article 15(3), point (p);",
            paragraph="1",
            point="a",
            parent_id=f"{base}:1",
        ),
        section(
            "6",
            "The monitoring in accordance with paragraph 1, point (a), concerning, where applicable, the grassland butterfly index shall be carried out every year.",
            paragraph="6",
        ),
        section(
            "9",
            "Member State monitoring systems shall operate on databases, and shall maximise data access.",
            paragraph="9",
        ),
        section("11", "The Commission may, by means of implementing acts:", paragraph="11"),
        section(
            "11:a",
            "specify monitoring methods for Annexes I and II;",
            paragraph="11",
            point="a",
            parent_id=f"{base}:11",
        ),
    ]
    habitat, annual, operate, maximise, permission = extract(provisions)
    assert habitat.referenced_sections == ["Article 4", "Article 5", "Article 15(3), point (p)"]
    assert habitat.conditions == []
    assert annual.conditions == ["where applicable, the grassland butterfly index"]
    assert (annual.actor, annual.frequency_text) == ("Member States", "every year")
    assert (operate.action, operate.observable) == ("operate", "on databases")
    assert (maximise.action, maximise.actor) == ("maximise", "Member State monitoring systems")
    assert maximise.verbatim_evidence == operate.verbatim_evidence
    assert (permission.modality, permission.actor, permission.action) == (
        "permission",
        "The Commission",
        "specify",
    )
    assert permission.referenced_sections == ["Annex I", "Annex II"]
    assert permission.parent_evidence == provisions[-2].text
