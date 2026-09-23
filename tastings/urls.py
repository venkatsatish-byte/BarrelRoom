from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/winery/", views.winery_edit, name="winery_edit"),
    path("dashboard/experiences/new/", views.experience_edit, name="experience_create"),
    path("dashboard/experiences/<int:pk>/", views.experience_edit, name="experience_edit"),
    path("dashboard/experiences/<int:pk>/slots/", views.experience_slots, name="experience_slots"),
    path("dashboard/slots/<int:pk>/toggle/", views.slot_toggle, name="slot_toggle"),
    path("dashboard/bookings/<int:pk>/cancel/", views.dashboard_booking_cancel, name="dashboard_booking_cancel"),
    path("book/<int:slot_id>/", views.book, name="book"),
    path("booking/<str:reference>/", views.booking_detail, name="booking_detail"),
    path("booking/<str:reference>/cancel/", views.booking_cancel, name="booking_cancel"),
    path("w/<slug:slug>/", views.winery_detail, name="winery_detail"),
    path("w/<slug:winery_slug>/<slug:slug>/", views.experience_detail, name="experience_detail"),
]
