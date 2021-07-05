"""Stock components are made here. Stocks are also made here based off the stock ID you give the stock component"""
import os
from math import ceil
from os.path import *

from flask import *
from werkzeug.exceptions import *
from werkzeug.utils import secure_filename

from componentDB.utility.utility_function import isfloat, csvwrite, csvread
from flaskr.db import get_db

bp = Blueprint("sample_stock", __name__)


@bp.route("/sample_stock/<int:page>", methods=("GET", "POST"))
def index(page):
    db = get_db()
    posts = db.execute(
        "SELECT * FROM sample_stock"
    ).fetchall()

    per_page = request.form.get("number")

    if per_page == '' or per_page is None:
        if 'per_page' not in session:
            session['per_page'] = 10
        per_page = session['per_page']

    per_page = int(per_page)
    session['per_page'] = per_page

    sample_id = request.form.get("sample_id")

    radius = 2
    total = len(posts)
    pages = ceil(total / per_page)  # this is the number of pages
    offset = (page - 1) * per_page  # offset for SQL query

    session['sample_stock_url'] = url_for('sample_stock.index', page=page)  # save last URL for going back. easier than using cookies

    if page > pages + 1 or page < 1:
        abort(404, "Out of range")

    if sample_id == '' or sample_id is None:
        session['sample_id'] = sample_id
        posts = db.execute(
            "SELECT * FROM sample_stock ORDER BY sample_id LIMIT ? OFFSET ?", (per_page, offset)
        ).fetchall()
    else:
        sample_id = int(sample_id)
        session['sample_id'] = sample_id
        posts = db.execute(
            "SELECT * FROM sample_stock WHERE sample_id = ? ORDER BY sample_id LIMIT ? OFFSET ?", (sample_id, per_page, offset)
        ).fetchall()

    filtercount = len(posts)

    return render_template("sample_stock/view_sample_stock.html", posts=posts, total=total, filtercount=filtercount, per_page=per_page,
                           pages=pages,
                           page=page,
                           radius=radius)


def get_post(id, check_author=True):
    """
    :raise 404: if a post with the given id doesn't exist
    :raise 403: if the current user isn't the author
    """
    post = (
        get_db()
            .execute(
            "SELECT * FROM sample_stock WHERE id = ?",
            (id,),
        )
            .fetchone()
    )

    if post is None:
        abort(404, f"Sample Stock ID {id} doesn't exist.")

    return post

@bp.route("/sample_stock/upload", methods=("GET", "POST"))
def upload():
    if request.method == "POST":

        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']

        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(join(dirname(realpath(__file__)), 'static/uploads'), filename))
            data = csvread(join('static/uploads/', filename))

            """Processing"""
            for row in data:

                insert(row[0].strip(), int(row[1].strip()), int(row[2].strip()), float(row[3].strip()), row[4].strip(), row[5].strip())

        return redirect(session['sample_url'])

    return render_template("sample_stock/upload_sample_stock.html", back=session['sample_stock_url'])

@bp.route("/sample_stock/create", methods=("GET", "POST"))
def create():
    if request.method == "POST":

        passed = True

        """Name For Sample Entry"""
        sample_name = request.form['sample_name']
        """"""

        sample_id = request.form['sample_id']
        stock_id = request.form['stock_id']
        amount = request.form['amount']
        units = request.form['units']
        volmass = request.form['volmass']

        if not (stock_id.isdecimal() and sample_id.isdecimal() and isfloat(amount)):
            flash("Stock, component ID, and amount must be valid numbers")
            passed = False

        if units.isdecimal() or volmass.isdecimal():
            flash("Input valid units")
            passed = False

        if passed:
            insert(sample_name, sample_id, stock_id, amount, units, volmass)

            return redirect(session['sample_stock_url'])

    return render_template("sample_stock/create_sample_stock.html", back=session['sample_stock_url'])

def insert(sample_name, sample_id, stock_id, amount, units, volmass):
    db = get_db()
    db.execute(
        "INSERT INTO sample_stock (sample_id, stock_id, amount, units, volmass) VALUES (?, ?, ?, ?, ?)",
        (sample_id, stock_id, amount, units, volmass),
    )
    db.commit()

    posts = db.execute(
        "SELECT * FROM sample WHERE id = ?", (sample_id,)
    ).fetchall()

    if len(posts) == 0:
        db.execute("INSERT INTO sample (name, id) VALUES (?, ?)",
                   (sample_name, sample_id))  # SQL does a check so you'll get a error if the id isn't unique
        db.commit()

@bp.route("/sample_stock/<int:id>/update", methods=("GET", "POST"))
def update(id):
    post = get_post(id)

    if request.method == "POST":

        passed = True

        sample_id = request.form['sample_id']
        stock_id = request.form['stock_id']
        amount = request.form['amount']
        units = request.form['units']
        volmass = request.form['volmass']

        if not (stock_id.isdecimal() and sample_id.isdecimal() and isfloat(amount)):
            flash("Stock, component ID, and amount must be valid numbers")
            passed = False

        if units.isdecimal() or volmass.isdecimal():
            flash("Input valid units")
            passed = False

        if passed:
            db = get_db()
            db.execute(
                "UPDATE sample_stock SET sample_id = ?, stock_id = ?, amount = ?, units = ?, volmass = ? WHERE id = ?",
                (sample_id, stock_id, amount, units, volmass, id)
            )

            db.commit()
            return redirect(session['sample_stock_url'])

    return render_template("sample_stock/update_sample_stock.html", post=post, back=session['sample_stock_url'])

@bp.route("/sample_stock/export")
def export():
    path = csvwrite('sample_stock', 'static/export', '/sample_stock_export.txt')
    return send_from_directory(path, 'sample_stock_export.txt', as_attachment=True)

@bp.route("/sample_stock/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM sample_stock WHERE id = ?", (id,))
    db.commit()
    print("SAMPLE STOCK DELETED!")
    return redirect(session['sample_stock_url'])
