"""Stock components are made here. Stocks are also made here based off the stock ID you give the stock component"""
from math import ceil

from flask import *
from werkzeug.exceptions import abort
from flaskr.db import get_db

bp = Blueprint("sample", __name__)


def get_post(id, check_author=True):
    """
    :raise 404: if a post with the given id doesn't exist
    :raise 403: if the current user isn't the author
    """
    post = (
        get_db()
            .execute(
            "SELECT * FROM sample WHERE id = ?",
            (id,),
        )
            .fetchone()
    )

    if post is None:
        abort(404, f"Sample ID {id} doesn't exist.")

    return post


@bp.route("/sample/<int:page>", methods=("GET", "POST"))
def index(page):
    db = get_db()
    posts = db.execute(
        "SELECT * FROM sample"
    ).fetchall()

    session['per_page'] = 10

    per_page = request.form.get("number")

    if per_page == '' or per_page is None:
        per_page = session['per_page']

    per_page = int(per_page)
    session['per_page'] = per_page

    radius = 2
    total = len(posts)
    pages = ceil(total / per_page)  # this is the number of pages
    offset = (page - 1) * per_page  # offset for SQL query

    session['sample_url'] = url_for('sample.index', page=page)  # save last URL for going back. easier than using cookies

    if page > pages + 1 or page < 1:
        abort(404, "Out of range")

    posts = db.execute(
        "SELECT * FROM sample ORDER BY id LIMIT ? OFFSET ?", (per_page, offset)
    ).fetchall()

    return render_template("sample/view_sample.html", posts=posts, total=total, per_page=per_page, pages=pages,
                           page=page, radius=radius)

@bp.route("/sample/<int:id>/detail", methods=("GET", "POST"))
def detail(id):
    post = get_post(id)
    db = get_db()
    stocks = db.execute(
        "SELECT * FROM sample_stock WHERE sample_id = ? ORDER BY stock_id", (id,)
    ).fetchall()

    names = []

    for p in stocks:
        nombre = db.execute("SELECT name FROM stock WHERE id = ?", (p[2],)).fetchone()
        print("NOMBREADADADAD" + nombre[0])
        names.append(nombre[0])

    return render_template("sample/view_sample_detail.html", post=post, stocks=stocks, names=names, back=session['sample_url'])


@bp.route("/sample/<int:id>/update", methods=("GET", "POST"))
def update(id):
    post = get_post(id)

    if request.method == "POST":

        name = request.form['name']

        if not name.isdecimal():
            db = get_db()
            db.execute(
                "UPDATE sample SET name = ? WHERE id = ?",
                (name, id)
            )

            db.commit()
            return redirect(session['sample_url'])

    return render_template("sample/update_sample.html", post=post, back=session['sample_url'])


@bp.route("/sample/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM sample WHERE id = ?", (id,))
    db.commit()
    return redirect(session['sample_url'])
