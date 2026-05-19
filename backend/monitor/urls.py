from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.health, name='health'),
    path('health/detailed/', views.health, name='health_detailed'),
    path('metrics/', views.metrics, name='metrics'),
    path('stream/', views.stream_video, name='stream_video'),
    path('status/', views.status_snapshot, name='status_snapshot'),
    path('events/', views.event_logs, name='event_logs'),
    path('source/', views.set_camera_source, name='set_camera_source'),
    path('upload-video/', views.upload_video, name='upload_video'),
]
