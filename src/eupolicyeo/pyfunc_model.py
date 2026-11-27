import json
from pathlib import Path

import mlflow
import pandas as pd

from eupolicyeo.bundle import Bundle
from eupolicyeo.schemas import SearchQuery


class PolicyRanker(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        self.bundle = Bundle(Path(context.artifacts["bundle"]))

    def predict(self, context, model_input, params=None):
        rows = []
        for row in model_input.to_dict(orient="records"):
            result = self.bundle.search(SearchQuery.model_validate(row))
            rows.append(json.dumps([item.model_dump(mode="json") for item in result]))
        return pd.DataFrame({"results_json": rows})


mlflow.models.set_model(PolicyRanker())
