"""Stock components are made here. Stocks are also made here based off the stock ID you give the stock component"""
from math import ceil

from flask import *
from werkzeug.exceptions import abort
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


@bp.route("/stock/<int:page>/<int:per_page>", methods=("GET", "POST"))
def stock_index(page, per_page):
    db = get_db()
    posts = db.execute(
        "SELECT * FROM stock ORDER BY created DESC"
    ).fetchall()

    per_page = int(request.form.get("number", per_page))
    radius = 2
    total = len(posts)
    pages = ceil(total / per_page)  # this is the number of pages
    offset = (page - 1) * per_page  # offset for SQL query

    session['stock_url'] = url_for('stock.stock_index', page=page,
                                   per_page=per_page)  # save last URL for going back. easier than using cookies

    if page > pages + 1 or page < 1:
        abort(404, "Out of range")

    posts = db.execute(
        "SELECT * FROM component ORDER BY created DESC LIMIT ? OFFSET ?", (per_page, offset)
    ).fetchall()

    return render_template("stock/view_stock.html", posts=posts, total=total, per_page=per_page, pages=pages, page=page,
                           radius=radius)


@bp.route("/stock/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM stock WHERE id = ?", (id,))
    db.commit()
    return redirect(session['stock_url'])
