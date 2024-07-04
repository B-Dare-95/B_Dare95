import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import *
from pyrevit import forms,script,revit

# Get the current Revit document
doc = __revit__.ActiveUIDocument.Document

#Get Loaded Families
all_loaded_families=FilteredElementCollector(doc).OfClass(Family).ToElements()

editable_families=[]

for family in all_loaded_families:
    if family.IsEditable:
        editable_families.append(family)

print("This Project has " +str(len(editable_families))+(" Editable Families"))
print("-"*100)
print("-"*100)

#Choose a Category to Filter Families
def get_all_cats(doc):
    cats = doc.Settings.Categories
    return [cat.Name for cat in cats]

all_cats=get_all_cats(doc)

names_choose=sorted(all_cats)

cat_chosen=forms.SelectFromList.show(names_choose,title="Choose Categories"\
                                       ,width=300\
                                       ,button_name="Make A Selection"\
                                       ,multiselect=False)
if cat_chosen:
    print("You are now Investigating Families of Category: "+ cat_chosen)
    print("-" * 100)

elif not cat_chosen:
    script.exit()

#Filter Families by chosen Category

families_to_inspect=[fam for fam in editable_families if fam.FamilyCategory.Name == cat_chosen]
if families_to_inspect:
    print(str(len(families_to_inspect)) + " Families Found")
    print("-" * 100)

else :
    print("No Families found of this Category: " + cat_chosen)
    script.exit()

for serial,family in enumerate(families_to_inspect):
    def family_tree(family,lvl=1):
        if family.IsEditable:
            family_doc=doc.EditFamily(family)
            nested_families = FilteredElementCollector(family_doc).OfClass(Family).ToElements()
            print(family_doc.Title + " has " + str(len(nested_families)) + " Nested Families @ Level " + str(lvl))

            lvl += 1
            for fam in nested_families:
                if fam.IsEditable:
                    family_tree(fam,lvl)
            if not nested_families:
                print("No Further Levels found")

    print("Family No. "+ str(serial+1) + " >> " + family.Name)
    print("_" * 40)
    print(family_tree(family))
    print("-" * 100)