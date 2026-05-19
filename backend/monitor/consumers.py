import asyncio
import json
import logging
import time

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .services import detection_manager

logger = logging.getLogger(__name__)


class AlertConsumer(AsyncWebsocketConsumer):
    group_name = 'alerts'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._heartbeat_task = None
        self._last_ping_at = 0.0
        self._connected_at = 0.0

    async def connect(self):
        self._connected_at = time.time()
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.info(f"WebSocket connected: {self.channel_name}")

        # Send connection info
        await self.send(
            text_data=json.dumps({
                'type': 'connection_info',
                'connected_at': self._connected_at,
                'server_time': time.time(),
            })
        )

        await sync_to_async(detection_manager.start)()
        status = await sync_to_async(detection_manager.get_status)()
        events = await sync_to_async(detection_manager.get_events)(20)
        await self.send(
            text_data=json.dumps({
                'type': 'snapshot',
                'status': status,
                'events': events,
            })
        )

    async def disconnect(self, close_code):
        logger.info(f"WebSocket disconnected: {self.channel_name}, code: {close_code}")
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = payload.get('type', '')

        # Handle heartbeat pong
        if msg_type == 'pong':
            self._last_ping_at = 0
            return

        # Handle ping request from client
        if msg_type == 'ping':
            await self.send(text_data=json.dumps({
                'type': 'pong',
                'timestamp': time.time()
            }))
            return

        # Handle get_metrics request
        if msg_type == 'get_metrics':
            metrics = await sync_to_async(detection_manager.get_metrics)()
            await self.send(text_data=json.dumps({
                'type': 'metrics',
                'metrics': metrics,
            }))
            return

        # Handle get_status request
        if msg_type == 'get_status':
            status = await sync_to_async(detection_manager.get_status)()
            await self.send(text_data=json.dumps({
                'type': 'status_response',
                'status': status,
            }))
            return

        if msg_type == 'set_source':
            source = str(payload.get('source', '')).strip()
            if not source:
                return

            try:
                await sync_to_async(detection_manager.set_source)(source)
            except ValueError as error:
                await self.send(text_data=json.dumps({
                    'type': 'source_error',
                    'error': str(error)
                }))
                return

            status = await sync_to_async(detection_manager.get_status)()
            await self.send(text_data=json.dumps({
                'type': 'source_ack',
                'status': status
            }))

    async def alert_message(self, event):
        await self.send(text_data=json.dumps(event['payload']))
