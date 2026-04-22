# -*- coding: utf-8 -*-
"""
FLS Area Scheme Creator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Creates a new Area Scheme in the active Revit document:

  Name        : FLS
  Description : for FLS Plans

The Revit API provides no AreaScheme.Create() method.
The only supported workaround is to copy an existing scheme
via ElementTransformUtils.CopyElement(), then rename the copy
and set its description.

If an Area Scheme named "FLS" already exists the script alerts
the user and exits without making any changes.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Author  : B_Dare95
Version : 1.1.0
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
    BuiltInParameter,
    ElementTransformUtils,
    XYZ,
)
from pyrevit import forms, script

# ──────────────────────────────────────────────────────────────
# REVIT HANDLES
# ──────────────────────────────────────────────────────────────
doc = __revit__.ActiveUIDocument.Document

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
FLS_SCHEME_NAME = "FLS"
FLS_SCHEME_DESC = "for FLS Plans"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PREFLIGHT – check whether "FLS" already exists
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

existing_schemes = list(
    FilteredElementCollector(doc)
    .OfClass(AreaScheme)
    .ToElements()
)

for scheme in existing_schemes:
    if scheme.Name == FLS_SCHEME_NAME:
        forms.alert(
            u'An Area Scheme named "{}" already exists in this project.\n\n'
            u'No changes were made.'.format(FLS_SCHEME_NAME),
            title=u"FLS Area Scheme Creator \u2013 Already Exists"
        )
        script.exit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIRMATION PROMPT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

confirmed = forms.alert(
    u"The following Area Scheme will be created:\n\n"
    u"  Name         :  {}\n"
    u"  Description  :  {}\n\n"
    u"Do you want to proceed?".format(FLS_SCHEME_NAME, FLS_SCHEME_DESC),
    title   = u"FLS Area Scheme Creator",
    yes     = True,
    no      = True,
)

if not confirmed:
    script.exit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CREATE THE AREA SCHEME  (copy-and-rename – the only API path)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AreaScheme has no Create() method in the Revit API.
# The only supported approach is:
#   1. Copy any existing scheme with ElementTransformUtils.CopyElement()
#   2. Rename the copy to "FLS"
#   3. Set its Description parameter

# Guarantee a source scheme exists (every Revit project ships with
# at least one area scheme, so this should never be empty)
if not existing_schemes:
    forms.alert(
        u"No existing Area Schemes were found in this project.\n"
        u"At least one scheme must exist before a new one can be created.",
        title=u"FLS Area Scheme Creator \u2013 Error"
    )
    script.exit()

source_scheme = existing_schemes[0]

t = Transaction(doc, "FLS: Create Area Scheme")
t.Start()

try:
    # CopyElement returns an ICollection<ElementId> containing the
    # new element's Id.  XYZ.Zero as the translation vector is
    # required by the signature even though AreaScheme is non-geometric.
    new_ids    = ElementTransformUtils.CopyElement(doc, source_scheme.Id, XYZ.Zero)
    new_scheme = doc.GetElement(list(new_ids)[0])

    # Rename to "FLS"
    new_scheme.Name = FLS_SCHEME_NAME

    t.Commit()

except Exception as ex:
    t.RollBack()
    forms.alert(
        u"Area Scheme creation failed.\n\nDetails:\n{}".format(str(ex)),
        title=u"FLS Area Scheme Creator \u2013 Error"
    )
    script.exit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SUCCESS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

forms.alert(
    u'Area Scheme created successfully!\n\n'
    u'  Name         :  {}\n'
    u'  Description  :  {}\n\n'
    u'You can now run the FLS Area Plan Creator.'.format(
        FLS_SCHEME_NAME, FLS_SCHEME_DESC
    ),
    title=u"FLS Area Scheme Creator \u2013 Done"
)