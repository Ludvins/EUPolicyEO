import pytest

from eupolicyeo.generation import (
    BriefClaim,
    BriefClaims,
    BriefSource,
    Duty,
    GenerationError,
    LegalDraft,
    Ollama,
    Quote,
    generate_brief,
    validate_brief,
    validate_legal_draft,
)


def source(id_, kind, text):
    return BriefSource(id=id_, kind=kind, title=id_, text=text, url="https://example.org/source")


def test_legal_draft_checks_offsets_and_inherited_modal():
    entries = {
        "parent": source("parent", "law", "Member States shall monitor the following:"),
        "child": source("child", "law", "tree canopy cover within urban ecosystem areas;"),
    }
    duty = Duty(
        target_quote=entries["child"].text,
        modality="obligation",
        modal_quote=Quote(source_id="parent", text="shall"),
        actor=Quote(source_id="parent", text="Member States"),
        action=Quote(source_id="parent", text="monitor"),
        scope=Quote(source_id="child", text="tree canopy cover"),
        area=Quote(source_id="child", text="within urban ecosystem areas"),
        frequency=None,
        deadline=None,
    )
    [result] = validate_legal_draft(LegalDraft(requirements=[duty]), "child", entries)
    offset = result["modal_quote"]
    assert entries["parent"].text[offset["start"] : offset["end"]] == "shall"
    duty.frequency = Quote(source_id="parent", text="the following")
    with pytest.raises(GenerationError, match="frequency quote needs evidence"):
        validate_legal_draft(LegalDraft(requirements=[duty]), "child", entries)


def test_brief_rejects_invented_source_numbers_and_quotes():
    rows = {"a": source("a", "product", "The product has nominal 10 m resolution.")}
    claim = BriefClaim(
        kind="contribution",
        statement="The product has 10 m resolution.",
        citations=[Quote(source_id="a", text="nominal 10 m resolution")],
    )
    draft = BriefClaims(claims=[claim])
    assert validate_brief(draft, rows)[0]["citations"][0]["start"] == 16

    claim.statement = "The product has 20 m resolution."
    with pytest.raises(GenerationError, match="Numerical claim"):
        validate_brief(draft, rows)

    claim.citations = [Quote(source_id="b", text="nominal 20 m resolution")]
    with pytest.raises(GenerationError, match="outside the supplied evidence"):
        validate_brief(draft, rows)

    claim.citations = [Quote(source_id="a", text="nominal 20 m resolution")]
    with pytest.raises(GenerationError, match="not verbatim"):
        validate_brief(draft, rows)

    rows["a"].assessment_status = "fails"
    claim.statement = "The product has 10 m resolution."
    claim.citations = [Quote(source_id="a", text="nominal 10 m resolution")]
    with pytest.raises(GenerationError, match="failed assessment"):
        validate_brief(draft, rows)


def test_unrelated_question_does_not_invoke_a_model():
    sources = [source("lc", "product", "Urban canopy coverage from tree crown rasters.")]
    result = generate_brief("When does the train depart?", sources, engine=None)
    assert result["status"] == "insufficient_evidence"
    assert result["model"] is None
    assert result["retrieved_sources"] == []


def test_ollama_rejects_remote_origins_and_cloud_tags():
    with pytest.raises(ValueError, match="loopback"):
        Ollama(url="http://127.0.0.1@example.org:11434")
    with pytest.raises(ValueError, match="installed local model"):
        Ollama(model="model:cloud")
