import ctypes
import os.path as op
import re
import struct
from collections import Counter, defaultdict
from collections.abc import Generator, Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from functools import cache, reduce
from math import sqrt
from operator import add
from pathlib import Path
from time import time
from typing import TypeVar

from fuzzywuzzy import fuzz, process  # pyright: ignore[reportMissingTypeStubs]
from jellyfish import damerau_levenshtein_distance

import const as cs

T = TypeVar(name='T')


@dataclass
class Answer:

    path: Path
    dir: Path

    stem: str
    runs: int
    score: float

    @property
    def name(self) -> str:
        return self.path.name



if not cs.DLL.is_file():
    raise FileNotFoundError(
        f"please, unpack dll's from Everything SDK to `{cs.DLL.parent}`")


@cache
def to_path(path: str) -> Path:
    return Path(path)


def get_time(filetime: bytes) -> datetime:
    value = struct.unpack('<Q', filetime)[0]
    return datetime.fromtimestamp((value - cs.WIN2POSIX) / cs.WINDOWS_TICKS)


def unique(iterable: Iterable[T]) -> Generator[T, None, None]:
    seen: set[T] = set()

    for item in iterable:
        if item not in seen:
            yield item
            seen.add(item)


@cache
def distance(x, y) -> int:
    return damerau_levenshtein_distance(x, y)


@cache
def distance_relative(x, y) -> float:
    with suppress(ZeroDivisionError):
        return distance(x, y) / float(min(len(x), len(y)))
    return .0


@cache
def get_api() -> ctypes.WinDLL:
    return ctypes.WinDLL(cs.DLL)


def search_api(term: str) -> ctypes.WinDLL:

    api = get_api()
    api.Everything_GetResultRunCount.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_ulonglong),
    ]

    api.Everything_SetRegex(False)

    api.Everything_SetMatchPath(False)

    api.Everything_SetMatchCase(False)

    api.Everything_SetMatchWholeWord(True)

    api.Everything_SetSort(
        cs.SortingCriteria.RUN_COUNT_DESCENDING.value
    )

    api.Everything_SetSearchW(
        f'file:ext:{";".join(cs.ENABLED_EXTENSIONS)} *{term}*'
    )

    api.Everything_SetRequestFlags(
        cs.SearchRequest.FILE_NAME |
        cs.SearchRequest.PATH |
        cs.SearchRequest.RUN_COUNT |
        cs.SearchRequest.EXTENSION
    )
    return api


@cache
def get_used_chars(x: list[str]) -> str:
    stems: tuple[str, ...] = tuple(unique(x))
    return ''.join(stems)


@cache
def count_missing_letters(term: str, base: str) -> int:
    set_term = set(term)
    common = set_term & set(base)
    return len(set_term) - len(common)


@cache
def same_start_bonus(term: str, base: str) -> int:
    for i in range(len(term)):
        try:
            if term[i] != base[i]:
                return i
        except IndexError:
            return i
    return len(term)


@cache
def count_missing_chars_count(term: str, base: str) -> float:
    set_term = set(term)
    common = set_term & set(base)
    return (len(set_term) - len(common)) / len(term)


def call_dll_search(term: str):

    term = re.sub(r'(\s+)', ' ', term.strip().lower())
    if len(term) <= cs.MIN_QUERY_LENGTH:
        return term, []

    query: str = '*'.join(map('*'.join, term.split(' ')))

    api = search_api(query)
    api.Everything_QueryW(True)  # False == async

    buf_path = ctypes.create_unicode_buffer(260)
    buf_count = ctypes.c_ulonglong(1)

    result = defaultdict(list)
    for no in range(api.Everything_GetNumResults()):

        api.Everything_GetResultFullPathNameW(no, buf_path, 260)

        full = ctypes.wstring_at(buf_path)
        lowered = full.lower()

        if (
            lowered.startswith(cs.WINDOWS_SXS_REPOSITORY) or
            lowered.startswith(cs.WINDOWS_CONTAINERS_LAYERS)
        ):
            continue

        split = op.splitext(op.basename(full))
        if split[-1][1:].lower() not in cs.ENABLED_EXTENSIONS:
            continue

        base = op.basename(full).lower()
        runs = api.Everything_GetResultRunCount(no, buf_count)

        result[base].append((full, runs))

    api.Everything_CleanUp()
    return term, dict(result)


def _lookup(query: str) -> tuple[Answer, ...]:

    def sort_by_length_delta(x) -> int:
        return abs(len(term) - len(x))

    term, order = call_dll_search(query)
    if not order:
        return []

    ratio = dict(
        process.extract(
            term,
            sorted(order),
            scorer=fuzz.token_sort_ratio,
            limit=len(order),
        )
    )

    length = len(term)
    rates = Counter()
    chars = get_used_chars(term)

    for stem in sorted(order, key=sort_by_length_delta):

        if count_missing_letters(term, stem) > cs.MAX_MISSING_LETTERS:
            continue

        base = get_used_chars(stem)

        # calc absolute and relative Damerau-Levenstein distance
        rate = (
            distance(chars, base) *
            distance_relative(chars, base)
        )

        rate *= sqrt(1 + distance(term, stem[:length]))

        rate *= sqrt(1 + count_missing_chars_count(term, stem))

        rate /= 1 + same_start_bonus(term, stem)

        rate *= float(ratio.get(stem, 0)) / 100

        if rate <= cs.MAX_RATE_FOR_RESULT:
            rates[stem] = rate

    result = defaultdict(list)

    for stem, rate in reversed(rates.most_common()):
        for full, count in order[stem]:

            path = to_path(full)

            try:
                if not path.exists():
                    continue
            except PermissionError:
                continue

            result[count].append(
                Answer(
                    path=path,
                    dir=path.parent,
                    stem=stem,
                    runs=count,
                    score=rate
                )
            )

    result = [result[i] for i in sorted(result, reverse=True)]

    result = tuple(tuple(reduce(add, result)) if result else [])

    result = result[:cs.MAX_RESULTS_COUNT]
    return result


def lookup(query: str) -> tuple[Answer, ...]:
    if cs.Keyboard.IsCyrillic(query):
        query = cs.Keyboard.Translate(query)
    return _lookup(query)


def increment(path: str) -> None:
    path = re.sub(r'(\\+)', r'\\', path)

    api = get_api()
    api.Everything_IncRunCountFromFileNameW(path)
    api.Everything_CleanUp()


if __name__ == '__main__':
    from sys import argv
    query = ' '.join(argv[1:]).lower()

    start = time()
    order = lookup(query)
    print(f' ++ {time() - start:f}s {len(order):d} files for {query}')

    for no, item in enumerate(order[:20]):
        print(
            f'{no:2d}. '
            f'{item.runs:d} '
            f'{item.score:0.3f} '
            f'{item.path} '
        )
        # print(dir(item.path))
