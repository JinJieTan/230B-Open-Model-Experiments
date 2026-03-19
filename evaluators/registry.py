from __future__ import annotations

from typing import Any, Callable

from evaluators.heuristics import evaluate_generic


Evaluator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


_PROFILE_TO_EVALUATOR: dict[str, Evaluator] = {
    "strategy": evaluate_generic,
    "debate": evaluate_generic,
    "coding": evaluate_generic,
    "reasoning": evaluate_generic,
    "creative": evaluate_generic,
    "dialogue": evaluate_generic,
    "classification": evaluate_generic,
    "forecasting": evaluate_generic,
}


def evaluate_experiment(config: dict[str, Any], run_result: dict[str, Any]) -> dict[str, Any]:
    profile = str(config.get("scoring_profile", "generic")).strip().lower()
    evaluator = _PROFILE_TO_EVALUATOR.get(profile, evaluate_generic)
    return evaluator(config, run_result)
