# -*- coding: utf-8 -*-
from symbol import continue_stmt

#Imports
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import *
from System.Collections.Generic import List
from pyrevit import forms, revit,script
from pyrevit import EXEC_PARAMS

#Revit Variables
uidoc       = __revit__.ActiveUIDocument
doc         = __revit__.ActiveUIDocument.Document
selection   = uidoc.Selection
app         = __revit__.Application
active_view = doc.ActiveView

# -*- coding: utf-8 -*-
__title__   = "05.05 - Supress Warning"
__doc__ = """Date    = 22.03.2024
_____________________________________________________________________
Description:
Learn how to Supress Warnings with Revit API.
_____________________________________________________________________
Author: Erik Frits"""

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
#==================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import *


# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
uidoc = __revit__.ActiveUIDocument
doc   = __revit__.ActiveUIDocument.Document

#--------------------------------------------------

#🔬 ISelectionFilter - Walls
class WallFilter(ISelectionFilter):
    def AllowElement(self, elem):
        if type(elem) == Wall:
            return True

#⚠️ Transaction Error Handler
class SolveWarnings(IFailuresPreprocessor):
    def PreprocessFailures(self, failuresAccessor):
        try:
            failures = failuresAccessor.GetFailureMessages()

            for fail in failures: #type: FailureMessageAccessor
                severity    = fail.GetSeverity()
                description = fail.GetDescriptionText()

                if description == "Thickness of this Floor may be slightly inaccurate due to extreme Shape Editing. Dimensions to this element in sections and details may not accurately indicate the Thickness shown in Type Properties.":
                    print('Captured: {}'.format(description))
                    failuresAccessor.ResolveFailure(fail)

                else:
                    print('Warning: {}'.format(description))
        except:
            import traceback
            print(traceback.format_exc())

        return FailureProcessingResult.Continue


# 🔓 Start Transaction
t = Transaction(doc, 'Update Mark')
t.Start()

#💡 Assign Error Handler
fail_hand_opts = t.GetFailureHandlingOptions()
fail_hand_opts.SetFailuresPreprocessor(SolveWarnings())
t.SetFailureHandlingOptions(fail_hand_opts)

t.Commit()