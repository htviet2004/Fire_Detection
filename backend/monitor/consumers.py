import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .services import detection_manager


class AlertConsumer(AsyncWebsocketConsumer):
    group_name = 'alerts'

    async def connect(self):
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await sync_to_async(detection_manager.start)()
        status = await sync_to_async(detection_manager.get_status)()
        events = await sync_to_async(detection_manager.get_events)(20)
        await self.send(
            text_data=json.dumps(
                {
                    'type': 'snapshot',
                    'status': status,
                    'events': events,
                }
            )
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            return

        if payload.get('type') == 'set_source':
            source = str(payload.get('source', '')).strip()
            if not source:
                return

            try:
                await sync_to_async(detection_manager.set_source)(source)
            except ValueError as error:
                await self.send(text_data=json.dumps({'type': 'source_error', 'error': str(error)}))
                return

            status = await sync_to_async(detection_manager.get_status)()
            await self.send(text_data=json.dumps({'type': 'source_ack', 'status': status}))

    async def alert_message(self, event):
        await self.send(text_data=json.dumps(event['payload']))