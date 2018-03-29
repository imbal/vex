#!/usr/bin/env python3

import io
import os
import sys
import time
import types
import itertools
import subprocess


ARGTYPES=[x.strip() for x in """
    bool boolean
    int integer
    float num number
    str string
    scalar
    infile outfile
""".split() if x]
#   stretch goals: rwfile jsonfile textfile

def parse_argspec(argspec):
    """
        argspec is a short description of a command's expected args:
        "x y z"         three args (x,y,z) in that order
        "x [y] [z]"       three args, where the second two are optional. 
                        "arg1 arg2" is x=arg1, y=arg2, z=null
        "x y [z...]"      three args (x,y,z) where the final arg can be repeated 
                        "arg1 arg2 arg3 arg4" is z = [arg3, arg4]

        an argspec comes in the following format, and order
            <flags> <positional> <optional> <tail>

        for a option named 'foo', a:
            switch is '--foo?'
                `cmd --foo` foo is True
                `cmd`       foo is False
            flag is `--foo`
                `cmd --foo=x` foo is 'x'
            list is `--foo...`
                `cmd` foo is []
                `cmd --foo=1 --foo=2` foo is [1,2]
            positional is `foo`
                `cmd x`, foo is `x`
            optional is `[foo]`
                `cmd` foo is null
                `cmd x` foo is x 
            tail is `[foo...]` 
                `cmd` foo is []
                `cmd 1 2 3` foo is [1,2,3] 
    """
    positional = []
    optional = []
    tail = None
    flags = []
    lists = []
    switches = []
    descriptions = {}

    if '\n' in argspec:
        args = [line for line in argspec.split('\n') if line]
    else:
        if argspec.count('#') > 0:
            raise Exception('badargspec')
        args = [x for x in argspec.split()]

    argtypes = {}
    argnames = set()

    def argdesc(arg):
        if '#' in arg:
            arg, desc = arg.split('#', 1)
            return arg.strip(), desc.strip()
        else:
            return arg.strip(), None

    def argname(arg, desc):
        if not arg:
            return arg
        if ':' in arg:
            name, atype = arg.split(':')
            if atype not in ARGTYPES:
                raise wire.BadArg("option {} has unrecognized type {}".format(name, atype))
            argtypes[name] = atype 
        else:
            name = arg
        if name in argnames:
            raise Exception('duplicate arg name')
        argnames.add(name)
        if desc:
            descriptions[name] = desc
        return name

    nargs = len(args) 
    while args: # flags
        arg, desc = argdesc(args[0])
        if not arg.startswith('--'): 
            break
        else:
            args.pop(0)
        if arg.endswith('?'):
            if ':' in arg:
                raise Exception('switches cant have types')
            switches.append(argname(arg[2:-1], desc))
        elif arg.endswith('...'):
            lists.append(argname(arg[2:-3], desc))
        else:
            flags.append(argname(arg[2:],desc))

    while args: # positional
        arg, desc = argdesc(args[0])
        if arg.startswith('--'): raise Exception('badarg')

        if arg.endswith(('...]', ']', '...')) : 
            break
        else:
            args.pop(0)

        positional.append(argname(arg, desc))

    if args and args[0].endswith('...'):
        arg, desc = argdesc(args.pop(0))
        if arg.startswith('--'): raise Exception('badarg')
        if arg.startswith('['): raise Exception('badarg')
        tail = argname(arg[:-3], desc)
    elif args:
        while args: # optional
            arg, desc = argdesc(args[0])
            if arg.startswith('--'): raise Exception('badarg')
            if arg.endswith('...]'): 
                break
            else:
                args.pop(0)
            if not (arg.startswith('[') and arg.endswith(']')): raise Exception('badarg')

            optional.append(argname(arg[1:-1], desc))

        if args: # tail
            arg, desc = argdesc(args.pop(0))
            if arg.startswith('--'): raise Exception('badarg')
            if not arg.startswith('['): raise Exception('badarg')
            if not arg.endswith('...]'): raise Exception('badarg')
            tail = argname(arg[1:-4], desc)

    if args:
        raise Exception('bad argspec')
    
    # check names are valid identifiers

    return nargs, wire.Argspec(
            switches = switches,
            flags = flags,
            lists = lists,
            positional = positional, 
            optional = optional , 
            tail = tail, 
            argtypes = argtypes,
            descriptions = descriptions,
    )


def parse_args(argspec, argv, environ):
    options = []
    flags = {}
    args = {}
    file_handles = {}

    for arg in argv:
        if arg.startswith('--'):
            if '=' in arg:
                key, value = arg[2:].split('=',1)
            else:
                key, value = arg[2:], None
            if key not in flags:
                flags[key] = []
            flags[key].append(value)
        else:
            options.append(arg)

    for name in argspec.switches:
        args[name] = False
        if name not in flags:
            continue

        values = flags.pop(name)

        if not values: 
            raise wire.BadArg("value given for switch flag {}".format(name))
        if len(values) > 1:
            raise wire.BadArg("duplicate switch flag for: {}".format(name, ", ".join(repr(v) for v in values)))

        if values[0] is None:
            args[name] = True
        else:
            args[name] = try_parse(name, values[0], "boolean")

    for name in argspec.flags:
        args[name] = None
        if name not in flags:
            continue

        values = flags.pop(name)
        if not values or values[0] is None:
            raise wire.BadArg("missing value for option flag {}".format(name))
        if len(values) > 1:
            raise wire.BadArg("duplicate option flag for: {}".format(name, ", ".join(repr(v) for v in values)))

        args[name] = try_parse(name, value, argspec.argtypes.get(name))

    for name in argspec.lists:
        args[name] = []
        if name not in flags:
            continue

        values = flags.pop(name)
        if not values or None in values:
            raise wire.BadArg("missing value for list flag {}".format(name))

        for value in values:
            args[name].append(try_parse(name, value, argspec.argtypes.get(name)))

    named_args = False
    if flags:
        for name in argspec.positional:
            if name in flags:
                named_args = True
                break
        for name in argspec.optional:
            if name in flags:
                named_args = True
                break
        if argspec.tail in flags:
            named_args = True
                
    if named_args:
        for name in argspec.positional:
            args[name] = None
            if name not in flags:
                raise BadArg("missing named option: {}".format(name))

            values = flags.pop(name)
            if not values or values[0] is None:
                raise wire.BadArg("missing value for named option {}".format(name))
            if len(values) > 1:
                raise wire.BadArg("duplicate named option for: {}".format(name, ", ".join(repr(v) for v in values)))

            args[name] = try_parse(name, value, argspec.argtypes.get(name))

        for name in argspec.optional:
            args[name] = None
            if name not in flags:
                continue

            values = flags.pop(name)
            if not values or values[0] is None:
                raise wire.BadArg("missing value for named option {}".format(name))
            if len(values) > 1:
                raise wire.BadArg("duplicate named option for: {}".format(name, ", ".join(repr(v) for v in values)))

            args[name] = try_parse(value, argspec.argtypes.get(name))

        name = argspec.tail
        if name and name in flags:
            args[name] = []

            values = flags.pop(name)
            if not values or None in values:
                raise wire.BadArg("missing value for named option  {}".format(name))

            for v in values:
                args[name].append(try_parse(name, value, argspec.argtypes.get(name)))
    else:
        if flags:
            raise wire.BadArg("unknown option flags: --{}".format("".join(flags)))

        if argspec.positional:
            for name in argspec.positional:
                if not options: 
                    raise wire.BadArg("missing option: {}".format(name))

                args[name] = try_parse(name, options.pop(0),argspec.argtypes.get(name))

        if argspec.optional:
            for name in argspec.optional:
                if not options: 
                    args[name] = None
                else:
                    args[name] = try_parse(name, options.pop(0), argspec.argtypes.get(name))

        if argspec.tail:
            tail = []
            name = argspec.tail
            tailtype = argspec.argtypes.get(name)
            while options:
                tail.append(try_parse(name, options.pop(0), tailtype))

            args[name] = tail

    if options and named_args:
        raise wire.BadArg("unnamed options given {!r}".format(" ".join(options)))
    if options:
        raise wire.BadArg("unrecognised option: {!r}".format(" ".join(options)))
    return args

def try_parse(name, arg, argtype):
    if argtype in ("str", "string"):
        return arg
    elif argtype == "infile":
        return wire.FileHandle(arg, "read")
    elif argtype == "outfile":
        return wire.FileHandle(arg, "write")

    elif argtype in ("int","integer"):
        try:
            i = int(arg)
            if str(i) == arg: return i
        except:
            pass
        raise wire.BadArg('{} expects an integer, got {}'.format(name, arg))

    elif argtype in ("float","num", "number"):
        try:
            i = float(arg)
            if str(i) == arg: return i
        except:
            pass
        raise wire.BadArg('{} expects an floating-point number, got {}'.format(name, arg))
    elif argtype in ("bool", "boolean"):
        if arg == "true":
            return True
        elif arg == "false":
            return False
        raise wire.BadArg('{} expects either true or false, got {}'.format(name, arg))
    elif not argtype or argtype == "scalar":
        try:
            i = int(arg)
            if str(i) == arg: return i
        except:
            pass
        try:
            f = float(arg)
            if str(f) == arg: return f
        except:
            pass
        return arg
    else:
        raise wire.BadArg("Don't know how to parse option {}, of unknown type {}".format(name, argtype))

class codec:
    """
        just enough of a type-length-value scheme to be dangerous
        data model: json with ordered dictionaries, bytestrings, and tagged objects

        true = "y"
        false = "n"
        null = "z"
        int = "i" <integer as ascii string> \x7F
        float = "f" <c99-hex float as ascii string> \x7F
        bytes = "b" <number bytes as ascii string> \x7F <bytes> \x7F
        list = "L" <number of entries as ascii string> \x7F (<encoded value>)* \7F
        record = "R" <number of pairs as ascii string> \x7F (<encoded key> <encoded value>)* \7F
        record = "T" <name as printable ascii string> \x7F <encoded value> \7F

        note: 0..31 and 128..255 are not used as types for a reason
        
        stretch goals:
            use utf-8 codepoint as type, as high bit is reserved
            encode ints 0..31 as types \x00 .. \x1f
            types for pos int, neg int, float that use <width as codepoint> <bytes>
                i.e "+\x01\x20 for 32, "-\x01\x7F" as -127
            types to define numbers for tag/field names in records, 

    """
    tags = {}
    classes = {}
    TRUE = ord("y")
    FALSE = ord("n")
    NULL = ord("z")
    INT = ord("i")
    FLOAT = ord("f")
    STRING = ord("u")
    BYTES = ord("b")
    LIST = ord("L")
    RECORD = ord("R")
    TAG = ord("T")
    END = 127

    def parse(buf, offset=0):
        peek = buf[offset]
        if peek == codec.TRUE:
            return True, offset+1
        elif peek == codec.FALSE:
            return False, offset+1
        elif peek == codec.NULL:
            return None, offset+1
        elif peek == codec.INT:
            end = buf.index(codec.END, offset+1)
            obj = buf[offset+1:end].decode('ascii')
            return int(obj), end+1
        elif peek == codec.FLOAT:
            end = buf.index(codec.END, offset+1)
            obj = buf[offset+1:end].decode('ascii')
            return float.fromhex(obj), end+1
        elif peek == codec.BYTES:
            end = buf.index(codec.END, offset+1)
            size = int(buf[offset+1:end].decode('ascii'))
            start, end = end+1, end+1+size
            obj = buf[start:end]
            end = buf.index(codec.END, end)
            return obj, end+1
        elif peek == codec.STRING:
            end = buf.index(codec.END, offset+1)
            size = int(buf[offset+1:end].decode('ascii'))
            start, end = end+1, end+1+size
            obj = buf[start:end].decode('utf-8')
            end = buf.index(codec.END, end)
            return obj, end+1
        elif peek == codec.LIST:
            end = buf.index(codec.END, offset+1)
            size = int(buf[offset+1:end].decode('ascii'))
            start = end+1
            out = []
            for _ in range(size):
                value, start = codec.parse(buf, start)
                out.append(value)
            end = buf.index(codec.END, start)
            return out, end+1
        elif peek == codec.RECORD:
            end = buf.index(codec.END, offset+1)
            size = int(buf[offset+1:end].decode('ascii'))
            start = end+1
            out = {}
            for _ in range(size):
                key, start = codec.parse(buf, start)
                value, start = codec.parse(buf, start)
                out[key] = value

            end = buf.index(codec.END, start)
            return out, end+1
        elif peek == codec.TAG:
            end = buf.index(codec.END, offset+1)
            tag = (buf[offset+1:end].decode('ascii'))
            cls = codec.classes[tag]
            args, start = codec.parse(buf, end+1)
            out = cls(**args)
            end = buf.index(codec.END, start)
            return out, end+1


        raise Exception('bad buf {}'.format(peek.encode('ascii')))


    def dump(obj, buf):
        if obj is True:
            buf.append(codec.TRUE)
        elif obj is False:
            buf.append(codec.FALSE)
        elif obj is None:
            buf.append(codec.NULL)
        elif isinstance(obj, int):
            buf.append(codec.INT)
            buf.extend(str(obj).encode('ascii'))
            buf.append(codec.END)
        elif isinstance(obj, float):
            buf.append(codec.INT)
            buf.extend(float.hex(obj).encode('ascii'))
            buf.append(codec.END)
        elif isinstance(obj, (bytes,bytearray)):
            buf.append(codec.BYTES)
            buf.extend(str(len(obj)).encode('ascii'))
            buf.append(codec.END)
            buf.extend(obj)
            buf.append(codec.END)
        elif isinstance(obj, (str)):
            obj = obj.encode('utf-8')
            buf.append(codec.STRING)
            buf.extend(str(len(obj)).encode('ascii'))
            buf.append(codec.END)
            buf.extend(obj)
            buf.append(codec.END)
        elif isinstance(obj, (list, tuple)):
            buf.append(codec.LIST)
            buf.extend(str(len(obj)).encode('ascii'))
            buf.append(codec.END)
            for x in obj:
                codec.dump(x, buf)
            buf.append(codec.END)
        elif isinstance(obj, (dict)):
            buf.append(codec.RECORD)
            buf.extend(str(len(obj)).encode('ascii'))
            buf.append(codec.END)
            for k,v in obj.items():
                codec.dump(k, buf)
                codec.dump(v, buf)
            buf.append(codec.END)
        elif obj.__class__ in codec.tags:
            tag = codec.tags[obj.__class__].encode('ascii')
            buf.append(codec.TAG)
            buf.extend(tag)
            buf.append(codec.END)
            codec.dump(obj.__dict__, buf)
            buf.append(codec.END)
        else:
            raise Exception('bad obj {!r}'.format(obj))
        return buf

    def register():
        def decorator(cls):
            name = cls.__name__
            codec.classes[name] = cls
            codec.tags[cls] = name
            return cls
        return decorator

class wire:
    @codec.register()
    class Session:
        def __init__(self, idx, value, file_handles):
            self.idx = idx
            self.value = value
            self.file_handles = file_handles

    class BadArg(Exception):
        def action(self, path):
            return cli.Action("error", path, {'usage':True}, errors=self.args)

    @codec.register()
    class FileHandle:
        def __init__(self, name, mode, buf=None):
            self.name = name
            self.mode = mode
            self.buf = buf

    @codec.register()
    class Argspec:
        def __init__(self, switches, flags, lists, positional, optional, tail, argtypes, descriptions):
            self.switches = switches
            self.flags = flags
            self.lists = lists
            self.positional = positional
            self.optional = optional 
            self.tail = tail
            self.argtypes = argtypes
            self.descriptions = descriptions

    @codec.register()
    class Request:
        def __init__(self, action, path, argv):
            self.action = action
            self.path = path
            self.argv = argv

    @codec.register()
    class Response:
        def __init__(self, exit_code, value, file_handles=()):
            self.exit_code = exit_code
            self.value = value
            self.file_handles = file_handles
            
    @codec.register()
    class Command:
        def __init__(self, prefix, name, subcommands, short, long, argspec):
            self.prefix = prefix
            self.name = name
            self.subcommands = subcommands
            self.short, self.long = short, long
            self.argspec = argspec

        def version(self):
            return "<None>"

        def complete(self, path, text):
            if path and path[0] in self.subcommands:
                return self.subcommands[path[0]].complete(path[1:], text)
            elif not path:
                output = []
                for name in self.subcommands:
                    if name.startswith(text):
                        output.append(name)
                if output:
                    return output

            if text.startswith('--'):
                return self.complete_flag(text[2:])
            elif text.startswith('-'):
                return self.complete_flag(text[1:])
            else:
                # work out which positional, optional, or tail arg it is
                # suggest type
                return ()

        def complete_flag(self, prefix):
            if '=' in prefix:
                # check to see if it's a completeable type
                return ()
            else:
                out = []
                out.extend("--{}".format(x) for x in self.argspec.switches if x.startswith(prefix))
                out.extend("--{}=".format(x) for x in self.argspec.flags if x.startswith(prefix))
                out.extend("--{}=".format(x) for x in self.argspec.lists if x.startswith(prefix))
                return out
                
            

        def parse_args(self, path,argv, environ):
            if argv and argv[0] in self.subcommands:
                return self.subcommands[argv[0]].parse_args(path+[argv[0]], argv[1:], environ)

            if not self.argspec:
                # no argspec, print usage
                if argv and argv[0]:
                    if argv[0] == "help":
                        return cli.Action("help", path, {'usage': False})
                    elif "--help" in argv:
                        return cli.Action("help", path, {'usage': True})
                    elif self.subcommands:
                        return cli.Action("error", path, {'usage':True}, errors=("unknown command: {}".format(argv[0]),))
                    else:
                        return cli.Action("error", path, {'usage':True}, errors=("unknown option: {}".format(argv[0]),))

                return cli.Action("help", path, {'usage': False})
            else:
                if '--help' in argv:
                    return cli.Action("help", path, {'usage':True})
                try:
                    args = parse_args(self.argspec, argv, environ)
                    return cli.Action("call", path, args)
                except wire.BadArg as e:
                    return e.action(path)

        def help(self, path, *, usage=False):
            if path and path[0] in self.subcommands:
                return self.subcommands[path[0]].help(path[1:], usage=usage)
            else:
                if usage:
                    return self.usage()
                return self.manual()
            
        def manual(self):
            output = []
            full_name = list(self.prefix)
            full_name.append(self.name)
            output.append("{}{}{}".format(" ".join(full_name), (" - " if self.short else ""), self.short or ""))

            output.append("")

            output.append(self.usage())
            output.append("")

            if self.long:
                output.append('description:')
                output.append(self.long)
                output.append("")

            if self.argspec and self.argspec.descriptions:
                output.append('options:')
                for name, desc in self.argspec.descriptions.items():
                    output.append('\t{}\t{}'.format(name, desc))
                output.append('')

            if self.subcommands:
                output.append("commands:")
                for cmd in self.subcommands.values():
                    output.append("\t{.name}\t{}".format(cmd, cmd.short or ""))
                output.append("")
            return "\n".join(output)

        def usage(self):
            output = []
            args = []
            full_name = list(self.prefix)
            full_name.append(self.name)
            if self.argspec:
                if self.argspec.switches:
                    args.extend("[--{0}]".format(o) for o in self.argspec.switches)
                if self.argspec.flags:
                    args.extend("[--{0}=<{0}>]".format(o) for o in self.argspec.flags)
                if self.argspec.lists:
                    args.extend("[--{0}=<{0}>...]".format(o) for o in self.argspec.lists)
                if self.argspec.positional:
                    args.extend("<{}>".format(o) for o in self.argspec.positional)
                if self.argspec.optional:
                    args.extend("[<{}>]".format(o) for o in self.argspec.optional)
                if self.argspec.tail:
                    args.append("[<{}>...]".format(self.argspec.tail))

                output.append("usage: {0} {1}".format(" ".join(full_name), " ".join(args)))
            if self.subcommands:
                output.append("usage: {0} [help] <{1}> [--help]".format(" ".join(full_name), "|".join(self.subcommands)))
            return "\n".join(output)



class cli:
    class Action:
        def __init__(self, mode, command, argv, errors=()):
            self.mode = mode
            self.path = command
            self.argv = argv
            self.errors = errors

    class Command:
        def __init__(self, name, short=None, long=None):
            self.name = name
            self.prefix = [] 
            self.subcommands = {}
            self.run_fn = None
            self.short = short
            self.long = None
            self.argspec = None
            self.nargs = 0

        # -- builder methods

        def subcommand(self, name, short=None):
            cmd = cli.Command(name, short)
            cmd.prefix.extend(self.prefix)
            cmd.prefix.append(self.name)
            self.subcommands[name] = cmd
            return cmd

        def run(self, argspec=None):
            """A decorator for setting the function to be run"""

            if argspec is not None:
                self.nargs, self.argspec = parse_argspec(argspec)

            def decorator(fn):
                self.run_fn = fn

                args = list(self.run_fn.__code__.co_varnames[:self.run_fn.__code__.co_argcount])
                args = [a for a in args if not a.startswith('_')]
                
                if not self.argspec:
                    self.nargs, self.argspec = parse_argspec(" ".join(args))
                else:
                    if self.nargs != len(args):
                        raise Exception('bad option definition')

                return fn
            return decorator

        # -- end of builder methods

        def render(self):
            long =self.run_fn.__doc__ if (not self.long and self.run_fn) else self.long
            return wire.Command(
                name = self.name,
                prefix = self.prefix,
                subcommands = {k: v.render() for k,v in self.subcommands.items()},
                short = self.short,
                long = long,
                argspec = self.argspec, 
            )
                


        def call(self, path, argv):
            if path and path[0] == 'help':
                return self.help(path[1:])
            elif path and path[0] in self.subcommands:
                return self.subcommands[path[0]].call(path[1:], argv)
            elif self.run_fn:
                if len(argv) == self.nargs:
                    return wire.Session(self.spawn(argv), None, {})
                else:
                    return wire.Response(-1, "bad options")
            else:
                if len(argv) == 0:
                    return wire.Response(0, self.render().manual())
                else:
                    return wire.Response(-1, self.render.usage())

        def __call__(self, **kwargs):
            return self.run_fn(**args)

        def main(self, name):
            if name == '__main__':
                cli.main(self)

        def spawn(self, argv):
            session = cli.Session(self.run_fn, argv)
            session.fork()
            return session
        
        def poll(self, session, file_handles):
            return session.poll(file_handles)

    #end Command

    class Pipe:
        def __init__(self):
            self.r, self.w = os.pipe()

        def byte_reader(self, close_other=True):
            if close_other: os.close(self.w)
            os.set_blocking(self.r, False)
            return  os.fdopen(self.r, 'rb')

        def byte_writer(self, close_other=True):
            if close_other: os.close(self.r)
            return os.fdopen(self.w, 'wb')



        def obj_reader(self):
            os.close(self.w)
            os.set_blocking(self.r, False)
            pipe = os.fdopen(self.r, 'rb')
            def reader():
                while True:
                    line = pipe.readline().decode('ascii').strip()
                    if not line:  # blank line means it's probably over
                        yield
                    else:
                        size = int(line)
                        buf = pipe.read(size)
                        if size < 0: break
                        obj, _ = codec.parse(buf, 0)
                        yield obj
                pipe.close()
            return reader()


        def obj_writer(self):
            os.close(self.r)
            pipe = os.fdopen(self.w, 'wb')

            def writer(obj=None, end=False):
                if end:
                    pipe.write(b"-1\n")
                    pipe.close()
                else:
                    buf = codec.dump(obj, bytearray())
                    pipe.write(b"%d\n" % (len(buf)))
                    pipe.write(buf)
                    pipe.flush()

            return writer


    class Session():
        def __init__(self, run_fn, argv):
            self.run_fn = run_fn
            self.argv = argv
            self.count = 0

        def fork(self):
            args = {}
            file_handles = {}
            for name, values in self.argv.items():
                if isinstance(values, list):
                    out = []
                    for value in values:
                        value, pipe = self.create_fh(value)
                        if pipe:
                            if name not in file_handles: file_handles[name] = []
                            file_handles[name].append(value.byte_reader(close_other=False))
                            out.append(value.byte_writer(close_other=False))
                        else:
                            out.append(value)
                    args[name] = out
                
                else:
                    value, pipe = self.create_fh(values)
                    if pipe:
                        file_handles[name] = [value.byte_reader(close_other=False)]
                        args[name] = value.byte_writer(close_other=False)
                    else:
                        args[name] = value

            self.file_handles = file_handles

            result_pipe = cli.Pipe()
            stderr_pipe = cli.Pipe()
            stdout_pipe = cli.Pipe()
            stdin_pipe = cli.Pipe()

            pid = os.fork()
            if pid == 0:
                stderr = stderr_pipe.byte_writer()
                stdout = stdout_pipe.byte_writer()
                stdin = stdin_pipe.byte_reader()
                os.set_blocking(stdin.fileno(), True)
                os.dup2(stdin.fileno(), sys.stdin.fileno())
                os.dup2(stdout.fileno(), sys.stdout.fileno())
                os.dup2(stderr.fileno(), sys.stderr.fileno())
                writer = result_pipe.obj_writer()
                try:
                    result = self.run_fn(**args)
                    sys.stderr.flush()
                    sys.stdout.flush()
                    if not isinstance(result, types.GeneratorType):
                        result = [result]
                    for r in result:
                        writer(r)
                finally:
                    writer(end=True)
                    sys.stdout.close()
                    sys.stderr.close()
                    stdout.close()
                    stderr.close()
                sys.exit(0)
            else:
                self.pid = pid
                self.stdout = stdout_pipe.byte_reader()
                self.stderr = stderr_pipe.byte_reader()
                self.reader = result_pipe.obj_reader()
                self.stdin = stdin_pipe.byte_writer()

        def create_fh(self, value):
            if isinstance(value, wire.FileHandle):
                if value.mode == "read":
                    buf = io.BytesIO()
                    buf.write(value.buf)
                    buf.seek(0)
                    return buf, False
                elif value.mode == "write":
                    return cli.Pipe(), True
            return value, False

        def close(self):
            pass

        def poll(self, client_file_handles=()):
            output_fhs = {}

            if self.stdin and 'stdin' in client_file_handles:
                buf = client_file_handles['stdin']
                if buf == b'':
                    self.stdin.close()
                    self.stdin = None
                elif buf is not None:
                    self.stdin.write(buf)
                    self.stdin.flush()

            out = self.stdout.read()
            if out:
                output_fhs['stdout'] = out

            out = self.stderr.read()
            if out:
                output_fhs['stderr'] = out

            for name, fhs in self.file_handles.items():
                output = []
                for fh in fhs:
                    output.append(fh.read())
                if any(output):
                    output_fhs[name] = output

            if output_fhs:
                return wire.Session(self, None, output_fhs)
            try:
                value = next(self.reader)
                return wire.Session(self, value, {})
            except (GeneratorExit, StopIteration):
                os.wait()
                output_fhs = {}
                out = self.stdout.read()
                if out:
                    output_fhs['stdout'] = out
                out = self.stderr.read()
                if out:
                    output_fhs['stderr'] = out
                for name, fhs in self.file_handles.items():
                    output_fhs[name] = []
                    for fh in fhs:
                        output_fhs[name].append(fh.read())

                return wire.Response(0, None, file_handles=output_fhs)

    def main(root):
        argv = sys.argv[1:]
        environ = os.environ
        force_local = False # 'COMP_LINE' in environ and 'COMP_POINT' in environ
        if argv == ["--pipe"]:
            stdin = os.fdopen(os.dup(sys.stdin.fileno()),'rb')
            stdout = os.fdopen(os.dup(sys.stdout.fileno()),'wb')
            os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

            sys.exit(cli.serve_pipe(root, stdin, stdout))
        elif argv and argv[0] == "--run":
            sys.exit(cli.run_pipe_client(argv[1:]))
        elif force_local: 
            code = cli.run(root, argv, environ)
        else:
            input_r, input_w = os.pipe()
            output_r, output_w = os.pipe()
            pid = os.fork()
            if pid == 0: # child
                os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
                code = (cli.serve_pipe(root, os.fdopen(input_r, 'rb'), os.fdopen(output_w, 'wb')))
                sys.exit(code)
            else:
                cmd = cli.PipeClient(os.fdopen(input_w, 'wb'), os.fdopen(output_r, 'rb'))
                code = cli.run(cmd, argv, environ)
                os.write(input_w, b'-1\n')
                sys.exit(code)

    def run_pipe_client(args):
        if '--' in args:
            split = args.index('--')
            cmd, args = " ".join(args[:split]), args[split+1:]
        else:
            cmd, args = args[0], args[1:]

        p = subprocess.Popen(
            cmd,
            shell = True,
            stdin = subprocess.PIPE,
            stdout = subprocess.PIPE,
        )
        root = cli.PipeClient(p.stdin, p.stdout)
        try:
            ret = cli.run(root, args, os.environ)
        finally:
            p.stdin.write(b'-1\n') # break out of readline()
            p.stdin.close()
            p.wait()
        return ret


    def serve_pipe(root, stdin, stdout):
        sessions = []
        while True:
            line = stdin.readline().decode('ascii').strip()
            if not line: 
                break # blank line means it's probably over
            size = int(line)
            if size < 0: break
            buf = stdin.read(size)
            obj, _ = codec.parse(buf, 0)

            try:
                if obj.action == "render":
                    response = root.render()
                elif obj.action == "call":
                    # alternate take: create fork here, but then struggle
                    # to pass streams? 
                    response = root.call(obj.path, obj.argv)
                    if isinstance(response,wire.Session):
                        sessions.append(response.idx)
                        response = wire.Session(len(sessions)-1, response.value, response.file_handles)
                elif obj.action == "poll":
                    s = sessions[obj.path]
                    response = s.poll(obj.argv)
                    if isinstance(response, wire.Response):
                        sessions[obj.path] = None
                    else:
                        response = wire.Session(obj.path, response.value, response.file_handles)
            except Exception as e:
                stdout.write(b'error: ')
                stdout.write(str(e).encode('ascii'))
                raise

            buf = codec.dump(response, bytearray())

            stdout.write(b"%d\n" % (len(buf)))
            stdout.write(buf)
            stdout.flush()
        for s in sessions:
            if s: s.close()
        return 0

    class PipeClient:
        def __init__(self, request, response):
            self.request = request 
            self.response = response

        def send(self, name, path, argv):
            obj = wire.Request(name, path, argv)
            buf = codec.dump(obj, bytearray())
            self.request.write(b"%d\n"%(len(buf)))
            self.request.write(buf)
            self.request.flush()
            size = int(self.response.readline().strip())
            buf = self.response.read(size)
            obj, _ = codec.parse(buf, 0)
            return obj

        def call(self, path, argv):
            return self.send("call", path, argv)

        def render(self):
            return self.send("render", None, None)

        def poll(self, idx, file_handles):
            return self.send("poll", idx, file_handles)


    def run(root, argv, environ):
        obj = root.render()

        if 'COMP_LINE' in environ and 'COMP_POINT' in environ:
            arg, offset =  environ['COMP_LINE'], int(environ['COMP_POINT'])
            tmp = arg[:offset].rsplit(' ', 1)
            if len(tmp) > 1:
                action = cli.Action('complete', tmp[0].split(' ')[1:], tmp[1])
            else:
                action = cli.Action('complete', [], tmp[0])
        elif argv and argv[0] in ("help"):
            argv.pop(0)
            use_help = True
            action = obj.parse_args([], argv, environ)
            action = cli.Action("help", action.path, {'manual': True})
        elif argv and argv[0] == '--version':
            action = cli.Action("version", [], {})
        elif argv and argv[0] == '--help':
            action = cli.Action("help", [], {'usage': True})
        else:
            action = obj.parse_args([], argv, environ)

    
        if action.mode == "complete":
            result = obj.complete(action.path, action.argv)
            for line in result:
                print(line)
            return 0
        elif action.mode != "call":
            if action.mode == "version":
                result = obj.version()
            if action.mode == "help":
                result = obj.help(action.path, usage=action.argv.get('usage'))
            if action.mode == "error":
                print("error: {}".format(", ".join(action.errors)))
                result = obj.help(action.path, usage=action.argv.get('usage'))

            if isinstance(result, wire.Response):
                if 'stdout' in result.file_handles and result.file_handles['stdout']:
                    line = result.file_handles['stdout']
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
                if 'stderr' in result.file_handles and result.file_handles['stderr']:
                    line = result.file_handles['stderr']
                    sys.stderr.buffer.write(line)
                    sys.stderr.buffer.flush()
                exit_code = result.exit_code
                result = result.value
            else:
                exit_code = -len(action.errors)

            if result is not None:
                if isinstance(result, (bytes, bytearray)):
                    sys.stdout.buffer.write(result)
                else:
                    print(result)
                sys.stdout.flush()

            return exit_code


        if action.mode != "call":
            raise Exception('no')

        file_handles = {}
        argv = {}

        for name, values in action.argv.items():
            if isinstance(values, list):
                out = []
                for value in values:
                    if isinstance(value, wire.FileHandle):
                        if value.mode == "read":
                            with open(value.name, "rb") as fh:
                                buf = fh.read()
                            out.append(wire.FileHandle(value.name, "read", buf=buf))
                        elif value.mode == "write":
                            fh = open(value.name, "xb")
                            if name not in file_handles:
                                file_handles[name] = []
                            file_handles[name].append(fh)
                            out.append(value)
                    else:
                        out.append(value)
                argv[name] = out
            else:
                value = values
                if isinstance(value, wire.FileHandle):
                    if value.mode == "read":
                        with open(value.name, "rb") as fh:
                            buf = fh.read()
                        argv[name] = wire.FileHandle(value.name, "read", buf=buf)
                    elif value.mode == "write":
                        fh = open(value.name, "xb")
                        if name not in file_handles:
                            file_handles[name] = []
                        file_handles[name].append(fh)
                        argv[name] = value
                else:
                    argv[name] = value

        os.set_blocking(sys.stdin.fileno(), False)

        result =  root.call(action.path, argv)

        while isinstance(result, wire.Session):
            if 'stdout' in result.file_handles and result.file_handles['stdout']:
                line = result.file_handles['stdout']
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
            if 'stderr' in result.file_handles and result.file_handles['stderr']:
                line = result.file_handles['stderr']
                sys.stderr.buffer.write(line)
                sys.stderr.buffer.flush()
            if file_handles and result.file_handles:
                for name, fhs in file_handles.items():
                    if name not in result.file_handles:
                        continue
                    for idx, fh in enumerate(fhs):
                        fh.write(result.file_handles[name][idx])
            if result.value is not None:
                r = result.value
                if isinstance(r, (bytes, bytearray)):
                    sys.stdout.buffer.write(r)
                else:
                    print(r)
                sys.stdout.flush()
            result = root.poll(result.idx, file_handles={'stdin': sys.stdin.buffer.read()})
            time.sleep(0.300) 

        if 'stdout' in result.file_handles and result.file_handles['stdout']:
            line = result.file_handles['stdout']
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            
        if 'stderr' in result.file_handles and result.file_handles['stderr']:
            line = result.file_handles['stderr']
            sys.stderr.buffer.write(line)
            sys.stderr.buffer.flush()

        if file_handles and isinstance(result, wire.Response) and result.file_handles:
            for name, fhs in file_handles.items():
                for idx, fh in enumerate(fhs):
                    fh.write(result.file_handles[name][idx])
                    fh.close()
        elif file_handles:
            for name, fhs in file_handles.items():
                for fh in fhs:
                    fh.close()
        if isinstance(result, wire.Response):
            exit_code = result.exit_code
            result = result.value
        else:
            exit_code = -len(action.errors)

        if result is not None:
            for r in result:
                if isinstance(r, (bytes, bytearray)):
                    sys.stdout.buffer.write(r)
                else:
                    print(r)
                sys.stdout.flush()

        return exit_code


if __name__ == '__main__':
    argv = sys.argv[1:]
    sys.exit(cli.run_pipe_client(argv))


Command = cli.Command
