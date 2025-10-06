import os
import re
from datetime import datetime
from enum import Enum, IntFlag
from pathlib import Path
from typing import final

from typing_extensions import LiteralString

# local tunables

WOX_SDK_PATH = 'D:/apps/utils/ergo/wox/JsonRPC'

MIN_QUERY_LENGTH    = 1
MAX_MISSING_LETTERS = 1
MAX_RATE_FOR_RESULT = 15
MAX_RESULTS_COUNT   = 15
ENABLED_EXTENSIONS          = ('exe', 'bat', 'cmd', 'lnk', 'chm', 'cpl')

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

WINDOWS_SXS_REPOSITORY = str(Path(os.environ["WINDIR"]) / 'WinSxS').lower()
WINDOWS_CONTAINERS_LAYERS = str(
    Path(os.environ["ALLUSERSPROFILE"])
    / 'Microsoft'
    / 'Windows'
    / 'Containers'
    / 'Layers'
).lower()

#

class SearchRequest(IntFlag):

    FILE_NAME                           = 0x00000001
    PATH                                = 0x00000002
    FULL_PATH_AND_FILE_NAME             = 0x00000004
    EXTENSION                           = 0x00000008
    SIZE                                = 0x00000010
    DATE_CREATED                        = 0x00000020
    DATE_MODIFIED                       = 0x00000040
    DATE_ACCESSED                       = 0x00000080
    ATTRIBUTES                          = 0x00000100
    FILE_LIST_FILE_NAME                 = 0x00000200
    RUN_COUNT                           = 0x00000400
    DATE_RUN                            = 0x00000800
    DATE_RECENTLY_CHANGED               = 0x00001000
    HIGHLIGHTED_FILE_NAME               = 0x00002000
    HIGHLIGHTED_PATH                    = 0x00004000
    HIGHLIGHTED_FULL_PATH_AND_FILE_NAME = 0x00008000


class SortingCriteria(Enum):

    NAME_ASCENDING                   = 1
    NAME_DESCENDING                  = 2
    PATH_ASCENDING                   = 3
    PATH_DESCENDING                  = 4

    EXTENSION_ASCENDING              = 7
    EXTENSION_DESCENDING             = 8

    FILE_LIST_FILENAME_ASCENDING     = 17
    FILE_LIST_FILENAME_DESCENDING    = 18

    #

    DATE_ACCESSED_ASCENDING          = 23
    DATE_ACCESSED_DESCENDING         = 24

    DATE_CREATED_ASCENDING           = 11
    DATE_CREATED_DESCENDING          = 12

    DATE_MODIFIED_ASCENDING          = 13
    DATE_MODIFIED_DESCENDING         = 14

    DATE_RECENTLY_CHANGED_ASCENDING  = 21
    DATE_RECENTLY_CHANGED_DESCENDING = 22

    DATE_RUN_ASCENDING               = 25
    DATE_RUN_DESCENDING              = 26

    #

    RUN_COUNT_ASCENDING              = 19
    RUN_COUNT_DESCENDING             = 20
    SIZE_ASCENDING                   = 5
    SIZE_DESCENDING                  = 6
    TYPE_NAME_ASCENDING              = 9
    TYPE_NAME_DESCENDING             = 10

    #

    ATTRIBUTES_ASCENDING             = 15
    ATTRIBUTES_DESCENDING            = 16


class SDKError(Enum):
    OK                    = 0  # The operation completed successfully.

    ERROR_MEMORY          = 1  # Failed to allocate memory for the search query.
    ERROR_IPC             = 2  # IPC is not available.
    ERROR_REGISTERCLASSEX = 3  # Failed to register the search query window class.
    ERROR_CREATEWINDOW    = 4  # Failed to create the search query window.
    ERROR_CREATETHREAD    = 5  # Failed to create the search query thread.
    ERROR_INVALIDINDEX    = 6  # Invalid index. The index must be greater or equal to 0 and less than the number of visible results.
    ERROR_INVALIDCALL     = 7  # Invalid call.


@final
class Keyboard:

    RU: LiteralString = 'ЙЦУКЕНГШЩЗФЫВАПРОЛДЯЧСМИТЬ'.lower()
    EN: LiteralString = 'QWERTYUIOPASDFGHJKLZXCVBNM'.lower()

    WORD: re.Pattern[str] = re.compile('(?ui)^([{}]+)$'.format(RU))
    CHAR: re.Pattern[str] = re.compile('(?ui)([{}])'.format(RU))

    MAP: dict[str, str] = dict(zip(RU, EN))

    IsCyrillic = staticmethod(WORD.match)

    @classmethod
    def Translate(cls, query: str) -> str:
        return cls.CHAR.sub(lambda x: cls.MAP[x.group(1)], query)
