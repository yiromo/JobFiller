import json
import shlex
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

APP_ID = "kz.jobfiller.Agent"
SERVICE = "job-filler-hunter.service"
REPO = Path(__file__).resolve().parents[1]
CORE_SRC = REPO / "core" / "src"
STATUS_DIR = CORE_SRC / "data" / "hunter"
TASK_LOG = Path(GLib.get_user_cache_dir()) / "job-agent" / "task.log"
REFRESH_DELAY_SECONDS = 8
POLL_SECONDS = 60

KINDS = {
    "captcha": (
        "Captcha",
        (
            "The site asked for a captcha. Send hh.kz jobs in a visible browser and solve it "
            "there; apply to the rest yourself."
        ),
    ),
    "unconfirmed": (
        "Not sure it was sent",
        (
            "The agent pressed Submit, but the site never confirmed it. Check your email or the "
            "site, then tell the agent what happened."
        ),
    ),
    "question": (
        "Questions only you can answer",
        "Legal confirmations, consents, or questions with no option matching your saved answers.",
    ),
    "account": (
        "Needs an account",
        "The employer wants you to sign up or log in. The agent never creates accounts.",
    ),
    "stuck": (
        "The agent got stuck",
        "The form confused the agent. Apply yourself, try again later, or skip it.",
    ),
    "other": ("Check it yourself", "Anything else, such as an office in another city."),
}


def uv_path() -> str:
    return shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")


def manage(*args: str) -> list[str]:
    return [uv_path(), "run", "python", "manage.py", *args]


def local_time(value: str | None, with_day: bool = True) -> str:
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return value
    if not with_day or moment.date() == datetime.now(UTC).astimezone().date():
        return moment.strftime("%H:%M")
    return moment.strftime("%b %d, %H:%M")


def last_line(text: str) -> str:
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def run(argv: list[str], done, cwd: Path = CORE_SRC) -> None:
    launcher = Gio.SubprocessLauncher.new(
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    )
    launcher.set_cwd(str(cwd))
    try:
        process = launcher.spawnv(argv)
    except GLib.Error as error:
        done(False, "", error.message)
        return

    def finished(source, result):
        try:
            _, out, err = source.communicate_utf8_finish(result)
        except GLib.Error as error:
            done(False, "", error.message)
            return
        done(source.get_successful(), out or "", err or "")

    process.communicate_utf8_async(None, None, finished)


def run_detached(lines: list[str], done) -> None:
    TASK_LOG.parent.mkdir(parents=True, exist_ok=True)
    script = "\n".join([f"exec >{shlex.quote(str(TASK_LOG))} 2>&1", *lines])
    launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.NONE)
    launcher.set_cwd(str(CORE_SRC))
    try:
        process = launcher.spawnv(["sh", "-c", script])
    except GLib.Error as error:
        done(False, error.message)
        return

    def finished(source, result):
        try:
            source.wait_finish(result)
        except GLib.Error as error:
            done(False, error.message)
            return
        try:
            output = TASK_LOG.read_text(errors="replace")
        except OSError:
            output = ""
        done(source.get_successful(), output)

    process.wait_async(None, finished)


def open_uri(uri: str) -> None:
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error:
        pass


def icon_button(icon: str, tooltip: str, callback) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.connect("clicked", lambda *_: callback())
    return button


def text_button(label: str, callback, suggested: bool = False) -> Gtk.Button:
    button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    if suggested:
        button.add_css_class("suggested-action")
    button.connect("clicked", lambda *_: callback())
    return button


def action_row(title: str, subtitle: str = "", **props) -> Adw.ActionRow:
    return Adw.ActionRow(
        title=GLib.markup_escape_text(title),
        subtitle=GLib.markup_escape_text(subtitle),
        **props,
    )


def clear(box: Gtk.Box) -> None:
    child = box.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        box.remove(child)
        child = following


def scrolled_page(content: Gtk.Widget) -> Gtk.ScrolledWindow:
    clamp = Adw.Clamp(maximum_size=860, child=content)
    clamp.set_margin_top(18)
    clamp.set_margin_bottom(24)
    clamp.set_margin_start(12)
    clamp.set_margin_end(12)
    return Gtk.ScrolledWindow(child=clamp, vexpand=True)


class AgentWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Job agent", default_width=820, default_height=860)
        self.data: dict = {}
        self.busy = False
        self.loading = False
        self.service_active = False
        self.refresh_pending = 0
        self.rendered: dict = {}
        self.banner_action = lambda: None

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self.stack = Adw.ViewStack()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        )
        self.refresh_button = icon_button("view-refresh-symbolic", "Refresh", self.refresh)
        header.pack_start(self.refresh_button)
        self.spinner = Adw.Spinner(visible=False)
        self.busy_label = Gtk.Label(visible=False, css_classes=["dim-label"])
        busy = Gtk.Box(spacing=8)
        busy.append(self.spinner)
        busy.append(self.busy_label)
        header.pack_end(busy)
        view.add_top_bar(header)

        self.banner = Adw.Banner()
        self.banner.connect("button-clicked", lambda *_: self.banner_action())
        view.add_top_bar(self.banner)
        view.set_content(self.stack)

        self.held_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.sent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.agent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.held_page = self.stack.add_titled_with_icon(
            scrolled_page(self.held_box), "held", "Needs you", "dialog-warning-symbolic"
        )
        self.stack.add_titled_with_icon(
            scrolled_page(self.sent_box), "sent", "Sent", "mail-send-symbolic"
        )
        self.stack.add_titled_with_icon(
            scrolled_page(self.agent_box), "agent", "Agent", "emblem-system-symbolic"
        )
        self.held_box.append(Adw.Spinner(height_request=48))

        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        self.monitor = Gio.File.new_for_path(str(STATUS_DIR)).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None
        )
        self.monitor.connect("changed", self.status_changed)
        GLib.timeout_add_seconds(POLL_SECONDS, self.poll)
        self.refresh()

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=5))

    def status_changed(self, _monitor, file, other, _event) -> None:
        names = {file.get_basename() if file else "", other.get_basename() if other else ""}
        if "status.json" not in names or self.refresh_pending:
            return
        self.refresh_pending = GLib.timeout_add_seconds(REFRESH_DELAY_SECONDS, self.delayed)

    def delayed(self) -> bool:
        self.refresh_pending = 0
        self.refresh()
        return GLib.SOURCE_REMOVE

    def poll(self) -> bool:
        self.refresh()
        return GLib.SOURCE_CONTINUE

    def refresh(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.refresh_button.set_sensitive(False)

        def listed(ok, out, err):
            self.loading = False
            self.refresh_button.set_sensitive(True)
            if not ok:
                self.toast(f"Could not read the agent: {last_line(err) or 'unknown error'}")
                return
            try:
                self.data = json.loads(out)
            except ValueError:
                self.toast("The agent returned something unreadable.")
                return
            self.check_service()

        run(manage("agent_desk", "list"), listed)

    def check_service(self) -> None:
        def checked(ok, _out, _err):
            self.service_active = ok
            self.render()

        run(["systemctl", "--user", "is-active", "--quiet", SERVICE], checked)

    def set_busy(self, text: str) -> None:
        self.busy = bool(text)
        self.spinner.set_visible(self.busy)
        self.busy_label.set_visible(self.busy)
        self.busy_label.set_label(text)
        self.render()

    def changed(self, section: str, *parts) -> bool:
        key = json.dumps(parts, sort_keys=True, default=str)
        if self.rendered.get(section) == key:
            return False
        self.rendered[section] = key
        return True

    def render(self) -> None:
        if not self.data:
            return
        self.render_banner()
        if self.changed("held", self.data["held"]):
            self.render_held()
        if self.changed("sent", self.data["sent"], self.data["sent_last_day"]):
            self.render_sent()
        if self.changed(
            "agent",
            self.data["agent"],
            self.data["counts"],
            self.data["sites"],
            self.data["logged_out"],
            self.service_active,
            self.busy,
        ):
            self.render_agent()

    def render_banner(self) -> None:
        agent = self.data["agent"]
        names = {site["site"]: site["name"] for site in self.data["sites"]}
        logged_out = self.data["logged_out"]
        self.banner_action = lambda: None
        if logged_out:
            site = logged_out[0]
            self.banner.set_title(f"{names.get(site, site)} is logged out, so the agent skips it.")
            self.banner.set_button_label("Log in")
            self.banner_action = lambda: self.log_in(site)
        elif not self.service_active:
            self.banner.set_title("The agent is paused.")
            self.banner.set_button_label("Resume")
            self.banner_action = lambda: self.set_service(True)
        elif paused := [site for site in self.data["sites"] if site.get("paused_until")]:
            until = local_time(paused[0]["paused_until"], with_day=False)
            attempt = paused[0].get("attempt") or [1, 1]
            self.banner.set_title(
                f"{paused[0]['name']} asked for a captcha; trying again at {until} "
                f"(wait {attempt[0]} of {attempt[1]})."
            )
            self.banner.set_button_label(None)
        elif agent.get("last_error"):
            self.banner.set_title(GLib.markup_escape_text(agent["last_error"][:200]))
            self.banner.set_button_label(None)
        else:
            self.banner.set_revealed(False)
            return
        self.banner.set_revealed(True)

    def render_held(self) -> None:
        clear(self.held_box)
        held = self.data["held"]
        self.held_page.set_badge_number(len(held))
        self.held_page.set_needs_attention(bool(held))
        if not held:
            self.held_box.append(
                Adw.StatusPage(
                    icon_name="object-select-symbolic",
                    title="Nothing needs you",
                    description="Jobs the agent cannot finish alone show up here.",
                    vexpand=True,
                )
            )
            return
        for kind in self.data["kinds"]:
            rows = [row for row in held if row["kind"] == kind]
            if not rows:
                continue
            title, description = KINDS.get(kind, (kind, ""))
            group = Adw.PreferencesGroup(
                title=f"{title} ({len(rows)})", description=GLib.markup_escape_text(description)
            )
            sendable = [row for row in rows if row["send_visible"]]
            if len(sendable) > 1:
                group.set_header_suffix(
                    text_button(
                        f"Send all {len(sendable)}…", lambda rows=sendable: self.send_rows(rows)
                    )
                )
            for row in rows:
                group.add(self.held_row(row))
            self.held_box.append(group)

    def held_row(self, row: dict) -> Adw.ActionRow:
        subtitle = " · ".join(part for part in (row["employer"], row["site_name"]) if part)
        note = "" if row["kind"] == "captcha" else row["note"]
        item = action_row(
            row["title"] or row["url"],
            f"{subtitle}\n{note}" if note else subtitle,
            subtitle_lines=3,
            title_lines=2,
        )
        if row["kind"] == "unconfirmed":
            item.add_suffix(
                text_button("It was sent", lambda: self.resolve(row, "applied"), suggested=True)
            )
        elif row["send_visible"]:
            item.add_suffix(text_button("Send…", lambda: self.send_rows([row]), suggested=True))
        item.add_suffix(
            icon_button("adw-external-link-symbolic", "Open the job", lambda: open_uri(row["url"]))
        )
        if row["kind"] != "unconfirmed":
            item.add_suffix(
                icon_button(
                    "object-select-symbolic",
                    "I applied myself",
                    lambda: self.resolve(row, "applied"),
                )
            )
        item.add_suffix(self.more_menu(row))
        return item

    def more_menu(self, row: dict) -> Gtk.MenuButton:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        popover = Gtk.Popover(child=box)

        def entry(label: str, callback) -> None:
            button = Gtk.Button(label=label)
            button.add_css_class("flat")
            button.get_child().set_halign(Gtk.Align.START)

            def clicked(*_):
                popover.popdown()
                callback()

            button.connect("clicked", clicked)
            box.append(button)

        if row["kind"] == "unconfirmed":
            entry("Not sent, try again", lambda: self.resolve(row, "retry", not_sent=True))
        else:
            entry("Try again", lambda: self.resolve(row, "retry"))
        entry("Skip this job", lambda: self.resolve(row, "skipped"))
        if row["screenshot"]:
            entry(
                "Show what the agent saw",
                lambda: open_uri(Gio.File.new_for_path(row["screenshot"]).get_uri()),
            )
        button = Gtk.MenuButton(
            icon_name="view-more-symbolic",
            popover=popover,
            valign=Gtk.Align.CENTER,
            tooltip_text="More",
        )
        button.add_css_class("flat")
        return button

    def render_sent(self) -> None:
        clear(self.sent_box)
        sent = self.data["sent"]
        group = Adw.PreferencesGroup(
            title="Sent applications",
            description=(
                f"{self.data['sent_last_day']} of {self.data['daily_cap']} allowed "
                "in the last 24 hours."
            ),
        )
        if not sent:
            group.add(Adw.ActionRow(title="Nothing sent yet."))
        for row in sent:
            subtitle = " · ".join(
                part
                for part in (row["employer"], row["site_name"], local_time(row["applied_at"]))
                if part
            )
            item = action_row(row["title"] or row["url"], subtitle, title_lines=2)
            url = row["url"]
            item.add_suffix(
                icon_button(
                    "adw-external-link-symbolic", "Open the job", lambda url=url: open_uri(url)
                )
            )
            group.add(item)
        self.sent_box.append(group)

    def status_text(self) -> str:
        agent = self.data["agent"]
        if not self.service_active:
            return "Paused"
        if agent.get("phase") == "running":
            started = local_time(agent.get("cycle_started_at"), with_day=False)
            return f"Applying now (since {started})" if started else "Applying now"
        if agent.get("phase") == "sleeping":
            return f"Waiting; next run at {local_time(agent.get('next_cycle_at'), with_day=False)}"
        return "Starting"

    def render_agent(self) -> None:
        clear(self.agent_box)
        group = Adw.PreferencesGroup(title="Agent")
        status = action_row("Status", self.status_text())
        switch = Gtk.Switch(
            active=self.service_active, valign=Gtk.Align.CENTER, sensitive=not self.busy
        )
        switch.connect("state-set", self.switch_toggled)
        status.add_suffix(switch)
        status.set_activatable_widget(switch)
        group.add(status)
        counts = self.data["counts"]
        group.add(
            Adw.ActionRow(
                title="Sent in the last 24 hours",
                subtitle=f"{self.data['sent_last_day']} of {self.data['daily_cap']}",
            )
        )
        group.add(Adw.ActionRow(title="Waiting to apply", subtitle=f"{counts['ready']} jobs"))
        self.agent_box.append(group)

        logins = Adw.PreferencesGroup(
            title="Logins", description="Each site keeps its own browser profile."
        )
        for site in self.data["sites"]:
            if site["site"] in self.data["logged_out"]:
                subtitle = "Logged out; log in again"
            elif site.get("paused_until"):
                until = local_time(site["paused_until"], with_day=False)
                subtitle = f"Asked for a captcha; trying again at {until}"
            elif site["saved_at"]:
                saved = (
                    datetime.fromtimestamp(site["saved_at"], UTC)
                    .astimezone()
                    .strftime("%b %d, %H:%M")
                )
                subtitle = f"Session saved {saved}"
            else:
                subtitle = "Never logged in"
            row = action_row(site["name"], subtitle)
            button = text_button("Log in…", lambda name=site["site"]: self.log_in(name))
            button.set_sensitive(not self.busy)
            row.add_suffix(button)
            logins.add(row)
        self.agent_box.append(logins)

        activity = Adw.PreferencesGroup(title="Recent activity")
        text = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
        text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text.set_top_margin(8)
        text.set_bottom_margin(8)
        text.set_left_margin(8)
        text.set_right_margin(8)
        text.get_buffer().set_text(
            "\n".join(reversed(self.data["agent"]["recent_log"])) or "No activity."
        )
        frame = Gtk.Frame(
            child=Gtk.ScrolledWindow(child=text, min_content_height=320, max_content_height=320)
        )
        activity.add(frame)
        self.agent_box.append(activity)

    def switch_toggled(self, _switch, active: bool) -> bool:
        if active != self.service_active:
            self.set_service(active)
        return True

    def resolve(self, row: dict, action: str, not_sent: bool = False) -> None:
        argv = manage("agent_desk", "resolve", str(row["id"]), action)
        if not_sent:
            argv.append("--not-sent")
        messages = {
            "applied": "Marked as applied.",
            "skipped": "Skipped.",
            "retry": "Back in the queue for the next run.",
        }

        def resolved(ok, _out, err):
            if not ok:
                self.toast(last_line(err).removeprefix("CommandError: ") or "That did not work.")
                return
            self.toast(messages[action])
            self.data["held"] = [held for held in self.data["held"] if held["id"] != row["id"]]
            self.render()
            self.refresh()

        run(argv, resolved)

    def mid_run(self) -> bool:
        return self.service_active and self.data.get("agent", {}).get("phase") == "running"

    def confirm(self, heading: str, body: str, label: str, proceed) -> None:
        if self.mid_run():
            body += (
                "\n\nThe agent is in the middle of a run. Stopping it now can interrupt an "
                "application it is sending. Waiting until it finishes is safer."
            )
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("go", label)
        dialog.set_response_appearance(
            "go",
            Adw.ResponseAppearance.DESTRUCTIVE
            if self.mid_run()
            else Adw.ResponseAppearance.SUGGESTED,
        )
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: proceed() if response == "go" else None)
        dialog.present(self)

    def set_service(self, active: bool) -> None:
        def apply():
            verb = "start" if active else "stop"
            self.set_busy("Resuming…" if active else "Pausing…")

            def done(ok, _out, err):
                self.set_busy("")
                if not ok:
                    self.toast(last_line(err) or f"Could not {verb} the agent.")
                self.check_service()

            run(["systemctl", "--user", verb, SERVICE], done)

        if active:
            apply()
            return
        self.confirm(
            "Pause the agent?",
            "It stops looking for and applying to jobs until you resume it.",
            "Pause",
            apply,
        )

    def with_agent_paused(self, label: str, commands: list[list[str]], finished) -> None:
        was_active = self.service_active
        self.set_busy(label)
        lines = ["status=0"]
        if was_active:
            lines.append(f"systemctl --user stop {SERVICE} || exit 1")
        lines += [
            f"HUNTER_NOTIFY_DESKTOP=false {shlex.join(argv)} || status=$?" for argv in commands
        ]
        if was_active:
            lines.append(f"systemctl --user start {SERVICE}")
        lines.append("exit $status")

        def done(ok, output):
            self.set_busy("")
            finished(ok, output)
            self.check_service()
            self.refresh()

        run_detached(lines, done)

    def send_rows(self, rows: list[dict]) -> None:
        if self.busy:
            self.toast("Wait for the current task to finish.")
            return
        single = len(rows) == 1

        def go():
            def finished(ok, output):
                sent = output.count("  APPLIED ")
                if sent:
                    self.toast(f"Sent {sent} of {len(rows)}.")
                elif "Daily cap: 0" in output:
                    self.toast("The daily cap is reached; nothing was sent.")
                else:
                    self.toast(last_line(output) or "Nothing was sent.")

            self.with_agent_paused(
                "Sending in a visible browser…",
                [
                    manage("hunt", "--apply", "--headed", "--vacancy", row["external_id"])
                    for row in rows
                ],
                finished,
            )

        what = rows[0]["title"] if single else f"{len(rows)} jobs, one after another"
        self.confirm(
            "Send in a visible browser?",
            f"{what}\n\nThe agent pauses and a browser window opens on "
            f"{rows[0]['site_name']}. If it asks for a captcha, solve it in that window and the "
            "response is sent. The agent resumes afterwards, even if you close this app.",
            "Send",
            go,
        )

    def log_in(self, site: str) -> None:
        if self.busy:
            self.toast("Wait for the current task to finish.")
            return
        name = next((s["name"] for s in self.data["sites"] if s["site"] == site), site)

        def go():
            def finished(ok, output):
                self.toast(f"{name} session saved." if ok else last_line(output) or "Login failed.")

            self.with_agent_paused(
                f"Waiting for you to log in to {name}…", [manage("hunter_login", site)], finished
            )

        self.confirm(
            f"Log in to {name}?",
            "The agent pauses and a browser window opens. Log in there; the window closes by "
            "itself once you are in, and the agent resumes, even if you close this app.",
            "Open browser",
            go,
        )


class AgentApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = AgentWindow(self)
        else:
            self.window.refresh()
        self.window.present()


def main() -> int:
    GLib.set_application_name("Job agent")
    Gtk.Window.set_default_icon_name(APP_ID)
    return AgentApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
