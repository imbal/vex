""" abandon all faith all ye who enter here

A program consists of `cli.Commands()`, chained together, used to 
decorate functions to dispatch:

```
cmd = cli.Command('florb','florb the morps')
@cmd.on_run("one [two] [three...]")
def cmd_run(one, two, three):
    print([one, two, three])
```

gives this output:

```
$ florb one 
["one", None, []]

$ florb one two three four
["one", "two", ["three", "four]]
```

If needed, these options can be passed *entirely* as flags: 

```
$ florb --one=one --two=two --three=three --three=four
["one", "two", ["three", "four]]
```

## Subcommands

`Command` can be nested, giving a `cmd one <args>` `cmd two <args>` like interface:
``` 
root = cli.Command('example', 'my program')

subcommand = cli.subcommand('one', 'example subcommand')

@subcommand.on_run(...)
def subcommand_run(...):
    ...
```

`cmd help one` `cmd one --help`, `cmd help two` `cmd two --help` will print out the manual and usage for `one` and `two` respectively.

The parameter to `on_run()`, is called an argspec.

## Argspec

An argspec is a string that describes how to turn CLI arguments into a dictionary of name, value pairs. For example:

- "x y z" given "1 2 3" gives {"x":1, "y":2, "z":3}
- "[x...]" given "a b c" gives {"x":["a","b","c"]}

This is used to call the function underneath, so every value in the function must be present in the argspec. When no argspec is provided, `textfree86` defaults to a string of argument names, i.e `foo(x,y,z)` gets `"x y z"`. 

The dictionary passed will contain a value for every name in the argspec. An argspec resembles a usage string, albeit with a standard formatting for flags or other command line options:

- `--name?` describes a switch, which defaults to `False`, but when present, is set to `True`, additionally, `--name=true` and `--name=false` both work.

- `--name` describes a normal flag, which defaults to `None`, and on the CLI `--name=value` sets it.

- `--name...` describes a list flag, which defaults to `[]`, and on the CLI `--name=value` appends to it

- `name` describes a positional argument. It must come after any flags and before any optional positional arguments.

- `[name]` describes an optional positional argument. If one arg is given for two optional positional args, like `[x] [y]`, then the values are assigned left to right.

- `[name...]` describes a tail positonal argument. It defaults to `[]`, and all remaining arguments are appended to it.

A short argspec has four parts, `<flags> <positional> [<optional positional>]* [<tail positional>...]`

### Long Argspec

Passing a multi-line string allows you to pass in short descriptions of the arguments, using `# ...` at the end of each line.

```
demo = cli.Command('demo', 'cli example programs')
@demo.on_run('''
    --switch?       # a demo switch
    --value:str     # pass with --value=...
    --bucket:int... # a list of numbers
    pos1            # positional
    [opt1]          # optional 1
    [opt2]          # optional 2
    [tail...]       # tail arg
''')
def run(switch, value, bucket, pos1, opt1, opt2, tail):
    '''a demo command that shows all the types of options'''
    return [switch, value, bucket, pos1, opt1, opt2, tail]
```

### Argument Types

A field can contain a parsing instruction, `x:string` or `x:int`

- `int`, `integer`
- `float`, `num`, `number`
- `str`, `string`
- `bool`, `boolean` (accepts 'true', 'false')

Example `arg1:str arg2:int` describes a progrm that would accept `foo 123` as input, passing `{'arg1': 'foo', 'arg2': 123}` to the function.

A scalar field tries to convert the argument to an integer or floating point number, losslessly, and if successful, uses that.

The default is 'string'

"""

import io
import os
import sys
import time
import types
import itertools
import subprocess
import traceback


### Argspec / Parsing

class BadArg(Exception):
    def action(self, path):
        return Action("error", path, {}, errors=self.args)

class BadDefinition(Exception):
    pass

class Complete:
    def __init__(self, prefix, name, argtype):
        self.prefix = prefix
        self.name = name
        self.argtype = argtype

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

ARGTYPES=[x.strip() for x in """
    bool boolean
    int integer
    float num number
    str string
    scalar
    path 
    branch
    commit
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
            raise BadDefinition('BUG: comment in single line argspec')
        args = [x for x in argspec.split()]

    argtypes = {}
    argnames = set()

    def argdesc(arg):
        if '#' in arg:
            arg, desc = arg.split('#', 1)
            return arg.strip(), desc.strip()
        else:
            return arg.strip(), None

    def argname(arg, desc, argtype=None):
        if not arg:
            return arg
        if ':' in arg:
            name, atype = arg.split(':')
            if atype not in ARGTYPES:
                raise BadDefinition("BUG: option {} has unrecognized type {}".format(name, atype))
            argtypes[name] = atype 
        else:
            name = arg
            if argtype:
                argtypes[name] = argtype 
        if name in argnames:
            raise BadDefinition('BUG: duplicate arg name {}'.format(name))
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
                raise BadDefinition('BUG: boolean switches cant have types: {!r}'.format(arg))
            switches.append(argname(arg[2:-1], desc, 'boolean'))
        elif arg.endswith('...'):
            lists.append(argname(arg[2:-3], desc))
        elif arg.endswith('='):
            flags.append(argname(arg[2:-1], desc))
        else:
            flags.append(argname(arg[2:],desc))

    while args: # positional
        arg, desc = argdesc(args[0])
        if arg.startswith('--'): raise BadDefinition('positional arguments must come after flags')

        if arg.endswith(('...]', ']', '...')) : 
            break
        else:
            args.pop(0)

        positional.append(argname(arg, desc))

    if args and args[0].endswith('...'):
        arg, desc = argdesc(args.pop(0))
        if arg.startswith('--'): raise BadDefinition('flags must come before positional args')
        if arg.startswith('['): raise BadDefinition('badarg')
        tail = argname(arg[:-3], desc)
    elif args:
        while args: # optional
            arg, desc = argdesc(args[0])
            if arg.startswith('--'): raise BadDefinition('badarg')
            if arg.endswith('...]'): 
                break
            else:
                args.pop(0)
            if not (arg.startswith('[') and arg.endswith(']')): raise BadDefinition('badarg')

            optional.append(argname(arg[1:-1], desc))

        if args: # tail
            arg, desc = argdesc(args.pop(0))
            if arg.startswith('--'): raise BadDefinition('badarg')
            if not arg.startswith('['): raise BadDefinition('badarg')
            if not arg.endswith('...]'): raise BadDefinition('badarg')
            tail = argname(arg[1:-4], desc)

    if args:
        raise BadDefinition('bad argspec')
    
    # check names are valid identifiers

    return nargs, Argspec(
            switches = switches,
            flags = flags,
            lists = lists,
            positional = positional, 
            optional = optional , 
            tail = tail, 
            argtypes = argtypes,
            descriptions = descriptions,
    )

def parse_err(error, pos, argv):
    message = ["{}, at argument #{}:".format(error, pos)]
    if pos-3 >0:
            message.append(" ... {} args before".format(pos-3))
    for i, a in enumerate(argv[pos-3:pos+3],pos-3):
        if i == pos:
            message.append(">>> {}".format(a))
        else:
            message.append("  > {}".format(a))
    if pos+3 < len(argv)-1:
            message.append(" ... {} args after".format(pos-3))
    message = "\n".join(message)
    return BadArg(message)

def parse_args(argspec, argv, environ):
    options = []
    flags = {}
    args = {}

    for pos, arg in enumerate(argv):
        if arg.startswith('--'):
            if '=' in arg:
                key, value = arg[2:].split('=',1)
            else:
                key, value = arg[2:], None
            if key not in flags:
                flags[key] = []
            flags[key].append((pos,value))
        else:
            options.append((pos,arg))

    for name in argspec.switches:
        args[name] = False
        if name not in flags:
            continue

        values = flags.pop(name)

        if not values: 
            raise parse_err("value given for switch flag {}".format(name), pos, argv)
        if len(values) > 1:
            raise parse_err("duplicate switch flag for: {}".format(name, ", ".join(repr(v) for v in values)), pos, argv)

        pos, value = values[0]

        if value is None:
            args[name] = True
        else:
            args[name] = try_parse(name, value, "boolean", pos, argv)

    for name in argspec.flags:
        args[name] = None
        if name not in flags:
            continue

        values = flags.pop(name)
        if not values or values[0] is None:
            raise parse_err("missing value for option flag {}".format(name), pos, argv)
        if len(values) > 1:
            raise parse_err("duplicate option flag for: {}".format(name, ", ".join(repr(v) for v in values)), pos, argv)

        pos, value = values[0]
        args[name] = try_parse(name, value, argspec.argtypes.get(name), pos, argv)

    for name in argspec.lists:
        args[name] = []
        if name not in flags:
            continue

        values = flags.pop(name)
        if not values or None in values:
            raise parse_err("missing value for list flag {}".format(name), pos, argv)

        for pos, value in values:
            args[name].append(try_parse(name, value, argspec.argtypes.get(name), pos, argv))

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
                raise parse_err("missing named option: {}".format(name), pos, argv)

            values = flags.pop(name)
            if not values or values[0] is None:
                raise parse_err("missing value for named option {}".format(name), pos, argv)
            if len(values) > 1:
                raise parse_err("duplicate named option for: {}".format(name, ", ".join(repr(v) for v in values)), pos, argv)

            pos, value = values[0]
            args[name] = try_parse(name, value, argspec.argtypes.get(name), pos, argv)

        for name in argspec.optional:
            args[name] = None
            if name not in flags:
                continue

            pos, values = flags.pop(name)
            if not values or values[0] is None:
                raise parse_err("missing value for named option {}".format(name), pos, argv)
            if len(values) > 1:
                raise parse_err("duplicate named option for: {}".format(name, ", ".join(repr(v) for v in values)), pos, argv)

            pos, value = values[0]
            args[name] = try_parse(name, value, argspec.argtypes.get(name), pos, argv)

        name = argspec.tail
        if name and name in flags:
            args[name] = []

            pos, values = flags.pop(name)
            if not values or None in values:
                raise parse_err("missing value for named option  {}".format(name), pos, argv)

            for pos, value in values:
                args[name].append(try_parse(name, value, argspec.argtypes.get(name), pos, argv))
    else:
        if flags:
            raise parse_err("unknown option flags: --{}".format("".join(flags)), pos, argv)

        if argspec.positional:
            for name in argspec.positional:
                if not options: 
                    raise parse_err("missing option: {}".format(name), len(argv), argv)
                pos, value= options.pop(0)

                args[name] = try_parse(name, value, argspec.argtypes.get(name), pos, argv)

        if argspec.optional:
            for name in argspec.optional:
                if not options: 
                    args[name] = None
                else:
                    pos, value= options.pop(0)
                    args[name] = try_parse(name, value, argspec.argtypes.get(name), pos, argv)

        if argspec.tail:
            tail = []
            name = argspec.tail
            tailtype = argspec.argtypes.get(name)
            while options:
                pos, value= options.pop(0)
                tail.append(try_parse(name, value, tailtype, pos, argv))

            args[name] = tail

    if options and named_args:
        raise parse_err("unnamed options given {!r}".format(" ".join(arg for pos,arg in options)), pos, argv)
    if options:
        raise parse_err("unrecognised option: {!r}".format(" ".join(arg for pos,arg in options)), pos, argv)
    return args

def try_parse(name, arg, argtype, pos, argv):
    if argtype in (None, "str", "string"):
        return arg
    elif argtype in ("branch", "commit"):
        return arg
    elif argtype in ("path"):
        return os.path.normpath(os.path.join(os.getcwd(), arg))

    elif argtype in ("int","integer"):
        try:
            i = int(arg)
            if str(i) == arg: return i
        except:
            pass
        raise parse_err('{} expects an integer, got {}'.format(name, arg), pos, argv)

    elif argtype in ("float","num", "number"):
        try:
            i = float(arg)
            if str(i) == arg: return i
        except:
            pass
        raise parse_err('{} expects an floating-point number, got {}'.format(name, arg), pos, argv)
    elif argtype in ("bool", "boolean"):
        if arg == "true":
            return True
        elif arg == "false":
            return False
        raise parse_err('{} expects either true or false, got {}'.format(name, arg), pos, argv)
    elif argtype == "scalar":
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
        raise parse_err("Don't know how to parse option {}, of unknown type {}".format(name, argtype), pos, argv)

class CommandDescription:
    def __init__(self, prefix, name, subcommands, subaliases, groups, short, long, argspec):
        self.prefix = prefix
        self.name = name
        self.subcommands = subcommands
        self.subaliases = subaliases
        self.groups = groups
        self.short, self.long = short, long
        self.argspec = argspec

    def version(self):
        return "<None>"


class Action:
    def __init__(self, mode, command, argv, errors=()):
        self.mode = mode
        self.path = command
        self.argv = argv
        self.errors = errors

class Error(Exception):
    def __init__(self, exit_code, value) :
        self.exit_code = exit_code
        self.value = value
        Exception.__init__(self)

class Group:
    def __init__(self, name, command):
        self.name = name
        self.command = command
        
    def subcommand(self, name, short=None, long=None, aliases=()):
        return self.command.subcommand(name, short=short, long=long, aliases=aliases, group=self.name)

class Command:
    def __init__(self, name, short=None,*, long=None, aliases=(), prefixes=()):
        self.name = name
        self.prefix = [] 
        self.subcommands = {}
        self.groups = {None:[]}
        self.subaliases = {}
        self.run_fn = None
        self.aliases=aliases
        self.argspec = None
        self.nargs = 0
        self.call_fn = None
        self.complete_fn= None
        self.prefixes=prefixes
        self.set_desc(short, long)

    def set_desc(self, short, long):
        if long:
            out = []
            for para in long.strip().split('\n\n'):
                para = " ".join(x for x in para.split() if x)
                out.append(para)
            long = "\n\n".join(out)
        else:
            long = None
        if long and '\n' in long and short is None:
            self.short, self.long = long.split('\n',1)
            self.long = self.long.strip()
        elif long and short is None:
            self.long = long.strip()
            self.short = self.long
        else:
            self.short = short
            self.long = long

    def main(self, name):
        if name == '__main__':
            argv = sys.argv[1:]
            environ = os.environ
            code = main(self, argv, environ)
            sys.exit(code)

    # -- builder methods

    def group(self, name):
        self.groups[name] = []
        return Group(name, self)

    def subcommand(self, name, short=None, long=None, aliases=(), group=None):
        #if self.argspec:
        #    raise Exception('bad')
        if name in self.subaliases or name in self.subcommands:
            raise BadDefinition('Duplicate {}'.format(name))
        for a in aliases:
            if a in self.subaliases or a in self.subcommands:
                raise BadDefinition('Duplicate {}'.format(a))
        cmd = Command(name, short)
        for a in aliases:
            self.subaliases[a] = name
        cmd.prefix.extend(self.prefix)
        cmd.prefix.append(self.name)
        self.subcommands[name] = cmd
        self.groups[group].append(name)
        return cmd

    def on_complete(self):
        def _decorator(fn):
            self.complete_fn = fn
            return fn
        return _decorator

    def on_call(self):
        def _decorator(fn):
            self.call_fn = fn
            return fn
        return _decorator


    def on_run(self):
        """A decorator for setting the function to be run"""
        if self.run_fn:
            raise BadDefinition('double definition')

        #if self.subcommands:
        #    raise BadDefinition('bad')

        def decorator(fn):
            self.run_fn = fn
            if not self.long:
                self.set_desc(self.short, fn.__doc__)

            args = list(self.run_fn.__code__.co_varnames[:self.run_fn.__code__.co_argcount])
            args = [a for a in args if not a.startswith('_')]

            if hasattr(fn, 'argspec'):
                self.nargs, self.argspec = fn.nargs, fn.argspec
            else:
                self.nargs, self.argspec = parse_argspec(" ".join(args))

        
            if self.nargs != len(args):
                raise BadDefinition('bad option definition')

            return fn
        return decorator

    def handler(self, path):
        handler = None
        if path and path[0] in self.subcommands:
            handler = self.subcommands[path[0]].handler(path[1:])
        if not handler:
            handler = self.call_fn
        return handler

    # -- end of builder methods

    def bind(self, path, argv):
        if path and path[0] in self.subcommands:
            return self.subcommands[path[0]].bind(path[1:], argv)
        elif self.run_fn:
            if len(argv) == self.nargs:
                return lambda: self.run_fn(**argv)
            else:
                raise Error(-1, "bad options")
        else:
            if len(argv) == 0:
                return lambda: (self.manual())
            else:
                raise Error(-1, self.usage())

    def complete_path(self, route, path):
        if path:
            output = []
            if len(path) > 0:
                path0 = path[0]
                if path0 in self.subaliases:
                    path0 = self.subaliases[path0]
                if path0 in self.subcommands:
                    output.extend(self.subcommands[path0].complete_path(route+[path[0]], path[1:]))
                if len(path) > 1:
                    return output
            prefix = ""
            for name,cmd in self.subcommands.items():
                if not path[0] or name.startswith(path[0]):
                    if name == path[0]: continue
                    if cmd.subcommands and cmd.argspec:
                        output.append("{}{}".format(prefix, name))
                    elif cmd.subcommands and not cmd.argspec:
                        output.append("{}{}:".format(prefix, name))
                    else:
                        output.append("{}{} ".format(prefix, name))
            for name,cmd in self.subaliases.items():
                cmd = self.subcommands[cmd]
                if path[0] and name.startswith(path[0]):
                    if cmd.subcommands and cmd.argspec:
                        output.append("{}{}".format(prefix, name))
                    elif cmd.subcommands and not cmd.argspec:
                        output.append("{}{}:".format(prefix, name))
                    else:
                        output.append("{}{} ".format(prefix, name))
            return output
        elif route:
            output = []
            prefix = route[-1]
            if self.subcommands:
                for name in self.groups[None]:
                    output.append("{}:{}".format(prefix, name))
                if self.argspec:
                    output.append("{} ".format(prefix))
            else:
                output.append("{} ".format(prefix))
            return output
        return ()

    def parse_args(self, path, argv, environ, route):
        if self.subcommands and path:
            if path[0] in self.subaliases:
                path[0] = self.subaliases[path[0]]

            if path[0] in self.subcommands:
                return self.subcommands[path[0]].parse_args(path[1:], argv, environ, route+[path[0]])
            else:
                if route:
                    error="unknown subcommand {} for {}".format(path[0],":".join(route))
                    return Action("error", route, {}, errors=(error,))
                return Action("error", route, {}, errors=("an unknown command: {}".format(path[0]),))

            # no argspec, print usage
        elif not self.argspec:
            if argv and argv[0]:
                if "--help" in argv:
                    return Action("usage", route, {})
                return Action("error", route, {}, errors=("unknown option: {}".format(argv[0]),))

            return Action("help", route, {})
        else:
            if '--help' in argv:
                return Action("usage", route, {})
            try:
                args = parse_args(self.argspec, argv, environ)
                return Action("call", route, args)
            except BadArg as e:
                return e.action(route)

    def help(self, path, *, usage=False):
        if path and path[0] in self.subcommands:
            return self.subcommands[path[0]].help(path[1:], usage=usage)
        else:
            if usage:
                return self.usage()
            return self.manual()

    def complete_arg(self, path, prefix, text):
        if path: 
            if path[0] in self.subaliases:
                path[0] = self.subaliases[path[0]]
            if path[0] in self.subcommands:
                return self.subcommands[path[0]].complete_arg(path[1:], prefix, text)
        else:
            if text.startswith('--'):
                return self.complete_flag(text[2:])
            elif text.startswith('-'):
                return self.complete_flag(text[1:])
            elif self.argspec:
                n = len([p for p in prefix if p and not p.startswith('--')])
                field = None
                if n < len(self.argspec.positional):
                    for i, name in enumerate(self.argspec.positional):
                        if i == n:
                            field = name
                else:
                    n-=len(self.argspec.positional)
                    if n < len(self.argspec.optional):
                        for i, name in enumerate(self.argspec.optional):
                            if i == n:
                                field = name
                    elif self.argspec.tail:
                        field = self.argspec.tail
                if not field:
                    return ()

                argtype = self.argspec.argtypes.get(field)
                return Complete(text, field, argtype)
        return ()

    def complete_flag(self, prefix):
        if '=' in prefix:
            field, prefix = prefix.split('=', 1)
            argtype = self.argspec.argtypes.get(field)
            return Complete(prefix, field, argtype)
        elif self.argspec:
            out = []
            out.extend("--{} ".format(x) for x in self.argspec.switches if x.startswith(prefix))
            out.extend("--{}=".format(x) for x in self.argspec.flags if x.startswith(prefix))
            out.extend("--{}=".format(x) for x in self.argspec.lists if x.startswith(prefix))
            out.extend("--{}=".format(x) for x in self.argspec.positional if x.startswith(prefix))
            out.extend("--{}=".format(x) for x in self.argspec.optional if x.startswith(prefix))
            out.extend("--{}=".format(x) for x in (self.argspec.tail,) if x and x.startswith(prefix))
            return out
        else:
            return ()
            
        
    def manual(self):
        output = []
        full_name = list(self.prefix)
        full_name.append(self.name)
        full_name = "{}{}{}".format(full_name[0], (" " if full_name[1:] else ""), ":".join(full_name[1:]))
        output.append("Name: {}{}{}".format(full_name, (" -- " if self.short else ""), self.short or ""))

        output.append("")

        output.append(self.usage(group=None))
        output.append("")

        if self.argspec and self.argspec.descriptions:
            output.append('Options:')
            for name, desc in self.argspec.descriptions.items():
                output.append('  --{}\t{}'.format(name, desc))
            output.append('')

        if self.long:
            output.append('Description: {}'.format(self.long))
            output.append("")

        if self.subcommands:
            output.append("Commands:") 
            for group, subcommands in self.groups.items():
                for name in subcommands:
                    if name.startswith((" ", "_",)): continue
                    cmd = self.subcommands[name]
                    output.append("  {.name:10}  {}".format(cmd, cmd.short or ""))
                output.append("")
        return "\n".join(output)

    def usage(self, group=None):
        output = []
        args = []
        full_name = list(self.prefix)
        full_name.append(self.name)
        help_full_name = "{} [help]{}{}".format(full_name[0], (" " if full_name[1:] else ""), ":".join(full_name[1:]))
        full_name = "{}{}{}".format(full_name[0], (" " if full_name[1:] else ""), ":".join(full_name[1:]))
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


            output.append("Usage: {0} {1}".format(full_name, " ".join(args)))
        subcommands = self.groups[group]
        subcommands = "|".join(subcommands)
        if group is None and len(self.groups) > 1:
            subcommands += "|..."
        if not self.prefix and subcommands:
            output.append("Usage: {0} [help] <{1}> [--help]".format(self.name, subcommands))
        elif subcommands:
            output.append("Usage: {0}:<{1}> [--help]".format(help_full_name, subcommands))
        return "\n".join(output)


def main(root, argv, environ):

    if 'COMP_LINE' in environ and 'COMP_POINT' in environ:
        arg, offset =  environ['COMP_LINE'], int(environ['COMP_POINT'])
        prefix, arg = arg[:offset].rsplit(' ', 1)
        tmp = prefix.lstrip().split(' ', 1)
        if len(tmp) > 1:
            path = tmp[1].split(' ')
            if path[0] in root.prefixes or path[0] in ('help', 'debug'):
                if len(path) > 1:
                    path = path[1].split(':') 
                    result = root.complete_arg(path, path[2:], arg)
                else:
                    result = root.complete_path([], arg.split(':'))
            else:
                path0 = path[0].split(':')
                result = root.complete_arg(path0, path[1:], arg)
        else:
            result = root.complete_path([], arg.split(':'))
        if isinstance(result, Complete):
            result = root.complete_fn(result.prefix, result.name, result.argtype)
        for line in result:
            print(line)
        return 0


    if argv and argv[0] == "help":
        argv.pop(0)
        path = []
        if argv and not argv[0].startswith('--'):
            path = argv.pop(0).strip().split(':')
        action = root.parse_args(path, argv, environ, [])
        action = Action("help", action.path, {})
    elif argv and (argv[0] in ('debug', 'help') or argv[0] in root.prefixes) and any(argv[1:]):
        mode = argv.pop(0)
        path = []
        if argv and not argv[0].startswith('--'):
            path = argv.pop(0).strip().split(':')
        action = root.parse_args(path, argv, environ, [])
        if action.path == []:
            action = Action(action.mode, [mode], action.argv)
        elif action.mode == "call":
            action = Action(mode, action.path, action.argv)
    elif argv and argv[0] == '--version':
        action = Action("version", [], {})
    elif argv and argv[0] == '--help':
        action = Action("usage", [], {})
    else:
        path = []
        if argv and not argv[0].startswith('--'):
            path = argv.pop(0).strip().split(':')
        action = root.parse_args(path, argv, environ, [])


    try:
        if action.mode == "error":
            if action.path:
                print("Error: {} {}, {}".format(root.name, ":".join(action.path), ", ".join(action.errors)))
            else:
                print("Error: {}, {}".format(root.name, ", ".join(action.errors)))
            print(root.help(action.path, usage=True))
            return -1
        elif action.mode == "version":
            result = root.version()
            callback = lambda:result
        elif action.mode == "usage":
            result = root.help(action.path, usage=True)
            callback = lambda:result
        elif action.mode == "help":
            result = root.help(action.path, usage=False)
            callback = lambda:result
        elif action.mode in ("call", "debug") or action.mode in root.prefixes:
            callback =  root.bind(action.path, action.argv)
        else:
            raise Error('what')

        handler = root.handler(action.path)
        if not handler:
            try:
                result = callback()
                if isinstance(result, types.GeneratorType):
                    for line in result:
                        print(line)
                else:
                    print(result)
                return 0
            except Exception as e:
                if action.mode == "debug":
                    raise
                result= "".join(traceback.format_exception(*sys.exc_info()))
                print(result)
                return -1
        else:
            return handler(action.mode, action.path, action.argv, callback)
    except Error as e:
        print()
        print(e.value)
        return e.exit_code


def argspec(spec=None):
    def decorator(fn):
        nonlocal spec
        args = list(fn.__code__.co_varnames[:fn.__code__.co_argcount])
        args = [a for a in args if not a.startswith('_')]
        
        if spec is None:
            nargs, spec = parse_argspec(" ".join(args))
        else:
            nargs, spec = parse_argspec(spec)

        if nargs != len(args):
            raise BadDefinition('bad option definition')

        fn.nargs = nargs
        fn.argspec = spec

        return fn
    return decorator

