"""
pydyf − Low-level PDF generator

"""

from codecs import BOM_UTF16_BE
import sys

VERSION = __version__ = '0.0.1'


def _to_data(item):
    if isinstance(item, bytes):
        return item
    elif isinstance(item, Object):
        return item.data
    elif isinstance(item, float) and item.as_integer_ratio()[1] == 1:
        item = int(item)
    return str(item).encode('ascii')


class Object:
    def __init__(self):
        self.number = None
        self.offset = 0
        self.generation = 0
        self.free = 'n'
        self._indirect = None

    @property
    def indirect(self):
        return b'\n'.join((
            f'{self.number} {self.generation} obj'.encode('ascii'),
            self.data,
            b'endobj',
        ))

    @property
    def reference(self):
        return f'{self.number} {self.generation} R'

    @property
    def data(self):
        raise NotImplementedError()


class Dictionary(Object, dict):
    def __init__(self, values=None):
        Object.__init__(self)
        dict.__init__(self, values or {})

    @property
    def data(self):
        result = [b'<<']
        for key, value in self.items():
            result.append(b'/' + _to_data(key) + b' ' + _to_data(value))
        result.append(b'>>')
        return b'\n'.join(result)


class Stream(Object):
    def __init__(self, stream=None, extra=None):
        super().__init__()
        self.stream = stream or []
        self.extra = extra or {}

    def begin_text(self):
        self.stream.append('BT')

    def clip(self, even_odd=False):
        self.stream.append('W*' if even_odd else 'W')

    def close(self):
        self.stream.append('h')

    def curve_to(self, x1, y1, x2, y2, x3, y3):
        self.stream.append(f'{x1} {y1} {x2} {y2} {x3} {y3} c')

    def end(self):
        self.stream.append('n')

    def end_text(self):
        self.stream.append('ET')

    def fill(self, even_odd=False):
        self.stream.append('f*' if even_odd else 'f')

    def fill_and_stroke(self, even_odd=False):
        self.stream.append('B*' if even_odd else 'B')

    def fill_stroke_and_close(self, even_odd=False):
        self.stream.append('b*' if even_odd else 'b')

    def line_to(self, x, y):
        self.stream.append(f'{x} {y} l')

    def move_to(self, x, y):
        self.stream.append(f'{x} {y} m')

    def pop_state(self):
        self.stream.append('Q')

    def push_state(self):
        self.stream.append('q')

    def rectangle(self, x, y, width, height):
        self.stream.append(f'{x} {y} {width} {height} re')

    def set_color_rgb(self, r, g, b, stroke=False):
        self.stream.append(f'{r} {g} {b} RG' if stroke else f'{r} {g} {b} rg')

    def set_dash(self, dash_array, dash_phase):
        self.stream.append(
            f'{Array(dash_array).data.decode("ascii")} {dash_phase} d')

    def set_font_size(self, font, size):
        self.stream.append(f'/{font} {size} Tf')

    def set_line_width(self, width):
        self.stream.append(f'{width} w')

    def set_state(self, state_name):
        self.stream.append(f'/{state_name} gs')

    def show_text(self, text):
        self.stream.append(f'[{text}] TJ')

    def stroke(self):
        self.stream.append('S')

    def stroke_and_close(self):
        self.stream.append('s')

    def text_matrix(self, a, b, c, d, e, f):
        self.stream.append(f'{a} {b} {c} {d} {e} {f} Tm')

    def transform(self, a, b, c, d, e, f):
        self.stream.append(f'{a} {b} {c} {d} {e} {f} cm')

    @property
    def data(self):
        stream = b'\n'.join(_to_data(item) for item in self.stream)
        extra = Dictionary(self.extra.copy())
        extra['Length'] = len(stream) + 1
        return b'\n'.join((extra.data, b'stream', stream, b'endstream'))


class String(Object):
    def __init__(self, string=''):
        super().__init__()
        self.string = string

    @property
    def data(self):
        try:
            return b'(' + _to_data(self.string) + b')'
        except UnicodeEncodeError:
            encoded = BOM_UTF16_BE + str(self.string).encode('utf-16-be')
            return b'<' + encoded.hex().encode('ascii') + b'>'


class Array(Object, list):
    def __init__(self, array=None):
        Object.__init__(self)
        list.__init__(self, array or [])

    @property
    def data(self):
        result = [b'[']
        for child in self:
            result.append(_to_data(child))
        result.append(b']')
        return b' '.join(result)


class PDF:
    def __init__(self):
        self.objects = []

        zero_object = Object()
        zero_object.generation = 65535
        zero_object.free = 'f'
        zero_object._indirect = ''
        self.add_object(zero_object)

        self.pages = Dictionary({
            'Type': '/Pages',
            'Kids': Array([]),
            'Count': 0,
        })
        self.add_object(self.pages)

        self.info = Dictionary({})
        self.add_object(self.info)

        self.catalog = Dictionary({
            'Type': '/Catalog',
            'Pages': self.pages.reference,
        })
        self.add_object(self.catalog)

        self.current_position = 0
        self.xref_position = None

    def add_page(self, page):
        self.pages['Count'] += 1
        self.add_object(page)
        self.pages['Kids'].extend([page.number, 0, 'R'])

    def add_object(self, object_):
        object_.number = len(self.objects)
        self.objects.append(object_)

    def write_line(self, content, output):
        self.current_position += len(content) + 1
        output.write(content + b'\n')

    def write_object(self, object_, output):
        for line in object_.data.split(b'\n'):
            self.write_line(line, output)

    def write_header(self, output):
        self.write_line(b'%PDF-1.7', output)

    def write_body(self, output):
        for object_ in self.objects:
            if object_.free == 'f':
                continue
            object_.offset = self.current_position
            self.write_line(object_.indirect, output)

    def write_cross_reference_table(self, output):
        self.xref_position = self.current_position
        self.write_line(b'xref', output)
        self.write_line(f'0 {len(self.objects)}'.encode('ascii'), output)
        for object_ in self.objects:
            self.write_line(
                (f'{object_.offset:010} {object_.generation:05} '
                 f'{object_.free} ').encode('ascii'), output
            )

    def write_trailer(self, output):
        self.write_line(b'trailer', output)
        self.write_object(Dictionary({
            'Size': len(self.objects),
            'Root': self.catalog.reference,
            'Info': self.info.reference,
        }), output)
        self.write_line(b'startxref', output)
        self.write_line(str(self.xref_position).encode('ascii'), output)
        self.write_line(b'%%EOF', output)

    def write(self, output=sys.stdout.buffer):
        self.write_header(output)
        self.write_body(output)
        self.write_cross_reference_table(output)
        self.write_trailer(output)
