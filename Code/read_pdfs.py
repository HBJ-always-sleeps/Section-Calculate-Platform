import subprocess
import os
import sys

# Try to extract text from PDFs using pdfplumber or PyPDF2
try:
    import pdfplumber
    use_pdfplumber = True
except:
    use_pdfplumber = False

try:
    import PyPDF2
    use_pypdf2 = True
except:
    use_pypdf2 = False

dir_path = r"C:\Users\训教\Desktop\师带徒"
files = os.listdir(dir_path)

output_lines = []

# Read 一季度师带徒材料 PDF
pdf1 = None
for f in files:
    if '一季度' in f and f.endswith('.pdf'):
        pdf1 = os.path.join(dir_path, f)
        break

if pdf1 and use_pdfplumber:
    output_lines.append("=== 一季度师带徒材料 ===")
    with pdfplumber.open(pdf1) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                output_lines.append(f"\n--- Page {i+1} ---")
                output_lines.append(text)
elif pdf1 and use_pypdf2:
    output_lines.append("=== 一季度师带徒材料 (PyPDF2) ===")
    with open(pdf1, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                output_lines.append(f"\n--- Page {i+1} ---")
                output_lines.append(text)

# Read 新员工成长记录本 PDF
pdf2 = None
for f in files:
    if '成长记录本' in f and f.endswith('.pdf'):
        pdf2 = os.path.join(dir_path, f)
        break

if pdf2 and use_pdfplumber:
    output_lines.append("\n\n=== 新员工成长记录本 ===")
    with pdfplumber.open(pdf2) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                output_lines.append(f"\n--- Page {i+1} ---")
                output_lines.append(text)

# Write output
output_path = os.path.join(dir_path, 'pdf_content.txt')
with open(output_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines))

print(f"PDF content written to: {output_path}")
print(f"pdfplumber: {use_pdfplumber}, PyPDF2: {use_pypdf2}")
