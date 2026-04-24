# https://www.googleapis.com/drive/v3/files/18IDGYvKJgkbVL7w4I6MTRjIHAu608JYX/?alt=media&key=AIzaSyA0OAVsOLYcn5u_2vWUCNQI_Z3gWNoicnQ

from aiogoogle import Aiogoogle, auth, resource

from mimetypes import guess_type

import json



class RefreshTokenExpires(Exception):
    def __init__(self, message="Refresh token has expired or is invalid"):
        super().__init__(message)
    

class GoogleDrive:
    FIELDS = "nextPageToken, files(kind,fileExtension,mimeType,webContentLink,webViewLink,size,name,id,parents)"

    def __init__(self, client_creds, google_drive_api_key=None):
        with open(client_creds, 'r') as f:
            self.__client_creds = json.loads(f.read())['web']
        self.__api_key = google_drive_api_key

    async def login(self, user_creds):
        with open(user_creds, 'r') as f:
            self.__user_creds = json.load(f)

        refreshed_user_creds = auth.Oauth2Manager()
        try:
            refreshed_user_creds = await refreshed_user_creds.refresh(client_creds=self.__client_creds,
                                                                  user_creds=self.__user_creds)
        except:
            raise RefreshTokenExpires

        self.__user_creds = refreshed_user_creds[1]

        with open(user_creds, 'w') as f:
            json.dump(refreshed_user_creds[1], f)

        async with Aiogoogle(user_creds=self.__user_creds, client_creds=self.__client_creds) as self.__aiogoogle:
            self.__service = await self.__aiogoogle.discover('drive', 'v3')

        return self

    async def get_all_list(self, next_page_token=None, page_size=1000):
        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.files.list(
                    fields=self.FIELDS,
                    pageSize=page_size,
                    pageToken=next_page_token
                )
            )
        return json_res

    async def get_folders_list(self, next_page_token=None, page_size=1000):
        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.files.list(
                    q="mimeType='application/vnd.google-apps.folder'",
                    fields=self.FIELDS,
                    pageSize=page_size,
                    pageToken=next_page_token
                )
            )
        return json_res

    async def get_files_list(self, next_page_token=None, page_size=1000):
        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.files.list(
                    q="mimeType!='application/vnd.google-apps.folder'",
                    fields=self.FIELDS,
                    pageSize=page_size,
                    pageToken=next_page_token)
            )

        return json_res

    async def get_files_list_in_folder(self, folder_id, next_page_token=None, page_size=1000):
        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.files.list(
                    q=f"'{folder_id}' in parents",
                    fields=self.FIELDS,
                    pageSize=page_size,
                    pageToken=next_page_token
                )
            )

        return json_res

    async def get_folder_by_name(self, folder_name, parent_folder_id=None):
        async with self.__aiogoogle:
            q = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}'"
            if parent_folder_id:
                q += f" and '{parent_folder_id}' in parents"
            json_res = await self.__aiogoogle.as_user(
                self.__service.files.list(q=q, fields=self.FIELDS),
            )
        return json_res.get('files', [])

    async def get_folder_by_id(self, folder_id):
        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.files.get(fileId=folder_id,
                                         fields="kind,fileExtension,mimeType,webContentLink,webViewLink,size,name,id,parents"),
            )
        return json_res

    async def get_file_by_name(self, file_name, parent_folder_id=None):
        async with self.__aiogoogle:
            q = f"name='{file_name}'"
            if parent_folder_id:
                q += f" and '{parent_folder_id}' in parents"
            json_res = await self.__aiogoogle.as_user(
                self.__service.files.list(q=q, fields=self.FIELDS),
            )
        return json_res.get('files', [])

    async def get_file_by_id(self, file_id):
        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.files.get(fileId=file_id,
                                         fields="kind,fileExtension,mimeType,webContentLink,webViewLink,size,name,id,parents"),
            )
        return json_res

    async def create_permission(self, item_id, role='reader', type='anyone', email_address=None, domain=None):
        """role: The role assigned to the user or group ('owner', 'writer', 'commenter', 'reader'). You can modify this to change the level of access.
        type: The type of the permission ('user', 'group', 'domain', 'anyone'). You can change this to modify the type of entity that the permission applies to."""

        permission_metadata = {
            'role': role,
            'type': type,
        }
        if email_address:
            permission_metadata['emailAddress'] = email_address
        elif domain:
            permission_metadata['domain'] = domain

        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.permissions.create(fileId=item_id, json=permission_metadata)
            )
        return json_res

    async def delete_permission(self, item_id, permissionId):
        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.permissions.delete(fileId=item_id, permissionId=permissionId),
            )
        return json_res

    async def permission_list(self, item_id):
        async with self.__aiogoogle:
            json_res = await self.__aiogoogle.as_user(
                self.__service.permissions.list(fileId=item_id),
            )
        return json_res

    async def download_file(self, file_id, output_path='./'):
        async with self.__aiogoogle:
            file_name = await self.__aiogoogle.as_user(
                self.__service.files.get(fileId=file_id),
            )
            file_name = file_name['name']
            file = await self.__aiogoogle.as_user(
                self.__service.files.get(fileId=file_id, download_file=output_path + fr'\{file_name}', alt='media',
                                         fields='name'),
            )
        return file

    async def upload_file(self, name_on_googledrive, file_path, folder_id=None):
        file_metadata = {
            'name': f'{name_on_googledrive}',
            # Specify the desired name for the file on Google Drive
        }
        if folder_id:
            file_metadata['parents'] = [folder_id]

        async with self.__aiogoogle:
            file = await self.__aiogoogle.as_user(
                self.__service.files.create(upload_file=file_path,
                                            fields='kind,fileExtension,mimeType,webContentLink,webViewLink,size,name,id,parents',
                                            json=file_metadata),
            )
        return file

    async def upload_by_chunk(self, process, name_on_googledrive, folder_id=None):
        """async def process():
            async with aiofile.async_open(file_path, 'rb') as f:
                async for chunk in f.iter_chunked(10):
                    print('uploaded 10 chunk')
                    yield chunk"""

        file_metadata = {
            'name': f'{name_on_googledrive}',
            # Specify the desired name for the file on Google Drive
        }
        if folder_id:
            file_metadata['parents'] = [folder_id]

        async with self.__aiogoogle:
            file = await self.__aiogoogle.as_user(
                self.__service.files.create(pipe_from=process,
                                            fields='kind,fileExtension,mimeType,webContentLink,webViewLink,size,name,id,parents',
                                            json=file_metadata)
            )
        return file

    async def upload_image_as_doc(self, name_on_googledrive, file_path, folder_id=None):
        if guess_type(file_path)[0] not in ['image/png', 'image/jpeg']:
            return 'send jpg or png file'

        file_metadata = {
            'name': name_on_googledrive,  # Specify the desired name for the file on Google Drive
            "mimeType": "application/vnd.google-apps.document",
        }

        if folder_id:
            file_metadata["parents"] = [folder_id]

        async with self.__aiogoogle:
            file = await self.__aiogoogle.as_user(
                self.__service.files.create(upload_file=file_path,
                                            fields="kind,fileExtension,mimeType,webContentLink,webViewLink,size,name,id,parents",
                                            json=file_metadata),
            )
        return file

    async def extract_text_from_img(self, file_id, output_path):
        async with self.__aiogoogle:
            await self.__aiogoogle.as_user(
                self.__service.files.export(
                    fileId=file_id, mimeType="text/plain", download_file=output_path
                ))

        return True

    async def get_direct_link_by_api(self, file_id):
        return f'https://www.googleapis.com/drive/v3/files/{file_id}/?alt=media&key={self.__api_key}'

    async def create_folder(self, folder_name, parent_folder_id=None):
        folder_metadata = {
            'name': folder_name,  # Specify the desired name for the folder
            'mimeType': 'application/vnd.google-apps.folder'
        }

        if parent_folder_id:
            folder_metadata['parents'] = [parent_folder_id]
        async with self.__aiogoogle:
            folder = await self.__aiogoogle.as_user(
                self.__service.files.create(json=folder_metadata,
                                            fields="kind,fileExtension,mimeType,webContentLink,webViewLink,size,name,id,parents"),
            )
        return folder

    async def get_drive_info(self):
        async with self.__aiogoogle:
            drive_info = await self.__aiogoogle.as_user(
                self.__service.about.get(fields='storageQuota, user'),
            )
        return drive_info

    async def delete_item(self, item_id):
        async with self.__aiogoogle:
            await self.__aiogoogle.as_user(
                self.__service.files.delete(fileId=item_id),
            )

        return True

    async def delete_all(self):
        async with self.__aiogoogle:
            results = await self.__aiogoogle.as_user(
                self.__service.files.list(fields='files(id)')
            )
            r = [self.__service.files.delete(fileId=id['id']) for id in results.get('files', [])]
            await self.__aiogoogle.as_user(*r)
        return True
    
    
if __name__ == "__main__":
    from asgiref.sync import async_to_sync
    
    g = GoogleDrive(r'./config/client_secrets2.json')
    d = async_to_sync(g.login)(r'./web.json')    
    
    # print(async_to_sync(d.upload_by_chunk)())
