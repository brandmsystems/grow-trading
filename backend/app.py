"""Grow Trading backend entry point.

Run from the backend folder:  python app.py   (or use start.py in the project root)
"""
from app.main import app
from app.api.realtime import PORT, socketio

if __name__ == "__main__":
    # Werkzeug with threads serves both HTTP and the Socket.IO WebSocket (simple-websocket).
    # Local use only (127.0.0.1), hence allow_unsafe_werkzeug.
    socketio.run(app, host="127.0.0.1", port=PORT, debug=False, allow_unsafe_werkzeug=True)
