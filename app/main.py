from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os, time, math

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://localhost:4300", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AI_CONN = os.getenv('AI_CONNECTION_STRING')
if AI_CONN:
    from opencensus.ext.azure.trace_exporter import AzureExporter
    from opencensus.trace.tracer import Tracer
    exporter = AzureExporter(connection_string=AI_CONN)
    tracer = Tracer(exporter=exporter)
else:
    tracer = None

# ── Clinical risk weights for boolean comorbidity flags ────────────────────────
COMORBIDITY_WEIGHTS: dict[str, float] = {
    "chf":                  0.22,
    "ckd":                  0.20,
    "cirrhosis":            0.21,
    "cancer":               0.19,
    "copd":                 0.17,
    "cad":                  0.16,
    "stroke_history":       0.15,
    "diabetes":             0.13,
    "af":                   0.12,
    "alcohol_use_disorder": 0.12,
    "hypertension":         0.09,
    "anemia":               0.08,
    "lupus":                0.09,
    "obesity":              0.07,
    "depression":           0.06,
    "anxiety":              0.04,
}

# ── Numeric features: (clinical_threshold, max_contribution) ──────────────────
# threshold = value where sigmoid midpoint lands (≈ 0.5 × max_contribution)
NUMERIC_CONFIG: dict[str, tuple[float, float]] = {
    "age":                  (70.0,  0.14),
    "los":                  (8.0,   0.18),
    "previous_admissions":  (2.0,   0.22),
    "comorbidities":        (4.0,   0.20),
    # vitals
    "hr":                   (110.0, 0.10),
    "bp_systolic":          (180.0, 0.09),
    "spo2_deficit":         (5.0,   0.12),  # 100 - spo2; caller may pass directly
    # labs
    "lactate":              (2.5,   0.20),
    "creatinine":           (3.0,   0.18),
    "bnp":                  (600.0, 0.18),
    "glucose":              (350.0, 0.13),
    "troponin":             (1.0,   0.16),
    "wbc":                  (14.0,  0.12),
    "pco2":                 (55.0,  0.13),
    "potassium":            (5.8,   0.16),
    "hba1c":                (9.0,   0.11),
    "ammonia":              (80.0,  0.18),
    "inr":                  (2.0,   0.14),
}


def _sigmoid_contrib(value: float, threshold: float, max_contrib: float) -> float:
    """Smooth 0→max_contrib contribution centred at threshold."""
    return max_contrib / (1.0 + math.exp(-4.0 * (value / threshold - 1.0)))


def _score_and_shap(features: dict) -> tuple[float, dict[str, float]]:
    shap: dict[str, float] = {}

    # Boolean comorbidity flags
    for key, weight in COMORBIDITY_WEIGHTS.items():
        raw = features.get(key)
        if raw is True or raw == 1 or str(raw).lower() == "true":
            shap[key] = weight

    # Numeric features
    for key, (threshold, max_c) in NUMERIC_CONFIG.items():
        raw = features.get(key)
        if raw is None:
            continue
        try:
            fval = float(raw)
        except (TypeError, ValueError):
            continue
        contrib = _sigmoid_contrib(fval, threshold, max_c)
        if contrib >= 0.01:
            shap[key] = round(contrib, 4)

    # spo2 → convert to deficit automatically
    if "spo2" in features and "spo2_deficit" not in features:
        try:
            deficit = 100.0 - float(features["spo2"])
            if deficit > 0:
                _, max_c = NUMERIC_CONFIG["spo2_deficit"]
                contrib = _sigmoid_contrib(deficit, 5.0, max_c)
                if contrib >= 0.01:
                    shap["spo2_deficit"] = round(contrib, 4)
        except (TypeError, ValueError):
            pass

    total = sum(shap.values())
    # Logistic squash: score of 0.5 when raw total ≈ 0.45
    score = round(1.0 / (1.0 + math.exp(-6.0 * (total - 0.45))), 4)
    score = max(0.0, min(1.0, score))
    return score, shap


class PredictIn(BaseModel):
    features: dict


@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.post("/v1/predict")
async def predict(req: PredictIn):
    start = time.time()
    score, shap = _score_and_shap(req.features)
    bucket = "HIGH" if score >= 0.70 else "MEDIUM" if score >= 0.40 else "LOW"
    top = sorted(shap.items(), key=lambda kv: kv[1], reverse=True)[:8]

    if tracer:
        with tracer.span(name="predict") as span:
            span.add_annotation("prediction", attributes={
                "count_features": len(req.features), "score": score
            })

    return {
        "risk_score":    score,
        "risk_bucket":   bucket,
        "shap":          shap,
        "top_features":  [{"name": k, "impact": v} for k, v in top],
        "model_version": "gbm_v2.1",
        "latency_ms":    round((time.time() - start) * 1000, 1),
    }
