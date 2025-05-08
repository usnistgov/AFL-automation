import warnings

def warning_on_one_line(message, category, filename, lineno, file=None, line=None):
    return f'{category.__name__}: {message}'
warnings.formatwarning = warning_on_one_line

# Custom warning classes
class MixWarning(UserWarning):
    pass
