from __future__ import annotations

from typing import Any, Callable, Dict

from evaluators.heuristics import evaluate_generic


Evaluator = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


_PROFILE_TO_EVALUATOR: Dict[str, Evaluator] = {
    "strategy": evaluate_generic,
    "debate": evaluate_generic,
    "coding": evaluate_generic,
    "reasoning": evaluate_generic,
    "creative": evaluate_generic,
    "dialogue": evaluate_generic,
    "classification": evaluate_generic,
    "forecasting": evaluate_generic,
}


def evaluate_experiment(config: Dict[str, Any], run_result: Dict[str, Any]) -> Dict[str, Any]:
    profile = str(config.get("scoring_profile", "generic")).strip().lower()
    evaluator = _PROFILE_TO_EVALUATOR.get(profile, evaluate_generic)
    return evaluator(config, run_result)
