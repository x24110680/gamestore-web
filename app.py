import os
from datetime import datetime
from flask import (
    Flask, render_template, redirect,
    url_for, session, flash, request
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from db import get_connection, init_db, seed_sample_games
from gamestore_lib import  calculate_cart_total, cart_item_count, format_eur, upload_game_image, send_order_event_to_sqs, notify_order_via_sns

app = Flask(__name__)
app.secret_key = "change_this_secret_key"  # change for production

#  File upload configuration 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# DB INIT 
with app.app_context():
    init_db()
    # seed_sample_games is currently a no-op in your updated db.py
    seed_sample_games()

# HELPERS 
def get_cart():
    return session.get("cart", {})


def save_cart(cart):
    session["cart"] = cart


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, user_type, is_admin FROM users WHERE id = ?",
        (user_id,)
    )
    user = cur.fetchone()
    conn.close()
    return user


def require_login():
    user = get_current_user()
    if not user:
        flash("Please log in first.")
        return None
    return user


def require_seller():
    user = require_login()
    if not user:
        return None
    if user["user_type"] != "seller":
        flash("You must be a seller to access this page.")
        return None
    return user


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# PUBLIC ROUTES 

@app.route("/")
def index():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM games")
    games = cur.fetchall()
    conn.close()

    cart = get_cart()
    cart_count = cart_item_count(cart)
    user = get_current_user()

    return render_template(
        "index.html",
        title="Game Store",
        games=games,
        cart_count=cart_count,
        user=user
    )


@app.route("/about")
def about():
    user = get_current_user()
    cart = get_cart()
    cart_count = cart_item_count(cart)

    return render_template(
        "about.html",
        title="About Us",
        user=user,
        cart_count=cart_count
    )


@app.route("/game/<int:game_id>")
def game_detail(game_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    game = cur.fetchone()
    conn.close()

    if game is None:
        flash("Game not found.")
        return redirect(url_for("index"))

    cart = get_cart()
    cart_count = cart_item_count(cart)
    user = get_current_user()

    return render_template(
        "game_detail.html",
        title=game["title"],
        game=game,
        cart_count=cart_count,
        user=user
    )


@app.route("/add-to-cart/<int:game_id>")
def add_to_cart(game_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    game = cur.fetchone()
    conn.close()

    if game is None:
        flash("Game not found.")
        return redirect(url_for("index"))

    cart = get_cart()
    key = str(game_id)

    if key in cart:
        cart[key]["quantity"] += 1
    else:
        cart[key] = {
            "id": game["id"],
            "title": game["title"],
            "price": float(game["price"]),
            "quantity": 1
        }

    save_cart(cart)
    flash(f"Added {game['title']} to cart.")
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    cart = get_cart()

    total = calculate_cart_total(cart)
    cart_count = cart_item_count(cart)
    user = get_current_user()

    return render_template(
        "cart.html",
        title="Your Cart",
        cart_items=cart,
        total=total,
        cart_count=cart_count,
        user=user
    )


@app.route("/cart/clear")
def clear_cart():
    session["cart"] = {}
    flash("Cart cleared.")
    return redirect(url_for("cart"))


# CHECKOUT AND ORDERS 

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    user = get_current_user()
    cart = get_cart()

    if not cart or len(cart) == 0:
        flash("Your cart is empty.")
        return redirect(url_for("cart"))

    if not user or user["user_type"] != "buyer":
        flash("Only logged-in buyers can check out.")
        return redirect(url_for("login"))

    total = calculate_cart_total(cart)

    if request.method == "POST":
        conn = get_connection()
        cur = conn.cursor()

        created_at = datetime.utcnow().isoformat(timespec="seconds")
        status = "PLACED"

        # 1) Create order
        cur.execute(
            "INSERT INTO orders (user_id, total_amount, created_at, status) "
            "VALUES (?, ?, ?, ?)",
            (user["id"], total, created_at, status)
        )
        order_id = cur.lastrowid

        # 2) Create order items
        items_for_queue = []
        for item in cart.values():
            cur.execute(
                """
                INSERT INTO order_items (order_id, game_id, quantity, price_each)
                VALUES (?, ?, ?, ?)
                """,
                (order_id, item["id"], item["quantity"], item["price"])
            )

            items_for_queue.append(
                {
                    "game_id": item["id"],
                    "title": item["title"],
                    "quantity": int(item["quantity"]),
                    "price": float(item["price"]),
                }
            )

        conn.commit()
        conn.close()

        # 3) Clear cart in session
        session["cart"] = {}

        # 4) Send SQS message (non-critical: do not break checkout on failure)
        try:
            send_order_event_to_sqs(
                order_id=order_id,
                user_id=user["id"],
                total=total,
                items=items_for_queue,
            )
        except RuntimeError as e:
            # Log message to console; user still sees successful order
            print("SQS send error:", e)

        # 5) Send SNS notification (also non-critical)
        try:
            notify_order_via_sns(
                order_id=order_id,
                user_email=user["email"],
                total=total,
            )
        except RuntimeError as e:
            print("SNS publish error:", e)

        flash(f"Order {order_id} placed successfully.")
        return redirect(url_for("index"))

    # GET request: show checkout page
    cart_count = cart_item_count(cart)

    return render_template(
        "checkout.html",
        title="Checkout",
        cart_items=cart,
        total=total,
        cart_count=cart_count,
        user=user
    )

@app.route("/orders")
def my_orders():
    user = get_current_user()
    if not user:
        flash("Please log in to view your orders.")
        return redirect(url_for("login"))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, total_amount, created_at, status
        FROM orders
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user["id"],)
    )
    orders = cur.fetchall()

    if not orders:
        conn.close()
        cart = get_cart()
        cart_count = cart_item_count(cart)
        return render_template(
            "orders.html",
            title="My Orders",
            user=user,
            cart_count=cart_count,
            orders=[],
            order_items_by_order={}
        )

    order_ids = [o["id"] for o in orders]

    placeholders = ",".join("?" for _ in order_ids)
    query = f"""
        SELECT oi.order_id, oi.quantity, oi.price_each,
               g.title AS game_title
        FROM order_items oi
        JOIN games g ON g.id = oi.game_id
        WHERE oi.order_id IN ({placeholders})
        ORDER BY oi.order_id
    """
    cur.execute(query, order_ids)
    items = cur.fetchall()
    conn.close()

    order_items_by_order = {}
    for row in items:
        order_id = row["order_id"]
        order_items_by_order.setdefault(order_id, []).append(row)

    cart = get_cart()
    cart_count = cart_item_count(cart)

    return render_template(
        "orders.html",
        title="My Orders",
        user=user,
        cart_count=cart_count,
        orders=orders,
        order_items_by_order=order_items_by_order
    )


# SELLER ROUTES 

@app.route("/seller/dashboard")
def seller_dashboard():
    user = require_seller()
    if not user:
        return redirect(url_for("index"))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM games WHERE seller_id = ? ORDER BY id DESC",
        (user["id"],)
    )
    games = cur.fetchall()
    conn.close()

    cart = get_cart()
    cart_count = cart_item_count(cart)

    return render_template(
        "seller_dashboard.html",
        title="Seller Dashboard",
        user=user,
        cart_count=cart_count,
        games=games
    )


@app.route("/seller/add-game", methods=["GET", "POST"])
@app.route("/seller/add-game", methods=["GET", "POST"])
def seller_add_game():
    user = require_seller()
    if not user:
        return redirect(url_for("index"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price_str = request.form.get("price", "").strip()
        image_file = request.files.get("image_file")

        if not title or not price_str:
            flash("Title and price are required.")
        else:
            try:
                price = float(price_str)
            except ValueError:
                flash("Price must be a valid number.")
            else:
                # default no image
                image_url = None

                # process image if provided
                if image_file and image_file.filename:
                    if allowed_file(image_file.filename):
                        filename = secure_filename(image_file.filename)

                        # prefix with seller id to avoid collisions
                        filename = f"{user['id']}_{filename}"

                        try:
                            # Upload to S3 using your library function
                            image_url = upload_game_image(image_file, filename)

                        except RuntimeError as e:
                            flash(f"Image upload failed: {e}")
                            image_url = None
                    else:
                        flash("Invalid image type. Allowed: png, jpg, jpeg, gif.")

                # Insert new game into DB
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO games (title, description, price, image_url, seller_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (title, description, price, image_url, user["id"])
                )
                conn.commit()
                conn.close()

                flash("Game added successfully.")
                return redirect(url_for("seller_dashboard"))

    # GET request continues here
    cart = get_cart()
    cart_count = cart_item_count(cart)

    return render_template(
        "seller_add_game.html",
        title="Add Game",
        user=user,
        cart_count=cart_count
    )

@app.route("/seller/edit-game/<int:game_id>", methods=["GET", "POST"])
def seller_edit_game(game_id):
    user = require_seller()
    if not user:
        return redirect(url_for("index"))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM games WHERE id = ? AND seller_id = ?",
        (game_id, user["id"])
    )
    game = cur.fetchone()

    if not game:
        conn.close()
        flash("Game not found or you do not have permission to edit it.")
        return redirect(url_for("seller_dashboard"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price_str = request.form.get("price", "").strip()
        image_file = request.files.get("image_file")

        if not title or not price_str:
            flash("Title and price are required.")
        else:
            try:
                price = float(price_str)
            except ValueError:
                flash("Price must be a valid number.")
            else:
                image_url = game["image_url"]

                if image_file and image_file.filename:
                    if allowed_file(image_file.filename):
                        filename = secure_filename(image_file.filename)
                        filename = f"{user['id']}_{filename}"
                        save_path = os.path.join(UPLOAD_FOLDER, filename)
                        image_file.save(save_path)
                        image_url = f"/static/uploads/{filename}"
                    else:
                        flash("Invalid image type. Allowed: png, jpg, jpeg, gif.")

                cur.execute(
                    """
                    UPDATE games
                    SET title = ?, description = ?, price = ?, image_url = ?
                    WHERE id = ? AND seller_id = ?
                    """,
                    (title, description, price, image_url, game_id, user["id"])
                )
                conn.commit()
                conn.close()
                flash("Game updated successfully.")
                return redirect(url_for("seller_dashboard"))

    conn.close()

    cart = get_cart()
    cart_count = cart_item_count(cart)

    return render_template(
        "seller_edit_game.html",
        title="Edit Game",
        user=user,
        cart_count=cart_count,
        game=game
    )


@app.route("/seller/delete-game/<int:game_id>", methods=["POST"])
def seller_delete_game(game_id):
    user = require_seller()
    if not user:
        return redirect(url_for("index"))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM games WHERE id = ? AND seller_id = ?",
        (game_id, user["id"])
    )
    conn.commit()
    conn.close()

    flash("Game deleted (if it existed and belonged to you).")
    return redirect(url_for("seller_dashboard"))


# ----- AUTH -----

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user_type = request.form.get("user_type", "buyer")

        if user_type not in ("buyer", "seller"):
            user_type = "buyer"

        if not email or not password:
            flash("Email and password are required.")
            return redirect(url_for("register"))

        conn = get_connection()
        cur = conn.cursor()
        try:
            password_hash = generate_password_hash(password)
            cur.execute(
                "INSERT INTO users (email, password_hash, user_type) VALUES (?, ?, ?)",
                (email, password_hash, user_type)
            )
            conn.commit()
            flash("Registration successful. Please log in.")
            return redirect(url_for("login"))
        except Exception as e:
            flash("Error creating user. Maybe email already exists.")
            print("Register error:", e)
            return redirect(url_for("register"))
        finally:
            conn.close()

    user = get_current_user()
    cart = get_cart()
    cart_count = cart_item_count(cart)

    return render_template(
        "register.html",
        title="Register",
        user=user,
        cart_count=cart_count
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        )
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            session["user_type"] = user["user_type"]
            flash("Logged in successfully.")

            if user["user_type"] == "seller":
                return redirect(url_for("seller_dashboard"))
            else:
                return redirect(url_for("index"))
        else:
            flash("Invalid email or password.")
            return redirect(url_for("login"))

    user = get_current_user()
    cart = get_cart()
    cart_count = cart_item_count(cart)

    return render_template(
        "login.html",
        title="Login",
        user=user,
        cart_count=cart_count
    )


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user_email", None)
    session.pop("user_type", None)
    flash("Logged out.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)