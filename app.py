from flask import (Flask, render_template, request, session, redirect,
                   url_for, flash, jsonify, abort, g)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import re
import secrets
import socket
import sqlite3
import time
import webbrowser
from datetime import datetime, timedelta
from threading import Timer

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_secret_key():
    """Use SECRET_KEY env var if set, otherwise create one once and keep it in .secret_key"""
    env_key = os.getenv("SECRET_KEY")
    if env_key:
        return env_key
    path = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as file:
            return file.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as file:
        file.write(key)
    return key


app = Flask(__name__)
app.secret_key = load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

# The person with THIS email (after registering on the site) can open /admin
# and see all users, login history and orders. Put your own email here.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()

# ---------------- Cashfree (online payment) ----------------
# Free test keys (no KYC needed for sandbox):
#   merchant.cashfree.com -> Developers -> API Keys -> Test mode -> copy App ID + Secret Key
# Either set environment variables, or paste the keys between the quotes below.
CASHFREE_APP_ID = os.getenv("CASHFREE_APP_ID", "")
CASHFREE_SECRET_KEY = os.getenv("CASHFREE_SECRET_KEY", "")
CASHFREE_ENV = os.getenv("CASHFREE_ENV", "sandbox")        # "sandbox" or "production"

CASHFREE_BASE = ("https://api.cashfree.com/pg" if CASHFREE_ENV == "production"
                 else "https://sandbox.cashfree.com/pg")
CASHFREE_ENABLED = bool(CASHFREE_APP_ID and CASHFREE_SECRET_KEY)


def cashfree_headers():
    return {
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "x-api-version": "2025-01-01",
        "Content-Type": "application/json",
    }


MAX_QTY = 10
DB_PATH = os.path.join(BASE_DIR, "shop.db")

products = [
    # Beauty
    {"id": 1, "name": "Rose Lipstick", "category": "Beauty", "price": 299, "emoji": "💄"},
    {"id": 2, "name": "Face Moisturizer", "category": "Beauty", "price": 349, "emoji": "🧴"},
    {"id": 3, "name": "Makeup Brush Set", "category": "Beauty", "price": 499, "emoji": "🖌️"},
    {"id": 4, "name": "Face Wash", "category": "Beauty", "price": 199, "emoji": "🫧"},
    {"id": 5, "name": "Sunscreen Lotion", "category": "Beauty", "price": 399, "emoji": "☀️"},
    {"id": 6, "name": "Perfume", "category": "Beauty", "price": 599, "emoji": "🌸"},

    # Home Appliances
    {"id": 7, "name": "Electric Kettle", "category": "Home Appliances", "price": 899, "emoji": "🫖"},
    {"id": 8, "name": "Mixer Grinder", "category": "Home Appliances", "price": 2499, "emoji": "⚙️"},
    {"id": 9, "name": "Steam Iron", "category": "Home Appliances", "price": 1199, "emoji": "♨️"},
    {"id": 10, "name": "Table Fan", "category": "Home Appliances", "price": 1599, "emoji": "🌀"},
    {"id": 11, "name": "Rice Cooker", "category": "Home Appliances", "price": 1899, "emoji": "🍚"},
    {"id": 12, "name": "Hand Blender", "category": "Home Appliances", "price": 799, "emoji": "🥣"},

    # Fashion
    {"id": 13, "name": "Cotton T-Shirt", "category": "Fashion", "price": 499, "emoji": "👕"},
    {"id": 14, "name": "Everyday Handbag", "category": "Fashion", "price": 799, "emoji": "👜"},
    {"id": 15, "name": "Casual Sneakers", "category": "Fashion", "price": 1299, "emoji": "👟"},
    {"id": 16, "name": "Denim Jeans", "category": "Fashion", "price": 999, "emoji": "👖"},
    {"id": 17, "name": "Wrist Watch", "category": "Fashion", "price": 899, "emoji": "⌚"},
    {"id": 18, "name": "Sunglasses", "category": "Fashion", "price": 499, "emoji": "🕶️"},

    # Groceries
    {"id": 19, "name": "Basmati Rice", "category": "Groceries", "price": 199, "emoji": "🍚"},
    {"id": 20, "name": "Cooking Oil", "category": "Groceries", "price": 159, "emoji": "🫗"},
    {"id": 21, "name": "Healthy Snack Box", "category": "Groceries", "price": 249, "emoji": "🥜"},
    {"id": 22, "name": "Wheat Flour", "category": "Groceries", "price": 89, "emoji": "🌾"},
    {"id": 23, "name": "Green Tea", "category": "Groceries", "price": 179, "emoji": "🍵"},
    {"id": 24, "name": "Breakfast Cereal", "category": "Groceries", "price": 229, "emoji": "🥣"},

    # Electronics
    {"id": 25, "name": "Wireless Headphones", "category": "Electronics", "price": 1499, "emoji": "🎧"},
    {"id": 26, "name": "Power Bank", "category": "Electronics", "price": 999, "emoji": "🔋"},
    {"id": 27, "name": "Wireless Mouse", "category": "Electronics", "price": 599, "emoji": "🖱️"},
    {"id": 28, "name": "Bluetooth Speaker", "category": "Electronics", "price": 1299, "emoji": "🔊"},
    {"id": 29, "name": "USB Keyboard", "category": "Electronics", "price": 699, "emoji": "⌨️"},
    {"id": 30, "name": "Smart Watch", "category": "Electronics", "price": 1999, "emoji": "⌚"},

    # Home & Kitchen
    {"id": 31, "name": "Non-Stick Pan", "category": "Home & Kitchen", "price": 699, "emoji": "🍳"},
    {"id": 32, "name": "Bedsheet Set", "category": "Home & Kitchen", "price": 899, "emoji": "🛏️"},
    {"id": 33, "name": "Dinner Plate Set", "category": "Home & Kitchen", "price": 599, "emoji": "🍽️"},
    {"id": 34, "name": "Water Bottle", "category": "Home & Kitchen", "price": 299, "emoji": "🧴"},
    {"id": 35, "name": "Storage Containers", "category": "Home & Kitchen", "price": 449, "emoji": "🥡"},
    {"id": 36, "name": "Table Lamp", "category": "Home & Kitchen", "price": 799, "emoji": "💡"},

    # Stationery
    {"id": 37, "name": "Notebook Set", "category": "Stationery", "price": 199, "emoji": "📚"},
    {"id": 38, "name": "Gel Pen Pack", "category": "Stationery", "price": 99, "emoji": "🖊️"},
    {"id": 39, "name": "School Backpack", "category": "Stationery", "price": 699, "emoji": "🎒"},
    {"id": 40, "name": "Sticky Notes", "category": "Stationery", "price": 79, "emoji": "🗒️"},
    {"id": 41, "name": "Desk Organizer", "category": "Stationery", "price": 249, "emoji": "🗃️"},
    {"id": 42, "name": "Color Pencil Set", "category": "Stationery", "price": 149, "emoji": "🖍️"},

    # Daily Care
    {"id": 43, "name": "Shampoo", "category": "Daily Care", "price": 249, "emoji": "🧴"},
    {"id": 44, "name": "Bath Towel", "category": "Daily Care", "price": 299, "emoji": "🧺"},
    {"id": 45, "name": "Toothpaste Pack", "category": "Daily Care", "price": 159, "emoji": "🪥"},
    {"id": 46, "name": "Hand Wash", "category": "Daily Care", "price": 129, "emoji": "🧼"},
    {"id": 47, "name": "Body Lotion", "category": "Daily Care", "price": 279, "emoji": "🧴"},
    {"id": 48, "name": "Comb Set", "category": "Daily Care", "price": 99, "emoji": "💇"},

    # Sports & Fitness
    {"id": 49, "name": "Yoga Mat", "category": "Sports & Fitness", "price": 699, "emoji": "🧘"},
    {"id": 50, "name": "Skipping Rope", "category": "Sports & Fitness", "price": 199, "emoji": "🏃"},

    # More Beauty Products
    {"id": 51, "name": "Compact Powder", "category": "Beauty", "price": 299, "emoji": "💄"},
    {"id": 52, "name": "Eye Liner", "category": "Beauty", "price": 199, "emoji": "🖊️"},
    {"id": 53, "name": "Face Serum", "category": "Beauty", "price": 449, "emoji": "🧴"},
    {"id": 54, "name": "Nail Polish Set", "category": "Beauty", "price": 249, "emoji": "💅"},
    {"id": 55, "name": "Makeup Remover", "category": "Beauty", "price": 229, "emoji": "🧼"},
    {"id": 56, "name": "Hair Dryer", "category": "Beauty", "price": 999, "emoji": "💨"},

    # More Home Appliances
    {"id": 57, "name": "Vacuum Cleaner", "category": "Home Appliances", "price": 2999, "emoji": "🧹"},
    {"id": 58, "name": "Pop-up Toaster", "category": "Home Appliances", "price": 1199, "emoji": "🍞"},
    {"id": 59, "name": "Sandwich Maker", "category": "Home Appliances", "price": 999, "emoji": "🥪"},
    {"id": 60, "name": "Air Cooler", "category": "Home Appliances", "price": 3999, "emoji": "❄️"},
    {"id": 61, "name": "Induction Cooktop", "category": "Home Appliances", "price": 2199, "emoji": "🍳"},
    {"id": 62, "name": "Electric Juicer", "category": "Home Appliances", "price": 1499, "emoji": "🧃"},

    # More Fashion
    {"id": 63, "name": "Formal Shirt", "category": "Fashion", "price": 799, "emoji": "👔"},
    {"id": 64, "name": "Kurti", "category": "Fashion", "price": 699, "emoji": "👗"},
    {"id": 65, "name": "Sports Shoes", "category": "Fashion", "price": 1599, "emoji": "👟"},
    {"id": 66, "name": "Wallet", "category": "Fashion", "price": 399, "emoji": "👛"},
    {"id": 67, "name": "Baseball Cap", "category": "Fashion", "price": 249, "emoji": "🧢"},
    {"id": 68, "name": "Winter Jacket", "category": "Fashion", "price": 1799, "emoji": "🧥"},

    # More Groceries
    {"id": 69, "name": "Brown Sugar", "category": "Groceries", "price": 89, "emoji": "🧂"},
    {"id": 70, "name": "Organic Honey", "category": "Groceries", "price": 299, "emoji": "🍯"},
    {"id": 71, "name": "Pasta Pack", "category": "Groceries", "price": 129, "emoji": "🍝"},
    {"id": 72, "name": "Corn Flakes", "category": "Groceries", "price": 199, "emoji": "🥣"},
    {"id": 73, "name": "Peanut Butter", "category": "Groceries", "price": 249, "emoji": "🥜"},
    {"id": 74, "name": "Coffee Powder", "category": "Groceries", "price": 179, "emoji": "☕"},

    # More Electronics
    {"id": 75, "name": "USB-C Cable", "category": "Electronics", "price": 299, "emoji": "🔌"},
    {"id": 76, "name": "Webcam", "category": "Electronics", "price": 1299, "emoji": "📷"},
    {"id": 77, "name": "Laptop Stand", "category": "Electronics", "price": 799, "emoji": "💻"},
    {"id": 78, "name": "Gaming Controller", "category": "Electronics", "price": 1799, "emoji": "🎮"},
    {"id": 79, "name": "LED Monitor", "category": "Electronics", "price": 6999, "emoji": "🖥️"},
    {"id": 80, "name": "Portable SSD", "category": "Electronics", "price": 3499, "emoji": "💾"},

    # More Home & Kitchen
    {"id": 81, "name": "Pressure Cooker", "category": "Home & Kitchen", "price": 1499, "emoji": "🍲"},
    {"id": 82, "name": "Coffee Mug Set", "category": "Home & Kitchen", "price": 399, "emoji": "☕"},
    {"id": 83, "name": "Curtain Set", "category": "Home & Kitchen", "price": 799, "emoji": "🪟"},
    {"id": 84, "name": "Floor Mat", "category": "Home & Kitchen", "price": 249, "emoji": "🏠"},
    {"id": 85, "name": "Kitchen Knife Set", "category": "Home & Kitchen", "price": 599, "emoji": "🔪"},
    {"id": 86, "name": "Laundry Basket", "category": "Home & Kitchen", "price": 449, "emoji": "🧺"},

    # More Stationery
    {"id": 87, "name": "A4 Paper Pack", "category": "Stationery", "price": 249, "emoji": "📄"},
    {"id": 88, "name": "Whiteboard", "category": "Stationery", "price": 499, "emoji": "📝"},
    {"id": 89, "name": "Stapler Set", "category": "Stationery", "price": 149, "emoji": "📎"},
    {"id": 90, "name": "Art Sketchbook", "category": "Stationery", "price": 199, "emoji": "🎨"},

    # More Daily Care
    {"id": 91, "name": "Dental Floss", "category": "Daily Care", "price": 99, "emoji": "🦷"},
    {"id": 92, "name": "Face Tissues", "category": "Daily Care", "price": 89, "emoji": "🧻"},
    {"id": 93, "name": "Hand Sanitizer", "category": "Daily Care", "price": 99, "emoji": "🧴"},
    {"id": 94, "name": "Hair Oil", "category": "Daily Care", "price": 179, "emoji": "🪮"},

    # More Sports & Fitness
    {"id": 95, "name": "Dumbbell Set", "category": "Sports & Fitness", "price": 999, "emoji": "🏋️"},
    {"id": 96, "name": "Football", "category": "Sports & Fitness", "price": 599, "emoji": "⚽"},
    {"id": 97, "name": "Badminton Racket", "category": "Sports & Fitness", "price": 799, "emoji": "🏸"},
    {"id": 98, "name": "Fitness Resistance Bands", "category": "Sports & Fitness", "price": 349, "emoji": "💪"},
    {"id": 99, "name": "Yoga Block Set", "category": "Sports & Fitness", "price": 299, "emoji": "🧘"},
    {"id": 100, "name": "Sports Water Bottle", "category": "Sports & Fitness", "price": 249, "emoji": "🥤"},

    # Extra products (previously outside the list)
    {"id": 101, "name": "Everyday Tote Bag", "category": "Fashion", "price": 499, "emoji": "👜"},
    {"id": 102, "name": "Classic Headphones", "category": "Electronics", "price": 1299, "emoji": "🎧"},
    {"id": 103, "name": "Daily Care Bottle", "category": "Daily Care", "price": 299, "emoji": "🧴"},
    {"id": 104, "name": "Soft Cushion", "category": "Home & Kitchen", "price": 699, "emoji": "🛋️"},
]

# Short description shown on the product detail page
descriptions = {
    1: "A soft rose-pink lipstick for a fresh, everyday look. Easy to apply and perfect for college, office or a day out.",
    2: "A light daily moisturizer that keeps your face feeling soft and comfortable. Use it morning and night as part of your routine.",
    3: "A handy set of makeup brushes for foundation, powder, blush and eye looks. Great for beginners and regular users.",
    4: "A gentle everyday face wash that helps clean away dust and oil, leaving your skin feeling fresh.",
    5: "A daily sunscreen lotion to help protect your skin from the sun. Apply before stepping out, especially on sunny days.",
    6: "A pleasant, long-lasting floral fragrance for daily wear and special occasions.",
    7: "A quick-boil electric kettle for tea, coffee, instant noodles and hot water in minutes. Compact and easy to use.",
    8: "A powerful mixer grinder for grinding chutneys, masalas and batters, and for blending juices at home.",
    9: "A steam iron that makes it easy to smooth out creases on everyday clothes. Fill the tank, heat up and press.",
    10: "A compact table fan that gives a steady breeze on your desk, bedside or kitchen counter.",
    11: "An easy rice cooker for fluffy rice with very little effort. Add rice and water, switch on and relax.",
    12: "A handy hand blender for soups, shakes, sauces and quick mixing right in the pot or jug.",
    13: "A comfortable cotton t-shirt for daily wear. Soft on the skin and easy to pair with jeans or shorts.",
    14: "A roomy everyday handbag with space for your phone, wallet, keys and daily essentials.",
    15: "Casual sneakers designed for all-day comfort. Pair them with jeans, shorts or your regular outfits.",
    16: "Classic denim jeans with a comfortable everyday fit. A wardrobe staple that goes with almost any top.",
    17: "A stylish wrist watch to keep you on time and add a finishing touch to your outfit.",
    18: "Stylish sunglasses to cut the glare on sunny days and complete your look.",
    19: "Long-grain basmati rice that cooks up fluffy and aromatic. Ideal for biryani, pulao and everyday meals.",
    20: "Cooking oil for everyday frying, sautéing and Indian home cooking.",
    21: "A box of healthy snacks to keep you going between meals. Handy for school, office or travel.",
    22: "Fine wheat flour for soft rotis, chapatis, parathas and other home-cooked favourites.",
    23: "Refreshing green tea to enjoy hot or iced. A light, calming drink for any time of the day.",
    24: "A quick and tasty breakfast cereal. Just add milk for an easy morning meal.",
    25: "Wireless headphones for music, calls and videos without tangled wires. Comfortable for long listening.",
    26: "A portable power bank to charge your phone on the go. Keep it in your bag for travel and long days.",
    27: "A wireless mouse for smooth, clutter-free work on your laptop or desktop.",
    28: "A portable Bluetooth speaker for music at home, on trips or with friends.",
    29: "A USB keyboard with easy plug-and-play use. Great for home, office and study desks.",
    30: "A smart watch to track your day, check notifications and stay on top of your schedule.",
    31: "A non-stick pan for dosas, omelettes and stir-fries with less oil. Easy to cook on and easy to clean.",
    32: "A soft bedsheet set for a comfortable night's sleep. Brightens up your bedroom too.",
    33: "A dinner plate set for everyday meals and family gatherings.",
    34: "A reusable water bottle to keep you hydrated at home, school, office or gym.",
    35: "A set of storage containers to keep dals, snacks and leftovers neat and organized in your kitchen.",
    36: "A table lamp that adds a warm glow to your study desk, bedside or living room.",
    37: "A set of notebooks for classes, notes and daily planning.",
    38: "A pack of smooth-writing gel pens for school, college and office use.",
    39: "A spacious backpack for books, a lunch box and daily essentials. Comfortable to carry every day.",
    40: "Sticky notes for reminders, to-do lists and quick messages on your desk or books.",
    41: "A desk organizer to keep pens, notes and small items tidy so your workspace stays neat.",
    42: "A colour pencil set for drawing, colouring and school projects.",
    43: "A daily shampoo that cleans your hair and leaves it feeling fresh and soft.",
    44: "A soft bath towel that absorbs water well and feels comfortable after every wash.",
    45: "A pack of toothpaste for your daily brushing routine. Keeps your mouth feeling fresh and clean.",
    46: "A hand wash for everyday cleaning. Keep one at every sink in your home.",
    47: "A body lotion to keep your skin soft and moisturized, especially after a bath.",
    48: "A comb set for everyday hair care at home or while travelling.",
    49: "A yoga mat with a comfortable grip for yoga, stretching and floor exercises at home.",
    50: "A skipping rope for a simple, effective cardio workout anywhere, any time.",
    51: "A compact powder for a smooth, matte finish. Slip it in your bag for quick touch-ups.",
    52: "An eye liner for defining your eyes, from a subtle everyday look to a bold evening style.",
    53: "A face serum to add to your skincare routine for a fresh, healthy-looking glow.",
    54: "A nail polish set with colours to mix and match for every outfit and mood.",
    55: "A makeup remover that helps clear away makeup gently at the end of the day.",
    56: "A hair dryer for quick drying and easy styling at home.",
    57: "A vacuum cleaner that makes cleaning floors, sofas and corners quick and simple.",
    58: "A pop-up toaster for crisp, golden toast in minutes. Perfect for breakfast and snacks.",
    59: "A sandwich maker for quick, toasty sandwiches at home. Great for breakfast, tiffin and evening snacks.",
    60: "An air cooler that helps keep your room comfortable during hot days.",
    61: "An induction cooktop for fast, convenient cooking. Easy to use and simple to clean.",
    62: "An electric juicer for fresh fruit juices at home in just a few minutes.",
    63: "A formal shirt with a neat look for office, interviews and special events.",
    64: "A comfortable kurti for everyday wear, college and festive occasions.",
    65: "Sports shoes with a comfortable fit for walking, running and gym sessions.",
    66: "A wallet with space for cards, cash and bills. A daily essential that is easy to carry.",
    67: "A baseball cap for sunny days, travel and casual outfits.",
    68: "A warm winter jacket to keep you comfortable on cold mornings and evenings.",
    69: "Brown sugar for tea, coffee, baking and desserts.",
    70: "Organic honey to enjoy with warm water, tea, toast or in your favourite recipes.",
    71: "A pack of pasta for quick, tasty meals. Cook it with your favourite sauce and vegetables.",
    72: "Crunchy corn flakes for a quick breakfast. Enjoy with milk, fruits or dry fruits.",
    73: "Creamy peanut butter for toast, sandwiches, smoothies and snacks.",
    74: "Coffee powder for a fresh, aromatic cup at home. Great for filter coffee and instant brews.",
    75: "A USB-C cable for charging and transferring data. Handy for phones, tablets and laptops.",
    76: "A webcam for online classes, meetings and video calls from your desk.",
    77: "A laptop stand that raises your screen to a more comfortable height for long working hours.",
    78: "A gaming controller for comfortable, responsive play on supported devices.",
    79: "An LED monitor for a bigger, clearer view for work, study and entertainment.",
    80: "A portable SSD for fast, easy storage and transfer of your files, photos and projects.",
    81: "A pressure cooker for quick and easy cooking of rice, dal and curries.",
    82: "A coffee mug set for your morning coffee, tea or your favourite hot drink.",
    83: "A curtain set that adds colour and privacy to your windows and doors.",
    84: "A floor mat that adds comfort and a neat finish to your entrance, kitchen or bedroom.",
    85: "A kitchen knife set for chopping, slicing and everyday food preparation.",
    86: "A laundry basket to keep clothes organized before wash day.",
    87: "An A4 paper pack for printing, assignments, notes and office work.",
    88: "A whiteboard for planning, studying and writing down ideas. Easy to write and wipe.",
    89: "A stapler set for neat, quick binding of papers at home, school or office.",
    90: "An art sketchbook for drawing, sketching and doodling.",
    91: "Dental floss to help clean between teeth as part of your daily oral care.",
    92: "Soft face tissues for everyday use at home, in the car or while travelling.",
    93: "A hand sanitizer for quick, on-the-go hand cleaning. Easy to carry in your bag.",
    94: "A hair oil for regular hair care and scalp massage.",
    95: "A dumbbell set for strength workouts at home. A simple way to start or continue your fitness routine.",
    96: "A football for matches, practice and fun with friends.",
    97: "A badminton racket for casual games and regular practice.",
    98: "Fitness resistance bands for stretching and strength workouts anywhere, with very little space.",
    99: "A yoga block set that supports your poses and helps you stretch more comfortably.",
    100: "A sports water bottle for the gym, playground or a long day out.",
    101: "An everyday tote bag with room for books, your laptop or shopping.",
    102: "Classic headphones for music, videos and calls with a comfortable fit.",
    103: "A handy daily care bottle for carrying your essentials while you are out.",
    104: "A soft cushion that adds comfort and colour to your sofa, bed or reading corner.",
}

for product in products:
    product["description"] = descriptions.get(
        product["id"],
        f"{product['name']} - a great pick from our {product['category']} collection.",
    )


# Local images: static/images/products/<id>.jpg (or static/Images/products/<id>.jpg)
# If an image is missing, the emoji is shown instead.
for product in products:
    product["image"] = ""
    for folder in ("images", "Images"):
        rel_path = f"{folder}/products/{product['id']}.jpg"
        if os.path.exists(os.path.join(app.static_folder, rel_path)):
            product["image"] = "/static/" + rel_path
            break

products_by_id = {p["id"]: p for p in products}


# ======================= Database =======================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_query(sql, params=(), one=False):
    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        conn.commit()
        if one:
            return rows[0] if rows else None
        return rows
    finally:
        conn.close()


def init_db():
    conn = get_db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            pincode TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            status TEXT NOT NULL,
            payment_status TEXT NOT NULL,
            total INTEGER NOT NULL,
            razorpay_order_id TEXT,
            payment_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT,
            login_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS login_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            email TEXT NOT NULL,
            success INTEGER NOT NULL,
            ip TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            qty INTEGER NOT NULL
        );
        """)
        # older databases may not have the gateway_order_id column
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(orders)")]
        if "gateway_order_id" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN gateway_order_id TEXT")
        if "user_id" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")
        conn.commit()
    finally:
        conn.close()


def create_order(user_id, form, method, items, total):
    status = "Placed" if method == "cod" else "Awaiting Payment"
    payment_status = "Pay on Delivery" if method == "cod" else "Pending"
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO orders
               (user_id, name, phone, address, pincode, payment_method, status,
                payment_status, total, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, form["name"], form["phone"], form["address"], form["pincode"],
             method, status, payment_status, total,
             datetime.now().strftime("%d %b %Y, %I:%M %p")),
        )
        order_id = cur.lastrowid
        for item in items:
            conn.execute(
                """INSERT INTO order_items (order_id, product_id, name, price, qty)
                   VALUES (?, ?, ?, ?, ?)""",
                (order_id, item["product"]["id"], item["product"]["name"],
                 item["product"]["price"], item["qty"]),
            )
        conn.commit()
        return order_id
    finally:
        conn.close()


# ======================= Cart helpers =======================
def get_cart():
    return session.get("cart", {})


def cart_items():
    items, total = [], 0
    for pid, qty in get_cart().items():
        product = products_by_id.get(int(pid))
        if not product:
            continue
        subtotal = product["price"] * qty
        total += subtotal
        items.append({"product": product, "qty": qty, "subtotal": subtotal})
    return items, total


def is_admin():
    return bool(g.get("user") and ADMIN_EMAIL and g.user["email"] == ADMIN_EMAIL)


@app.before_request
def load_user():
    g.user = None
    if request.endpoint == "static":
        return
    user_id = session.get("user_id")
    if user_id:
        g.user = db_query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
        if not g.user:
            session.pop("user_id", None)


@app.context_processor
def inject_globals():
    return {
        "cart_count": sum(get_cart().values()),
        "gateway_enabled": CASHFREE_ENABLED,
        "current_user": g.get("user"),
        "is_admin": is_admin(),
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash("Please log in to continue.", "error")
            next_url = request.full_path.rstrip("?") if request.method == "GET" else ""
            return redirect(url_for("login", next=next_url))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin():
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def get_my_order(order_id):
    """A customer can only open their own orders."""
    order = db_query("SELECT * FROM orders WHERE id = ?", (order_id,), one=True)
    if not order or order["user_id"] != g.user["id"]:
        abort(404)
    items = db_query("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
    return order, items


# ======================= Shop =======================
@app.route("/")
def home():
    search_query = request.args.get("q", "").strip().lower()
    selected_category = request.args.get("category", "").strip()

    filtered_products = [
        product for product in products
        if (
            search_query in product["name"].lower()
            or search_query in product["category"].lower()
        )
        and (
            not selected_category
            or product["category"] == selected_category
        )
    ]

    categories = sorted(set(product["category"] for product in products))

    return render_template(
        "index.html",
        products=filtered_products,
        search_query=search_query,
        categories=categories,
        selected_category=selected_category,
    )


# ======================= Product detail =======================
@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = products_by_id.get(product_id)
    if not product:
        abort(404)
    related = [p for p in products
               if p["category"] == product["category"] and p["id"] != product_id][:4]
    in_cart = get_cart().get(str(product_id), 0)
    return render_template("product.html", product=product,
                           related=related, in_cart=in_cart)


# ======================= Cart =======================
@app.route("/cart")
def cart_page():
    items, total = cart_items()
    return render_template("cart.html", items=items, total=total)


@app.route("/cart/add/<int:product_id>", methods=["POST"])
def cart_add(product_id):
    if product_id not in products_by_id:
        abort(404)
    qty = request.form.get("qty", 1, type=int)
    qty = max(1, min(qty, MAX_QTY))
    cart = get_cart()
    key = str(product_id)
    cart[key] = min(cart.get(key, 0) + qty, MAX_QTY)
    session["cart"] = cart
    return jsonify(count=sum(cart.values()), qty=cart[key])


@app.route("/cart/buy/<int:product_id>", methods=["POST"])
def cart_buy_now(product_id):
    """Add the product (with chosen quantity) and go straight to checkout."""
    if product_id not in products_by_id:
        abort(404)
    qty = request.form.get("qty", 1, type=int)
    qty = max(1, min(qty, MAX_QTY))
    cart = get_cart()
    key = str(product_id)
    cart[key] = min(cart.get(key, 0) + qty, MAX_QTY)
    session["cart"] = cart
    return redirect(url_for("checkout"))


@app.route("/cart/update/<int:product_id>", methods=["POST"])
def cart_update(product_id):
    action = request.form.get("action")
    cart = get_cart()
    key = str(product_id)
    if key in cart:
        if action == "inc":
            cart[key] = min(cart[key] + 1, MAX_QTY)
        elif action == "dec":
            cart[key] -= 1
            if cart[key] <= 0:
                del cart[key]
        elif action == "remove":
            del cart[key]
    session["cart"] = cart
    return redirect(url_for("cart_page"))


@app.route("/cart/clear", methods=["POST"])
def cart_clear():
    session["cart"] = {}
    flash("Cart cleared.", "success")
    return redirect(url_for("cart_page"))


# ======================= Checkout =======================
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    items, total = cart_items()
    if not items:
        flash("Your cart is empty. Add some products first.", "error")
        return redirect(url_for("home"))

    form = {"name": g.user["name"], "phone": g.user["phone"], "address": "", "pincode": ""}
    method = "cod"

    if request.method == "POST":
        for key in form:
            form[key] = request.form.get(key, "").strip()
        method = request.form.get("payment_method", "cod")

        errors = []
        if len(form["name"]) < 2:
            errors.append("Please enter your full name.")
        if not re.fullmatch(r"[6-9]\d{9}", form["phone"]):
            errors.append("Enter a valid 10-digit mobile number.")
        if len(form["address"]) < 10:
            errors.append("Please enter your full delivery address.")
        if not re.fullmatch(r"\d{6}", form["pincode"]):
            errors.append("Enter a valid 6-digit pincode.")
        if method not in ("cod", "online"):
            errors.append("Choose a payment method.")

        if errors:
            for message in errors:
                flash(message, "error")
        else:
            order_id = create_order(g.user["id"], form, method, items, total)
            session["cart"] = {}
            if method == "cod":
                flash("Order placed successfully! Pay when it arrives.", "success")
                return redirect(url_for("order_detail", order_id=order_id))
            return redirect(url_for("pay", order_id=order_id))

    return render_template("checkout.html", items=items, total=total,
                           form=form, method=method)


# ======================= Payment =======================
def mark_paid(order_id, payment_ref):
    db_query("""UPDATE orders SET status = 'Placed', payment_status = 'Paid',
                payment_id = ? WHERE id = ?""", (payment_ref, order_id))


@app.route("/pay/<int:order_id>")
@login_required
def pay(order_id):
    order, items = get_my_order(order_id)
    if order["status"] != "Awaiting Payment":
        return redirect(url_for("order_detail", order_id=order_id))

    session_id = None
    if CASHFREE_ENABLED:
        gateway_order_id = f"LC{order_id}_{int(time.time())}"
        return_url = url_for("pay_return", order_id=order_id, _external=True)
        payload = {
            "order_id": gateway_order_id,
            "order_amount": float(order["total"]),
            "order_currency": "INR",
            "customer_details": {
                "customer_id": f"cust_{order['phone']}",
                "customer_name": order["name"],
                "customer_phone": order["phone"],
            },
            "order_meta": {"return_url": return_url + "?cf_order_id={order_id}"},
        }
        try:
            response = requests.post(f"{CASHFREE_BASE}/orders", json=payload,
                                     headers=cashfree_headers(), timeout=20)
            data = response.json()
            if response.status_code != 200 or "payment_session_id" not in data:
                app.logger.error("Cashfree create order failed: %s %s",
                                 response.status_code, response.text)
                raise ValueError(data.get("message", "create order failed"))
            session_id = data["payment_session_id"]
            db_query("UPDATE orders SET gateway_order_id = ? WHERE id = ?",
                     (gateway_order_id, order_id))
        except Exception as error:
            app.logger.error("Cashfree error: %s", error)
            flash("Payment gateway error. Please try again.", "error")
            return redirect(url_for("order_detail", order_id=order_id))

    return render_template("pay.html", order=order, items=items,
                           session_id=session_id, cf_mode=CASHFREE_ENV)


@app.route("/pay/<int:order_id>/return")
@login_required
def pay_return(order_id):
    """Cashfree sends the customer back here. We never trust the URL:
    the payment status is checked directly with Cashfree from the server."""
    order, _ = get_my_order(order_id)
    if order["status"] != "Awaiting Payment":
        return redirect(url_for("order_detail", order_id=order_id))
    if not CASHFREE_ENABLED or not order["gateway_order_id"]:
        flash("Payment could not be verified. Please try Pay Now again.", "error")
        return redirect(url_for("order_detail", order_id=order_id))

    try:
        response = requests.get(
            f"{CASHFREE_BASE}/orders/{order['gateway_order_id']}",
            headers=cashfree_headers(), timeout=20)
        data = response.json()
        status = data.get("order_status")
    except Exception as error:
        app.logger.error("Cashfree status check failed: %s", error)
        flash("Could not confirm your payment right now. "
              "Please check My Orders again in a minute.", "error")
        return redirect(url_for("order_detail", order_id=order_id))

    if status == "PAID":
        mark_paid(order_id, order["gateway_order_id"])
        flash("Payment successful! Your order is placed.", "success")
    else:
        flash("Payment was not completed. You can try again with Pay Now.", "error")
    return redirect(url_for("order_detail", order_id=order_id))


@app.route("/pay/<int:order_id>/demo", methods=["POST"])
@login_required
def pay_demo(order_id):
    """Demo payment (no real money). Disabled once Cashfree keys are set."""
    order, _ = get_my_order(order_id)
    if order["status"] != "Awaiting Payment":
        flash("This order is already processed.", "error")
        return redirect(url_for("order_detail", order_id=order_id))
    if CASHFREE_ENABLED:
        flash("Demo payment is off because Cashfree keys are set. Use Pay Now.", "error")
        return redirect(url_for("order_detail", order_id=order_id))
    mark_paid(order_id, f"DEMO-{order_id}-{int(time.time())}")
    flash("Demo payment successful! Your order is placed.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


# ======================= Orders =======================
@app.route("/orders")
@login_required
def orders_page():
    orders = []
    rows = db_query("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (g.user["id"],))
    for order in rows:
        lines = db_query("SELECT * FROM order_items WHERE order_id = ?", (order["id"],))
        orders.append({"order": order, "lines": lines})
    return render_template("orders.html", orders=orders)


@app.route("/order/<int:order_id>")
@login_required
def order_detail(order_id):
    order, items = get_my_order(order_id)
    return render_template("order_detail.html", order=order, items=items)


@app.route("/order/<int:order_id>/cancel", methods=["POST"])
@login_required
def order_cancel(order_id):
    order, _ = get_my_order(order_id)
    if order["status"] not in ("Placed", "Awaiting Payment"):
        flash("This order can't be cancelled.", "error")
        return redirect(url_for("order_detail", order_id=order_id))

    payment_status = "Not charged"
    message = "Order cancelled."
    if order["payment_status"] == "Paid":
        payment_status = "Refunded"
        message = "Order cancelled. Your refund has been initiated (5-7 working days)."
        if CASHFREE_ENABLED and order["gateway_order_id"] and not str(order["payment_id"]).startswith("DEMO"):
            try:
                response = requests.post(
                    f"{CASHFREE_BASE}/orders/{order['gateway_order_id']}/refunds",
                    json={"refund_amount": float(order["total"]),
                          "refund_id": f"refund_{order_id}_{int(time.time())}"},
                    headers=cashfree_headers(), timeout=20)
                if response.status_code not in (200, 201):
                    app.logger.error("Cashfree refund failed: %s %s",
                                     response.status_code, response.text)
                    raise ValueError("refund failed")
            except Exception:
                payment_status = "Refund Pending"
                message = ("Order cancelled. Refund could not be started automatically - "
                           "it will be processed manually.")

    db_query("UPDATE orders SET status = 'Cancelled', payment_status = ? WHERE id = ?",
             (payment_status, order_id))
    flash(message, "success")
    return redirect(url_for("order_detail", order_id=order_id))


# ======================= Accounts =======================
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 10


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.remote_addr
    return ip or "unknown"


def log_login(user_id, email, success):
    db_query(
        "INSERT INTO login_log (user_id, email, success, ip, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, email, 1 if success else 0, client_ip(), now_str()),
    )


def start_session(user):
    session["user_id"] = user["id"]
    session.permanent = True
    db_query("UPDATE users SET last_login = ?, login_count = login_count + 1 WHERE id = ?",
             (now_str(), user["id"]))
    log_login(user["id"], user["email"], True)


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("home")


def insert_user(name, email, phone, password):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, phone, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, phone, generate_password_hash(password), now_str()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("home"))

    form = {"name": "", "email": "", "phone": ""}
    next_url = request.values.get("next", "")

    if request.method == "POST":
        for key in form:
            form[key] = request.form.get(key, "").strip()
        form["email"] = form["email"].lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = []
        if len(form["name"]) < 2:
            errors.append("Please enter your full name.")
        if not EMAIL_RE.match(form["email"]):
            errors.append("Enter a valid email address.")
        if not re.fullmatch(r"[6-9]\d{9}", form["phone"]):
            errors.append("Enter a valid 10-digit mobile number.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not errors and db_query("SELECT id FROM users WHERE email = ?", (form["email"],), one=True):
            errors.append("This email is already registered. Please log in.")

        if not errors:
            try:
                user_id = insert_user(form["name"], form["email"], form["phone"], password)
            except sqlite3.IntegrityError:
                errors.append("This email is already registered. Please log in.")
            else:
                user = db_query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
                start_session(user)
                flash(f"Welcome to Lotus Cart, {user['name'].split()[0]}! 🌸", "success")
                return redirect(safe_next(next_url))

        for message in errors:
            flash(message, "error")

    return render_template("register.html", form=form, next_url=next_url)


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.values.get("next", "")
    if g.user:
        return redirect(safe_next(next_url))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        cutoff = (datetime.now() - timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        failures = db_query(
            "SELECT COUNT(*) AS n FROM login_log WHERE email = ? AND success = 0 AND created_at >= ?",
            (email, cutoff), one=True)["n"]

        if failures >= MAX_FAILED_LOGINS:
            flash(f"Too many failed attempts. Please try again after {LOCK_MINUTES} minutes.", "error")
        else:
            user = db_query("SELECT * FROM users WHERE email = ?", (email,), one=True)
            if user and check_password_hash(user["password_hash"], password):
                start_session(user)
                flash(f"Welcome back, {user['name'].split()[0]}!", "success")
                return redirect(safe_next(next_url))
            log_login(user["id"] if user else None, email, False)
            flash("Invalid email or password.", "error")

    return render_template("login.html", next_url=next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


# ======================= Admin =======================
@app.route("/admin")
@login_required
@admin_required
def admin_page():
    stats = {
        "users": db_query("SELECT COUNT(*) AS n FROM users", one=True)["n"],
        "orders": db_query("SELECT COUNT(*) AS n FROM orders", one=True)["n"],
        "placed": db_query("SELECT COUNT(*) AS n FROM orders WHERE status = 'Placed'", one=True)["n"],
        "cancelled": db_query("SELECT COUNT(*) AS n FROM orders WHERE status = 'Cancelled'", one=True)["n"],
        "revenue": db_query("SELECT COALESCE(SUM(total), 0) AS n FROM orders WHERE status = 'Placed'",
                            one=True)["n"],
    }
    users = db_query("SELECT * FROM users ORDER BY id DESC")
    logins = db_query(
        """SELECT l.*, u.name AS user_name FROM login_log l
           LEFT JOIN users u ON u.id = l.user_id ORDER BY l.id DESC LIMIT 100""")
    orders = db_query(
        """SELECT o.*, u.name AS user_name, u.email AS user_email FROM orders o
           LEFT JOIN users u ON u.id = o.user_id ORDER BY o.id DESC LIMIT 100""")
    return render_template("admin.html", stats=stats, users=users, logins=logins, orders=orders)


def lan_ip():
    """Local network address, so family on the same WiFi can open the site."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "thamaraibharani0908@gmail.com").strip().lower()

init_db()

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")      # 0.0.0.0 = reachable from other devices on your WiFi
    port = int(os.getenv("PORT", "5000"))
    print("\n  Open on this PC : http://127.0.0.1:%d/" % port)
    print("  Family (same WiFi): http://%s:%d/\n" % (lan_ip(), port))
    Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    app.run(host=host, port=port, debug=False)