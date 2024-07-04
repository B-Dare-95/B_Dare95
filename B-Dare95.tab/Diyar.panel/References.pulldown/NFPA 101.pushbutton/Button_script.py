import System.Diagnostics

# Specify the file path
pdf_file_path = r'Y:\Architectural Public\Mohamed Bedair_AR\101H-18-PDF.pdf'

try:
    # Open the PDF file using the default PDF viewer on Windows
    System.Diagnostics.Process.Start(pdf_file_path)
except Exception as e:
    print("An error occurred: {e}")