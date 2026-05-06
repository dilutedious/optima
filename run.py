"""Launcher — `python run.py`."""

from app.main import create_app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5050, debug=True)
