from math import ceil

from flask import *
from werkzeug.exceptions import abort

from componentDB.utility.utility_function import isfloat
from flaskr.db import get_db

bp = Blueprint("measurement", __name__)

@bp.route("/measurement/<int:page>", methods=("GET", "POST"))
def index(page):
    db = get_db()
    posts = db.execute(
        "SELECT * FROM measurement"
    ).fetchall()

    per_page = request.form.get("number")

    if per_page == '' or per_page is None:
        per_page = session['per_page']

    per_page = int(per_page)
    session['per_page'] = per_page

    radius = 2
    total = len(posts)
    pages = ceil(total / per_page)  # this is the number of pages
    offset = (page - 1) * per_page  # offset for SQL query

    session['measurement_url'] = url_for('measurement.index', page=page)  # save last URL for going back. easier than using cookies

    if page > pages + 1 or page < 1:
        abort(404, "Out of range")

    posts = db.execute(
        "SELECT * FROM measurement ORDER BY created DESC LIMIT ? OFFSET ?", (per_page, offset)
    ).fetchall()

    return render_template("measurement/view_measurement.html", posts=posts, total=total, per_page=per_page, pages=pages,
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
            "SELECT * FROM measurement WHERE id = ?",
            (id,),
        )
            .fetchone()
    )

    if post is None:
        abort(404, f"Measurement ID {id} doesn't exist.")

    return post


@bp.route("/measurement/create", methods=("GET", "POST"))
def create():
    if request.method == "POST":

        sample_id = request.form['sample_id']
        metadata = request.form['metadata']

        if sample_id.isdecimal():
            db = get_db()
            db.execute(
                "INSERT INTO measurement (sample_id, metadata) VALUES (?, ?)",
                (sample_id, metadata),
            )
            db.commit()

            return redirect(session['measurement_url'])
        else:
            flash("Sample ID must be valid number")

    return render_template("measurement/create_measurement.html", back=session['measurement_url'])


@bp.route("/measurement/<int:id>/update", methods=("GET", "POST"))
def update(id):
    post = get_post(id)

    if request.method == "POST":

        sample_id = request.form['sample_id']
        metadata = request.form['metadata']

        if sample_id.isdecimal():
            db = get_db()
            db.execute(
                "UPDATE measurement SET sample_id = ?, metadata = ? WHERE id = ?",
                (sample_id, metadata, id)
            )  # update stock_component table

            db.commit()
            return redirect(session['measurement_url'])
        else:
            flash("Sample ID must be valid number")

    return render_template("measurement/update_measurement.html", post=post, back=session['measurement_url'])


@bp.route("/measurement/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM measurement WHERE id = ?", (id,))
    db.commit()
    return redirect(session['measurement_url'])
