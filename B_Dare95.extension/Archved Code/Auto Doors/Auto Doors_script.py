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

naming_convention = "SDC_A_WDW_ENLARGED"

# ╔╦╗╔═╗╦╔╗╔
# ║║║╠═╣║║║║
# ╩ ╩╩ ╩╩╝╚╝ MAIN
#==================================================
#👉 Get and Sort Window Instances of Each Type

windows = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType().ToElements()

if not windows:
    TaskDialog.Show("Auto Windows","No Windows found in Model")
    script.exit()

window_ids = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType().ToElementIds()

wall_ids = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Walls).WhereElementIsNotElementType().ToElementIds()

#👉 Get and Sort Anything that's not a Window

non_windows=[elem for elem in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements() if elem.Id not in window_ids]
# non_windows_and_walls = [elem for elem in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements() if elem.Id not in window_ids or wall_ids]


dict_windows = {}
for win in windows:
    family_name = win.Symbol.Family.Name
    type_name   = Element.Name.GetValue(win.Symbol)
    key_name    = '{}_{}'.format(family_name, type_name)


    host = win.Host
    if type(host) == Wall:
        dict_windows[key_name] = win
    else:
        print('Unsupported Host for Window: {} [{}]'.format(key_name, win.Id))

chosen_windows = forms.SelectFromList.show(list(dict_windows.keys()),
                                            title="Choose Windows",
                                            width=300,
                                            button_name="Make A Selection",
                                            multiselect=True)

if not chosen_windows:
    pass
    script.exit()

chosen_windows_dict={}

for chosen_window in chosen_windows:
    chosen_window_elem=dict_windows.get(chosen_window)
    chosen_windows_dict.update({chosen_window:chosen_window_elem})

#🔏 Create Transaction to Modify Project
t = Transaction(doc, 'Generate Window Sections')
t.Start() #🔓


#🎯 Create Section
for window_name, window in chosen_windows_dict.items():
    try:
        #1️⃣ Get Window Origin Point
        win_origin = window.Location.Point          #type: XYZ

        #2️⃣ Calculate Vector based on the Wall
        host_wall = window.Host
        curve     = host_wall.Location.Curve        #type: Curve
        pt_start  = curve.GetEndPoint(0)            #type: XYZ
        pt_end    = curve.GetEndPoint(1)            #type: XYZ
        vector    = pt_end - pt_start               #type: XYZ

        #3️⃣ Get Window Size
        win_width  = window.Symbol.get_Parameter(BuiltInParameter.GENERIC_WIDTH).AsDouble()
        win_depth  = UnitUtils.ConvertToInternalUnits(40, UnitTypeId.Centimeters) #40cm (Revit API takes unit in FEET!)
        offset     = UnitUtils.ConvertToInternalUnits(40, UnitTypeId.Centimeters) #40cm (Revit API takes unit in FEET!)
        win_height = window.Symbol.get_Parameter(BuiltInParameter.CASEWORK_HEIGHT).AsDouble() # ADJUST TO YOUR PARAMETERS!
        if not win_height:
            print("Window: " + window_name + ">> No Built-in Height Parameter Found, Please Check!" )

        # ╔╦╗╦═╗╔═╗╔╗╔╔═╗╔═╗╔═╗╦═╗╔╦╗
        #  ║ ╠╦╝╠═╣║║║╚═╗╠╣ ║ ║╠╦╝║║║
        #  ╩ ╩╚═╩ ╩╝╚╝╚═╝╚  ╚═╝╩╚═╩ ╩
        # ==================================================

        # 🪟 TRANSFORMATION - ELEVATION SECTION
        # 4️⃣🅰️ Create Transform (Origin point + X,Y,Z Vectors)

        # TRANSFORMATION - ELEVATION
        trans_elev        = Transform.Identity           # Create Instance of Transform
        trans_elev.Origin = win_origin                   # Set Origin Point (Window Insertion Point)

        vector = vector.Normalize() # * -1/1 Multiply Vector to flip Section if necessary!

        trans_elev.BasisX = vector
        trans_elev.BasisY = XYZ.BasisZ
        trans_elev.BasisZ = vector.CrossProduct(XYZ.BasisZ)  #The cross product is defined as the vector which is perpendicular to both vectors

        section_box_elev = BoundingBoxXYZ()  # origin 0,0,0

        half = win_width / 2
        section_box_elev.Min = XYZ(-half - offset, 0 - offset, -win_depth)
        section_box_elev.Max = XYZ(half + offset, win_height + offset, win_depth)
        # 💡               XYZ(X - Left/Right , Y - Up/Down          , Z - Forward/Backwards)

        section_box_elev.Transform = trans_elev  # Apply Transform (Origin + XYZ Vectors)

        # Create Section View
        section_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
        window_elevation = ViewSection.CreateSection(doc, section_type_id, section_box_elev) #ELEVATION CREATED HERE!!,HOW TO CREATE ACTUAL ELEVATION??


        non_win_ids = []
        for non_window in non_windows:
            if non_window.CanBeHidden(window_elevation):
                non_win_ids.append(non_window.Id)
        window_elevation.HideElements(List[ElementId](non_win_ids))

        # New Name
        new_name = 'SDC_A_WDW_ENLARGED_{} (Elevation)'.format(window_name)

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
        trans_sect.Origin = win_origin                   # Set Origin Point (Window Insertion Point)

        vector = vector.Normalize() # * -1/1 Multiply Vector to flip Section if necessary!

        vector_cross = vector.CrossProduct(XYZ.BasisZ)

        trans_sect.BasisX = vector_cross
        trans_sect.BasisY = XYZ.BasisZ
        trans_sect.BasisZ = vector_cross.CrossProduct(XYZ.BasisZ)

        section_box_sect = BoundingBoxXYZ()  # origin 0,0,0

        half = win_width / 2
        section_box_sect.Min = XYZ(-half - offset, 0 - offset, -win_depth)
        section_box_sect.Max = XYZ(half + offset, win_height + offset, win_depth)
        # 💡               XYZ(X - Left/Right , Y - Up/Down          , Z - Forward/Backwards)

        section_box_sect.Transform = trans_sect  # Apply Transform (Origin + XYZ Vectors)

        # Create Section View
        section_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
        window_section = ViewSection.CreateSection(doc, section_type_id, section_box_sect) #SECTION CREATED HERE!!

        non_win_ids = []
        for non_window in non_windows:
            if non_window.CanBeHidden(window_section):
                non_win_ids.append(non_window.Id)
        window_section.HideElements(List[ElementId](non_win_ids))

        # New Name
        new_name = 'SDC_A_WDW_ENLARGED_{} (Section)'.format(window_name)

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
        trans_plan.Origin = win_origin  # Set Origin Point (Window Insertion Point)

        # Create Transform for PlanSection (XYZ Vectors) 🤦‍♂️ Yes, Section can be used to look down like Plans...
        vector = vector.Normalize()
        trans_plan.BasisX = vector
        trans_plan.BasisY = -XYZ.BasisZ.CrossProduct(vector).Normalize()
        trans_plan.BasisZ = -XYZ.BasisZ

        section_box_plan = BoundingBoxXYZ()  # origin 0,0,0

        half = win_width / 2
        section_box_plan.Min = XYZ(-half - offset, 0 - offset, -win_depth)
        section_box_plan.Max = XYZ(half + offset, win_height + offset, win_depth)
        # 💡               XYZ(X - Left/Right , Y - Up/Down          , Z - Forward/Backwards)

        section_box_plan.Transform = trans_plan  # Apply Transform (Origin + XYZ Vectors)

        # Create Section View
        section_type_id = doc.GetDefaultElementTypeId(ElementTypeGroup.ViewTypeSection)
        window_plan = ViewSection.CreateSection(doc, section_type_id, section_box_plan) #PLAN CREATED HERE!!HOW TO CREATE ACTUAL PLAN??

        non_win_ids = []
        for non_window in non_windows:
            if non_window.CanBeHidden(window_plan):
                non_win_ids.append(non_window.Id)
        window_plan.HideElements(List[ElementId](non_win_ids))

        # New Name
        new_name = 'SDC_A_WDW_ENLARGED_{} (Plan)'.format(window_name)

        for i in range(10):
            try:
                window_plan.Name = new_name
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