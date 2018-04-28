#!/usr/bin/env python3 
import subprocess
import tempfile
import os.path
import sys
import os

def shell(args):
    print('shell:', args)
    p= subprocess.run(args, stdout=subprocess.PIPE, shell=True)
    if p.returncode:
        sys.stdout.write(p.stdout)
        raise Exception('error')
    return p.stdout

class Vex:
    def __init__(self, path, command=()):
        self.path = path
        self.command = command

    def __getattr__(self, name):
        return self.__class__(self.path, self.command+(name,))

    def __call__(self, *args, **kwargs):
        cmd = []
        cmd.append(self.path)
        if self.command:
            cmd.append(":".join(self.command))
        for name, value in kwargs.items():
            if isinstance(value, (list, tuple)):
                for v in value:
                    cmd.append("--{}={}".format(name, v))
            else:
                cmd.append("--{}={}".format(name, value))
        for value in args:
            cmd.append(value)

        p=  subprocess.run(cmd, stdout=subprocess.PIPE)
        if p.returncode:
            sys.stdout.buffer.write(p.stdout)
            raise Exception('error')
        print("vex {}:".format(" ".join(cmd[1:])))
        for line in p.stdout.splitlines():
            print(">  ", line.decode('utf-8'))

vex = Vex(os.path.join(os.path.split(os.path.abspath(__file__))[0], "vex"))

with tempfile.TemporaryDirectory() as dir:
    print("Using:", dir)
    os.chdir(dir)
    shell('mkdir repo')
    dir = os.path.join(dir, 'repo')
    os.chdir(dir)

    vex.init()

    shell('date >> date')
    shell('mkdir -p dir1 dir2 dir3/dir3.1 dir3/dir3.2')
    shell('echo yes >> dir1/a')
    shell('echo yes >> dir1/b')
    shell('echo yes >> dir1/c')

    vex.add()
    vex.commit()

    vex.undo()
    vex.prepare()
    vex.commit.prepared()

    vex.undo()
    vex.undo()
    vex.redo(choice=1)
    vex.log()
    shell('date >> date')
    vex.switch('dir1')
    shell('rm a')
    shell('mkdir a')
    vex.switch('/repo')
    vex.commit()
    shell('rmdir dir2')
    shell('date >> dir2')
    vex.commit()
    vex.undo()
    vex.branch.saveas('other')
    vex.branch('latest')
    vex.undo()
    vex.commit()
    vex.branch('latest')
    vex.status()

    




