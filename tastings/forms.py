from datetime import time

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Experience, Winery

WEEKDAY_CHOICES = [
    (0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun"),
]


class BookingForm(forms.Form):
    guest_name = forms.CharField(label="Your name", max_length=120)
    guest_email = forms.EmailField(label="Email")
    guest_phone = forms.CharField(label="Phone (optional)", max_length=30, required=False)
    party_size = forms.IntegerField(label="Guests", min_value=1)
    notes = forms.CharField(
        label="Anything we should know?",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Allergies, celebrations, accessibility needs"}),
    )

    def __init__(self, *args, slot, **kwargs):
        super().__init__(*args, **kwargs)
        limit = min(slot.experience.max_party_size, slot.seats_left) or 1
        self.fields["party_size"].max_value = limit
        self.fields["party_size"].widget.attrs["max"] = limit
        self.fields["party_size"].initial = min(2, limit)


class SignupForm(UserCreationForm):
    """Creates the owner's login and their winery in one step."""

    email = forms.EmailField(label="Your email")
    winery_name = forms.CharField(max_length=120)
    region = forms.CharField(max_length=80, help_text="e.g. Napa Valley")

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            Winery.objects.create(
                owner=user,
                name=self.cleaned_data["winery_name"],
                region=self.cleaned_data["region"],
                email=user.email,
            )
        return user


class WineryForm(forms.ModelForm):
    class Meta:
        model = Winery
        fields = ["name", "region", "description", "address", "email", "phone", "website", "is_published"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class ExperienceForm(forms.ModelForm):
    class Meta:
        model = Experience
        fields = [
            "name", "description", "duration_minutes", "price_per_guest",
            "capacity", "max_party_size", "is_active",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def clean(self):
        cleaned = super().clean()
        capacity, max_party = cleaned.get("capacity"), cleaned.get("max_party_size")
        if capacity and max_party and max_party > capacity:
            self.add_error("max_party_size", "Can't be larger than the slot capacity.")
        return cleaned


class SlotGeneratorForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    weekdays = forms.TypedMultipleChoiceField(
        choices=WEEKDAY_CHOICES,
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
        initial=[3, 4, 5, 6],
    )
    times = forms.CharField(
        help_text="Start times, comma separated, 24-hour. e.g. 11:00, 13:30, 15:30",
        initial="11:00, 13:00, 15:00",
    )

    def clean_times(self):
        parsed = []
        for raw in self.cleaned_data["times"].split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                hour, minute = (int(part) for part in raw.split(":"))
                parsed.append(time(hour, minute))
            except ValueError:
                raise forms.ValidationError(f"“{raw}” isn't a time like 14:30.")
        if not parsed:
            raise forms.ValidationError("Add at least one start time.")
        return sorted(set(parsed))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end:
            if end < start:
                self.add_error("end_date", "End date is before the start date.")
            elif (end - start).days > 180:
                self.add_error("end_date", "Generate at most 6 months at a time.")
        return cleaned
