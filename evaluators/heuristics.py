from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?\n])\s+")


@dataclass
class HeuristicScore:
    final_score: float
    keyword_coverage: float
    format_score: float
    length_score: float
    coherence_score: float


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_lower(text: str) -> str:
    return text.lower() if text else ""


def keyword_coverage(text: str, required_keywords: list[str]) -> float:
    if not required_keywords:
        return 1.0

    lowered_text = _safe_lower(text)
    hit_count = sum(1 for keyword in required_keywords if keyword.lower() in lowered_text)
    return _clip(hit_count / len(required_keywords))


def format_score(text: str) -> float:
    if not text:
        return 0.0

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0

    heading_hits = sum(1 for line in lines if line.startswith("#") or line.endswith(":"))
    bullet_hits = sum(1 for line in lines if line.startswith("-") or re.match(r"^\d+\.\s", line))
    block_count = len(re.split(r"\n\s*\n", text.strip()))

    heading_score = _clip(heading_hits / 4)
    bullet_score = _clip(bullet_hits / 6)
    block_score = _clip(block_count / 4)

    return round((0.35 * heading_score) + (0.45 * bullet_score) + (0.20 * block_score), 4)


def length_score(text: str) -> float:
    target_chars = 2500
    if not text:
        return 0.0
    return round(_clip(len(text) / target_chars), 4)


def coherence_score(text: str) -> float:
    if not text:
        return 0.0

    sentences = [s.strip().lower() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if len(sentences) < 2:
        return 0.4

    unique_ratio = len(set(sentences)) / len(sentences)

    contradiction_pairs = [
        ("must", "must not"),
        ("always", "never"),
        ("certain", "uncertain"),
    ]

    lowered_text = _safe_lower(text)
    contradiction_hits = 0
    for a, b in contradiction_pairs:
        if a in lowered_text and b in lowered_text:
            contradiction_hits += 1

    contradiction_penalty = min(0.25, contradiction_hits * 0.08)
    score = _clip(unique_ratio - contradiction_penalty)
    return round(score, 4)


def combine_scores(scores: HeuristicScore) -> float:
    weighted = (
        0.45 * scores.keyword_coverage
        + 0.2 * scores.format_score
        + 0.15 * scores.length_score
        + 0.2 * scores.coherence_score
    )
    return round(_clip(weighted), 4)


def extract_full_text(run_result: dict[str, Any]) -> str:
    rounds = run_result.get("rounds", [])
    parts: list[str] = []
    for item in rounds:
        content = item.get("response", "")
        if content:
            parts.append(content)
    return "\n\n".join(parts).strip()


def evaluate_generic(config: dict[str, Any], run_result: dict[str, Any]) -> dict[str, Any]:
    status = run_result.get("status", "unknown")
    if status != "completed":
        return {
            "status": status,
            "final_score": 0.0,
            "keyword_coverage": 0.0,
            "format_score": 0.0,
            "length_score": 0.0,
            "coherence_score": 0.0,
            "notes": "Run not completed; score set to 0.",
        }

    text = extract_full_text(run_result)
    scores = HeuristicScore(
        final_score=0.0,
        keyword_coverage=keyword_coverage(text, config.get("required_keywords", [])),
        format_score=format_score(text),
        length_score=length_score(text),
        coherence_score=coherence_score(text),
    )
    final_score = combine_scores(scores)

    return {
        "status": "completed",
        "final_score": final_score,
        "keyword_coverage": scores.keyword_coverage,
        "format_score": scores.format_score,
        "length_score": scores.length_score,
        "coherence_score": scores.coherence_score,
        "notes": "Heuristic score (baseline). Replace with task-specific evaluator for publish-grade benchmarking.",
    }
