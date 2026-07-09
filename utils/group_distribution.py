from __future__ import annotations

from typing import Sequence, TypeVar


T = TypeVar("T")


def split_groups_for_accounts(groups: Sequence[T] | None, accounts_count: int) -> list[list[T]]:
    if accounts_count <= 0:
        return []

    group_items = list(groups or [])
    base_size = len(group_items) // accounts_count
    remainder = len(group_items) % accounts_count
    first_remainder_index = accounts_count - remainder

    chunks: list[list[T]] = []
    start = 0
    for account_index in range(accounts_count):
        chunk_size = base_size
        if remainder and account_index >= first_remainder_index:
            chunk_size += 1

        end = start + chunk_size
        chunks.append(group_items[start:end])
        start = end

    return chunks
