from flask import Flask
from flask_login import LoginManager

login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.secret_key = "super-secret-key"

    # подключаем login_manager к приложению
    login_manager.init_app(app)
    login_manager.login_view = "login"

    return app
