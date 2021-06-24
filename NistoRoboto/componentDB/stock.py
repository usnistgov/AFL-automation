"""Stock components are made here. Stocks are also made here based off the stock ID you give the stock component"""

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

@bp.route("/stock")
def stock_index():
    db = get_db()
    posts = db.execute(
        "SELECT * FROM stock ORDER BY created DESC"
    ).fetchall()
    return render_template("stock/view_stock.html", posts=posts)


@bp.route("/stock/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM stock WHERE id = ?", (id,))
    db.commit()
    return redirect(url_for("stock.stock_index"))
