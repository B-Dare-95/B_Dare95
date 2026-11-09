# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes view templates that no view uses and no view type applies to new views.
__________________________________________________
How-to:

-> Click on the button
-> Read the list of unused view templates: they are all checked
-> Uncheck anything you want to keep
-> Check Show used items too to see what stays and why
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "view_templates")  # noqa: F821
