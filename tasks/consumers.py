import json
import asyncio
from datetime import datetime
from django.utils.dateparse import parse_datetime
from channels.generic.websocket import AsyncWebsocketConsumer

from channels.db import database_sync_to_async
from tasks.models import Task, Comment

class CommentConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sockConnected = True
        self.y=0
        self.latest_timestamps = {}
   
    async def check_DB(self):
        while self.sockConnected:
            comments = await self.get_comments()
        
            for comment in comments:
                updated_timestamp = comment['updated_at']
                if comment['id'] not in self.latest_timestamps or updated_timestamp > self.latest_timestamps[comment['id']]:
                    self.latest_timestamps[comment['id']] = updated_timestamp
                    username = comment['author']
                    task_author_username = comment['task']
                   

                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'edit_message',
                            'message': comment['body'],
                            'commentId': comment['id'],
                            'username': username,
                            'taskAuthor': task_author_username,
                            'operation': 'edit'
                        }
                    )
            await asyncio.sleep(1)
    
    @database_sync_to_async
    def get_comments(self):
        comments = Comment.objects.filter(task_id=self.room_name)
        
        comments_list = []
        
        for comment in comments:
            comments_list.append({
                'id': comment.id,
                'author': comment.author.username,  # or comment.author.username, depending on what you need
                'task': comment.task.title,  # or comment.task.title
                'body': comment.body,
                'date_added': comment.date_added.isoformat(),
                'updated_at': comment.updated_at.isoformat()
            })
        
        return comments_list
    
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['pk']
        # if incoming url is ws://127.0.0.1:8000/ws/comment/1/
        # then self.room_name = 1//it is just the id of the comment automatically assigned by the DB
        self.room_group_name = 'task_%s' % self.room_name
        #then self.room_group_name = task_1, it is just "task_+self.room_name" 
        self.user = self.scope['user']
        # self.user is the current user connected to the websocket
        # currently we connected through the admin account
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        
        await self.accept()
        self.background_task = asyncio.create_task(self.check_DB())



    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        self.sockConnected=False
        



    async def receive(self, text_data):
        # self.x = False
        #when a message is received from a websocket
        text_data_json = json.loads(text_data)
        #if requested operation is "create"
        if text_data_json['operation'] == 'create': 
            message = text_data_json['message']
            task_id = text_data_json['taskId']      
            created_comment = await self.create_comment(task_id, message)
            username = await self.get_user(created_comment)
            task_author_username = await self.get_task_author_username(task_id)

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'comment',
                    'message': created_comment.body,
                    'commentId': created_comment.id,
                    'username': username,
                    'taskAuthor': task_author_username,
                    'operation': 'create'
                }
            )


        if text_data_json['operation'] == 'delete':
            comment_id = text_data_json['commentId']
            task_id = text_data_json['taskId'] 
            await self.delete_comment(task_id, comment_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'delete',
                    'commentId': comment_id,
                    'operation': 'delete'
                }
            )

        if text_data_json['operation'] == 'edit':
            
            comment_id = text_data_json['commentId']            
            task_id = text_data_json['taskId'] 
            message = text_data_json['message']
            
            
            edited_comment = await self.edit_comment(task_id, comment_id, message)
            username = await self.get_user(edited_comment)
            task_author_username = await self.get_task_author_username(task_id)


            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'edit_message',
                    'commentId': edited_comment.id,
                    'message': edited_comment.body,
                    'username': username,
                    'taskAuthor': task_author_username,
                    'operation': 'edit'
                }
            )
        

    async def comment(self, event):
        created_comment_message = event['message']
        created_comment_id = event['commentId']
        created_comment_username = event['username']
        created_comment_task_author = event['taskAuthor']
        operation = event['operation']
        # Send message to WebSocket
        await self.send(text_data=json.dumps({ #encodage json
            'message': created_comment_message,
            'commentId': created_comment_id,
            'username': created_comment_username,
            'taskAuthor': created_comment_task_author,
            'operation': operation
        }))

    @database_sync_to_async
    def create_comment(self, task_id, message):
        task = Task.objects.get(pk=task_id)

        comment = task.comments.create(
            author = self.user,
            body = message
        )
        return comment



    async def delete(self, event):
        comment_id = event['commentId']
        operation = event['operation']
        print(comment_id, operation)
        # Send message to WebSocket
        await self.send(text_data=json.dumps({ #encodage json
            'commentId': comment_id,
            'operation': operation
        }))



    @database_sync_to_async
    def delete_comment(self, task_id, comment_id):
        print(task_id, comment_id)
        task = Task.objects.get(pk=task_id)
        comment = Comment.objects.get(pk=comment_id, task=task)
        comment.delete()


    async def edit_message(self, event):
        edited_comment_message = event['message']
        edited_comment_id = event['commentId']
        edited_comment_username = event['username']
        edited_comment_task_author = event['taskAuthor']        
        operation = event['operation']
        
        # Send message to WebSocket
        await self.send(text_data=json.dumps({ #encodage json
            'commentId': edited_comment_id,
            'message': edited_comment_message,
            'username': edited_comment_username,
            'taskAuthor': edited_comment_task_author,
            'operation': operation
        }))
    
    @database_sync_to_async
    def edit_comment(self, task_id, comment_id, message):
        task = Task.objects.get(pk=task_id)

        comment = Comment.objects.get(pk=comment_id, task=task)
        comment.body = message
        comment.save()

        return comment



    @database_sync_to_async
    def get_user(self, comment):
        return comment.author.username

    @database_sync_to_async
    def get_task_author_username(self, task_id):
        task = Task.objects.get(pk=task_id)
        return task.author.username