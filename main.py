import ctypes
import os
import os.path as op
from contextlib import suppress
from pathlib import Path
from subprocess import (
    CREATE_BREAKAWAY_FROM_JOB,
    CREATE_NEW_PROCESS_GROUP,
    DETACHED_PROCESS,
    DEVNULL,
    STARTF_USESHOWWINDOW,
    STARTUPINFO,
    SW_HIDE,
    Popen,
)
from typing import Any

from exespy import pe_file
from lxml import etree
from win32api import GetFileVersionInfo
from win32com import client
from win32process import CREATE_NO_WINDOW

import search
from const import WOX_SDK_PATH

try:
    from wox import Wox

except ImportError:
    import sys

    sys.path = [WOX_SDK_PATH] + sys.path
    from wox import Wox


def needs_admin(path: str) -> bool:

    with suppress(Exception):
        info = GetFileVersionInfo(path, "\\")
        ms = info["FileVersionMS"]
        ls = info["FileVersionLS"]
        return (ms & 0x1) == 1

    return False


def needs_admin_another_one(path: str) -> bool:
    try:
        manifest = ctypes.c_wchar_p()
        ctypes.windll.shell32.GetAppManifest(
            ctypes.c_wchar_p(path), ctypes.byref(manifest)
        )

    except (AttributeError, TypeError):
        return False

    return bool(manifest.value and "requireAdministrator" in manifest.value)


def needs_admon_another_one_yet(path: str) -> bool:

    pe = pe_file.PEFile(path)  # TODO: pe.sha256

    def get_manifest(pe: pe_file.PEFile):
        for resource in pe.resources:
            if resource.rtype == "RT_MANIFEST":
                return resource

        raise ValueError("No manifest found")

    try:
        manifest_rsrc = get_manifest(pe)

    except ValueError:
        return False

    # asInvoker
    # highestAvailable
    # requireAdministrator

    for top in etree.fromstring(manifest_rsrc.data).iterchildren():
        if str(top.tag).endswith("trustInfo"):
            ns = top.tag[:-len("trustInfo")]
            for internal in top.iterdescendants():
                if internal.tag == f"{ns}requestedExecutionLevel":
                    return internal.get("level")

    return False


def run_something(path: str) -> None:
    extension = Path(path).suffix[1:].lower()

    if extension in ("lnk", "pif"):
        link = client.Dispatch("WScript.Shell").CreateShortCut(path)

        path = link.TargetPath
        work_dir = link.WorkingDirectory
        arguments = link.Arguments.split()

    else:
        work_dir = op.dirname(path)
        arguments = []

    os.chdir(work_dir)

    startupinfo = STARTUPINFO()
    startupinfo.dwFlags |= STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = SW_HIDE

    Popen(
        [path] + arguments,
        startupinfo=startupinfo,
        creationflags=(
            DETACHED_PROCESS
            | CREATE_NO_WINDOW
            | CREATE_NEW_PROCESS_GROUP
            | CREATE_BREAKAWAY_FROM_JOB
            | DETACHED_PROCESS
        ),
        stdin=DEVNULL,
        stdout=DEVNULL,
        stderr=DEVNULL,
    )
    search.increment(path)


class Everything(Wox):

    def query(self, query)-> list[dict[str, Any]]:
        results = []
        for full, path, name, count, rate in search.lookup(query):
            title = op.basename(full).lower()
            if op.splitext(title)[1].lower() == ".exe":
                title = op.splitext(title)[0]

            results.append(
                {
                    "Title": title,
                    "SubTitle": path,
                    "IcoPath": full,
                    "ContextData": "ctxData",
                    "JsonRPCAction": {
                        "method": "run_something",
                        "parameters": [full],
                        "dontHideAfterAction": False,
                    },
                }
            )
        return results

    def run_something(self, path) -> None:
        return run_something(path)

    def context_menu(self, _) -> list[Any]:
        results = []
        # results.append({
        #     "Title": "Context menu entry",
        #     "SubTitle": "Data: {}".format(data),
        #     "IcoPath":"Images/app.png"
        # })
        return results


if __name__ == "__main__":
    # must be here for Wox using
    Everything()

    # for debugging comment Everything() create and uncomment this

    # query = 'tcmd'
    # path, workdir, executive, runs, rate = search.lookup(query)[0]
    # run_something(path)
