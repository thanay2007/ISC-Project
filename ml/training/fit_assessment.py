"""Fit a binary verdict classifier and evaluate it on reserved document groups."""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from scipy.special import expit, logit

from ml.document_assessment import page_features
from ml.model import tensor_image
from ml.training.common import rows_for
from ml.training.evaluate_model import load_model, summarize


def collect(folder, rows, model, device):
    features = []
    with torch.inference_mode():
        for offset in range(0, len(rows), 16):
            pages, bounds = [], []
            for row in rows[offset:offset + 16]:
                with np.load(folder / row["data"], allow_pickle=False) as sample:
                    pages.append(sample["image"])
                    bounds.append(sample["bounds"])
            masks, logits, embeddings = model(torch.stack([tensor_image(page) for page in pages]).to(device), return_features=True)
            for page, (x, y, w, h), mask, score, embedding in zip(
                pages, bounds, masks.sigmoid().cpu().numpy()[:, 0], logits.sigmoid().tolist(), embeddings.cpu().numpy(),
            ):
                features.append(page_features(page[y:y+h, x:x+w], mask[y:y+h, x:x+w], score, embedding))
    return np.asarray(features)


def fit(features, labels, strata):
    _, inverse, counts = np.unique(strata, return_inverse=True, return_counts=True)
    weights = len(labels) / (len(counts) * counts[inverse])
    scaler = StandardScaler().fit(features, sample_weight=weights)
    head = LogisticRegression(C=.05, max_iter=1000)
    head.fit(scaler.transform(features), labels, sample_weight=weights)
    boosted = GradientBoostingClassifier(n_estimators=120, max_depth=2, min_samples_leaf=20,
                                         learning_rate=.07, random_state=427)
    boosted.fit(features, labels, sample_weight=weights)
    return scaler, head, boosted


def export_trees(model):
    trees = []
    for estimator in model.estimators_[:, 0]:
        tree = estimator.tree_
        nodes = []
        for node, feature in enumerate(tree.feature):
            if feature < 0:
                nodes.append([-1, float(tree.value[node, 0, 0] * model.learning_rate)])
            else:
                nodes.append([int(feature), float(tree.threshold[node]),
                              int(tree.children_left[node]), int(tree.children_right[node])])
        trees.append(nodes)
    prior = float(model.init_.class_prior_[1])
    return {"trees": trees, "intercept": float(logit(prior))}


def evaluate(labels, sources, scores, threshold):
    return {group: summarize(labels[selected], scores[selected], threshold)
            for group, selected in [("overall", np.ones(len(labels), dtype=bool)),
                                    *((source, sources == source) for source in np.unique(sources))]}


def assess(args):
    cv2.setNumThreads(1)
    torch.set_num_threads(6)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, config, digest = load_model(args.model, device)
    training = defaultdict(list)
    for row in rows_for(args.data, "train"):
        training[row["source"], row["label"]].append(row)
    rng = random.Random(427)
    selected = [row for (source, label), rows in sorted(training.items()) if (source, 1 - label) in training
                for row in rng.sample(rows, k=min(len(rows), 400))]
    train_strata = [f"{row['source']}:{row['label']}" for row in selected]
    scaler, head, boosted = fit(collect(args.data, selected, model, device), [row["label"] for row in selected], train_strata)
    print(f"Fitted the verdict classifier on {len(selected)} training pages.", flush=True)
    validation = rows_for(args.data, "validation")
    test = rows_for(args.data, "test")
    x = collect(args.data, validation, model, device)
    y = np.array([row["label"] for row in validation])
    sources = np.array([row["source"] for row in validation])

    baseline_predictions = x[:, 0] >= config["classification_threshold"]
    baseline_recall = baseline_predictions[y == 1].mean()
    baseline_false_positives = baseline_predictions[y == 0].mean()
    raw_logits = logit(x[:, 0].clip(.001, .999))
    candidates = []
    predictors = {"linear": lambda features: head.decision_function(scaler.transform(features)),
                  "boosted": boosted.decision_function}
    for name, predict in predictors.items():
        scores = predict(x)
        for weight in np.linspace(0, 1, 11):
            blended = expit(weight * raw_logits + (1 - weight) * scores)
            for threshold in np.linspace(.40, .85, 91):
                prediction = blended >= threshold
                recall = prediction[y == 1].mean()
                false_positives = prediction[y == 0].mean()
                if recall < baseline_recall - .12 or false_positives > baseline_false_positives - .05:
                    continue
                candidates.append((false_positives - recall, false_positives, float(weight), float(threshold), name))
    if not candidates:
        raise SystemExit("No candidate reduced false positives while maintaining the validation recall floor.")
    _, _, weight, threshold, name = min(candidates)

    predict = predictors[name]
    print(f"Selected {name} model with raw score weight {weight:.2f} and threshold {threshold:.3f} from {len(y)} validation pages.", flush=True)
    held_out = collect(args.data, test, model, device)
    test_scores = expit(weight * logit(held_out[:, 0].clip(.001, .999)) + (1 - weight) * predict(held_out))
    test_labels = np.array([row["label"] for row in test])
    test_sources = np.array([row["source"] for row in test])
    metrics = evaluate(test_labels, test_sources, test_scores, threshold)
    baseline = evaluate(test_labels, test_sources, held_out[:, 0], config["classification_threshold"])
    model_parameters = (export_trees(boosted) if name == "boosted" else
                        {"feature_mean": scaler.mean_.tolist(), "feature_scale": scaler.scale_.tolist(),
                         "coefficients": head.coef_[0].tolist(), "intercept": float(head.intercept_[0])})
    artifact = {"checkpoint_sha256": digest, "threshold": threshold, "raw_weight": weight, **model_parameters,
                "validation": evaluate(y, sources, expit(weight * raw_logits + (1 - weight) * predict(x)), threshold),
                "test": metrics, "baseline_test": baseline}
    args.out.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    for group in metrics:
        print(group, {key: (baseline[group][key], metrics[group][key])
                      for key in ("false_positive_rate", "recall", "roc_auc")}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=Path("ml/models"))
    parser.add_argument("--out", type=Path, required=True)
    assess(parser.parse_args())
