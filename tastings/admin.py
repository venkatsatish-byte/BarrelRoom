from django.contrib import admin

from .models import Booking, Experience, TimeSlot, Winery


class ExperienceInline(admin.TabularInline):
    model = Experience
    extra = 0
    fields = ["name", "price_per_guest", "capacity", "max_party_size", "is_active"]


@admin.register(Winery)
class WineryAdmin(admin.ModelAdmin):
    list_display = ["name", "region", "owner", "email", "is_published", "created_at"]
    list_filter = ["region", "is_published"]
    search_fields = ["name", "region", "email"]
    inlines = [ExperienceInline]


@admin.register(Experience)
class ExperienceAdmin(admin.ModelAdmin):
    list_display = ["name", "winery", "price_per_guest", "capacity", "is_active"]
    list_filter = ["is_active", "winery__region"]
    search_fields = ["name", "winery__name"]


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ["experience", "start", "capacity", "seats_left", "is_closed"]
    list_filter = ["is_closed", "experience__winery"]
    date_hierarchy = "start"


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["reference", "guest_name", "party_size", "slot", "status", "created_at"]
    list_filter = ["status", "slot__experience__winery"]
    search_fields = ["reference", "guest_name", "guest_email"]
    readonly_fields = ["reference", "created_at", "cancelled_at"]
