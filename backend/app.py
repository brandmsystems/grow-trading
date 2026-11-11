"""Grow Trading backend entry point.

Run from the backend folder:  python app.py   (or use start.py in the project root)
"""
from app.main import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
