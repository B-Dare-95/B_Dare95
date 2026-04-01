# -*- coding: utf-8 -*-

# Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit, script
from pyrevit import EXEC_PARAMS

# Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView
output      = script.get_output()

# --- Wall Types ---
all_wall_types = FilteredElementCollector(doc).OfClass(WallType).ToElements()

wall_type_names = {
    wt.LookupParameter("Type Name").AsString(): wt
    for wt in all_wall_types
}

# --- Levels (sorted by elevation) ---
all_levels = (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_Levels)
              .WhereElementIsNotElementType()
              .ToElements())

sorted_levels    = sorted(all_levels, key=lambda lvl: lvl.Elevation)
sorted_level_ids = [lvl.Id for lvl in sorted_levels]

# --- Collect and Classify Shafts ---
all_shafts = (FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_ShaftOpening)
              .WhereElementIsNotElementType()
              .ToElements())

shafts_less_than_3lvls    = []
shafts_greater_than_3lvls = []

for shaft in all_shafts:
    shaft_top_id    = shaft.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()
    shaft_bottom_id = shaft.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()

    bottom_index = sorted_level_ids.index(shaft_bottom_id)
    top_index    = sorted_level_ids.index(shaft_top_id)

    # Number of levels the shaft crosses (inclusive of both bounding levels)
    no_of_connected_lvls = (top_index - bottom_index) + 1

    if no_of_connected_lvls < 3:
        shafts_less_than_3lvls.append(shaft)
    else:
        shafts_greater_than_3lvls.append(shaft)

# --- User Selects Wall Types ---
TaskDialog.Show("Choose Wall Type", "Choose a Wall Type for Shafts connecting fewer than 3 levels.")

wall_1hr_chosen = forms.SelectFromList.show(
    sorted(wall_type_names.keys()),
    title="Choose a Wall Type",
    width=300,
    button_name="Done",
    multiselect=False)

chosen_one_hr_type_wall = wall_type_names[wall_1hr_chosen]

TaskDialog.Show("Choose Wall Type", "Choose a Wall Type for Shafts connecting 3 or more levels.")

wall_2hr_chosen = forms.SelectFromList.show(
    sorted(wall_type_names.keys()),
    title="Choose a Wall Type",
    width=300,
    button_name="Done",
    multiselect=False)

chosen_two_hr_type_wall = wall_type_names[wall_2hr_chosen]


# --- Helper: Create Encasing Walls for a Shaft ---
def create_encasing_walls(shaft, wall_type):
    """
    Creates encasing walls around a shaft boundary curve for every floor-to-floor
    interval that the shaft spans — no more, no less.
    """
    shaft_top_id    = shaft.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsElementId()
    shaft_bottom_id = shaft.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId()

    bottom_index = sorted_level_ids.index(shaft_bottom_id)
    top_index    = sorted_level_ids.index(shaft_top_id)

    # Only the levels the shaft spans (exclude the topmost — it is the ceiling, not a base)
    shaft_levels = sorted_levels[bottom_index:top_index]

    shaft_bounds = shaft.BoundaryCurves

    for i, base_level in enumerate(shaft_levels):
        # The next level up determines the wall height for this floor band
        next_level  = sorted_levels[bottom_index + i + 1]
        wall_height = next_level.Elevation - base_level.Elevation

        for boundary_curve in shaft_bounds:
            Wall.Create(
                doc,
                boundary_curve,
                wall_type.Id,
                base_level.Id,
                wall_height,
                0,       # offset
                False,   # flip
                False    # structural
            )


# --- Transaction ---
t = Transaction(doc, "Create Shaft Encasing Walls")
t.Start()

for shaft in shafts_less_than_3lvls:
    create_encasing_walls(shaft, chosen_one_hr_type_wall)

for shaft in shafts_greater_than_3lvls:
    create_encasing_walls(shaft, chosen_two_hr_type_wall)

t.Commit()