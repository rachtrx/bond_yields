import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)
print(f" Live in app: {os.environ.get('LIVE')}")

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:

    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'bond.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False