# # -*- coding: utf-8 -*-
# __title__   = "Shut Up,Revit"
# __doc__ = """Date    = 16.02.2025
# _____________________________________________________________________
# Description:
# Revit is annoying me!!
# _____________________________________________________________________
# """
#
# # ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# # ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# # ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# #==================================================
# from Autodesk.Revit.DB import *
# from Autodesk.Revit.UI.Selection import *
#
#
# # ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# # ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
# #  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
# #==================================================
# # uidoc = __revit__.ActiveUIDocument
# doc   = __revit__.ActiveUIDocument.Document
#
# #--------------------------------------------------
#
# #🔬 ISelectionFilter - Walls
# class WallFilter(ISelectionFilter):
#     def AllowElement(self, elem):
#         if type(elem) == Wall:
#             return True
#
# #⚠️ Transaction Error Handler
# class SolveWarnings(IFailuresPreprocessor):
#     def PreprocessFailures(self, failuresAccessor):
#         try:
#             failures = failuresAccessor.GetFailureMessages()
#
#             for fail in failures: #type: FailureMessageAccessor
#                 severity    = fail.GetSeverity()
#                 description = fail.GetDescriptionText()
#                 fail_id = fail.GetFailureDefinitionId()
#
#                 if fail_id == BuiltInFailures.FloorFailures.FloorSlopeExceedsThreshold:
#
#                     failuresAccessor.ResolveFailure(fail)
#
#                 else:
#                     print('Warning: {}'.format(description))
#         except:
#             import traceback
#             print(traceback.format_exc())
#
#         return FailureProcessingResult.Continue
#
#
# # 🔓 Start Transaction
# t = Transaction(doc, 'Update Mark')
# t.Start()
#
# #💡 Assign Error Handler
# fail_hand_opts = t.GetFailureHandlingOptions()
# fail_hand_opts.SetFailuresPreprocessor(SolveWarnings())
# t.SetFailureHandlingOptions(fail_hand_opts)
#
# t.Commit()