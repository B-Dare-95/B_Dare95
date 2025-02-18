# -*- coding: utf-8 -*-

# IMPORTS
#==================================================
import traceback

from Autodesk.Revit.DB import *
from pyrevit import *

# VARIABLES
#==================================================
sender = __eventsender__
args   = __eventargs__

fail_accessor = args.GetFailuresAccessor()

failures = fail_accessor.GetFailureMessages()

for fail in failures:  # type: FailureMessageAccessor
    severity = fail.GetSeverity()
    fail_id = fail.GetFailureDefinitionId()

    if fail_id == BuiltInFailures.FloorFailures.FloorSlopeExceedsThreshold:
        if severity == FailureSeverity.Warning:
            fail_accessor.DeleteWarning(fail)