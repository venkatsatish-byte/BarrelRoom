"""Booking rules shared by the guest pages, the dashboard and the admin."""

from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Booking, TimeSlot


class BookingError(Exception):
    """A booking could not be made; the message is safe to show the guest."""


def create_booking(slot_id, *, guest_name, guest_email, party_size, guest_phone="", notes=""):
    """Book ``party_size`` seats on a slot, refusing if it would overfill it.

    The slot row is locked for the duration of the transaction so two guests
    grabbing the last seats at the same moment can't both succeed (Postgres;
    SQLite serialises writes anyway).
    """
    with transaction.atomic():
        slot = (
            TimeSlot.objects.select_for_update()
            .select_related("experience__winery")
            .get(pk=slot_id)
        )
        experience = slot.experience
        if slot.is_closed or not experience.is_active or not experience.winery.is_published:
            raise BookingError("This time is no longer available.")
        if slot.start <= timezone.now():
            raise BookingError("This time has already passed.")
        if party_size > experience.max_party_size:
            raise BookingError(
                f"Groups larger than {experience.max_party_size} need to contact the winery directly."
            )
        if party_size > slot.seats_left:
            if slot.seats_left == 0:
                raise BookingError("Sorry, this time just sold out.")
            raise BookingError(f"Only {slot.seats_left} seats are left at this time.")

        booking = Booking.objects.create(
            slot=slot,
            guest_name=guest_name,
            guest_email=guest_email,
            guest_phone=guest_phone,
            party_size=party_size,
            notes=notes,
        )

    transaction.on_commit(lambda: send_booking_emails(booking, "confirmed"))
    return booking


def cancel_booking(booking):
    if not booking.can_cancel:
        raise BookingError("This booking can no longer be cancelled online.")
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
    send_booking_emails(booking, "cancelled")
    return booking


def send_booking_emails(booking, event):
    """Email the guest and the winery about a confirmed or cancelled booking."""
    context = {
        "booking": booking,
        "slot": booking.slot,
        "winery": booking.winery,
        "booking_url": settings.SITE_URL + booking.get_absolute_url(),
    }
    subject_prefix = "Booking confirmed" if event == "confirmed" else "Booking cancelled"
    subject = f"{subject_prefix}: {booking.slot.experience.name} at {booking.winery.name}"

    send_mail(
        subject,
        render_to_string(f"tastings/email/guest_{event}.txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [booking.guest_email],
    )
    send_mail(
        f"[{booking.reference}] {subject} — {booking.guest_name}, party of {booking.party_size}",
        render_to_string(f"tastings/email/winery_{event}.txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [booking.winery.email],
    )


def generate_slots(experience, *, start_date, end_date, weekdays, times, capacity=None):
    """Create a slot at each of ``times`` on each matching day in the range.

    ``weekdays`` uses Monday=0 ... Sunday=6. Slots that already exist are
    left alone. Returns the number of slots created.
    """
    tz = timezone.get_current_timezone()
    created = 0
    day = start_date
    while day <= end_date:
        if day.weekday() in weekdays:
            for t in times:
                start = timezone.make_aware(datetime.combine(day, t), tz)
                if start <= timezone.now():
                    continue
                try:
                    with transaction.atomic():
                        _, was_created = TimeSlot.objects.get_or_create(
                            experience=experience,
                            start=start,
                            defaults={"capacity": capacity or experience.capacity},
                        )
                except IntegrityError:
                    was_created = False
                created += was_created
        day += timedelta(days=1)
    return created
