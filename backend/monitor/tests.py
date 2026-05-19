"""Unit tests for the monitor app."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import FireEvent
from .services import DetectionManager, normalize_camera_source


class FireEventModelTest(TestCase):
    """Tests for FireEvent model."""

    def test_create_fire_event(self):
        """Test creating a fire event."""
        event = FireEvent.objects.create(
            source='0',
            status=FireEvent.FIRE_ALERT,
            label='fire',
            confidence=0.95,
        )
        self.assertEqual(event.status, FireEvent.FIRE_ALERT)
        self.assertEqual(event.label, 'fire')
        self.assertEqual(event.confidence, 0.95)
        self.assertIsNotNone(event.created_at)

    def test_create_smoke_event(self):
        """Test creating a smoke event."""
        event = FireEvent.objects.create(
            source='0',
            status=FireEvent.SMOKE_DETECTED,
            label='smoke',
            confidence=0.85,
        )
        self.assertEqual(event.status, FireEvent.SMOKE_DETECTED)

    def test_to_payload(self):
        """Test event payload conversion."""
        event = FireEvent.objects.create(
            source='test_source',
            status=FireEvent.FIRE_ALERT,
            label='fire',
            confidence=0.92,
            details={'test': 'data'},
        )
        payload = event.to_payload()

        self.assertIn('id', payload)
        self.assertEqual(payload['source'], 'test_source')
        self.assertEqual(payload['status'], FireEvent.FIRE_ALERT)
        self.assertEqual(payload['label'], 'fire')
        self.assertAlmostEqual(payload['confidence'], 0.92, places=4)
        self.assertEqual(payload['details'], {'test': 'data'})
        self.assertIn('created_at', payload)

    def test_ordering(self):
        """Test events are ordered by created_at descending."""
        event1 = FireEvent.objects.create(
            source='0',
            status=FireEvent.SAFE,
            label='',
            confidence=0.0,
        )
        time.sleep(0.01)
        event2 = FireEvent.objects.create(
            source='0',
            status=FireEvent.FIRE_ALERT,
            label='fire',
            confidence=0.95,
        )

        events = list(FireEvent.objects.all())
        self.assertEqual(events[0], event2)  # Newer first
        self.assertEqual(events[1], event1)


class NormalizeCameraSourceTest(TestCase):
    """Tests for camera source normalization."""

    def test_webcam_index(self):
        """Test webcam index normalization."""
        self.assertEqual(normalize_camera_source('0'), 0)
        self.assertEqual(normalize_camera_source('1'), 1)
        self.assertEqual(normalize_camera_source('99'), 99)

    def test_rtsp_url(self):
        """Test RTSP URL passthrough."""
        rtsp_url = 'rtsp://192.168.1.100:554/stream'
        self.assertEqual(normalize_camera_source(rtsp_url), rtsp_url)

    def test_http_url(self):
        """Test HTTP URL passthrough."""
        http_url = 'http://example.com/stream'
        self.assertEqual(normalize_camera_source(http_url), http_url)

    def test_invalid_source(self):
        """Test invalid source raises ValueError."""
        with self.assertRaises(ValueError):
            normalize_camera_source('nonexistent_file.mp4')


class HealthEndpointTest(TestCase):
    """Tests for health endpoint."""

    def setUp(self):
        self.client = Client()

    def test_health_endpoint_returns_json(self):
        """Test health endpoint returns JSON."""
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_health_endpoint_structure(self):
        """Test health endpoint response structure."""
        response = self.client.get('/api/health/')
        data = json.loads(response.content)

        self.assertIn('ok', data)
        self.assertIn('status', data)
        self.assertIn('database', data)
        self.assertIn('timestamp', data)


class StatusEndpointTest(TestCase):
    """Tests for status endpoint."""

    def setUp(self):
        self.client = Client()

    def test_status_endpoint_returns_json(self):
        """Test status endpoint returns JSON."""
        response = self.client.get('/api/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_status_endpoint_structure(self):
        """Test status endpoint response structure."""
        response = self.client.get('/api/status/')
        data = json.loads(response.content)

        self.assertIn('state', data)
        self.assertIn('source', data)
        self.assertIn('label', data)
        self.assertIn('confidence', data)
        self.assertIn('message', data)


class EventsEndpointTest(TestCase):
    """Tests for events endpoint."""

    def setUp(self):
        self.client = Client()

    def test_events_endpoint_returns_json(self):
        """Test events endpoint returns JSON."""
        response = self.client.get('/api/events/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_events_endpoint_with_limit(self):
        """Test events endpoint respects limit parameter."""
        # Create some events
        for i in range(10):
            FireEvent.objects.create(
                source='0',
                status=FireEvent.FIRE_ALERT,
                label='fire',
                confidence=0.9,
            )

        response = self.client.get('/api/events/?limit=5')
        data = json.loads(response.content)

        self.assertIn('items', data)
        self.assertLessEqual(len(data['items']), 5)

    def test_events_endpoint_empty(self):
        """Test events endpoint with no events."""
        response = self.client.get('/api/events/')
        data = json.loads(response.content)

        self.assertIn('items', data)
        self.assertEqual(len(data['items']), 0)


class SourceEndpointTest(TestCase):
    """Tests for camera source endpoint."""

    def setUp(self):
        self.client = Client()

    def test_source_endpoint_requires_source(self):
        """Test source endpoint requires source parameter."""
        response = self.client.post(
            '/api/source/',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_source_endpoint_valid_source(self):
        """Test source endpoint with valid source."""
        response = self.client.post(
            '/api/source/',
            data=json.dumps({'source': '0'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data.get('ok'))

    def test_source_endpoint_invalid_source(self):
        """Test source endpoint with invalid source."""
        response = self.client.post(
            '/api/source/',
            data=json.dumps({'source': 'nonexistent_source'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)


class UploadVideoEndpointTest(TestCase):
    """Tests for video upload endpoint."""

    def setUp(self):
        self.client = Client()

    def test_upload_video_requires_file(self):
        """Test upload endpoint requires video file."""
        response = self.client.post('/api/upload-video/')
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)


class MetricsEndpointTest(TestCase):
    """Tests for metrics endpoint."""

    def setUp(self):
        self.client = Client()

    def test_metrics_endpoint_returns_text(self):
        """Test metrics endpoint returns Prometheus format."""
        response = self.client.get('/api/metrics/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')

    def test_metrics_endpoint_contains_metrics(self):
        """Test metrics endpoint contains expected metrics."""
        response = self.client.get('/api/metrics/')
        content = response.content.decode()

        self.assertIn('fire_monitor_up', content)
        self.assertIn('fire_monitor_frame_count', content)
        self.assertIn('fire_monitor_fps', content)


class DetectionManagerTest(TestCase):
    """Tests for DetectionManager service."""

    def setUp(self):
        self.manager = DetectionManager()

    def test_initial_state(self):
        """Test manager starts in SAFE state."""
        status = self.manager.get_status()
        self.assertEqual(status['state'], FireEvent.SAFE)
        self.assertEqual(status['confidence'], 0.0)

    def test_set_source_valid(self):
        """Test setting valid source."""
        status = self.manager.set_source('0')
        self.assertIsNotNone(status)
        self.assertEqual(status['source'], '0')

    def test_set_source_invalid(self):
        """Test setting invalid source raises error."""
        with self.assertRaises(ValueError):
            self.manager.set_source('nonexistent')

    def test_get_events(self):
        """Test getting events from manager."""
        # Create some events in DB
        FireEvent.objects.create(
            source='0',
            status=FireEvent.FIRE_ALERT,
            label='fire',
            confidence=0.9,
        )

        events = self.manager.get_events(limit=10)
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0)

    def test_get_events_limit(self):
        """Test events limit is respected."""
        # Create 10 events
        for i in range(10):
            FireEvent.objects.create(
                source='0',
                status=FireEvent.FIRE_ALERT,
                label='fire',
                confidence=0.9,
            )

        events = self.manager.get_events(limit=5)
        self.assertLessEqual(len(events), 5)

    def test_get_metrics(self):
        """Test getting metrics."""
        metrics = self.manager.get_metrics()

        self.assertIn('frame_count', metrics)
        self.assertIn('inference_count', metrics)
        self.assertIn('uptime_seconds', metrics)
        self.assertIn('fps', metrics)
        self.assertIn('model_loaded', metrics)
