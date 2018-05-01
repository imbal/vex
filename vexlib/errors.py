"""
    hooray for exceptions
"""
class VexError(Exception): pass

# Should not happen: bad state reached internally
# always throws exception

class VexBug(Exception): pass
class VexCorrupt(Exception): pass

# Can happen: bad environment/arguments
class VexLock(Exception): pass
class VexArgument(VexError): pass

# Recoverable State Errors
class VexNoProject(VexError): pass
class VexNoHistory(VexError): pass
class VexUnclean(VexError): pass

class VexUnimplemented(VexError): pass

