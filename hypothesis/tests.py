import tempfile
import shutil
import os
import os.path
import sys
import subprocess

from hypothesis import given
from hypothesis.strategies import text, integers, lists
from hypothesis.stateful import rule, precondition, RuleBasedStateMachine, Bundle


vexpath = os.path.normpath(os.path.join(os.path.split(os.path.abspath(__file__))[0], "..", "vex"))

class Vex:
    def __init__(self, path, dir, command=()):
        self.path = path
        self.dir=dir
        self.command = command

    def __getattr__(self, name):
        return self.__class__(self.path, self.dir, command=self.command+(name,))

    def __call__(self, *args, **kwargs):
        cmd = [sys.executable]
        cmd.append(self.path)
        if self.command:
            cmd.append(":".join(self.command))
        for name, value in kwargs.items():
            if value is True:
                cmd.append("--{}=true".format(name))
            elif value is False:
                cmd.append("--{}=false".format(name))
            elif isinstance(value, (list, tuple)):
                for v in value:
                    cmd.append("--{}={}".format(name, v))
            else:
                cmd.append("--{}={}".format(name, value))
        for value in args:
            cmd.append(value)

        p=  subprocess.run(cmd, stdout=subprocess.PIPE, cwd=self.dir)
        if p.returncode:
            sys.stdout.buffer.write(p.stdout)
            raise Exception('Error')
        return p.stdout

class VexMachine(RuleBasedStateMachine):
    def __init__(self):
        self.tempd = tempfile.mkdtemp()
        self.vex= Vex(vexpath, self.tempd)
        self.vex.init(prefix='/')
        RuleBasedStateMachine.__init__(self)

    def teardown(self):
        shutil.rmtree(self.tempd)
        RuleBasedStateMachine.teardown(self)

    @rule()
    def status(self):
        self.vex.status()


TestHeap = VexMachine.TestCase
