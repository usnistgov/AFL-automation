import csv
import os
from flask import current_app
from componentDB.db import get_db


def isfloat(value):
  if value == '':
    return True
  try:
    float(value)
    return True
  except ValueError:
    return False

def csvread(path):

  path = os.path.join(current_app.root_path, path)

  with open(path, newline='') as csvfile:
    reader = csv.reader(csvfile, delimiter=',')
    rows = []
    next(reader) #skip header line
    for row in reader:
      rows.append(row)
    return rows


def csvwrite(table, path, name):

  path = os.path.join(current_app.root_path, path)

  db = get_db()

  header = []

  if table == 'component':

    posts = db.execute(
      "SELECT name, description, mass, mass_units, density, density_units, formula, sld FROM component ORDER BY id"
    ).fetchall()

    header = ['NAME', 'DESCRIPTION', 'MASS', 'MASS UNITS', 'DENSITY', 'DENSITY UNITS', 'FORMULA', 'SLD (LEAVE BLANK IF OPTIONAL)']

  elif table == 'stock_component':
    posts1 = db.execute(
      "SELECT stock_id, component_id, amount, units, volmass FROM stock_component ORDER BY id"
    ).fetchall()

    posts = []

    for index, post in enumerate(posts1):

      nombre = db.execute("SELECT name FROM stock WHERE id = ?", (post[0],)).fetchone()[0]
      posts.append([])
      posts[index].append(nombre)
      for en in post:
        posts[index].append(en)

    header = ['STOCK NAME', 'STOCK ID', 'COMPONENT ID', 'AMOUNT', 'UNITS', 'VOLMASS']

  elif table == 'sample_stock':
    posts1 = db.execute(
      "SELECT sample_id, stock_id, amount, units, volmass FROM sample_stock ORDER BY id"
    ).fetchall()

    posts = []

    for index, post in enumerate(posts1):

      nombre = db.execute("SELECT name FROM sample WHERE id = ?", (post[0],)).fetchone()[0]
      posts.append([])
      posts[index].append(nombre)
      for en in post:
        posts[index].append(en)

    header = ['SAMPLE NAME', 'SAMPLE ID', 'STOCK ID', 'AMOUNT', 'UNITS', 'VOLMASS']

  elif table == 'measurement':

    posts = db.execute(
      "SELECT sample_id, metadata FROM measurement ORDER BY id"
    ).fetchall()
    header = ['SAMPLE ID', 'METADATA']

  with open(path+name, mode='w') as csvfile:

    writer = csv.writer(csvfile, dialect='excel', delimiter=',', quotechar='"', lineterminator='\n')
    writer.writerow(header)
    for post in posts:
      writer.writerow(post)

  return os.path.join(current_app.root_path, path)



