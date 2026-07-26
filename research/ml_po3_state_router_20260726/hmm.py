from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Iterable

import numpy as np


@dataclass
class HMMFitResult:
    log_likelihoods: list[float]


class DiagonalGaussianHMM:
    """Small deterministic diagonal-Gaussian HMM.

    Baum-Welch uses scaled forward/backward recursions. Trading code may use
    only ``filter``; smoothed gamma and Viterbi paths are never exposed to the
    strategy evaluator.
    """

    def __init__(
        self,
        n_states: int = 3,
        n_iter: int = 12,
        covariance_floor: float = 0.05,
        diagonal_prior: float = 5.0,
        random_seed: int = 20260726,
    ) -> None:
        if n_states != 3:
            raise ValueError("this frozen study requires exactly three states")
        self.n_states = int(n_states)
        self.n_iter = int(n_iter)
        self.covariance_floor = float(covariance_floor)
        self.diagonal_prior = float(diagonal_prior)
        self.random_seed = int(random_seed)
        self.startprob_: np.ndarray | None = None
        self.transmat_: np.ndarray | None = None
        self.means_: np.ndarray | None = None
        self.covars_: np.ndarray | None = None

    @staticmethod
    def _as_sequences(sequences: Iterable[np.ndarray]) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        width: int | None = None
        for sequence in sequences:
            array = np.asarray(sequence, dtype=np.float64)
            if array.ndim != 2 or len(array) < 2:
                continue
            if width is None:
                width = int(array.shape[1])
            if int(array.shape[1]) != width:
                raise ValueError("feature width mismatch")
            if not np.isfinite(array).all():
                raise ValueError("non-finite HMM observation")
            out.append(array)
        if not out:
            raise ValueError("no usable HMM sequences")
        return out

    def _initialize(self, sequences: list[np.ndarray]) -> None:
        x = np.concatenate(sequences, axis=0)
        if x.shape[1] != 5:
            raise ValueError("the frozen model requires exactly five features")

        # Fixed, outcome-free initial semantic prototypes.
        acc_score = np.abs(x[:, 0]) + x[:, 1] + 0.5 * np.abs(x[:, 2])
        manipulation_score = x[:, 1] + np.abs(x[:, 3]) + 0.25 * np.abs(x[:, 0]) - 0.25 * np.abs(x[:, 2])
        distribution_score = np.abs(x[:, 0]) + np.abs(x[:, 2]) + 0.5 * np.abs(x[:, 4]) - 0.25 * np.abs(x[:, 3])

        selectors = [
            acc_score <= np.quantile(acc_score, 0.20),
            manipulation_score >= np.quantile(manipulation_score, 0.80),
            distribution_score >= np.quantile(distribution_score, 0.80),
        ]
        means = []
        for state, selector in enumerate(selectors):
            chosen = x[selector]
            if len(chosen) < 20:
                chosen = x[state :: self.n_states]
            means.append(np.mean(chosen, axis=0))
        self.means_ = np.asarray(means, dtype=np.float64)

        global_var = np.var(x, axis=0) + self.covariance_floor
        self.covars_ = np.tile(global_var, (self.n_states, 1))
        self.startprob_ = np.full(self.n_states, 1.0 / self.n_states, dtype=np.float64)
        off = (1.0 - 0.94) / (self.n_states - 1)
        self.transmat_ = np.full((self.n_states, self.n_states), off, dtype=np.float64)
        np.fill_diagonal(self.transmat_, 0.94)

    def _require_parameters(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if self.startprob_ is None or self.transmat_ is None or self.means_ is None or self.covars_ is None:
            raise RuntimeError("HMM is not fitted")
        return self.startprob_, self.transmat_, self.means_, self.covars_

    def _emission(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        _, _, means, covars = self._require_parameters()
        diff = x[:, None, :] - means[None, :, :]
        log_det = np.sum(np.log(2.0 * np.pi * covars), axis=1)
        quadratic = np.sum(diff * diff / covars[None, :, :], axis=2)
        log_prob = -0.5 * (quadratic + log_det[None, :])
        row_offset = np.max(log_prob, axis=1)
        emission = np.exp(np.clip(log_prob - row_offset[:, None], -745.0, 0.0))
        emission = np.maximum(emission, 1e-300)
        return emission, row_offset

    def _forward_backward(
        self, x: np.ndarray
    ) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
        startprob, transmat, _, _ = self._require_parameters()
        emission, row_offset = self._emission(x)
        t_count = len(x)
        k = self.n_states
        alpha = np.empty((t_count, k), dtype=np.float64)
        scales = np.empty(t_count, dtype=np.float64)

        alpha[0] = startprob * emission[0]
        scales[0] = max(float(alpha[0].sum()), 1e-300)
        alpha[0] /= scales[0]
        for t in range(1, t_count):
            alpha[t] = (alpha[t - 1] @ transmat) * emission[t]
            scales[t] = max(float(alpha[t].sum()), 1e-300)
            alpha[t] /= scales[t]

        beta = np.ones((t_count, k), dtype=np.float64)
        for t in range(t_count - 2, -1, -1):
            beta[t] = transmat @ (emission[t + 1] * beta[t + 1])
            beta[t] /= scales[t + 1]

        gamma = alpha * beta
        gamma /= np.maximum(gamma.sum(axis=1, keepdims=True), 1e-300)

        xi_sum = np.zeros((k, k), dtype=np.float64)
        for t in range(t_count - 1):
            next_weight = emission[t + 1] * beta[t + 1]
            xi = alpha[t, :, None] * transmat * next_weight[None, :]
            denominator = float(xi.sum())
            if denominator > 0.0:
                xi_sum += xi / denominator

        log_likelihood = float(np.sum(np.log(scales) + row_offset))
        return log_likelihood, gamma, xi_sum, alpha

    def fit(self, sequences: Iterable[np.ndarray]) -> HMMFitResult:
        seqs = self._as_sequences(sequences)
        self._initialize(seqs)
        history: list[float] = []

        for _ in range(self.n_iter):
            _, _, means, _ = self._require_parameters()
            feature_count = means.shape[1]
            start_sum = np.zeros(self.n_states, dtype=np.float64)
            transition_sum = np.zeros((self.n_states, self.n_states), dtype=np.float64)
            gamma_sum = np.zeros(self.n_states, dtype=np.float64)
            x_sum = np.zeros((self.n_states, feature_count), dtype=np.float64)
            x2_sum = np.zeros((self.n_states, feature_count), dtype=np.float64)
            total_ll = 0.0

            for sequence in seqs:
                log_likelihood, gamma, xi_sum, _ = self._forward_backward(sequence)
                total_ll += log_likelihood
                start_sum += gamma[0]
                transition_sum += xi_sum
                gamma_sum += gamma.sum(axis=0)
                x_sum += gamma.T @ sequence
                x2_sum += gamma.T @ (sequence * sequence)

            if np.any(gamma_sum <= 1e-6):
                raise RuntimeError("collapsed HMM state")

            self.startprob_ = start_sum / max(float(start_sum.sum()), 1e-300)
            prior = np.full_like(transition_sum, 0.1)
            prior += np.eye(self.n_states) * self.diagonal_prior
            transition = transition_sum + prior
            self.transmat_ = transition / np.maximum(transition.sum(axis=1, keepdims=True), 1e-300)
            self.means_ = x_sum / gamma_sum[:, None]
            variance = x2_sum / gamma_sum[:, None] - self.means_ * self.means_
            self.covars_ = np.maximum(variance, self.covariance_floor)
            history.append(total_ll)
            if len(history) >= 2:
                relative = abs(history[-1] - history[-2]) / max(1.0, abs(history[-2]))
                if relative < 1e-6:
                    break

        return HMMFitResult(log_likelihoods=history)

    def filter(self, sequence: np.ndarray) -> np.ndarray:
        """Return causal filtered probabilities p(z_t | x_0..x_t)."""
        x = np.asarray(sequence, dtype=np.float64)
        if x.ndim != 2 or len(x) == 0:
            raise ValueError("filter requires a non-empty 2-D sequence")
        startprob, transmat, _, _ = self._require_parameters()
        emission, _ = self._emission(x)
        alpha = np.empty((len(x), self.n_states), dtype=np.float64)
        alpha[0] = startprob * emission[0]
        alpha[0] /= max(float(alpha[0].sum()), 1e-300)
        for t in range(1, len(x)):
            alpha[t] = (alpha[t - 1] @ transmat) * emission[t]
            alpha[t] /= max(float(alpha[t].sum()), 1e-300)
        return alpha

    def semantic_mapping(self) -> dict[str, int]:
        """Map fitted anonymous states to PO3 semantics using fixed scores."""
        _, _, means, _ = self._require_parameters()
        best: tuple[float, tuple[int, int, int]] | None = None
        for acc, manipulation, distribution in permutations(range(self.n_states), 3):
            a = means[acc]
            m = means[manipulation]
            d = means[distribution]
            acc_score = -abs(a[0]) - a[1] - 0.5 * abs(a[2])
            manipulation_score = m[1] + abs(m[3]) + 0.25 * abs(m[0]) - 0.25 * abs(m[2])
            distribution_score = abs(d[0]) + abs(d[2]) + 0.5 * abs(d[4]) - 0.25 * abs(d[3])
            score = float(acc_score + manipulation_score + distribution_score)
            if best is None or score > best[0]:
                best = (score, (acc, manipulation, distribution))
        if best is None:
            raise RuntimeError("semantic mapping failed")
        acc, manipulation, distribution = best[1]
        return {
            "accumulation": int(acc),
            "manipulation": int(manipulation),
            "distribution": int(distribution),
        }

    def to_dict(self) -> dict[str, object]:
        startprob, transmat, means, covars = self._require_parameters()
        return {
            "n_states": self.n_states,
            "n_iter": self.n_iter,
            "covariance_floor": self.covariance_floor,
            "diagonal_prior": self.diagonal_prior,
            "random_seed": self.random_seed,
            "startprob": startprob.tolist(),
            "transmat": transmat.tolist(),
            "means": means.tolist(),
            "covars": covars.tolist(),
        }
