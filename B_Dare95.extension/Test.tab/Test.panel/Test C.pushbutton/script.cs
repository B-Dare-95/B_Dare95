using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;
using Excel = Microsoft.Office.Interop.Excel;

namespace IssueLogger
{
    public class IssueLoggerForm : Form
    {
        private TextBox txtComment;
        private Button btnSnip;
        private Button btnSave;
        private Label lblComment;

        private readonly string saveFolder;
        private readonly string excelPath;
        private readonly string imagesFolder;

        private readonly string snipastePath =
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Microsoft",
                "WindowsApps",
                "Snipaste.exe"
            );

        public IssueLoggerForm(string folder)
        {
            saveFolder = folder;
            excelPath = Path.Combine(saveFolder, "Issue Logger.xlsx");
            imagesFolder = Path.Combine(saveFolder, "Issue_Images");

            InitializeUI();
        }

        private void InitializeUI()
        {
            Text = "Issue Logger";
            Size = new Size(500, 300);
            StartPosition = FormStartPosition.CenterScreen;

            lblComment = new Label
            {
                Text = "Write your comment:",
                Location = new Point(20, 20),
                Size = new Size(200, 20)
            };

            txtComment = new TextBox
            {
                Multiline = true,
                Location = new Point(20, 50),
                Size = new Size(440, 120)
            };

            btnSnip = new Button
            {
                Text = "Take Screenshot",
                Location = new Point(70, 200),
                Size = new Size(150, 40)
            };

            btnSave = new Button
            {
                Text = "Save Issue",
                Location = new Point(260, 200),
                Size = new Size(150, 40)
            };

            btnSnip.Click += TakeScreenshot;
            btnSave.Click += SaveIssue;

            Controls.Add(lblComment);
            Controls.Add(txtComment);
            Controls.Add(btnSnip);
            Controls.Add(btnSave);
        }

        private async void TakeScreenshot(object sender, EventArgs e)
        {
            try
            {
                Opacity = 0;

                await Task.Delay(200);

                Process process = Process.Start(new ProcessStartInfo
                {
                    FileName = snipastePath,
                    Arguments = "snip",
                    UseShellExecute = true
                });

                if (process != null)
                {
                    await Task.Run(() => process.WaitForExit());
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    $"Failed to launch Snipaste.\n\n{ex.Message}",
                    "Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
            finally
            {
                Opacity = 1;
            }
        }

        private void SaveIssue(object sender, EventArgs e)
        {
            string comment = txtComment.Text.Trim();

            if (string.IsNullOrWhiteSpace(comment))
            {
                MessageBox.Show(
                    "Please enter a comment.",
                    "Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );

                return;
            }

            if (!Clipboard.ContainsImage())
            {
                MessageBox.Show(
                    "No image found in clipboard.\n\nPlease take a screenshot first.",
                    "Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );

                return;
            }

            if (!Directory.Exists(imagesFolder))
            {
                Directory.CreateDirectory(imagesFolder);
            }

            Image image = Clipboard.GetImage();

            string timestamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");

            Excel.Application excelApp = null;
            Excel.Workbook workbook = null;
            Excel.Worksheet worksheet = null;

            try
            {
                excelApp = new Excel.Application
                {
                    Visible = false,
                    DisplayAlerts = false
                };

                bool fileExists = File.Exists(excelPath);

                if (fileExists)
                {
                    workbook = excelApp.Workbooks.Open(excelPath);
                }
                else
                {
                    workbook = excelApp.Workbooks.Add();
                }

                worksheet = (Excel.Worksheet)workbook.Worksheets[1];

                if (!fileExists)
                {
                    worksheet.Name = "Issues";

                    worksheet.Cells[1, 1] = "Timestamp";
                    worksheet.Cells[1, 2] = "Comment";
                    worksheet.Cells[1, 3] = "Screenshot";
                }

                int nextRow = worksheet.Cells[
                    worksheet.Rows.Count,
                    1
                ].End[Excel.XlDirection.xlUp].Row + 1;

                if (nextRow == 2 &&
                    worksheet.Cells[1, 1].Value == null)
                {
                    nextRow = 1;
                }

                string imageFilename = $"issue_{nextRow}.png";
                string imagePath = Path.Combine(imagesFolder, imageFilename);

                image.Save(imagePath, ImageFormat.Png);

                worksheet.Cells[nextRow, 1] = timestamp;
                worksheet.Cells[nextRow, 2] = comment;

                Excel.Range imageCell = worksheet.Cells[nextRow, 3];

                float left = (float)(double)imageCell.Left;
                float top = (float)(double)imageCell.Top;

                worksheet.Shapes.AddPicture(
                    imagePath,
                    Microsoft.Office.Core.MsoTriState.msoFalse,
                    Microsoft.Office.Core.MsoTriState.msoTrue,
                    left,
                    top,
                    300,
                    170
                );

                worksheet.Rows[nextRow].RowHeight = 140;

                worksheet.Columns[1].ColumnWidth = 22;
                worksheet.Columns[2].ColumnWidth = 50;
                worksheet.Columns[3].ColumnWidth = 45;

                if (fileExists)
                {
                    workbook.Save();
                }
                else
                {
                    workbook.SaveAs(excelPath);
                }

                txtComment.Clear();

                MessageBox.Show(
                    "Issue saved successfully.",
                    "Saved",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information
                );
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    $"Error saving issue:\n\n{ex.Message}",
                    "Error",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
            }
            finally
            {
                if (workbook != null)
                {
                    workbook.Close(true);
                }

                if (excelApp != null)
                {
                    excelApp.Quit();
                }

                ReleaseObject(worksheet);
                ReleaseObject(workbook);
                ReleaseObject(excelApp);
            }
        }

        private void ReleaseObject(object obj)
        {
            try
            {
                if (obj != null)
                {
                    System.Runtime.InteropServices.Marshal.ReleaseComObject(obj);
                }
            }
            catch
            {
                // Ignore COM cleanup errors
            }
            finally
            {
                obj = null;
            }
        }

        [STAThread]
        public static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            using (FolderBrowserDialog dialog = new FolderBrowserDialog())
            {
                dialog.Description = "Select where to save Issue Logger.xlsx";

                if (dialog.ShowDialog() != DialogResult.OK)
                {
                    return;
                }

                Application.Run(new IssueLoggerForm(dialog.SelectedPath));
            }
        }
    }
}