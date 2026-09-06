# -*- coding: utf-8 -*-
__title__   = "Ghost Model"
__doc__     = """
________________________________________________________________
Description:
- Run the script
- Entire Model will be Transparent except for Lines
- Press again to toggle Ghost Mode off
________________________________________________________________
Author: Mohamed Bedair"""

# Imports
import json, os
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit, script
from pyrevit import EXEC_PARAMS
from pyrevit.script import toggle_icon

# Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

# ── Version Detection ──────────────────────────────────────────────────────────
REVIT_VERSION = int(app.VersionNumber)   # e.g. 2024, 2025, 2026

# ── ElementId Compatibility ────────────────────────────────────────────────────
def get_element_id_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2026, replaced with .Value.
    This helper works transparently across all versions."""
    if hasattr(element_id, 'IntegerValue'):
        return element_id.IntegerValue   # Revit 2025 and older
    return element_id.Value              # Revit 2026+

# ── Check for View Template ────────────────────────────────────────────────────
if get_element_id_value(active_view.ViewTemplateId) != -1:
    TaskDialog.Show('Error', 'This View has a View Template. Please turn it off first.')
    script.exit()

PATH_SCRIPT = os.path.dirname(__file__)

# ── Toggle Config ──────────────────────────────────────────────────────────────
def read_toggle_config():
    """Read toggle_state.json from the script folder.
    Creates the file with a False value if not found."""
    json_toggle_state = os.path.join(PATH_SCRIPT, 'toggle_state.json')

    if os.path.exists(json_toggle_state):
        with open(json_toggle_state) as f:
            TOGGLE = json.load(f)['toggle_state']
    else:
        TOGGLE = False

    with open(json_toggle_state, "w") as f:
        json.dump({"toggle_state": not TOGGLE}, f)

    return TOGGLE

TOGGLE = read_toggle_config()

# Activate/Deactivate icon
icon_on  = os.path.join(PATH_SCRIPT, 'on.png')
icon_off = os.path.join(PATH_SCRIPT, 'off.png')
toggle_icon(TOGGLE, icon_on, icon_off)

# ── Override Helper ────────────────────────────────────────────────────────────
def build_ghost_override(transparency=95):
    """Build OverrideGraphicSettings with surface transparency.
    Handles API differences across Revit versions."""
    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceTransparency(transparency)

    if REVIT_VERSION >= 2026:
        try:
            solid_id = LinePatternElement.GetSolidPatternId()
            ogs.SetProjectionLinePatternId(solid_id)
        except Exception:
            pass  # Transparency alone is sufficient if this fails

    return ogs

def set_display_style(view, style):
    """Set DisplayStyle, guarding against view types that don't support it."""
    try:
        view.DisplayStyle = style
    except Exception as e:
        print("Could not set DisplayStyle: {}".format(e))

def set_category_hidden(view, cat_id, hidden):
    """Wrapper for SetCategoryHidden — Revit 2026 is stricter about
    which categories accept this call."""
    try:
        view.SetCategoryHidden(cat_id, hidden)
    except Exception:
        pass

# ── Main Logic ─────────────────────────────────────────────────────────────────
all_categories = doc.Settings.Categories
line_category  = Category.GetCategory(doc, BuiltInCategory.OST_Lines)

if not TOGGLE:
    # ── Ghost Mode ON ──────────────────────────────────────────────────────
    ghost_override = build_ghost_override(transparency=95)

    t = Transaction(doc, "Ghost Model - ON")
    t.Start()
    try:
        set_display_style(active_view, DisplayStyle.Shading)
        set_category_hidden(active_view, line_category.Id, True)

        for category in all_categories:
            try:
                active_view.SetCategoryOverrides(category.Id, ghost_override)
            except Exception:
                continue

        t.Commit()
    except Exception as e:
        t.RollBack()
        TaskDialog.Show("Ghost Model Error", "Failed to apply Ghost Mode:\n{}".format(e))

else:
    # ── Ghost Mode OFF (Reset) ─────────────────────────────────────────────
    reset_override = OverrideGraphicSettings()

    t = Transaction(doc, "Ghost Model - OFF")
    t.Start()
    try:
        set_display_style(active_view, DisplayStyle.ShadingWithEdges)
        set_category_hidden(active_view, line_category.Id, False)

        for category in all_categories:
            try:
                active_view.SetCategoryOverrides(category.Id, reset_override)
            except Exception:
                continue

        t.Commit()
    except Exception as e:
        t.RollBack()
        TaskDialog.Show("Ghost Model Error", "Failed to reset Ghost Mode:\n{}".format(e))