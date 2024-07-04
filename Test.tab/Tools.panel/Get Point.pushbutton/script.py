from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *

doc         = __revit__.ActiveUIDocument.Document
uidoc       = __revit__.ActiveUIDocument
selection   = uidoc.Selection

point = selection.PickPoint(ObjectSnapTypes.Endpoints,"Pick a Point")

TaskDialog.Show("Tester","Point Coordinates :\n " + "(" + str(point.X) + ", " +str(point.Y) + ", " + str(point.Z) + ")")