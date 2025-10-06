import ctypes
import os.path as op
import re
import struct
from collections import Counter, defaultdict
from collections.abc import Generator, Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from math import sqrt
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


def call_everything(term: str) -> ctypes.WinDLL:

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
    chars: tuple[str, ...] = tuple(unique(x))
    return ''.join(chars)


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


def get_extension(path: str) -> str:
    result: list[str] = []
    for char in reversed(path):
        if char in ('.', '\\', '/'):
            break
        result.append(char)

    if len(result) == len(path):
        return ''
    return ''.join(reversed(result)).lower()


def its_ignored_path(path: str) -> bool:
    lowered = path.lower()
    if (
        lowered.startswith(cs.WINDOWS_SXS_REPOSITORY) or
        lowered.startswith(cs.WINDOWS_CONTAINERS_LAYERS)
    ):
        return True

    return get_extension(lowered) not in cs.ENABLED_EXTENSIONS


def call_dll_search(query: str) -> dict[str, list[tuple[str, int]]]:

    query = re.sub(r'(\s+)', ' ', query.strip().lower())
    if len(query) <= cs.MIN_QUERY_LENGTH:
        return {}

    term: str = '*'.join(map('*'.join, query.split(' ')))

    # call Everything via ABI interface
    api = call_everything(term)
    api.Everything_QueryW(True)  # set sync mode

    result = defaultdict(list)
    result_count: int = api.Everything_GetNumResults()

    # allocate buffers for retrieve result
    int_ptr = ctypes.c_ulonglong(1)
    str_ptr = ctypes.create_unicode_buffer(260)

    for no in range(result_count):

        # put result number to buffer
        api.Everything_GetResultFullPathNameW(no, str_ptr, 260)

        # read string from buffer
        path = ctypes.wstring_at(str_ptr)

        # skip path, can be only executable and not in hidden folders
        if its_ignored_path(path):
            continue

        # read run count from buffer
        runs = api.Everything_GetResultRunCount(no, int_ptr)

        base = op.basename(path).lower()
        result[base].append((path, runs))

    api.Everything_CleanUp()
    return dict(result)


def subsequence_match(query: str, stem: str) -> float:
    if not query:
        return 0.0

    query_idx = 0
    match_positions = []

    for text_idx, char in enumerate(stem):
        if query_idx < len(query) and char == query[query_idx]:
            match_positions.append(text_idx)
            query_idx += 1

    if query_idx != len(query):
        return 0.0

    if len(match_positions) < 2:
        density = 1.0

    else:
        gaps = [
            match_positions[i + 1] - match_positions[i]
            for i in range(len(match_positions) - 1)
        ]
        avg_gap = sum(gaps) / len(gaps)
        density = 1.0 / (1.0 + avg_gap * 0.1)

    start_bonus = 1.2 if match_positions[0] == 0 else 1.0
    length_ratio = len(query) / len(stem)
    return density * start_bonus * (0.5 + length_ratio * 0.5)


def precompute_scores(
    query: str,
    order: dict[str, list[tuple[str, int]]],
) -> dict[str, float]:

    def sort_by_length_delta(x) -> int:
        return abs(len(query) - len(x))

    ratio = dict(
        process.extract(
            query,
            sorted(order),
            scorer=fuzz.token_sort_ratio,
            limit=len(order),
        )
    )

    result = {}
    length = len(query)
    chars = get_used_chars(query)

    for word in sorted(order, key=sort_by_length_delta):
        if ext := get_extension(word):
            stem = word[:-len(ext) -1]
        else:
            stem = word

        if count_missing_letters(query, stem) > cs.MAX_MISSING_LETTERS:
            continue

        base = get_used_chars(stem)

        if stem == query:
            rate = 20.0

        elif stem.startswith(query):
            rate = 5.0

        else:
            rate = 1.0

        by_match = (
            distance(query, stem) *
            distance_relative(query, stem)
        )
        rate /= sqrt(1 + by_match) + 1

        by_chars = (
            distance(chars, base) *
            distance_relative(chars, base)
        )
        rate /= sqrt(1 + by_chars) + 1

        rate *= (
            subsequence_match(query, stem) +
            subsequence_match(chars, base)
        )

        rate /= sqrt(1 + by_chars) * sqrt(1 + by_match)

        rate /= sqrt(1 + distance(query, stem[:length]))

        rate /= sqrt(1 + count_missing_chars_count(query, stem))

        rate /= 1 + same_start_bonus(query, stem)

        rate /= float(ratio.get(word, 1)) / 100

        if rate <= 0.001:
            continue

        result[word] = rate

    return result


def postprocess_scoring(
    order: dict[str, list[tuple[str, int]]],
    scores: dict[str, float],
) -> tuple[Answer, ...]:
    result = defaultdict(list)

    runstat = {}
    scoring = {}
    mapping = defaultdict(list)

    for stem, score in scores.items():
        for full, runs in order[stem]:
            path = to_path(full)

            # check file existence and have permissions
            try:
                stat = path.stat()
            except Exception:
                continue

            # use (inode, device) as unique file identifier
            key = stat.st_ino, stat.st_dev
            mapping[key].append(full)

            if key not in scoring:
                runstat[key] = runs
                scoring[key] = sqrt(runs + 1) * sqrt(score + 1)

    # lock mapping to avoid changes during missing __getitem__
    mapping = dict(mapping)

    result = []
    for key, score in Counter(scoring).most_common(cs.MAX_RESULTS_COUNT):

        # take the shortest path from duplicates
        path = to_path(sorted(mapping[key], key=len)[0])

        # finally, prepare the answer
        result.append(
            Answer(
                path=path,
                dir=path.parent,
                stem=path.stem,
                runs=runstat[key],
                score=score,
            )
        )

    return tuple(result)


def _lookup(query: str) -> tuple[Answer, ...]:
    order = call_dll_search(query)
    if not order:
        return ()

    scores = precompute_scores(query, order)
    return postprocess_scoring(order, scores)



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
