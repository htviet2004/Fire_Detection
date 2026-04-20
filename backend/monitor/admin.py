from django.contrib import admin

from .models import FireEvent


@admin.register(FireEvent)
class FireEventAdmin(admin.ModelAdmin):
	list_display = ('id', 'status', 'label', 'confidence', 'source', 'created_at')
	list_filter = ('status', 'created_at')
	search_fields = ('label', 'source')
	ordering = ('-created_at',)

# Register your models here.
