from typing import Any
from pdfminer.layout import LTFigure
from pdfminer.layout import LTTextBox
from pdfminer.layout import LTTextLine
from pdfminer.layout import LTTextBoxHorizontal
from pdfminer.layout import LTTextLineHorizontal
from pdfminer.layout import LTLine
from pdfminer.layout import LTRect
from pdfminer.layout import LTImage
from pdfminer.layout import LTCurve
from pdfminer.layout import LTChar
from pdfminer.layout import LTLine
import binascii
import re


class Pile(object):
    def __init__(self):
        self.verticals = []
        self.horizontals = []
        self.texts = []
        self.images = []
        self._SEARCH_DISTANCE = 1.0

    def __bool__(self):
        return bool(self.texts)

    def get_type(self):
        if self.verticals:
            return 'table'
        elif self.images:
            return 'image'
        else:
            return 'paragraph'

    def parse_layout(self, layout):
        obj_stack = list(reversed(list(layout)))
        while obj_stack:
            obj = obj_stack.pop()
            if type(obj) in [LTFigure, LTTextBox, LTTextLine, LTTextBoxHorizontal]:
                obj_stack.extend(reversed(list(obj)))
            elif type(obj) == LTTextLineHorizontal:
                try:
                    if len(list(obj)):
                        font = font
                        obj.bold = "Bold" in font
                        obj.italic = "Italic" in font or "Oblique" in font
                        obj.font = font
                except:
                    obj.font = None
                    obj.bold = None
                    obj.italic = None

                obj.chars = len(list(obj))
                obj.size = round(obj.height, 0)
                self.texts.append(obj)
                
            elif type(obj) == LTRect:
                if obj.width < 1.0:
                    self._adjust_to_close(obj, self.verticals, 'x0')
                    self.verticals.append(obj)
                elif obj.height < 1.0:
                    self._adjust_to_close(obj, self.horizontals, 'y0')
                    self.horizontals.append(obj)
            elif type(obj) == LTImage:
                self.images.append(obj)
            elif type(obj) == LTCurve:
                pass
            elif type(obj) == LTChar:
                pass
            elif type(obj) == LTLine:
                pass
            else:
                assert False, "Unrecognized type: %s" % type(obj)

    def split_piles(self):
        tables = self._find_tables()
        paragraphs = self._find_paragraphs(tables)
        images = self._find_images()

        try:
            piles = sorted(tables + paragraphs + images, reverse=True,
                    key=lambda x: x._get_anything().y0)
        except:
            piles = []

        return piles

    def gen_markdown(self, syntax):
        pile_type = self.get_type()
        if pile_type == 'paragraph':
            return self._gen_paragraph_markdown(syntax)
        elif pile_type == 'table':
            return self._gen_table_markdown(syntax)
        elif pile_type == 'image':
            return self._gen_image_markdown()
        else:
            raise Exception('Unsupported markdown type')

    def gen_html(self):
        html = ''

        page_height = 800  # for flipping the coordinate

        html += '<meta charset="utf8" />'
        html += '<svg width="100%" height="100%">'

        # flip coordinate
        html += '<g transform="translate(0, {}) scale(1, -1)">'.format(
            page_height)

        rect = '<rect width="{width}" height="{height}" x="{x}" y="{y}" fill="{fill}"><title>{text}</title></rect>'

        for text in self.texts:
            info = {
                'width': text.x1 - text.x0,
                'height': text.y1 - text.y0,
                'x': text.x0,
                'y': text.y0,
                # 'text': text.get_text().encode('utf8'),
                'text': text.get_text(),
                'fill': 'green',
            }
            html += rect.format(**info)

        for vertical in self.verticals:
            info = {
                'width': 1,
                'height': vertical.y1 - vertical.y0,
                'x': vertical.x0,
                'y': vertical.y0,
                'text': '',
                'fill': 'blue',
            }
            html += rect.format(**info)

        for horizontal in self.horizontals:
            info = {
                'width': horizontal.x1 - horizontal.x0,
                'height': 1,
                'x': horizontal.x0,
                'y': horizontal.y0,
                'text': '',
                'fill': 'red',
            }
            html += rect.format(**info)

        html += '</g>'
        html += '</svg>'

        return html

    def get_image(self):
        if not self.images:
            raise Exception('No images here')
        return self.images[0]

    def _adjust_to_close(self, obj, lines, attr):
        obj_coor = getattr(obj, attr)
        close = None
        for line in lines:
            line_coor = getattr(line, attr)
            if abs(obj_coor - line_coor) < self._SEARCH_DISTANCE:
                close = line
                break

        if not close:
            return

        if attr == 'x0':
            new_bbox = (close.bbox[0], obj.bbox[1], close.bbox[2], obj.bbox[3])
        elif attr == 'y0':
            new_bbox = (obj.bbox[0], close.bbox[1], obj.bbox[2], close.bbox[3])
        else:
            raise Exception('No such attr')
        obj.set_bbox(new_bbox)

    def _find_tables(self):
        tables = []
        visited = set()
        for vertical in self.verticals:
            if vertical in visited:
                continue

            near_verticals = self._find_near_verticals(
                vertical, self.verticals)
            top, bottom = self._calc_top_bottom(near_verticals)
            included_horizontals = self._find_included(
                top, bottom, self.horizontals)
            included_texts = self._find_included(top, bottom, self.texts)

            table = Pile()
            table.verticals = near_verticals
            table.horizontals = included_horizontals
            table.texts = included_texts

            tables.append(table)
            visited.update(near_verticals)
        return tables

    def _find_paragraphs(self, tables):
        tops = []
        for table in tables:
            top, bottom = self._calc_top_bottom(table.verticals)
            tops.append(top)

        tops.append(float('-inf'))  # for the last part of paragraph

        all_table_texts = set()
        for table in tables:
            all_table_texts.update(table.texts)

        num_slots = len(tables) + 1
        paragraphs = [Pile() for idx in range(num_slots)]
        for text in self.texts:
            if text in all_table_texts:
                continue
            for idx, top in enumerate(tops):
                if text.y0 > top:
                    paragraphs[idx].texts.append(text)
                    break

        paragraphs = [_f for _f in paragraphs if _f]

        return paragraphs

    def _find_images(self):
        images = []
        for image in self.images:
            pile = Pile()
            pile.images.append(image)
            images.append(pile)
        return images

    def _get_anything(self):
        if self.texts:
            return self.texts[0]
        if self.images:
            return self.images[0]
        raise Exception('The pile contains nothing')

    def _is_overlap(self, top, bottom, obj):
        assert top > bottom
        return (bottom - self._SEARCH_DISTANCE) <= obj.y0 <= (top + self._SEARCH_DISTANCE) or \
            (bottom - self._SEARCH_DISTANCE) <= obj.y1 <= (top + self._SEARCH_DISTANCE)

    def _calc_top_bottom(self, objects):
        top = float('-inf')
        bottom = float('inf')
        for obj in objects:
            top = max(top, obj.y1)
            bottom = min(bottom, obj.y0)
        return top, bottom

    def _find_near_verticals(self, start, verticals):
        near_verticals = [start]
        top = start.y1
        bottom = start.y0
        for vertical in verticals:
            if vertical == start:
                continue
            if self._is_overlap(top, bottom, vertical):
                near_verticals.append(vertical)
                top, bottom = self._calc_top_bottom(near_verticals)
        return near_verticals

    def _find_included(self, top, bottom, objects):
        included = []
        for obj in objects:
            if self._is_overlap(top, bottom, obj):
                included.append(obj)
        return included

    def _gen_paragraph_markdown(self, syntax):
        markdown = ''
        prevtext = ''

        font_names: set[Any] = {char.fontname for line in self.texts for char in line._objs if isinstance(char, LTChar)} 
        font_sizes: set[float] = {round(char.size,0) for line in self.texts for char in line._objs if isinstance(char, LTChar)}
        max_font_size: float = max(font_sizes)
        min_font_size: float = min(font_sizes)

        for text in self.texts:
            pattern = syntax.pattern(text)
            newline = syntax.newline(text)
            content = syntax.purify(text)

            is_bold: bool = any('Bold' in name or 'Black' in name for name in font_names)
            # print(f'<< {content}')

            # markdown = re.sub(r'\n\s(\d+.\d+.)', r'\n\1', markdown)
            
            
            if 'heading' in pattern:
                if prevtext.startswith('#'):
                    markdown += '\n'
            
            if pattern == 'none':
                if prevtext.startswith('#'):
                    markdown += '\n'
            #     continue
            # elif pattern.startswith('heading'):
            #     lead = '#' * int(pattern[-1])
            #     if prevtext.startswith(lead):
            #         markdown += ' ' + content
            #     else:
            #         markdown += '\n' + lead + ' ' + content
            # elif pattern.startswith('plain-text'):
            #     markdown += ' ' + content + ' '
            # elif pattern.endswith('list-item'):
            #     lead = '\n#####' if pattern.startswith('ordered') else ' ' # '-'
            #     markdown += lead + ' ' + content
            # else:
            #     raise Exception('Unsupported syntax pattern')
            
            if text.get_text().isupper() and re.match(r'^(\s|)\d+\.', text.get_text()) : 
                markdown += f"## {text.get_text()}"
            elif text.get_text().isupper() and text.size == max_font_size or\
                text.get_text().isupper() and is_bold: 
                markdown += f"# {text.get_text()}"
            elif is_bold and re.match(r'^Раздел ', text.get_text()) or \
                    is_bold and text.size > min_font_size and re.match(r'^(\s|)\d+\.\s', text.get_text()):
                markdown += f"### {text.get_text()}"
            elif re.match(r'^(\s|)(\d+\.){2}(\s{1}|\s{0}$)', text.get_text()):
                markdown += f"#### {text.get_text()}"
            elif is_bold and text.size > min_font_size and re.match(r'^\D+–', text.get_text()):
                markdown += f"- {text.get_text()}"
            elif re.match(r'^\d+\.\d+\.\d+.', text.get_text()):
                markdown += f"- {text.get_text()}"
            else:
                markdown += text.get_text()

            if newline:
                # markdown.strip()
                # markdown = '\n' + markdown + '\n'
                markdown += '\n'

            prevtext = markdown.split('\n')[-1]

        ###
        # Удаляет цифру в конце строки, если затем идет перенос строки
        markdown = re.sub(r'[^\d+]\d{1,2}\s+\n', '\n', markdown)        
        markdown = re.sub(r'[^\d+]\d{1,2}\s+\n$', '\n', markdown)
        # Удаление случаев, когда есть пробел, перенос строки, и сразу за переносом идет маленькая буква
        markdown = re.sub(r'\ +', ' ', markdown)
        markdown = re.sub('\n{2,10}', '\n', markdown)
        markdown = re.sub(r"", ">", markdown)
        markdown = re.sub(r" \n(?=[а-я0-9\(\«)])", " ", markdown)
        markdown = re.sub(r"(?<=[\–]) \n(?=[А-Я\(\-])", " ", markdown)
        markdown = re.sub(r"(?<=[\>\-]) \n", " ", markdown)
        # Удаление переноса строки между строками, начинающимися с '# '
        markdown = re.sub(r'\n#(?=\s)', '', markdown)
        # Удаление переноса строки где он идет сразу после установки пунктов (1., 1.2)
        markdown = re.sub(r'(\#{1}\s(\d+\.){0,3}\s)\n', r'\1', markdown)
        markdown = re.sub(r'\sстр. \d+ из', '', markdown) 

        # Дальнейшие правила для обработки текста
        # text = re.sub(r'(?<!\.\n)(?<!\n\n)(?<!\.\s)\n(?=[A-ZА-Я])', ' ', text)
        ###
        # markdown = markdown.strip()
        # print(f'>>>\n{markdown}')
        return markdown

    def _gen_table_markdown(self, syntax):
        intermediate = self._gen_table_intermediate()
        return self._intermediate_to_markdown(intermediate)

    def _gen_image_markdown(self):
        image = self.get_image()
        return '![{0}](images/{0})\n\n'.format(image.name)

    def average_close_numbers(self, arr, closeness):
        result = []
        temp = []
        for num in sorted(arr):
            if temp and abs(temp[-1] - num) > closeness:
                result.append(sum(temp) / len(temp))
                temp = []
            temp.append(num)
        if temp:
            result.append(sum(temp) / len(temp))
        return result

    def _gen_table_intermediate(self):
        # self.verticals =[obj for obj in self.verticals if obj.height >= 1 or obj.width >= 1]
        self.verticals = [obj for obj in self.verticals if obj.height >= 1 or obj.width >= 1] \
            if isinstance(self.verticals, list) else None
        vertical_coor = self._calc_coordinates(self.verticals, 'x0', False)
        horizontal_coor = self._calc_coordinates(self.horizontals, 'y0', True)

        vertical_coor = self.average_close_numbers(vertical_coor, 2)

        # for el in self.verticals:
        #     for coor in vertical_coor:
        #         if self.is_in_range(el.x0, coor):
        #             el.x0 = coor
        #         if self.is_in_range(el.x1, coor):
        #             el.x1 = coor
        #     for coor in horizontal_coor:
        #         if self.is_in_range(el.y0, coor):
        #             el.y0 = coor
        #         if self.is_in_range(el.y1, coor):
        #             el.y1 = coor
        # for el in self.horizontals:
        #     for coor in vertical_coor:
        #         if self.is_in_range(el.x0, coor):
        #             el.x0 = coor
        #         if self.is_in_range(el.x1, coor):
        #             el.x1 = coor
        #     for coor in horizontal_coor:
        #         if self.is_in_range(el.y0, coor):
        #             el.y0 = coor
        #         if self.is_in_range(el.y1, coor):
        #             el.y1 = coor

        # Проверим логически невидимые Вертикальные линии по краям таблицы, при наличии добавим их, для этого посмотрим выходят ли горизонтальные линии дальше вертикальных (Т)
        if len(self.horizontals):
            ly0 = 0
            ly1 = 0
            ry0 = 0
            ry1 = 0
            lx = min(self._calc_coordinates(self.horizontals, 'x0', True))
            rx = max(self._calc_coordinates(self.horizontals, 'x1', True))

            if not len(vertical_coor):
                vertical_coor = [(lx + rx)/2]

            for coor in self.horizontals:
                if not (lx > coor.x0 - self._SEARCH_DISTANCE or rx < coor.x1 + self._SEARCH_DISTANCE):
                    continue
                if coor.x0 < min(vertical_coor) - self._SEARCH_DISTANCE:
                    if ly0 and ly1:
                        new_object = LTRect(linewidth=0,
                                            bbox=(round(lx, 3), ly0, round(lx + self._SEARCH_DISTANCE/2, 3), round(coor.y1, 3)),
                                            stroke=False)
                        self.verticals.append(new_object)
                    ly0 = round(coor.y0, 3)
                    ly1 = round(coor.y1, 3)
                if coor.x1 > max(vertical_coor) + self._SEARCH_DISTANCE:
                    if ry0 and ry1:
                        new_object = LTRect(linewidth=0,
                                            bbox=(round(rx, 3), ry0, round(rx + self._SEARCH_DISTANCE/2, 3), round(coor.y1, 3)),
                                            stroke=False)
                        self.verticals.append(new_object)
                    ry0 = round(coor.y0, 3)
                    ry1 = round(coor.y1, 3)

            # self.verticals.sort(key=lambda t: t.x0)
            # self.horizontals.sort(key=lambda t: (t.y0, -t.x0))

            vertical_coor = self._calc_coordinates(self.verticals, 'x0', False)
            horizontal_coor = self._calc_coordinates(self.horizontals, 'y0', True)

        num_rows = len(horizontal_coor) - 1
        num_cols = len(vertical_coor) - 1

        # print(f'V.coor: {vertical_coor}, H.coor: {horizontal_coor}')
        # print(f'Rows: {num_rows}, Cols: {num_cols}')

        intermediate = [[] for idx in range(num_rows)]
        for row_idx in range(num_rows):
            for col_idx in range(num_cols):
                left = vertical_coor[col_idx]
                top = horizontal_coor[row_idx]
                right = vertical_coor[col_idx + 1]
                bottom = horizontal_coor[row_idx + 1]

                assert top > bottom

                if self._is_ignore_cell(left, top, right, bottom):
                    continue

                right, colspan = self._find_exist_coor(
                    bottom + self._SEARCH_DISTANCE, top - self._SEARCH_DISTANCE, col_idx, vertical_coor, 'vertical')
                bottom, rowspan = self._find_exist_coor(
                    left + self._SEARCH_DISTANCE, right - self._SEARCH_DISTANCE, row_idx, horizontal_coor, 'horizontal')

                if rowspan == 0:
                    rowspan = 1
                    colspan = num_cols
                    right = rx

                cell = {}
                cell['texts'] = self._find_cell_texts(left, top, right, bottom)
                if colspan > 1:
                    cell['colspan'] = colspan
                if rowspan > 1:
                    cell['rowspan'] = rowspan

                intermediate[row_idx].append(cell)

        return intermediate

    def _find_cell_texts(self, left, top, right, bottom):
        texts = []
        for text in self.texts:
            if self._in_range(left, top, right, bottom, text):
                texts.append(text)
        return texts

    def _in_range(self, left, top, right, bottom, obj):
        return (left - self._SEARCH_DISTANCE) <= obj.x0 < obj.x1 <= (right + self._SEARCH_DISTANCE) and \
            (bottom - self._SEARCH_DISTANCE) <= obj.y0 < obj.y1 <= (top + self._SEARCH_DISTANCE)

    def _is_ignore_cell(self, left, top, right, bottom):
        left_exist = self._line_exists(left, bottom, top, 'vertical')
        top_exist = self._line_exists(top, left, right, 'horizontal')
        return not left_exist or not top_exist

    def _find_exist_coor(self, minimum, maximum, start_idx, line_coor, direction):
        span = 0
        line_exist = False
        while not line_exist:
            span += 1
            # Если достигли конца массива и не нашли подходящей линии,
            # возвращаем элемент сразу за start_idx и span равным 1.
            if len(line_coor) == start_idx + span:
                return line_coor[start_idx + 1], 1
            coor = line_coor[start_idx + span]
            line_exist = self._line_exists(coor, minimum, maximum, direction)

        if direction == 'horizontal' and len(line_coor) == start_idx + span + 1:  # ??????
            return line_coor[start_idx + 1], 1

        # Если линия найдена, возвращаем ее координаты и span
        return coor, span

    # def _find_exist_coor(self, minimum, maximum, start_idx, line_coor, direction):
    #     span = 0
    #     line_exist = False
    #     while not line_exist and start_idx + span < len(line_coor):
    #         coor = line_coor[start_idx + span]
    #         line_exist = self._line_exists(coor, minimum, maximum, direction)
    #         if not line_exist:
    #             span += 1
    #
    #     if not line_exist:
    #         # Здесь должна быть логика обработки ситуации,
    #         # когда подходящая координата так и не была найдена.
    #         return None, span
    #
    #     return coor, span

    def _line_exists(self, target, minimum, maximum, direction):
        if direction == 'vertical':
            lines = self.verticals
            attr = 'x0'
            fill_range = self._fill_vertical_range
        elif direction == 'horizontal':
            lines = self.horizontals
            attr = 'y0'
            fill_range = self._fill_horizontal_range
        else:
            raise Exception('No such direction')

        for line in lines:
            if getattr(line, attr) != target:
                continue
            if fill_range(minimum, maximum, line):
                return True

        return False

    def _fill_vertical_range(self, bottom, top, obj):
        assert top > bottom
        return obj.y0 <= (bottom + self._SEARCH_DISTANCE) and (top - self._SEARCH_DISTANCE) <= obj.y1

    def _fill_horizontal_range(self, left, right, obj):
        return obj.x0 <= (left + self._SEARCH_DISTANCE) and (right - self._SEARCH_DISTANCE) <= obj.x1

    def _intermediate_to_markdown(self, intermediate):
        markdown = '\n'
        markdown += self._create_tag('table', True, 0)
        for row in intermediate:
            markdown += self._create_tag('tr', True, 1)
            for cell in row:
                markdown += self._create_td_tag(cell)
            markdown += self._create_tag('tr', False, 1)
        markdown += self._create_tag('table', False, 0)
        markdown += '\n'

        # # Regular expression pattern for matching empty table rows.
        # pattern = r"<tr(.*)>\s+<td><\/td>\s+<\/tr>\n"
        # # Substitute the empty rows with an empty string.
        # markdown = re.sub(pattern, '', markdown)

        return markdown

    def _create_tag(self, tag_name, start, level):
        indent = '\t' * level
        slash = '' if start else '/'
        center = ' align="center"' if start else ''
        return indent + '<' + slash + tag_name + center + '>\n'

    def _create_td_tag(self, cell):
        indent = '\t' * 2
        texts = [text.get_text().strip() for text in cell['texts']]
        # texts = [text.get_text().encode('utf8').strip() for text in cell['texts']]
        texts = ' '.join(texts)
        colspan = ' colspan={}'.format(
            cell['colspan']) if 'colspan' in cell else ''
        rowspan = ' rowspan={}'.format(
            cell['rowspan']) if 'rowspan' in cell else ''
        return indent + '<td' + colspan + rowspan + '>' + texts + '</td>\n'

    def _calc_coordinates(self, axes, attr, reverse):
        coor_set = set()
        for axis in axes:
            # coor_set.add(getattr(axis, attr))
            coor_set.add(round(getattr(axis, attr), 3))
        coor_list = list(coor_set)
        coor_list.sort(reverse=reverse)
        return coor_list
