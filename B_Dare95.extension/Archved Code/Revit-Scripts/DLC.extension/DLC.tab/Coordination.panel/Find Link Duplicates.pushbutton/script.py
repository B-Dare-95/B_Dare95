# -*- coding: utf-8 -*-
"""DLC_FindLinkDuplicates - colour host walls/floors/ceilings that duplicate
the structural link red in the active view, then offer to delete them."""
__title__ = "Find Link\nDuplicates"
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

# Firm-level settings - edit here, not in the library.
SETTINGS = {
    # Ticked by default the FIRST time; after that the picker remembers you
    "HOST_CATEGORIES": ["OST_Walls", "OST_Floors", "OST_Ceilings"],
    # Categories offered in the picker (only ones with elements are shown)
    "CATEGORY_CHOICES": ["OST_Walls", "OST_Floors", "OST_Ceilings", "OST_Roofs",
                         "OST_StructuralFraming", "OST_StructuralColumns",
                         "OST_Columns", "OST_StructuralFoundation",
                         "OST_GenericModel", "OST_Stairs", "OST_Ramps"],
    # Structural link categories a host element can duplicate
    "LINK_CATEGORIES": ["OST_Floors", "OST_Walls", "OST_StructuralFraming",
                        "OST_StructuralColumns", "OST_StructuralFoundation",
                        "OST_Roofs", "OST_Stairs", "OST_Ramps"],
    "DUPLICATE_THRESHOLD": 0.80,   # 80% of host volume inside link geometry
    "PARTIAL_REPORT_MIN": 0.25,    # list (not colour) overlaps above 25%
    "HIGHLIGHT_RGB": (255, 0, 0),
    "BBOX_TOLERANCE_MM": 10.0,
}

flows.run_find(revit.doc, revit.uidoc, SETTINGS)
