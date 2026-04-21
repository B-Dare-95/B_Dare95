# -*- coding: utf-8 -*-
"""
FLS Area Scheme Creator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Creates a new Area Scheme in the active Revit document:

  Name        : FLS
  Description : for FLS D

If an Area Scheme named "FLS" already exists, the script
reports it and exits without making any changes.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Author  : B_Dare95
Version : 1.0.0
"""

# ──────────────────────────────────────────────────────────────
# IMPORTS
# ──────────────────────────────────────────────────────────────
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    AreaScheme,
    Transaction,
)

from pyrevit import forms, script

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
SCHEME_NAME = "FLS"
SCHEME_DESC = "for FLS D"

# ──────────────────────────────────────────────────────────────
# REVIT HANDLES
# ──────────────────────────────────────────────────────────────
doc = __revit__.ActiveUIDocument.Document

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PREFLIGHT – check if scheme already exists
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

existing_schemes = {
    s.Name: s
    for s in FilteredElementCollector(doc)
                 .OfClass(AreaScheme)
                 .ToElements()
}

if SCHEME_NAME in existing_schemes:
    forms.alert(
        u"An Area Scheme named \u201c{}\u201d already exists in this project.\n\n"
        u"No changes were made.".format(SCHEME_NAME),
        title=u"FLS Area Scheme Creator \u2013 Already Exists"
    )
    script.exit()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CREATE AREA SCHEME
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

t = Transaction(doc, u"Create FLS Area Scheme")
t.Start()

try:
    # AreaScheme.Create(doc, name, isGrossInterior)
    # isGrossInterior=False → standard area scheme (not a gross-interior scheme)
    new_scheme = AreaScheme.Create(doc, SCHEME_NAME, False)

    # Set the description via LookupParameter – AreaScheme exposes it
    # as a text parameter under Identity Data in the Revit UI.
    desc_param = new_scheme.LookupParameter("Description")
    if desc_param is not None and not desc_param.IsReadOnly:
        desc_param.Set(SCHEME_DESC)

    t.Commit()

    forms.alert(
        u"Area Scheme created successfully!\n\n"
        u"  Name         :  {}\n"
        u"  Description  :  {}".format(SCHEME_NAME, SCHEME_DESC),
        title=u"FLS Area Scheme Creator \u2013 Done"
    )

except Exception as ex:
    t.RollBack()
    forms.alert(
        u"Failed to create the Area Scheme.\n\nDetails:\n{}".format(str(ex)),
        title=u"FLS Area Scheme Creator \u2013 Error"
    )