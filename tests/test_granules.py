from datetime import UTC, datetime
from time import monotonic

import httpx

from eupolicyeo.granules import cmr_pages, normalize_granule, stac_pages
from eupolicyeo.schemas import RawPage
from eupolicyeo.settings import Config
from eupolicyeo.sources import Fetcher


def test_cmr_search_after_header_and_end_condition(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        i = len(requests)
        return httpx.Response(
            200,
            json={"items": [{"id": i}]},
            headers={"CMR-Hits": "2", "CMR-Search-After": f"[{i}]"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = Fetcher(tmp_path, Config(), client)
        fetcher.deadline = monotonic() + 10
        pages = list(cmr_pages(fetcher, "C1-NASA", (0, 1, 2, 3), "start", "end", 5, 1))
    assert len(pages) == 2
    assert requests[1].url == requests[0].url
    assert requests[1].headers["CMR-Search-After"] == "[1]"


def test_stac_post_and_get_continuation(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        links = (
            [{"rel": "next", "href": "/v1/search?token=next"}] if request.method == "POST" else []
        )
        return httpx.Response(200, json={"features": [{"id": "test"}], "links": links})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = Fetcher(tmp_path, Config(), client)
        fetcher.deadline = monotonic() + 10
        pages = list(stac_pages(fetcher, "s2", (0, 1, 2, 3), "start", "end", 5, 1))
    assert len(pages) == 2
    assert requests[0].method == "POST" and b'"collections":["s2"]' in requests[0].content
    assert requests[1].method == "GET" and requests[1].url.params["token"] == "next"


def test_missing_cloud_and_approximate_polygon():
    page = RawPage(
        source="cmr",
        path="test.raw",
        url="https://cmr.earthdata.nasa.gov",
        retrieved_at=datetime.now(UTC),
        sha256="0" * 64,
        size=0,
        mode="import",
    )
    record = {
        "meta": {"concept-id": "G1-NASA", "revision-id": 2, "collection-concept-id": "C1-NASA"},
        "umm": {
            "SpatialExtent": {
                "HorizontalSpatialDomain": {
                    "Geometry": {
                        "GPolygons": [
                            {
                                "Boundary": {
                                    "Points": [
                                        {"Longitude": -2, "Latitude": 33},
                                        {"Longitude": 4, "Latitude": 38},
                                    ]
                                }
                            }
                        ]
                    }
                }
            },
            "TemporalExtent": {"SingleDateTime": "2024-06-01T00:00:00Z"},
        },
    }
    granule = normalize_granule(record, page, "0" * 24, "cmr:C1-NASA")
    assert granule.cloud_cover_percent is None
    assert granule.bbox_parts == [(-2, 33, 4, 38)]
    assert granule.temporal_start == granule.temporal_end
    assert granule.metadata_quality_flags == ["polygon_bbox_approximation"]
