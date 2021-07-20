import os
from os.path import *

from flask import *
from werkzeug.exceptions import *
from werkzeug.utils import secure_filename

from componentDB.utility.utility_function import isfloat, csvwrite, csvread, pagination, page_range
from componentDB.db import get_db

bp = Blueprint("sample_stock", __name__)


@bp.route("/sample_stock/<int:page>", methods=("GET", "POST"))
def index(page):
    db = get_db()

    filter_by = request.form.get('filter', 'id')

    posts = db.execute(
        f"SELECT * FROM sample_stock ORDER BY {filter_by}"
    ).fetchall()

    paged = pagination(page, posts)

    sample_id = request.form.get("sample_id")

    session['sample_stock_url'] = url_for('sample_stock.index', page=page)  # save last URL for going back. easier than using cookies

    page_range(page, paged.pages)

    if paged.unified:

        return render_template("sample_stock/view_sample_stock_unified.html", posts=posts, total=paged.total,
                               unified=paged.unified, filter_by=filter_by)

    else:

        if sample_id == '' or sample_id is None:
            session['sample_id'] = sample_id
            posts = db.execute(
                "SELECT * FROM sample_stock ORDER BY sample_id LIMIT ? OFFSET ?", (paged.per_page, paged.offset)
            ).fetchall()
        else:
            sample_id = int(sample_id)
            session['sample_id'] = sample_id
            posts = db.execute(
                "SELECT * FROM sample_stock WHERE sample_id = ? ORDER BY sample_id LIMIT ? OFFSET ?", (sample_id, paged.per_page, paged.offset)
            ).fetchall()

        filtercount = len(posts)

        return render_template("sample_stock/view_sample_stock.html", posts=posts, total=paged.total, filtercount=filtercount, per_page=paged.per_page,
                               pages=paged.pages, page=page, radius=paged.radius)


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

        return redirect(url_for('sample.index', page=1))

    return render_template("sample_stock/upload_sample_stock.html", back=url_for('sample_stock.create'))

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
        volmass = request.form.get('volmass', '')

        if volmass == '':
            flash("Choose volume or mass")
            passed = False

        if not (stock_id.isdecimal() and sample_id.isdecimal() and isfloat(amount)):
            flash("Stock, component ID, and amount must be valid numbers")
            passed = False

        if units.isdecimal() or volmass.isdecimal():
            flash("Input valid units")
            passed = False

        if passed:
            insert(sample_name, sample_id, stock_id, amount, units, volmass)

            return redirect(url_for('sample.detail', id=sample_id))

    db = get_db()

    stocks = db.execute(
        "SELECT id FROM stock ORDER BY id"
    ).fetchall()

    return render_template("sample_stock/create_sample_stock.html", stocks=stocks, back=session['sample_url'])

def insert(sample_name, sample_id, stock_id, amount, units, volmass):
    db = get_db()

    posts = db.execute(
        "SELECT * FROM sample_stock WHERE sample_id = ? AND stock_id = ?", (sample_id, stock_id)
    ).fetchone()

    if posts is None:

        db.execute(
            "INSERT INTO sample_stock (sample_id, stock_id, amount, units, volmass) VALUES (?, ?, ?, ?, ?)",
            (sample_id, stock_id, amount, units, volmass),
        )
    else:

        db.execute(
            "UPDATE sample_stock SET amount = ?, units = ?, volmass = ? WHERE sample_id = ? AND stock_id = ?",
            (amount, units, volmass, sample_id, stock_id)
        )

    db.commit()

    posts = db.execute(
        "SELECT * FROM sample WHERE id = ?", (sample_id,)
    ).fetchone()

    if posts is None:
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
        volmass = request.form.get('volmass', '')

        if volmass == '':
            flash("Choose volume or mass")
            volmass = ''
            passed = False

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
            return redirect(url_for('sample.detail', id=sample_id))

    db = get_db()

    stocks = db.execute(
        "SELECT id FROM stock ORDER BY id"
    ).fetchall()

    return render_template("sample_stock/update_sample_stock.html", post=post, stocks=stocks, back=session['sample_detail_url'])

@bp.route("/sample_stock/export")
def export():
    db = get_db()
    posts1 = db.execute(
        "SELECT sample_id, stock_id, amount, units, volmass FROM sample_stock ORDER BY id"
    ).fetchall()

    posts = []

    for index, post in enumerate(posts1):

        name = db.execute("SELECT name FROM sample WHERE id = ?", (post[0],)).fetchone()[0]
        posts.append([])
        posts[index].append(name)
        for en in post:
            posts[index].append(en)

    header = ['SAMPLE NAME', 'SAMPLE ID', 'STOCK ID', 'AMOUNT', 'UNITS', 'VOLMASS']

    path = csvwrite(posts, header, 'static/export', '/sample_stock_export.txt')
    return send_from_directory(path, 'sample_stock_export.txt', as_attachment=True)

@bp.route("/sample_stock/send_json", methods=("GET", "POST"))
def send_json():
    if request.method == "POST":
        dictionary = request.get_json()
        for entry in dictionary:
            insert(entry['sample_name'], entry['sample_id'], entry['stock_id'], entry['amount'], entry['units'],
                   entry['volmass'])

    return "Send JSONS to this url."

@bp.route("/sample_stock/json")
def generate_json():
    db = get_db()
    posts = db.execute(
        "SELECT sample_id, stock_id, amount, units, volmass FROM sample_stock ORDER BY id",
    ).fetchall()

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

    return jsonify(sample_stock_list)

@bp.route("/sample_stock/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM sample_stock WHERE id = ?", (id,))
    db.commit()
    print("SAMPLE STOCK DELETED!")
    return redirect(session['sample_detail_url'])
