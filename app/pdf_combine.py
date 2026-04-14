from PyPDF2 import PdfMerger

def combine_pdfs(pdf_list, output_path: str):
    merger = PdfMerger()
    for pdf in pdf_list:
        if hasattr(pdf, "seek"):
            pdf.seek(0)
            merger.append(pdf)
        else:
            merger.append(str(pdf))
    merger.write(output_path)
    merger.close()