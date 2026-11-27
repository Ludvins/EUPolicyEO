from .schemas import EvidenceUse

_LAND_COVER = EvidenceUse(
    role="supporting_context",
    note="Maps land-cover classes to help locate possible habitats. Assess habitat condition with additional field or condition evidence.",
    source_url="https://land.copernicus.eu/en/products/global-dynamic-land-cover/land-cover-2020-raster-10-m-global-annual",
)

# Each annotation covers a specific observable or use within its provision.
# Source links document the measurement or method and its limits.
ARTICLE20_EVIDENCE = {
    "a": {
        "cordis:101056844": EvidenceUse(
            role="research_method",
            note="Uses experiments and living labs to study changes in wetland ecosystem functions after restoration.",
            source_url="https://cordis.europa.eu/project/id/101056844",
        ),
        "cdse:clms_lcm_global_10m_yearly_v1_cog": _LAND_COVER,
    },
    "b": {
        "cdse:clms_vlcc_tree-cover-density_europe_10m_yearly_v1": EvidenceUse(
            role="direct_measurement",
            note="Maps tree crown cover as a percentage per 10 m cell. Apply the urban ecosystem boundary to calculate the canopy indicator.",
            source_url="https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=tree_cover_density",
        ),
        "cdse:clms_vlcc_tree-cover-density_europe_100m_yearly_v1": EvidenceUse(
            role="direct_measurement",
            note="Maps tree crown cover on a 100 m grid aggregated from the 10 m product. Apply the urban boundary and consider the coarser resolution.",
            source_url="https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover/tree-cover-density-2018-present-raster-100-m-europe-yearly",
        ),
        "cdse:clms_urban-atlas_land-cover-use_europe_V025ha_vector_static_v01": EvidenceUse(
            role="supporting_context",
            note="Maps urban land-use classes, including green urban areas in covered functional urban areas. Check the classes and geography against the legal indicator.",
            source_url="https://land.copernicus.eu/en/products/urban-atlas",
        ),
    },
    "g": {
        "cordis:101135005": EvidenceUse(
            role="research_method",
            note="Combines field pollinator biodiversity surveys with pesticide monitoring across European landscapes.",
            source_url="https://cordis.europa.eu/project/id/101135005/reporting",
        ),
        "cordis:101082102": EvidenceUse(
            role="research_method",
            note="Monitors pollinators and vegetation at restoration study sites to assess the effect of restoration.",
            source_url="https://cordis.europa.eu/project/id/101082102/reporting",
        ),
    },
    "h": {"cdse:clms_lcm_global_10m_yearly_v1_cog": _LAND_COVER},
    "j": {"cdse:clms_lcm_global_10m_yearly_v1_cog": _LAND_COVER},
}
