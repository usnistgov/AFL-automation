import random
from componentDB.utility.units import * # CHANGE THIS IMPORT PATH WHEN YOU USE THE REAL PROJECT!!!!

from flask import *
from werkzeug.exceptions import abort

from componentDB.utility.utility_function import pagination, page_range, generate_label, csvwrite
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

    session['stock_detail_url'] = url_for('stock.detail', id=id)

    post = get_post(id)
    db = get_db()
    components = db.execute(
        "SELECT * FROM stock_component WHERE stock_id = ? ORDER BY component_id", (id,)
    ).fetchall()

    names = []
    colors = []
    amounts = []

    for p in components:
        name = db.execute("SELECT name FROM component WHERE id = ?", (p[2],)).fetchone()[0]
        names.append(name)
        color = '#'+"%06x" % random.randint(0, 0xFFFFFF)
        colors.append(color)

        amount = float(p[4]) * units(p[5])

        if is_volume(amount):
            amount.ito('ml')

        if is_mass(amount):
            amount.ito('g')

        amounts.append(amount.magnitude)

    return render_template("stock/view_stock_detail.html", post=post, components=components,
                           amounts=amounts, names=names, colors=colors, back=session['stock_url'])


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

@bp.route("/stock/<int:id>/export", methods=("GET", "POST"))
def export(id):
    db = get_db()

    posts1 = db.execute(
        "SELECT stock_id, component_id, amount, units, volmass FROM stock_component WHERE stock_id = ? ORDER BY id", (id,)
    ).fetchall()

    posts = []

    for index, post in enumerate(posts1):

        nombre = db.execute("SELECT name FROM stock WHERE id = ?", (id,)).fetchone()[0]
        posts.append([])
        posts[index].append(nombre)
        for en in post:
            posts[index].append(en)

    header = ['STOCK NAME', f'STOCK ID: {id}', 'COMPONENT ID', 'AMOUNT', 'UNITS', 'VOLMASS']

    path = csvwrite(posts, header, 'static/export', '/stock_component_export_in.txt')
    return send_from_directory(path, 'stock_component_export_in.txt', as_attachment=True)

@bp.route("/stock/<int:id>/delete", methods=("GET", "POST"))
def delete(id):
    get_post(id)
    db = get_db()
    db.execute("DELETE FROM stock WHERE id = ?", (id,))
    db.commit()
    return redirect(session['stock_url'])

@bp.route("/stock/<int:id>/label")
def label(id):
    db = get_db()

    name = db.execute("SELECT name FROM stock WHERE id = ?", (id,)).fetchone()[0]

    generate_label(id, name, 'stock')

    return "Label printed..."
