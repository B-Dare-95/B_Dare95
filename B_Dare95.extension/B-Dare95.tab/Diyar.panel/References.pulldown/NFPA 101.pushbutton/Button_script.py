# -*- coding: utf-8 -*-

import System.Diagnostics

# Specify the file path
pdf_file_path = r"I:\CODE-Practice\NFPA++\NFPA 101 2021  Life Safety Code.pdf"

try:
    # Open the PDF file using the default PDF viewer on Windows
    System.Diagnostics.Process.Start(pdf_file_path)
except Exception as e:
    print("An error occurred: {e}")