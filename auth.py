from sanic import Sanic, response, redirect
 
import os
from aiofiles import os as aioos

from aiogoogle import Aiogoogle

import json


from cryptography.fernet import InvalidToken

from telethon import TelegramClient

from telethon.sessions import MemorySession

from drive import GoogleDrive


import asyncio
from utils import (size_convertor, users_cred,
                      bot_status, users_status, CONFIG,
                     BOT_TOKEN, BOT_ID, DOMAIN, FERNET,
                     CREDS, TMP
)


client = TelegramClient('auth', api_id=436151, api_hash='edeede532275d4107f79411b37cb3f41')


with open(CONFIG.joinpath('web.json'), 'r') as f:
    config = json.load(f)
    CLIENT_CREDS = {
        "client_id": config["web"]["client_id"],
        "client_secret": config["web"]["client_secret"],
        "scopes": ["https://www.googleapis.com/auth/drive.file"],
        "redirect_uri":f"http://localhost/callback/"
        # "redirect_uri":f"http://{DOMAIN}/callback/"
        }




app = Sanic(__name__)
aiogoogle = Aiogoogle()

@app.route('/authorize/login/')
def authorize(request):
    try:
        user_id = FERNET.decrypt(request.args['q'][0].encode()).decode()
    except InvalidToken:
        return response.text('دسترسی رد شد',status=401)
    
    
    if os.path.exists(CREDS.joinpath(f'{user_id}.json')):
        return response.text('⚠️ در حال حاضر درایو شما به ربات متصل است')
    else:
        uri = aiogoogle.oauth2.authorization_url(
            client_creds=CLIENT_CREDS,
            access_type='offline',
            prompt='consent',
            state=request.args['q'][0]
        )
        return response.redirect(uri)
        # return response.text('ok')



@app.route('/callback/')
async def callback(request):
    try:
        user_id = int(FERNET.decrypt(request.args['state'][0].encode()).decode())
    except InvalidToken:
        return response.text('Forbidden',status=401)
    
    if os.path.exists(CONFIG.joinpath(f'{user_id}.json')):
        return response.text('⚠️ در حال حاضر درایو شما به ربات متصل است')
    
    if request.args.get('error'):
        error = {
            'error': request.args.get('error'),
            'error_description': request.args.get('error_description')
        }
        return response.json(error)

    # Here we request the access and refresh token
    elif grant:=request.args.get('code'):
        full_user_creds = await aiogoogle.oauth2.build_user_creds(
            grant = grant,
            client_creds = CLIENT_CREDS
        )
        # Here, you should store full_user_creds in a db. Especially the refresh token and access token.
        with open(CREDS.joinpath(f'cache_{user_id}.json'), 'w') as f:
            json.dump(full_user_creds, f)
        
        gd = GoogleDrive(CONFIG.joinpath('web.json'))
        user_drive = await gd.login(CREDS.joinpath(f'cache_{user_id}.json'))
        gmail = await user_drive.get_drive_info()
        gmail = gmail['user']['emailAddress']

        if await bot_status.find_one({'id':'bot', "gmails": gmail}):
            await aioos.remove(CREDS.joinpath(f'cache_{user_id}.json'))
            return response.text('⚠️ درایو شما به اکانتی دیگر متصل است\nاز درایو دیگری استفاده کنید')

        await aioos.rename(CREDS.joinpath(f'cache_{user_id}.json'), CREDS.joinpath(f'{user_id}.json'))
            
        if not (await user_drive.get_folder_by_name('DriveFile')):
            folder = await user_drive.create_folder('DriveFile')
            await user_drive.create_permission(folder['id'])
        
        task = [users_cred.update_one({'id':user_id},{'$set':{'cred':full_user_creds}}),
                bot_status.update_one({'id':'bot'},{"$push":{'gmails':gmail}}),
                users_status.update_one({'id': user_id, 'status': False}, {'$set': {'status': True}}),
                client.send_message(user_id, '🎉 تبریک درایو شما با موفقیت متصل شد'),
                ]

        user_db = await users_status.find_one({'id':user_id})
        if user_db.get('refferaled'):
            referral_bonus = (await bot_status.find_one({'id':"bot"})).get('referral_bonus', 0)
            task.extend([users_status.update_one({'id':user_db['refferaled']},{'$inc':{'transfer_remaining':referral_bonus}}),
                         client.send_message(user_db['refferaled'], f"🎉 تبریک {size_convertor(referral_bonus)} به اکانت شما بابت عضویت زیر مجموعه افزوده شد.")])

        await asyncio.gather(*task)
        
        return redirect(f'https://t.me/{BOT_ID}')
        

    else:
        # Should either receive a code or an error
        return response.text("Something's probably wrong with your callback")



if __name__ == "__main__":
    async def main():
        await client.connect()
        
        server = await app.create_server(host='0.0.0.0', port=8080)
        await server.startup()
        await server.serve_forever()

    asyncio.run(main())