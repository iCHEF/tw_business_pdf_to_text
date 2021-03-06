# -*- coding: utf-8 -*-
import re
import sys
from collections import OrderedDict

import pandas
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.layout import LTContainer
from pdfminer.layout import LTText
from pdfminer.layout import LTTextBox
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfpage import PDFPage

NEED_BUSINESS_ID = ["F501060", "F501030", "F501990", "F501050", "F203020", "C104020"]


class My(TextConverter):

    word = ""
    group = []
    word_pos_info = {}

    def receive_layout(self, ltpage):
        def render(item):
            if isinstance(item, LTContainer):
                for child in item:
                    render(child)
            elif isinstance(item, LTText):
                if self.word == "":
                    if "x0" in dir(item):
                        self.word_pos_info = {"x0": item.x0, "y1": item.y0}
                if item.get_text() == " " or item.get_text() == "\n":  # 將空白也判斷成下一個句子
                    self.word_pos_info.update({"content": self.word.strip()})
                    self.group.append(self.word_pos_info.copy())
                    self.word_pos_info = {}
                    self.word = ""
                else:
                    self.word += item.get_text()

            if isinstance(item, LTTextBox):
                split_data_list = self.word.strip().split("\n")
                for split_data_index in range(len(split_data_list)):
                    self.word_pos_info = {"x0": item.x0, "y1": item.y0 + split_data_index*10}
                    self.word_pos_info.update({"content": split_data_list[split_data_index]})
                    self.group.append(self.word_pos_info.copy())
                self.word_pos_info = {}
                self.word = ""
        render(ltpage)
        return

    def reset(self):
        self.word = ""
        self.group = []
        self.word_pos_info = {}


def find_match_string(string):
    pattern = re.compile(r"(?P<id>[A-Z0-9]{7})", flags=re.MULTILINE)
    for match in pattern.finditer(string):
        if match.groupdict()["id"] in NEED_BUSINESS_ID:
            return True
    return False


def read_pdf_data(filename):
    fp = open(filename, "rb")

    rsrcmgr = PDFResourceManager()
    laparams = LAParams()
    laparams.line_margin = 0.01
    device = My(rsrcmgr, sys.stdout, laparams=laparams)
    device.reset()
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    result_data = []
    count = 0
    for page in PDFPage.get_pages(fp, set()):
        # if count != 9:
        #     count += 1
        #     continue
        interpreter.process_page(page)
        result_data.append(device.group)
        device.word = ""
        device.group = []
        device.word_pos_info = {}
        count += 1

    fp.close()
    return result_data


def get_row_group(data, row_name):
    _temp = data[row_name].value_counts()
    # 將大於7的list，當作是正常的，有可能因為名字或者其他因素造成多切
    group_list = _temp[_temp >= 10].index.tolist()
    group_list.sort()
    group_list.insert(0, 0)
    group_list.insert(len(group_list), group_list[-1] + 100)
    return group_list


def get_column_groups():
    return [0, 40.00, 90.0, 175.0, 295.0, 360.0, 520.0, 600.0, 655.0, 800]


def index_keys_dict():
    return OrderedDict([
        ("(0, 40]", 0),
        ("(40, 90]", 1),
        ("(90, 175]", 2),
        ("(175, 295]", 3),
        ("(295, 360]", 4),
        ("(360, 520]", 5),
        ("(520, 600]", 6),
        ("(600, 655]", 7),
        ("(655, 800]", 8)])


def main(filename):
    pdf_data_list = read_pdf_data(filename)
    final_data = pandas.DataFrame()
    for pdf_single_data in pdf_data_list:
        pdf_data = pandas.DataFrame(pdf_single_data)
        # parsing enter alphabet
        pdf_data["content"] = pdf_data["content"].str.replace("\n", "")
        # y must be 24.412 <= y1 <= 522.309
        pdf_data = pdf_data[ (pdf_data.y1>24.412) & (pdf_data.y1<=522.309) ]
        pdf_data = pdf_data.reset_index(drop=True)
        pdf_data["column"] = -1
        pdf_data["row"] = -1

        pdf_data = pdf_data.sort_values(["x0", "y1"], ascending=[1, 0]).reset_index(drop=True)
        x_group = pdf_data.groupby(pandas.cut(pdf_data["x0"], get_column_groups()))
        column_group_dict = x_group.groups.items()

        for key, column_group in column_group_dict:
            pdf_data.loc[column_group, "column"] = key

        # 這裡做的事情是保證順序一致，因為cut會導致index的順序亂掉，這邊會調整回來
        # unique_string_list = pdf_data["column"].unique()
        # for idx, list_value in enumerate(unique_string_list):
        #     pdf_data = pdf_data.replace({list_value: idx})
        group_list = get_row_group(pdf_data, "y1")
        y_group = pdf_data.groupby(pandas.cut(pdf_data["y1"], group_list))
        row_group_list = y_group.groups.values()

        for idx, row_group in enumerate(row_group_list):
            pdf_data.loc[row_group, "row"] = idx

        # pdf_data = pdf_data[pdf_data["column"] < 100]
        pdf_data = pdf_data.drop(["x0", "y1"], axis=1)
        pdf_data["content"] = pdf_data["content"].map(lambda x: "%s" % x)

        gby_data = pdf_data.groupby(["row", "column"]).sum().unstack("column")

        gby_data.index = range(gby_data.shape[0])

        # gby_data.columns = range(gby_data.shape[1])
        result_list = []
        for column_list in  gby_data.columns.levels:
            if len(column_list) == gby_data.shape[1]:
                result_list = column_list
        gby_data.columns = result_list
        for column_key, column_value in index_keys_dict().items():
            if column_key in gby_data:
                gby_data = gby_data.rename(columns={column_key: column_value})
            else:
                gby_data[column_value] = ""
        gby_data = gby_data.dropna()
        if gby_data.shape[1] >= 8:
            gby_data = gby_data[(gby_data[0] != u"序號") & (gby_data[0] != 0)]
            gby_data["is_ok"] = gby_data[8].map(lambda x: find_match_string(x))
            final_data = final_data.append(gby_data)

    if final_data.empty is False:
        final_data[0] = pandas.to_numeric(final_data[0], errors="ignore")
        final_data = final_data.sort_values([0])
        final_data = final_data.reset_index(drop=True)
        final_data.to_csv("%s.csv" % filename, encoding="utf8", index=False)

if __name__ == "__main__":
    main("376570000Asetup10505.pdf")
