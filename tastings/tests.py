from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Booking, Experience, TimeSlot, Winery
from .services import BookingError, cancel_booking, create_booking, generate_slots


class BookingTestCase(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("owner", "owner@example.com", "pw-12345!x")
        self.winery = Winery.objects.create(
            owner=self.owner, name="Oak Hollow", region="Napa Valley", email="winery@example.com"
        )
        self.experience = Experience.objects.create(
            winery=self.winery, name="Estate Tasting", price_per_guest=40, capacity=6, max_party_size=4
        )
        self.slot = TimeSlot.objects.create(
            experience=self.experience, start=timezone.now() + timedelta(days=2)
        )

    def book(self, party_size=2, slot=None):
        return create_booking(
            (slot or self.slot).pk,
            guest_name="Ana",
            guest_email="ana@example.com",
            party_size=party_size,
        )


class ModelTests(BookingTestCase):
    def test_slugs_are_generated_and_unique(self):
        twin = Winery.objects.create(owner=self.owner, name="Oak Hollow", region="Sonoma", email="x@example.com")
        self.assertEqual(self.winery.slug, "oak-hollow")
        self.assertEqual(twin.slug, "oak-hollow-2")

    def test_slot_capacity_defaults_to_experience(self):
        self.assertEqual(self.slot.capacity, 6)

    def test_seats_left_ignores_cancelled_bookings(self):
        booking = self.book(3)
        self.assertEqual(self.slot.seats_left, 3)
        cancel_booking(booking)
        self.assertEqual(self.slot.seats_left, 6)

    def test_total_price(self):
        self.assertEqual(self.book(3).total_price, 120)


class CreateBookingTests(BookingTestCase):
    def test_booking_sends_guest_and_winery_emails(self):
        with self.captureOnCommitCallbacks(execute=True):
            booking = self.book(2)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(len(booking.reference), 8)
        recipients = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(recipients, ["ana@example.com", "winery@example.com"])
        guest_email = next(m for m in mail.outbox if m.to == ["ana@example.com"])
        self.assertIn(booking.get_absolute_url(), guest_email.body)

    def test_cannot_overbook(self):
        self.book(4)
        with self.assertRaisesMessage(BookingError, "Only 2 seats"):
            self.book(3)
        self.book(2)
        with self.assertRaisesMessage(BookingError, "sold out"):
            self.book(1)

    def test_party_size_limit(self):
        with self.assertRaisesMessage(BookingError, "Groups larger than 4"):
            self.book(5)

    def test_past_and_closed_slots_are_rejected(self):
        past = TimeSlot.objects.create(experience=self.experience, start=timezone.now() - timedelta(hours=1))
        with self.assertRaisesMessage(BookingError, "already passed"):
            self.book(1, slot=past)
        self.slot.is_closed = True
        self.slot.save()
        with self.assertRaisesMessage(BookingError, "no longer available"):
            self.book(1)

    def test_unpublished_winery_is_rejected(self):
        self.winery.is_published = False
        self.winery.save()
        with self.assertRaises(BookingError):
            self.book(1)


class CancelBookingTests(BookingTestCase):
    def test_cancel_sends_emails(self):
        booking = self.book(2)
        mail.outbox.clear()
        cancel_booking(booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertIsNotNone(booking.cancelled_at)
        self.assertEqual(len(mail.outbox), 2)

    def test_cannot_cancel_twice(self):
        booking = self.book(2)
        cancel_booking(booking)
        with self.assertRaises(BookingError):
            cancel_booking(booking)


class GenerateSlotsTests(BookingTestCase):
    def test_generates_on_chosen_weekdays_only_and_skips_duplicates(self):
        start = timezone.localdate() + timedelta(days=7)
        start -= timedelta(days=start.weekday())  # a Monday a week or more out
        end = start + timedelta(days=13)  # two full weeks
        kwargs = dict(start_date=start, end_date=end, weekdays=[5, 6], times=[time(11), time(15)])
        self.assertEqual(generate_slots(self.experience, **kwargs), 8)  # 2 weekends x 2 days x 2 times
        self.assertEqual(generate_slots(self.experience, **kwargs), 0)
        weekdays = {timezone.localtime(s.start).weekday() for s in self.experience.slots.filter(start__date__gte=start)}
        self.assertEqual(weekdays, {5, 6})

    def test_skips_times_in_the_past(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        created = generate_slots(
            self.experience, start_date=yesterday, end_date=yesterday, weekdays=range(7), times=[time(12)]
        )
        self.assertEqual(created, 0)


class GuestPageTests(BookingTestCase):
    def test_home_lists_wineries_and_filters_by_region(self):
        other = Winery.objects.create(owner=self.owner, name="Red Fern", region="Willamette Valley", email="r@example.com")
        Experience.objects.create(winery=other, name="Pinot Flight", price_per_guest=30)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Oak Hollow")
        self.assertContains(response, "Red Fern")
        response = self.client.get(reverse("home"), {"region": "napa valley"})
        self.assertContains(response, "Oak Hollow")
        self.assertNotContains(response, "Red Fern")

    def test_experience_page_shows_bookable_times(self):
        response = self.client.get(self.experience.get_absolute_url())
        self.assertContains(response, reverse("book", args=[self.slot.pk]))
        self.assertContains(response, "6 left")

    def test_book_flow(self):
        url = reverse("book", args=[self.slot.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {
                "guest_name": "Ana", "guest_email": "ana@example.com", "party_size": 2,
            })
        booking = Booking.objects.get()
        self.assertRedirects(response, booking.get_absolute_url())
        self.assertContains(self.client.get(booking.get_absolute_url()), booking.reference)
        self.assertEqual(len(mail.outbox), 2)

    def test_book_form_rejects_party_over_seats_left(self):
        self.book(4)
        response = self.client.post(reverse("book", args=[self.slot.pk]), {
            "guest_name": "Bo", "guest_email": "bo@example.com", "party_size": 3,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Booking.objects.count(), 1)

    def test_guest_can_cancel_with_reference(self):
        booking = self.book(2)
        response = self.client.post(reverse("booking_cancel", args=[booking.reference.lower()]))
        self.assertRedirects(response, booking.get_absolute_url())
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)

    def test_unknown_reference_is_404(self):
        self.assertEqual(self.client.get(reverse("booking_detail", args=["NOPE1234"])).status_code, 404)


class DashboardTests(BookingTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)
        intruder = get_user_model().objects.create_user("intruder", "i@example.com", "pw-12345!x")
        self.intruder_winery = Winery.objects.create(
            owner=intruder, name="Other Place", region="Sonoma", email="o@example.com"
        )

    def test_signup_creates_user_and_winery(self):
        self.client.logout()
        response = self.client.post(reverse("signup"), {
            "username": "newowner",
            "email": "new@example.com",
            "winery_name": "Hillcrest",
            "region": "Paso Robles",
            "password1": "a-Str0ng-passphrase",
            "password2": "a-Str0ng-passphrase",
        })
        self.assertRedirects(response, reverse("dashboard"))
        winery = Winery.objects.get(name="Hillcrest")
        self.assertEqual(winery.owner.username, "newowner")
        self.assertEqual(winery.email, "new@example.com")

    def test_dashboard_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_dashboard_lists_bookings(self):
        self.book(3)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Ana")
        self.assertContains(response, "Estate Tasting")

    def test_create_experience_and_generate_slots(self):
        response = self.client.post(reverse("experience_create"), {
            "name": "Cave Tour", "duration_minutes": 90, "price_per_guest": "85.00",
            "capacity": 8, "max_party_size": 4, "is_active": "on",
        })
        experience = Experience.objects.get(name="Cave Tour")
        self.assertEqual(experience.winery, self.winery)
        self.assertRedirects(response, reverse("experience_slots", args=[experience.pk]))

        start = timezone.localdate() + timedelta(days=1)
        self.client.post(reverse("experience_slots", args=[experience.pk]), {
            "start_date": start, "end_date": start + timedelta(days=6),
            "weekdays": list(range(7)), "times": "11:00, 14:30",
        })
        self.assertEqual(experience.slots.count(), 14)

    def test_experience_rejects_party_bigger_than_capacity(self):
        response = self.client.post(reverse("experience_create"), {
            "name": "Tiny", "duration_minutes": 60, "price_per_guest": "10",
            "capacity": 2, "max_party_size": 4,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Experience.objects.filter(name="Tiny").exists())

    def test_slot_generator_rejects_bad_times(self):
        response = self.client.post(reverse("experience_slots", args=[self.experience.pk]), {
            "start_date": date.today(), "end_date": date.today(), "weekdays": [0], "times": "noon",
        })
        self.assertContains(response, "isn&#x27;t a time")

    def test_toggle_slot(self):
        self.client.post(reverse("slot_toggle", args=[self.slot.pk]))
        self.slot.refresh_from_db()
        self.assertTrue(self.slot.is_closed)

    def test_winery_cancels_booking(self):
        booking = self.book(2)
        self.client.post(reverse("dashboard_booking_cancel", args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)

    def test_owners_cannot_touch_other_wineries(self):
        other_exp = Experience.objects.create(winery=self.intruder_winery, name="Theirs", price_per_guest=10)
        other_slot = TimeSlot.objects.create(experience=other_exp, start=timezone.now() + timedelta(days=1))
        other_booking = create_booking(
            other_slot.pk, guest_name="Cy", guest_email="cy@example.com", party_size=1
        )
        self.assertEqual(self.client.get(reverse("experience_edit", args=[other_exp.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("experience_slots", args=[other_exp.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("slot_toggle", args=[other_slot.pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("dashboard_booking_cancel", args=[other_booking.pk])).status_code, 404
        )
        other_booking.refresh_from_db()
        self.assertEqual(other_booking.status, Booking.Status.CONFIRMED)
