import random

from flask import *
from werkzeug.exceptions import abort

from NistoRoboto.shared.units import *
from componentDB.utility.utility_function import pagination, page_range, generate_label, csvwrite, sample_stock_json
from componentDB.db import get_db

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

    paged = pagination(page, posts)

    session['sample_url'] = url_for('sample.index', page=page)  # save last URL for going back. easier than using cookies

    page_range(page, paged.pages)

    posts = db.execute(
        "SELECT * FROM sample ORDER BY id LIMIT ? OFFSET ?", (paged.per_page, paged.offset)
    ).fetchall()

    return render_template("sample/view_sample.html", posts=posts, total=paged.total, per_page=paged.per_page, pages=paged.pages,
                           page=page, radius=paged.radius)

@bp.route("/sample/<int:id>/detail", methods=("GET", "POST"))
def detail(id):

    session['sample_detail_url'] = url_for('sample.detail', id=id)

    post = get_post(id)
    db = get_db()
    stocks = db.execute(
        "SELECT * FROM sample_stock WHERE sample_id = ? ORDER BY stock_id", (id,)
    ).fetchall()

    names = []
    colors = []
    amounts = []

    for p in stocks:
        name = db.execute("SELECT name FROM stock WHERE id = ?", (p[2],)).fetchone()[0]
        names.append(name)
        color = '#' + "%06x" % random.randint(0, 0xFFFFFF)
        colors.append(color)

        amount = float(p[4]) * units(p[5])

        if is_volume(amount):
            amount.ito('ml')

        if is_mass(amount):
            amount.ito('g')

        amounts.append(amount.magnitude)

    return render_template("sample/view_sample_detail.html", post=post, stocks=stocks,
                           amounts=amounts, names=names, colors=colors, back=session['sample_url'])


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

@bp.route("/sample/<int:id>/export", methods=("GET", "POST"))
def export(id):
    db = get_db()

    posts1 = db.execute(
        "SELECT sample_id, stock_id, amount, units, volmass FROM sample_stock WHERE sample_id = ? ORDER BY id", (id,)
    ).fetchall()

    posts = []

    for index, post in enumerate(posts1):

        nombre = db.execute("SELECT name FROM sample WHERE id = ?", (id,)).fetchone()[0]
        posts.append([])
        posts[index].append(nombre)
        for en in post:
            posts[index].append(en)

    header = ['SAMPLE NAME', f'SAMPLE ID: {id}', 'STOCK ID', 'AMOUNT', 'UNITS', 'VOLMASS']

    path = csvwrite(posts, header, 'static/export', '/sample_stock_export_in.txt')
    return send_from_directory(path, 'sample_stock_export_in.txt', as_attachment=True)

@bp.route("/sample/<string:name>/json")
def generate_json_name(name):
    db = get_db()

    name = name.replace("_", " ")

    id = db.execute("SELECT id FROM sample WHERE name = ?", (name,), ).fetchone()

    if id is None:
        abort(404, f"Sample '{name}' doesn't exist. Names are case sensitive. Use underscores for spaces in name.")

    id = id[0]

    posts = db.execute(
        "SELECT sample_id, stock_id, amount, units, volmass FROM sample_stock WHERE sample_id = ? ORDER BY id", (id,)
    ).fetchall()

    return dictionary_gen(posts)

@bp.route("/sample/<int:id>/json")
def generate_json_id(id):
    db = get_db()
    posts = db.execute(
        "SELECT sample_id, stock_id, amount, units, volmass FROM sample_stock WHERE sample_id = ? ORDER BY id", (id,)
    ).fetchall()

    if len(posts) == 0:
        abort(404, f"Sample ID {id} doesn't exist.")

    return dictionary_gen(posts)

def dictionary_gen(posts):
    stock_component_list = sample_stock_json(posts)

    if len(stock_component_list) == 1:

        stock_component_list = stock_component_list[0]

    return jsonify(stock_component_list)

@bp.route("/sample/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM sample WHERE id = ?", (id,))
    db.commit()
    return redirect(session['sample_url'])

@bp.route("/sample/<int:id>/label")
def label(id):
    db = get_db()

    name = db.execute("SELECT name FROM sample WHERE id = ?", (id,)).fetchone()[0]

    generate_label(id, name, 'sample')

    return "Label printed..."
