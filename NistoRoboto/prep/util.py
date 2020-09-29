import string

def make_locs(slot,nrows,ncols):
    locs = []
    for i in range(nrows):
        row = string.ascii_uppercase[i]
        for j in range(ncols):
            col = j+1
            locs.append(f'{slot}{row}{col}')
    return locs


