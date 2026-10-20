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
SETTINGS = Path(GLib.get_user_config_dir()) / "job-agent" / "settings.json"
REFRESH_DELAY_SECONDS = 8
POLL_SECONDS = 60
MAIL_PREVIEW = 4
ALL = "all"
AI_KIND = "ai_interview"

CSS = """
.chip {
  border-radius: 999px;
  padding: 4px 14px;
  min-height: 24px;
  background: none;
  box-shadow: inset 0 0 0 1px alpha(currentColor, 0.15);
  font-weight: 600;
}
.chip:hover {
  background: alpha(currentColor, 0.07);
}
.chip.selected {
  background: @accent_bg_color;
  color: @accent_fg_color;
  box-shadow: none;
}
.chip.urgent {
  color: @accent_color;
  box-shadow: inset 0 0 0 1px alpha(@accent_color, 0.5);
}
dropdown.picker > button {
  border-radius: 999px;
  padding: 4px 10px 4px 14px;
  min-height: 24px;
  font-weight: 600;
  background: none;
  box-shadow: inset 0 0 0 1px alpha(currentColor, 0.15);
}
dropdown.picker > button:hover {
  background: alpha(currentColor, 0.07);
}
"""

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
    "cv": (
        "CV did not pass review",
        (
            "A company on your flagship list. The CV written for the role failed the "
            "reviewer; read its findings, then retry, apply yourself, or skip."
        ),
    ),
    "stuck": (
        "The agent got stuck",
        "The form confused the agent. Apply yourself, try again later, or skip it.",
    ),
    "other": ("Check it yourself", "Anything else, such as an office in another city."),
}

MAIL_KINDS = {
    "interview": "Interviews",
    "offer": "Offers",
    "assessment": "Tests and tasks",
    "action_needed": "Asks you to do something",
    "recruiter": "Recruiters",
    "rejection": "Rejections",
    "confirmation": "Application received",
    AI_KIND: "AI interviews",
}


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(values: dict) -> None:
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(values, indent=2))
    except OSError:
        pass


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


def chip_button(label: str, selected: bool, urgent: bool, callback) -> Gtk.Button:
    chip = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    chip.add_css_class("chip")
    if selected:
        chip.add_css_class("selected")
    elif urgent:
        chip.add_css_class("urgent")
    chip.connect("clicked", lambda *_: callback())
    return chip


def picker_dropdown(values: list, labels: list, current: str, callback) -> Gtk.DropDown:
    picker = Gtk.DropDown(model=Gtk.StringList(strings=labels), valign=Gtk.Align.CENTER)
    picker.add_css_class("picker")
    picker.set_selected(values.index(current) if current in values else 0)
    picker.connect(
        "notify::selected", lambda widget, _spec: callback(values[widget.get_selected()])
    )
    return picker


def see_all_button(total: int, callback) -> Gtk.Button:
    button = Gtk.Button(label=f"See all {total}", valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.connect("clicked", lambda *_: callback())
    return button


def newest_first(rows: list, field: str) -> list:
    return sorted(rows, key=lambda row: row.get(field) or "", reverse=True)


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
        self.mail_kind = ALL
        self.mail_account = ALL
        self.held_kind = ALL
        self.held_site = ALL
        self.settings = load_settings()
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

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
        self.mail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.agent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.held_page = self.stack.add_titled_with_icon(
            scrolled_page(self.held_box), "held", "Needs you", "dialog-warning-symbolic"
        )
        self.stack.add_titled_with_icon(
            scrolled_page(self.sent_box), "sent", "Sent", "mail-send-symbolic"
        )
        self.mail_page = self.stack.add_titled_with_icon(
            scrolled_page(self.mail_box), "mail", "Mail", "mail-unread-symbolic"
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
        if self.changed("held", *self.held_state()):
            self.render_held()
        if self.changed("sent", self.data["sent"], self.data["sent_last_day"]):
            self.render_sent()
        if self.changed("mail", *self.mail_state()):
            self.render_mail()
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
        held = newest_first(self.data["held"], "held_at")
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
        sites = {row["site"]: row["site_name"] for row in held}
        if self.held_site not in (ALL, *sites):
            self.held_site = ALL
        if self.held_site != ALL:
            held = [row for row in held if row["site"] == self.held_site]
        totals: dict = {}
        for row in held:
            totals[row["kind"]] = totals.get(row["kind"], 0) + 1
        if self.held_kind != ALL and not totals.get(self.held_kind):
            self.held_kind = ALL
        self.held_box.append(self.held_filters(sites, totals))
        kinds = self.data["kinds"] if self.held_kind == ALL else [self.held_kind]
        for kind in kinds:
            rows = [row for row in held if row["kind"] == kind]
            if not rows:
                continue
            title, description = KINDS.get(kind, (kind, ""))
            group = Adw.PreferencesGroup(
                title=f"{title} ({len(rows)})", description=GLib.markup_escape_text(description)
            )
            shown = rows
            if self.held_kind == ALL and len(rows) > MAIL_PREVIEW:
                shown = rows[:MAIL_PREVIEW]
                group.set_header_suffix(
                    see_all_button(len(rows), lambda kind=kind: self.filter_held(kind=kind))
                )
            else:
                sendable = [row for row in rows if row["send_visible"]]
                if len(sendable) > 1:
                    group.set_header_suffix(
                        text_button(
                            f"Send all {len(sendable)}…",
                            lambda rows=sendable: self.send_rows(rows),
                        )
                    )
            for row in shown:
                group.add(self.held_row(row))
            self.held_box.append(group)

    def held_filters(self, sites: dict, totals: dict) -> Gtk.Widget:
        bar = Adw.WrapBox(child_spacing=8, line_spacing=8)
        if len(sites) > 1:
            values = [ALL, *sites]
            labels = ["All sites", *sites.values()]
            bar.append(
                picker_dropdown(
                    values, labels, self.held_site, lambda site: self.filter_held(site=site)
                )
            )
        chips = [(ALL, "All", sum(totals.values()))]
        chips += [
            (kind, KINDS.get(kind, (kind, ""))[0], totals[kind])
            for kind in self.data["kinds"]
            if totals.get(kind)
        ]
        for kind, label, total in chips:
            bar.append(
                chip_button(
                    f"{label}  {total}",
                    kind == self.held_kind,
                    False,
                    lambda kind=kind: self.filter_held(kind=kind),
                )
            )
        return bar

    def held_state(self) -> tuple:
        return self.data["held"], self.held_kind, self.held_site

    def filter_held(self, kind: str | None = None, site: str | None = None) -> None:
        if kind is not None:
            self.held_kind = kind
        if site is not None:
            self.held_site = site
        GLib.idle_add(self.rerender_held)

    def rerender_held(self) -> bool:
        if self.changed("held", *self.held_state()):
            self.render_held()
        return GLib.SOURCE_REMOVE

    def held_row(self, row: dict) -> Adw.ActionRow:
        site = row["site_name"] if self.held_site == ALL else ""
        subtitle = " · ".join(
            part for part in (row["employer"], site, local_time(row.get("held_at"))) if part
        )
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

    def render_mail(self) -> None:
        clear(self.mail_box)
        data = self.data.get("mail") or {}
        rows, counts, kinds = self.mail_view(data)
        rows = newest_first(rows, "received_at")
        accounts = data.get("accounts", [])
        urgent_kinds = data.get("urgent", [])
        urgent = sum(
            total
            for per_kind in counts.values()
            for kind, total in per_kind.items()
            if kind in urgent_kinds
        )
        self.mail_page.set_badge_number(urgent)
        self.mail_page.set_needs_attention(bool(urgent))
        if not accounts:
            self.mail_box.append(
                Adw.StatusPage(
                    icon_name="mail-unread-symbolic",
                    title="No mailbox connected",
                    description=(
                        "Add your Gmail addresses to HUNTER_MAIL_ACCOUNTS in core/.env, with an "
                        "app password or oauth after running mail_login, then restart the agent."
                    ),
                    vexpand=True,
                )
            )
            return
        if self.mail_account not in (ALL, *accounts):
            self.mail_account = ALL
        totals = self.mail_totals(counts)
        if self.mail_kind != ALL and not totals.get(self.mail_kind):
            self.mail_kind = ALL
        self.mail_box.append(self.mail_filters(data, accounts, totals, kinds))
        if self.mail_account != ALL:
            rows = [row for row in rows if row["account"] == self.mail_account]
        if not rows:
            self.mail_box.append(
                Adw.StatusPage(
                    icon_name="object-select-symbolic",
                    title="No job email to act on",
                    description=f"{data.get('sorted', 0)} emails sorted so far.",
                    vexpand=True,
                )
            )
            return
        if self.mail_kind != ALL:
            kinds = [self.mail_kind]
        for kind in kinds:
            matching = [row for row in rows if row["kind"] == kind]
            if not matching:
                continue
            total = totals.get(kind, len(matching))
            group = Adw.PreferencesGroup(title=f"{MAIL_KINDS.get(kind, kind)} ({total})")
            shown = matching
            if self.mail_kind == ALL and len(matching) > MAIL_PREVIEW:
                shown = matching[:MAIL_PREVIEW]
                group.set_header_suffix(
                    see_all_button(total, lambda kind=kind: self.filter_mail(kind=kind))
                )
            elif total > len(matching):
                group.set_description(f"The newest {len(matching)} of {total}.")
            for row in shown:
                group.add(self.mail_row(row))
            self.mail_box.append(group)

    def mail_totals(self, counts: dict) -> dict:
        totals: dict = {}
        for account, per_kind in counts.items():
            if self.mail_account not in (ALL, account):
                continue
            for kind, total in per_kind.items():
                totals[kind] = totals.get(kind, 0) + total
        return totals

    def mail_filters(self, data: dict, accounts: list, totals: dict, kinds: list) -> Gtk.Widget:
        bar = Adw.WrapBox(child_spacing=8, line_spacing=8)
        if len(accounts) > 1:
            bar.append(
                picker_dropdown(
                    [ALL, *accounts],
                    ["All inboxes", *accounts],
                    self.mail_account,
                    lambda account: self.filter_mail(account=account),
                )
            )
        chips = [(ALL, "All", sum(totals.values()))]
        chips += [
            (kind, MAIL_KINDS.get(kind, kind), totals[kind]) for kind in kinds if totals.get(kind)
        ]
        for kind, label, total in chips:
            bar.append(
                chip_button(
                    f"{label}  {total}",
                    kind == self.mail_kind,
                    kind in data.get("urgent", []),
                    lambda kind=kind: self.filter_mail(kind=kind),
                )
            )
        toggle = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER, margin_start=4)
        toggle.append(Gtk.Label(label="Count AI interviews", css_classes=["dim-label"]))
        switch = Gtk.Switch(active=self.count_ai(), valign=Gtk.Align.CENTER)
        switch.set_tooltip_text(
            "Off: emails about automated AI interviews (Anyone AI, micro1 and the like) move to "
            "their own chip and stop counting as interviews or in the tab badge."
        )
        switch.connect(
            "notify::active", lambda widget, _spec: self.set_count_ai(widget.get_active())
        )
        toggle.append(switch)
        bar.append(toggle)
        return bar

    def filter_mail(self, kind: str | None = None, account: str | None = None) -> None:
        if kind is not None:
            self.mail_kind = kind
        if account is not None:
            self.mail_account = account
        GLib.idle_add(self.rerender_mail)

    def rerender_mail(self) -> bool:
        if self.changed("mail", *self.mail_state()):
            self.render_mail()
        return GLib.SOURCE_REMOVE

    def mail_state(self) -> tuple:
        return self.data.get("mail"), self.mail_kind, self.mail_account, self.count_ai()

    def count_ai(self) -> bool:
        return self.settings.get("count_ai_interviews", True)

    def set_count_ai(self, active: bool) -> None:
        if active == self.count_ai():
            return
        self.settings["count_ai_interviews"] = active
        save_settings(self.settings)
        GLib.idle_add(self.rerender_mail)

    def mail_view(self, data: dict) -> tuple[list, dict, list]:
        rows = data.get("rows", [])
        counts = data.get("counts", {})
        kinds = data.get("kinds", [])
        if self.count_ai():
            return rows, counts, kinds
        adjusted: dict = {}
        for account, per_kind in counts.items():
            mine = dict(per_kind)
            moved = 0
            for kind, total in data.get("ai_counts", {}).get(account, {}).items():
                mine[kind] = mine.get(kind, 0) - total
                moved += total
            mine = {kind: total for kind, total in mine.items() if total > 0}
            if moved:
                mine[AI_KIND] = moved
            adjusted[account] = mine
        rows = [{**row, "kind": AI_KIND} if row.get("ai_interview") else row for row in rows]
        return rows, adjusted, [*kinds, AI_KIND]

    def mail_row(self, row: dict) -> Adw.ActionRow:
        account = row["account"] if self.mail_account == ALL else ""
        lines = [
            " · ".join(
                part
                for part in (
                    row["employer"] or row["sender"],
                    account,
                    local_time(row["received_at"]),
                )
                if part
            )
        ]
        if row.get("job_title"):
            lines.append(
                " · ".join(
                    part
                    for part in (
                        f"Applied: {row['job_title']}",
                        row.get("job_site"),
                        local_time(row.get("job_sent_at")),
                        f"sent with {row['job_cv']}" if row.get("job_cv") else "",
                    )
                    if part
                )
            )
        elif row.get("position"):
            lines.append(f"Position: {row['position']} · no application on record")
        if row["summary"]:
            lines.append(row["summary"])
        item = action_row(
            row["subject"] or "(no subject)", "\n".join(lines), subtitle_lines=5, title_lines=2
        )
        item.add_suffix(
            icon_button("mail-read-symbolic", "Open in Gmail", lambda: open_uri(row["gmail_url"]))
        )
        if row.get("vacancy_id"):
            item.add_suffix(
                icon_button(
                    "dialog-information-symbolic",
                    "What you applied to",
                    lambda: self.show_job(row["vacancy_id"]),
                )
            )
        item.add_suffix(
            icon_button("object-select-symbolic", "Done, hide it", lambda: self.mail_done(row))
        )
        return item

    def show_job(self, vacancy_id: int) -> None:
        def loaded(ok, out, err):
            if not ok:
                self.toast(last_line(err).removeprefix("CommandError: ") or "That did not work.")
                return
            try:
                job = json.loads(out)
            except ValueError:
                self.toast("The agent returned something unreadable.")
                return
            self.job_dialog(job).present(self)

        run(manage("agent_desk", "job", str(vacancy_id)), loaded)

    def job_dialog(self, job: dict) -> Adw.Dialog:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        group = Adw.PreferencesGroup(title=GLib.markup_escape_text(job["employer"] or ""))
        role = action_row(job["title"] or job["url"], job["url"], title_lines=2)
        role.add_suffix(
            icon_button("adw-external-link-symbolic", "Open the job", lambda: open_uri(job["url"]))
        )
        group.add(role)
        sent = " · ".join(
            part
            for part in (
                job["site_name"],
                f"sent {local_time(job['sent_at'])}" if job.get("sent_at") else "",
                f"match {job['score']}" if job.get("score") is not None else "",
            )
            if part
        )
        group.add(action_row("Applied through", sent))
        if job.get("cv_name"):
            cv = action_row("CV sent", job["cv_name"])
            if job.get("cv_path"):
                cv.add_suffix(
                    icon_button(
                        "document-open-symbolic",
                        "Open the CV",
                        lambda: open_uri(Gio.File.new_for_path(job["cv_path"]).get_uri()),
                    )
                )
            group.add(cv)
        if job.get("added"):
            group.add(action_row("Added to the CV for this job", job["added"], subtitle_lines=4))
        content.append(group)
        for title, text in (
            ("Cover letter", job.get("cover_letter")),
            ("Posting", job.get("text")),
        ):
            if not text:
                continue
            section = Adw.PreferencesGroup(title=title)
            label = Gtk.Label(
                label=text.strip(),
                wrap=True,
                selectable=True,
                xalign=0,
                margin_top=12,
                margin_bottom=12,
                margin_start=12,
                margin_end=12,
            )
            frame = Gtk.Frame(child=label)
            frame.add_css_class("card")
            section.add(frame)
            content.append(section)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(scrolled_page(content))
        return Adw.Dialog(
            title=job["title"] or "Job", child=view, content_width=720, content_height=780
        )

    def mail_done(self, row: dict) -> None:
        def done(ok, _out, err):
            if not ok:
                self.toast(last_line(err).removeprefix("CommandError: ") or "That did not work.")
                return
            mail = self.data.get("mail") or {}
            original = next(
                (other for other in mail.get("rows", []) if other["id"] == row["id"]), row
            )
            mail["rows"] = [other for other in mail.get("rows", []) if other["id"] != row["id"]]
            tallies = [mail.get("counts", {})]
            if original.get("ai_interview"):
                tallies.append(mail.get("ai_counts", {}))
            for tally in tallies:
                per_kind = tally.get(original["account"], {})
                if per_kind.get(original["kind"]):
                    per_kind[original["kind"]] -= 1
            self.render()

        run(manage("agent_desk", "mail-done", str(row["id"])), done)

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
