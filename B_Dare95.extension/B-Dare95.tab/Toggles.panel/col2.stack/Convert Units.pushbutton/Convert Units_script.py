# -*- coding: utf-8 -*-

#Imports
import json, os, codecs
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS
from pyrevit.script import toggle_icon

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

PATH_SCRIPT = os.path.dirname(__file__)

def read_toggle_config():
    """Function to read toggle_state.json config located in the script's folder.
    If file is not found it will be created with False value."""
    json_toggle_state = os.path.join(PATH_SCRIPT, 'toggle_state.json')

    # READ/CREATE file
    if os.path.exists(json_toggle_state):
        with open(json_toggle_state) as f:
            json_data = json.load(f)
            TOGGLE = json_data['toggle_state']
    else:
        TOGGLE = False
    # REVERSE VALUE
    with open(json_toggle_state, "w") as f:
        x = not TOGGLE
        new_data = {"toggle_state": x}
        json.dump(new_data, f)
    return TOGGLE

TOGGLE = read_toggle_config()

# ACTIVATE/DEACTIVATE ICON
icon_on = os.path.join(PATH_SCRIPT, 'on.png')
icon_off = os.path.join(PATH_SCRIPT, 'off.png')
toggle_icon(TOGGLE, icon_on, icon_off)  # Change icon

if app.VersionNumber < 2022:

    t = Transaction(doc, "Change Project Units to Metric")
    t.Start()

    # Get the current document units
    units = doc.GetUnits()

    # Set the new unit system to Metric
    units.SetFormatOptions(UnitType.UT_Length, FormatOptions(DisplayUnitType.DUT_MILLIMETERS, 1))
    units.SetFormatOptions(UnitType.UT_Area, FormatOptions(DisplayUnitType.DUT_SQUARE_METERS, 0.01))
    units.SetFormatOptions(UnitType.UT_Volume, FormatOptions(DisplayUnitType.DUT_CUBIC_METERS, 0.01))
    units.SetFormatOptions(UnitType.UT_Slope, FormatOptions(DisplayUnitType.DUT_PERCENTAGE, 0.1))
    units.SetFormatOptions(UnitType.UT_Angle, FormatOptions(DisplayUnitType.DUT_DECIMAL_DEGREES, 0.1))

    # Apply the modified units to the document
    doc.SetUnits(units)

    # Commit the transaction
    t.Commit()

    if not TOGGLE:
        t = Transaction(doc, "Change to Imperial")
        t.Start()

        # Get the current document units
        units = doc.GetUnits()

        # Set the new unit system to Imperial
        units.SetFormatOptions(UnitType.UT_Length, FormatOptions(DisplayUnitType.DUT_FEET_FRACTIONAL_INCHES, 0.1))
        units.SetFormatOptions(UnitType.UT_Area, FormatOptions(DisplayUnitType.DUT_SQUARE_FEET, 0.1))
        units.SetFormatOptions(UnitType.UT_Volume, FormatOptions(DisplayUnitType.DUT_CUBIC_FEET, 0.1))
        units.SetFormatOptions(UnitType.UT_Slope, FormatOptions(DisplayUnitType.DUT_PERCENTAGE, 0.1))
        units.SetFormatOptions(UnitType.UT_Angle, FormatOptions(DisplayUnitType.DUT_DECIMAL_DEGREES, 0.1))

        # Apply the modified units to the document
        doc.SetUnits(units)

        # Commit the transaction
        t.Commit()

else:
    t = Transaction(doc, "Change to Metric")
    t.Start()

    # Get the current document units
    units = doc.GetUnits()

    # Define new FormatOptions using correct UnitTypeId values
    length_format = FormatOptions(UnitTypeId.Millimeters)  # Length in Meters
    area_format = FormatOptions(UnitTypeId.SquareMeters)  # Area in Square Meters
    volume_format = FormatOptions(UnitTypeId.CubicMeters)  # Volume in Cubic Meters
    slope_format = FormatOptions(UnitTypeId.SlopeDegrees)  # Slope in Degrees (Percentage alternative)
    angle_format = FormatOptions(UnitTypeId.Degrees)  # Angle in Decimal Degrees

    # Apply the new format options
    units.SetFormatOptions(SpecTypeId.Length, length_format)
    units.SetFormatOptions(SpecTypeId.Area, area_format)
    units.SetFormatOptions(SpecTypeId.Volume, volume_format)
    units.SetFormatOptions(SpecTypeId.Slope, slope_format)
    units.SetFormatOptions(SpecTypeId.Angle, angle_format)

    # Apply the modified units to the document
    doc.SetUnits(units)

    # Commit the transaction
    t.Commit()

    if not TOGGLE:
        t = Transaction(doc, "Change to Imperial")
        t.Start()

        # Get the current document units
        units = doc.GetUnits()

        # Define new FormatOptions using correct UnitTypeId values
        length_format = FormatOptions(UnitTypeId.FeetFractionalInches)  # Length in Feet & Fractional Inches
        area_format = FormatOptions(UnitTypeId.SquareFeet)  # Area in Square Feet
        volume_format = FormatOptions(UnitTypeId.CubicFeet)  # Volume in Cubic Feet
        slope_format = FormatOptions(UnitTypeId.SlopeDegrees)  # Slope in Degrees (Percentage alternative)
        angle_format = FormatOptions(UnitTypeId.Degrees)  # Angle in Decimal Degrees

        # Apply the new format options
        units.SetFormatOptions(SpecTypeId.Length, length_format)
        units.SetFormatOptions(SpecTypeId.Area, area_format)
        units.SetFormatOptions(SpecTypeId.Volume, volume_format)
        units.SetFormatOptions(SpecTypeId.Slope, slope_format)
        units.SetFormatOptions(SpecTypeId.Angle, angle_format)

        # Apply the modified units to the document
        doc.SetUnits(units)

        # Commit the transaction
        t.Commit()