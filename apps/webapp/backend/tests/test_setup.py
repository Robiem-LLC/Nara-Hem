import json
import os
import re
import smtplib
import ssl
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from narahem.app import HASHER, create_app, digest, email_address
from narahem.models import (
    Account,
    AccountApproval,
    Base,
    Challenge,
    LoginSession,
    NativeRefreshSession,
    Outbox,
    PasswordReset,
    Rate,
    Settings,
)

PASSWORD = "synthetic long test password"
PUBLIC = "https://narahem.example.invalid"
OWNER = "owner@example.invalid"
MAIL = {
    "host": "smtp.example.invalid",
    "port": 587,
    "mode": "starttls",
    "username": "synthetic",
    "password": "smtp-test-secret",
    "sender": OWNER,
}


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.db_url = os.environ.get("NARAHEM_TEST_DATABASE_URL", f"sqlite:///{self.path}/test.db")
        if os.environ.get("NARAHEM_TEST_DATABASE_URL"):
            # Explicit disposable test DB only; never reads DATABASE_URL.
            engine = create_engine(self.db_url)
            Base.metadata.drop_all(engine)
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
            engine.dispose()
        self.messages = []
        self.app = create_app(
            self.db_url,
            self.path,
            PUBLIC,
            mailer=lambda *args: self.messages.append(args),
            mail_worker=False,
        )
        self.client = TestClient(self.app, base_url=PUBLIC)
        self.client.__enter__()
        self.client.headers["Origin"] = PUBLIC
        self.token = (self.path / "bootstrap-token").read_text()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def setup_owner(self):
        return self.client.post(
            "/api/setup",
            json={
                "token": self.token,
                "household": "Test household",
                "email": OWNER,
                "password": PASSWORD,
            },
        )

    def login(self, email=OWNER, password=PASSWORD):
        result = self.client.post("/api/login", json={"email": email, "password": password})
        if result.status_code == 200:
            self.client.headers["X-CSRF-Token"] = result.json()["csrf"]
        return result

    def configure(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.put("/api/mail", json=MAIL).status_code, 200)

    def invitation(self):
        self.configure()
        self.assertEqual(
            self.client.post(
                "/api/invitations", json={"email": "member@example.invalid"}
            ).status_code,
            201,
        )
        return re.search(r"#verify=([^&\s]+)", self.messages[-1][3]).group(1)

    def activate(self, token):
        return self.client.post(
            "/api/enrollment/verify",
            json={"token": token, "username": "member", "password": PASSWORD},
        )

    def test_server_admin_cannot_change_household_username(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        self.assertIsNone(self.client.get("/api/session").json()["username"])
        result = self.client.put("/api/account/username", json={"username": "AdminAlias"})
        self.assertEqual(result.status_code, 403, result.text)
        self.assertIsNone(self.client.get("/api/session").json()["username"])

    def test_docker_setup_token_trusts_admin_before_email_confirmation(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        session = self.client.get("/api/session").json()
        self.assertTrue(session["verified"])
        self.assertFalse(session["email_verified"])
        with Session(self.app.state.engine) as db:
            owner = db.scalar(select(Account).where(Account.email == OWNER))
            self.assertIsNotNone(db.get(AccountApproval, owner.id))

    def test_reset_email_single_use_and_revokes_all_browser_native_sessions(self):
        changed = "a different synthetic long password"
        self.configure()
        other = TestClient(self.app, base_url=PUBLIC)
        other.headers["Origin"] = PUBLIC
        native = other.post(
            "/api/login", json={"email": OWNER, "password": PASSWORD, "native": True}
        )
        self.assertEqual(native.status_code, 200)
        refresh = native.json()["refresh_token"]
        unknown = self.client.post(
            "/api/password/forgot", json={"email": "missing@example.invalid"}
        )
        known = self.client.post("/api/password/forgot", json={"email": OWNER})
        self.assertEqual(unknown.status_code, 202)
        self.assertEqual(unknown.json(), known.json())
        with Session(self.app.state.engine) as db:
            row = db.scalar(select(Outbox).where(Outbox.account_id.like("r:%")))
            self.assertIsNotNone(row)
            message = json.loads(self.app.state.cipher.decrypt(row.payload.encode()))
            self.assertEqual(message["recipient"], OWNER)
            token = re.search(r"#reset=(\S+)", message["body"]).group(1)
            self.assertNotIn(token, row.payload)
        result = self.client.post(
            "/api/password/reset", json={"token": token, "new_password": changed}
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            self.client.post(
                "/api/password/reset", json={"token": token, "new_password": changed}
            ).status_code,
            400,
        )
        self.assertEqual(self.client.get("/api/session").status_code, 401)
        self.assertEqual(
            other.post("/api/native/session/refresh", json={"refresh_token": refresh}).status_code,
            401,
        )
        self.assertEqual(
            other.post("/api/login", json={"email": OWNER, "password": PASSWORD}).status_code, 401
        )
        self.assertEqual(
            other.post("/api/login", json={"email": OWNER, "password": changed}).status_code, 200
        )

    def test_admin_can_send_reset_only_to_existing_active_email_member(self):
        self.configure()
        self.assertEqual(
            self.client.post(
                "/api/invitations", json={"email": "member@example.invalid"}
            ).status_code,
            201,
        )
        token = re.search(r"#verify=([^&\s]+)", self.messages[-1][3]).group(1)
        self.assertEqual(self.activate(token).status_code, 200)
        accounts = self.client.get("/api/accounts").json()
        member_id = next(a["id"] for a in accounts if a["email"] == "member@example.invalid")
        self.assertEqual(
            self.client.post(f"/api/accounts/{member_id}/password-reset", json={}).status_code, 202
        )
        with Session(self.app.state.engine) as db:
            self.assertIsNotNone(
                db.scalar(select(Outbox).where(Outbox.account_id == "r:" + member_id))
            )
        owner_id = next(a["id"] for a in accounts if a["email"] == OWNER)
        self.assertEqual(
            self.client.post(f"/api/accounts/{owner_id}/password-reset", json={}).status_code, 404
        )
        self.assertEqual(
            self.client.post("/api/accounts/absent/password-reset", json={}).status_code, 404
        )

    def test_reset_expiry_and_missing_smtp_do_not_change_password(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertEqual(
            self.client.post("/api/password/forgot", json={"email": OWNER}).status_code, 202
        )
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.query(PasswordReset).count(), 0)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.put("/api/mail", json=MAIL).status_code, 200)
        self.client.post("/api/password/forgot", json={"email": OWNER})
        with Session(self.app.state.engine) as db:
            row = db.scalar(select(PasswordReset))
            self.assertIsNotNone(row)
            row.expires = time.time() - 1
            db.commit()
        self.assertEqual(
            self.client.post(
                "/api/password/reset",
                json={
                    "token": "nonexistent-recovery-proof-is-not-valid-but-long-enough",
                    "new_password": "an acceptable different password",
                },
            ).status_code,
            400,
        )
        self.assertEqual(self.login().status_code, 200)

    def test_admin_can_change_password_without_docker_and_revoke_other_sessions(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        old = TestClient(self.app, base_url=PUBLIC)
        old.headers["Origin"] = PUBLIC
        old_login = old.post(
            "/api/login", json={"email": OWNER, "password": PASSWORD, "native": True}
        )
        self.assertEqual(old_login.status_code, 200)
        refresh = old_login.json()["refresh_token"]
        original = {
            "current_password": PASSWORD,
            "new_password": "new long passphrase for the admin",
        }
        bad = self.client.post(
            "/api/admin/change-password", json={**original, "current_password": "incorrect"}
        )
        self.assertEqual(bad.status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/admin/change-password", json={**original, "new_password": PASSWORD}
            ).status_code,
            422,
        )
        changed = self.client.post("/api/admin/change-password", json=original)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertTrue(changed.json()["other_sessions_signed_out"])
        self.assertEqual(self.client.get("/api/session").status_code, 200)
        self.assertEqual(old.get("/api/session").status_code, 401)
        self.assertEqual(
            old.post("/api/native/session/refresh", json={"refresh_token": refresh}).status_code,
            401,
        )
        self.assertEqual(
            old.post("/api/login", json={"email": OWNER, "password": PASSWORD}).status_code, 401
        )
        self.assertEqual(
            old.post(
                "/api/login", json={"email": OWNER, "password": original["new_password"]}
            ).status_code,
            200,
        )

    def test_bootstrap_locks_and_hashes_password(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertFalse((self.path / "bootstrap-token").exists())
        self.assertEqual(self.setup_owner().status_code, 409)
        with Session(self.app.state.engine) as db:
            account = db.scalar(select(Account))
            self.assertEqual(account.email, OWNER)
            self.assertIsNone(account.username)
            self.assertIsNotNone(db.get(AccountApproval, account.id))
            self.assertNotEqual(account.password, PASSWORD)
            self.assertTrue(HASHER.verify(account.password, PASSWORD))
            self.assertIsNone(db.get(Settings, 1).bootstrap_hash)

    def test_first_generated_setup_key_appears_in_logs_only_once(self):
        import io
        from contextlib import redirect_stdout
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            log = io.StringIO()
            with redirect_stdout(log):
                app = create_app(
                    "sqlite:///" + directory + "/fresh.db", directory, PUBLIC, mail_worker=False
                )
                with TestClient(app, base_url=PUBLIC):
                    token = (Path(directory) / "bootstrap-token").read_text()
                    self.assertIn("NARAHEM FIRST-RUN SETUP TOKEN: " + token, log.getvalue())
                    log.seek(0)
                    log.truncate()
                    app.state.initialize()
                    self.assertNotIn(token, log.getvalue())

    def test_previous_clients_may_send_admin_username_but_it_is_ignored(self):
        body = {
            "token": self.token,
            "household": "Household",
            "email": OWNER,
            "username": "unused-admin-alias",
            "password": PASSWORD,
        }
        self.assertEqual(self.client.post("/api/setup", json=body).status_code, 201)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.scalar(select(Account)).username)
        self.assertEqual(self.login().status_code, 200)

    def test_configured_token_replaces_unclaimed_token_and_cannot_reopen_setup(self):
        with patch.dict(os.environ, {"NARAHEM_SETUP_TOKEN": "family-test"}):
            self.app.state.initialize()
            self.assertEqual((self.path / "bootstrap-token").read_text(), "family-test")
            self.assertEqual((self.path / "bootstrap-token").stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.setup_owner().status_code, 403)
            self.token = "family-test"
            self.assertEqual(self.setup_owner().status_code, 201)
            self.app.state.initialize()
            self.assertFalse((self.path / "bootstrap-token").exists())
            self.assertEqual(self.setup_owner().status_code, 409)

    def test_configured_token_on_fresh_install(self):
        with tempfile.TemporaryDirectory() as directory:
            database_url = "sqlite:///" + directory + "/fresh.db"
            with patch.dict(os.environ, {"NARAHEM_SETUP_TOKEN": "fresh-test-token"}):
                app = create_app(database_url, directory, PUBLIC, mail_worker=False)
                with TestClient(app, base_url=PUBLIC) as client:
                    result = client.post(
                        "/api/setup",
                        headers={"Origin": PUBLIC},
                        json={
                            "token": "fresh-test-token",
                            "household": "Fresh",
                            "email": OWNER,
                            "username": "owner",
                            "password": PASSWORD,
                        },
                    )
                    self.assertEqual(result.status_code, 201)

    def test_invalid_configured_token_does_not_replace_existing_token(self):
        with patch.dict(os.environ, {"NARAHEM_SETUP_TOKEN": "short"}):
            with self.assertRaises(ValueError):
                self.app.state.initialize()
        self.assertEqual((self.path / "bootstrap-token").read_text(), self.token)
        self.assertEqual(self.setup_owner().status_code, 201)

    def test_wrong_token_origin_host_and_weak_password(self):
        self.token = "wrong" * 8
        self.assertEqual(self.setup_owner().status_code, 403)
        self.client.headers["Origin"] = "https://attacker.invalid"
        self.assertEqual(self.setup_owner().status_code, 403)
        self.assertEqual(
            self.client.get("/api/setup", headers={"host": "attacker.invalid"}).status_code, 400
        )
        self.client.headers["Origin"] = PUBLIC
        result = self.client.post(
            "/api/setup",
            json={
                "token": self.token,
                "household": "test",
                "email": OWNER,
                "username": "test",
                "password": "short-secret",
            },
        )
        self.assertEqual(result.status_code, 422)
        self.assertNotIn("short-secret", result.text)
        self.assertIn(
            {"field": "password", "message": "Use at least 15 characters."}, result.json()["fields"]
        )

    def test_persistence_and_key_loss_fail_closed(self):
        self.configure()
        self.app.state.initialize()
        again = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with TestClient(again, base_url=PUBLIC) as client:
            self.assertTrue(client.get("/healthz").json()["configured"])
        (self.path / "server.key").unlink()
        with self.assertRaisesRegex(RuntimeError, "key is missing"):
            create_app(self.db_url, self.path, PUBLIC, mail_worker=False)

    def test_http_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError):
            create_app(self.db_url, self.path, "http://localhost:8080", allow_http=False)

    def test_schema_from_a_newer_server_is_refused(self):
        from alembic.util import CommandError

        with self.app.state.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE alembic_version SET version_num='9999'")
        with self.assertRaisesRegex(CommandError, "9999"):
            self.app.state.initialize()

    def test_admin_household_summary_storage_cleanup_and_audit(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        self.assertEqual(self.login().status_code, 200)
        household = self.client.get("/api/household")
        self.assertEqual(household.status_code, 200, household.text)
        self.assertLessEqual(
            {"id", "protocol", "transport", "revision", "retention_days"}, set(household.json())
        )
        # The web app's "Clean expired data now" button sends an empty JSON body.
        cleanup = self.client.post("/api/storage/cleanup", json={})
        self.assertEqual(cleanup.status_code, 200, cleanup.text)
        audit = self.client.get("/api/audit")
        self.assertEqual(audit.status_code, 200, audit.text)
        self.assertIsInstance(audit.json(), list)

    def test_map_images_are_served_only_from_the_fixed_list(self):
        for name in ("marker-icon.png", "marker-icon-2x.png", "marker-shadow.png", "layers.png"):
            image = self.client.get(f"/images/{name}")
            self.assertEqual(image.status_code, 200, name)
            self.assertEqual(image.headers["content-type"], "image/png")
        for name in ("other.png", "..%2Fserver.key", "%2E%2E%2Fbootstrap-token"):
            self.assertEqual(self.client.get(f"/images/{name}").status_code, 404, name)

    def test_login_cookie_session_csrf_expiry_and_logout(self):
        self.setup_owner()
        response = self.login()
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=strict"):
            self.assertIn(flag, cookie)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(LoginSession, self.client.cookies.get("narahem_session")))
        self.assertEqual(self.client.get("/api/admin").status_code, 200)
        csrf = self.client.headers.pop("X-CSRF-Token")
        self.assertEqual(self.client.post("/api/logout", json={}).status_code, 403)
        self.client.headers["X-CSRF-Token"] = csrf
        self.assertEqual(self.client.post("/api/logout", json={}).status_code, 200)
        self.assertEqual(self.client.get("/api/session").status_code, 401)
        self.login()
        with Session(self.app.state.engine) as db:
            db.scalar(select(LoginSession)).expires = time.time() - 1
            db.commit()
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_native_remembered_login_rotates_and_revokes_without_browser_cookie(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        login = self.client.post(
            "/api/login", json={"email": OWNER, "password": PASSWORD, "native": True}
        )
        self.assertEqual(login.status_code, 200, login.text)
        access = login.json()["access_token"]
        refresh = login.json()["refresh_token"]
        self.assertNotEqual(access, refresh)
        self.assertEqual(
            self.client.get(
                "/api/session", headers={"Authorization": f"Bearer {access}"}
            ).status_code,
            200,
        )
        native = TestClient(self.app, base_url=PUBLIC)
        native.headers["X-NaraHem-Client"] = "native"
        self.assertEqual(
            native.post(
                "/api/native/session/refresh",
                headers={"Origin": "https://attacker.invalid"},
                json={"refresh_token": refresh},
            ).status_code,
            403,
        )
        renewed = native.post("/api/native/session/refresh", json={"refresh_token": refresh})
        self.assertEqual(renewed.status_code, 200, renewed.text)
        next_access, next_refresh = renewed.json()["access_token"], renewed.json()["refresh_token"]
        self.assertNotEqual(access, next_access)
        self.assertNotEqual(refresh, next_refresh)
        self.assertEqual(
            native.post("/api/native/session/refresh", json={"refresh_token": refresh}).status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                "/api/session", headers={"Authorization": f"Bearer {next_access}"}
            ).status_code,
            200,
        )
        with Session(self.app.state.engine) as db:
            db.get(LoginSession, digest(next_access)).expires = time.time() - 1
            db.commit()
        self.assertEqual(
            self.client.get(
                "/api/session", headers={"Authorization": f"Bearer {next_access}"}
            ).status_code,
            401,
        )
        # App can refresh even when the short-lived access token has expired.
        again = native.post("/api/native/session/refresh", json={"refresh_token": next_refresh})
        self.assertEqual(again.status_code, 200)
        last_refresh = again.json()["refresh_token"]
        self.assertEqual(
            native.post(
                "/api/native/session/revoke", json={"refresh_token": last_refresh}
            ).status_code,
            200,
        )
        self.assertEqual(
            native.post(
                "/api/native/session/refresh", json={"refresh_token": last_refresh}
            ).status_code,
            401,
        )
        ordinary = self.login()
        self.assertNotIn("refresh_token", ordinary.json())
        self.assertNotIn("access_token", ordinary.json())

    def test_native_refresh_reuse_after_grace_revokes_remembered_sign_in(self):
        self.assertEqual(self.setup_owner().status_code, 201)
        native = TestClient(self.app, base_url=PUBLIC)
        native.headers["X-NaraHem-Client"] = "native"
        stolen = native.post(
            "/api/login", json={"email": OWNER, "password": PASSWORD, "native": True}
        ).json()["refresh_token"]
        current = native.post("/api/native/session/refresh", json={"refresh_token": stolen}).json()[
            "refresh_token"
        ]
        # A quick retry of the old token (lost response) only fails; the phone keeps its new grant.
        self.assertEqual(
            native.post("/api/native/session/refresh", json={"refresh_token": stolen}).status_code,
            401,
        )
        current = native.post(
            "/api/native/session/refresh", json={"refresh_token": current}
        ).json()["refresh_token"]
        later = time.time() + 600
        with patch("narahem.app.time.time", return_value=later):
            self.assertEqual(
                native.post(
                    "/api/native/session/refresh", json={"refresh_token": stolen}
                ).status_code,
                401,
            )
            self.assertEqual(
                native.post(
                    "/api/native/session/refresh", json={"refresh_token": current}
                ).status_code,
                401,
            )
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.query(NativeRefreshSession).count(), 0)
            from narahem.models import AuditEntry

            self.assertTrue(
                db.scalar(select(AuditEntry).where(AuditEntry.action == "session.refresh_reuse"))
            )
        # Password sign-in still works afterwards.
        self.assertEqual(
            native.post(
                "/api/login", json={"email": OWNER, "password": PASSWORD, "native": True}
            ).status_code,
            200,
        )

    def test_brute_force_throttled_without_enumeration(self):
        self.setup_owner()
        frozen = patch(
            "narahem.app.time.time", return_value=time.time()
        )  # keep backoff windows deterministic
        frozen.start()
        self.addCleanup(frozen.stop)
        known = self.login(password="incorrect").json()
        unknown = self.login(email="unknown@example.invalid").json()
        self.assertEqual(known, unknown)
        for _ in range(2):
            self.assertEqual(self.login(password="incorrect").status_code, 401)
        # Backoff starts after three failures and answers identically for unknown accounts.
        blocked = self.login(password="incorrect")
        self.assertEqual(blocked.status_code, 429)
        self.assertGreaterEqual(int(blocked.headers["Retry-After"]), 1)
        for _ in range(3):
            self.login(email="unknown@example.invalid")
        self.assertEqual(self.login(email="unknown@example.invalid").json(), blocked.json())

    def test_successful_logins_never_use_up_the_allowance(self):
        self.setup_owner()
        for _ in range(15):
            self.assertEqual(self.login().status_code, 200)

    def test_login_backoff_grows_then_clears_on_success(self):
        self.setup_owner()
        now = time.time()
        with patch("narahem.app.time.time", return_value=now):
            for _ in range(3):
                self.assertEqual(self.login(password="incorrect").status_code, 401)
            self.assertEqual(self.login().status_code, 429)  # even the right password waits
        with patch("narahem.app.time.time", return_value=now + 2):
            self.assertEqual(self.login(password="incorrect").status_code, 401)
        with patch("narahem.app.time.time", return_value=now + 3):
            self.assertEqual(self.login().status_code, 429)  # second wait is 2 s
        with patch("narahem.app.time.time", return_value=now + 5):
            self.assertEqual(self.login().status_code, 200)
            self.assertEqual(self.login(password="incorrect").status_code, 401)  # count was reset

    def test_guessing_one_account_never_delays_another(self):
        self.setup_owner()
        with Session(self.app.state.engine) as db:
            db.add(
                Account(
                    id="b" * 32,
                    email="member@example.invalid",
                    password=HASHER.hash(PASSWORD),
                    status="active",
                    role="member",
                    verified=True,
                )
            )
            db.commit()
        frozen = patch("narahem.app.time.time", return_value=time.time())
        frozen.start()
        self.addCleanup(frozen.stop)
        # Behind a proxy every request shares one address: limits must not be per IP.
        # Spraying 25 different accounts from one address used to trip a shared ceiling.
        for n in range(25):
            self.client.post(
                "/api/login",
                json={"email": f"stranger{n}@example.invalid", "password": "incorrect"},
            )
        for _ in range(5):
            self.client.post(
                "/api/login", json={"email": "member@example.invalid", "password": "incorrect"}
            )
        self.assertEqual(
            self.client.post(
                "/api/login", json={"email": "member@example.invalid", "password": PASSWORD}
            ).status_code,
            429,
        )
        self.assertEqual(self.login().status_code, 200)

    def test_refresh_is_not_blocked_by_junk_requests_from_the_same_address(self):
        self.setup_owner()
        native = TestClient(self.app, base_url=PUBLIC)
        native.headers["X-NaraHem-Client"] = "native"
        refresh = native.post(
            "/api/login", json={"email": OWNER, "password": PASSWORD, "native": True}
        ).json()["refresh_token"]
        for _ in range(60):
            native.post("/api/native/session/refresh", json={"refresh_token": "x" * 43})
        self.assertEqual(
            native.post("/api/native/session/refresh", json={"refresh_token": refresh}).status_code,
            200,
        )

    def test_anonymous_cannot_manage_accounts_mail_or_devices(self):
        self.setup_owner()
        for path in ("/api/admin", "/api/accounts", "/api/mail", "/api/devices"):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_smtp_secret_encrypted_and_never_returned(self):
        self.configure()
        result = self.client.get("/api/mail")
        self.assertNotIn("password", result.json())
        with Session(self.app.state.engine) as db:
            stored = db.get(Settings, 1).smtp
            self.assertNotIn(MAIL["password"], stored)
            self.assertEqual(
                json.loads(self.app.state.cipher.decrypt(stored.encode()))["password"],
                MAIL["password"],
            )
        changed = {**MAIL, "password": None}
        self.client.put("/api/mail", json=changed)
        self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        self.assertEqual(self.messages[-1][0]["password"], MAIL["password"])

    def test_changed_smtp_settings_reset_mail_cooldown(self):
        self.configure()
        changes = {
            "host": "corrected.example.invalid",
            "port": 465,
            "mode": "tls",
            "username": "corrected-user",
            "password": "corrected-secret",
            "sender": "corrected@example.invalid",
        }
        config = dict(MAIL)
        self.assertEqual(self.client.post("/api/mail/retry", json={}).status_code, 200)
        with Session(self.app.state.engine) as db:
            db.add(Rate(id=digest("other-client:mail"), started=time.time(), count=10))
            db.commit()
        # One failed sign-in leaves login throttling state that must survive SMTP changes.
        self.assertEqual(
            self.client.post(
                "/api/login", json={"email": OWNER, "password": "incorrect"}
            ).status_code,
            401,
        )
        for field, value in changes.items():
            with self.subTest(field=field):
                for _ in range(9):
                    self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
                self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 429)
                self.assertEqual(self.client.post("/api/mail/retry", json={}).status_code, 429)
                config[field] = value
                self.assertEqual(self.client.put("/api/mail", json=config).status_code, 200)
                # Changing SMTP settings must not clear login or other clients' limits.
                with Session(self.app.state.engine) as db:
                    self.assertEqual(db.get(Rate, digest("login-account:" + OWNER)).count, 1)
                    self.assertEqual(db.get(Rate, digest("other-client:mail")).count, 10)
                self.assertEqual(self.client.post("/api/mail/retry", json={}).status_code, 200)

    def test_unchanged_or_invalid_smtp_settings_keep_mail_cooldown(self):
        self.configure()
        for _ in range(10):
            self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 200)
        for config, status in (
            (MAIL, 200),
            ({**MAIL, "password": None}, 200),
            ({**MAIL, "mode": "plain"}, 422),
            ({**MAIL, "host": "bad host"}, 422),
        ):
            with self.subTest(config=config):
                self.assertEqual(self.client.put("/api/mail", json=config).status_code, status)
                self.assertEqual(self.client.post("/api/mail/test", json={}).status_code, 429)
        with Session(self.app.state.engine) as db:
            self.assertTrue(db.get(Settings, 1).mail_tested)

    def test_smtp_must_use_tls_and_header_injection_rejected(self):
        self.configure()
        self.assertEqual(
            self.client.put("/api/mail", json={**MAIL, "mode": "plain"}).status_code, 422
        )
        self.assertEqual(
            self.client.put(
                "/api/mail",
                json={**MAIL, "sender": "a@example.invalid\r\nBcc:evil@example.invalid"},
            ).status_code,
            422,
        )

    def test_smtp_verifies_certificates_and_authenticates_after_starttls(self):
        self.configure()
        real = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with TestClient(real, base_url=PUBLIC) as client:
            client.headers.update(dict(self.client.headers))
            client.cookies.update(self.client.cookies)
            for mode in ("starttls", "tls"):
                client.put("/api/mail", json={**MAIL, "mode": mode})
                with (
                    patch("narahem.app.smtplib.SMTP") as plain,
                    patch("narahem.app.smtplib.SMTP_SSL") as secure,
                ):
                    self.assertEqual(client.post("/api/mail/test", json={}).status_code, 200)
                    factory = plain if mode == "starttls" else secure
                    connection = factory.return_value
                    context = (
                        connection.starttls.call_args.kwargs["context"]
                        if mode == "starttls"
                        else factory.call_args.kwargs["context"]
                    )
                    self.assertTrue(context.check_hostname)
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    connection.login.assert_called_once_with(MAIL["username"], MAIL["password"])
                    connection.send_message.assert_called_once()
                    if mode == "starttls":
                        calls = [call[0] for call in connection.method_calls]
                        self.assertLess(calls.index("starttls"), calls.index("login"))
                        secure.assert_not_called()
                    else:
                        plain.assert_not_called()

    def test_wrong_server_key_refuses_startup(self):
        self.configure()
        from cryptography.fernet import Fernet

        (self.path / "server.key").write_bytes(Fernet.generate_key())
        wrong = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with self.assertRaisesRegex(RuntimeError, "key does not match"):
            wrong.state.initialize()
        wrong.state.engine.dispose()

    def test_phone_invitations_need_text_messages(self):
        self.configure()
        invited = self.client.post("/api/invitations", json={"email": "(415) 555-0123"})
        self.assertEqual(invited.status_code, 409, invited.text)
        self.assertIn("Set up text messages", invited.json()["detail"])
        also = self.client.post(
            "/api/invitations", json={"email": "kim@example.invalid", "phone": "4155550123"}
        )
        self.assertEqual(also.status_code, 409, also.text)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.scalar(select(Account).where(Account.phone == "+14155550123")))
        for invalid in ("123", "+000001123", "bad@", "+1-abc"):
            self.assertEqual(
                self.client.post("/api/invitations", json={"email": invalid}).status_code, 422
            )
        self.client.post("/api/logout", json={})
        refused = self.client.post(
            "/api/login", json={"email": "+14155550123", "password": "synthetic long test password"}
        )
        self.assertEqual(refused.status_code, 401)

    def test_invite_verify_single_use_and_member_cannot_admin(self):
        token = self.invitation()
        result = self.activate(token)
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()["device_approval_required"])
        self.assertEqual(self.activate(token).status_code, 400)
        self.client.post("/api/logout", json={})
        self.assertEqual(self.login(email="member@example.invalid").status_code, 200)
        self.assertEqual(self.client.get("/api/admin").status_code, 403)
        self.assertEqual(self.client.put("/api/mail", json=MAIL).status_code, 403)

    def test_native_invitation_request_notifies_owner_without_granting_access(self):
        self.configure()
        with Session(self.app.state.engine) as db:
            db.scalar(select(Account).where(Account.email == OWNER)).verified = True
            db.commit()
        self.client.cookies.clear()
        self.client.headers.pop("Origin", None)
        self.client.headers["X-NaraHem-Client"] = "native"
        body = {
            "email": "new@example.invalid",
            "name": "Synthetic person",
            "relationship": "School friend",
        }
        response = self.client.post("/api/invitation-requests", json=body)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.client.post("/api/invitation-requests", json=body).status_code, 202)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.scalar(select(Account).where(Account.email == body["email"])))
            queued = list(db.scalars(select(Outbox).where(Outbox.status == "pending")))
            self.assertEqual(len(queued), 1)
            self.assertNotIn(body["email"], queued[0].payload)
            payload = json.loads(self.app.state.cipher.decrypt(queued[0].payload.encode()))
            self.assertEqual(payload["recipient"], OWNER)
            for value in (body["email"], body["name"], body["relationship"]):
                self.assertIn(value, payload["body"])
            self.assertIn("not independently verified", payload["body"])
        self.client.headers["Origin"] = PUBLIC
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.post("/api/mail/retry", json={}).status_code, 200)
        self.assertEqual(self.messages[-1][1], OWNER)

    def test_invitation_requests_require_ready_server_and_limit_spam(self):
        self.configure()
        body = {
            "email": "new@example.invalid",
            "name": "Synthetic person",
            "relationship": "School friend",
        }
        self.assertEqual(self.client.post("/api/invitation-requests", json=body).status_code, 503)
        with Session(self.app.state.engine) as db:
            db.scalar(select(Account).where(Account.email == OWNER)).verified = True
            db.commit()
        self.assertEqual(self.client.post("/api/invitation-requests", json=body).status_code, 202)
        self.assertEqual(self.client.post("/api/invitation-requests", json=body).status_code, 202)
        self.assertEqual(self.client.post("/api/invitation-requests", json=body).status_code, 429)
        with Session(self.app.state.engine) as db:
            limit = db.get(Rate, digest("all-clients:invitation-request-global"))
            limit.count = 20
            db.get(Rate, digest("testclient:invitation-request")).count = 0
            db.commit()
        self.assertEqual(self.client.post("/api/invitation-requests", json=body).status_code, 429)

    def test_invitation_request_keeps_confirmation_and_rejects_invalid_input(self):
        self.configure()
        with Session(self.app.state.engine) as db:
            db.scalar(select(Account).where(Account.email == OWNER)).verified = True
            db.commit()
        self.client.post("/api/invitations", json={"email": "member@example.invalid"})
        self.client.post("/api/enrollment/request", json={"email": "member@example.invalid"})
        self.assertEqual(
            self.client.post(
                "/api/invitation-requests",
                json={"email": "new@example.invalid", "name": " ", "relationship": "friend"},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/api/invitation-requests",
                json={
                    "email": "bad\r\nBcc: victim@example.invalid",
                    "name": "Person",
                    "relationship": "friend",
                },
            ).status_code,
            422,
        )
        with Session(self.app.state.engine) as db:
            self.assertEqual(
                len(list(db.scalars(select(Outbox).where(Outbox.status == "pending")))), 1
            )

    def test_uninvited_resend_generic_and_no_account_creation(self):
        self.configure()
        self.client.post("/api/invitations", json={"email": "member@example.invalid"})
        known = self.client.post(
            "/api/enrollment/request", json={"email": "member@example.invalid"}
        )
        unknown = self.client.post(
            "/api/enrollment/request", json={"email": "unknown@example.invalid"}
        )
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(unknown.status_code, 202)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(
                db.scalar(select(Account).where(Account.email == "unknown@example.invalid"))
            )

    def test_delete_pending_and_revoked_accounts_frees_invitation_email(self):
        for revoked in (False, True):
            with self.subTest(revoked=revoked):
                if not revoked:
                    self.configure()
                self.assertEqual(
                    self.client.post(
                        "/api/invitations", json={"email": "reusable@example.invalid"}
                    ).status_code,
                    201,
                )
                with Session(self.app.state.engine) as db:
                    ident = db.scalar(
                        select(Account).where(Account.email == "reusable@example.invalid")
                    ).id
                if revoked:
                    self.assertEqual(
                        self.client.post(f"/api/accounts/{ident}/revoke", json={}).status_code, 200
                    )
                self.assertEqual(
                    self.client.request("DELETE", f"/api/accounts/{ident}", json={}).status_code,
                    200,
                )
                with Session(self.app.state.engine) as db:
                    self.assertIsNone(db.get(Account, ident))
                    self.assertEqual(db.query(Challenge).filter_by(account_id=ident).count(), 0)
                    self.assertEqual(db.query(Outbox).filter_by(account_id=ident).count(), 0)

    def test_resend_invalidates_old_token_and_expiry_rejected(self):
        token = self.invitation()
        self.client.post("/api/enrollment/request", json={"email": "member@example.invalid"})
        self.assertEqual(self.activate(token).status_code, 400)
        self.client.post("/api/mail/retry", json={})
        fresh = re.search(r"#verify=([^&\s]+)", self.messages[-1][3]).group(1)
        with Session(self.app.state.engine) as db:
            db.get(Challenge, digest(fresh)).expires = time.time() - 1
            db.commit()
        self.assertEqual(self.activate(fresh).status_code, 400)

    def test_owner_confirmation_does_not_reset_password(self):
        self.configure()
        self.client.post("/api/enrollment/request", json={"email": OWNER})
        self.client.post("/api/mail/retry", json={})
        token = re.search(r"#verify=([^&\s]+)", self.messages[-1][3]).group(1)
        self.client.post(
            "/api/enrollment/verify",
            json={"token": token, "password": "a different long password", "username": "hijack"},
        )
        with Session(self.app.state.engine) as db:
            owner = db.scalar(select(Account).where(Account.email == OWNER))
            self.assertTrue(owner.verified)
            self.assertIsNone(owner.username)
            self.assertTrue(HASHER.verify(owner.password, PASSWORD))

    def test_revocation_kills_sessions_and_pending_devices(self):
        token = self.invitation()
        self.activate(token)
        with Session(self.app.state.engine) as db:
            member = db.scalar(select(Account).where(Account.email == "member@example.invalid"))
            member_id = member.id
            db.add(
                LoginSession(
                    id=digest("synthetic-token"),
                    account_id=member_id,
                    csrf="synthetic",
                    expires=time.time() + 100,
                )
            )
            db.commit()
        self.assertEqual(
            self.client.post(f"/api/accounts/{member_id}/revoke", json={}).status_code, 200
        )
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(LoginSession, digest("synthetic-token")))
        self.assertEqual(self.login(email="member@example.invalid").status_code, 401)

    def test_admin_restore_revoked_member_keeps_old_phone_revoked(self):
        token = self.invitation()
        self.assertEqual(self.activate(token).status_code, 200)
        with Session(self.app.state.engine) as db:
            member = db.scalar(select(Account).where(Account.email == "member@example.invalid"))
            member_id = member.id
            original_hash = member.password
            db.commit()
        restore_url = f"/api/accounts/{member_id}/restore"
        self.assertEqual(self.client.post(restore_url, json={}).status_code, 409)
        self.assertEqual(
            self.client.post(f"/api/accounts/{member_id}/revoke", json={}).status_code, 200
        )
        self.assertEqual(self.login(email="member@example.invalid").status_code, 401)
        anonymous = TestClient(self.app, base_url=PUBLIC)
        anonymous.headers["Origin"] = PUBLIC
        self.assertEqual(anonymous.post(restore_url, json={}).status_code, 401)
        result = self.client.post(restore_url, json={})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {"restored": True, "phones_remain_revoked": True})
        self.assertEqual(self.client.post(restore_url, json={}).status_code, 409)
        with Session(self.app.state.engine) as db:
            member = db.get(Account, member_id)
            self.assertEqual(member.status, "active")
            self.assertEqual(member.password, original_hash)
        self.assertEqual(self.login(email="member@example.invalid").status_code, 200)
        # Restoring the account is not authorization to reuse an old phone.
        self.assertEqual(self.client.get("/api/admin").status_code, 403)

    def test_mail_failure_is_retryable_and_secret_not_leaked(self):
        self.configure()

        def fail(*args):
            raise smtplib.SMTPException("smtp-test-secret")

        failed = create_app(self.db_url, self.path, PUBLIC, mailer=fail, mail_worker=False)
        with TestClient(failed, base_url=PUBLIC) as client:
            client.headers.update(dict(self.client.headers))
            client.cookies.update(self.client.cookies)
            response = client.post("/api/invitations", json={"email": "member@example.invalid"})
            self.assertEqual(response.json()["delivery"], "pending")
            self.assertNotIn("smtp-test-secret", response.text)
        self.assertEqual(self.client.post("/api/mail/retry", json={}).json()["sent"], 1)
        with Session(self.app.state.engine) as db:
            item = db.scalar(select(Outbox))
            self.assertEqual(item.payload, "")
            self.assertEqual(item.status, "sent")

    def test_failed_test_email_says_what_went_wrong(self):
        self.configure()
        cases = [
            (smtplib.SMTPAuthenticationError(535, b"bad"), "rejected the username or password"),
            (ConnectionRefusedError("refused"), "Could not connect to the mail server"),
            (smtplib.SMTPRecipientsRefused({}), "refused the test email"),
        ]
        for error, text in cases:
            with self.subTest(error=type(error).__name__):

                def fail(*args, error=error):
                    raise error

                failed = create_app(self.db_url, self.path, PUBLIC, mailer=fail, mail_worker=False)
                with TestClient(failed, base_url=PUBLIC) as client:
                    client.headers.update(dict(self.client.headers))
                    client.cookies.update(self.client.cookies)
                    response = client.post("/api/mail/test", json={})
                    self.assertEqual(response.status_code, 502)
                    self.assertIn(text, response.json()["detail"])

    def test_plaintext_location_endpoints_are_not_exposed(self):
        self.setup_owner()
        for path in ("/api/locations", "/locations", "/api/devices/approve"):
            self.assertEqual(
                self.client.post(path, json={"location": "synthetic"}).status_code, 404
            )
        self.login()
        self.assertTrue(self.client.get("/api/devices").json()["pairing_available"])

    def test_setup_ui_and_security_headers(self):
        for path in ("/", "/app.js", "/style.css", "/app-icon.png", "/nara-hem-wordmark.png"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
            self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(self.client.get("/app-icon.png").headers["content-type"], "image/png")
        wordmark = self.client.get("/nara-hem-wordmark.png")
        self.assertEqual(wordmark.headers["content-type"], "image/png")
        self.assertNotIn(self.token, self.client.get("/").text)

    def test_server_version_is_shown_to_signed_in_users_only(self):
        self.assertEqual(self.client.get("/api/version").status_code, 401)
        self.configure()
        build = {
            "NARAHEM_BUILD_CHANNEL": "dev",
            "NARAHEM_BUILD_NUMBER": "591",
            "NARAHEM_BUILD_COMMIT": "c399c6c" + "0" * 33,
            "NARAHEM_BUILD_UTC": "2026-10-26T00:45Z",
            "NARAHEM_SOURCE_URL": "https://source.example.invalid/nara-hem",
        }
        with patch.dict("os.environ", build):
            self.assertEqual(
                self.client.get("/api/version").json(),
                {
                    "channel": "dev",
                    "build": "591",
                    "commit": "c399c6c",
                    "built": "2026-10-26T00:45Z",
                    "source": "https://source.example.invalid/nara-hem",
                },
            )
        with patch.dict(
            "os.environ",
            {
                "NARAHEM_BUILD_CHANNEL": "local",
                "NARAHEM_BUILD_COMMIT": "not-a-commit",
                "NARAHEM_SOURCE_URL": "javascript:alert(1)",
            },
        ):
            version = self.client.get("/api/version").json()
            self.assertEqual(version["commit"], None)
            self.assertEqual(version["source"], None)

    def test_default_map_configuration_requires_login(self):
        self.assertEqual(self.client.get("/api/maps").status_code, 401)
        self.configure()
        self.assertEqual(
            self.client.get("/api/maps").json(), {"provider": "openstreetmap", "api_key": ""}
        )
        self.assertNotIn("googleapis.com", self.client.get("/").headers["content-security-policy"])

    def test_configured_google_maps_key_and_nonce(self):
        self.configure()
        with patch.dict(os.environ, {"NARAHEM_GOOGLE_MAPS_API_KEY": " synthetic-maps-key "}):
            application = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with TestClient(application, base_url=PUBLIC) as client:
            self.assertEqual(client.get("/api/maps").status_code, 401)
            client.cookies.update(self.client.cookies)
            result = client.get("/api/maps")
            self.assertEqual(result.json(), {"provider": "google", "api_key": "synthetic-maps-key"})
            self.assertEqual(result.headers["cache-control"], "no-store")
            page = client.get("/")
            nonce = re.search(r'<script nonce="([^"]+)"', page.text).group(1)
            self.assertIn(f"'nonce-{nonce}'", page.headers["content-security-policy"])
            self.assertIn("'strict-dynamic'", page.headers["content-security-policy"])
            self.assertNotIn("synthetic-maps-key", page.text)
            self.assertEqual(page.headers["referrer-policy"], "strict-origin-when-cross-origin")
            self.assertNotIn(f'nonce="{nonce}"', client.get("/").text)

    def test_whitespace_google_key_keeps_default_policy(self):
        with patch.dict(os.environ, {"NARAHEM_GOOGLE_MAPS_API_KEY": "   "}):
            application = create_app(self.db_url, self.path, PUBLIC, mail_worker=False)
        with TestClient(application, base_url=PUBLIC) as client:
            self.assertEqual(client.get("/").headers["referrer-policy"], "no-referrer")


class EmailAddressTests(unittest.TestCase):
    def test_normal_addresses_pass_and_odd_ones_are_refused(self):
        self.assertEqual(email_address(" Sam@Example.org "), "sam@example.org")
        self.assertEqual(email_address("a.b+c@mail.example.co.uk"), "a.b+c@mail.example.co.uk")
        for bad in ["sam", "sam@example", "sam@.org", "sam@example..org", "a b@example.org"]:
            with self.assertRaises(HTTPException):
                email_address(bad)
        with self.assertRaises(HTTPException):
            email_address("a" * 250 + "@example.org")

    def test_a_long_hostile_address_is_refused_quickly(self):
        started = time.monotonic()
        for value in ["a@" + "b." * 120 + "<", "a@" + "." * 240 + "b"]:
            with self.assertRaises(HTTPException):
                email_address(value)
        self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
