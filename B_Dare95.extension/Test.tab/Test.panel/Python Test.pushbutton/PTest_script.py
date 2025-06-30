import clr
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, Element, ElementId, ParameterValueProvider, \
    FilterStringRule, ElementParameterFilter, ParameterValueProvider, FilterElementIdRule, ElementId, BuiltInParameter

# Get current Revit document
doc = __revit__.ActiveUIDocument.Document

# Collect all walls in the model
walls = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElements()

# Process each wall
for wall in walls:
    # Get wall type
    wall_type_id = wall.GetTypeId()
    wall_type = doc.GetElement(wall_type_id)

    # Get wall type parameters
    type_params = wall_type.Parameters

    # Get the wall's name
    wall_name = wall.Name if hasattr(wall, "Name") and wall.Name else "Unnamed Wall"
    type_name = wall_type.Name if hasattr(wall_type, "Name") and wall_type.Name else "Unnamed Type"

    print("Wall: {} (Type: {})".format(wall_name, type_name))

    # Get Fire Rating parameter
    fire_rating_param = None

    # Try to get fire rating parameter from wall
    fire_rating_param = wall.get_Parameter()

    # If not found on wall, try to get it from the wall type
    if fire_rating_param is None or not fire_rating_param.HasValue:
        fire_rating_param = wall_type.LookupParameter("Fire Rating")

    # Print fire rating if found
    if fire_rating_param is not None and fire_rating_param.HasValue:
        fire_rating_value = fire_rating_param.AsString()
        print("  Fire Rating: {}".format(fire_rating_value))
    else:
        print("  Fire Rating: Not specified")

    print("  Type Parameters:")
    for param in type_params:
        # Skip non-valued parameters
        if not param.HasValue:
            continue

        param_name = param.Definition.Name

        # Get parameter value based on its storage type
        if param.StorageType.ToString() == "String":
            param_value = param.AsString()
        elif param.StorageType.ToString() == "Integer":
            param_value = param.AsInteger()
        elif param.StorageType.ToString() == "Double":
            param_value = param.AsDouble()
        elif param.StorageType.ToString() == "ElementId":
            param_value = param.AsElementId().IntegerValue
        else:
            param_value = "Unknown value type"

        print("    {}: {}".format(param_name, param_value))

    print("")

