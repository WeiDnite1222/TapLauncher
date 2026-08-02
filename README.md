# TestLauncher (TapLauncher)

# Still thinking about its name...
# There's no stable branch because this project is still under development.


## How to use ?

#### Below are this project dependencies. Install them before use the launcher.

* `git` : [Website](https://git-scm.com/)
* `uv` : [Install Guide](https://docs.astral.sh/uv/getting-started/installation/)
* `python` : [Website](https://python.org) (Version 3.12 or above)

### Installation

1. Clone the project :
```
git clone https://repo.weispace.net/wei/Launcher.git TestLauncher
cd TestLauncher
```

2. Sync required packages :
```
uv sync
```

3. Run the launcher
> Is recommended to use `--work-dir` argument to change working directory. (If you don't like launcher mess up the 
> project folder)
```aiignore
mkdir launcherDir 
uv run python main.py --work-dir
```

## Troubleshooting
#### Unable to log in Microsoft account. Launcher throw error "Signing in to Minecraft services failed (HTTP 403). This account is not allowed to complete this step. Check Xbox privacy settings and account restrictions. Or check the client id has authorized to use Minecraft API."

This launcher's client id haven't registered to [Minecraft API](https://forms.cloud.microsoft/Pages/ResponsePage.aspx?id=v4j5cvGGr0GRqy180BHbR-ajEQ1td1ROpz00KtS8Gd5UNVpPTkVLNFVROVQxNkdRMEtXVjNQQjdXVC4u).
You may need to replace the client id that has permission to access Minecraft API in settings page (Settings>Account>Client ID)