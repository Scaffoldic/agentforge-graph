from flask import Blueprint, Flask

app = Flask(__name__)
bp = Blueprint("api", __name__)

PREFIX = "/v1"


@app.route("/health")
def health():
    return "ok"


@app.route("/users/<int:uid>", methods=["GET", "POST"])
def user(uid):
    return str(uid)


@bp.get("/items")  # Flask 2.0 shortcut on a blueprint
def items():
    return []


@app.route(PREFIX + "/dynamic")  # non-literal path → counted unresolved
def dynamic():
    return 1


@app.before_request  # not a route decorator → ignored, not counted
def before():
    return None
