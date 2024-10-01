# -*- coding: utf-8 -*-

from System import *
from Autodesk.Revit.DB import *

uidoc     = __revit__.ActiveUIDocument

print(type(BuiltInCategory.OST_Walls))