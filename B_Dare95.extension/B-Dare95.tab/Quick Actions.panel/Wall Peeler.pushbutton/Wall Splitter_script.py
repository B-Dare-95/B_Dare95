# -*- coding: utf-8 -*-
__title__   = "Wall Peeler"
__doc__     = """Version = 1.0
Date    = 17.01.2025
________________________________________________________________
Description:
- Select Wall
- Split Into Individual Layers
________________________________________________________________

To-Do:
- Supress Join walls Warning
- Keep same Mark Parameter (+Supress Mark Parameter Warning)
________________________________________________________________
Authors: Erik Frits / Mohamed Bedair"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝
#====================================================================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *
from pyrevit import forms

#.NET Imports
import clr
clr.AddReference('System')
from System.Collections.Generic import List

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#====================================================================================================
doc      = __revit__.ActiveUIDocument.Document
uidoc    = __revit__.ActiveUIDocument
app      = __revit__.Application


# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝
#====================================================================================================

def pick_wall():
    #type: () -> WallType
    class WallFilter(ISelectionFilter):
        def AllowElement(self, elem):
            if elem.Category.Name == "Walls":
                return True

    try:
        ref_wall = uidoc.Selection.PickObject(ObjectType.Element, WallFilter(), "Select Wall to Slice")
        wall     = doc.GetElement(ref_wall)
        return wall
    except:
        forms.alert("Couldn't Pick Wall. Please Try Again", exitscript=True)

def generate_wall_type_name(layer):
    # Get Current Material Name
    mat_id       = layer.MaterialId
    if mat_id   != ElementId.InvalidElementId:
        mat      = doc.GetElement(mat_id)
        mat_name = mat.Name
    else:
        mat_name = 'Empty'

        # New Type Name
    width_cm = UnitUtils.ConvertFromInternalUnits(layer.Width, UnitTypeId.Centimeters)
    new_type_name = "{} ({}cm)".format(mat_name, width_cm)
    return new_type_name

def duplicate_wall_type(wall_type, new_type_name, layer=None):
    # Duplicate Wall Type (if doesn't exist)
    new_wall_type      = wall_type.Duplicate(new_type_name)
    new_wall_type.Name = new_type_name

    if layer:
        compound = CompoundStructure.CreateSimpleCompoundStructure([layer])
        new_wall_type.SetCompoundStructure(compound)

    return new_wall_type


def get_hosted_elements(wall):
    # Get the dependent elements of the wall
    dependent_ids = wall.GetDependentElements(None)

    # Collect the hosted elements by filtering only those with valid categories (ignoring annotations, etc.)
    hosted_elements = []
    for elem_id in dependent_ids:
        element = doc.GetElement(elem_id)
        if element is not None and element.Category is not None:
            hosted_elements.append(element)

    return hosted_elements

def duplicate_wall(wall, keep_hosted ):
    list_wall_ids   = [wall.Id, ]
    walls_to_copy   = List[ElementId](list_wall_ids)
    new_element_ids = ElementTransformUtils.CopyElements(doc, walls_to_copy, XYZ(0,0,0))
    new_wall        = doc.GetElement(new_element_ids[0])

    if keep_hosted:
        return new_wall

    # Remove Hosted Elements
    hosted_elements = get_hosted_elements(new_wall)
    # print(hosted_elements)
    for el in hosted_elements:
        if type(el) != Wall:
            doc.Delete(el.Id)



    return new_wall

def get_wall_type_by_name(wall_type_name):
    """Function to get FireWall Types based on FamilyName"""
    # Create Filter
    rvt_year    = int(app.VersionNumber)
    pvp         = ParameterValueProvider(ElementId(BuiltInParameter.ALL_MODEL_TYPE_NAME))
    condition   = FilterStringEquals()
    fRule       = FilterStringRule(pvp, condition, wall_type_name, True) if rvt_year < 2022 \
             else FilterStringRule(pvp, condition, wall_type_name)
    my_filter   = ElementParameterFilter(fRule)

    # Get Types
    return FilteredElementCollector(doc).OfClass(WallType).WherePasses(my_filter).FirstElement()


def join_walls(list_walls):
    for wall1 in list_walls:
        for wall2 in list_walls:
            try:
                JoinGeometryUtils.JoinGeometry(doc, wall1, wall2)
                # print('Joined: {} + {}'.format(wall1.Id, wall2.Id))
            except:
                pass

def split_wall_into_layers(wall):
    new_walls = []

    # Get Wall properties
    wall_layers       = wall.WallType.GetCompoundStructure().GetLayers()
    total_thickness   = sum(layer.Width for layer in wall_layers)
    counter_thickness = 0

    # Create Walls for each layer
    for n, layer in enumerate(wall_layers):
        # Find WallType for Single Layer
        new_type_name = generate_wall_type_name(layer)
        new_wall_type = get_wall_type_by_name(new_type_name)

        # Duplicate WallType for a Single Layer (if doesn't exist)
        if not new_wall_type:
            new_wall_type = duplicate_wall_type(wall.WallType, new_type_name, layer)

        # Create Offset Curve
        offset = (total_thickness - (2 * counter_thickness) - layer.Width) / 2
        if not sel_wall.Flipped:
            offset = -offset
        offset_curve = wall.Location.Curve.CreateOffset(offset, XYZ.BasisZ)

        # Duplicate Wall (To keep parameters)
        keep_hosted       = True if n == 0 else False #Only first layer has True.
        new_wall          = duplicate_wall(wall, keep_hosted)
        new_wall.WallType = new_wall_type
        new_wall.Location.Curve = offset_curve

        # Update Values
        counter_thickness += layer.Width
        new_walls.append(new_wall)

    return new_walls


# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝  MAIN
#====================================================================================================

t=Transaction(doc,"Split Wall Layers.")
t.Start()

sel_wall  = pick_wall()
new_walls = split_wall_into_layers(sel_wall)
join_walls(new_walls)       # Join All New Walls for correct Openings
doc.Delete(sel_wall.Id)     # Delete Existing Wall

#PS Mark parameter will be changed!

t.Commit()