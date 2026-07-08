"""The "About / Authors" dialog (☰ menu → About Manoni).

A small dark modal in the same style as the cull dialogs: the app name +
version + description, who made it, the libraries it is built with, project
links, and a "Buy me a coffee" button. Modeled on CTkMaker's About window but
built in Manoni's plain-tk idiom (no CustomTkinter here).

Mixin on the Manoni window — uses the shared `self`, like the other ui mixins.
"""

import webbrowser
import tkinter as tk

from ..i18n import t


# --- Static content (kept here so the dialog body stays declarative) --------

APP_VERSION = "1.1.1"
AUTHOR_NAME = "Lasha Kandelaki"
AUTHOR_HANDLE = "kandelucky"

# Libraries Manoni is built on: (name, url, license). Shown in "Built with".
# Python + Tkinter aren't listed as links — they get a plain "written in"
# mention instead (see the header).
BUILT_WITH = [
    ("Pillow",       "https://pypi.org/project/Pillow/",    "HPND"),
    ("Lucide Icons", "https://lucide.dev",                  "ISC"),
]

# Project links: (label, url).
PROJECT_LINKS = [
    ("Source", "https://github.com/kandelucky/Manoni"),
    ("Issues", "https://github.com/kandelucky/Manoni/issues"),
]

# Where "Contact the developer" (Settings → Contact) writes to. The GitHub issues
# tracker above is the second channel offered on that tab.
DEV_EMAIL = "kandelucky.dev@gmail.com"
ISSUES_URL = "https://github.com/kandelucky/Manoni/issues"

BMC_URL = "https://buymeacoffee.com/Kandelucky_dev"
# Official Buy-Me-a-Coffee palette so the in-app button reads as the brand.
BMC_BG = "#FFDD00"
BMC_BG_HOVER = "#FFE54B"
BMC_FG = "#000000"


class AboutMixin:
    def _about_dialog(self):
        "Show the About / Authors modal (centered, dismiss with Esc / Close)."
        dlg = tk.Toplevel(self.root)
        dlg.title(t("About Manoni"))
        self._tw(dlg, bg="bg")
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = self._tw(tk.Frame(dlg, padx=28, pady=22), bg="bg")
        wrap.pack(fill="both", expand=True)

        # --- Header: name · version · description · author ------------------
        self._tw(tk.Label(wrap, text="Manoni",
                 font=("Segoe UI", 17, "bold")), bg="bg", fg="fg").pack()
        self._tw(tk.Label(wrap, text="v" + APP_VERSION,
                 font=("Segoe UI", 9)), bg="bg", fg="fg_dim").pack(pady=(2, 0))
        self._tw(tk.Label(wrap, text=t("A fast, simple photo browser, culler and editor."),
                 font=("Segoe UI", 9),
                 justify="center", wraplength=360), bg="bg", fg="fg_dim").pack(pady=(8, 0))

        author = "{label}: {name} · {handle}".format(
            label=t("Author"), name=AUTHOR_NAME, handle=AUTHOR_HANDLE)
        self._tw(tk.Label(wrap, text=author, font=("Segoe UI", 9)),
                 bg="bg", fg="fg").pack(pady=(10, 0))

        # A simple, link-free mention of the language it's written in.
        self._tw(tk.Label(wrap, text=t("Written in Python"),
                 font=("Segoe UI", 9)), bg="bg", fg="fg_dim").pack(pady=(2, 0))

        self._about_sep(wrap)

        # --- Built with -----------------------------------------------------
        self._about_heading(wrap, t("Built with"))
        for name, url, lic in BUILT_WITH:
            self._about_link_row(wrap, name, url, lic)

        self._about_sep(wrap)

        # --- Links ----------------------------------------------------------
        self._about_heading(wrap, t("Links"))
        for label, url in PROJECT_LINKS:
            self._about_link_row(wrap, label, url)

        # --- Buy me a coffee ------------------------------------------------
        self._tw(tk.Frame(wrap, height=18), bg="bg").pack()
        bmc = tk.Label(wrap, text=t("Buy me a coffee"), bg=BMC_BG, fg=BMC_FG,
                       font=("Segoe UI", 10, "bold"), padx=20, pady=8,
                       cursor="hand2")
        bmc.pack()
        bmc.bind("<Enter>", lambda e: bmc.configure(bg=BMC_BG_HOVER))
        bmc.bind("<Leave>", lambda e: bmc.configure(bg=BMC_BG))
        bmc.bind("<Button-1>", lambda e: webbrowser.open(BMC_URL))

        # --- Close ----------------------------------------------------------
        self._tw(tk.Frame(wrap, height=10), bg="bg").pack()
        close = self._tw(tk.Label(wrap, text=t("Close"), cursor="hand2",
                         padx=22, pady=7, font=("Segoe UI", 9)), bg="bar", fg="fg")
        close.pack()
        close.bind("<Enter>", lambda e: close.configure(bg=self.theme["hover"]))
        close.bind("<Leave>", lambda e: close.configure(bg=self.theme["bar"]))
        close.bind("<Button-1>", lambda e: dlg.destroy())

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: dlg.destroy())
        self._center_dialog(dlg)
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)

    # --- Small building blocks ---------------------------------------------

    def _about_sep(self, parent):
        "A faint full-width divider between sections."
        self._tw(tk.Frame(parent, height=1), bg="divider").pack(fill="x", pady=14)

    def _about_heading(self, parent, text):
        "A bold left-aligned section heading."
        self._tw(tk.Label(parent, text=text, anchor="w",
                 font=("Segoe UI", 9, "bold")), bg="bg", fg="fg").pack(
                     fill="x", pady=(0, 6))

    def _about_link_row(self, parent, label, url, lic=None):
        "One row: a name, the clickable underlined URL, and an optional license."
        row = self._tw(tk.Frame(parent), bg="bg")
        row.pack(fill="x", pady=1)
        self._tw(tk.Label(row, text=label + "  ", anchor="w",
                 font=("Segoe UI", 9)), bg="bg", fg="fg").pack(side="left")
        link = self._tw(tk.Label(row, text=url, cursor="hand2",
                        font=("Segoe UI", 9, "underline")), bg="bg", fg="accent")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        if lic:
            self._tw(tk.Label(row, text="  (" + lic + ")",
                     font=("Segoe UI", 8)), bg="bg", fg="fg_dim").pack(side="left")
