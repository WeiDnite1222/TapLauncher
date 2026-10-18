# TapLauncher

# There's no stable branch because this project is still under development.

## How to use?

#### Below are the project dependencies. Install them before use the launcher.

* `git` : [Website](https://git-scm.com/)
* `uv` : [Install Guide](https://docs.astral.sh/uv/getting-started/installation/)
* `python` : [Website](https://python.org) (Version 3.12 or above)

### Installation

1. Clone the project :
```bash
git clone https://repo.weispace.net/wei/Launcher.git TestLauncher
cd TestLauncher
```

2. Sync required packages :
```bash
uv sync
```

3. Run the launcher
> The launcher provide `--work-dir` argument to change the working directory. (If not provided, the launcher will use the application directory)
```bash
uv run python main.py
uv run python main.py --work-dir path_to_work_dir # With custom working directory
```

### Themes

You can customize the appearance of the launcher by adding a new theme to the `data/themes` under working directory.
Its `palette.toml` defines colors, and `styles/*.qss` customizes individual pages.
To create a variant, create a folder to `<work-dir>/data/themes/<your-theme-id>` and edit its `theme.toml`, palette,
and QSS files. Restart the launcher to discover the new theme. You can copy the built-in theme folder as the reference.
Missing QSS files use the default styles. See the [custom theme guide](resources/themes/README.md) for details.

## Troubleshooting
#### Unable to log in Microsoft account. Launcher throw error "Signing in to Minecraft services failed (HTTP 403). This account is not allowed to complete this step. Check Xbox privacy settings and account restrictions. Or check the client id has authorized to use Minecraft API."

Now this launcher has registered to Minecraft API. If you use custom client ID. Please make sure
 it is valid and registered to the API system (If not, see [this](https://forms.cloud.microsoft/Pages/ResponsePage.aspx?id=v4j5cvGGr0GRqy180BHbR-ajEQ1td1ROpz00KtS8Gd5UNVpPTkVLNFVROVQxNkdRMEtXVjNQQjdXVC4u))

### Missing Python packages (`ModuleNotFoundError`)

Run `uv sync` from the project directory, then start the launcher with `uv run python main.py`.
This uses the project's environment instead of a separate system Python installation.
If the same module is still missing, include its name and the full traceback when reporting the issue.

### Invalid working directory or permission errors

If you see `Specified work directory "..." does not exist or is not a directory`, create the directory first.
Use a directory that your account can write to, and quote paths containing spaces:

```bash
uv run python main.py --work-dir "path to an existing directory"
```

For `PermissionError`, `Unable to save version manifest`, or `Unable to save profile`, check the permissions
and available disk space for the working directory and any custom game directory.

### Login session expired (`HTTP 401`)

For `Authentication failed. Session may expire.` or a message saying the login session is invalid or expired,
sign in again from the account page and retry. If signing in still fails, check the accompanying server message.
For `HTTP 429`, wait before retrying; repeated login attempts can keep hitting the service's request limit.

### Xbox account errors (`XErr`)

The launcher displays an Xbox error code when the account needs additional setup:

| Error code | Suggested action |
| --- | --- |
| `2148916233` | Sign in to Xbox and create an Xbox profile, then retry. |
| `2148916235` | Check whether Xbox Live is available for the account's country or region. |
| `2148916236` / `2148916237` | Complete the adult or age verification requested on the Xbox website. |
| `2148916238` | Ask an adult to add the child account to a Microsoft family and allow Xbox access. |

### Connection, manifest, or download failures

For `Unable to fetch version manifest`, `Unable to fetch asset manifest`, `Some files failed to download`,
or authentication connection/time-out errors:

1. Check your internet connection and whether your proxy or firewall permits the launcher to connect.
2. Retry later if the remote service is temporarily unavailable.
3. If downloads or saves still fail, check available disk space and write permissions.
4. For a file hash mismatch, retry the download. If it repeats, include the affected file path and error details
   when reporting the issue.

### Java runtime missing or no longer available

For `No compatible Java runtime found (required major version: ...)` or
`No Java executable found for major version ...`, install or register a Java runtime matching the major version
shown in the error using the launcher's Java settings. A different major version may not satisfy the requirement.
If you see `Some runtimes are no longer available after last check`, check whether Java was moved or removed,
then refresh the runtime list or register its new executable path.

Links for available Java runtimes provider: 
[Oracle](https://www.java.com/download/)
[Eclipse Temurin](https://adoptium.net/)
[Azul Zulu](https://www.azul.com/downloads/)
[Microsoft Build of OpenJDK](https://www.microsoft.com/openjdk)

### No profile selected or profile data cannot be loaded

For `There is no profile is selected. Please create one first.`, create a profile and select it before launching.
For `Unable to load profile` or a missing profile-key error, back up the profile data before attempting repairs.
Try creating a separate profile for the same game version to check whether the problem is limited to the original profile.

### Game closes immediately after launch

Check the Minecraft Log window for the error preceding the exit message. An exit code alone does not identify the cause.
If you changed the profile's Java arguments, try restoring those arguments to their previous values.
For a modded profile, try a separate vanilla profile for the same Minecraft version to help isolate the failure.

### Collecting debug information

Run the launcher from a terminal with debug logging enabled:

```bash
uv run python main.py --debug --work-dir "path to an existing directory"
```

Use the same working directory as the failing session so that the launcher loads the same data.
When reporting a problem, include the launcher version, operating system, Minecraft version, steps to reproduce,
and the relevant terminal output or Minecraft Log messages. Remove any sensitive information such as access tokens,
refresh tokens, and sign-in codes before sharing logs.

## Misc

### TODO

- [ ] Add support for installing Forge/Neoforge mod loader.
- [ ] Design the home page.
- [ ] Add more custom settings.
- [ ] Add a usage guide.
- [ ] Add download mod from third party website support.
- [ ] Add a simple plugin system, allows customizing launcher behavior such as adding a new page or button.
