from .evidence_uses import ARTICLE20_EVIDENCE
from .schemas import LegalSection, RetrievalProfile

HABITAT = ["habitat", "habitats", "ecosystem", "ecosystems", "land cover", "wetland", "wetlands"]
CONDITION = ["condition", "quality", "change", "changes", "trend", "trends", "restoration"]
BIRDS = ["bird", "birds", "avian", "breeding birds"]

# The groups are alternative phrases for the observables in Article 20(1)
# and its cited indicator definitions. Every group needs metadata evidence.
ARTICLE20_PROFILES = {
    "a": RetrievalProfile(
        query="habitat condition restoration ecological monitoring vegetation change",
        evidence_groups=[HABITAT, CONDITION],
    ),
    "b": RetrievalProfile(
        query="urban tree canopy cover urban green space tree cover density",
        evidence_groups=[
            ["urban", "city", "cities", "settlement", "settlements", "tree cover density"],
            [
                "canopy",
                "tree cover",
                "green space",
                "green spaces",
                "urban vegetation",
                "urban greening",
            ],
        ],
    ),
    "c": RetrievalProfile(
        query="grassland butterfly index cropland soil organic carbon hedgerows agricultural landscape features",
        evidence_groups=[
            [
                "grassland butterfly",
                "grassland butterflies",
                "soil organic carbon",
                "organic carbon in cropland",
                "hedgerow",
                "hedgerows",
                "landscape features",
            ]
        ],
    ),
    "d": RetrievalProfile(
        query="farmland birds population monitoring breeding bird index",
        evidence_groups=[BIRDS, ["farmland", "agricultural", "agriculture", "cropland"]],
    ),
    "e": RetrievalProfile(
        query="common forest bird index forest birds population abundance monitoring",
        evidence_groups=[BIRDS, ["forest", "forests", "woodland", "woodlands"]],
    ),
    "f": RetrievalProfile(
        query="forest deadwood structure connectivity organic carbon native tree species diversity",
        evidence_groups=[
            ["forest", "forests", "woodland", "woodlands"],
            [
                "deadwood",
                "dead wood",
                "forest structure",
                "connectivity",
                "organic carbon",
                "native tree species",
                "tree species diversity",
                "uneven aged",
            ],
        ],
    ),
    "g": RetrievalProfile(
        query="pollinator species abundance diversity population monitoring wild bee surveys",
        evidence_groups=[
            [
                "pollinator",
                "pollinators",
                "pollination",
                "wild bee",
                "wild bees",
                "bumblebee",
                "bumblebees",
            ],
            [
                "abundance",
                "diversity",
                "monitoring",
                "survey",
                "surveys",
                "population",
                "populations",
                "biodiversity",
            ],
        ],
    ),
    "h": RetrievalProfile(
        query="habitat extent distribution condition mapping ecosystem monitoring",
        evidence_groups=[HABITAT, ["extent", "distribution", "condition", "mapping", "monitoring"]],
    ),
    "i": RetrievalProfile(
        query="species habitat extent habitat quality suitability monitoring",
        evidence_groups=[
            ["species", "wildlife"],
            [
                "habitat quality",
                "habitat extent",
                "habitat condition",
                "habitat suitability",
                "habitat mapping",
                "habitat distribution",
            ],
        ],
    ),
    "j": RetrievalProfile(
        query="habitat loss deterioration degradation change monitoring restoration compensation",
        evidence_groups=[
            HABITAT,
            ["loss", "deterioration", "degradation", "change", "changes", "compensation"],
        ],
    ),
}


def article20_profile(section: LegalSection) -> RetrievalProfile | None:
    if (section.celex, section.article) != ("32024R1991", "20"):
        return None
    if section.paragraph == "1" and section.point:
        profile = ARTICLE20_PROFILES.get(section.point)
        if profile:
            return profile.model_copy(
                update={"record_evidence": ARTICLE20_EVIDENCE.get(section.point, {})}
            )
        return None
    # Timing, monitoring methods, administration and permissions are legal evidence.
    return RetrievalProfile(query=None)
