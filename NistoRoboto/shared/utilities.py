import types


def listify(obj):
    if isinstance(obj, str) or not hasattr(obj, "__iter__"):
        obj = [obj]
    return obj

def tprint(in_str):
    now = datetime.datetime.now().strftime('%y%m%d-%H:%M:%S')
    print(f'[{now}] {in_str}')

