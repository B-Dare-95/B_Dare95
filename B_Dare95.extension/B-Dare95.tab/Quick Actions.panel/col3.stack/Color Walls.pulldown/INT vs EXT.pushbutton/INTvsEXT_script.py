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

interior_walls=[]
exterior_walls=[]

interior_walls_original_materials = []
exterior_walls_original_materials = []

for wall in all_walls_in_view:

    if "CMU" in wall.Name:
        if "INT" in wall.Name:
            interior_walls.append(wall)
        elif "EXT" in wall.Name:
            exterior_walls.append(wall)


#Create Filtering Colors
interior_walls_color = Color(102,175,253)
exterior_walls_color = Color(250, 214, 112)


reset_override = OverrideGraphicSettings()


#Create Interior Graphic Settings
override_settings_interior = OverrideGraphicSettings()

override_settings_interior.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings_interior.SetSurfaceForegroundPatternColor(interior_walls_color)

override_settings_interior.SetCutForegroundPatternId(solid_pattern.Id)
override_settings_interior.SetCutForegroundPatternColor(interior_walls_color)

#Create Exterior Graphic Settings
override_settings_exterior = OverrideGraphicSettings()

override_settings_exterior.SetSurfaceForegroundPatternId(solid_pattern.Id)
override_settings_exterior.SetSurfaceForegroundPatternColor(exterior_walls_color)

override_settings_exterior.SetCutForegroundPatternId(solid_pattern.Id)
override_settings_exterior.SetCutForegroundPatternColor(exterior_walls_color)

t = Transaction(doc,"Colorize Walls (INT.vs.EXT)")

t.Start()

for wall in interior_walls:
    doc.ActiveView.SetElementOverrides(wall.Id, override_settings_interior)

for wall in exterior_walls:
    doc.ActiveView.SetElementOverrides(wall.Id, override_settings_exterior)

t.Commit()

if EXEC_PARAMS.config_mode:
    t = Transaction(doc, "Reset Colorize")

    t.Start()

    for wall in interior_walls:
        doc.ActiveView.SetElementOverrides(wall.Id, reset_override)

    for wall in exterior_walls:
        doc.ActiveView.SetElementOverrides(wall.Id, reset_override)

    t.Commit()