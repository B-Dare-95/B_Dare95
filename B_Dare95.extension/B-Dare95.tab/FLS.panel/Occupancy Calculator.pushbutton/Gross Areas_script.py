# -*- coding: utf-8 -*-

__title__     = "Occupancy Calculator"
__author__    = "Mohamed Bedair"
__doc__       = """
_____________________________________________________________________
Description:

Collects all Room Areas for Net,Gross and By Seat Calculation
_____________________________________________________________________
How-to:

-> Run the script
-> Excel File will be generated
-> Choose a directory to place file
-> Excel will open automatically
_____________________________________________________________________
Author: Mohamed Bedair"""

 #  ___ __  __ ____   ___  ____ _____ ____
 # |_ _|  \/  |  _ \ / _ \|  _ \_   _/ ___|
 #  | || |\/| | |_) | | | | |_) || | \___ \
 #  | || |  | |  __/| |_| |  _ < | |  ___) |
 # |___|_|  |_|_|    \___/|_| \_\|_| |____/

import clr
clr.AddReference('System.Windows.Forms')

import System.Diagnostics
from System.Diagnostics import Process
from System.IO import Path
from System.IO import File
from System.Windows.Forms import *

import shutil
from collections import defaultdict
import xlsxwriter

from Autodesk.Revit.DB import *

#__     ___    ____  ___    _    ____  _     _____ ____
#\ \   / / \  |  _ \|_ _|  / \  | __ )| |   | ____/ ___|
# \ \ / / _ \ | |_) || |  / _ \ |  _ \| |   |  _| \___ \
#  \ V / ___ \|  _ < | | / ___ \| |_) | |___| |___ ___) |
#   \_/_/   \_\_| \_\___/_/   \_\____/|_____|_____|____/

#REVIT VARIABLES
doc         =__revit__.ActiveUIDocument.Document
uidoc       =__revit__.ActiveUIDocument

#EXCEL VARIABLES
xlsx_filepath = 'D:\Test.xlsx' # PUT HERE YOU ABSOLUTE FILEPATH. DON'T FORGET .xlsx
workbook=xlsxwriter.Workbook(xlsx_filepath)

# __  __    _    ___ _   _
#|  \/  |  / \  |_ _| \ | |
#| |\/| | / _ \  | ||  \| |
#| |  | |/ ___ \ | || |\  |
#|_|  |_/_/   \_\___|_| \_|

#Collect All Rooms
all_rooms     = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType().ToElements()

#Filter Rooms by Area Type
net_rooms     = [room for room in all_rooms if room.LookupParameter("SDC_A_AREA TYPE").AsString() == "NET"]

by_seat_rooms = [room for room in all_rooms if room.LookupParameter("SDC_A_AREA TYPE").AsString() == "N.O.SEATS"]

gross_rooms   = [room for room in all_rooms if room.LookupParameter("SDC_A_AREA TYPE").AsString() == "GROSS"]

# _   _ _____ _____   ____   ___   ___  __  __ ____    ____  _   _ _____ _____ _____
#| \ | | ____|_   _| |  _ \ / _ \ / _ \|  \/  / ___|  / ___|| | | | ____| ____|_   _|
#|  \| |  _|   | |   | |_) | | | | | | | |\/| \___ \  \___ \| |_| |  _| |  _|   | |
#| |\  | |___  | |   |  _ <| |_| | |_| | |  | |___) |  ___) |  _  | |___| |___  | |
#|_| \_|_____| |_|   |_| \_\\___/ \___/|_|  |_|____/  |____/|_| |_|_____|_____| |_|

#List Comprehension to collect Parameters from all Net Rooms
room_name      = [room.LookupParameter("Name").AsString() for room in net_rooms]

room_number    = [room.LookupParameter("Number").AsString() for room in net_rooms]

area_value     = [UnitUtils.ConvertFromInternalUnits(room.LookupParameter("Area").AsDouble(),UnitTypeId.SquareMeters) for room in net_rooms]

room_occupancy = [room.LookupParameter("Occupancy").AsString() for room in net_rooms]

room_factor    = [room.LookupParameter("SDC_A_OCCUPANCY_LOAD_FACTOR").AsDouble() for room in net_rooms]

occupants=[]

for i,j in zip(area_value,room_factor):
    if j == 0:
        result=0
    else:
        result = i / j
    occupants.append(result)

# Create Worksheet for Net Areas
worksheet1 = workbook.add_worksheet('Net Rooms Calculations')

#1️⃣Create Headers

header_format = workbook.add_format({
'bold': True,
'bg_color': '#F5CBA7',
'font_color': 'black',
'font_size': 12,
'border': 2,
'border_color': 'black',
'align': 'left',
'valign': 'vcenter'})

worksheet1.write(0,0,"Room Name",header_format)
worksheet1.write(0,1,"Room Number",header_format)
worksheet1.write(0,2,"Area",header_format)
worksheet1.write(0,3,"Occupancy",header_format)
worksheet1.write(0,4,"Load Factor",header_format)
worksheet1.write(0,5,"No. of Occupants",header_format)

#2️⃣Write Data (+ formatting)

data_format = workbook.add_format({
'border': 1,
'border_color': 'gray',
'align': 'left',
'valign': 'vcenter'})

data = [room_name,room_number,area_value,room_occupancy,room_factor,occupants]

for row,row_data in enumerate(data):
    for col, value in enumerate(row_data):
        if row == 0:
            worksheet1.write(col+1,row,value,data_format)
        else:
            worksheet1.write(col+1,row,value,data_format)

#  ____ ____   ___  ____ ____    ____   ___   ___  __  __ ____    ____  _   _ _____ _____ _____
# / ___|  _ \ / _ \/ ___/ ___|  |  _ \ / _ \ / _ \|  \/  / ___|  / ___|| | | | ____| ____|_   _|
#| |  _| |_) | | | \___ \___ \  | |_) | | | | | | | |\/| \___ \  \___ \| |_| |  _| |  _|   | |
#| |_| |  _ <| |_| |___) |__) | |  _ <| |_| | |_| | |  | |___) |  ___) |  _  | |___| |___  | |
# \____|_| \_\\___/|____/____/  |_| \_\\___/ \___/|_|  |_|____/  |____/|_| |_|_____|_____| |_|

#Get Corresponding Gross Area

all_areas       = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Areas).WhereElementIsNotElementType().ToElements()

gross_room_name = [room.LookupParameter("Name").AsString() for room in gross_rooms]

gross_areas     = [area for area in all_areas if area.LookupParameter("Name").AsString() in gross_room_name]

#List Comprehension to collect Parameters from all Gross Rooms
room_name      = [room.LookupParameter("Name").AsString() for room in gross_rooms]

room_number   = [room.LookupParameter("Number").AsString() for room in gross_rooms]

area_value     = [UnitUtils.ConvertFromInternalUnits(area.LookupParameter("Area").AsDouble(),UnitTypeId.SquareMeters) for area in gross_areas]

room_occupancy = [room.LookupParameter("Occupancy").AsString() for room in gross_rooms]

room_factor    = [room.LookupParameter("SDC_A_OCCUPANCY_LOAD_FACTOR").AsDouble() for room in gross_rooms]

occupants=[]

for i,j in zip(area_value,room_factor):
    if j <= 0:
        result=0
    else:
        result=i/j
    occupants.append(result)

# Create Worksheet
worksheet2 = workbook.add_worksheet('Gross Rooms Calculations')

worksheet2.write(0,0,"Room Name",header_format)
worksheet2.write(0,1,"Room Number",header_format)
worksheet2.write(0,2,"Area",header_format)
worksheet2.write(0,3,"Occupancy",header_format)
worksheet2.write(0,4,"Load Factor",header_format)
worksheet2.write(0,5,"No. of Occupants",header_format)

#2️⃣Write Data (+ formatting)

data_format = workbook.add_format({
'border': 1,
'border_color': 'gray',
'align': 'left',
'valign': 'vcenter'})

data = [room_name,room_number,area_value,room_occupancy,room_factor,occupants]

for row,row_data in enumerate(data):
    for col, value in enumerate(row_data):
        if row == 0:
            worksheet2.write(col+1,row,value,data_format)
        else:
            worksheet2.write(col+1,row,value,data_format)

#  ______   __  ____  _____    _  _____  __        _____  ____  _  ______  _   _ _____ _____ _____
# | __ ) \ / / / ___|| ____|  / \|_   _| \ \      / / _ \|  _ \| |/ / ___|| | | | ____| ____|_   _|
# |  _ \\ V /  \___ \|  _|   / _ \ | |    \ \ /\ / / | | | |_) | ' /\___ \| |_| |  _| |  _|   | |
# | |_) || |    ___) | |___ / ___ \| |     \ V  V /| |_| |  _ <| . \ ___) |  _  | |___| |___  | |
# |____/ |_|   |____/|_____/_/   \_\_|      \_/\_/  \___/|_| \_\_|\_\____/|_| |_|_____|_____| |_|

#Get Number of Fixed Seats in a Room

all_furniture=FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Furniture).WhereElementIsNotElementType().ToElements()

fixed_seats=[seat for seat in all_furniture if "FIX_CHR" in seat.Name]

room_seat_counts = defaultdict(int)

for room in by_seat_rooms:
    for seat in fixed_seats:
        if room.IsPointInRoom(seat.Location.Point):
            room_seat_counts[room] += 1

fixed_seat_count=[]
for room, count in room_seat_counts.items():
    fixed_seat_count.append(count)

#List Comprehension to collect Parameters from all By Seat Rooms

room_name      = [room.LookupParameter("Name").AsString() for room in by_seat_rooms]

room_number    = [room.LookupParameter("Number").AsString() for room in by_seat_rooms]

room_occupancy = [room.LookupParameter("Occupancy").AsString() for room in by_seat_rooms]

no_of_seats    = fixed_seat_count

# Create Worksheet
worksheet3 = workbook.add_worksheet('By Fixed Seat')

worksheet3.write(0,0,"Room Name",header_format)
worksheet3.write(0,1,"Room Number",header_format)
worksheet3.write(0,2,"Occupancy",header_format)
worksheet3.write(0,3,"No. of Fixed Seats",header_format)

#2️⃣Write Data (+ formatting)

data_format = workbook.add_format({
'border': 1,
'border_color': 'gray',
'align': 'left',
'valign': 'vcenter'})

data = [room_name,room_number,room_occupancy,no_of_seats]

for row,row_data in enumerate(data):
    for col, value in enumerate(row_data):
        if row == 0:
            worksheet3.write(col+1,row,value,data_format)
        else:
            worksheet3.write(col+1,row,value,data_format)

#  ____    ___     _______  __        _____  ____  _  ______  _   _ _____ _____ _____
# / ___|  / \ \   / / ____| \ \      / / _ \|  _ \| |/ / ___|| | | | ____| ____|_   _|
# \___ \ / _ \ \ / /|  _|    \ \ /\ / / | | | |_) | ' /\___ \| |_| |  _| |  _|   | |
#  ___) / ___ \ V / | |___    \ V  V /| |_| |  _ <| . \ ___) |  _  | |___| |___  | |
# |____/_/   \_\_/  |_____|    \_/\_/  \___/|_| \_\_|\_\____/|_| |_|_____|_____| |_|


# Prompt the user to choose a directory
save_dialog = SaveFileDialog()
save_dialog.Filter = "Excel files (*.xlsx)|*.xlsx"
save_dialog.FileName = "Test.xlsx"

result = save_dialog.ShowDialog()

# Check if the user canceled or closed the dialog
if result == DialogResult.Cancel or result == DialogResult.Abort:
    # Save operation canceled
    selected_filepath = None
else:
    selected_filepath = save_dialog.FileName

    # Check if the file already exists
    if File.Exists(selected_filepath):
        # Ask the user if they want to replace the existing file
        confirm_result = MessageBox.Show(
            "The file already exists. Do you want to replace it?",
            "Confirmation",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question
        )

        if confirm_result == DialogResult.Yes:
            # If the user chooses to replace, delete the existing file
            try:
                File.Delete(selected_filepath)
            except Exception:
                # Handle delete error silently
                selected_filepath = None
                print("Error deleting existing file.")
        else:
            # If the user chooses not to replace, cancel the save operation
            # Save operation canceled
            selected_filepath = None

# Check if the source and destination paths are different before moving
if selected_filepath and xlsx_filepath != selected_filepath:
    # Check if the destination file is open
    try:
        with open(selected_filepath, 'a'):
            pass
    except IOError:
        # File is open
        MessageBox.Show("The file is open. Please close it before saving.", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error)
        selected_filepath = None

    # Move the file only if the user has confirmed the save and the file is not open
    if selected_filepath:
        try:
            import shutil
            shutil.move(xlsx_filepath, selected_filepath)

            # Open the Excel file
            try:
                # Open the Excel file using the default application on Windows
                Process.Start(selected_filepath)
            except Exception:
                # Handle open error silently
                print("Error opening the file.")
        except Exception:
            # Handle move error silently
            print("Error moving the file.")
else:
    # File not moved. Source and destination are the same.
    pass