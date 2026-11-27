"""Discovery labels for method and measurement terms mentioned in project objectives."""

import re
import unicodedata

MAX_DISCOVERY_TERMS = 16
_SEPARATORS = re.compile(r"[^a-z0-9]+")

# The returned labels are authored here. Matched substrings are discarded.
_ALIASES = {
    "acoustic monitoring": r"passive acoustic(?: monitoring| record(?:ing|ers?))?|acoustic surveys?|bio ?acoustic(?:s| monitoring)|acoustic monitoring",
    "acoustic telemetry": r"acoustic telemetry|acoustic tag(?:s|ging)",
    "aerial imagery": r"aerial (?:imagery|images?|photograph(?:s|y))|airborne imagery|orthophotos?",
    "aquatic vegetation": r"aquatic vegetation|aquatic macrophytes?|submerged vegetation",
    "biodiversity monitoring": r"biodiversity (?:monitoring|surveys?|assessment)|monitoring biodiversity|species inventories",
    "canopy height": r"canopy height|tree height",
    "catchment modelling": r"catchment model(?:s|l?ing)|hydrologic(?:al)? model(?:s|l?ing)",
    "change detection": r"change detection|detecting (?:land cover|forest cover|land use) change",
    "citizen science": r"citizen science|community based monitoring",
    "coastal erosion": r"coastal erosion|shoreline retreat|shoreline change",
    "crop phenology": r"crop phenology|crop development stages",
    "deadwood": r"dead ?wood|coarse woody debris|standing dead trees|fallen logs",
    "drone surveys": r"drone (?:imagery|mapping|survey(?:s|ing))|unmanned aerial vehicles?|uavs?",
    "ecosystem restoration": r"(?:ecosystem|ecological|habitat) restoration|restoration of (?:habitats|ecosystems)",
    "environmental DNA": r"environmental dna|e ?dna",
    "field sampling": r"field (?:sampling|surveys?|observations?|measurements?|campaigns?)|in situ (?:sampling|surveys?|observations?|measurements?)",
    "forest biomass": r"forest biomass|woody biomass|tree biomass|above ground biomass",
    "forest disturbance": r"forest disturbances?|forest damage|tree mortality",
    "forest structure": r"forest structure|forest structural diversity|canopy structure",
    "freshwater monitoring": r"freshwater monitoring|river monitoring|monitoring of (?:rivers|streams|freshwater)",
    "groundwater": r"groundwater|ground water|aquifers?",
    "habitat mapping": r"habitat mapping|mapping (?:marine |coastal |terrestrial )?habitats|habitat (?:classification|maps)",
    "habitat suitability": r"habitat suitability|suitable habitats?",
    "hydroperiod": r"hydroperiods?|inundation duration|duration of inundation",
    "hyperspectral imaging": r"hyperspectral (?:imagery|imaging|images|sensing|data)",
    "land cover mapping": r"land cover (?:mapping|maps?|classification)|land cover change",
    "land use mapping": r"land use (?:mapping|maps?|classification)|land use change",
    "LiDAR": r"li ?dar|(?:airborne|terrestrial|mobile) laser scan(?:s|ning)|laser altimetry",
    "metabarcoding": r"meta ?barcoding",
    "multispectral imaging": r"multi ?spectral (?:imagery|imaging|images|data)",
    "ocean colour": r"ocean colou?r",
    "optical imagery": r"optical (?:imagery|images)|optical satellite data",
    "peatland restoration": r"peatland restoration|peatland rewetting|rewetting peatlands",
    "pollinator monitoring": r"pollinator (?:monitoring|surveys?|sampling)|monitoring (?:wild )?pollinators|surveying pollinators",
    "remote sensing": r"remote sensing|earth observation",
    "river discharge": r"river discharge|stream discharge|streamflow|stream flow",
    "satellite imagery": r"satellite (?:imagery|images|data)|spaceborne imagery",
    "seagrass": r"sea ?grass(?:es)?",
    "sediment transport": r"sediment transport|sediment loads?|sediment flux",
    "snow cover": r"snow cover|snow covered area|snow extent|snowpack extent",
    "soil carbon stocks": r"soil (?:organic )?carbon stocks?|stocks? of (?:soil )?organic carbon",
    "soil erosion": r"soil erosion|erosion of (?:top)?soil|soil loss",
    "soil moisture": r"soil moisture|soil water content",
    "soil organic carbon": r"soil organic carbon|organic carbon in (?:the )?soil",
    "species abundance": r"species abundance|population abundance|species counts?",
    "species diversity": r"species diversity|species richness",
    "species distribution": r"species distributions?|species ranges?|distribution of species",
    "surface water extent": r"surface water extent|surface water area|inundation extent|open water extent",
    "synthetic aperture radar": r"synthetic aperture radar|sar (?:imagery|images|data)",
    "thermal imaging": r"thermal (?:infrared|imagery|imaging)|infrared thermography",
    "time series analysis": r"time series (?:analysis|modelling|modeling)|longitudinal analysis",
    "tree canopy cover": r"tree canopy cover|tree crown cover|tree cover density",
    "vegetation indices": r"vegetation index|vegetation indices|ndvi|normalized difference vegetation index",
    "water quality": r"water quality|aquatic water chemistry|water chemistry",
    "water temperature": r"(?:river |lake |ocean |sea |surface )?water temperature|sea surface temperature",
    "wetland": r"wetlands?|marshes|fens",
}
DISCOVERY_TERMS = frozenset(_ALIASES)
_PATTERNS = tuple(
    (name, re.compile(rf"\b(?:{aliases})\b")) for name, aliases in sorted(_ALIASES.items())
)


def project_discovery_terms(description: str | None) -> list[str]:
    """Return a bounded, sorted set of vocabulary labels for evidence in an objective."""
    if not description:
        return []
    text = _SEPARATORS.sub(" ", unicodedata.normalize("NFKC", description).casefold())
    return [name for name, pattern in _PATTERNS if pattern.search(text)][:MAX_DISCOVERY_TERMS]
