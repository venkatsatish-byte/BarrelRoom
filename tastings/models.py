import secrets

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


def unique_slug(instance, value, queryset):
    """Slugify ``value``, adding -2, -3, ... until it is unique in ``queryset``."""
    base = slugify(value)[:60] or "item"
    slug, n = base, 2
    while queryset.exclude(pk=instance.pk).filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class Winery(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wineries"
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=70, unique=True, blank=True)
    region = models.CharField(max_length=80, help_text="e.g. Napa Valley, Willamette Valley")
    description = models.TextField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    email = models.EmailField(help_text="Booking notifications are sent here.")
    phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)
    is_published = models.BooleanField(
        default=True, help_text="Unpublished wineries are hidden from guests."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "wineries"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name, Winery.objects)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("winery_detail", args=[self.slug])


class Experience(models.Model):
    """A bookable tasting or tour, e.g. "Reserve flight" or "Cave tour"."""

    winery = models.ForeignKey(Winery, on_delete=models.CASCADE, related_name="experiences")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=70, blank=True)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=60, validators=[MinValueValidator(15)])
    price_per_guest = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(0)]
    )
    capacity = models.PositiveIntegerField(
        default=8,
        validators=[MinValueValidator(1)],
        help_text="Maximum guests per time slot.",
    )
    max_party_size = models.PositiveIntegerField(
        default=6,
        validators=[MinValueValidator(1)],
        help_text="Largest group one booking can hold.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["winery", "name"]
        constraints = [
            models.UniqueConstraint(fields=["winery", "slug"], name="unique_experience_slug"),
        ]

    def __str__(self):
        return f"{self.name} at {self.winery}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name, Experience.objects.filter(winery=self.winery))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("experience_detail", args=[self.winery.slug, self.slug])

    def upcoming_slots(self):
        return self.slots.filter(start__gt=timezone.now(), is_closed=False).order_by("start")


class TimeSlot(models.Model):
    experience = models.ForeignKey(Experience, on_delete=models.CASCADE, related_name="slots")
    start = models.DateTimeField()
    capacity = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Defaults to the experience capacity.",
    )
    is_closed = models.BooleanField(default=False, help_text="Closed slots take no new bookings.")

    class Meta:
        ordering = ["start"]
        constraints = [
            models.UniqueConstraint(fields=["experience", "start"], name="unique_slot_start"),
        ]

    def __str__(self):
        local = timezone.localtime(self.start)
        return f"{self.experience.name} — {local:%a %b %-d, %-I:%M %p}"

    def save(self, *args, **kwargs):
        if self.capacity is None:
            self.capacity = self.experience.capacity
        super().save(*args, **kwargs)

    @property
    def seats_booked(self):
        total = self.bookings.filter(status=Booking.Status.CONFIRMED).aggregate(
            total=Sum("party_size")
        )["total"]
        return total or 0

    @property
    def seats_left(self):
        return max(self.capacity - self.seats_booked, 0)

    @property
    def is_bookable(self):
        return not self.is_closed and self.start > timezone.now() and self.seats_left > 0


def new_reference():
    # Short, unambiguous code guests can read over the phone.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    slot = models.ForeignKey(TimeSlot, on_delete=models.PROTECT, related_name="bookings")
    reference = models.CharField(max_length=12, unique=True, default=new_reference, editable=False)
    guest_name = models.CharField(max_length=120)
    guest_email = models.EmailField()
    guest_phone = models.CharField(max_length=30, blank=True)
    party_size = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    notes = models.TextField(blank=True, help_text="Allergies, celebrations, accessibility needs.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["slot__start", "created_at"]

    def __str__(self):
        return f"{self.reference} — {self.guest_name} ({self.party_size})"

    def get_absolute_url(self):
        return reverse("booking_detail", args=[self.reference])

    @property
    def total_price(self):
        return self.slot.experience.price_per_guest * self.party_size

    @property
    def winery(self):
        return self.slot.experience.winery

    @property
    def can_cancel(self):
        return self.status == self.Status.CONFIRMED and self.slot.start > timezone.now()
