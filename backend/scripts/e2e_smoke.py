"""End-to-end smoke test against a running Django server.

Exercises the full journey the assignment describes:
  login -> create templates -> toggle -> test send -> fire trigger -> logs
Run with:  python scripts/e2e_smoke.py [base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
TOKEN: str | None = None
AMIT: int = 0

passed = 0
failed = 0


def call(method: str, path: str, body=None, auth=True, expect=200):
    global passed, failed
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if auth and TOKEN:
        headers["Authorization"] = f"Token {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            payload = json.loads(raw) if raw else None
            code = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = raw
        code = exc.code

    wanted = expect if isinstance(expect, tuple) else (expect,)
    ok = code in wanted
    label = f"{method:6} {path:46} -> {code} (want {'/'.join(str(w) for w in wanted)})"
    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {payload}")
    return payload


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def purge_smoke_triggers() -> None:
    """Delete anything a previous run of this script left behind."""
    rows = call("GET", "/api/triggers/") or []
    for row in rows:
        if row["key"].startswith("smoke-"):
            call("DELETE", f"/api/triggers/{row['key']}/", expect=204)


def user_id(username: str) -> int:
    """Look a user up by name.

    Hardcoding an id would break the moment the database is re-seeded or is a
    different instance (e.g. a deployed one), so resolve it every run.
    """
    rows = call("GET", f"/api/users/?search={username}") or []
    for row in rows:
        if row["username"] == username:
            return row["id"]
    raise AssertionError(f"User '{username}' not found. Run: manage.py create_demo_users --admin")


def main() -> int:
    global TOKEN

    section("public")
    call("GET", "/api/health/", auth=False)
    config = call("GET", "/api/config/", auth=False)
    assert config and len(config["variables"]) > 5, "variable catalogue missing"

    section("auth")
    login = call("POST", "/api/auth/login/",
                 {"identifier": "admin", "password": "admin12345"}, auth=False)
    TOKEN = login["token"]
    call("GET", "/api/auth/me/")
    purge_smoke_triggers()

    # Resolved by name so the script works against any database.
    global AMIT
    AMIT = user_id("amit")
    print(f"        using user 'amit' (id={AMIT})")
    call("GET", "/api/auth/me/")

    section("triggers + templates")
    triggers = call("GET", "/api/triggers/")
    keys = {t["key"] for t in triggers}
    assert "login" in keys, f"login trigger missing from {keys}"
    login_trigger = next(t for t in triggers if t["key"] == "login")
    print(f"        seeded triggers: {sorted(keys)}")

    # Create the WhatsApp template for the login trigger (may already exist).
    wa = call("GET", "/api/templates/?trigger=login&channel=whatsapp")
    if isinstance(wa, list) and wa:
        template_id = wa[0]["id"]
        print(f"        reusing whatsapp template #{template_id}")
    else:
        created = call("POST", "/api/templates/", {
            "trigger_key": "login",
            "channel": "whatsapp",
            "body": "Smoke test: welcome back, {{ first_name }}!",
        }, expect=201)
        template_id = created["id"]

    call("PATCH", f"/api/templates/{template_id}/",
         {"body": "Smoke test v2: welcome back, {{ first_name }}!"})
    preview = call("GET", f"/api/templates/{template_id}/preview/?user_id={AMIT}")
    assert "v2" in preview["body"], "preview did not reflect the edit"
    print(f"        preview body: {preview['body']!r}")

    section("toggles")
    call("POST", f"/api/templates/{template_id}/toggle/", {})
    toggled_off = call("GET", f"/api/templates/{template_id}/")
    assert toggled_off["is_enabled"] is False
    call("POST", f"/api/templates/{template_id}/toggle/", {})
    toggled_on = call("GET", f"/api/templates/{template_id}/")
    assert toggled_on["is_enabled"] is True
    print("        toggle off -> on verified")

    call("POST", "/api/triggers/login/toggle/", {"is_active": False})
    call("POST", "/api/triggers/login/toggle/", {"is_active": True})

    section("test send (bypasses toggles)")
    result = call("POST", f"/api/templates/{template_id}/test/", {"user_id": AMIT})
    assert result["status"] in {"simulated", "sent"}, result
    print(f"        whatsapp test send: {result['status']} -> {result['destination']}")

    section("fire triggers")
    for key in ("login", "logout"):
        if key not in keys:
            continue
        report = call("POST", f"/api/triggers/{key}/fire/", {"user_id": AMIT})
        print(f"        {key}: {report['summary']}")

    section("inactivity scan")
    out = call("POST", "/api/triggers/not_logged_in_1_week/fire/", {"user_id": AMIT})
    print(f"        inactivity: {out['summary']}")

    section("draft test (unsaved copy)")
    draft = call("POST", "/api/templates/draft-test/", {
        "trigger_key": "login",
        "channel": "webpush",
        "title": "Draft title",
        "body": "Draft for {{ first_name }}",
    })
    print(f"        draft: {draft['status']}")

    section("push subscription")
    # 201 on first subscribe, 200 afterwards (update_or_create is idempotent).
    call("POST", "/api/push/subscribe/", {
        "endpoint": "https://fcm.googleapis.com/fcm/send/smoke-test-endpoint",
        "p256dh": "k" * 40,
        "auth": "a" * 20,
        "provider": "webpush",
    }, expect=(200, 201))
    subs = call("GET", "/api/push/subscriptions/")
    print(f"        subscriptions: {len(subs)}")
    push = call("POST", "/api/triggers/login/fire/", {"user_id": AMIT})
    wp = [r for r in push["results"] if r["channel"] == "webpush"][0]
    print(f"        webpush after subscribe: {wp['status']}")
    call("POST", "/api/push/unsubscribe/",
         {"endpoint": "https://fcm.googleapis.com/fcm/send/smoke-test-endpoint"})

    section("add a new trigger (admin)")
    created = call("POST", "/api/triggers/", {
        "name": "Smoke Cart Abandoned",
        "kind": "event",
        "description": "User leaves items in the cart.",
    }, expect=201)
    new_key = created["key"]
    print(f"        derived key: {new_key!r}")
    assert new_key == "smoke-cart-abandoned", new_key

    # The new row must show up with three empty template cells.
    rows = call("GET", "/api/triggers/")
    new_row = next(t for t in rows if t["key"] == new_key)
    assert new_row["templates"] == [], new_row["templates"]
    print(f"        templates: {len(new_row['templates'])} (empty, as expected)")

    # Fill its three channels, then fire it.
    for ch, fields in (
        ("whatsapp", {"body": "You left {{ first_name }} items in your cart."}),
        ("email", {"subject": "Your cart is waiting", "body": "Hi {{ first_name }}, come back."}),
        ("webpush", {"title": "Cart waiting", "body": "You left items behind."}),
    ):
        tpl = call("POST", "/api/templates/", {"trigger_key": new_key, "channel": ch, **fields},
                   expect=201)
        print(f"        {ch}: id={tpl['id']} vars={tpl['variables']}")
        if ch == "whatsapp":
            wa_template_id = tpl["id"]

    # Inactivity validation.
    call("POST", "/api/triggers/", {"name": "Smoke Idle 3 days", "kind": "inactivity"},
         expect=400)
    ok = call("POST", "/api/triggers/",
              {"name": "Smoke Idle 3 days", "kind": "inactivity", "config": {"days": 3}},
              expect=201)
    print(f"        inactivity trigger days={ok['days']}")
    assert ok["days"] == 3

    fired = call("POST", f"/api/triggers/{new_key}/fire/", {"user_id": AMIT})
    print(f"        fired new trigger: {fired['summary']}")
    # All three templates exist, so nothing may fail. Web Push can still be
    # skipped if this run unsubscribed the browser earlier in the script.
    by_ch = {r["channel"]: r for r in fired["results"]}
    assert set(by_ch) == {"whatsapp", "email", "webpush"}, by_ch
    assert fired["summary"]["failed"] == 0, fired
    for ch in ("whatsapp", "email"):
        assert by_ch[ch]["status"] == "simulated", by_ch[ch]
    print(
        "        statuses: "
        + ", ".join(f"{c}={by_ch[c]['status']}" for c in ("whatsapp", "email", "webpush"))
    )

    section("whatsapp template approval status")
    before = call("GET", f"/api/templates/{wa_template_id}/")
    assert before["provider_status"] == "not_submitted", before["provider_status"]
    assert before["provider_submitted_at"] is None

    # A status without a template name must be refused.
    call("PATCH", f"/api/templates/{wa_template_id}/",
         {"provider_status": "approved"}, expect=400)

    pending = call("PATCH", f"/api/templates/{wa_template_id}/", {
        "provider_status": "pending",
        "provider_template_name": "cart_abandoned_v1",
        "provider_language": "en_US",
    })
    assert pending["provider_submitted_at"] is not None
    print(f"        pending -> submitted_at set ({pending['provider_status_label']})")

    first_stamp = pending["provider_submitted_at"]
    approved = call("PATCH", f"/api/templates/{wa_template_id}/", {"provider_status": "approved"})
    assert approved["provider_submitted_at"] == first_stamp, "stamp was overwritten"
    print(f"        approved -> stamp preserved")

    rejected = call("PATCH", f"/api/templates/{wa_template_id}/", {
        "provider_status": "rejected",
        "provider_status_note": "Meta: expected UTILITY, got MARKETING",
    })
    print(f"        rejected -> {rejected['provider_status_note']!r}")

    console = config["whatsapp"]["template_console_url"]
    assert "facebook.com" in console
    print(f"        meta console: {console}")

    # Leave the table as we found it. This runs last because deleting a trigger
    # cascades to its templates, which the sections above still needed.
    section("cleanup")
    purge_smoke_triggers()
    left = [t["key"] for t in (call("GET", "/api/triggers/") or []) if t["key"].startswith("smoke-")]
    assert not left, f"leftover rows: {left}"

    section("onesignal push subscription (spec section 4 path)")
    # The browser stores OneSignal subscriptions under a synthetic https key
    # derived from the player id, because the backend keys on `endpoint`.
    os_endpoint = "https://onesignal.app/player/smoke-player-001"
    os_sub = call("POST", "/api/push/subscribe/", {
        "provider": "onesignal",
        "endpoint": os_endpoint,
        "onesignal_subscription_id": "smoke-player-001",
        "p256dh": "",
        "auth": "",
    }, expect=(200, 201))
    assert os_sub["provider"] == "onesignal", os_sub
    assert os_sub["onesignal_subscription_id"] == "smoke-player-001"
    print(f"        provider={os_sub['provider']} player={os_sub['onesignal_subscription_id']}")

    # Re-subscribing must update in place, not duplicate.
    call("POST", "/api/push/subscribe/", {
        "provider": "onesignal",
        "endpoint": os_endpoint,
        "onesignal_subscription_id": "smoke-player-001",
    }, expect=(200, 201))
    subs = call("GET", "/api/push/subscriptions/")
    ones = [s for s in subs if s["provider"] == "onesignal"]
    assert len(ones) == 1, f"expected 1 onesignal sub, got {len(ones)}"
    print(f"        idempotent: {len(ones)} onesignal subscription(s)")

    fired = call("POST", "/api/triggers/login/fire/", {"user_id": AMIT})
    wp = [r for r in fired["results"] if r["channel"] == "webpush"][0]
    print(f"        webpush with a onesignal sub: {wp['status']}")
    call("POST", "/api/push/unsubscribe/", {"endpoint": os_endpoint})
    gone = call("GET", "/api/push/subscriptions/")
    # The list includes deactivated rows on purpose, so check the flag.
    remaining = [s for s in gone if s["provider"] == "onesignal" and s["is_active"]]
    assert not remaining, f"onesignal sub still active: {remaining}"
    print("        unsubscribed (row kept, is_active=false)")

    section("push backend reporting")
    backend = config["push"]["backend"]
    print(f"        backend={backend} onesignal={config['push']['onesignal_configured']} "
          f"vapid={config['push']['vapid_configured']}")
    assert backend in {"onesignal", "vapid", "none"}
    if backend == "none":
        assert not config["push"]["onesignal_configured"]
        assert not config["push"]["vapid_configured"]

    section("logs + stats + validation")
    logs = call("GET", "/api/logs/?limit=20")
    print(f"        {len(logs)} log entries")
    assert any(entry["is_test"] for entry in logs), "no test send was logged"
    call("GET", "/api/stats/")
    call("GET", "/api/variables/scan/")
    call("GET", "/api/users/?search=amit")

    # a template with an unknown variable must be reported, not crash
    call("PATCH", f"/api/templates/{template_id}/", {"body": "Hi {{ bogus_var }}"})

    section("errors")
    call("GET", "/api/triggers/nope-not-real/", expect=404)
    call("POST", "/api/templates/", {"trigger_key": "login", "channel": "email", "body": "x"},
         expect=400)
    call("POST", "/api/auth/logout/", {})

    print(f"\n{'=' * 60}\n  passed: {passed}   failed: {failed}\n{'=' * 60}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
