"""
Central place for all environment/config values.
Add new settings here as your app grows so nobody has to grep for os.getenv().
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")


settings = Settings()
