import string

def make_locs(slot,nrows,ncols):
    locs = []
    for i in range(nrows):
        row = string.ascii_uppercase[i]
        for j in range(ncols):
            col = j+1
            locs.append(f'{slot}{row}{col}')
    return locs

def make_wellplate_locs(slot,size):
    if size==96
        locs = make_locs(slot,8,12)
    elif size==24
        locs = make_locs(slot,4,6)
    elif size==6
        locs = make_locs(slot,2,3)
    else:
        raise ValueError(f'Not set up for wellplate size: {size}')
    return locs



