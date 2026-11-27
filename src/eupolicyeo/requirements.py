import re

from .legal_search import article20_profile
from .schemas import LegalSection, MonitoringRequirement
from .storage import read_json, snapshot_dir, write_json, write_table

ACTION = r"be carried out|make public|be [a-z]+|[a-z]+"
MODAL = re.compile(
    r"\b(?:(?P<actor>Member State monitoring systems|Member States|The Commission|"
    rf"Member State|The Agency)\s+)?(?P<modal>shall|may|should)\b(?:\s+(?P<action>{ACTION}))?",
    re.I,
)
LEADING_ACTION = re.compile(rf"^(?:{ACTION})\b", re.I)
MONITOR = re.compile(
    r"\b(monitor\w*|measure\w*|assess\w*|report\w*|indicator\w*|map\w*|survey\w*)\b", re.I
)
JOIN = r"(?:\s*,\s*(?:and\s+)?|\s+and\s+)"
NUMBER = r"\d+(?:\([a-z0-9]+\))*"
ARTICLE_NUMBER = rf"(?:{NUMBER}|(?:\([a-z0-9]+\))+)"
POINTS = rf"\([a-z]\)(?:{JOIN}\([a-z]\))*"
ARTICLE = re.compile(
    rf"\bArticles?\s+(?P<numbers>{NUMBER}(?:{JOIN}{ARTICLE_NUMBER})*)"
    rf"(?:,?\s+(?P<points>points?\s+{POINTS}))?"
    r"(?P<act>\s+of\s+(?:Directive|Regulation)\s+(?:\([A-Z]+\)\s+)?[\d/A-Z]+)?",
    re.I,
)
ANNEX = re.compile(rf"\bAnnex(?:es)?\s+(?P<numbers>[IVXLCDM]+(?:{JOIN}[IVXLCDM]+)*)\b", re.I)
ACT = re.compile(
    r"\b(?P<kind>Directives?|Regulations?)\s+(?P<ids>(?:\([A-Z]+\)\s+)?\d+/[\d/]+[A-Z]*"
    rf"(?:{JOIN}(?:\([A-Z]+\)\s+)?\d+/[\d/]+[A-Z]*)*)",
)
LOCAL_NUMBER = r"(?:\(\d+\)|\d+)"
LOCAL = re.compile(
    rf"\bparagraphs?\s+(?P<numbers>{LOCAL_NUMBER}(?:{JOIN}{LOCAL_NUMBER})*)"
    rf"(?:,?\s+points?\s+(?P<points>{POINTS}))?",
    re.I,
)
AREA = re.compile(
    r"\b(?:within|in) (?:the |each )?(?:urban ecosystem areas|areas subject to restoration measures)\b",
    re.I,
)
FREQUENCY = re.compile(r"\b(?:at least )?(?:every (?:[\w-]+ )?years?|annually|once a year)\b", re.I)
DEADLINE = re.compile(
    r"\b(?:(?:by|from|on) \d{1,2} [a-z]+ \d{4}|as soon as [^.]+|one year after [^.]+)",
    re.I,
)
CONDITION = re.compile(
    r"\bwhere applicable(?:, [^.;]+?(?=,\s*(?:and\s+)?paragraph\b|[.;]|$))?"
    r"|\b(?:where necessary|if|unless|provided that) [^.;]+",
    re.I,
)
EXPANSIONS = {
    "urban tree canopy": ["tree canopy cover", "urban vegetation", "land cover"],
    "habitat types": ["habitat mapping", "land cover"],
    "forest ecosystems": ["forest structure", "vegetation"],
    "marine habitat": ["marine habitat mapping", "seafloor"],
}


def _references(evidence: str, section: LegalSection) -> tuple[list[str], list[str]]:
    external = []
    articles = list(ARTICLE.finditer(evidence))
    for match in articles:
        article = ""
        for token in re.split(JOIN, match["numbers"]):
            if token[0].isdigit():
                article = token.split("(")[0]
            number = article + token if token.startswith("(") else token
            qualifier = ", " + match["points"] if match["points"] else ""
            external.append("Article " + number + qualifier + (match["act"] or ""))
    for match in ANNEX.finditer(evidence):
        external.extend("Annex " + number for number in re.split(JOIN, match["numbers"]))
    for match in ACT.finditer(evidence):
        if not any(
            start <= match.start() < end for start, end in (article.span() for article in articles)
        ):
            external.extend(
                match["kind"].removesuffix("s") + " " + act for act in re.split(JOIN, match["ids"])
            )
    prefix = f"{section.celex}:{section.language}:{section.article}"
    local = []
    for match in LOCAL.finditer(evidence):
        for number in re.findall(r"\d+", match["numbers"]):
            paragraph = f"{prefix}:{number}"
            points = re.findall(r"\(([a-z])\)", match["points"] or "", re.I)
            local.extend([f"{paragraph}:{point.lower()}" for point in points] or [paragraph])
    return list(dict.fromkeys(external)), list(dict.fromkeys(local))


def _lead_in(section: LegalSection, by_id: dict[str, LegalSection]):
    while section.parent_id in by_id:
        section = by_id[section.parent_id]
        match = MODAL.search(section.text)
        if match:
            return section, match
    return None, None


def _linked_actor(local_ids: list[str], by_id: dict[str, LegalSection]) -> str | None:
    actors = set()
    for id_ in local_ids:
        target = by_id.get(id_)
        if target:
            modal = MODAL.search(target.text) or _lead_in(target, by_id)[1]
            if modal and modal["actor"]:
                actors.add(modal["actor"])
    return next(iter(actors)) if len(actors) == 1 else None


def extract(sections: list[LegalSection]) -> list[MonitoringRequirement]:
    by_id = {s.id: s for s in sections}
    parents = {s.parent_id for s in sections if s.parent_id}
    results = []
    for section in sections:
        value = section.text
        inherited, common = _lead_in(section, by_id)
        spans = list(re.finditer(r"[^\s].*?(?:[.!?](?=\s+[A-Z]|$)|$)", value))
        for span in spans:
            evidence = span.group()
            direct = list(MODAL.finditer(evidence))
            if not common and (
                not direct or not MONITOR.search(evidence + " " + (section.title or ""))
            ):
                continue
            if section.id in parents and evidence.endswith(":"):
                continue
            external_refs, local_refs = _references(evidence, section)
            local_ids = [ref for ref in local_refs if ref in by_id and ref != section.id]
            actor = common["actor"] if common else None
            subject = evidence[: direct[0].start()].strip(" ,") if direct else ""
            for index, match in enumerate(direct or ([common] if common else [])):
                actor = match["actor"] or actor
                last = direct[index + 1].start() if index + 1 < len(direct) else len(evidence)
                clause = evidence[match.end() : last] if direct else evidence
                action = match["action"]
                if not action and not direct:
                    leading = LEADING_ACTION.match(clause)
                    if leading:
                        action, clause = leading[0], clause[leading.end() :]
                if not action:
                    continue
                action = action.lower()
                clause = clause.strip(" .;:,").removesuffix(" and").rstrip(" ,")
                observable = clause
                if subject and (action == "start" or action.startswith("be ")):
                    if action in {"start", "be carried out", "be coordinated"}:
                        actor = actor or _linked_actor(local_ids, by_id)
                    observable = (
                        subject if action in {"start", "be carried out"} else f"{subject} {clause}"
                    )
                if not observable:
                    continue
                context = " ".join(by_id[key].text for key in local_ids if by_id[key].point)
                topic = f"{observable} {context}".strip()
                expanded = list(
                    dict.fromkeys(
                        term
                        for key, terms in EXPANSIONS.items()
                        if key in topic.lower()
                        for term in terms
                    )
                )
                area = AREA.search(observable)
                freq = FREQUENCY.search(clause)
                deadline = DEADLINE.search(clause) or (
                    DEADLINE.search(subject) if not index else None
                )
                conditions = list(dict.fromkeys(CONDITION.findall(observable + ". " + clause)))
                rid = f"{section.id}:r{span.start()}" + (f".{index + 1}" if index else "")
                results.append(
                    MonitoringRequirement(
                        id=rid,
                        section_id=section.id,
                        verbatim_evidence=evidence,
                        evidence_start=span.start(),
                        evidence_end=span.end(),
                        actor=actor,
                        modality={
                            "shall": "obligation",
                            "may": "permission",
                            "should": "recommendation",
                        }[match["modal"].lower()],
                        action=action,
                        observable=observable,
                        area_text=area[0] if area else None,
                        frequency_text=freq[0] if freq else None,
                        deadline_text=deadline[0] if deadline else None,
                        conditions=conditions,
                        referenced_sections=[*external_refs, *local_refs],
                        parent_section_id=inherited.id if not direct and inherited else None,
                        parent_evidence=inherited.text if not direct and inherited else None,
                        parent_evidence_start=0 if not direct and inherited else None,
                        parent_evidence_end=len(inherited.text)
                        if not direct and inherited
                        else None,
                        extraction_method="modal-section-v3",
                        query=" ".join([action, topic, *expanded])[:2000],
                        expansions=expanded,
                        search_profile=article20_profile(section),
                    )
                )
    return results


def extract_snapshot(snapshot: str) -> list[MonitoringRequirement]:
    root = snapshot_dir(snapshot)
    sections = [LegalSection.model_validate(row) for row in read_json(root / "sections.json")]
    requirements = extract(sections)
    if not requirements:
        raise ValueError("no requirements extracted")
    write_json(root / "requirements.json", [r.model_dump(mode="json") for r in requirements])
    write_table(root / "requirements.parquet", requirements)
    return requirements
