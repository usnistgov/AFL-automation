import csv
import os
from math import ceil

from flask import current_app, request, session
from werkzeug.exceptions import abort
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

def pagination(page, posts):

  per_page = request.form.get("number")

  unified = 'unified' in request.form

  if per_page == '' or per_page is None:
    if 'per_page' not in session:
      session['per_page'] = 10
    per_page = session['per_page']

  per_page = int(per_page)
  session['per_page'] = per_page
  session['unified'] = unified
  radius = 2
  total = len(posts)
  pages = ceil(total / per_page)  # this is the number of pages
  offset = (page - 1) * per_page  # offset for SQL query

  return paginated(per_page, radius, total, pages, offset, unified)

class paginated:

  per_page = None
  radius = None
  total = None
  pages = None
  offset = None
  unified = False

  def __init__(self, per_page, radius, total, pages, offset, unified):
    self.per_page = per_page
    self.radius = radius
    self.total = total
    self.pages = pages
    self.offset = offset
    self.unified = unified

def page_range(page, pages):
  if page > pages + 1 or page < 1:
    abort(404, "Out of range")



