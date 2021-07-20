import csv
import os
from math import ceil
import PIL
import datetime
import qrcode
import rasterprynt
from flask import current_app, request, session, jsonify
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

def generate_label(id, name, type):

  qrimg = qrcode.make(f"id:{id}")
  img = PIL.Image.new(mode='RGB', size=[1100, 290],color='#ffffff')
  canvas = PIL.ImageDraw.Draw(img)
  canvas.text((300, 25), f"ID: {id}", font=PIL.ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeSans.ttf', size=36),
            fill='#000000')  # You may need to change filepath for fonts if using linux
  canvas.text((300, 75), f"Type: {type}", font=PIL.ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeSans.ttf', size=24), fill='#000000')
  canvas.text((300, 125), f"Name: {name}", font=PIL.ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeSans.ttf', size=48), fill='#000000')
  canvas.text((300, 225), f"Last Printed: {datetime.datetime.now()}",
                         font=PIL.ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeSans.ttf', size=24),
   fill='#000000')
  img.paste(qrimg, box=(0, 0))
  img.show()

  printer_ip = '10.42.0.184' # Replace the ip with whatever the printer IP is
  rasterprynt.prynt([img], printer_ip)

def csvread(path):

  path = os.path.join(current_app.root_path, path)

  with open(path, newline='') as csvfile:
    reader = csv.reader(csvfile, delimiter=',')
    rows = []
    next(reader) #skip header line
    for row in reader:
      rows.append(row)
    return rows

def csvwrite(posts, header, path, name):

  path = os.path.join(current_app.root_path, path)

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

def stock_component_json(posts):
  db = get_db()
  stock_component_list = []

  for i, post in enumerate(posts):
    stock_component_list.append({})

    name = db.execute("SELECT name FROM stock WHERE id = ?", (post[1],)).fetchone()[0]

    stock_component_list[i]['stock_name'] = name
    stock_component_list[i]['component_id'] = post[0]
    stock_component_list[i]['stock_id'] = post[1]
    stock_component_list[i]['amount'] = post[2]
    stock_component_list[i]['units'] = post[3]
    stock_component_list[i]['volmass'] = post[4]

  return stock_component_list

def sample_stock_json(posts):
  db = get_db()
  sample_stock_list = []

  for i, post in enumerate(posts):
    sample_stock_list.append({})

    name = db.execute("SELECT name FROM sample WHERE id = ?", (post[0],)).fetchone()[0]

    sample_stock_list[i]['sample_name'] = name
    sample_stock_list[i]['sample_id'] = post[0]
    sample_stock_list[i]['stock_id'] = post[1]
    sample_stock_list[i]['amount'] = post[2]
    sample_stock_list[i]['units'] = post[3]
    sample_stock_list[i]['volmass'] = post[4]

    return sample_stock_list

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



