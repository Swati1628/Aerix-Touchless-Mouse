"""Train the bundled demonstrator classifier from its documented synthetic CSV."""
from __future__ import annotations

import csv
from pathlib import Path

import joblib
import sklearn
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

from .url_classifier import MODEL_PATH, RISK_LABELS, build_model

DATA_PATH = Path(__file__).with_name("data") / "url_training.csv"


def main() -> None:
    with DATA_PATH.open("r", encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    urls = [row["url"] for row in rows]
    labels = [row["label"].upper() for row in rows]
    if not urls or set(labels) != RISK_LABELS:
        raise ValueError(f"Dataset must contain samples for exactly {sorted(RISK_LABELS)}")

    train_urls, validation_urls, train_labels, validation_labels = train_test_split(
        urls, labels, test_size=0.2, random_state=42, stratify=labels,
    )
    validation_model = build_model()
    validation_model.fit(train_urls, train_labels)
    validation_predictions = validation_model.predict(validation_urls)
    validation_accuracy = validation_model.score(validation_urls, validation_labels)
    class_order = ["SAFE", "SUSPICIOUS", "DANGEROUS"]
    matrix = confusion_matrix(validation_labels, validation_predictions, labels=class_order)
    benign_indexes = [index for index, label in enumerate(validation_labels) if label == "SAFE"]
    benign_false_positives = sum(validation_predictions[index] != "SAFE" for index in benign_indexes)
    benign_false_positive_rate = benign_false_positives / len(benign_indexes) if benign_indexes else 0.0

    model = build_model()
    model.fit(urls, labels)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "training_samples": len(urls),
        "scikit_learn_version": sklearn.__version__,
    }, MODEL_PATH, compress=3)
    print(f"Trained URL safety model from {len(urls)} synthetic samples.")
    print(f"Synthetic 20% holdout accuracy (small and not a real-world benchmark): {validation_accuracy:.3f}")
    print("Synthetic holdout classification report:")
    print(classification_report(validation_labels, validation_predictions, labels=class_order, zero_division=0))
    print(f"Confusion matrix (labels={class_order}): {matrix.tolist()}")
    print(f"SAFE sample false-positive rate (prediction != SAFE): {benign_false_positive_rate:.3f} "
          f"({benign_false_positives}/{len(benign_indexes)})")
    print(f"Saved model: {MODEL_PATH}")


if __name__ == "__main__":
    main()
