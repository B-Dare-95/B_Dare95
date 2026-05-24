import os
import time
import threading
import subprocess
import clr
import System

# Load .NET Framework assemblies
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("Microsoft.VisualBasic")

from System.Windows.Forms import (
    Application, Form, Button, TextBox, Label, FolderBrowserDialog,
    MessageBox, MessageBoxButtons, MessageBoxIcon, Clipboard, DialogResult, FormStartPosition
)
from System.Drawing import Size, Point
from System.Drawing.Imaging import ImageFormat
from Microsoft.VisualBasic import Interaction, CallType


# ==========================================
# COM LATE-BINDING HELPERS
# ==========================================
def com_get(obj, prop_name, *args):
    return Interaction.CallByName(obj, prop_name, CallType.Get, *args)


def com_set(obj, prop_name, value):
    Interaction.CallByName(obj, prop_name, CallType.Set, value)


def com_call(obj, method_name, *args):
    return Interaction.CallByName(obj, method_name, CallType.Method, *args)


# ==========================================
# SETTINGS
# ==========================================
SNIPASTE_PATH = os.path.join(
    os.environ["LOCALAPPDATA"],
    "Microsoft",
    "WindowsApps",
    "Snipaste.exe"
)

# ==========================================
# SELECT FOLDER
# ==========================================
folder_dialog = FolderBrowserDialog()
folder_dialog.Description = "Select where to save Issue Logger.xlsx"

if folder_dialog.ShowDialog() != DialogResult.OK:
    import sys

    sys.exit("No folder selected.")

save_folder = folder_dialog.SelectedPath
excel_path = os.path.join(save_folder, "Issue Logger.xlsx")


# ==========================================
# MAIN UI (WinForms)
# ==========================================
class IssueLogger(Form):
    def __init__(self):
        self.Text = "Issue Logger"
        self.Size = Size(500, 300)
        self.StartPosition = FormStartPosition.CenterScreen

        # Comment Label
        self.lbl = Label()
        self.lbl.Text = "Write your comment:"
        self.lbl.Location = Point(20, 20)
        self.lbl.Size = Size(200, 20)
        self.Controls.Add(self.lbl)

        # Comment Textbox
        self.txt = TextBox()
        self.txt.Multiline = True
        self.txt.Location = Point(20, 50)
        self.txt.Size = Size(440, 120)
        self.Controls.Add(self.txt)

        # Take Screenshot Button
        self.btn_snip = Button()
        self.btn_snip.Text = "Take Screenshot"
        self.btn_snip.Location = Point(70, 200)
        self.btn_snip.Size = Size(150, 40)
        self.btn_snip.Click += self.take_screenshot
        self.Controls.Add(self.btn_snip)

        # Save Issue Button
        self.btn_save = Button()
        self.btn_save.Text = "Save Issue"
        self.btn_save.Location = Point(260, 200)
        self.btn_save.Size = Size(150, 40)
        self.btn_save.Click += self.save_issue
        self.Controls.Add(self.btn_save)

    def take_screenshot(self, sender, e):
        self.Opacity = 0.0
        time.sleep(0.2)

        process = subprocess.Popen([SNIPASTE_PATH, "snip"])

        def watch_snipaste():
            process.wait()

            def restore_ui():
                self.Opacity = 1.0

            self.Invoke(System.Action(restore_ui))

        t = threading.Thread(target=watch_snipaste)
        t.daemon = True
        t.start()

    def save_issue(self, sender, e):
        comment = self.txt.Text.strip()

        if not comment:
            MessageBox.Show("Please enter a comment.", "Error", MessageBoxButtons.OK, MessageBoxIcon.Error)
            return

        if not Clipboard.ContainsImage():
            MessageBox.Show(
                "No image found in clipboard.\n\nPlease take a screenshot with Snipaste first.",
                "Error", MessageBoxButtons.OK, MessageBoxIcon.Error
            )
            return

        img = Clipboard.GetImage()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        images_folder = os.path.join(save_folder, "Issue_Images")
        if not os.path.exists(images_folder):
            os.makedirs(images_folder)

        excel_type = System.Type.GetTypeFromProgID("Excel.Application")
        excel_app = System.Activator.CreateInstance(excel_type)

        try:
            com_set(excel_app, "Visible", False)
            com_set(excel_app, "DisplayAlerts", False)

            workbooks = com_get(excel_app, "Workbooks")

            if os.path.exists(excel_path):
                wb = com_call(workbooks, "Open", excel_path)
            else:
                wb = com_call(workbooks, "Add")

            worksheets = com_get(wb, "Worksheets")
            ws = com_get(worksheets, "Item", 1)

            # Explicitly get the master collections first
            cells = com_get(ws, "Cells")
            rows = com_get(ws, "Rows")
            columns = com_get(ws, "Columns")

            if not os.path.exists(excel_path):
                com_set(ws, "Name", "Issues")
                # Use .Item to access specific cells
                com_set(com_get(cells, "Item", 1, 1), "Value2", "Timestamp")
                com_set(com_get(cells, "Item", 1, 2), "Value2", "Comment")
                com_set(com_get(cells, "Item", 1, 3), "Value2", "Screenshot")

            row_count = com_get(rows, "Count")
            start_cell = com_get(cells, "Item", row_count, 1)
            end_cell = com_get(start_cell, "End", -4162)
            last_row = com_get(end_cell, "Row")

            val_a1 = com_get(com_get(cells, "Item", 1, 1), "Value2")

            next_row = last_row + 1 if val_a1 else 1
            if next_row == 1 and val_a1 == "Timestamp":
                next_row = 2

            image_filename = "issue_{0}.png".format(next_row)
            image_path = os.path.join(images_folder, image_filename)
            img.Save(image_path, ImageFormat.Png)

            com_set(com_get(cells, "Item", next_row, 1), "Value2", timestamp)
            com_set(com_get(cells, "Item", next_row, 2), "Value2", comment)

            rng = com_get(cells, "Item", next_row, 3)
            rng_left = com_get(rng, "Left")
            rng_top = com_get(rng, "Top")

            shapes = com_get(ws, "Shapes")

            # 0 = False (LinkToFile), -1 = True (SaveWithDocument)
            com_call(shapes, "AddPicture", image_path, 0, -1, rng_left, rng_top, 300, 170)

            # Format using .Item
            com_set(com_get(rows, "Item", next_row), "RowHeight", 140)
            com_set(com_get(columns, "Item", 1), "ColumnWidth", 22)
            com_set(com_get(columns, "Item", 2), "ColumnWidth", 50)
            com_set(com_get(columns, "Item", 3), "ColumnWidth", 45)

            if os.path.exists(excel_path):
                com_call(wb, "Save")
            else:
                com_call(wb, "SaveAs", excel_path)

            com_call(wb, "Close", -1)  # -1 is COM True for SaveChanges

        finally:
            com_call(excel_app, "Quit")

        self.txt.Text = ""
        MessageBox.Show("Issue saved successfully.", "Saved", MessageBoxButtons.OK, MessageBoxIcon.Information)


# ==========================================
# RUN APP
# ==========================================
if __name__ == "__main__":
    Application.EnableVisualStyles()
    form = IssueLogger()
    form.ShowDialog()