from math import ceil
import os
from os.path import *

from flask import *
from werkzeug.exceptions import abort
from werkzeug.utils import secure_filename

from componentDB.utility.utility_function import isfloat, csvwrite, csvread
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
        if 'per_page' not in session:
            session['per_page'] = 10
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
        "SELECT * FROM measurement ORDER BY id DESC LIMIT ? OFFSET ?", (per_page, offset)
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

@bp.route("/measurement/upload", methods=("GET", "POST"))
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
                insert(int(row[0]), row[1].strip())

        return redirect(session['measurement_url'])

    return render_template("measurement/upload_measurement.html", back=session['measurement_url'])

@bp.route("/measurement/create", methods=("GET", "POST"))
def create():
    if request.method == "POST":

        sample_id = request.form['sample_id']
        metadata = request.form['metadata']

        if sample_id.isdecimal():
            insert(sample_id, metadata)

            return redirect(session['measurement_url'])
        else:
            flash("Sample ID must be valid number")

    return render_template("measurement/create_measurement.html", back=session['measurement_url'])

def insert(sample_id, metadata):
    db = get_db()
    db.execute(
        "INSERT INTO measurement (sample_id, metadata) VALUES (?, ?)",
        (sample_id, metadata),
    )
    db.commit()

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
            )

            db.commit()
            return redirect(session['measurement_url'])
        else:
            flash("Sample ID must be valid number")

    return render_template("measurement/update_measurement.html", post=post, back=session['measurement_url'])

@bp.route("/measurement/export")
def export():
    path = csvwrite('measurement', 'static/export', '/measurement_export.txt')
    return send_from_directory(path, 'measurement_export.txt', as_attachment=True)

@bp.route("/measurement/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM measurement WHERE id = ?", (id,))
    db.commit()
    return redirect(session['measurement_url'])
