from collections import OrderedDict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import BookingForm, ExperienceForm, SignupForm, SlotGeneratorForm, WineryForm
from .models import Booking, Experience, TimeSlot, Winery
from .services import BookingError, cancel_booking, create_booking, generate_slots

BOOKING_WINDOW_DAYS = 60


# --- Guest-facing pages -----------------------------------------------------


def home(request):
    region = request.GET.get("region", "").strip()
    wineries = (
        Winery.objects.filter(is_published=True)
        .annotate(active_experiences=Count("experiences", filter=Q(experiences__is_active=True)))
        .filter(active_experiences__gt=0)
    )
    regions = wineries.order_by("region").values_list("region", flat=True).distinct()
    if region:
        wineries = wineries.filter(region__iexact=region)
    return render(
        request,
        "tastings/home.html",
        {"wineries": wineries, "regions": regions, "selected_region": region},
    )


def winery_detail(request, slug):
    winery = get_object_or_404(Winery, slug=slug, is_published=True)
    experiences = winery.experiences.filter(is_active=True)
    return render(request, "tastings/winery_detail.html", {"winery": winery, "experiences": experiences})


def experience_detail(request, winery_slug, slug):
    experience = get_object_or_404(
        Experience.objects.select_related("winery"),
        winery__slug=winery_slug,
        winery__is_published=True,
        slug=slug,
        is_active=True,
    )
    horizon = timezone.now() + timedelta(days=BOOKING_WINDOW_DAYS)
    slots = experience.upcoming_slots().filter(start__lte=horizon).annotate(
        booked=Sum("bookings__party_size", filter=Q(bookings__status=Booking.Status.CONFIRMED))
    )
    days = OrderedDict()
    for slot in slots:
        slot.left = max(slot.capacity - (slot.booked or 0), 0)
        days.setdefault(timezone.localtime(slot.start).date(), []).append(slot)
    return render(
        request,
        "tastings/experience_detail.html",
        {"experience": experience, "winery": experience.winery, "days": days},
    )


def book(request, slot_id):
    slot = get_object_or_404(
        TimeSlot.objects.select_related("experience__winery"),
        pk=slot_id,
        experience__is_active=True,
        experience__winery__is_published=True,
    )
    if not slot.is_bookable:
        messages.error(request, "That time is no longer available — please pick another.")
        return redirect(slot.experience)

    form = BookingForm(request.POST or None, slot=slot)
    if request.method == "POST" and form.is_valid():
        try:
            booking = create_booking(slot.pk, **form.cleaned_data)
        except BookingError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "You're booked! A confirmation email is on its way.")
            return redirect(booking)
    return render(request, "tastings/book.html", {"slot": slot, "experience": slot.experience, "form": form})


def booking_detail(request, reference):
    booking = get_object_or_404(
        Booking.objects.select_related("slot__experience__winery"), reference=reference.upper()
    )
    return render(request, "tastings/booking_detail.html", {"booking": booking})


@require_POST
def booking_cancel(request, reference):
    booking = get_object_or_404(Booking, reference=reference.upper())
    try:
        cancel_booking(booking)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Your booking has been cancelled.")
    return redirect(booking)


# --- Winery sign-up and dashboard -------------------------------------------


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome to BarrelRoom! Add your first tasting experience below.")
        return redirect("dashboard")
    return render(request, "registration/signup.html", {"form": form})


def owned_winery(request):
    winery = request.user.wineries.first()
    if winery is None:
        raise Http404("This account has no winery.")
    return winery


@login_required
def dashboard(request):
    winery = owned_winery(request)
    now = timezone.now()
    today_end = timezone.localtime(now).replace(hour=23, minute=59, second=59)
    upcoming = (
        Booking.objects.filter(
            slot__experience__winery=winery,
            status=Booking.Status.CONFIRMED,
            slot__start__gte=now - timedelta(hours=3),
        )
        .select_related("slot__experience")
        .order_by("slot__start")
    )
    today = [b for b in upcoming if b.slot.start <= today_end]
    context = {
        "winery": winery,
        "today": today,
        "upcoming": upcoming[:50],
        "guests_today": sum(b.party_size for b in today),
        "experiences": winery.experiences.annotate(
            future_slots=Count("slots", filter=Q(slots__start__gt=now))
        ),
        "booking_url": request.build_absolute_uri(winery.get_absolute_url()),
    }
    return render(request, "tastings/dashboard/index.html", context)


@login_required
def winery_edit(request):
    winery = owned_winery(request)
    form = WineryForm(request.POST or None, instance=winery)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Winery details saved.")
        return redirect("dashboard")
    return render(request, "tastings/dashboard/form.html", {"form": form, "title": "Winery details"})


@login_required
def experience_edit(request, pk=None):
    winery = owned_winery(request)
    experience = get_object_or_404(Experience, pk=pk, winery=winery) if pk else Experience(winery=winery)
    form = ExperienceForm(request.POST or None, instance=experience)
    if request.method == "POST" and form.is_valid():
        experience = form.save()
        messages.success(request, f"Saved “{experience.name}”.")
        if pk is None:
            messages.info(request, "Now add some time slots guests can book.")
        return redirect("experience_slots", pk=experience.pk)
    title = f"Edit {experience.name}" if pk else "New tasting experience"
    return render(request, "tastings/dashboard/form.html", {"form": form, "title": title})


@login_required
def experience_slots(request, pk):
    winery = owned_winery(request)
    experience = get_object_or_404(Experience, pk=pk, winery=winery)
    form = SlotGeneratorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        created = generate_slots(experience, **form.cleaned_data)
        messages.success(request, f"Added {created} time slot{'s' if created != 1 else ''}.")
        return redirect("experience_slots", pk=experience.pk)
    slots = experience.slots.filter(start__gt=timezone.now()).annotate(
        booked=Sum("bookings__party_size", filter=Q(bookings__status=Booking.Status.CONFIRMED))
    )
    return render(
        request,
        "tastings/dashboard/slots.html",
        {"experience": experience, "slots": slots, "form": form},
    )


@login_required
@require_POST
def slot_toggle(request, pk):
    slot = get_object_or_404(TimeSlot, pk=pk, experience__winery__owner=request.user)
    slot.is_closed = not slot.is_closed
    slot.save(update_fields=["is_closed"])
    messages.success(request, f"{slot} is now {'closed' if slot.is_closed else 'open'}.")
    return redirect("experience_slots", pk=slot.experience_id)


@login_required
@require_POST
def dashboard_booking_cancel(request, pk):
    booking = get_object_or_404(Booking, pk=pk, slot__experience__winery__owner=request.user)
    try:
        cancel_booking(booking)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Cancelled booking {booking.reference}; the guest has been emailed.")
    return redirect("dashboard")
