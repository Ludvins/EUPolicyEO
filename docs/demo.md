# Five-minute demo

Start the [static preview](deployment.md#preview-the-static-explorer). For the last step, start the [local API and metrics stack](deployment.md#run-the-python-stack).

## 1. Find documented monitoring evidence

Choose **Urban green space and tree canopy** from **Search starting point** and press **Search**. Follow the Article 20(1)(b) citation, then open one of the Tree Cover Density results. Its evidence note identifies the canopy measurement and the urban boundary needed to calculate the indicator. Choose **Pollinator abundance and diversity** to inspect the PollinERA and RestPoll field monitoring methods in the projects list. [Nature Restoration Regulation](https://eur-lex.europa.eu/eli/reg/2024/1991/oj/eng#art_20) · [Tree Cover Density](https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover?tab=tree_cover_density) · [PollinERA](https://cordis.europa.eu/project/id/101135005/reporting)

Return to the tree-canopy provision and run the search. Open **Assess these collections**, set the maximum spatial resolution to **20 m**, and choose **Assess collections**. Compare the resolution cells for the 10 m and 100 m Tree Cover Density collections. Raise the threshold to **120 m** and assess again. The matrix screens the same search results under the new criteria. [Interactive assessment](policy_assessment.md#interactive-assessment)

## 2. Compare rankers on a free-text query

Choose **Wetland restoration** and search in keyword mode. Switch to **Semantic search**, press **Search**, and open **Embedding map** to see the query and its returned neighbors projected into two dimensions. Select **Hybrid search** to combine the keyword and semantic rankings for the same query. [Model card](model_card.md)

## 3. Narrow the map area

Open **Collection filters**, then **Draw or view area on map**. Use **Find a city** with `Seville` and select **Go**. Pan by dragging. Use the zoom controls, pinch on a touch screen, or focus the canvas to use the wheel, arrow keys and plus or minus keys.

Select **Draw area**, draw a rectangle and drag a corner to refine it. The decimal-degree bounding box fields update with the selection and can be edited directly. Use **Fit area** to frame the box, or **Andalusia example** to load a preset. To inspect a collection's catalogue extent, select **Show extent on map** on a result with bounds.

Add a date range and enable strict filtering to hide known incompatibilities. Records with insufficient metadata can still appear. Collection rectangles and dates describe the catalogue. Check the provider record for individual observations. [Coverage and availability](data_sources.md#coverage-and-availability)

## 4. Verify what is served

Open **Dataset and methodology** for source coverage and release lineage. Repeat a browser search while the API is stopped to demonstrate the static runtime. [Search quality and coverage](verification.md#search-quality)

In free-text mode, search **Standardized monitoring of freshwater fish communities using environmental DNA**. Keyword and semantic search both put eDNAqua-plan first in the revised browser release. Its CORDIS record describes work on reference libraries and a standardized aquatic monitoring approach. [eDNAqua-plan](https://cordis.europa.eu/project/id/101112800)

For the local stack, open `/docs`, compare `/version` before and after promotion, and inspect Prometheus after a valid and an invalid request. A rollback is complete when `/version` reports the restored numeric model version. [Verification commands](deployment.md#3-promote-and-inspect-a-model) · [Recorded results](verification.md)
