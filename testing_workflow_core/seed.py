from __future__ import annotations


def agent_seed(run_timestamp: int, user_index: int, iteration_index: int, salt: int = 0) -> int:
    return (run_timestamp * 1_000_003) + (user_index * 9_973) + iteration_index + salt
