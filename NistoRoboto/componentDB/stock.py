"""Stock components are made here. Stocks are also made here based off the stock ID you give the stock component"""
from math import ceil

from flask import *
from werkzeug.exceptions import abort

from componentDB.utility.utility_function import pagination, page_range
from flaskr.db import get_db

bp = Blueprint("stock", __name__)


def get_post(id, check_author=True):
    """
    :raise 404: if a post with the given id doesn't exist
    :raise 403: if the current user isn't the author
    """
    post = (
        get_db()
            .execute(
            "SELECT * FROM stock WHERE id = ?",
            (id,),
        )
            .fetchone()
    )

    if post is None:
        abort(404, f"Stock ID {id} doesn't exist.")

    return post


@bp.route("/stock/<int:page>", methods=("GET", "POST"))
def index(page):
    db = get_db()
    posts = db.execute(
        "SELECT * FROM stock"
    ).fetchall()

    paged = pagination(page, posts)

    session['stock_url'] = url_for('stock.index', page=page)  # save last URL for going back. easier than using cookies

    page_range(page, paged.pages)

    posts = db.execute(
        "SELECT * FROM stock ORDER BY id LIMIT ? OFFSET ?", (paged.per_page, paged.offset)
    ).fetchall()

    return render_template("stock/view_stock.html", posts=posts, total=paged.total, per_page=paged.per_page, pages=paged.pages, page=page,
                           radius=paged.radius)


@bp.route("/stock/<int:id>/detail", methods=("GET", "POST"))
def detail(id):
    post = get_post(id)
    db = get_db()
    components = db.execute(
        "SELECT * FROM stock_component WHERE stock_id = ? ORDER BY component_id", (id,)
    ).fetchall()

    names = []

    for p in components:
        nombre = db.execute("SELECT name FROM component WHERE id = ?", (p[2],)).fetchone()
        names.append(nombre[0])

    return render_template("stock/view_stock_detail.html", post=post, components=components, names=names, back=session['stock_url'])


@bp.route("/stock/<int:id>/update", methods=("GET", "POST"))
def update(id):
    post = get_post(id)

    if request.method == "POST":

        name = request.form['name']

        if not name.isdecimal():
            db = get_db()
            db.execute(
                "UPDATE stock SET name = ? WHERE id = ?",
                (name, id)
            )

            db.commit()
            return redirect(session['stock_url'])

    return render_template("stock/update_stock.html", post=post, back=session['stock_url'])


@bp.route("/stock/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM stock WHERE id = ?", (id,))
    db.commit()
    return redirect(session['stock_url'])
