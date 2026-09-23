from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from tastings.models import Experience, Winery
from tastings.services import generate_slots

DEMO_WINERIES = [
    {
        "name": "Oak Hollow Cellars",
        "region": "Napa Valley",
        "description": "Family-run estate pouring small-lot Cabernet since 1987.",
        "address": "1200 Silverado Trail, Napa, CA",
        "phone": "(707) 555-0142",
        "experiences": [
            ("Estate Tasting", "Five current releases on the terrace.", 60, 45, 12, 6),
            ("Cave Tour & Barrel Tasting", "Walk the caves and taste from the barrel with our cellar master.", 90, 85, 8, 4),
        ],
    },
    {
        "name": "Red Fern Vineyard",
        "region": "Willamette Valley",
        "description": "Pinot Noir from a hillside farmed without irrigation.",
        "address": "8800 NE Worden Hill Rd, Dundee, OR",
        "phone": "(503) 555-0199",
        "experiences": [
            ("Pinot Flight", "Four single-vineyard Pinots, seated.", 60, 35, 16, 8),
        ],
    },
]


class Command(BaseCommand):
    help = "Create demo wineries, experiences and two weeks of time slots. Login: demo / barrelroom-demo"

    def handle(self, *args, **options):
        User = get_user_model()
        owner, created = User.objects.get_or_create(username="demo", defaults={"email": "demo@example.com"})
        if created:
            owner.set_password("barrelroom-demo")
            owner.save()

        today = timezone.localdate()
        slot_count = 0
        for data in DEMO_WINERIES:
            winery, _ = Winery.objects.get_or_create(
                name=data["name"],
                defaults={
                    "owner": owner,
                    "region": data["region"],
                    "description": data["description"],
                    "address": data["address"],
                    "phone": data["phone"],
                    "email": "demo@example.com",
                },
            )
            for name, desc, minutes, price, capacity, max_party in data["experiences"]:
                experience, _ = Experience.objects.get_or_create(
                    winery=winery,
                    name=name,
                    defaults={
                        "description": desc,
                        "duration_minutes": minutes,
                        "price_per_guest": price,
                        "capacity": capacity,
                        "max_party_size": max_party,
                    },
                )
                slot_count += generate_slots(
                    experience,
                    start_date=today,
                    end_date=today + timedelta(days=14),
                    weekdays=range(7),
                    times=[time(11), time(13, 30), time(16)],
                )

        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready ({slot_count} new slots). Winery login: demo / barrelroom-demo"
        ))
