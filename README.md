# Notification System

Admin-managed notifications over **WhatsApp**, **Email** and **Web Push**.
Triggers, templates and on/off switches all live in **one table** in the admin
panel — no opening the Meta, Brevo or OneSignal dashboards.

| Part | Stack | Host |
|---|---|---|
| Backend | Python 3.12 · Django 5.1 · DRF | Render |
| Frontend | TypeScript · Next.js 15 (App Router) | Vercel |

```
New folder/
├── backend/            Django API + notification engine
│   ├── config/         settings, urls, wsgi/asgi
│   ├── notifications/  the app: models, API, providers, tests
│   │   ├── services/   provider layer + dispatcher
│   │   └── management/commands/  seed, scan, purge, vapid
│   ├── scripts/        e2e_smoke.py
└── frontend/           Next.js site + admin panel
    ├── src/app/        routes (/, /login, /dashboard, /admin/*)
    ├── src/components/ TopBar, TemplateEditor, Toast, ui
    ├── src/lib/        api client, auth, push
    └── public/sw.js    service worker for Web Push
```

---

## Test safety

Automated Django tests always force notification sandbox mode, regardless of the local `.env`. This prevents `python manage.py test` from making real WhatsApp, Brevo, or OneSignal network calls when local development is configured with `NOTIFICATION_SANDBOX=False`.

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt

copy .env.example .env          # Windows     (macOS/Linux: cp .env.example .env)
python manage.py migrate
python manage.py seed_triggers --with-templates
python manage.py create_demo_users --admin
python manage.py runserver
```

Check it is alive: <http://127.0.0.1:8000/api/health/> → `{"status": "ok", ...}`

### 2. Frontend

```bash
cd frontend
npm install
copy .env.example .env.local    # Windows     (macOS/Linux: cp .env.example .env.local)
npm run dev
```

Open <http://localhost:3000> and sign in as **`admin` / `admin12345`**.

### Demo accounts

| Username | Password | Notes |
|---|---|---|
| `admin` | `admin12345` | staff/superuser — sees the notification table |
| `amit` | `demo12345` | has a WhatsApp number on the profile |
| `priya` | `demo12345` | plain user |
| `demo` | `demo12345` | user with **no** WhatsApp number (good for showing skips) |

Sign in with either the username or the email address.

---

## How it works

### Trigger
Anything that should cause a message. Seeded: `login`, `logout`,
`not_logged_in_1_day`, `not_logged_in_1_week`, `password_reset`,
`order_placed`. Each is one row in the admin table.

- `kind = event` → fired by application code (`POST /api/auth/login/` fires `login`).
- `kind = inactivity` → fired by the daily scanner, which reads
  `config.days` and each user's `last_seen_at`.

### Channel
WhatsApp (Cloud API) · Email (Brevo, with provider abstraction) · Web Push
(browser only, no mobile app push). A trigger can use one, two or all three.

### Template
One cell of the table. Copy uses `{{ placeholder }}` syntax:

```
Hi {{ first_name }}, it has been {{ days }} days since you visited {{ site_name }}.
```

Template variables are rendered from a controlled context. Unknown variables are
rejected with a validation/delivery error instead of silently becoming blank.
The placeholders used by a template are auto-detected in `Template.variables`,
and `Template.variable_mapping` stores the safe application source for each
variable (for example `first_name -> user.first_name`). `GET /api/variables/scan/`
reports stored templates containing unsupported placeholders.

Available variables: `user`, `username`, `first_name`, `last_name`, `full_name`,
`email`, `phone`, `trigger`, `trigger_key`, `days`, `days_away`, `last_seen`,
`date`, `time`, `year`, `month`, `day`, `site_name`.
Filters: `{{ name|upper }}`, `|lower`, `|title`, `|trim`, `|date`, `|time`.

### Adding a trigger
The **+ Add trigger** button in the admin table creates a new row. You give it a
name, an optional key (derived from the name when left blank), and a type:

- **Event** — fired by your code, e.g. `tasks.fire("cart_abandoned", user)`.
- **Inactivity window** — fired by the daily scan; must state how many days
  count as inactive.

The new row appears immediately with three empty cells, and you fill them the
same way as any other row.

### WhatsApp template approval
WhatsApp provider templates still have to be created/submitted in Meta when the
account requires them. Once a provider template name exists, the admin panel's
**Sync** action reads the current template id/language/approval status from the
configured WhatsApp Business Account. Sending a named provider template is
blocked until Meta reports it as approved:

| Status | Meaning |
|---|---|
| Not submitted | Default. Fine for the sandbox. |
| Draft in Meta | Created in the template console, not yet sent for review. |
| Pending review | Waiting on Meta. Can take minutes to hours. |
| Approved | The template name can now be used when sending. |
| Rejected | Add the reason, fix it in Meta, resubmit. |

The editor links to Meta's
[template console](https://business.facebook.com/wa/manage/message-templates/) for
provider-side creation/submission, then **Sync** keeps local status current. Sync
requires `WHATSAPP_BUSINESS_ACCOUNT_ID` in addition to the access token. The
approved status shows as a badge in the table.

### Toggle
Two levels, both respected by the engine:
- `Trigger.is_active` — master switch for the whole trigger.
- `Template.is_enabled` — per-channel switch.

**Test sends deliberately bypass both**, so you can verify copy before switching
a channel on for real users.

### What gets skipped, and why
Every attempt is written to `NotificationLog` with a status, so the Activity
page always explains itself:

| Status | Meaning |
|---|---|
| `sent` | provider accepted it |
| `simulated` | sandbox mode — rendered and logged, nothing left the machine |
| `skipped` | no template / trigger off / toggle off / opted out / no destination |
| `failed` | provider rejected it; `error` holds the reason |

Destinations are **always masked** in the log (`+9********10`, `s******@else.com`).

### Sandbox mode
`NOTIFICATION_SANDBOX=True` (the default) means no request ever leaves the
machine. Turn it off once real sandbox keys are in `.env`:

```
NOTIFICATION_SANDBOX=False
```

---

## Provider setup

Run `python manage.py provider_status` at any time to see what is missing.

### WhatsApp — Meta Cloud API sandbox
1. <https://developers.facebook.com> → **My Apps** → create app → add **WhatsApp**.
2. **WhatsApp → API Setup** shows a test phone number and a temporary token.
3. **Configuration → WhatsApp → Phone numbers → Test recipients** — add your own
   number. Only approved recipients can receive sandbox messages.
4. `.env`:

```ini
WHATSAPP_ACCESS_TOKEN=your_test_token
WHATSAPP_PHONE_NUMBER_ID=your_test_phone_number_id
WHATSAPP_BUSINESS_ACCOUNT_ID=your_waba_id
WHATSAPP_API_VERSION=v25.0
```

Tokens expire often — mint a new one from Meta when a send fails.

### Email — Brevo (current deployment) or another supported provider
`EMAIL_PROVIDER` selects the backend. All of them need a token **and** a
verified sender.

| Provider | `EMAIL_PROVIDER` | Free tier | Notes |
|---|---|---|---|
| Postmark | `postmark` | ~100/month | named in the spec; strict marketing/transactional separation |
| Brevo | `brevo` | 300/day (~9k/mo) | most generous for repeated test sends |
| Resend | `resend` | 3,000/month | good DX for a React/Next frontend |
| Mailgun | `mailgun` | 100–300/day | built-in email validation |
| Amazon SES | `ses` | 62,000/month (12 mo, from EC2) | cheapest at scale, more setup |

Brevo (used by the deployed demo):

```ini
EMAIL_PROVIDER=brevo
BREVO_API_KEY=your_key
BREVO_FROM_EMAIL=you@yourdomain.com
```

Also available: `EMAIL_PROVIDER=console` logs the message instead of sending it.

### Web Push — OneSignal (the spec's path) or VAPID

Both are fully wired, on the **frontend as well as the backend**. The backend
tells the browser which one is active, via `GET /api/config/` →
`push.backend`, and the browser subscribes through that transport:

| `push.backend` | When | How the browser subscribes |
|---|---|---|
| `onesignal` | `ONESIGNAL_APP_ID` + `ONESIGNAL_REST_API_KEY` are set | loads the OneSignal Web SDK, asks permission, stores the player id |
| `vapid` | `VAPID_PUBLIC_KEY` + `VAPID_PRIVATE_KEY` are set | native `PushManager` with `applicationServerKey` |
| `none` | neither configured | the UI says exactly which variables are missing |

If both are configured, OneSignal wins, because it is the option the spec names.
A OneSignal deployment loads the OneSignal SDK lazily only when it is the active
transport; a VAPID-only deployment never loads the OneSignal SDK.

**OneSignal**

```bash
# .env
ONESIGNAL_APP_ID=your_app_id
ONESIGNAL_REST_API_KEY=your_api_key
```

Then in the OneSignal dashboard: create a **Website** app, enable **Web Push
only** (this is where you "turn off iOS and Android"), and subscribe in your
browser once. Player ids are stored keyed by a synthetic
`https://onesignal.app/player/<id>` url, because the backend's uniqueness is on
`endpoint`; that value is never fetched.

**Raw Web Push (VAPID)** — no third-party account needed:

```bash
python manage.py generate_vapid_keys
```

```ini
VAPID_PUBLIC_KEY=BP...
VAPID_PRIVATE_KEY=...
VAPID_CLAIM_EMAIL=mailto:you@example.com
```

`VAPID_PUBLIC_KEY` is published to the browser via `GET /api/config/`; the
private key never leaves the backend. The frontend registers `public/sw.js` and
POSTs the subscription to `/api/push/subscribe/`.

> iOS requires a user-installed Home Screen web app for Web Push. Use Chrome or
> Edge on desktop for the demo.
>
> Subscriptions stay scoped to the user who made them. A *test* send may borrow
> any available device; a normal send never does.

---

## Environment variables

### Backend (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev placeholder | **required** when `DJANGO_DEBUG=False`; the app refuses to boot with the default |
| `DJANGO_DEBUG` | `True` | set `False` in production |
| `DJANGO_ALLOWED_HOSTS` | `*` | comma separated |
| `CORS_ORIGINS` | `http://localhost:3000` | also used for `CSRF_TRUSTED_ORIGINS` |
| `POSTGRES_*` | empty | when `POSTGRES_DB` is set, Postgres is used; otherwise sqlite |
| `NOTIFICATION_SANDBOX` | `True` | `False` to really send |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID` | — | WhatsApp Cloud API send + template status sync |
| `EMAIL_PROVIDER` | `brevo` | `brevo`/`postmark`/`resend`/`mailgun`/`ses`/`console` |
| `POSTMARKAPP_TOKEN`, `POSTMARK_FROM_EMAIL` | — | Postmark |
| `BREVO_API_KEY`, `BREVO_FROM_EMAIL` | — | Brevo |
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | — | Resend |
| `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_FROM_EMAIL` | — | Mailgun |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `SES_FROM_EMAIL` | — | Amazon SES |
| `ONESIGNAL_APP_ID`, `ONESIGNAL_REST_API_KEY` | — | OneSignal Web Push |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIM_EMAIL` | — | raw Web Push |
| `FRONTEND_URL` | `http://localhost:3000` | link target in push notifications |
| `LOG_RETENTION_DAYS` | `90` | window for `manage.py purge_logs` |

### Frontend (`frontend/.env.local`)

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Django base URL the browser calls (e.g. the Render URL) |
| `API_URL_INTERNAL` | optional server-side URL |

---

## API reference

Public (no token):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health/` | liveness + sandbox flag |
| `GET` | `/api/config/` | channels, provider readiness, **which Web Push transport is live**, VAPID key, variable catalogue |
| `POST` | `/api/auth/register/` | create a user; returns DRF token + JWT access/refresh |
| `POST` | `/api/auth/login/` | `{identifier, password}` → DRF token + JWT access/refresh + user + dispatch report |
| `POST` | `/api/auth/token/refresh/` | refresh a JWT access token |

Authenticated as the user:

| Method | Path | Purpose |
|---|---|---|
| `GET`/`PATCH` | `/api/auth/me/` | current user |
| `PATCH` | `/api/auth/me/profile/` | own phone number + per-channel opt-ins |
| `POST` | `/api/auth/logout/` | fires `logout`, revokes DRF token; optionally blacklists supplied JWT refresh token |
| `POST` | `/api/users/activity/` | throttled frontend heartbeat; updates `last_seen_at` for inactivity triggers |
| `POST` | `/api/push/subscribe/` | register/refresh a browser subscription |
| `POST` | `/api/push/unsubscribe/` | deactivate subscriptions |

Authenticated as staff:

| Method | Path | Purpose |
|---|---|---|
| `GET`/`POST` | `/api/triggers/` | list (nested templates) / create (`name`, `kind`, `config.days`) |
| `GET`/`PATCH`/`DELETE` | `/api/triggers/{key}/` | detail — **key**, not id |
| `POST` | `/api/triggers/{key}/toggle/` | `{is_active}` |
| `POST` | `/api/triggers/{key}/fire/` | `{user_id?}` — fire now (ignores toggles) |
| `GET`/`POST` | `/api/templates/` | list (`?trigger=&channel=`) / create (`trigger_key`) |
| `GET`/`PATCH`/`DELETE` | `/api/templates/{id}/` | detail |
| `POST` | `/api/templates/{id}/toggle/` | flip `is_enabled` |
| `GET` | `/api/templates/{id}/preview/?user_id=` | rendered copy, nothing sent |
| `POST` | `/api/templates/{id}/test/` | tests exactly this one template/channel; `{user_id?, email?, phone?}` |
| `POST` | `/api/templates/{id}/sync/` | WhatsApp only: refresh Meta provider template id/status |
| `POST` | `/api/templates/draft-test/` | send **unsaved** copy from the editor |
| `GET` | `/api/push/subscriptions/` | all subscriptions |
| `GET` | `/api/logs/?channel=&status=&trigger=&limit=` | activity feed |
| `GET` | `/api/users/?search=` | pick a test recipient |
| `GET` | `/api/stats/` | dashboard counters |
| `GET` | `/api/variables/scan/` | templates using unknown placeholders |

`Template` also carries `provider_template_id`, WhatsApp approval fields
(`provider_status`, `provider_status_note`, `provider_submitted_at`) and
`variable_mapping`. WhatsApp provider-template sends require `approved`; Email
and Web Push ignore WhatsApp approval state.

### Firing a trigger from your own code

```python
from notifications import tasks

tasks.fire("login", user)                       # respects toggles and opt-ins
tasks.fire("order_placed", user, context_extra={"order_id": "A-1042"})
```

```python
# or fire an inactivity window on demand
from notifications.tasks import scan_inactive_users
scan_inactive_users(dry_run=True)
```

---

## Management commands

| Command | What it does |
|---|---|
| `manage.py seed_triggers --with-templates [--reset]` | create the spec's triggers + starter copy |
| `manage.py create_demo_users --admin` | demo users and the admin account |
| `manage.py provider_status` | what is configured, what is missing |
| `manage.py generate_vapid_keys` | print a VAPID key pair for Web Push |
| `manage.py scan_inactive [--dry-run]` | fire the inactivity triggers |
| `manage.py purge_logs [--days N]` | delete old `NotificationLog` rows (`0` disables) |

`seed_triggers` is safe to re-run: existing triggers and templates are left
alone so it never clobbers copy an admin has edited. Pass `--reset` to force the
triggers back to their spec values (name, kind, `config.days`, order, and
`is_active=True`) — useful if you ever hand-edited a trigger's `kind`.

---

## Tests

```bash
# 125 unit + API tests
cd backend && python manage.py test notifications

# 57 end-to-end HTTP checks against a running server
python backend/scripts/e2e_smoke.py http://127.0.0.1:8000

# frontend
cd frontend && npm run typecheck && npm run build
```

`e2e_smoke.py` resolves users by name, creates and removes its own trigger, and
cleans up after itself — so it is safe to re-run and works against a deployed
backend, not just a fresh local database. Pass the Render URL to run it against
production.

`check --deploy` is clean with a real `DJANGO_SECRET_KEY`.

---

## Current deployed demo (verified 28 Sep 2026)

- Frontend: <https://notification-system-opal-nine.vercel.app>
- Backend: <https://notification-api-dft7.onrender.com>
- Health: <https://notification-api-dft7.onrender.com/api/health/>
- Email: Brevo test sends and automatic Login/Logout delivery verified.
- Web Push: OneSignal subscription plus Login/Logout delivery verified on the Vercel domain.
- WhatsApp: Cloud API credentials are configured; `welcome_back_v1` and
  `signed_out_v1` are waiting for Meta template approval before final real sends.


## Deploy

### Backend → Render
1. Push the repo to GitHub.
2. Render → **New → Blueprint** → pick the repo. The repository-root
   `render.yaml` is included so Render discovers the Blueprint directly.
3. Fill the `sync: false` values in the Render dashboard:
   `CORS_ORIGINS`, `FRONTEND_URL`, and the provider keys you obtained.
4. The Blueprint build runs migrations, seeds trigger rows and collects static files automatically.
   Render Free does not provide Shell access. For an assignment-only demo account,
   temporarily add `python manage.py create_demo_users --admin` to the Blueprint
   build command, deploy once, then remove that line and redeploy. Do not leave a
   fixed demo credential bootstrap in the permanent production build.

The daily inactivity scan is a cron job. Free plans cannot run cron, so either
uncomment the `type: cron` block in `render.yaml` on a paid plan, or hit it from
an external scheduler:

```bash
curl -X POST https://<your-api>.onrender.com/api/internal/scan-inactive/ \
  -H "X-Scan-Token: $SCAN_TOKEN"
```

### Frontend → Vercel
1. Vercel → **New Project** → select the repo, set **Root Directory** to
   `frontend`.
2. Framework preset: **Next.js** (auto-detected). No build overrides needed.
3. Environment variables: `NEXT_PUBLIC_API_URL=https://<your-api>.onrender.com` and optional `API_URL_INTERNAL` with the same backend URL.
4. Deploy, then add that Vercel URL to the backend's `CORS_ORIGINS` and redeploy
   the backend.

> Free Render Postgres expires after 30 days. For a longer-lived demo, point
> `POSTGRES_*` at any external Postgres, or leave the vars unset to fall back to
> sqlite (which resets on each deploy — fine for a 2-day assignment).

---

## Assignment tasks

| Task | How |
|---|---|
| **A** — one trigger, all 3 channels | Admin → Notifications → pick *Login* → **Create template** in each channel column → **Test send** |
| **B** — a second trigger | Repeat for *Logout* or *Not logged in 1 week*, with different copy |
| **C** — edit + toggle | Open a template, change the text, test again; flip a channel toggle off then on |
| **D** — explain | See below |

In Task A the WhatsApp column also has a **Meta approval** section. Set the
provider template name/language when using a Meta template, save it, then press
**Sync** until Meta reports `Approved`. Free-form sandbox text can still be tested
with the provider template name left blank when allowed by the test setup.

**Task D, in plain words**

1. *A trigger is anything on the site that should send a message.* Examples
   other than login: signing out, not visiting for a day, not visiting for a
   week, asking for a password reset, finishing a purchase.
2. *The three channels are WhatsApp, email and Web Push.* WhatsApp and email
   reach the user outside the browser; Web Push is a pop-up in the browser
   itself. A trigger can use one, two or all three.
3. *Templates are written in the admin panel because the admin should not have
   to leave it.* The wording, the placeholders and the on/off switch for every
   trigger/channel pair are managed in one table, and the backend talks to
   Meta/Brevo/OneSignal for you. Opening three provider dashboards to
   change one line of copy is slow and easy to get out of sync.
4. *Web Push is a browser notification.* The browser gives the site an
   subscription id; the backend sends through OneSignal. It needs permission
   once per browser, and the browser subscription is stored against the user.

### Walkthrough video (required)
Record with Loom, Google Drive or an unlisted YouTube video. Cover, in order:
1. Open the Vercel frontend and Render `/api/health/` endpoint.
2. Sign in as admin and open the one-table Notification Settings screen.
3. Show Login and Logout templates for WhatsApp, Email and Web Push.
4. Test-send Email and show the Brevo-delivered inbox message.
5. Test-send Web Push and show the OneSignal browser notification.
6. Sign in/out as the subscribed test user and show automatic delivery logs.
7. Toggle Web Push off, trigger Login once, show it is skipped, then turn it back on.
8. Run/show inactivity scan evidence and the Activity log.
9. When Meta approves the two WhatsApp templates, press Sync, test-send each,
   then repeat Login/Logout and show WhatsApp + Email + Web Push all attempted.
10. Finish with GitHub, Render and Vercel URLs.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Backend unreachable` in the UI | Django not running, or `NEXT_PUBLIC_API_URL` is wrong |
| Login succeeds but the table is empty | `python manage.py seed_triggers --with-templates` |
| `403` on admin pages | the account is not staff — `manage.py create_demo_users --admin` |
| WhatsApp send fails | token expired, or the recipient is not an approved test recipient |
| Email send fails | sender not verified, or the free tier is exhausted |
| No browser notification | check `ONESIGNAL_APP_ID` + `ONESIGNAL_REST_API_KEY`, OneSignal Site URL, the service worker, and browser permission |
| Everything says `simulated` | `NOTIFICATION_SANDBOX` is still `True` — that is the default |
| Channel always `skipped` | read the `error` on the Activity page; usually a missing phone number or no subscription |
| `No module named 'fcntl'` | `gunicorn` is Linux-only. Use `manage.py runserver` locally; gunicorn only runs on Render. |
| Render container will not boot | `render.yaml` uses `rootDir: backend`, so the start command must **not** pass `--chdir backend` |

---

## Notes / limitations

- Sends are **synchronous** (no Celery/Redis) so the free Render tier is enough.
  `notifications/tasks.py` is a thin wrapper — each job is a plain function and
  can be handed to a task queue later without changing the callers.
- Meta requires approved message templates for anything outside the 24-hour
  customer-service window. The editor exposes `provider_template_name` and
  `provider_language` for that; the sandbox sends free-form text.
- Push subscriptions that a push service rejects with 404/410 are deactivated
  automatically after three failures.
- **Web Push is scoped per user.** A real send only ever reaches the
  recipient's own browsers. Borrowing any available device is allowed for admin
  *test* sends only, so a push can be verified before the browser has been
  associated with your account.
- `DEFAULT_REPLY_TO` is sent as a real `Reply-To` header (Postmark, Brevo and
  Resend). It is never appended to the `From` address, which would make that
  address malformed and get the message rejected.
- There is **no rate limiting on `/api/auth/login/`**. Fine for a two-day
  assignment; add throttling (or `django-axes`) before exposing this publicly.
