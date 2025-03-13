import System.Diagnostics

# Specify the file path
pdf_file_path = r"I:\CODES & DETAILS\SBC_2018\SBC_Code_201_2018.pdf"

try:
    # Open the PDF file using the default PDF viewer on Windows
    System.Diagnostics.Process.Start(pdf_file_path)
except Exception as e:
    print("An error occurred: {e}")