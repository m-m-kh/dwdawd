from cryptography.fernet import Fernet
import os
from drive import GoogleDrive
from motor.motor_asyncio import AsyncIOMotorClient
from motor.motor_asyncio import AsyncIOMotorCollection
import asyncio
from aiofiles import os as aioos
from pathlib import Path
import shutil
from dotenv import load_dotenv
import redis

load_dotenv()

CONFIG = Path('./config/')
TMP = CONFIG.joinpath('users/tmp/')
CREDS = CONFIG.joinpath('users/creds/')


CONFIG.mkdir(exist_ok=True)
TMP.mkdir(exist_ok=True)
CREDS.mkdir(exist_ok=True)

DEBUG = bool(os.getenv('DEBUG'))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MONGO_URL = 'mongodb://localhost:27017' if DEBUG else os.getenv("ME_CONFIG_MONGODB_URL")
REDIS_HOST = 'localhost' if DEBUG else os.getenv("REDIS_HOST")
REDIS_PORT = 6379 if DEBUG else int(os.getenv("REDIS_PORT"))
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_ID = os.getenv("BOT_ID")
DOMAIN = os.getenv("DOMAIN")


mg = AsyncIOMotorClient(MONGO_URL)
db:AsyncIOMotorCollection = mg['database']
users_status = db['users_status']
bot_status = db['bot_status']
users_cred = db['users_cred']

redis_cli = redis.asyncio.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)



async def reset_user_data():
    
    async def remove_file(file):
        try:
            await asyncio.to_thread(Path(file).unlink)
        except PermissionError:
            await asyncio.sleep(2)
            await remove_file(file)

    tasks = []
    for file in TMP.rglob('*.*'):
        tasks.append(remove_file(file))

    tasks.append(users_status.update_many({},{"$set":{"in_queue":0}}))
    
    await asyncio.gather(*tasks)


def size_convertor(size):
    size = int(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    
    for unit in units:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024

    return f"{size:.2f}PB"
    
    
def generate_private_key():
    if not os.path.exists(CONFIG.joinpath('private.key')):
        key = Fernet.generate_key()
        with open(CONFIG.joinpath('private.key'), "wb") as key_file:
            key_file.write(key)
            fernet = Fernet(key)
    else:
        with open(CONFIG.joinpath('private.key'), "rb") as f:
            key = f.read()
            fernet = Fernet(key)
    return fernet
    
FERNET = generate_private_key()

LOCK = asyncio.Lock()
async def check_disk_space(file_size):
    async with LOCK:
        free_space = float(shutil.disk_usage(__file__).free)
        if free_space < file_size:
            await asyncio.sleep(5)
            await check_disk_space(file_size, LOCK)
        return