# main.py
# Responsibility: Application entry point — creates the Flask app and starts the server.
# Import this module to get the app instance; run directly to start development server.

from app import create_app

app = create_app()

if __name__ == '__main__':
    import os
    port = int(os.environ.get('FLASK_PORT', 8425))
    app.run(host='127.0.0.1', port=port, debug=False)
