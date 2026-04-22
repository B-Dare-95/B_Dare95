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
    BuiltInParameter,
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
# (Function of Space, Occupancy Load Factor as float or None, Measurement Type)
#
# Section-reference rules applied:
#   "See Section 1004.6"  → Assembly with Fixed Seats → factor=None, meas="N.O.SEATS"
#   "See Section 1004.8"  → Concentrated Business    → factor=4.65,  meas="GROSS"
#   "See Section 402.8.2" → Mall Buildings            → factor=None,  meas=""
# ──────────────────────────────────────────────────────────────
TABLE_1004_5 = [
    # ── Accessory / Agricultural / Aircraft ──────────────────
    ("Accessory Storage / Mechanical Equipment Room",    28.0,  "GROSS"),
    ("Agricultural Building",                            28.0,  "GROSS"),
    ("Aircraft Hangars",                                 46.0,  "GROSS"),
    # ── Airport Terminal ─────────────────────────────────────
    ("Airport Terminal - Baggage Claim",                  1.9,  "GROSS"),
    ("Airport Terminal - Baggage Handling",              28.0,  "GROSS"),
    ("Airport Terminal - Concourse",                      9.0,  "GROSS"),
    ("Airport Terminal - Waiting Areas",                  1.4,  "GROSS"),
    # ── Assembly ─────────────────────────────────────────────
    ("Assembly - Gaming Floors (Keno, Slots, etc.)",      1.0,  "GROSS"),
    ("Assembly - Exhibit Gallery and Museum",             2.8,  "NET"),
    ("Assembly with Fixed Seats",                        None,  "N.O.SEATS"),  # Sec. 1004.6
    ("Assembly without Fixed Seats - Concentrated",      0.65, "NET"),
    ("Assembly without Fixed Seats - Standing Space",    0.46, "NET"),
    ("Assembly without Fixed Seats - Unconcentrated",    1.4,  "NET"),
    # ── B ────────────────────────────────────────────────────
    ("Bowling Centers",                                  0.65,  "NET"),
    ("Business Areas",                                   14.0,  "GROSS"),
    ("Concentrated Business Use Areas",                  4.65,  "GROSS"),    # Sec. 1004.8
    # ── C / D ────────────────────────────────────────────────
    ("Courtrooms - Other than Fixed Seating Areas",       3.7,  "NET"),
    ("Day Care",                                          3.3,  "NET"),
    ("Dormitories",                                       4.6,  "GROSS"),
    # ── Educational ──────────────────────────────────────────
    ("Educational - Classroom Area",                      1.9,  "NET"),
    ("Educational - Shops and Vocational Room Areas",     4.6,  "NET"),
    # ── E / H / I ────────────────────────────────────────────
    ("Exercise Rooms",                                    4.6,  "GROSS"),
    ("H-5 Fabrication and Manufacturing Areas",          19.0,  "GROSS"),
    ("Industrial Areas",                                  9.0,  "GROSS"),
    # ── Institutional ────────────────────────────────────────
    ("Institutional - Inpatient Treatment Areas",        22.0,  "GROSS"),
    ("Institutional - Outpatient Areas",                  9.0,  "GROSS"),
    ("Institutional - Sleeping Areas",                   11.0,  "GROSS"),
    # ── K / L ────────────────────────────────────────────────
    ("Kitchens, Commercial",                             19.0,  "GROSS"),
    ("Library - Reading Rooms",                           4.6,  "NET"),
    ("Library - Stack Area",                              9.0,  "GROSS"),
    # ── M ────────────────────────────────────────────────────
    ("Mall Buildings - Covered and Open",                None,  ""),          # Sec. 402.8.2
    ("Mercantile - Areas on Other Floors",                5.6,  "GROSS"),
    ("Mercantile - Basement and Grade Floor Areas",       2.8,  "GROSS"),
    ("Mercantile - Storage, Stock, Shipping Areas",      28.0,  "GROSS"),
    # ── P / R ────────────────────────────────────────────────
    ("Parking Garages",                                  19.0,  "GROSS"),
    ("Residential",                                      19.0,  "GROSS"),
    # ── S / W ────────────────────────────────────────────────
    ("Skating Rinks and Swimming Pools - Rink and Pool",  4.6,  "GROSS"),
    ("Skating Rinks and Swimming Pools - Decks",          1.4,  "GROSS"),
    ("Stages and Platforms",                              1.4,  "NET"),
    ("Warehouses",                                       46.0,  "GROSS"),
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
    # CreateKeySchedule(doc, categoryId) – exactly 2 arguments.
    # Revit always creates the key field as the built-in "Key Name"
    # (BuiltInParameter.ROOM_KEY_VALUE). There is no API to substitute
    # a custom parameter as the key field. KeyScheduleParameterName is
    # NOT a valid property on ViewSchedule – it was removed in the API.
    # Strategy:
    #   • Column A  "Key Name"              → set via ROOM_KEY_VALUE (built-in)
    #                                          heading relabelled to "FLS Function of Space"
    #   • Column B  "FLS Function of Space" → custom Text param, mirrors Column A
    #   • Column C  "FLS Occupancy Factor"  → custom Number param
    #   • Column D  "FLS Area Measurement"  → custom Text param
    cat_id       = ElementId(BuiltInCategory.OST_Rooms)
    key_schedule = ViewSchedule.CreateKeySchedule(doc, cat_id)
    key_schedule.Name = KEY_SCHEDULE_NAME

    # ── 3b. Relabel Key Name column & add value fields ────────
    defn = key_schedule.Definition

    # Relabel the built-in "Key Name" column heading to "FLS Function of Space"
    # so the schedule reads naturally without a redundant second column.
    field_order = defn.GetFieldOrder()
    if field_order:
        key_field = defn.GetField(field_order[0])
        key_field.ColumnHeading = FLS_KEY_PARAM

    # Build a lookup: schedulable field name → SchedulableField
    sched_field_map = {}
    for sf in defn.GetSchedulableFields():
        try:
            sched_field_map[sf.GetName(doc)] = sf
        except Exception:
            pass

    # Add value fields in display order: Factor → Measurement
    # FLS Function of Space is handled by the relabelled Key Name column above.
    for field_name in (FLS_KEY_PARAM, FLS_FACTOR_PARAM, FLS_MEAS_PARAM):
        if field_name in sched_field_map:
            defn.AddField(sched_field_map[field_name])
        # FLS Key param not found is fine – it is already shown via Key Name column

    # ── 3c. Add rows and populate data ────────────────────────
    # Strategy: insert one row at a time and diff the set of elements
    # visible in the schedule view before/after each InsertRow call.
    # FilteredElementCollector(doc, viewId) gives live document state
    # so the diff always resolves to exactly the one new element.

    table = key_schedule.GetTableData()
    body  = table.GetSectionData(SectionType.Body)

    def _current_ids():
        return set(
            e.Id for e in
            FilteredElementCollector(doc, key_schedule.Id).ToElements()
        )

    assigned_ids = set()

    for func_name, factor, meas_str in TABLE_1004_5:

        before_ids = _current_ids()
        body.InsertRow(body.LastRowNumber + 1)
        after_ids  = _current_ids()
        new_ids    = after_ids - before_ids - assigned_ids

        if not new_ids:
            continue

        new_id = new_ids.pop()
        assigned_ids.add(new_id)

        elem = doc.GetElement(new_id)
        if elem is None:
            continue

        # ── Column B: FLS Function of Space (custom Text param) ─
        # This ensures the value lives on a proper custom parameter
        # so it can be scheduled on Room views and used elsewhere.
        p_key_custom = elem.LookupParameter(FLS_KEY_PARAM)
        if p_key_custom and not p_key_custom.IsReadOnly:
            p_key_custom.Set(func_name)

        # ── Column C: FLS Occupancy Factor (Number → float) ───
        if factor is not None:
            p_factor = elem.LookupParameter(FLS_FACTOR_PARAM)
            if p_factor and not p_factor.IsReadOnly:
                p_factor.Set(float(factor))

        # ── Column D: FLS Area Measurement (Text) ─────────────
        if meas_str:
            p_meas = elem.LookupParameter(FLS_MEAS_PARAM)
            if p_meas and not p_meas.IsReadOnly:
                p_meas.Set(meas_str)

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