import json
import fitz
import re
import unicodedata
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Resume Parser'

class ResumeProcessor:
    default_config = {
    "email_pattern": "[\\w\\.-]+@[\\w\\.-]+",
    "phone_pattern": "\\d{10}",
    "date_pattern1": "\\d{1,2}/\\d{4}\\s*-\\s*\\d{1,2}/\\d{4}",
    "date_pattern2": "\\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) \\d{4}\\s*-\\s*(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) \\d{4}\\b",
    "college_pattern": "(?i).*college.*",
    "school_pattern": "(?i).*school.*",
    "degree_pattern1": "(?i)(?:Bsc|\\bB\\.\\w+|\\bM\\.\\w+|\\bPh\\.D\\.\\w+|\\bBachelor(?:'s)?|\\bMaster(?:'s)?|\\bPh\\.D)\\s(?:\\w+\\s)*\\w+|Pre-University Education|PUC|sslc",
    "degree_pattern2": "(B\\.E\\.\\s.+)"
    }

    def __init__(self, pdf_file_path):
        self.pdf_file_path = pdf_file_path
        self.combined_blocks = []
        self.headers = []
        self.blocks = []
        self.formatted_json = {}
        self.subheads = []
        self.config = self.load_config()

    def load_config(self):
        return self.default_config

    def extract_text_blocks_with_fonts(self):
        pdf_document = fitz.open(self.pdf_file_path)
        for page in pdf_document:
            output = page.get_text("dict")
            for block in output["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"].strip()
                            if text:
                                text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
                                font_info = {
                                    "fontname": span["font"],
                                    "fontsize": span["size"],
                                    "fontcolor": span["color"]
                                }
                                current_block = {
                                    "text": text,
                                    "block_id": block["number"],
                                    "page_number": page.number + 1,
                                    "coordinates": (span["bbox"][0], span["bbox"][1], span["bbox"][2], span["bbox"][3]),
                                    "font_info": font_info,
                                    "header": False,
                                    "subhead": False
                                }
                                self.combined_blocks.append(current_block)
        pdf_document.close()

    def identify_headers(self):
        for index in range(1, len(self.combined_blocks) - 1):
            currentfont_info = self.combined_blocks[index]["font_info"]
            prev_block = self.combined_blocks[index - 1]["font_info"]
            next_block = self.combined_blocks[index + 1]["font_info"]
            text = self.combined_blocks[index]["text"]
            if (currentfont_info["fontsize"] >= prev_block["fontsize"] and
                    currentfont_info["fontsize"] >= next_block["fontsize"]) and \
                    ("Bold" in currentfont_info["fontname"] or "CMBX" in currentfont_info["fontname"] or
                     currentfont_info["fontname"] == "CIDFont+F1"):
                self.combined_blocks[index]["subhead"] = True

            if (currentfont_info["fontsize"] >= prev_block["fontsize"] and
                    currentfont_info["fontsize"] >= next_block["fontsize"]) and \
                    ("Bold" in currentfont_info["fontname"] or "CMBX" in currentfont_info["fontname"] or
                     currentfont_info["fontname"] == "CIDFont+F1") and text.isupper():
                self.combined_blocks[index]["header"] = True
                self.headers.append(self.combined_blocks[index])
            else:
                self.combined_blocks[index]["header"] = False

    def combine_text(self):
        current_block = None
        for block in self.combined_blocks:
            text = block["text"]
            if current_block is not None and block["font_info"]["fontsize"] <= 12 and \
                    block["font_info"]["fontname"] == current_block["font_info"]["fontname"] and \
                    not block["subhead"] and not block["header"]:
                current_block["text"] += " " + text
            else:
                current_block = {
                    "text": text,
                    "font_info": block["font_info"],
                    "header": block["header"],
                    "subhead": block["subhead"]
                }
                self.blocks.append(current_block)

    def format_to_json(self):
        flag = False
        lis = []
        current_header = None
        for block in self.blocks:
            if block["subhead"]:
                self.subheads.append(block["text"])

            if block["header"]:
                flag = True
                current_header = block["text"]
                self.formatted_json[current_header] = []
            elif current_header is not None:
                self.formatted_json[current_header].append(block["text"])

            if not flag:
                lis.append(block["text"])

        email_pattern = self.config["email_pattern"]
        phone_pattern = self.config["phone_pattern"]

        starting_text = ' '.join(lis)
        emails = re.findall(email_pattern, starting_text)
        phones = re.findall(phone_pattern, starting_text)

        if not starting_text:
            for block in self.blocks:
                text = block["text"]
                emails = re.findall(email_pattern, text)
                phones = re.findall(phone_pattern, text)
                if emails:
                    self.formatted_json["email"] = emails[0]
                    break
                if phones:
                    self.formatted_json["phone_no"] = phones[0]
                    break

        if emails:
            self.formatted_json["email"] = emails[0]
        if phones:
            self.formatted_json["phone_no"] = phones[0]

        if lis:
            self.formatted_json["Name"] = lis[0]

    def format_ed(self):
        colleges = []
        degrees = []
        dates = []
        start_date=[]
        end_date=[]
        date_pattern1 = self.config["date_pattern1"]
        date_pattern2 = self.config["date_pattern2"]
        college_pattern = self.config["college_pattern"]
        school_pattern = self.config["school_pattern"]
        degree_pattern1 = self.config["degree_pattern1"]
        degree_pattern2 = self.config["degree_pattern2"]

        ed_key = ""
        for key in self.formatted_json:
            if "education" in key.lower() or "qualification" in key.lower():
                ed_key = key

        for text in self.formatted_json[ed_key]:
            if re.search(college_pattern, text):
                college = re.findall(college_pattern, text)
                colleges.append(college[0])

            if re.search(school_pattern, text):
                school = re.findall(school_pattern, text)
                colleges.append(school[0])

            if re.search(degree_pattern1, text):
                degree = re.findall(degree_pattern1, text)
                degrees.append(degree[0])

            if re.search(degree_pattern2, text):
                degree = re.findall(degree_pattern2, text)
                degrees.append(degree[0])

            if re.search(date_pattern1, text):
                date = re.findall(date_pattern1, text)
                startdate,enddate=date[0].split("-")
                start_date.append(startdate)
                end_date.append(enddate)
                dates.append(date[0])
            if re.search(date_pattern2, text):
                date = re.findall(date_pattern2, text)
                startdate,enddate=date[0].split("-")
                start_date.append(startdate)
                end_date.append(enddate)
                                           
                dates.append(date[0])

        self.formatted_json[ed_key] = []
        for college, degree, date,startdate,enddate in zip(colleges, degrees, dates,start_date,end_date):
            entry = {
                "college_name": college,
                "startdate":startdate,
                "enddate":enddate,
                "degree": degree,
               
            }
            self.formatted_json[ed_key].append(entry)

    def exp_format(self):
        ex_key = ""
        for key in self.formatted_json:
            if "experience" in key.lower() or "work experience" in key.lower():
                ex_key = key
        for text in self.subheads:
            if "," in text:
                self.subheads.remove(text)
        exp = self.formatted_json[ex_key]
        self.formatted_json[ex_key] = []
        lis = []
        for index, text in enumerate(exp):
            if text == ",":
                continue
            if text in self.subheads and lis is not None and not len(lis) == 0:
                self.formatted_json[ex_key].append(lis)
                lis = []
            if index == len(exp) - 1:
                self.formatted_json[ex_key].append(lis)
            lis.append(text)

  
    def process_resume(self):
        self.extract_text_blocks_with_fonts()
        self.identify_headers()
        self.combine_text()
        self.format_to_json()
        self.format_ed()
        for key in self.formatted_json:
            if "experience" in key.lower() or "work experience" in key.lower():
                self.exp_format()
        return self.formatted_json


@app.route('/process_resumes')
def process_resumes():
    # Check if folder_path or pdf_path is provided as a URL parameter
    folder_path = request.args.get('folder_path')
    pdf_path = request.args.get('pdf_path')

    if folder_path and pdf_path:
        return jsonify({"error": "Please provide either folder_path or pdf_path, not both"}), 400

    if folder_path:
        # Get a list of PDF files in the specified folder
        pdf_files = [f for f in os.listdir(folder_path) if f.endswith('.pdf')]

        processed_resumes = []
        for pdf_file in pdf_files:
            pdf_file_path = os.path.join(folder_path, pdf_file)
            processor = ResumeProcessor(pdf_file_path)
            formatted_resume = processor.process_resume()
            processed_resumes.append({pdf_file: formatted_resume})

        return jsonify(processed_resumes)
    elif pdf_path:
        # Process a single PDF file
        processor = ResumeProcessor(pdf_path)
        formatted_resume = processor.process_resume()
        return jsonify({os.path.basename(pdf_path): formatted_resume})
    else:
        return jsonify({"error": "Please provide either folder_path or pdf_path as a URL parameter"}), 400
@app.route('/process_data')
def jsfor():
    data = {
        "name": "mithun",
        "age": 23,
        "role": "data scientist"
    }
    return jsonify(data)

if __name__ == '__main__':
    app.run(debug=True)
