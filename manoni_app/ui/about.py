"""The "About / Authors" dialog (☰ menu → About Manoni).

A small dark modal in the same style as the cull dialogs: the app name +
version + description, who made it, the libraries it is built with, project
links, and a "Buy me a coffee" button. Modeled on CTkMaker's About window but
built in Manoni's plain-tk idiom (no CustomTkinter here).

Mixin on the Manoni window — uses the shared `self`, like the other ui mixins.
"""

import webbrowser
import tkinter as tk

from ..config import BG, BAR, HOVER, ACCENT, FG, FG_DIM
from ..i18n import t


# --- Static content (kept here so the dialog body stays declarative) --------

APP_VERSION = "1.0"
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
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=BG, padx=28, pady=22)
        wrap.pack(fill="both", expand=True)

        # --- Header: name · version · description · author ------------------
        tk.Label(wrap, text="Manoni", bg=BG, fg=FG,
                 font=("Segoe UI", 17, "bold")).pack()
        tk.Label(wrap, text="v" + APP_VERSION, bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(pady=(2, 0))
        tk.Label(wrap, text=t("A fast, simple dark photo browser and culler."),
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 9),
                 justify="center", wraplength=360).pack(pady=(8, 0))

        author = "{label}: {name} · {handle}".format(
            label=t("Author"), name=AUTHOR_NAME, handle=AUTHOR_HANDLE)
        tk.Label(wrap, text=author, bg=BG, fg=FG, font=("Segoe UI", 9)).pack(
            pady=(10, 0))

        # A simple, link-free mention of the language it's written in.
        tk.Label(wrap, text=t("Written in Python"), bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(pady=(2, 0))

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
        tk.Frame(wrap, bg=BG, height=18).pack()
        bmc = tk.Label(wrap, text=t("Buy me a coffee"), bg=BMC_BG, fg=BMC_FG,
                       font=("Segoe UI", 10, "bold"), padx=20, pady=8,
                       cursor="hand2")
        bmc.pack()
        bmc.bind("<Enter>", lambda e: bmc.configure(bg=BMC_BG_HOVER))
        bmc.bind("<Leave>", lambda e: bmc.configure(bg=BMC_BG))
        bmc.bind("<Button-1>", lambda e: webbrowser.open(BMC_URL))

        # --- Close ----------------------------------------------------------
        tk.Frame(wrap, bg=BG, height=10).pack()
        close = tk.Label(wrap, text=t("Close"), bg=BAR, fg=FG, cursor="hand2",
                         padx=22, pady=7, font=("Segoe UI", 9))
        close.pack()
        close.bind("<Enter>", lambda e: close.configure(bg=HOVER))
        close.bind("<Leave>", lambda e: close.configure(bg=BAR))
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
        tk.Frame(parent, bg=HOVER, height=1).pack(fill="x", pady=14)

    def _about_heading(self, parent, text):
        "A bold left-aligned section heading."
        tk.Label(parent, text=text, bg=BG, fg=FG, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(0, 6))

    def _about_link_row(self, parent, label, url, lic=None):
        "One row: a name, the clickable underlined URL, and an optional license."
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=label + "  ", bg=BG, fg=FG, anchor="w",
                 font=("Segoe UI", 9)).pack(side="left")
        link = tk.Label(row, text=url, bg=BG, fg=ACCENT, cursor="hand2",
                        font=("Segoe UI", 9, "underline"))
        link.pack(side="left")
        link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        if lic:
            tk.Label(row, text="  (" + lic + ")", bg=BG, fg=FG_DIM,
                     font=("Segoe UI", 8)).pack(side="left")
