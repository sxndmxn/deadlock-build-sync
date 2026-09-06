"""Overlapping factors, binary latent classes, and item-graph communities."""

from __future__ import annotations

import warnings
from itertools import combinations

import igraph
import leidenalg
import numpy as np
from scipy.special import logsumexp
from sklearn.decomposition import NMF
from sklearn.exceptions import ConvergenceWarning


def profile_triples(profiles: np.ndarray, marginal: np.ndarray) -> set[tuple[int, ...]]:
    proposed = set()
    for profile in profiles:
        strength = profile / np.sqrt(marginal.clip(1e-6))
        top = np.argsort(-strength, kind="stable")[:8]
        proposed.update(
            tuple(sorted(int(item) for item in core)) for core in combinations(top, 3)
        )
    return proposed


def nmf(matrix: np.ndarray, seed: int, components: int = 6) -> tuple[set, dict]:
    model = NMF(
        n_components=components,
        init="random",
        solver="mu",
        beta_loss="kullback-leibler",
        max_iter=500,
        tol=0.0001,
        random_state=seed,
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", ConvergenceWarning)
        model.fit(matrix.astype(float))
    return profile_triples(model.components_, matrix.mean(axis=0)), {
        "components": model.components_.tolist(),
        "iterations": int(model.n_iter_),
        "reconstruction_error": float(model.reconstruction_err_),
        "warnings": [str(warning.message) for warning in captured],
    }


def bernoulli_log_prob(
    matrix: np.ndarray, theta: np.ndarray, weights: np.ndarray
) -> np.ndarray:
    return (
        matrix @ (np.log(theta) - np.log1p(-theta)).T
        + np.log1p(-theta).sum(axis=1)
        + np.log(weights)
    )


def bernoulli_fit(
    matrix: np.ndarray, seed: int, components: int = 6, iterations: int = 500
) -> tuple[np.ndarray, dict]:
    data = matrix.astype(float)
    rng = np.random.default_rng(seed)
    theta = (
        0.1
        + 0.8 * data[rng.choice(len(data), components, replace=False)]
        + rng.uniform(-0.05, 0.05, (components, data.shape[1]))
    ).clip(0.01, 0.99)
    weights = np.full(components, 1 / components)
    history, previous = [], -np.inf
    for step in range(iterations):
        log_prob = bernoulli_log_prob(data, theta, weights)
        objective = float(
            logsumexp(log_prob, axis=1).sum()
            + 0.5
            * (np.log(theta).sum() + np.log1p(-theta).sum() + np.log(weights).sum())
        )
        if step % 25 == 0:
            history.append(objective)
        if step and abs(objective - previous) / len(data) < 1e-6:
            break
        previous = objective
        responsibilities = np.exp(log_prob - logsumexp(log_prob, axis=1, keepdims=True))
        mass = responsibilities.sum(axis=0)
        theta = (responsibilities.T @ data + 0.5) / (mass[:, None] + 1)
        weights = (mass + 0.5) / (len(data) + components * 0.5)
    return theta, {
        "components": theta.tolist(),
        "mixture_weights": weights.tolist(),
        "iterations": step + 1,
        "converged": step + 1 < iterations,
        "penalized_log_likelihood": history,
        "final_objective": objective,
    }


def bernoulli(matrix: np.ndarray, seed: int, components: int = 6) -> tuple[set, dict]:
    theta, diagnostic = bernoulli_fit(matrix, seed, components)
    return profile_triples(theta, matrix.mean(axis=0)), diagnostic


def leiden(matrix: np.ndarray, seed: int, minimum: int = 100) -> tuple[set, dict]:
    data = matrix.astype(float)
    joint = data.T @ data
    marginal = data.mean(axis=0)
    expected = len(data) * marginal[:, None] * marginal[None, :]
    lift = joint / expected.clip(1e-6)
    valid = np.triu((joint >= minimum) & (lift >= 1.1), k=1)
    first, second = np.nonzero(valid)
    weights = (joint[valid] / len(data) * np.log(lift[valid])).tolist()
    graph = igraph.Graph(
        n=matrix.shape[1],
        edges=list(zip(first.tolist(), second.tolist(), strict=True)),
        directed=False,
    )
    if not weights:
        return set(), {"edges": 0, "communities": [], "modularity": None}
    partition = leidenalg.find_partition(
        graph,
        leidenalg.RBConfigurationVertexPartition,
        weights=weights,
        resolution_parameter=1,
        n_iterations=10,
        seed=seed,
    )
    adjacency = np.zeros_like(joint)
    adjacency[first, second] = weights
    adjacency[second, first] = weights
    proposed = set()
    for community in partition:
        strength = adjacency[np.ix_(community, community)].sum(axis=1)
        top = np.asarray(community)[np.argsort(-strength, kind="stable")[:8]]
        proposed.update(
            tuple(sorted(int(item) for item in core)) for core in combinations(top, 3)
        )
    return proposed, {
        "edges": len(weights),
        "communities": [list(community) for community in partition],
        "modularity": float(partition.quality()),
    }
