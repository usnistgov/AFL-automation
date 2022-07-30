import base64
import pickle

def serialize(obj):
    pickled = pickle.dumps(obj)
    pickled_b64 = base64.b64encode(pickled)
    pickled_str = pickled_b64.decode('utf8')
    return pickled_str

def deserialize(pickled_str):
    pickled_b64 = pickled_str.encode()
    
    # the b'==' ensures the string is always correctly padeded
    # see https://stackoverflow.com/a/49459036
    pickled = base64.b64decode(pickled_b64 + b'==')
    obj = pickle.loads(pickled)
    return obj