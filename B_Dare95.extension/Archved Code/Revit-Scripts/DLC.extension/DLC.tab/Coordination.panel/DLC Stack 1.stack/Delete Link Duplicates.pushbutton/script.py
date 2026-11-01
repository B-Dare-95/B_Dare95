# -*- coding: utf-8 -*-
"""DLC_DeleteLinkDuplicates - delete all / selected / ticked duplicates found
by Find Link Duplicates."""
__title__ = "Delete\nDuplicates"
__author__ = "DLC"

import os
import sys

# Make the shared library importable even if pyRevit hasn't registered
# DLC.extension\lib (e.g. lib copied in after the last reload).
def _find_lib():
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        cand = os.path.join(here, "lib")
        if os.path.isdir(os.path.join(cand, "dlc_linkdup")):
            return cand
        here = os.path.dirname(here)
    return None

_LIB = _find_lib()
if _LIB is None:
    from pyrevit import forms
    forms.alert("Can't find the 'dlc_linkdup' library.\n\nCopy the folder\n"
                "  lib\\dlc_linkdup\\\n"
                "into your DLC.extension folder (next to DLC.tab), then pyRevit > Reload.",
                title="DLC Link Duplicates", exitscript=True)
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from pyrevit import revit
from dlc_linkdup import flows

flows.run_delete(revit.doc, revit.uidoc)
