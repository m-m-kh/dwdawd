from telethon import TelegramClient, Button
from telethon import events
from telethon.errors import UserNotParticipantError
from telethon.tl.functions.channels import GetParticipantRequest, GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.tl.patched import Message
from telethon.sessions import MemorySession

import os
from aiofiles import os as aioos
import aiofiles
import asyncio
import shutil

from tqdm.asyncio import tqdm_asyncio


import json
import re
import zoneinfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from utils import (size_convertor, users_cred,
                    bot_status, users_status,
                    ADMIN_ID, FERNET,
                     BOT_TOKEN, BOT_ID, DOMAIN,
                     CONFIG, TMP, CREDS,
                     redis_cli, reset_user_data, check_disk_space
)
from drive import GoogleDrive



semaphore = asyncio.Semaphore(4)

download_tasks = dict()

WELECOME_MSG = """👋 سلام به DriveFile خوش آمدید!

📥 با این سرویس، شما می‌توانید هر نوع فایل تلگرامی را از جمله ویدئو، سند، عکس، صدا و گیف را به راحتی در گوگل درایو آپلود کرده و لینک دانلود آن را دریافت کنید.

🚀 از این امکان بهره‌مند شوید و تجربه ارسال و دریافت فایل‌هایتان را با سرعت و کارایی بیشتری تجربه کنید. در صورت نیاز به راهنمایی بیشتر، /help کلیک کنید."""



client = TelegramClient('bot', api_id=436151, api_hash='edeede532275d4107f79411b37cb3f41')
client.start(bot_token=BOT_TOKEN)

asyncio.get_event_loop().run_until_complete(reset_user_data())
client.loop.run_until_complete(client.send_message(ADMIN_ID, 'starting....'))
# check \config\users path

bot_status.update_one({"id":'bot'},{'$setOnInsert':{'users_count':0, "new_users":0 ,'total_transfered':0,
                                            "today_transfered":0, 'download_count':0, "today_download_count":0,
                                            "referral_bonus":1073741824, "change_join_bonus":1073741824,
                                            "verify_phone": False,"channels":[],
                                            "join_channel":False, 'gmails':[]}}, upsert=True)

############ Check Drive Cred ###########

async def check_drive_cred(event, msg:Message, login=False):
    if not await aioos.path.exists(CREDS.joinpath(f'{event.chat_id}.json')):
        if not login:
            await msg.reply('⚠️ درایو متصلی به ربات وجود ندارد.\nبرای ورود /login کلیک کنید')
        return False
    return True


########## Check joined channel ###########
async def check_joined_channel(event:events.CallbackQuery.Event, is_callback_query=False):
    bot_db = await bot_status.find_one()
    if not bot_db["join_channel"] or not bot_db["channels"]:
        return True

    buttons = []

    channel_ids = bot_db["channels"]
    
    checked_channels = [client(GetParticipantRequest(id,event.chat_id)) for id in channel_ids]
    checked_channels = await asyncio.gather(*checked_channels, return_exceptions=True)

    for channel_id, channel in zip(channel_ids, checked_channels):
        if isinstance(channel, Exception):
            buttons.append([Button.url('عضویت',url=f"https://t.me/{channel_id}")])
            
    if buttons:
        buttons.append([Button.inline('عضو شدم',data='confirm_joined_channel')])
        if is_callback_query:
            await asyncio.gather(event.answer('⚠️ لطفا در تمام کانال ها عضو شوید', alert=True),
                                 event.edit('⚠️ برای ادامه کار با ربات حتما عضو کانال زیر بشین',buttons=buttons),
                                 return_exceptions=True)
        else:
            await event.reply('⚠️ برای ادامه کار با ربات حتما عضو کانال زیر بشین', buttons=buttons)
        return False
    return True

@client.on(events.CallbackQuery(data='confirm_joined_channel'))
async def confirm_joined_channel_button(event:events.CallbackQuery.Event):
    if (await check_joined_channel(event, is_callback_query=True)) is False:
        return

    await event.edit(
        WELECOME_MSG)


########## Check Phone Number ###########
async def check_phone_number(event:events.NewMessage.Event, is_callback_query=False):
    bot_db = await bot_status.find_one()
    if not bot_db["verify_phone"]:
        return True

    user_db = await users_status.find_one({"id":event.chat_id})
    if not user_db["phone_status"]:
        buttons = [[Button.request_phone("ارسال شماره", resize=True, single_use=True)]]
        if is_callback_query:
            await event.delete()
        await event.message.reply("‼️ به منظور ادامه خدمات، لطفاً شماره اکانت خود را به اشتراک بگذارید. این اطلاعات صرفاً جهت تایید هویت ایرانی شما استفاده می‌شود و به هیچ عنوان در دیتابیس ذخیره نخواهد شد. حریم خصوصی شما برای ما بسیار حائز اهمیت است. با اعتماد به این فرآیند، می‌توانید به راحتی از خدمات ما بهره‌مند شوید.",
                                        buttons=buttons)
        return False
    return True

@client.on(events.NewMessage(incoming=True))
async def verify_phone_number(event:events.NewMessage.Event):
    msg:Message = event.message
    
    if not msg.contact:
        return
    
    bot_db = await bot_status.find_one()
    if not bot_db["verify_phone"]:
        return

    user_db = await users_status.find_one({"id":event.chat_id})
    if user_db["phone_status"]:
        return
    
    contact_id = msg.contact.user_id
    user_id = event.chat_id
    if contact_id != user_id:
        await msg.reply("⚠️ لطفا فقط از دکمه زیر استفاده کنید")
        return

    phone_number = msg.contact.phone_number
    if not re.search(r"^(?:\+98|98)\d{10}$",phone_number):
        await msg.reply("⚠️ شماره ایرانی نیست")
        return

    await users_status.update_one({"id":event.chat_id},{"$set":{"phone_status":True}})
    await msg.reply(
        WELECOME_MSG)


########### Start Bot ############
@client.on(events.NewMessage(pattern='^/start', incoming=True))
async def start(event:events.NewMessage.Event):
    msg:Message = event.message

    args = msg.raw_text.split(' ')

    # create user space folder
    if not await users_status.find_one({"id":event.chat_id}):
        try:
            ref = int(args[1])
        except:
            ref = None
        bot_db = await bot_status.find_one()
        user_dict = {
                "id":event.chat_id,
                'username':(await msg.get_sender()).username,
                'total_transfered':0,
                'today_transfered':0,
                'transfer_remaining':bot_db["change_join_bonus"],
                'referrals':[],
                'refferaled':None,
                'in_queue':0,
                'status': False,
                'phone_status': False
                                    }
        tasks = [
                users_cred.insert_one(
                {"id":event.chat_id,'cred':''}
                                    ),
                bot_status.update_one(
                {"id":'bot'},
                {'$inc':{'users_count':+1, "new_users":+1}}
                                    )
                ]
        if ref and await users_status.find_one({"id":ref}):
            user_dict['refferaled'] = ref
            tasks.append(
                users_status.update_one(
            {"id":ref},{'$push':{'referrals':event.chat_id}})
                )
        
        tasks.append(users_status.insert_one(user_dict))


        await asyncio.gather(
            *tasks
            )
    
    if ((await check_phone_number(event)) is False) or ((await check_joined_channel(event)) is False):
        return



    await msg.reply(
        WELECOME_MSG,
    )

############## Help #################
@client.on(events.NewMessage(pattern='^/help$', incoming=True))
async def help(event:events.NewMessage.Event):
    msg:Message = event.message
    await msg.reply("""نحوه اتصال Google Drive به ربات:
🔗 لینک ورود خود را از /login دریافت کنید.
🔗 به صفحه ورود بروید، با حساب Google Drive خود وارد شوید، دسترسی ها را مجاز کنید و تمام! 🎉

🔴 برای خروج از حساب Google Drive فعلی از /logout استفاده کنید.

🔺 /status - مشاهده اطلاعات و حجم باقی مانده در ربات و درایو
🔺 /my_referral - دریافت لینک معرف
🔺 /my_files - مشاهده فایل های آپلود شده توسط ربات
🔺 /delete_all - حذف تمام فایل های آپلود شده توسط ربات""")






# ############login & logout#############
@client.on(events.NewMessage(pattern='^/login$', incoming=True))
async def login(event:events.NewMessage.Event):
    msg: Message = event.message
    # check user login
    if ((await check_joined_channel(event)) is False
        or (await check_phone_number(event)) is False):
        return

    if (await check_drive_cred(event, msg, login=True)) is True:
        await msg.reply('⚠️ در حال حاضر درایو شما به ربات متصل است.')
        return

    # create user login url key
    secure_id = FERNET.encrypt(str(event.chat_id).encode()).decode()
    buttons = [Button.url('LogIn', url=f'http://{DOMAIN}/authorize/login/?q=' + secure_id)]
    
    bot_db = await bot_status.find_one()
    await msg.reply(f"""نحوه اتصال Google Drive به ربات:
🔗 لینک ورود خود را از  /login دریافت کنید.
🔗 به صفحه ورود بروید، با حساب Google Drive خود وارد شوید، دسترسی ها را مجاز کنید و {size_convertor(bot_db["change_join_bonus"])} ترافیک دریافت کنید! 🎉

⚠️ کاربران با ترافیک کمتر از {size_convertor(bot_db["change_join_bonus"])} ترافیک آنها مجدد به مقدار {size_convertor(bot_db["change_join_bonus"])} در پایان روز شارژ میشود.
""", buttons=buttons)


@client.on(events.NewMessage(pattern='^/logout$', incoming=True))
async def logout(event:events.NewMessage.Event):
    msg:Message = event.message
    if ((await check_joined_channel(event)) is False or
        (await check_phone_number(event)) is False):
        return
    
    user = await users_status.find_one({'id':event.chat_id})
    if user['in_queue']:
        await msg.reply('امکان خروج از درایو وجود ندارد\nیک فایل در صف دانلود قرار دارد.')
        return

    if (await aioos.path.exists(CREDS.joinpath(f'{event.chat_id}.json'))) is True:
        GD = GoogleDrive(CONFIG.joinpath('web.json'))
        user_dr = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
        user_dr = await user_dr.get_drive_info()
        gmail = user_dr['user']['emailAddress']
        await asyncio.gather(
            msg.reply('⚠️ درایو شما با موفقیت از ربات خارج شد.'),
            aioos.remove(CREDS.joinpath(f'{event.chat_id}.json')),
            users_cred.update_one({"id":event.chat_id},{"$set":{'cred':''}}),
            bot_status.update_one({"id":'bot'},{'$pull':{'gmails':gmail}}),
            users_status.update_one({"id":event.chat_id},{"$set":{"in_queue":0}}),
            return_exceptions=True
            )
        return

    await msg.reply('''⚠️ درایو متصلی به ربات وجود ندارد.
برای ورود /login کلیک کنید''')
############login & logout#############


############drive manager section#############
@client.on(events.NewMessage(pattern='^/status$', incoming=True))
async def status(event:events.NewMessage.Event):
    msg:Message = event.message
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, msg)) is False):
        return

    GD = GoogleDrive(CONFIG.joinpath('web.json'))
    user_dr = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
    user_dr_info, user_db = await asyncio.gather(
        user_dr.get_drive_info(),
        users_status.find_one({"id":event.chat_id})
        )

    await msg.reply(f"""🌟 نام: {user_dr_info['user']['displayName']}
📧 جیمیل: {user_dr_info['user']['emailAddress']}
💽 کل حجم: {size_convertor(user_dr_info['storageQuota']['limit'])}
📤 حجم مصرف شده: {size_convertor(user_dr_info['storageQuota']['usageInDrive'])}
📥 حجم باقی مانده: {size_convertor(float(user_dr_info['storageQuota']['limit'])-float(user_dr_info['storageQuota']['usageInDrive']))}
🌐 ترافیک باقی مانده ربات: {size_convertor(user_db['transfer_remaining'])}""")

@client.on(events.NewMessage(pattern='^/my_files$', incoming=True))
async def my_files(event:events.NewMessage.Event):
    # context.user_data['current_page'] = 0

    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, event.message)) is False):
        return
    
    
    GD = GoogleDrive(CONFIG.joinpath('web.json'))
    user_dr = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
    folder_id = await user_dr.get_folder_by_name('DriveFile')
    buttons = [[Button.inline('name', data='None'),Button.inline('size', data='None')]]

    data = await user_dr.get_files_list_in_folder(folder_id[0]["id"], page_size=10)

    files = data['files']
    

    for file in files:
        buttons.append([Button.inline(file['name'], data='id:'+file["id"]),
                          Button.inline(size_convertor(file['size']), data='None')])

    next_page = data.get('nextPageToken')
    
    if next_page:
        buttons.append([Button.inline('صفحه بعد', data='next_page')])

    user_cache = await redis_cli.hget(event.chat_id, 'my_file_msg_id')
    if msg_id := user_cache:
        await client.delete_messages(event.chat_id, msg_id)

    msg = await event.message.reply("""**فایل‌های آپلود شده:**
    برای دسترسی بیشتر روی اسم فایل کلیک کنید 📂👇""" , buttons=buttons)

    mapping = {'pages':json.dumps([next_page]),
               'my_file_msg_id':msg.id}
    
    await redis_cli.hsetex(event.chat_id, mapping=mapping)
    await redis_cli.expire(event.chat_id, 1800)


@client.on(events.CallbackQuery(data='next_page'))
async def next_page(event:events.CallbackQuery.Event):
    query:Message = event.query

    if ((await check_joined_channel(event) is False or
         (await check_phone_number(event))) is False or
            (await check_drive_cred(event, query)) is False):
        return
    
    GD = GoogleDrive(CONFIG.joinpath('web.json'))
    user_dr = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
    folder_id = await user_dr.get_folder_by_name('DriveFile')
    buttons = [
        [Button.inline('name', data='None'), Button.inline('size', data='None')]
        ]

    pages = json.loads(await redis_cli.hget(event.chat_id, 'pages'))
    next_page = pages[-1]
    data = await user_dr.get_files_list_in_folder(folder_id[0]["id"],
                                                  page_size=10,
                                                  next_page_token=next_page)

    files = data['files']

    for file in files:
        buttons.append([Button.inline(file['name'], data='id:' + file["id"]),
                         Button.inline(size_convertor(file['size']), data='None')])

    buttons.append([Button.inline('صفحه قبل', data='previous_page')])

    next_page_token = data.get('nextPageToken')
    if next_page_token:
        pages.append(next_page_token)
        buttons.append([Button.inline('صفحه بعد', data='next_page')])
    else:
        pages.append(False)
    
    await redis_cli.hset(event.chat_id, 'pages', json.dumps(pages))
    await event.edit(buttons=buttons)
    
@client.on(events.CallbackQuery(data='previous_page'))
async def previous_page(event:events.CallbackQuery.Event):
    query:Message = event.query

    if ((await check_joined_channel(event) is False or
         (await check_phone_number(event))) is False or
            (await check_drive_cred(event, query)) is False):
        return
    
    GD = GoogleDrive(CONFIG.joinpath('web.json'))
    user_dr = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
    folder_id = await user_dr.get_folder_by_name('DriveFile')
    buttons = [
        [Button.inline('name', data='None'), Button.inline('size', data='None')]
        ]

    pages = json.loads(await redis_cli.hget(event.chat_id, 'pages'))
    if len(pages) == 2:
        data = await user_dr.get_files_list_in_folder(folder_id[0]["id"],
                                                      page_size=10)
    else:
        next_page = pages[-3]
        data = await user_dr.get_files_list_in_folder(folder_id[0]["id"],
                                                  page_size=10,
                                                  next_page_token=next_page)

    pages.pop()
    files = data['files']

    for file in files:
        buttons.append([Button.inline(file['name'], data='id:' + file["id"]),
                         Button.inline(size_convertor(file['size']), data='None')])


    if len(pages) >= 2 :
        buttons.append([Button.inline('صفحه قبل', data='previous_page')])

    buttons.append([Button.inline('صفحه بعد', data='next_page')])

    await redis_cli.hset(event.chat_id, 'pages', json.dumps(pages))
    await event.edit(buttons=buttons)

@client.on(events.CallbackQuery(pattern='^id:'))
async def file_details(event:events.CallbackQuery.Event):
    query = event.query
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, query)) is False):
        return
    
    file_id = event.data.decode()[3:]
    GD = GoogleDrive(CONFIG.joinpath('web.json'))
    user_dr = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
    file = await user_dr.get_file_by_id(file_id)
    buttons = [[Button.url('🔗 لینک دانلود', url=file['webContentLink']),
                Button.inline('🗑 حذف', data=f"check_delete:{file_id}")]]

    await event.reply(f'📝 نام فایل: {file["name"]}\n💾 سایز: {size_convertor(file["size"])}', buttons=buttons)

############file manager section#############


# ############File deletion section#############
@client.on(events.CallbackQuery(pattern='^check_delete:'))
async def check_delete_file(event:events.CallbackQuery.Event):
    query = event.query
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, query)) is False):
        return

    file_id = event.data.decode()[13:]

    buttons = [[Button.inline('🗑 حذف', data=f'ok_delete:{file_id}'), Button.inline('❌ لغو',data='cancel_del')]]

    await event.edit('🗑️🤔 آیا مطمئن هستید که می‌خواهید این فایل را حذف کنید؟', buttons=buttons)

@client.on(events.CallbackQuery(pattern='^ok_delete:'))
async def ok_delete_file(event:events.CallbackQuery.Event):
    query = event.query
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, query)) is False):
        return


    file_id = event.data.decode()[10:]
    GD = GoogleDrive(CONFIG.joinpath('web.json'))
    user_dr = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
    await user_dr.delete_item(file_id)

    await event.edit('✌️ فایل با موفقیت حذف شد.')

@client.on(events.CallbackQuery(data='cancel_del'))
async def cancel_del(event:events.CallbackQuery.Event):
    query = event.query
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, query)) is False):
        return
    
    await event.edit("❌ لغو شد")

@client.on(events.NewMessage(pattern='^/delete_all$', incoming=True))
async def check_delete_all(event:events.NewMessage.Event):
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, event.message)) is False):
        return
    buttons = [[Button.inline('🗑 حذف', data='delete_all'),
                 Button.inline('❌ لغو', data='cancel_del')]]

    await event.message.reply("آیا مطمئن هستید که می‌خواهید تمام فایل ها را حذف کنید؟ 🗑️🤔", buttons=buttons)

@client.on(events.CallbackQuery(data='delete_all'))
async def ok_delete_all(event:events.CallbackQuery.Event):
    query = event.query
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, query)) is False):
        return
    GD = GoogleDrive(CONFIG.joinpath('web.json'))
    user_dr = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
    folder_id = await user_dr.get_folder_by_name('DriveFile')
    files = await user_dr.get_files_list_in_folder(folder_id[0]["id"])
    tasks = [user_dr.delete_item(file["id"]) for file in files['files'] ]
    await asyncio.gather(*tasks)
    
    await event.edit('✌️تمامی فایل ها با موفقیت حذف شدن.')



# ############File deletion section#############



# ############Upload file section#############
@client.on(events.NewMessage)
async def file_status(event:events.NewMessage.Event):
    msg:Message = event.message
    if not msg.file:
        return
    
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, event.message)) is False):
        return
    
    
    
    file_name = msg.file.name if msg.file.name else f'{msg.id}{msg.file.ext}'
    file_size = msg.file.size
    file_type = msg.file.mime_type

    buttons = [
            [Button.inline('آپلود ✅', data=f'confirm_{file_size}')],
            [Button.inline('لغو ❌', data='cancel')]
        ]
    await msg.reply(f"""📝 نام فایل : {file_name}
    🗂 نوع فایل : {file_type}
    💾 سایز : {size_convertor(file_size)}""",
        buttons=buttons)

@client.on(events.CallbackQuery(pattern='^confirm_'))
async def confirm(event:events.CallbackQuery.Event):
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, event.query)) is False):
        return

    file_size = float(event.data.decode().split('_')[1])
    GD = GoogleDrive(CONFIG.joinpath('web.json'))
    user_dr = await GD.login(CREDS.joinpath(f"{event.chat_id}.json"))
    user_dr = await user_dr.get_drive_info()

    if float(user_dr['storageQuota']['limit'])-float(user_dr['storageQuota']['usageInDrive'])<file_size:
        await event.edit("فضای کافی در درایو شما وجود ندارد.")
        return

    user_db = await users_status.find_one({"id":event.chat_id})

    if user_db['transfer_remaining'] < file_size:
        await event.edit(f"⚠️ حجم ترافیک شما کافی نیست\n💢 ترافیک باقی مانده ربات: {size_convertor(user_db['transfer_remaining'])}")
        return

    in_queue = user_db['in_queue']
    if in_queue:
        await event.edit('🔴 یک فایل در صف آپلود قرار دارد لطفا تا اتمام فرایند صبر کنید')
        return

    query:Message = event.query
    # start download
    
    msg = await event.get_message()
    file_msg:Message = await client.get_messages(event.chat_id, ids=msg.reply_to_msg_id)
    
    file_name = file_msg.file.name if file_msg.file.name else f'{file_msg.id}{file_msg.file.ext}'
    file_size = file_msg.file.size
    file_type = file_msg.file.mime_type

    
    await users_status.update_one({'id': event.chat_id}, {'$set': {'in_queue': 1}})
    file_detail = """📝 نام فایل : {}
🗂 نوع فایل : {}
💾 سایز : {}"""

    try:
        file_detail = file_detail.format(file_name, file_type, size_convertor(file_size))
        task = asyncio.current_task()
        task_name = task.get_name()
        download_tasks.update({task_name:task})
        
        buttons = [
            Button.inline('لغو', data='cancel_proccess_'+task_name)
        ]
        
        await event.edit(file_detail, buttons=buttons)
      
        async with semaphore:
            await check_disk_space(file_size)
            print(semaphore)

            # Downloading File


            p = [0, 0]
            t = tqdm_asyncio(total=file_size, unit='B', unit_scale=True,
                 bar_format="تکمیل شده: {percentage:3.0f}% | سرعت: {rate_fmt} | زمان باقی مانده: {remaining}")
            async def progress(current, total):
                nonlocal p
                nonlocal t
                t.update(current - p[1])
                p[1] = current
                if (current >= p[0]):
                    p[0] += total / 10
                    try:
                        await event.edit(
                            file_detail + f'\n\nدرحال دریافت فایل از سرور تلگرام: \n'+\
                            f'\n{t}', buttons=buttons)
                    except:
                        pass

            await event.edit(file_detail + f'\n\nدرحال دریافت فایل از سرور تلگرام: \n'+\
                                            f'\n{t}', buttons=buttons)
            # client.get_file()
            await asyncio.wait_for(
                file_msg.download_media(TMP.joinpath(f'{event.chat_id}/{file_name}'), progress_callback=progress),
                timeout=900
            )
            GD = GoogleDrive(CONFIG.joinpath('web.json'))
            user_drive = await GD.login(CREDS.joinpath(f'{event.chat_id}.json'))
            folder_id = await user_drive.get_folder_by_name('Drivefile')
            if not folder_id:
                folder_id = (await user_drive.create_folder("Drivefile"),)
                await user_drive.create_permission(folder_id[0]['id'])

            # Uploading File
            p = [0]
            t = tqdm_asyncio(total=file_size, unit='B', unit_scale=True,
                     bar_format="تکمیل شده: {percentage:3.0f}% | سرعت: {rate_fmt} | زمان باقی مانده: {remaining}")
            async def process():
                chunk_size = 1024**2
                current = 0
                async with aiofiles.open(TMP.joinpath(f'{event.chat_id}/{file_name}'), 'rb') as f:
                    while True:
                        chunk = await f.read(chunk_size)
                        if not chunk:  # یعنی به انتهای فایل رسیدیم
                            break
                        yield chunk 
                        l_chunk = len(chunk)
                        current += l_chunk
                        t.update(l_chunk)
                        if (current >= p[0]):
                            p[0] += file_size / 10
                            try:
                                await event.edit(
                                    file_detail + f'\n\nدرحال آپلود در درایو شما: \n'+\
                                    f'\n{t}', buttons=buttons)
                            except:
                                pass
                                
                await event.edit(
                    file_detail + f'\n\nدر حال دریافت لینک دانلود...', buttons=buttons)
            

            file = await asyncio.wait_for(
                user_drive.upload_by_chunk(process(), file_name, folder_id=folder_id[0]['id']),
                timeout=900
            )

            await asyncio.gather(
                users_status.update_one({'id': event.chat_id},
                                        {'$inc': {
                                            'transfer_remaining': -file_size,
                                            'today_transfered': +file_size,
                                            'total_transfered': +file_size,
                                        }}),
                bot_status.update_one({'_id': 'bot'},
                                      {'$inc': {
                                          'total_transfered': +file_size,
                                          'today_transfered': +file_size,
                                          'download_count': +1,
                                          "today_download_count": +1}})
            )

            buttons = [Button.url('لینک دانلود', url=file["webContentLink"])]
            
            user_db = await users_status.find_one({"id": event.chat_id})
            await event.edit(text=f"""📝 نام فایل : {file["name"]}
    💾 سایز : {size_convertor(file_size)}
    💽 ترافیک باقی مانده ربات: {size_convertor(user_db['transfer_remaining'])}""", 
                                            buttons=buttons),

        print('uploading')
    except TimeoutError as e:
        await event.edit('🔴 زمان آپلود فایل بیش از حد طول کشید، لطفاً دوباره تلاش کنید.')
    
    except Exception as e:
        await event.edit('🔴 خطایی رخ داد. لطفاً دوباره تلاش کنید.')
        log = f"error msg: {e}\n user_id: {event.chat_id}\n"
        await client.send_message(ADMIN_ID, log)
        # await API_BOT.send_document(chat_id=ADMIN_ID, document=file_id)
    except asyncio.exceptions.CancelledError:
        await event.edit(file_detail+'\n\n 🚫 آپلود فایل لغو شد.')
    finally:
        download_tasks.pop(task_name, None)
        async def remove_file(path):
            try:
                await os.remove(path)
            except PermissionError:
                await asyncio.sleep(2)
                await remove_file(path)

        await asyncio.gather(
            asyncio.wait_for(remove_file(TMP.joinpath(f'{event.chat_id}/{file_name}')),60),
            users_status.update_one({'id': event.chat_id},{'$set': {'in_queue': 0}}
        ), return_exceptions=True)

@client.on(events.CallbackQuery(pattern='^cancel_proccess_'))
async def cancel_proccess_task(event:events.CallbackQuery.Event):
    task_name = event.data.decode().split('_')[-1]
    task = download_tasks.get(task_name, None)
    if task:
        task.cancel()
    ''.split()


@client.on(events.CallbackQuery(data='cancel'))
async def cancel(event:events.CallbackQuery.Event):
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, event.query)) is False):
        return

    await event.edit('🚫 آپلود فایل لغو شد.')

@client.on(events.NewMessage(pattern='^/my_referral$', incoming=True))
async def my_referral(event:events.NewMessage.Event):
    if ((await check_joined_channel(event) is False or
        (await check_phone_number(event))) is False or
        (await check_drive_cred(event, event.message)) is False):
        return

    bot_db = await bot_status.find_one()

    await event.message.reply(f"""لینک زیرمجموعه‌گیری شما:
`https://t.me/{BOT_ID}?start={event.chat_id}`

🌐💾 مقدار {size_convertor(bot_db["referral_bonus"])} بعد از عضویت و متصل کردن درایو توسط کاربر به شما افزوده خواهد شد.""")


# ########### Admin section ############

admin_buttons = [
        [Button.inline('تغییر حجم کاربر',data='change_user_traffic'),
         Button.inline('تغییر حجم رفرال',data='change_referral_bonus')],
        [Button.inline('تغییر حجم عضویت',data='change_join_bonus'),
         Button.inline('احراز شماره همراه ایرانی',data='toggle_phone_verification_stage_1')],
        [Button.inline('عضویت اجباری',data='toggle_join_channel_verification_stage_1'),
         Button.inline('تغییر کانال های عضویت اجباری',data='change_join_channel_list')],
        [Button.inline('آمار ربات',data='bot_stats'),
         Button.inline('پیام همگانی',data='send_msg_to_all')],
        [Button.inline('راه اندازی مجدد',data='reset_data')]
        ]
@client.on(events.NewMessage(pattern="^/admin$", incoming=True))
async def admin(event:events.NewMessage.Event):
    if event.chat_id != ADMIN_ID:
        return
    await client.conversation(event.chat_id).cancel_all()
    
    await event.message.reply("مدریت ربات", buttons=admin_buttons)
    
    
@client.on(events.CallbackQuery(data='admin_cancel'))
async def admin_cancel(event:events.CallbackQuery.Event):
    await client.conversation(event.chat_id).cancel_all()
    await event.delete()
    await event.reply("مدریت ربات", buttons=admin_buttons)


# ##### Increase Transfer Remainnig #####
@client.on(events.CallbackQuery(data='change_user_traffic'))
async def change_user_traffic(event:events.CallbackQuery.Event):
    await event.delete()
    async with client.conversation(event.chat_id) as conv:
        buttons = [[Button.inline('لغو',data='admin_cancel')]]
        msg = await conv.send_message("آیدی عددی یا یوزرنیم کابر ارسال کنید.",
                                        buttons=buttons)
        
        while True:
            admin_msg:Message = await conv.get_response()
            
            try:
                user_id = int(admin_msg.text)
            except ValueError:
                user_id = admin_msg.text.replace("@","")

            user_db = await users_status.find_one({"$or":[{"id":user_id},
                                                {"username":user_id}]})
            if not user_db or user_db["status"] == False:
                buttons = [[Button.inline('لغو', data='admin_cancel')]]
                await msg.delete()
                msg = await conv.send_message("کاربری با این مشخصات وجود ندارد",
                                                        buttons=buttons)
            else:
                break
        
        buttons = [[Button.inline('لغو', data='admin_cancel')]]
        
        await msg.delete()
        msg = await conv.send_message("مقدار حجم درخواستی بر مبنا مگابایت ارسال کنید\nاعداد منفی : کاهش حجم\nاعداد مثبت افزایش حجم",
                                        buttons=buttons)
        while True:
            admin_msg = await conv.get_response()
        
            try :
                value = int(admin_msg.text)
                break
            except ValueError:
                buttons = [[Button.inline('لغو', data='admin_cancel')]]
                await msg.delete()
                msg = await conv.send_message('لطفا عدد ارسال کنید',
                                                buttons=buttons)
            

        value = 1024**2 *value
        await msg.delete()
        await asyncio.gather(
            users_status.update_one({"id":user_db['id']}, {"$inc":{"transfer_remaining":value}}),
            client.send_message(user_db['id'], f'مقدار {size_convertor(value)} افزوده شد'),
            conv.send_message(f'مقدار {size_convertor(value)} افزوده شد')
        )
        await conv.cancel_all()




# ######### Send Message To All ##########

@client.on(events.CallbackQuery(data='send_msg_to_all'))
async def send_msg_to_all(event:events.CallbackQuery.Event):
    buttons = [[Button.inline('لغو', data='admin_cancel')]]
    await event.delete()
    async with client.conversation(event.chat_id) as conv:
        msg = await conv.send_message("پیام خود را ارسال کنید",
                                    buttons=buttons)
        
        admin_msg = await conv.get_response()

        users = users_status.find()
        async for user in users:
            await client.send_message(user["id"], admin_msg)
        
        
        await msg.edit("پیام ارسال شد", buttons=None)
        


# ######### Change Referral bonus ##########

@client.on(events.CallbackQuery(data='change_referral_bonus'))
async def change_referral_bonus(event:events.CallbackQuery.Event):
    buttons = [[Button.inline('لغو', data='admin_cancel')]]
    await event.delete()
    async with client.conversation(event.chat_id) as conv:
        msg = await conv.send_message("مقدار حجم مورد نظر در مبنا مگابایت ارسال کنید",
                                        buttons=buttons)
        
        
        while True:
            admin_msg = await conv.get_response()
            try :
                value = int(admin_msg.text)
                break
            except ValueError:
                buttons = [[Button.inline('لغو', data='admin_cancel')]]
                await msg.delete()
                msg = await conv.send_message('لطفا عدد ارسال کنید',
                                                buttons=buttons)
                
            
        value = 1048576*value+(value*25165.824)
        await msg.delete()
        await asyncio.gather(
            bot_status.update_one({"id":"bot"},{"$set":{"referral_bonus":value}}),
            conv.send_message(f'تغییر اعمال شد')
        )
        


# ######### Change Join bonus ##########
@client.on(events.CallbackQuery(data='change_join_bonus'))
async def change_join_bonus(event:events.CallbackQuery.Event):
    
    buttons = [[Button.inline('لغو',data='admin_cancel')]]
    await event.delete()
    async with client.conversation(event.chat_id) as conv:
        
        msg = await conv.send_message("مقدار حجم مورد نظر در مبنا مگابایت ارسال کنید",
                                    buttons=buttons)
    
        while True:
            admin_msg = await conv.get_response()
            try :
                value = int(admin_msg.text)
                break
            except ValueError:
                buttons = [[Button.inline('لغو',data='admin_cancel')]]
                await msg.delete()
                msg = await conv.send_message('لطفا عدد ارسال کنید',
                                                buttons=buttons)

        value = 1048576*value+(value*25165.824)
        await msg.delete()
        await asyncio.gather(
            bot_status.update_one({"id":"bot"},{"$set":{"change_join_bonus":value}}),
            conv.send_message(f'تغییر اعمال شد')
        )
        




# ######### Bot Status ##########
@client.on(events.CallbackQuery(data='bot_stats'))
async def bot_stats(event:events.CallbackQuery.Event):
    bot = await bot_status.find_one()
    text = f"""تعداد کل کاربران : {bot["users_count"]}
تعداد کاربران جدید : {bot["new_users"]}
تعداد کل دانلودها : {bot["download_count"]}
تعداد دانلودهای امروز : {bot["today_download_count"]}
حجم کل مصرف شده: {size_convertor(bot["total_transfered"])}
حجم مصرف شده امروز : {size_convertor(bot["today_transfered"])}
"""
    
    await event.edit(text)

# ########### on/off Phone Verification ##############

@client.on(events.CallbackQuery(data='toggle_phone_verification_stage_1'))
async def toggle_phone_verification_stage_1(event:events.CallbackQuery.Event):
    bot_db = await bot_status.find_one()
    txt = "فعال سازی" if not bot_db["verify_phone"] else "غیرفعال سازی"
    buttons = [[Button.inline(txt,
                                      data="toggle_phone_verification_stage_2")]]
    txt = "وضعیت: فعال" if bot_db["verify_phone"] else "وضعیت: غیرفعال"
    await event.edit(txt,buttons=buttons)

@client.on(events.CallbackQuery(data='toggle_phone_verification_stage_2'))
async def active_inactive_verify_phone(event:events.CallbackQuery.Event):
    bot_db = await bot_status.find_one()
    
    txt = "فعال شد"
    verify_phone = True

    if bot_db["verify_phone"]:
        txt = "غیرفعال شد"
        verify_phone = False
    
    await bot_status.update_one({"id":"bot"},
                                            {"$set":{"verify_phone":verify_phone}})

    await event.edit(txt)

# ############ on/off Join Channel Verification ############

@client.on(events.CallbackQuery(data='toggle_join_channel_verification_stage_1'))
async def toggle_join_channel_verification_stage_1(event:events.CallbackQuery.Event):
    bot_db = await bot_status.find_one()
    txt = "فعال سازی" if not bot_db["join_channel"] else "غیرفعال سازی"
    buttons = [[Button.inline(txt,
                                      data="toggle_join_channel_verification_stage_2")]]
    txt = "وضعیت: فعال" if bot_db["join_channel"] else "وضعیت: غیرفعال"
    await event.edit(txt,buttons=buttons)

@client.on(events.CallbackQuery(data='toggle_join_channel_verification_stage_2'))
async def toggle_join_channel_verification_stage_2(event:events.CallbackQuery.Event):
    bot_db = await bot_status.find_one()
    
    txt = "فعال شد"
    join_channel = True
    
    if bot_db["join_channel"]:
        txt = "غیرفعال شد"
        join_channel = False
    
    await bot_status.update_one({"id":"bot"},{"$set":{"join_channel":join_channel}})
    

    await event.edit(txt)


# ############ add/romeve Join Channel Verification  ############
async def get_channels_list(event):
    bot_db = await bot_status.find_one()
    buttons = [
        [Button.inline('افزودن کانال', data='register_channel')],
        [Button.inline('افزودن ربات به کانال یا گروه', )]]
    if bot_db["channels"]:
        for ch in bot_db["channels"]:
            buttons.append([Button.url(ch, url='https://t.me/'+ch),
                             Button.inline('حذف', data="unregister_"+ch)])

    await event.edit('لیست کانال های عضویت اجباری', buttons=buttons)


@client.on(events.CallbackQuery(data='change_join_channel_list'))
async def change_join_channel_list(event:events.CallbackQuery.Event):
    await get_channels_list(event)

@client.on(events.CallbackQuery(pattern='^unregister_'))
async def unregister_channel(event:events.CallbackQuery.Event):
    
    id = event.data.decode().split('_')[1]
    await bot_status.update_one({"id":"bot"},
                                   {"$pull":{"channels":id}})

    await get_channels_list(event)


@client.on(events.CallbackQuery(data='register_channel'))
async def register_channel(event:events.CallbackQuery.Event):
    buttons = [[Button.inline('لغو',data='admin_cancel')]]
    await event.delete()

    async with client.conversation(event.chat_id) as conv:
        
        msg = await conv.send_message("آیدی گروه یا کانال ارسال کنید\nابتدا ربات را حتما عضو و ادمین کنید.",
                                        buttons=buttons)
        admin_msg = await conv.get_response()
        its_id = admin_msg.text.replace("https://t.me/","")
        await msg.delete()
        try:
            channel = await client.get_entity(its_id)
            client_user = await client.get_me()
            await client(GetParticipantRequest(channel, client_user.id))
                            
            bot_status.update_one({"id":"bot"},
                                        {"$push":{"channels":its_id}})
            await conv.send_message("کانال با موفقیت در ربات قفل شد",)
            
        except UserNotParticipantError:
            await conv.send_message("ربات را ابتدا در کانال عضو و ادمین کنید",)
        except Exception:
            await conv.send_message("چنین آیدی وجود ندارد")


# ############# Reset data ###############
@client.on(events.CallbackQuery(data='reset_data'))
async def reset_data(event:events.CallbackQuery.Event):
    await reset_user_data()
    await event.edit("ربات با موفقیت راه اندازی مجدد شد")


# ########### Autmate ###########

scheduler = AsyncIOScheduler(timezone=zoneinfo.ZoneInfo("Asia/Tehran"))
scheduler._eventloop = client.loop


async def autmate():
    await reset_data()
    bot_db = await bot_status.find_one()
    await asyncio.gather(
        bot_status.update_many({},{"$set":{"new_users":0,"today_transfered":0, "today_download_count":0}}),
        users_status.update_many({},{"$set":{"today_transfered":0,"in_queue":0}}),
        users_status.update_many({"transfer_remaining":{"$lt":bot_db["change_join_bonus"]}},{"$set":{"transfer_remaining":bot_db["change_join_bonus"]}})
        )

async def backup_db():
    await asyncio.to_thread(shutil.make_archive, CONFIG.joinpath('./db'), 'zip', CONFIG.joinpath('./db'))
    await client.send_file(ADMIN_ID, file=CONFIG.joinpath('./db.zip'))


scheduler.add_job(autmate, CronTrigger(hour=2))
scheduler.add_job(backup_db, IntervalTrigger(minutes=30))


scheduler.start()
client.run_until_disconnected()
