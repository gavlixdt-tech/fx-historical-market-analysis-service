"""Pure-Python research model portfolio and walk-forward evaluation helpers."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from backend.app.analysis.forecasting import (
    accuracy,
    balanced_accuracy,
    confusion_matrix,
    mae,
    mean_error,
    r2_score,
    rmse,
)

MODEL_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "name": "zero_return",
        "tier": 1,
        "task_types": ["regression"],
        "description": "Predicts zero for every observation (no-change baseline).",
    },
    {
        "name": "historical_mean",
        "tier": 1,
        "task_types": ["regression"],
        "description": "Predicts the training-window mean target.",
    },
    {
        "name": "majority_class",
        "tier": 1,
        "task_types": ["classification"],
        "description": "Predicts the majority training label.",
    },
    {
        "name": "volatility_mean",
        "tier": 1,
        "task_types": ["regression"],
        "description": "Predicts the training-window mean target (naive volatility baseline).",
    },
    {
        "name": "ridge_regression",
        "tier": 2,
        "task_types": ["regression"],
        "description": "L2-regularised linear regression with standardised features.",
    },
    {
        "name": "ridge_logistic",
        "tier": 2,
        "task_types": ["classification"],
        "description": "L2-regularised logistic regression (one-vs-rest) with standardised features.",
    },
    {
        "name": "random_forest",
        "tier": 3,
        "task_types": ["regression", "classification"],
        "description": "Small random forest of shallow decision trees.",
    },
    {
        "name": "histogram_gradient_boosting",
        "tier": 3,
        "task_types": ["regression", "classification"],
        "description": "Small gradient-boosted ensemble of shallow trees.",
    },
)


def supported_model_families(task_type: str | None = None) -> list[dict[str, Any]]:
    if task_type is None:
        return [dict(m) for m in MODEL_FAMILIES]
    return [dict(m) for m in MODEL_FAMILIES if task_type in m["task_types"]]


def task_type_for_target(target_type: str) -> str:
    if target_type == "direction":
        return "classification"
    return "regression"


@dataclass
class Preprocessor:
    medians: list[float] = field(default_factory=list)
    means: list[float] = field(default_factory=list)
    stds: list[float] = field(default_factory=list)
    fitted: bool = False

    def fit(self, X: Sequence[Sequence[float | None]]) -> Preprocessor:
        n_feat = len(X[0]) if X else 0
        self.medians = [0.0] * n_feat
        for j in range(n_feat):
            vals = cast(list[float], [row[j] for row in X if row[j] is not None])
            if vals:
                s = sorted(vals)
                mid = len(s) // 2
                self.medians[j] = (s[mid - 1] + s[mid]) / 2.0 if len(s) % 2 == 0 else float(s[mid])
            else:
                self.medians[j] = 0.0
        imputed = [
            [(row[j] if row[j] is not None else self.medians[j]) for j in range(n_feat)]
            for row in X
        ]
        self.means = [0.0] * n_feat
        self.stds = [1.0] * n_feat
        for j in range(n_feat):
            col = cast(list[float], [r[j] for r in imputed])
            m = sum(col) / len(col) if col else 0.0
            var = sum((v - m) ** 2 for v in col) / len(col) if col else 0.0
            sd = math.sqrt(var)
            self.means[j] = m
            self.stds[j] = sd if sd > 1e-12 else 1.0
        self.fitted = True
        return self

    def transform(self, X: Sequence[Sequence[float | None]]) -> list[list[float]]:
        if not self.fitted:
            raise RuntimeError("Preprocessor not fitted")
        n_feat = len(self.medians)
        out: list[list[float]] = []
        for row in X:
            new_row: list[float] = []
            for j in range(n_feat):
                v = row[j] if (j < len(row) and row[j] is not None) else self.medians[j]
                if v is None:
                    v = 0.0
                new_row.append((float(v) - self.means[j]) / self.stds[j])
            out.append(new_row)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "medians": self.medians,
            "means": self.means,
            "stds": self.stds,
            "fitted": self.fitted,
        }


@dataclass
class TreeNode:
    feature: int | None = None
    threshold: float | None = None
    left: TreeNode | None = None
    right: TreeNode | None = None
    value: float | None = None
    proba: list[float] | None = None


def _gini(labels: Sequence[float]) -> float:
    if not labels:
        return 0.0
    counts: dict[float, int] = {}
    for v in labels:
        counts[v] = counts.get(v, 0) + 1
    n = len(labels)
    return 1.0 - sum((c / n) ** 2 for c in counts.values())


def _mse(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    m = sum(values) / len(values)
    return sum((v - m) ** 2 for v in values) / len(values)


def build_tree(
    X: Sequence[Sequence[float]],
    y: Sequence[float],
    *,
    task_type: str,
    max_depth: int = 4,
    min_samples_leaf: int = 5,
    feature_indices: Sequence[int] | None = None,
    rng: random.Random | None = None,
) -> TreeNode:
    rng = rng or random.Random(0)  # noqa: S311
    n = len(X)
    n_feat = len(X[0]) if X else 0
    feats = list(feature_indices) if feature_indices is not None else list(range(n_feat))

    def majority_or_mean(labels: Sequence[float]) -> tuple[float, list[float] | None]:
        if task_type == "classification":
            counts: dict[float, int] = {}
            for v in labels:
                counts[v] = counts.get(v, 0) + 1
            best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            classes = sorted(set(y))
            proba = [counts.get(c, 0) / len(labels) if labels else 0.0 for c in classes]
            return float(best), proba
        m = sum(labels) / len(labels) if labels else 0.0
        return float(m), None

    def recurse(depth: int, idx: list[int]) -> TreeNode:
        labels = [y[i] for i in idx]
        val, proba = majority_or_mean(labels)
        node = TreeNode(value=val, proba=proba)
        if depth >= max_depth or len(idx) < 2 * min_samples_leaf:
            return node
        parent_imp = _gini(labels) if task_type == "classification" else _mse(labels)
        best = None
        cand_feats = list(feats)
        rng.shuffle(cand_feats)
        for f in cand_feats:
            vals = sorted({X[i][f] for i in idx})
            thresholds = []
            for t in range(len(vals) - 1):
                thresholds.append((vals[t] + vals[t + 1]) / 2.0)
            if len(thresholds) > 12:
                thresholds = thresholds[:: max(1, len(thresholds) // 12)]
            for thr in thresholds:
                left = [i for i in idx if X[i][f] <= thr]
                right = [i for i in idx if X[i][f] > thr]
                if len(left) < min_samples_leaf or len(right) < min_samples_leaf:
                    continue
                w_l = len(left) / len(idx)
                w_r = len(right) / len(idx)
                if task_type == "classification":
                    imp = w_l * _gini([y[i] for i in left]) + w_r * _gini([y[i] for i in right])
                else:
                    imp = w_l * _mse([y[i] for i in left]) + w_r * _mse([y[i] for i in right])
                reduction = parent_imp - imp
                if best is None or reduction > best[0]:
                    best = (reduction, f, thr, left, right)
        if best is None or best[0] <= 1e-12:
            return node
        _, f, thr, left, right = best
        node.feature = f
        node.threshold = thr
        node.left = recurse(depth + 1, left)
        node.right = recurse(depth + 1, right)
        return node

    return recurse(0, list(range(n)))


def predict_tree(node: TreeNode, x: Sequence[float]) -> tuple[float, list[float] | None]:
    cur = node
    while cur.feature is not None and cur.threshold is not None:
        if x[cur.feature] <= cur.threshold:
            if cur.left is None:
                break
            cur = cur.left
        else:
            if cur.right is None:
                break
            cur = cur.right
    return (cur.value if cur.value is not None else 0.0, cur.proba)


class RidgeRegression:
    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha
        self.weights: list[float] = []
        self.bias: float = 0.0
        self.fitted = False

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[float]) -> RidgeRegression:
        n = len(X)
        p = len(X[0]) if X else 0
        A = [[0.0] * (p + 1) for _ in range(p + 1)]
        bv = [0.0] * (p + 1)
        for i in range(n):
            xi = list(X[i]) + [1.0]
            yi = y[i]
            for a in range(p + 1):
                bv[a] += xi[a] * yi
                for b in range(p + 1):
                    A[a][b] += xi[a] * xi[b]
        for j in range(p):
            A[j][j] += self.alpha
        sol = _solve_linear(A, bv)
        self.weights = sol[:p]
        self.bias = sol[p]
        self.fitted = True
        return self

    def predict(self, X: Sequence[Sequence[float]]) -> list[float]:
        out = []
        for row in X:
            s = self.bias
            for j, w in enumerate(self.weights):
                s += w * row[j]
            out.append(s)
        return out


class RidgeLogistic:
    def __init__(self, alpha: float = 1.0, lr: float = 0.1, epochs: int = 200) -> None:
        self.alpha = alpha
        self.lr = lr
        self.epochs = epochs
        self.classes: list[float] = []
        self.weights: dict[float, list[float]] = {}
        self.biases: dict[float, float] = {}
        self.fitted = False

    def _sigmoid(self, z: float) -> float:
        if z >= 0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[float]) -> RidgeLogistic:
        self.classes = sorted(set(y))
        p = len(X[0]) if X else 0
        for c in self.classes:
            w = [0.0] * p
            b = 0.0
            for _ in range(self.epochs):
                grad_w = [0.0] * p
                grad_b = 0.0
                for i in range(len(X)):
                    target = 1.0 if y[i] == c else 0.0
                    z = b + sum(w[j] * X[i][j] for j in range(p))
                    pred = self._sigmoid(z)
                    err = pred - target
                    for j in range(p):
                        grad_w[j] += err * X[i][j]
                    grad_b += err
                for j in range(p):
                    w[j] -= self.lr * (grad_w[j] / len(X) + self.alpha * w[j])
                b -= self.lr * (grad_b / len(X))
            self.weights[c] = w
            self.biases[c] = b
        self.fitted = True
        return self

    def predict_proba(self, X: Sequence[Sequence[float]]) -> list[list[float]]:
        out = []
        for row in X:
            scores = []
            for c in self.classes:
                w = self.weights[c]
                b = self.biases[c]
                z = b + sum(w[j] * row[j] for j in range(len(row)))
                scores.append(self._sigmoid(z))
            s = sum(scores)
            if s <= 0:
                s = 1.0
            out.append([sc / s for sc in scores])
        return out

    def predict(self, X: Sequence[Sequence[float]]) -> list[float]:
        proba = self.predict_proba(X)
        out = []
        for pr in proba:
            idx = max(range(len(pr)), key=lambda i: pr[i])
            out.append(self.classes[idx])
        return out


class RandomForest:
    def __init__(
        self,
        *,
        task_type: str,
        n_estimators: int = 20,
        max_depth: int = 4,
        min_samples_leaf: int = 5,
        max_features: str = "sqrt",
        seed: int = 0,
    ) -> None:
        self.task_type = task_type
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.max_features = max_features
        self.seed = seed
        self.trees: list[TreeNode] = []
        self.feature_count = 0
        self.classes: list[float] = []
        self.fitted = False

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[float]) -> RandomForest:
        self.feature_count = len(X[0]) if X else 0
        self.classes = sorted(set(y)) if self.task_type == "classification" else []
        rng = random.Random(self.seed)  # noqa: S311
        self.trees = []
        for _ in range(self.n_estimators):
            idx = [rng.randrange(len(X)) for _ in range(len(X))]
            Xb = [list(X[i]) for i in idx]
            yb = [y[i] for i in idx]
            if self.max_features == "sqrt":
                m = max(1, int(math.sqrt(self.feature_count)))
            else:
                m = self.feature_count
            feat_idx = (
                rng.sample(range(self.feature_count), min(m, self.feature_count))
                if self.feature_count
                else []
            )
            tree = build_tree(
                Xb,
                yb,
                task_type=self.task_type,
                max_depth=self.max_depth,
                min_samples_leaf=self.min_samples_leaf,
                feature_indices=feat_idx,
                rng=rng,
            )
            self.trees.append(tree)
        self.fitted = True
        return self

    def predict(self, X: Sequence[Sequence[float]]) -> list[float]:
        out = []
        for row in X:
            if self.task_type == "classification":
                votes: dict[float, int] = {}
                for t in self.trees:
                    v, _ = predict_tree(t, row)
                    votes[v] = votes.get(v, 0) + 1
                out.append(max(votes.items(), key=lambda kv: (kv[1], -kv[0]))[0])
            else:
                preds = [predict_tree(t, row)[0] for t in self.trees]
                out.append(sum(preds) / len(preds) if preds else 0.0)
        return out

    def predict_proba(self, X: Sequence[Sequence[float]]) -> list[list[float]]:
        if self.task_type != "classification":
            return []
        out = []
        for row in X:
            votes: dict[float, int] = {}
            for t in self.trees:
                v, _ = predict_tree(t, row)
                votes[v] = votes.get(v, 0) + 1
            total = len(self.trees) or 1
            out.append([votes.get(c, 0) / total for c in self.classes])
        return out


def walk_forward_folds(
    n: int,
    *,
    n_folds: int = 3,
    min_train: int = 30,
    purge: bool = True,
    embargo_periods: int = 0,
    outcome_ends: Sequence[datetime] | None = None,
    timestamps: Sequence[datetime] | None = None,
) -> list[dict[str, Any]]:
    if n < min_train + 2 * n_folds:
        return []
    block = max(5, (n - min_train) // (2 * n_folds))
    folds: list[dict[str, Any]] = []
    ts = list(timestamps) if timestamps is not None else [datetime.now(UTC) for _ in range(n)]
    oe = list(outcome_ends) if outcome_ends is not None else [ts[i] for i in range(n)]
    for k in range(n_folds):
        test_start = n - (n_folds - k) * block
        test_end = test_start + block
        val_start = test_start - block
        val_end = test_start
        train_end = val_start
        if train_end < min_train:
            continue
        train_idx = list(range(0, train_end))
        val_idx = list(range(val_start, val_end))
        test_idx = list(range(test_start, min(test_end, n)))
        purged: list[int] = []
        if purge and val_idx:
            boundary = ts[val_idx[0]]
            new_train = []
            for i in train_idx:
                if oe[i] >= boundary:
                    purged.append(i)
                else:
                    new_train.append(i)
            train_idx = new_train
        embargoed: list[int] = []
        if embargo_periods and embargo_periods > 0 and train_idx:
            ne = min(embargo_periods, len(train_idx))
            embargoed = list(train_idx[-ne:])
            train_idx = train_idx[:-ne]
        folds.append(
            {
                "fold": k + 1,
                "train_indices": sorted(train_idx),
                "validation_indices": sorted(val_idx),
                "test_indices": sorted(test_idx),
                "purged_indices": sorted(purged),
                "embargoed_indices": sorted(embargoed),
            }
        )
    return folds


class HistogramGradientBoosting:
    def __init__(
        self,
        *,
        task_type: str,
        n_estimators: int = 30,
        learning_rate: float = 0.1,
        max_depth: int = 3,
        min_samples_leaf: int = 5,
        seed: int = 0,
    ) -> None:
        self.task_type = task_type
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.seed = seed
        self.trees: list[TreeNode] = []
        self.base: float = 0.0
        self.classes: list[float] = []
        self._class_trees: dict[float, list[TreeNode]] = {}
        self._class_base: dict[float, float] = {}
        self.fitted = False

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[float]) -> HistogramGradientBoosting:
        rng = random.Random(self.seed)  # noqa: S311
        self.classes = sorted(set(y)) if self.task_type == "classification" else []
        n = len(X)
        if self.task_type == "regression":
            self.base = sum(y) / n if n else 0.0
            resid = [y[i] - self.base for i in range(n)]
            for _ in range(self.n_estimators):
                tree = build_tree(
                    [list(r) for r in X],
                    resid,
                    task_type="regression",
                    max_depth=self.max_depth,
                    min_samples_leaf=self.min_samples_leaf,
                    rng=rng,
                )
                preds = [predict_tree(tree, X[i])[0] for i in range(n)]
                for i in range(n):
                    resid[i] -= self.learning_rate * preds[i]
                self.trees.append(tree)
        else:
            self._class_trees = {c: [] for c in self.classes}
            self._class_base = {}
            for c in self.classes:
                yc = [1.0 if y[i] == c else 0.0 for i in range(n)]
                base = sum(yc) / n if n else 0.0
                self._class_base[c] = base
                resid = [yc[i] - base for i in range(n)]
                for _ in range(self.n_estimators):
                    tree = build_tree(
                        [list(r) for r in X],
                        resid,
                        task_type="regression",
                        max_depth=self.max_depth,
                        min_samples_leaf=self.min_samples_leaf,
                        rng=rng,
                    )
                    preds = [predict_tree(tree, X[i])[0] for i in range(n)]
                    for i in range(n):
                        resid[i] -= self.learning_rate * preds[i]
                    self._class_trees[c].append(tree)
        self.fitted = True
        return self

    def predict(self, X: Sequence[Sequence[float]]) -> list[float]:
        if self.task_type == "regression":
            out = []
            for row in X:
                s = self.base
                for t in self.trees:
                    s += self.learning_rate * predict_tree(t, row)[0]
                out.append(s)
            return out
        out = []
        for row in X:
            best_c = self.classes[0] if self.classes else 0.0
            best_score = -float("inf")
            for c in self.classes:
                s = self._class_base[c]
                for t in self._class_trees[c]:
                    s += self.learning_rate * predict_tree(t, row)[0]
                if s > best_score:
                    best_score = s
                    best_c = c
            out.append(best_c)
        return out

    def predict_proba(self, X: Sequence[Sequence[float]]) -> list[list[float]]:
        if self.task_type != "classification":
            return []
        out = []
        for row in X:
            scores = []
            for c in self.classes:
                s = self._class_base[c]
                for t in self._class_trees[c]:
                    s += self.learning_rate * predict_tree(t, row)[0]
                scores.append(s)
            mx = max(scores) if scores else 0.0
            exps = [math.exp(s - mx) for s in scores]
            ssum = sum(exps) or 1.0
            out.append([e / ssum for e in exps])
        return out


def _solve_linear(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            M[pivot][col] = 1e-12
        M[col], M[pivot] = M[pivot], M[col]
        pv = M[col][col]
        for j in range(col, n + 1):
            M[col][j] /= pv
        for r in range(n):
            if r == col:
                continue
            factor = M[r][col]
            if factor != 0.0:
                for j in range(col, n + 1):
                    M[r][j] -= factor * M[col][j]
    return [M[i][n] for i in range(n)]


def _safe_div(a: float, b: float) -> float:
    return a / b if b not in (0, 0.0) else float("nan")


def classification_metrics(
    y_true: Sequence[float],
    y_pred: Sequence[float],
    y_proba: Sequence[Sequence[float]] | None = None,
) -> dict[str, Any]:
    classes = sorted(set(list(y_true) + list(y_pred)))
    acc = accuracy(y_true, y_pred)
    bacc = balanced_accuracy(y_true, y_pred)
    cm = confusion_matrix(y_true, y_pred)
    precisions = []
    recalls = []
    f1s = []
    for c in classes:
        tp = sum(1 for a, b in zip(y_true, y_pred, strict=False) if a == c and b == c)
        fp = sum(1 for a, b in zip(y_true, y_pred, strict=False) if a != c and b == c)
        fn = sum(1 for a, b in zip(y_true, y_pred, strict=False) if a == c and b != c)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        precisions.append(prec)
        recalls.append(rec)
        f1s.append(f1)
    macro_p = sum(precisions) / len(precisions) if precisions else float("nan")
    macro_r = sum(recalls) / len(recalls) if recalls else float("nan")
    macro_f1 = sum(f1s) / len(f1s) if f1s else float("nan")
    mcc = float("nan")
    if len(classes) == 2:
        tp = sum(
            1 for a, b in zip(y_true, y_pred, strict=False) if a == classes[1] and b == classes[1]
        )
        tn = sum(
            1 for a, b in zip(y_true, y_pred, strict=False) if a == classes[0] and b == classes[0]
        )
        fp = sum(
            1 for a, b in zip(y_true, y_pred, strict=False) if a == classes[0] and b == classes[1]
        )
        fn = sum(
            1 for a, b in zip(y_true, y_pred, strict=False) if a == classes[1] and b == classes[0]
        )
        denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
        mcc = (tp * tn - fp * fn) / denom if denom > 0 else 0.0
    dist: dict[str, int] = {}
    for v in y_true:
        dist[str(v)] = dist.get(str(v), 0) + 1
    out: dict[str, Any] = {
        "accuracy": acc,
        "balanced_accuracy": bacc,
        "precision_macro": macro_p,
        "recall_macro": macro_r,
        "f1_macro": macro_f1,
        "mcc": mcc,
        "confusion_matrix": cm,
        "class_distribution": dist,
    }
    if y_proba is not None and len(y_proba) == len(y_true):
        if len(classes) == 2:
            ps = [
                pr[1] if isinstance(pr, list | tuple) and len(pr) > 1 else float(cast(Any, pr))
                for pr in y_proba
            ]
            brier = sum(
                (p - (1.0 if t == classes[1] else 0.0)) ** 2
                for p, t in zip(ps, y_true, strict=False)
            ) / len(y_true)
            eps = 1e-12
            ll = 0.0
            for p, t in zip(ps, y_true, strict=False):
                pp = min(max(p, eps), 1 - eps)
                yb = 1.0 if t == classes[1] else 0.0
                ll += -(yb * math.log(pp) + (1 - yb) * math.log(1 - pp))
            ll /= len(y_true)
            out["brier_score"] = brier
            out["log_loss"] = ll
        else:
            out["brier_score"] = None
            out["log_loss"] = None
    else:
        out["brier_score"] = None
        out["log_loss"] = None
    out["roc_auc"] = None
    if y_proba is not None and len(classes) == 2:
        try:
            ps = [
                pr[1] if isinstance(pr, list | tuple) and len(pr) > 1 else float(cast(Any, pr))
                for pr in y_proba
            ]
            pos = [ps[i] for i in range(len(y_true)) if y_true[i] == classes[1]]
            neg = [ps[i] for i in range(len(y_true)) if y_true[i] == classes[0]]
            if pos and neg:
                cnt = 0.0
                for p in pos:
                    for n in neg:
                        if p > n:
                            cnt += 1
                        elif p == n:
                            cnt += 0.5
                out["roc_auc"] = cnt / (len(pos) * len(neg))
        except Exception:
            out["roc_auc"] = None
    return out


def regression_metrics(y_true: Sequence[float], y_pred: Sequence[float]) -> dict[str, Any]:
    return {
        "mae": mae(y_true, y_pred),
        "rmse": rmse(y_true, y_pred),
        "r2": r2_score(y_true, y_pred),
        "mean_error": mean_error(y_true, y_pred),
    }


def calibration_bins(
    y_true: Sequence[float], proba: Sequence[float], n_bins: int = 10
) -> list[dict[str, Any]]:
    bins: list[dict[str, Any]] = []
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        idx = [
            i
            for i in range(len(y_true))
            if lo <= proba[i] < hi or (b == n_bins - 1 and proba[i] == 1.0)
        ]
        if not idx:
            bins.append({"bin": b, "count": 0, "mean_pred": None, "empirical_rate": None})
            continue
        mp = sum(proba[i] for i in idx) / len(idx)
        er = sum(1.0 for i in idx if y_true[i] == 1) / len(idx)
        bins.append({"bin": b, "count": len(idx), "mean_pred": mp, "empirical_rate": er})
    return bins


def fold_bootstrap_ci(values: Sequence[float], n_boot: int = 200, seed: int = 0) -> dict[str, Any]:
    if not values:
        return {"mean": None, "ci_lower": None, "ci_upper": None, "n_boot": n_boot}
    rng = random.Random(seed)  # noqa: S311
    n = len(values)
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    return {"mean": sum(values) / n, "ci_lower": lo, "ci_upper": hi, "n_boot": n_boot}
