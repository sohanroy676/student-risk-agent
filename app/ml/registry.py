"""MLflow registry for the weekly production models, with the promotion gate in front of it.

One release is a set of per-week models trained together (registered models
`risk-lgbm-week<N>`). The gate looks at the week-4 model; if it passes (or is signed off),
the `production` alias moves to every week's new version. Metrics and the sign-off travel
with each version as tags, so the current model's numbers can be read back for the next gate.
"""

import json
import math
from collections.abc import Mapping
from pathlib import Path

import mlflow
from mlflow import MlflowClient

from app.ml.calibrate import CalibratedModel
from app.ml.gate import GateResult, Metrics, SignOff, check

MODEL_PREFIX = "risk-lgbm-week"
ALIAS = "production"
GATE_WEEK = 4
EXPERIMENT = "risk-model"


def model_name(week: int) -> str:
    return f"{MODEL_PREFIX}{week}"


def _clean(value: float) -> float | None:
    return None if math.isnan(value) else value


def metrics_to_json(metrics: Metrics) -> str:
    return json.dumps(
        {
            "auc_week4": _clean(metrics.auc_week4),
            "ece": _clean(metrics.ece),
            "recall_gaps": {k: _clean(v) for k, v in metrics.recall_gaps.items()},
        }
    )


def metrics_from_json(text: str) -> Metrics:
    def number(v: float | None) -> float:
        return float("nan") if v is None else float(v)

    raw = json.loads(text)
    return Metrics(
        auc_week4=number(raw["auc_week4"]),
        ece=number(raw["ece"]),
        recall_gaps={k: number(v) for k, v in raw["recall_gaps"].items()},
    )


class Registry:
    """A local MLflow store (sqlite database plus an artifact folder) under `root`."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.uri = f"sqlite:///{(root / 'mlflow.db').resolve().as_posix()}"
        self.artifacts = (root / "artifacts").resolve()
        mlflow.set_tracking_uri(self.uri)
        mlflow.set_registry_uri(self.uri)
        self.client = MlflowClient(self.uri, self.uri)

    def _experiment_id(self) -> str:
        found = self.client.get_experiment_by_name(EXPERIMENT)
        if found is not None:
            return str(found.experiment_id)
        return str(self.client.create_experiment(EXPERIMENT, self.artifacts.as_uri()))

    def current_metrics(self) -> Metrics | None:
        """Metrics of the week-4 model now holding the production alias, if any."""
        try:
            version = self.client.get_model_version_by_alias(model_name(GATE_WEEK), ALIAS)
        except mlflow.exceptions.MlflowException:
            return None
        text = version.tags.get("gate_metrics")
        if text is None:
            raise ValueError("the production model has no recorded metrics; cannot run the gate")
        return metrics_from_json(text)

    def log_release(
        self,
        fitted: Mapping[int, CalibratedModel],
        metrics: Metrics,
        params: Mapping[str, str | float],
        card: str,
    ) -> dict[int, str]:
        """Register one version per week and return their version numbers."""
        if GATE_WEEK not in fitted:
            raise ValueError(f"a release must include the week-{GATE_WEEK} model")
        versions: dict[int, str] = {}
        with mlflow.start_run(experiment_id=self._experiment_id()):
            mlflow.log_params(dict(params))
            mlflow.log_text(card, "model_card.md")
            for week, model in fitted.items():
                info = mlflow.sklearn.log_model(
                    model,
                    name=f"week{week}",
                    registered_model_name=model_name(week),
                    serialization_format="cloudpickle",
                )
                version = str(info.registered_model_version)
                self.client.set_model_version_tag(
                    model_name(week), version, "gate_metrics", metrics_to_json(metrics)
                )
                versions[week] = version
        return versions

    def promote(
        self, versions: Mapping[int, str], candidate: Metrics, sign_off: SignOff | None = None
    ) -> GateResult:
        """Run the gate against the current production model; move the alias only if it passes."""
        result = check(candidate, self.current_metrics(), sign_off)
        verdict = {
            "passed": result.passed,
            "blocks": list(result.blocks),
            "hard_failures": list(result.hard_failures),
            "overridden": list(result.overridden),
        }
        for week, version in versions.items():
            name = model_name(week)
            self.client.set_model_version_tag(name, version, "gate_result", json.dumps(verdict))
            if sign_off is not None and result.overridden:
                tag = json.dumps({"name": sign_off.name, "reason": sign_off.reason})
                self.client.set_model_version_tag(name, version, "sign_off", tag)
            if result.passed:
                self.client.set_registered_model_alias(name, ALIAS, version)
        return result
