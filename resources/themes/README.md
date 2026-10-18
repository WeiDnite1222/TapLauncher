# Tutorial of creating custom themes

Each theme is a directory containing a `theme.toml` manifest and a
`palette.toml` color palette. Copy a built-in theme directory to `data/themes`,
rename the directory, then edit its display `name` and palette colors. The
directory name is stored as the theme ID. Restart the launcher after adding or
removing a theme directory.

Example:

```text
data/themes/
└── ocean/
    ├── theme.toml    # name and future theme metadata
    ├── palette.toml  # Qt palette colors
    ├── styles/       # optional QSS overrides, using default stylesheet names
    │   └── main.qss
    └── background.png  # optional asset for future theme features
```

Every key in the `palette.toml` `[palette]` table is required. Colors may use
any format accepted by Qt's `QColor`, including `#RRGGBB` and standard SVG
color names.

Stylesheets are loaded as UTF-8. Put overrides in the theme's `styles`
directory using the same filenames as `resources/styles` (for example,
`profile.qss`, `toolbar.qss`, `process_log.qss`, `progress_dialog.qss`, or
`test.qss`). Each missing file falls back to the default stylesheet.
Switching themes reloads stylesheets on existing windows and pages.

`main.qss` is applied to the whole application, including parentless message
boxes and detailed error dialogs. Customize `QMessageBox`, `QMessageBox QLabel`,
and `QMessageBox QPushButton` there; page styles such as `settings.qss` only
apply within that page.

Profile list rows contain separate `QLabel` children: a button's `color` does
not override those labels' explicit colors. Use
`QPushButton#profileItem QLabel[itemHovered="true"]` for dropdown hover text
and `QPushButton#manageProfileItem QLabel[itemChecked="true"]` for selected
management rows. These properties follow the button state and refresh the
label styles automatically.
