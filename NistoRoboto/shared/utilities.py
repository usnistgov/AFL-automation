import types


def listify(obj):
    if not isinstance(obj, types.StringTypes) and hasattr(obj, "__iter__"):
        obj = list(obj)
    return obj
