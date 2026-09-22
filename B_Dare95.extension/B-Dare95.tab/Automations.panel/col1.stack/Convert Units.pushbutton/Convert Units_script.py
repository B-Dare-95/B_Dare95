# -*- coding: utf-8 -*-
"""Convert Units - toggles the active document between Metric and Imperial.

Full-system conversion. A fresh Units object is built from the Revit
UnitSystem default, which covers every spec in every discipline (Common,
Structural, HVAC, Electrical, Piping, Energy, Infrastructure) in one shot.
A small override table is then layered on top for the specs where the office
standard differs from Revit's stock default.

The current state is read from the document itself, not from a stored toggle
file, so the button icon can never disagree with the model, and two open
models each report their own true state.

Revit 2024+ / IronPython 2.7. No version guards - this will not run on older
releases and is not intended to.
"""

import os

from Autodesk.Revit.DB import (RoundingMethod, SpecTypeId, Transaction,
                               UnitSystem, UnitTypeId, UnitUtils, Units)
from pyrevit import forms, script
from pyrevit.script import toggle_icon


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Office overrides applied on top of the UnitSystem defaults.
# Every spec NOT listed here is still converted - it simply takes the stock
# Revit default for the target system. Only list a spec here when you want
# something other than that default.
#
#   spec name: {"metric": (unit name, accuracy), "imperial": (unit name, accuracy)}
#
# accuracy = None keeps whatever accuracy the UnitSystem default supplied.
# That is the correct choice for imperial fractional units, where accuracy is
# expressed as a fraction of a foot and is easy to get wrong by hand.
#
# Names are plain strings and are resolved with getattr() at runtime, so a
# member that does not exist in a given Revit release is reported and skipped
# instead of raising AttributeError and killing the whole script.

OVERRIDES = {
    "Length":        {"metric": ("Millimeters", 1.0),
                      "imperial": ("FeetFractionalInches", None)},

    "Distance":      {"metric": ("Meters", 0.001),
                      "imperial": ("FeetFractionalInches", None)},

    "Area":          {"metric": ("SquareMeters", 0.01),
                      "imperial": ("SquareFeet", None)},

    "Volume":        {"metric": ("CubicMeters", 0.01),
                      "imperial": ("CubicFeet", None)},

    "Angle":         {"metric": ("Degrees", 0.01),
                      "imperial": ("Degrees", 0.01)},

    "RotationAngle": {"metric": ("Degrees", 0.01),
                      "imperial": ("Degrees", 0.01)},

    "Slope":         {"metric": ("SlopeDegrees", 0.01),
                      "imperial": ("RiseDividedBy12Inches", None)},

    "Speed":         {"metric": ("MetersPerSecond", 0.1),
                      "imperial": ("FeetPerSecond", None)},

    "Time":          {"metric": ("Seconds", 1.0),
                      "imperial": ("Seconds", 1.0)},

    "MassDensity":   {"metric": ("KilogramsPerCubicMeter", 0.01),
                      "imperial": ("PoundsMassPerCubicFoot", None)},

    "CostPerArea":   {"metric": ("CurrencyPerSquareMeter", 0.01),
                      "imperial": ("CurrencyPerSquareFoot", None)},

    "Currency":      {"metric": ("Currency", 0.01),
                      "imperial": ("Currency", 0.01)},
}

# Length units that identify a document as Imperial. Anything else is Metric.
IMPERIAL_LENGTH_UNITS = ("Feet",
                         "FeetFractionalInches",
                         "Inches",
                         "FractionalInches",
                         "UsSurveyFeet")

# Which system the "on" icon represents. Flip to False if you want on.png to
# mean Imperial instead.
ICON_ON_MEANS_METRIC = True


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def resolve(container, name):
    """Return a ForgeTypeId member by name, or None if this build lacks it."""
    return getattr(container, name, None)


def get_current_system(document):
    """Read the document's own Length unit and derive the active system.

    ForgeTypeId instances are compared by their .TypeId string rather than by
    the == operator, which is the reliable route under IronPython.
    """
    fmt = document.GetUnits().GetFormatOptions(SpecTypeId.Length)
    current_id = fmt.GetUnitTypeId().TypeId

    for unit_name in IMPERIAL_LENGTH_UNITS:
        unit = resolve(UnitTypeId, unit_name)
        if unit is not None and unit.TypeId == current_id:
            return UnitSystem.Imperial

    return UnitSystem.Metric


def build_units(target_system, skipped):
    """Build a complete Units object for target_system, then apply overrides.

    Anything that cannot be applied is appended to 'skipped' and reported
    afterwards rather than being swallowed.
    """
    units = Units(target_system)
    key = "metric" if target_system == UnitSystem.Metric else "imperial"

    for spec_name in sorted(OVERRIDES.keys()):
        unit_name, accuracy = OVERRIDES[spec_name][key]

        spec = resolve(SpecTypeId, spec_name)
        if spec is None:
            skipped.append("{0}: SpecTypeId.{0} does not exist in this Revit "
                           "version".format(spec_name))
            continue

        if not UnitUtils.IsMeasurableSpec(spec):
            skipped.append("{0}: not a measurable spec in this Revit "
                           "version".format(spec_name))
            continue

        unit = resolve(UnitTypeId, unit_name)
        if unit is None:
            skipped.append("{0}: UnitTypeId.{1} does not exist in this Revit "
                           "version".format(spec_name, unit_name))
            continue

        if not UnitUtils.IsValidUnit(spec, unit):
            skipped.append("{0}: {1} is not a valid unit for this spec"
                           .format(spec_name, unit_name))
            continue

        try:
            fmt = units.GetFormatOptions(spec)
            fmt.UseDefault = False
            fmt.SetUnitTypeId(unit)
            if accuracy is not None:
                fmt.Accuracy = accuracy
            fmt.RoundingMethod = RoundingMethod.Nearest
            units.SetFormatOptions(spec, fmt)
        except Exception as e:
            skipped.append("{0}: override rejected by Revit - {1}"
                           .format(spec_name, e))

    return units


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

uidoc = __revit__.ActiveUIDocument

if uidoc is None:
    forms.alert("No active document. Open a model before running this tool.",
                title="Convert Units",
                exitscript=True)

doc = uidoc.Document

if doc.IsReadOnly:
    forms.alert("This document is read-only. Project Units cannot be changed.",
                title="Convert Units",
                exitscript=True)

current_system = get_current_system(doc)

if current_system == UnitSystem.Metric:
    target_system = UnitSystem.Imperial
    target_label = "Imperial"
else:
    target_system = UnitSystem.Metric
    target_label = "Metric"

# Built outside the transaction - nothing here touches the document.
skipped = []
new_units = build_units(target_system, skipped)

t = Transaction(doc, "Convert Project Units to {0}".format(target_label))
t.Start()

try:
    doc.SetUnits(new_units)
    t.Commit()
except Exception as e:
    t.RollBack()
    forms.alert("Unit conversion failed and was rolled back.\n\n{0}".format(e),
                title="Convert Units",
                exitscript=True)

# Icon is set from the committed result, never from a stored flag.
PATH_SCRIPT = os.path.dirname(__file__)
icon_on = os.path.join(PATH_SCRIPT, "on.png")
icon_off = os.path.join(PATH_SCRIPT, "off.png")

if os.path.exists(icon_on) and os.path.exists(icon_off):
    is_metric_now = (target_system == UnitSystem.Metric)
    icon_state = is_metric_now if ICON_ON_MEANS_METRIC else not is_metric_now
    toggle_icon(icon_state, icon_on, icon_off)

# Silent on a clean run - the icon is the feedback. The output window opens
# only when something in the override table could not be applied.
if skipped:
    output = script.get_output()
    output.print_md("### Convert Units - now {0}".format(target_label))
    output.print_md("Conversion committed. These overrides were skipped, so "
                    "those specs kept the Revit {0} default:"
                    .format(target_label))
    for item in skipped:
        output.print_md("- {0}".format(item))