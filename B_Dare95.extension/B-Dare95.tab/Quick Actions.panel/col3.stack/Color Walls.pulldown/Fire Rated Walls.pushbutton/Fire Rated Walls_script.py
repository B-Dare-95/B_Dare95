# -*- coding: utf-8 -*-

#Imports
from Autodesk.Revit.DB import *
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
active_view = doc.ActiveView

# Get Solid Pattern
all_patterns  = FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements()
solid_pattern = [i for i in all_patterns if i.GetFillPattern().IsSolidFill][0]

# Get Exterior/Interior Walls

all_walls_in_view=FilteredElementCollector(doc,active_view.Id).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements()

one_hour_rated_walls=[]
two_hour_rated_walls=[]

for wall in all_walls_in_view:

    if "FPR" in wall.Name:
        if "60MINS" in wall.Name:
            one_hour_rated_walls.append(wall)
        elif "120MINS" in wall.Name:
            two_hour_rated_walls.append(wall)

# Create Filtering Colors
one_hour_rated_color = Color(250, 253, 45)
two_hour_rated_color = Color(255, 0, 0)

# Create One_Hour Graphic Settings
override_settings_one_hour = OverrideGraphicSettings()

override_settings_one_hour.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings_one_hour.SetSurfaceForegroundPatternColor(one_hour_rated_color)

override_settings_one_hour.SetCutForegroundPatternId(solid_pattern.Id)
override_settings_one_hour.SetCutForegroundPatternColor(one_hour_rated_color)

# Create Two_Hour Graphic Settings
override_settings_two_hour = OverrideGraphicSettings()

override_settings_two_hour.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings_two_hour.SetSurfaceForegroundPatternColor(two_hour_rated_color)

override_settings_two_hour.SetCutForegroundPatternId(solid_pattern.Id)
override_settings_two_hour.SetCutForegroundPatternColor(two_hour_rated_color)


reset_override = OverrideGraphicSettings()

if EXEC_PARAMS.config_mode:
    t = Transaction(doc, "Reset Colorize")

    t.Start()

    for wall in one_hour_rated_walls:
        doc.ActiveView.SetElementOverrides(wall.Id, reset_override)

    for wall in two_hour_rated_walls:
        doc.ActiveView.SetElementOverrides(wall.Id, reset_override)

    t.Commit()

else:


    t = Transaction(doc, "Colorize Walls (Fire Rating)")

    t.Start()

    for wall in one_hour_rated_walls:
        doc.ActiveView.SetElementOverrides(wall.Id, override_settings_one_hour)

    for wall in two_hour_rated_walls:
        doc.ActiveView.SetElementOverrides(wall.Id, override_settings_two_hour)

    t.Commit()