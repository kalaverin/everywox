import ctypes
import os
import os.path as op
import re
import struct
from collections import Counter, defaultdict
from collections.abc import Generator, Iterable
from datetime import datetime
from functools import cache, reduce
from math import sqrt
from operator import add
from pathlib import Path
from time import time
from typing import TypeVar

from fuzzywuzzy import fuzz, process  # pyright: ignore[reportMissingTypeStubs]
from jellyfish import damerau_levenshtein_distance

from const import (
    EXTENSIONS,
    KEYBOARD,
    MAX_MISSING_LETTERS,
    MAX_RATE_FOR_RESULT,
    MAX_RESULTS_COUNT,
    MIN_QUERY_LENGTH,
    REQUEST,
    SORT,
)

T = TypeVar('T')

# CACHE = Redis(expire=60, options={'socket_connect_timeout' : 0.01})
CACHE = None

#

FILE = Path(__file__)
ARCH: int = 64 if 'PROGRAMFILES(X86)' in os.environ else 32
DLL: Path = FILE.parent / 'Dll' / f'Everything{ARCH}.dll'

POSIX_EPOCH = datetime.strptime(
    '1970-01-01 00:00:00',
    '%Y-%m-%d %H:%M:%S',
)

WINDOWS_EPOCH = datetime.strptime(
    '1601-01-01 00:00:00',
    '%Y-%m-%d %H:%M:%S',
)

WINDOWS_TICKS: int = int(1 / 10 ** -7)  # 10,000,000 (100 nanoseconds or .1 microseconds)
EPOCH_DIFF: float = (POSIX_EPOCH - WINDOWS_EPOCH).total_seconds()  # 11644473600.0
WIN2POSIX: float = (EPOCH_DIFF * WINDOWS_TICKS)  # 116444736000000000.0


if not DLL.is_file():
    raise FileNotFoundError(
        f"please, unpack dll's from Everything SDK to `{DLL.parent}`")


def get_time(filetime):
    return datetime.fromtimestamp(
        (struct.unpack('<Q', filetime)[0] - WIN2POSIX) / WINDOWS_TICKS)


def unique(iterable: Iterable[T]) -> Generator[T, None, None]:
    seen: set[T] = set()

    for item in iterable:
        if item not in seen:
            yield item
        seen.add(item)


@cache
def distance(x, y):
    return damerau_levenshtein_distance(x, y)


@cache
def distance_relative(x, y):
    try:
        return distance(x, y) / float(min([len(x), len(y)]))
    except ZeroDivisionError:
        return .0


@cache
def get_api():
    return ctypes.WinDLL(DLL)


def search_api(term: str) -> ctypes.WinDLL:
    api = get_api()

    api.Everything_GetResultRunCount.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_ulonglong)]

    api.Everything_SetRegex(False)

    api.Everything_SetMatchPath(False)

    api.Everything_SetMatchCase(False)

    api.Everything_SetMatchWholeWord(True)

    api.Everything_SetSort(SORT.RUN_COUNT_DESCENDING)

    api.Everything_SetSearchW(r'file:ext:{} *{}*'.format(';'.join(EXTENSIONS), term))

    api.Everything_SetRequestFlags(
        REQUEST.FILE_NAME |
        REQUEST.PATH |
        REQUEST.RUN_COUNT |
        REQUEST.EXTENSION
    )
    return api


@cache
def unique_letters(x: list[str]) -> str:
    stems: tuple[str, ...] = tuple(unique(x))
    return ''.join(stems)


@cache
def count_missing_letters(term: str, base: str) -> int:
    set_term = set(term)
    common = set_term & set(base)
    return len(set_term) - len(common)


@cache
def count_common_head(term: str, base: str) -> int:
    for i in range(len(term)):
        try:
            if term[i] != base[i]:
                return i
        except IndexError:
            return i
    return len(term)


@cache
def count_missing_letters_rel(term: str, base: str):
    set_term = set(term)
    common = set_term & set(base)
    return (len(set_term) - len(common)) / len(term)


def call(term: str):
    term = re.sub(r'(\s+)', ' ', term.strip().lower())
    if len(term) <= MIN_QUERY_LENGTH:
        return term, []

    try:
        if CACHE is None:
            raise KeyError
        key = 'call_{!r}'.format(term)
        result = CACHE[key]

    except KeyError:
        api = search_api('*'.join(map('*'.join, term.split(' '))))
        api.Everything_QueryW(True)  # False == async

        buf_path = ctypes.create_unicode_buffer(260)
        buf_count = ctypes.c_ulonglong(1)

        result = defaultdict(list)
        for no in range(api.Everything_GetNumResults()):
            api.Everything_GetResultFullPathNameW(no, buf_path, 260)
            full = ctypes.wstring_at(buf_path)

            if full.lower().startswith(r'C:\Windows\WinSxS'.lower()):
                continue

            split = op.splitext(op.basename(full))
            if split[-1][1:].lower() not in EXTENSIONS:
                continue

            # base = op.basename(split[0]).lower()
            base = op.basename(full).lower()
            count = api.Everything_GetResultRunCount(no, buf_count)
            result[base].append((full, count))

        api.Everything_CleanUp()

        result = dict(result)
        if CACHE is not None:
            CACHE[key] = result

    return term, result


def _lookup(query: str):
    try:
        if CACHE is None:
            raise KeyError
        key = 'lookup_{!r}'.format(query)
        result = CACHE[key]

    except KeyError:
        term, order = call(query)
        if not order:
            return []

        unq_term = unique_letters(term)

        ratio = dict(
            process.extract(
                term,
                sorted(order),
                scorer=fuzz.token_sort_ratio,
                limit=len(order),
            )
        )

        rates = Counter()
        for base in sorted(order, key=lambda x: abs(len(term) - len(x))):
            if count_missing_letters(term, base) > MAX_MISSING_LETTERS:
                continue

            unq_base = unique_letters(base)
            rate = distance_relative(unq_term, unq_base) * distance(unq_term, unq_base)
            rate *= sqrt(distance(term, base[:len(term)]) + 1)
            rate *= sqrt(count_missing_letters_rel(term, base) + 1)
            rate /= (count_common_head(term, base) + 1)
            rate *= (ratio.get(base, 0)) / 100
            if rate <= MAX_RATE_FOR_RESULT:
                rates[base] = rate

        result = defaultdict(list)
        for no, (base, rate) in enumerate(reversed(rates.most_common())):
            for (full, count) in order[base]:
                result[count].append((full, op.dirname(full), base, count, rate))

        result = [result[i] for i in sorted(result, reverse=True)]
        result = tuple(tuple(reduce(add, result)) if result else [])
        if CACHE is not None:
            CACHE[key] = result

    result = result[:MAX_RESULTS_COUNT]
    return result


def lookup(query: str):
    if KEYBOARD.IS_RUS(query):
        query = KEYBOARD.CONVERT(query)
    return _lookup(query)


def increment(path) -> None:
    path = re.sub(r'(\\+)', r'\\', path)

    api = get_api()
    api.Everything_IncRunCountFromFileNameW(path)
    api.Everything_CleanUp()


if __name__ == '__main__':
    from sys import argv
    query = ' '.join(argv[1:]).lower()

    start = time()
    order = lookup(query)
    print(' ++ %0.5f sec %i files for %r' % (time() - start, len(order), query))

    for no, (full, path, base, runs, rate) in enumerate(order[:20]):
        print('%2i. %i %0.3f %s | %s' % (no, runs, rate, path, base))
