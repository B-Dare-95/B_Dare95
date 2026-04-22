# -*- coding: utf-8 -*-
"""
FLS Room Key Schedule Creator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Creates a Room Key Schedule named "FLS Room Types" with:

  Key Parameter  : FLS Function of Space
  Value Fields   : FLS Occupancy Factor  (m²/person as text)
                   FLS Area Measurement  (NET / GROSS)

Rows are pre-populated from SBC 201 Table 1004.5 —
"Maximum Floor Area Allowances Per Occupant".

Entries whose load factor is a code section reference
(e.g. "See Sec. 1004.6") are included with the reference
stored as-is in "FLS Occupancy Factor" and an empty
"FLS Area Measurement".

Prerequisites:
  Run FLS Parameter Creator first so all four FLS parameters
  exist in the project before running this script.
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
    ViewSchedule,
    ElementId,
    BuiltInCategory,
    Transaction,
    SectionType,
)
from pyrevit import forms, script

# ──────────────────────────────────────────────────────────────
# REVIT HANDLES
# ──────────────────────────────────────────────────────────────
doc = __revit__.ActiveUIDocument.Document

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
KEY_SCHEDULE_NAME   = "FLS Room Types"
FLS_KEY_PARAM       = "FLS Function of Space"
FLS_FACTOR_PARAM    = "FLS Occupancy Factor"
FLS_MEAS_PARAM      = "FLS Area Measurement"

ALL_FLS_PARAMS = [FLS_KEY_PARAM, FLS_FACTOR_PARAM, FLS_MEAS_PARAM,
                  "FLS Occupancy"]   # 4th param checked for completeness

# ──────────────────────────────────────────────────────────────
# TABLE 1004.5  –  SBC 201, Chapter 10
# (Function of Space, Occupancy Load Factor m², Measurement Type)
# ──────────────────────────────────────────────────────────────
TABLE_1004_5 = [
    # ── Accessory / Agricultural / Aircraft ──────────────────
    ("Accessory Storage / Mechanical Equipment Room",    "28",               "GROSS"),
    ("Agricultural Building",                            "28",               "GROSS"),
    ("Aircraft Hangars",                                 "46",               "GROSS"),
    # ── Airport Terminal ─────────────────────────────────────
    ("Airport Terminal - Baggage Claim",                 "1.9",              "GROSS"),
    ("Airport Terminal - Baggage Handling",              "28",               "GROSS"),
    ("Airport Terminal - Concourse",                     "9",                "GROSS"),
    ("Airport Terminal - Waiting Areas",                 "1.4",              "GROSS"),
    # ── Assembly ─────────────────────────────────────────────
    ("Assembly - Gaming Floors (Keno, Slots, etc.)",     "1",                "GROSS"),
    ("Assembly - Exhibit Gallery and Museum",            "2.8",              "NET"),
    ("Assembly with Fixed Seats",                        "See Sec. 1004.6",  ""),
    ("Assembly without Fixed Seats - Concentrated",      "0.65",             "NET"),
    ("Assembly without Fixed Seats - Standing Space",    "0.46",             "NET"),
    ("Assembly without Fixed Seats - Unconcentrated",    "1.4",              "NET"),
    # ── B ────────────────────────────────────────────────────
    ("Bowling Centers",                                  "0.65",             "NET"),
    ("Business Areas",                                   "14",               "GROSS"),
    ("Concentrated Business Use Areas",                  "See Sec. 1004.8",  ""),
    # ── C / D ────────────────────────────────────────────────
    ("Courtrooms - Other than Fixed Seating Areas",      "3.7",              "NET"),
    ("Day Care",                                         "3.3",              "NET"),
    ("Dormitories",                                      "4.6",              "GROSS"),
    # ── Educational ──────────────────────────────────────────
    ("Educational - Classroom Area",                     "1.9",              "NET"),
    ("Educational - Shops and Vocational Room Areas",    "4.6",              "NET"),
    # ── E / H / I ────────────────────────────────────────────
    ("Exercise Rooms",                                   "4.6",              "GROSS"),
    ("H-5 Fabrication and Manufacturing Areas",          "19",               "GROSS"),
    ("Industrial Areas",                                 "9",                "GROSS"),
    # ── Institutional ────────────────────────────────────────
    ("Institutional - Inpatient Treatment Areas",        "22",               "GROSS"),
    ("Institutional - Outpatient Areas",                 "9",                "GROSS"),
    ("Institutional - Sleeping Areas",                   "11",               "GROSS"),
    # ── K / L ────────────────────────────────────────────────
    ("Kitchens, Commercial",                             "19",               "GROSS"),
    ("Library - Reading Rooms",                          "4.6",              "NET"),
    ("Library - Stack Area",                             "9",                "GROSS"),
    # ── M ────────────────────────────────────────────────────
    ("Mall Buildings - Covered and Open",                "See Sec. 402.8.2", ""),
    ("Mercantile - Areas on Other Floors",               "5.6",              "GROSS"),
    ("Mercantile - Basement and Grade Floor Areas",      "2.8",              "GROSS"),
    ("Mercantile - Storage, Stock, Shipping Areas",      "28",               "GROSS"),
    # ── P / R ────────────────────────────────────────────────
    ("Parking Garages",                                  "19",               "GROSS"),
    ("Residential",                                      "19",               "GROSS"),
    # ── S / W ────────────────────────────────────────────────
    ("Skating Rinks and Swimming Pools - Rink and Pool", "4.6",              "GROSS"),
    ("Skating Rinks and Swimming Pools - Decks",         "1.4",              "GROSS"),
    ("Stages and Platforms",                             "1.4",              "NET"),
    ("Warehouses",                                       "46",               "GROSS"),
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 1 – PREFLIGHT CHECKS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 1a. FLS parameters must exist ─────────────────────────────
bound_param_names = set()
it = doc.ParameterBindings.ForwardIterator()
while it.MoveNext():
    try:
        bound_param_names.add(it.Key.Name)
    except Exception:
        pass

missing_params = [p for p in ALL_FLS_PARAMS if p not in bound_param_names]
if missing_params:
    forms.alert(
        u"The following required FLS parameters are missing:\n\n"
        + u"\n".join(u"  \u2022  {}".format(p) for p in missing_params)
        + u"\n\nPlease run the FLS Parameter Creator first.",
        title      = u"FLS Room Key Schedule Creator \u2013 Missing Parameters",
        exitscript = True
    )

# ── 1b. Key schedule must not already exist ───────────────────
for v in (FilteredElementCollector(doc)
          .OfClass(ViewSchedule)
          .ToElements()):
    if v.Name == KEY_SCHEDULE_NAME:
        forms.alert(
            u'A schedule named "{}" already exists in this project.\n\n'
            u'No changes were made.'.format(KEY_SCHEDULE_NAME),
            title      = u"FLS Room Key Schedule Creator \u2013 Already Exists",
            exitscript = True
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 2 – CONFIRMATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

confirmed = forms.alert(
    u'A Room Key Schedule named "{}" will be created.\n\n'
    u'  Key Parameter  :  {}\n'
    u'  Value Fields   :  {}  |  {}\n'
    u'  Entries        :  {} rows (SBC 201 Table 1004.5)\n\n'
    u'Do you want to proceed?'.format(
        KEY_SCHEDULE_NAME,
        FLS_KEY_PARAM,
        FLS_FACTOR_PARAM,
        FLS_MEAS_PARAM,
        len(TABLE_1004_5)
    ),
    title = u"FLS Room Key Schedule Creator",
    yes   = True,
    no    = True,
)
if not confirmed:
    script.exit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 3 – CREATE KEY SCHEDULE & POPULATE ROWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

t = Transaction(doc, "FLS: Create Room Key Schedule")
t.Start()

try:
    # ── 3a. Create the key schedule ───────────────────────────
    cat_id       = ElementId(BuiltInCategory.OST_Rooms)
    key_schedule = ViewSchedule.CreateKeySchedule(doc, cat_id)
    key_schedule.Name = KEY_SCHEDULE_NAME

    # ── 3b. Add value fields ──────────────────────────────────
    defn = key_schedule.Definition

    # Build a lookup of schedulable field names → SchedulableField objects
    sched_field_map = {}
    for sf in defn.GetSchedulableFields():
        try:
            sched_field_map[sf.GetName(doc)] = sf
        except Exception:
            pass

    for field_name in (FLS_FACTOR_PARAM, FLS_MEAS_PARAM):
        if field_name in sched_field_map:
            defn.AddField(sched_field_map[field_name])
        else:
            forms.alert(
                u'Could not find schedulable field "{}".\n'
                u'The key schedule will be created without it.'.format(field_name)
            )

    # ── 3c. Add rows and populate data ────────────────────────
    # Strategy: insert one row at a time, immediately identify the new
    # element via set-difference, and set its parameter values.
    # This avoids any ambiguity about element ordering.

    table  = key_schedule.GetTableData()
    body   = table.GetSectionData(SectionType.Body)

    assigned_ids = set()

    for func_name, factor_str, meas_str in TABLE_1004_5:

        # Insert one row
        body.InsertRow(body.LastRowNumber + 1)

        # The new element is whichever ID appeared since the last iteration
        current_ids = set(key_schedule.GetScheduleInstances())
        new_ids     = current_ids - assigned_ids

        if not new_ids:
            # Fallback: skip this entry if we can't identify the new element
            continue

        new_id = new_ids.pop()
        assigned_ids.add(new_id)

        elem = doc.GetElement(new_id)
        if elem is None:
            continue

        # Set key + value parameters
        for pname, pval in (
            (FLS_KEY_PARAM,    func_name),
            (FLS_FACTOR_PARAM, factor_str),
            (FLS_MEAS_PARAM,   meas_str),
        ):
            p = elem.LookupParameter(pname)
            if p is not None and not p.IsReadOnly:
                p.Set(pval)

    t.Commit()

except Exception as ex:
    t.RollBack()
    forms.alert(
        u"Key schedule creation failed.\n\nDetails:\n{}".format(str(ex)),
        title=u"FLS Room Key Schedule Creator \u2013 Error"
    )
    script.exit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 4 – SUCCESS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

forms.alert(
    u'Room Key Schedule created successfully!\n\n'
    u'  Schedule Name  :  {}\n'
    u'  Key Parameter  :  {}\n'
    u'  Rows Created   :  {}\n\n'
    u'Assign a "FLS Function of Space" value on any Room to\n'
    u'automatically populate its Occupancy Factor and Area Measurement.'.format(
        KEY_SCHEDULE_NAME,
        FLS_KEY_PARAM,
        len(TABLE_1004_5)
    ),
    title=u"FLS Room Key Schedule Creator \u2013 Done"
)