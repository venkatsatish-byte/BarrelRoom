# BarrelRoom

Online booking for winery tastings and tours. Small wineries list their tasting
experiences and open time slots; guests pick a time and book in under a minute
instead of phoning or emailing.

Built with Python and [Django](https://www.djangoproject.com/).

## What's in this first version

**For guests**
- Browse wineries, filtered by region
- See each experience's open times for the next 60 days, with seats left
- Book a slot (name, email, party size, notes) and get a confirmation email
- View or cancel a booking from the link in that email

**For wineries**
- Sign up (creates a login and a winery in one step)
- Add tasting experiences: price per guest, duration, capacity per slot, largest party
- Add time slots in bulk (date range, weekdays, start times) and close or reopen single slots
- Dashboard with today's guests, upcoming bookings and guest notes; cancel a booking and the guest is emailed
- A shareable booking page link to put on the winery's own website

**Rules the app enforces**
- A slot can never be overbooked (the slot is locked while a booking is written)
- Party size limits, closed slots, past slots and unpublished wineries are all refused
- Winery owners can only see and change their own winery's data

Payments aren't taken online yet — guests pay at the winery.

## Run it locally

Needs Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo         # optional: two demo wineries with two weeks of times
python manage.py runserver
```

Then open http://localhost:8000.

- Winery dashboard: http://localhost:8000/dashboard/ (demo login: `demo` / `barrelroom-demo`)
- Admin site for you as platform operator: create a superuser with
  `python manage.py createsuperuser`, then go to http://localhost:8000/admin/

Emails are printed in the terminal running the server rather than sent.

## Tests

```bash
python manage.py test
```

GitHub Actions runs the tests on every push and pull request.

## Configuration

Settings come from environment variables; the defaults suit local development.

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_DEBUG` | `true` | Turn off in production |
| `DJANGO_SECRET_KEY` | dev key | Required when debug is off |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — | e.g. `https://barrelroom.example` |
| `SITE_URL` | `http://localhost:8000` | Used for links in emails |
| `DJANGO_TIME_ZONE` | `America/Los_Angeles` | Time zone tasting times are shown in |
| `DATABASE_ENGINE` | SQLite | Set to `postgresql` and fill in `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT` |
| `DJANGO_EMAIL_BACKEND` | console | `django.core.mail.backends.smtp.EmailBackend` to send real mail, with `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` |

## Project layout

```
barrelroom/        Django project settings and root URLs
tastings/
  models.py        Winery, Experience, TimeSlot, Booking
  services.py      Booking rules: create/cancel bookings, emails, bulk slot creation
  forms.py         Guest booking, winery signup, dashboard forms
  views.py         Guest pages and winery dashboard
  templates/       Page and email templates
  management/      seed_demo command
  tests.py
templates/         Base layout, login and signup pages
static/css/        Stylesheet
```

## Next steps

- Online deposits and a per-booking commission with Stripe Connect
- Reminder email the day before a tasting
- Embeddable booking widget for winery websites
- A time zone per winery, for regions in different zones
- Region pages for tourists, reviews, and multi-winery tour packages
