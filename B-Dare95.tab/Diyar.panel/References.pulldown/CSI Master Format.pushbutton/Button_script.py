import System.Diagnostics

# Specify the file path
pdf_file_path = r'Y:\Architectural Public\Mohamed Bedair_AR\MasterFormat 2016 Edition_ Numbers and Titles.pdf'

try:
    # Open the PDF file using the default PDF viewer on Windows
    System.Diagnostics.Process.Start(pdf_file_path)
except Exception as e:
    print("An error occurred: {e}")