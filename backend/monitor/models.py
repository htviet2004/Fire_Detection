from django.db import models


class FireEvent(models.Model):
	SAFE = 'SAFE'
	SMOKE_DETECTED = 'SMOKE DETECTED'
	FIRE_ALERT = 'FIRE ALERT'

	STATUS_CHOICES = (
		(SAFE, SAFE),
		(SMOKE_DETECTED, SMOKE_DETECTED),
		(FIRE_ALERT, FIRE_ALERT),
	)

	source = models.CharField(max_length=255, default='0')
	status = models.CharField(max_length=32, choices=STATUS_CHOICES)
	label = models.CharField(max_length=64, blank=True)
	confidence = models.FloatField(default=0.0)
	created_at = models.DateTimeField(auto_now_add=True)
	details = models.JSONField(default=dict, blank=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self) -> str:
		return f'{self.status} ({self.confidence:.2f})'

	def to_payload(self) -> dict:
		return {
			'id': self.id,
			'source': self.source,
			'status': self.status,
			'label': self.label,
			'confidence': round(float(self.confidence), 4),
			'created_at': self.created_at.isoformat(),
			'details': self.details,
		}
