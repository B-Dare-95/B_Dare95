from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

#Revit Variables
uidoc   = __revit__.ActiveUIDocument
doc     = __revit__.ActiveUIDocument.Document
app     = __revit__.Application

def cut_to_clipboard():
    revit_command_id = RevitCommandId.LookupPostableCommandId(PostableCommand.CutToClipboard)

    if revit_command_id:
        return UIApplication(app).PostCommand(revit_command_id)