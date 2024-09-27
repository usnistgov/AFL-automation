import threading
from typing import Any, List

class NoContextException(Exception):
    pass

class Context:
    """Inherited by Pipeline to allow for context manager abuse

    See https://stackoverflow.com/questions/49573131/how-are-pymc3-variables-assigned-to-the-currently-active-model
    """

    contexts = threading.local()
    _stack_name = 'stack'

    def __init__(self, name):
        self.name = name
        self.context_type = 'Base'
        self.stack = []

    def __str__(self):
        return f'<{self.context_type}:{self.name}>'

    def __repr__(self):
        return f'<{self.context_type}:{self.name}>'

    def __enter__(self):
        type(self).get_contexts().append(self)
        return self

    def __exit__(self, typ, value, traceback):
        type(self).get_contexts().pop()

    @classmethod
    def get_contexts(cls) -> List:
        if not hasattr(cls.contexts, "stack"):
            cls.contexts.stack = []
        return cls.contexts.stack

    @classmethod
    def get_context(cls) -> Any:
        """Return the deepest context on the stack."""
        try:
            return cls.get_contexts()[-1]
        except IndexError:
            raise NoContextException("No context on context stack")

    def add_self_to_context(self, stack_name=None):
        if stack_name is None:
            stack_name = self._stack_name

        try:
            context = Context.get_context()
        except NoContextException:
            pass  # allow this to be used without a context
        else:
            try:
                stack = getattr(context, stack_name)
            except AttributeError:
                raise AttributeError((
                    f'''Cannot find stack named {stack_name} in parent context of type {context.context_type}. '''
                    f'''Is the indentation correct? Should this object of type {self.context_type} be inside '''
                    f'''of context type {self.context_type}.'''
                ))
            else:
                stack.append(self)
