#!/usr/bin/env python3
r"""
# RSON: Restructured Object Notation

RSON is JSON, with a little bit of sugar: Comments, Commas, and Tags.

For example:

```
{
    "numbers": +0123.0,       # Can have leading zeros
    "octal": 0o10,            # Oh, and comments too
    "hex": 0xFF,              #
    "binary": 0b1000_0001,     # Number literals can have _'s 

    "lists": [1,2,3],         # Lists can have trailing commas

    "strings": "At least \x61 \u0061 and \U00000061 work now",
    "or": 'a string',          # both "" and '' work.

    "records": {
        "a": 1,               # Must have unique keys
        "b": 2,               # and the order must be kept
    },
}
```

Along with some sugar atop JSON, RSON supports tagging literals to represent types outside of JSON:

- `@datetime "2017-11-22T23:32:07.100497Z"`, a tagged RFC 3339 datestamp
- `@duration 60` (a duration in seconds, float or int)
- `@base64 "...=="`, a base64 encoded bytestring
- `@set`, `@dict`, `@complex`, `@bytestring`


## JSON in a nutshell:

 - A unicode text file, without a Byte Order Mark
 - Whitespace is `\t`, `\r`, `\n`, `\x20`
 - JSON document is either list, or object
 - Lists are `[]`, `[obj]`, `[ obj, obj ]`, ...
 - Objects: `{ "key": value}`, only string keys
 - Built-ins: `true`, `false`, `null`
 - `"unicode strings"` with escapes `\" \\ \/ \b \f \n \r \t \uFFFF`, and no control codes unecaped.
 - int/float numbers (unary minus, no leading zeros, except for `0.xxx`)
 - No Comments, No Trailing commas

## RSON in a Nutshell

 - File MUST be utf-8, not cesu-8/utf-16/utf-32, without surrogate pairs.
 - Use `#.... <end of line>` for comments
 - Byte Order Mark is treated as whitespace (along with `\x09`, `\x0a`, `\x0d`, `\x20`)
 - RSON Document is any RSON Object, (i.e `1` is a valid RSON file).
 - Lists are `[]`, `[obj]`, `[obj,]`, `[obj, obj]` ... (trailing comma optional)
 - Records are `{ "key": value}`, keys must be unique, order must be preserved. 
 - Built-ins: `true`, `false`, `null`
 - `"unicode strings"` with escapes `\" \\ \/ \b \f \n \r \t \uFFFF`, no control codes unecaped, and `''` can be used instead of `""`.
 - int/float numbers (unary plus or minus, allowleading zeros, hex, octal, and binary integer liters)
 - Tagged literals: `@name [1,2,3]` for any other type of value.


# RSON Object Model and Syntax

RSON has the following types of literals:

 - `null`, `true`, `false`
 - Integers (decimal, binary, octal, hex)
 - Floating Point
 - Strings (using single or double quotes)
 - Lists
 - Records (a JSON object with ordering and without duplicate keys)
 - Tagged Literal

RSON has a number of built-in tags:
 - `@object`, `@bool`, `@int`, `@float`, `@string`, `@list`, `@record`

As well as optional tags for other types:
 - `@bytestring`, or `@base64` for bytestrings
 - `@float "0x0p0"`, for C99 Hex Floating Point Literals
 - `@dict` for unordered key-value maps
 - `@set` for sets, `@complex` for complex numbers
 - `@datetime`, `@duration` for time as point or measurement.

## RSON strings: 

 - use ''s or ""s
 - json escapes, and `\xFF` (as `\u00FF`), `\UFFFFFFFF`  `\'` too
 - `\` at end of line is continuation
 - no surrogate pairs

## RSON numbers:

 - allow unary minus, plus
 - allow leading zero
 - allow underscores (except leading digits)
 - binary ints: `0b1010`
 - octal ints `0o777`
 - hex ints: `0xFF` 

## RSON lists:

 - allow trailing commas

## RSON records (aka, JSON objects):

 - no duplicate keys
 - insertion order must be preserved
 - allow trailing commas
 - implementations MUST support string keys

## RSON tagged objects:

 - `@foo.foo {"foo":1}` name is any unicode letter/digit, `_`or a `.`
 - `@int 1`, `@string "two"` are just `1` and `"two"`
 - do not nest,
 - whitespace between tag name and object is *mandatory*
 - every type has a reserved tag name
 - parsers MAY reject unknown, or return a wrapped object 

### RSON C99 float strings (optional):

 - `@float "0x0p0"` C99 style, sprintf('%a') format
 - `@float "NaN"` or nan,Inf,inf,+Inf,-Inf,+inf,-inf
 -  no underscores allowed

### RSON sets (optional):

 - `@set [1,2,3]`
 - always a tagged list
 - no duplicate items

### RSON dicts (optional):

 - `@dict {"a":1}` 
 - keys must be in lexical order, must round trip in same order.
 - no duplicate items
 - keys must be comparable, hashable, parser MAY reject if not

### RSON datetimes/periods (optional):

 - RFC 3339 format in UTC, (i.e 'Zulu time')
 - `@datetime "2017-11-22T23:32:07.100497Z"`
 - `@duration 60` (in seconds, float or int)
 - UTC MUST be supported, using `Z` suffix
 - implementations should support subset of RFC 3339

### RSON bytestrings (optional):

 - `@bytestring "....\xff"` 
 - `@base64 "...=="`
 - returns a bytestring if possible
 - can't have `\u` `\U` escapes > 0xFF
 - all non printable ascii characters must be escaped: `\xFF`

### RSON complex numbers: (optional)

 - `@complex [0,1]` (real, imaginary)

### Builtin RSON Tags:

Pass throughs (i.e `@foo bar` is `bar`):

 - `@object` on any 
 - `@bool` on true, or false
 - `@int` on ints
 - `@float` on ints or floats
 - `@string` on strings
 - `@list` on lists
 - `@record` on records

Tags that transform the literal:

 - @float on strings (for C99 hex floats, including NaN, -Inf, +Inf)
 - @duration on numbers (seconds)
 - @datetime on strings (utc timestamp)
 - @base64 on strings (into a bytesting)
 - @bytestring on strings (into a bytestring)
 - @set on lists 
 - @complex on lists
 - @dict on records

Reserved:

 - `@unknown`

Any other use of a builtin tag is an error and MUST be rejected.

# RSON Test Vectors

## MUST parse
```
@object null
@bool true
false
0
@float 0.0
-0.0
"test-\x32-\u0032-\U00000032"
'test \" \''
[]
[1,]
{"a":"b",}
```

## MUST not parse

```
_1
0b0123
0o999
0xGHij
@set {}
@dict []
[,]
{"a"}
{"a":1, "a":2}
@object @object {}
"\uD800\uDD01"
```

# Alternate Encodings

## Binary RSON

Note: this is a work-in-progress

This is a simple Type-Length-Value style encoding, similar to bencoding or netstrings:

```
OBJECT :== TRUE | FALSE | NULL |
                INT | FLOAT | BYTES | STRING |
                LIST | RECORD |
                TAG 

TRUE :== 'y'
FALSE :== 'n'
NULL :== 'z'
INT :== 'i' <number encoded as ascii string> '\x7f'
FLOAT :== 'f' <number encoded as hex ascii string> '\x7f'
BYTES :== 'b' <INT as n> '\x7f' <n bytes> `\x7f`
STRING :== 'u' <INT as n> '\x7f' <n bytes of utf-8 encoded string> `\x7f`

LIST :== 'l' <INT as n> <n OBJECTs> `\x7f`
RECORD :== 'r' <INT as n> <2n OBJECTs> `\x7f`
TAG :== 't' <STRING as tag> <OBJECT as value> `\x7f`
```

If a more compact representation is needed, use compression.

Work in Progress:

- Framing (i.e encaptulating in a len-checksum header, like Gob)
- tags for unsigned int8,16,32,64, signed ints
- tags for float32, float64
- tags for ints 0..31
- tags for field/tag definitions header
- tags for [type]/fixed width types

Rough plan: 
```
Tags: 'A..J' 'K..T' 'S..Z'
    unsigned 8,16,32,64, (128,256,512,1024, 2048,4096)
    negative 8,16,32,64, (128,256,512,1024, 2048,4096)
    float 16, 32         (64, 128, 256, 512)
Tags \x00-\x31:
    ints 0-31
Tags >x127:
    Either using leading bit as unary continuation bit,
    Or, UTF-8 style '10'/'11' continuation bits.
```

## Decorated JSON (RSON inside JSON)

- `true`, `false`, `null`, numbers, strings, lists unchanged.
- `{"a":1}` becomes `{'record': ["a", 1]}`
- `@tag {'a':1}` becomes `{'tag', ["a", 1]}`

Note: In this scheme, `@tag ["a",1]` and `@tag {"a":1}` encode to the same JSON, and cannot be distinguished.
"""

import re
import io
import base64
import sys

if sys.version_info.minor > 6 or sys.version_info.minor == 6 and sys.implementation.name == 'cpython':
    OrderedDict = dict
    from collections import namedtuple
else:
    from collections import namedtuple, OrderedDict

from datetime import datetime, timedelta, timezone


CONTENT_TYPE="application/rson"

reserved_tags = set("""
        bool int float complex
        string bytestring base64
        duration datetime
        set list dict record
        object
        unknown
""".split())

whitespace = re.compile(r"(?:\ |\t|\uFEFF|\r|\n|#[^\r\n]*(?:\r?\n|$))+")

int_b2 = re.compile(r"0b[01][01_]*")
int_b8 = re.compile(r"0o[0-7][0-7_]*")
int_b10 = re.compile(r"\d[\d_]*")
int_b16 = re.compile(r"0x[0-9a-fA-F][0-9a-fA-F_]*")

flt_b10 = re.compile(r"\.[\d_]+")
exp_b10 = re.compile(r"[eE](?:\+|-)?[\d+_]")

string_dq = re.compile(
    r'"(?:[^"\\\n\x00-\x1F\uD800-\uDFFF]|\\(?:[\'"\\/bfnrt]|\r?\n|x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}))*"')
string_sq = re.compile(
    r"'(?:[^'\\\n\x00-\x1F\uD800-\uDFFF]|\\(?:[\"'\\/bfnrt]|\r?\n|x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}))*'")

tag_name = re.compile(r"@(?!\d)\w+[ ]+")
identifier = re.compile(r"(?!\d)[\w\.]+")

c99_flt = re.compile(
    r"NaN|nan|[-+]?Inf|[-+]?inf|[-+]?0x[0-9a-fA-F][0-9a-fA-F]*\.[0-9a-fA-F]+[pP](?:\+|-)?[\d]+")

str_escapes = {
    'b': '\b',
    'n': '\n',
    'f': '\f',
    'r': '\r',
    't': '\t',
    '/': '/',
    '"': '"',
    "'": "'",
    '\\': '\\',
}

byte_escapes = {
    'b': b'\b',
    'n': b'\n',
    'f': b'\f',
    'r': b'\r',
    't': b'\t',
    '/': b'/',
    '"': b'"',
    "'": b"'",
    '\\': b'\\',
}

escaped = {
    '\b': '\\b',
    '\n': '\\n',
    '\f': '\\f',
    '\r': '\\r',
    '\t': '\\t',
    '"': '\\"',
    "'": "\\'",
    '\\': '\\\\',
}

builtin_names = {'null': None, 'true': True, 'false': False}
builtin_values = {None: 'null', True: 'true', False: 'false'}

# names -> Classes (take name, value as args)
def parse_datetime(v):
    if v[-1] == 'Z':
        if '.' in v:
            return datetime.strptime(v, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        else:
            return datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    else:
        raise NotImplementedError()


def format_datetime(obj):
    obj = obj.astimezone(timezone.utc)
    return obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

class ParserErr(Exception):
    def __init__(self, buf, pos, reason=None):
        self.buf = buf
        self.pos = pos
        if reason is None:
            nl = buf.rfind(' ', pos - 10, pos)
            if nl < 0:
                nl = pos - 5
            reason = "Unknown Character {} (context: {})".format(
                repr(buf[pos]), repr(buf[pos - 10:pos + 5]))
        Exception.__init__(self, "{} (at pos={})".format(reason, pos))


class Codec:
    content_type = CONTENT_TYPE

    def __init__(self, object_to_tagged, tagged_to_object):
        self.object_to_tagged = object_to_tagged
        self.tagged_to_object = tagged_to_object

    def parse(self, buf, transform=None):
        obj, pos = self.parse_rson(buf, 0, transform)

        m = whitespace.match(buf, pos)
        if m:
            pos = m.end()
            m = whitespace.match(buf, pos)

        if pos != len(buf):
            raise ParserErr(buf, pos, "Trailing content: {}".format(
                repr(buf[pos:pos + 10])))

        return obj


    def dump(self, obj, transform=None):
        buf = io.StringIO('')
        self.dump_rson(obj, buf, transform)
        buf.write('\n')
        return buf.getvalue()

    def parse_rson(self, buf, pos, transform=None):
        m = whitespace.match(buf, pos)
        if m:
            pos = m.end()

        peek = buf[pos]
        name = None
        if peek == '@':
            m = tag_name.match(buf, pos)
            if m:
                pos = m.end()
                name = buf[m.start() + 1:pos].rstrip()
            else:
                raise ParserErr(buf, pos)

        peek = buf[pos]

        if peek == '@':
            raise ParserErr(buf, pos, "Cannot nest tags")

        elif peek == '{':
            if name in reserved_tags:
                if name not in ('object', 'record', 'dict'):
                    raise ParserErr(
                        buf, pos, "{} can't be used on objects".format(name))

            if name == 'dict':
                out = dict()
            else:
                out = OrderedDict()

            pos += 1
            m = whitespace.match(buf, pos)
            if m:
                pos = m.end()

            while buf[pos] != '}':
                key, pos = self.parse_rson(buf, pos, transform)

                if key in out:
                    raise SemanticErr('duplicate key: {}, {}'.format(key, out))

                m = whitespace.match(buf, pos)
                if m:
                    pos = m.end()

                peek = buf[pos]
                if peek == ':':
                    pos += 1
                    m = whitespace.match(buf, pos)
                    if m:
                        pos = m.end()
                else:
                    raise ParserErr(
                        buf, pos, "Expected key:value pair but found {}".format(repr(peek)))

                item, pos = self.parse_rson(buf, pos, transform)

                out[key] = item

                peek = buf[pos]
                if peek == ',':
                    pos += 1
                    m = whitespace.match(buf, pos)
                    if m:
                        pos = m.end()
                elif peek != '}':
                    raise ParserErr(
                        buf, pos, "Expecting a ',', or a '{}' but found {}".format('{}',repr(peek)))
            if name not in (None, 'object', 'record', 'dict'):
                out = self.tagged_to_object(name,  out)
            if transform is not None:
                out = transform(out)
            return out, pos + 1

        elif peek == '[':
            if name in reserved_tags:
                if name not in ('object', 'list', 'set', 'complex'):
                    raise ParserErr(
                        buf, pos, "{} can't be used on lists".format(name))

            if name == 'set':
                out = set()
            else:
                out = []

            pos += 1

            m = whitespace.match(buf, pos)
            if m:
                pos = m.end()

            while buf[pos] != ']':
                item, pos = self.parse_rson(buf, pos, transform)
                if name == 'set':
                    if item in out:
                        raise SemanticErr('duplicate item in set: {}'.format(item))
                    else:
                        out.add(item)
                else:
                    out.append(item)

                m = whitespace.match(buf, pos)
                if m:
                    pos = m.end()

                peek = buf[pos]
                if peek == ',':
                    pos += 1
                    m = whitespace.match(buf, pos)
                    if m:
                        pos = m.end()
                elif peek != ']':
                    raise ParserErr(
                        buf, pos, "Expecting a ',', or a ']' but found {}".format(repr(peek)))

            pos += 1

            if name in (None, 'object', 'list', 'set'):
                pass
            elif name == 'complex':
                out = complex(*out)
            else:
                out = self.tagged_to_object(name,  out)

            if transform is not None:
                out = transform(out)
            return out, pos

        elif peek == "'" or peek == '"':
            if name in reserved_tags:
                if name not in ('object', 'string', 'float', 'datetime', 'bytestring', 'base64'):
                    raise ParserErr(
                        buf, pos, "{} can't be used on strings".format(name))

            if name == 'bytestring':
                s = bytearray()
                ascii = True
            else:
                s = io.StringIO()
                ascii = False

            # validate string
            if peek == "'":
                m = string_sq.match(buf, pos)
                if m:
                    end = m.end()
                else:
                    raise ParserErr(buf, pos, "Invalid single quoted string")
            else:
                m = string_dq.match(buf, pos)
                if m:
                    end = m.end()
                else:
                    raise ParserErr(buf, pos, "Invalid double quoted string")

            lo = pos + 1  # skip quotes
            while lo < end - 1:
                hi = buf.find("\\", lo, end)
                if hi == -1:
                    if ascii:
                        s.extend(buf[lo:end - 1].encode('ascii'))
                    else:
                        s.write(buf[lo:end - 1])  # skip quote
                    break

                if ascii:
                    s.extend(buf[lo:hi].encode('ascii'))
                else:
                    s.write(buf[lo:hi])

                esc = buf[hi + 1]
                if esc in str_escapes:
                    if ascii:
                        s.extend(byte_escapes[esc])
                    else:
                        s.write(str_escapes[esc])
                    lo = hi + 2
                elif esc == 'x':
                    n = int(buf[hi + 2:hi + 4], 16)
                    if ascii:
                        s.append(n)
                    else:
                        s.write(chr(n))
                    lo = hi + 4
                elif esc == 'u':
                    n = int(buf[hi + 2:hi + 6], 16)
                    if ascii:
                        if n > 0xFF:
                            raise ParserErr(
                                buf, hi, 'bytestring cannot have escape > 255')
                        s.append(n)
                    else:
                        if 0xD800 <= n <= 0xDFFF:
                            raise ParserErr(
                                buf, hi, 'string cannot have surrogate pairs')
                        s.write(chr(n))
                    lo = hi + 6
                elif esc == 'U':
                    n = int(buf[hi + 2:hi + 10], 16)
                    if ascii:
                        if n > 0xFF:
                            raise ParserErr(
                                buf, hi, 'bytestring cannot have escape > 255')
                        s.append(n)
                    else:
                        if 0xD800 <= n <= 0xDFFF:
                            raise ParserErr(
                                buf, hi, 'string cannot have surrogate pairs')
                        s.write(chr(n))
                    lo = hi + 10
                elif esc == '\n':
                    lo = hi + 2
                elif (buf[hi + 1:hi + 3] == '\r\n'):
                    lo = hi + 3
                else:
                    raise ParserErr(
                        buf, hi, "Unkown escape character {}".format(repr(esc)))

            if name == 'bytestring':
                out = s
            else:
                out = s.getvalue()

                if name in (None, 'string', 'object'):
                    pass
                elif name == 'base64':
                    try:
                        out = base64.standard_b64decode(out)
                    except Exception as e:
                        raise ParserErr(buf, pos, "Invalid base64") from e
                elif name == 'datetime':
                    try:
                        out = parse_datetime(out)
                    except Exception as e:
                        raise ParserErr(
                            buf, pos, "Invalid datetime: {}".format(repr(out))) from e
                elif name == 'float':
                    m = c99_flt.match(out)
                    if m:
                        out = float.fromhex(out)
                    else:
                        raise ParserErr(
                            buf, pos, "invalid C99 float literal: {}".format(out))
                else:
                    out = self.tagged_to_object(name,  out)

            if transform is not None:
                out = transform(out)
            return out, end

        elif peek in "-+0123456789":
            if name in reserved_tags:
                if name not in ('object', 'int', 'float', 'duration'):
                    raise ParserErr(
                        buf, pos, "{} can't be used on numbers".format(name))

            flt_end = None
            exp_end = None

            sign = +1

            if buf[pos] in "+-":
                if buf[pos] == "-":
                    sign = -1
                pos += 1
            peek = buf[pos:pos + 2]

            if peek in ('0x', '0o', '0b'):
                if peek == '0x':
                    base = 16
                    m = int_b16.match(buf, pos)
                    if m:
                        end = m.end()
                    else:
                        raise ParserErr(
                            buf, pos, "Invalid hexadecimal number (0x...)")
                elif peek == '0o':
                    base = 8
                    m = int_b8.match(buf, pos)
                    if m:
                        end = m.end()
                    else:
                        raise ParserErr(buf, pos, "Invalid octal number (0o...)")
                elif peek == '0b':
                    base = 2
                    m = int_b2.match(buf, pos)
                    if m:
                        end = m.end()
                    else:
                        raise ParserErr(
                            buf, pos, "Invalid hexadecimal number (0x...)")

                out = sign * int(buf[pos + 2:end].replace('_', ''), base)
            else:
                m = int_b10.match(buf, pos)
                if m:
                    int_end = m.end()
                    end = int_end
                else:
                    raise ParserErr(buf, pos, "Invalid number")

                t = flt_b10.match(buf, end)
                if t:
                    flt_end = t.end()
                    end = flt_end

                e = exp_b10.match(buf, end)
                if e:
                    exp_end = e.end()
                    end = exp_end

                if flt_end or exp_end:
                    out = sign * float(buf[pos:end].replace('_', ''))
                else:
                    out = sign * int(buf[pos:end].replace('_', ''), 10)

            if name is None or name == 'object':
                pass
            elif name == 'duration':
                out = timedelta(seconds=out)
            elif name == 'int':
                if flt_end or exp_end:
                    raise ParserErr(
                        buf, pos, "Can't tag floating point with @int")
            elif name == 'float':
                if not isintance(out, float):
                    out = float(out)
            else:
                out = self.tagged_to_object(name, out)

            if transform is not None:
                out = transform(out)
            return out, end

        else:
            m = identifier.match(buf, pos)
            if m:
                end = m.end()
                item = buf[pos:end]
            else:
                raise ParserErr(buf, pos)

            if item not in builtin_names:
                raise ParserErr(
                    buf, pos, "{} is not a recognised built-in".format(repr(item)))

            out = builtin_names[item]

            if name is None or name == 'object':
                pass
            elif name == 'bool':
                if item not in ('true', 'false'):
                    raise ParserErr(buf, pos, '@bool can only true or false')
            elif name in reserved_tags:
                raise ParserErr(
                    buf, pos, "{} has no meaning for {}".format(repr(name), item))
            else:
                out = self.tagged_to_object(name,  out)

            if transform is not None:
                out = transform(out)
            return out, end

        raise ParserErr(buf, pos)



    def dump_rson(self, obj, buf, transform=None):
        if transform:
            obj = transform(obj)
        if obj is True or obj is False or obj is None:
            buf.write(builtin_values[obj])
        elif isinstance(obj, str):
            buf.write('"')
            for c in obj:
                if c in escaped:
                    buf.write(escaped[c])
                elif ord(c) < 0x20:
                    buf.write('\\x{:02X}'.format(ord(c)))
                else:
                    buf.write(c)
            buf.write('"')
        elif isinstance(obj, int):
            buf.write(str(obj))
        elif isinstance(obj, float):
            hex = obj.hex()
            if hex.startswith(('0', '-')):
                buf.write(str(obj))
            else:
                buf.write('@float "{}"'.format(hex))
        elif isinstance(obj, complex):
            buf.write("@complex [{}, {}]".format(obj.real, obj.imag))
        elif isinstance(obj, (bytes, bytearray)):
            buf.write('@base64 "')
            # assume no escaping needed
            buf.write(base64.standard_b64encode(obj).decode('ascii'))
            buf.write('"')
        elif isinstance(obj, (list, tuple)):
            buf.write('[')
            first = True
            for x in obj:
                if first:
                    first = False
                else:
                    buf.write(", ")
                self.dump_rson(x, buf, transform)
            buf.write(']')
        elif isinstance(obj, set):
            buf.write('@set [')
            first = True
            for x in obj:
                if first:
                    first = False
                else:
                    buf.write(", ")
                self.dump_rson(x, buf, transform)
            buf.write(']')
        elif isinstance(obj, OrderedDict): # must be before dict
            buf.write('{')
            first = True
            for k, v in obj.items():
                if first:
                    first = False
                else:
                    buf.write(", ")
                self.dump_rson(k, buf, transform)
                buf.write(": ")
                self.dump_rson(v, buf, transform)
            buf.write('}')
        elif isinstance(obj, dict):
            buf.write('@dict {')
            first = True
            for k in sorted(obj.keys()):
                if first:
                    first = False
                else:
                    buf.write(", ")
                self.dump_rson(k, buf, transform)
                buf.write(": ")
                self.dump_rson(obj[k], buf, transform)
            buf.write('}')
        elif isinstance(obj, datetime):
            buf.write('@datetime "{}"'.format(format_datetime(obj)))
        elif isinstance(obj, timedelta):
            buf.write('@duration {}'.format(obj.total_seconds()))
        else:
            nv = self.object_to_tagged(obj)
            name, value = nv
            if not isinstance(value, OrderedDict) and isinstance(value, dict):
                value = OrderedDict(value)
            buf.write('@{} '.format(name))
            self.dump_rson(value, buf, transform)  # XXX: prevent @foo @foo
        


class BinaryCodec:
    """
        just enough of a type-length-value scheme to be dangerous

    """
    TRUE = ord("y")
    FALSE = ord("n")
    NULL = ord("z")
    INT = ord("i")
    FLOAT = ord("f")
    STRING = ord("u")
    BYTES = ord("b")
    LIST = ord("l")
    RECORD = ord("r")
    TAG = ord("t")
    END = 127

    def __init__(self, object_to_tagged, tagged_to_object):
        self.tags = object_to_tagged
        self.classes = tagged_to_object

    def parse(self, buf):
        obj, offset = self.parse_buf(buf, 0)
        return obj

    def dump(self, obj):
        return self.dump_buf(obj, bytearray())

    def parse_buf(self, buf, offset=0):
        peek = buf[offset]
        if peek == self.TRUE:
            return True, offset+1
        elif peek == self.FALSE:
            return False, offset+1
        elif peek == self.NULL:
            return None, offset+1
        elif peek == self.INT:
            end = buf.index(self.END, offset+1)
            obj = buf[offset+1:end].decode('ascii')
            return int(obj), end+1
        elif peek == self.FLOAT:
            end = buf.index(self.END, offset+1)
            obj = buf[offset+1:end].decode('ascii')
            return float.fromhex(obj), end+1
        elif peek == self.BYTES:
            size, end = self.parse_buf(buf, offset+1)
            start, end = end, end+size
            obj = buf[start:end]
            end = buf.index(self.END, end)
            return obj, end+1
        elif peek == self.STRING:
            size, end = self.parse_buf(buf, offset+1)
            start, end = end, end+size
            obj = buf[start:end].decode('utf-8')
            end = buf.index(self.END, end)
            return obj, end+1
        elif peek == self.LIST:
            size, start = self.parse_buf(buf, offset+1)
            out = []
            for _ in range(size):
                value, start = self.parse_buf(buf, start)
                out.append(value)
            end = buf.index(self.END, start)
            return out, end+1
        elif peek == self.RECORD:
            size, start = self.parse_buf(buf, offset+1)
            out = {}
            for _ in range(size):
                key, start = self.parse_buf(buf, start)
                value, start = self.parse_buf(buf, start)
                out[key] = value

            end = buf.index(self.END, start)
            return out, end+1
        elif peek == self.TAG:
            tag, start = self.parse_buf(buf, offset+1)
            value, start = self.parse_buf(buf, start)
            end = buf.index(self.END, start)
            if tag == 'set':
                out = set(value)
            elif tag == 'complex':
                out = complex(*value)
            elif tag == 'datetime':
                out = parse_datetime(value)
            elif tag == 'duration':
                out = timedelta(seconds=value)
            else:
                cls = self.classes[tag]
                out = cls(**value)
            return out, end+1


        raise Exception('bad buf {}'.format(peek.encode('ascii')))


    def dump_buf(self, obj, buf):
        if obj is True:
            buf.append(self.TRUE)
        elif obj is False:
            buf.append(self.FALSE)
        elif obj is None:
            buf.append(self.NULL)
        elif isinstance(obj, int):
            buf.append(self.INT)
            buf.extend(str(obj).encode('ascii'))
            buf.append(self.END)
        elif isinstance(obj, float):
            buf.append(self.FLOAT)
            buf.extend(float.hex(obj).encode('ascii'))
            buf.append(self.END)
        elif isinstance(obj, (bytes,bytearray)):
            buf.append(self.BYTES)
            self.dump_buf(len(obj), buf)
            buf.extend(obj)
            buf.append(self.END)
        elif isinstance(obj, (str)):
            obj = obj.encode('utf-8')
            buf.append(self.STRING)
            self.dump_buf(len(obj), buf)
            buf.extend(obj)
            buf.append(self.END)
        elif isinstance(obj, (list, tuple)):
            buf.append(self.LIST)
            self.dump_buf(len(obj), buf)
            for x in obj:
                self.dump_buf(x, buf)
            buf.append(self.END)
        elif isinstance(obj, (dict)):
            buf.append(self.RECORD)
            self.dump_buf(len(obj), buf)
            for k,v in obj.items():
                self.dump_buf(k, buf)
                self.dump_buf(v, buf)
            buf.append(self.END)
        elif isinstance(obj, (set)):
            buf.append(self.TAG)
            self.dump_buf("set", buf)
            buf.append(self.LIST)
            self.dump_buf(len(obj), buf)
            for x in obj:
                self.dump_buf(x, buf)
            buf.append(self.END)
            buf.append(self.END)
        elif isinstance(obj, complex):
            buf.append(self.TAG)
            self.dump_buf("complex", buf)
            buf.append(self.LIST)
            self.dump_buf(2, buf)
            self.dump_buf(obj.real, buf)
            self.dump_buf(obj.imag, buf)
            buf.append(self.END)
            buf.append(self.END)
        elif isinstance(obj, datetime):
            buf.append(self.TAG)
            self.dump_buf("datetime", buf)
            self.dump_buf(format_datetime(obj), buf)
            buf.append(self.END)
        elif isinstance(obj, timedelta):
            buf.append(self.TAG)
            self.dump_buf("duration", buf)
            self.dump_buf(obj.total_seconds(), buf)
            buf.append(self.END)

        elif obj.__class__ in self.tags:
            tag = self.tags[obj.__class__].encode('ascii')
            buf.append(self.TAG)
            self.dump_buf(tag, buf)
            self.dump_buf(obj.__dict__, buf)
            buf.append(self.END)
        else:
            raise Exception('bad obj {!r}'.format(obj))
        return buf


if __name__ == '__main__':
    codec = Codec(None, None)
    bcodec = BinaryCodec({},{})

    parse = codec.parse
    dump = codec.dump

    bparse = bcodec.parse
    bdump = bcodec.dump

    def test_parse(buf, obj):
        out = parse(buf)

        if (obj != obj and out == out) or (obj == obj and obj != out):
            raise AssertionError('{} != {}'.format(obj, out))

    def test_dump(obj, buf):
        out = dump(obj)
        if buf != out:
            raise AssertionError('{} != {}'.format(buf, out))

    def test_parse_err(buf, exc):
        try:
            obj = parse(buf)
        except Exception as e:
            if isinstance(e, exc):
                return
            else:
                raise AssertionError(
                    '{} did not cause {}, but {}'.format(buf, exc, e)) from e
        else:
            raise AssertionError(
                '{} did not cause {}, parsed:{}'.format(buf, exc, obj))


    def test_dump_err(obj, exc):
        try:
            buf = dump(obj)
        except Exception as e:
            if isinstance(e, exc):
                return
            else:
                raise AssertionError(
                    '{} did not cause {}, but '.format(obj, exc, e))
        else:
            raise AssertionError(
                '{} did not cause {}, dumping: {}'.format(obj, exc, buf))


    test_parse("0", 0)
    test_parse("0x0_1_2_3", 0x123)
    test_parse("0o0_1_2_3", 0o123)
    test_parse("0b0_1_0_1", 5)
    test_parse("0 #comment", 0)
    test_parse("""
"a\\
b"        
    """, "ab")
    test_parse("0.0", 0.0)
    test_parse("-0.0", -0.0)
    test_parse("'foo'", "foo")
    test_parse(r"'fo\no'", "fo\no")
    test_parse("'\\\\'", "\\")
    test_parse(r"'\b\f\r\n\t\"\'\/'", "\b\f\r\n\t\"\'/")
    test_parse("''", "")
    test_parse(r'"\x20"', " ")
    test_parse(r'"\uF0F0"', "\uF0F0")
    test_parse(r'"\U0001F0F0"', "\U0001F0F0")
    test_parse("'\\\\'", "\\")
    test_parse("[1]", [1])
    test_parse("[1,]", [1])
    test_parse("[]", [])
    test_parse("[1 , 2 , 3 , 4 , 4 ]", [1, 2, 3, 4, 4])
    test_parse("{'a':1,'b':2}", dict(a=1, b=2))
    test_parse("@set [1,2,3,4]", set([1, 2, 3, 4]))
    test_parse("{'a':1,'b':2}", dict(a=1, b=2))
    test_parse("@complex [1,2]", 1 + 2j)
    test_parse("@bytestring 'foo'", b"foo")
    test_parse("@base64 '{}'".format(
        base64.standard_b64encode(b'foo').decode('ascii')), b"foo")
    test_parse("@float 'NaN'", float('NaN'))
    test_parse("@float '-inf'", float('-Inf'))
    obj = datetime.now().astimezone(timezone.utc)
    test_parse('@datetime "{}"'.format(
        obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")), obj)
    obj = timedelta(seconds=666)
    test_parse('@duration {}'.format(obj.total_seconds()), obj)
    test_parse("@bytestring 'fo\x20o'", b"fo o")
    test_parse("@float '{}'".format((3000000.0).hex()), 3000000.0)
    test_parse(hex(123), 123)
    test_parse('@object "foo"', "foo")
    test_parse('@object 12', 12)

    test_dump(1, "1")

    test_parse_err('"foo', ParserErr)
    test_parse_err('"\uD800\uDD01"', ParserErr)
    test_parse_err(r'"\uD800\uDD01"', ParserErr)

    tests = [
        0, -1, +1,
        -0.0, +0.0, 1.9,
        True, False, None,
        "str", b"bytes",
        [1, 2, 3], {"c": 3, "a": 1, "b": 2, }, set(
            [1, 2, 3]), OrderedDict(a=1, b=2),
        1 + 2j, float('NaN'),
        datetime.now().astimezone(timezone.utc),
        timedelta(seconds=666),
    ]

    for obj in tests:
        buf0 = dump(obj)
        obj1 = parse(buf0)
        buf1 = dump(obj1)

        out = parse(buf1)

        if obj != obj:
            if buf0 != buf1 or obj1 == obj1 or out == out:
                raise AssertionError('{} != {}'.format(obj, out))
        else:
            if buf0 != buf1:
                raise AssertionError(
                    'mismatched output {} != {}'.format(buf0, buf1))
            if obj != obj1:
                raise AssertionError(
                    'failed first trip {} != {}'.format(obj, obj1))
            if obj != out:
                raise AssertionError(
                    'failed second trip {} != {}'.format(obj, out))

    for obj in tests:
        buf0 = bdump(obj)
        obj1 = bparse(buf0)
        buf1 = bdump(obj1)

        out = bparse(buf1)

        if obj != obj:
            if buf0 != buf1 or obj1 == obj1 or out == out:
                raise AssertionError('{} != {}'.format(obj, out))
        else:
            if buf0 != buf1:
                raise AssertionError(
                    'mismatched output {} != {}'.format(buf0, buf1))
            if obj != obj1:
                raise AssertionError(
                    'failed first trip {} != {}'.format(obj, obj1))
            if obj != out:
                raise AssertionError(
                    'failed second trip {} != {}'.format(obj, out))
    print('tests passed')


