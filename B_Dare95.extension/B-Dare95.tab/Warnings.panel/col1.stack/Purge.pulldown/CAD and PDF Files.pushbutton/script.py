# -*- coding: utf-8 -*-

__author__ = "Mohamed Bedair"
__doc__ = """__________________________________________________
Description:

Deletes the CAD imports, CAD links and PDFs you tick, not only unused ones, plus CAD links that aren't placed. When every placed copy of a file is ticked, the file itself is removed too. Nothing is ticked for you.
__________________________________________________
How-to:

-> Click on the button
-> Read the list: nothing is ticked for you, so tick what to delete
-> Leave "Purge up to 3 times" ticked to also purge what this purge frees
-> Click Purge and read the result at the bottom; the list refreshes and the window stays open
-> One Undo puts the whole purge back
__________________________________________________
Author: Mohamed Bedair"""

import bd_purge

bd_purge.run(__revit__, "cad_and_pdf")  # noqa: F821
