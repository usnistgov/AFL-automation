import base64
import pickle

def serialize(obj):
    pickled = pickle.dumps(obj)
    pickled_b64 = base64.b64encode(pickled)
    pickled_str = pickled_b64.decode('utf8')
    return pickled_str

def deserialize(pickled_str):
    pickled_b64 = pickled_str.encode()
    pickled = base64.b64decode(pickled_b64)
    obj = pickle.loads(pickled)
    return obj