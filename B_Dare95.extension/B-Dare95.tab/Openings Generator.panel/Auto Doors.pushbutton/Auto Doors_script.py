# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog
from System.Collections.Generic import List

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
#==================================================
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document #type: Document
app       = __revit__.Application

from pyrevit import forms,script

naming_convention = "SDC_A_DOR_ENLARGED"

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
#==================================================
#👉 Get and Sort Window Instances of Each Type

all_doors = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType().ToElements()

if not all_doors:
    TaskDialog.Show("Auto Doors","No Doors found in Model")
    script.exit()


door_ids = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType().ToElementIds()

wall_ids = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElementIds()

#👉 Get and Sort Anything that's not a Window

non_doors=[elem for elem in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements() if elem.Id not in door_ids]
# non_windows_and_walls = [elem for elem in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements() if elem.Id not in window_ids or wall_ids]


dict_doors = {}
for door in all_doors:
    family_name = door.Symbol.Family.Name
    type_name   = Element.Name.GetValue(door.Symbol)
    key_name    = '{}_{}'.format(family_name, type_name)


    host = door.Host
    if type(host) == Wall:
        dict_doors[key_name] = door
    else:
        print('Unsupported Host for Window: {} [{}]'.format(key_name, door.Id))

chosen_doors = forms.SelectFromList.show(list(dict_doors.keys()),
                                            title="Choose Windows",
                                            width=300,
                                            button_name="Make A Selection",
                                            multiselect=True)

if not chosen_doors:
    pass
    script.exit()

chosen_doors_dict={}

for chosen_door in chosen_doors:
    chosen_door_elem=dict_doors.get(chosen_door)
    chosen_doors_dict.update({chosen_door:chosen_door_elem})

#🔏 Create Transaction to Modify Project
t = Transaction(doc, 'Generate Door Sections')
t.Start() #🔓


#🎯 Create Section
for door_name, door in chosen_doors_dict.items():
    try:
        #1️⃣ Get Window Origin Point
        door_origin = door.Location.Point          #type: XYZ

        #2️⃣ Calculate Vector based on the Wall
        host_wall = door.Host
        curve     = host_wall.Location.Curve        #type: Curve
        pt_start  = curve.GetEndPoint(0)            #type: XYZ
        pt_end    = curve.GetEndPoint(1)            #type: XYZ
        vector    = pt_end - pt_start               #type: XYZ

        #3️⃣ Get Window Size
        door_width  = door.Symbol.get_Parameter(BuiltInParameter.GENERIC_WIDTH).AsDouble()
        door_depth  = UnitUtils.ConvertToInternalUnits(40, UnitTypeId.Centimeters) #40cm (Revit API takes unit in FEET!)
        offset     = UnitUtils.ConvertToInternalUnits(40, UnitTypeId.Centimeters) #40cm (Revit API takes unit in FEET!)
        door_height = door.Symbol.get_Parameter(BuiltInParameter.CASEWORK_HEIGHT).AsDouble() # ADJUST TO YOUR PARAMETERS!
        if not door_height:
            print("Door: " + door_name + ">> No Built-in Height Parameter Found, Please Check!" )

        # ╔╦╗╦═╗╔═╗╔╗╔╔═╗╔═╗╔═╗╦═╗╔╦╗
        #  ║ ╠╦╝╠═╣║║║╚═╗╠╣ ║ ║╠╦╝║║║
        #  ╩ ╩╚═╩ ╩╝╚╝╚═╝╚  ╚═╝╩╚═╩ ╩
        # ==================================================

        # 🪟 TRANSFORMATION - ELEVATION SECTION
        # 4️⃣🅰️ Create Transform (Origin point + X,Y,Z Vectors)

        # TRANSFORMATION - ELEVATION
        trans_elev        = Transform.Identity           # Create Instance of Transform
        trans_elev.Origin = door_origin                   # Set Origin Point (Window Insertion Point)

        vector = vector.Normalize() # * -1/1 Multiply Vector to flip Section if necessary!

        trans_elev.BasisX = vector
        trans_elev.BasisY = XYZ.BasisZ
        trans_elev.BasisZ = vector.CrossProduct(XYZ.BasisZ)  #The cross product is defined as the vector which is perpendicular to both vectors

        section_box_elev = BoundingBoxXYZ()  # origin 0,0,0

        half = door_width / 2
        section_box_elev.Min = XYZ(-half - offset, 0 - offset, -door_depth)
        section_box_elev.Max = XYZ(half + offset, door_height + offset, door_depth)
        # 💡               XYZ(X - Left/Right , Y - Up/Down          , Z - Forward/Backwards)

        section_box_elev.Transform = trans_elev  # Apply Transform (Origin + XYZ Vectors)

        # Create Section View
        section_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
        window_elevation = ViewSection.CreateSection(doc, section_type_id, section_box_elev)


        non_door_ids = []
        for non_door in non_doors:
            if non_door.CanBeHidden(window_elevation):
                non_door_ids.append(non_door.Id)
        window_elevation.HideElements(List[ElementId](non_door_ids))

        # New Name
        new_name = 'SDC_A_DOR_ENLARGED_{} (Elevation)'.format(door_name)

        for i in range(10):
            try:
                window_elevation.Name = new_name
                print('✅ Created Elevation: {}'.format(new_name))
                break
            except:
                new_name += '*'


        # ==================================================

        #🪟 TRANSFORMATION - CROSS SECTION
        #4️⃣🅱️ Create Transform (Origin point + X,Y,Z Vectors)
        trans_sect       = Transform.Identity           # Create Instance of Transform
        trans_sect.Origin = door_origin                   # Set Origin Point (Window Insertion Point)

        vector = vector.Normalize() # * -1/1 Multiply Vector to flip Section if necessary!

        vector_cross = vector.CrossProduct(XYZ.BasisZ)

        trans_sect.BasisX = vector_cross
        trans_sect.BasisY = XYZ.BasisZ
        trans_sect.BasisZ = vector_cross.CrossProduct(XYZ.BasisZ)

        section_box_sect = BoundingBoxXYZ()  # origin 0,0,0

        half = door_width / 2
        section_box_sect.Min = XYZ(-half - offset, 0 - offset, -door_depth)
        section_box_sect.Max = XYZ(half + offset, door_height + offset, door_depth)
        # 💡               XYZ(X - Left/Right , Y - Up/Down          , Z - Forward/Backwards)

        section_box_sect.Transform = trans_sect  # Apply Transform (Origin + XYZ Vectors)

        # Create Section View
        section_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
        window_section = ViewSection.CreateSection(doc, section_type_id, section_box_sect)

        non_door_ids = []
        for non_door in non_doors:
            if non_door.CanBeHidden(window_section):
                non_door_ids.append(non_door.Id)
        window_section.HideElements(List[ElementId](non_door_ids))

        # New Name
        new_name = 'SDC_A_DOR_ENLARGED_{} (Section)'.format(door_name)

        for i in range(10):
            try:
                window_section.Name = new_name
                print('✅ Created Section: {}'.format(new_name))
                break
            except:
                new_name += '*'
        # ==================================================

        # #🪟 TRANSFORMATION - SECTION PLAN
        # #4️⃣©️ Create Transform (Origin point + X,Y,Z Vectors)
        trans_plan = Transform.Identity  # Create Instance of Transform
        trans_plan.Origin = door_origin  # Set Origin Point (Window Insertion Point)

        # Create Transform for PlanSection (XYZ Vectors) 🤦‍♂️ Yes, Section can be used to look down like Plans...
        vector = vector.Normalize()
        trans_plan.BasisX = vector
        trans_plan.BasisY = -XYZ.BasisZ.CrossProduct(vector).Normalize()
        trans_plan.BasisZ = -XYZ.BasisZ

        section_box_plan = BoundingBoxXYZ()  # origin 0,0,0

        half = door_width / 2
        section_box_plan.Min = XYZ(-half - offset, 0 - offset*3.5, -door_width)
        section_box_plan.Max = XYZ(half + offset, door_height-offset*3, door_width)
        # 💡               XYZ(X - Left/Right , Y - Up/Down          , Z - Forward/Backwards)

        section_box_plan.Transform = trans_plan  # Apply Transform (Origin + XYZ Vectors)

        # Create Section View
        section_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
        door_plan = ViewSection.CreateSection(doc, section_type_id, section_box_plan)

        non_door_ids = []
        for non_door in non_doors:
            if non_door.CanBeHidden(door_plan):
                non_door_ids.append(non_door.Id)
        door_plan.HideElements(List[ElementId](non_door_ids))

        # New Name
        new_name = 'SDC_A_DOR_ENLARGED_{} (Plan)'.format(door_name)

        for i in range(10):
            try:
                door_plan.Name = new_name
                print('✅ Created Plan: {}'.format(new_name))
                break
            except:
                new_name += '*'
        # ==================================================

    except:
        import traceback
        print('---\n❌ERROR:')
        print(traceback.format_exc())

t.Commit() # 🔒