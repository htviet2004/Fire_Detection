"""Rate limiting middleware for API endpoints."""

import time
from collections import defaultdict
from threading import Lock

from django.conf import settings
from django.http import JsonResponse


class RateLimitMiddleware:
    """Simple in-memory rate limiter."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.requests = defaultdict(list)
        self.lock = Lock()

    def __call__(self, request):
        # Only rate limit API endpoints
        if not request.path.startswith('/api/'):
            return self.get_response(request)

        # Get client IP
        client_ip = self._get_client_ip(request)
        current_time = time.time()

        # Get rate limit settings
        max_requests = getattr(settings, 'RATE_LIMIT_REQUESTS', 100)
        window_seconds = getattr(settings, 'RATE_LIMIT_WINDOW_SECONDS', 60)

        with self.lock:
            # Clean old requests
            self.requests[client_ip] = [
                req_time for req_time in self.requests[client_ip]
                if current_time - req_time < window_seconds
            ]

            # Check rate limit
            if len(self.requests[client_ip]) >= max_requests:
                return JsonResponse(
                    {
                        'error': 'Rate limit exceeded',
                        'retry_after': int(window_seconds - (current_time - self.requests[client_ip][0])) + 1,
                    },
                    status=429,
                )

            # Add current request
            self.requests[client_ip].append(current_time)

        return self.get_response(request)

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')
