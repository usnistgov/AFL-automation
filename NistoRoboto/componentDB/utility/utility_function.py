def isfloat(value):
  if value is '':
    return True
  try:
    float(value)
    return True
  except ValueError:
    return False