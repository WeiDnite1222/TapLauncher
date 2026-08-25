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
```bash
git clone https://repo.weispace.net/wei/Launcher.git TestLauncher
cd TestLauncher
```

2. Sync required packages :
```bash
uv sync
```

3. Run the launcher
> The launcher provide `--work-dir` argument to change working directory. (If not provided, launcher will use application directory)
```bash
uv run python main.py
uv run python main.py --work-dir path_to_work_dir # With custom working directory
```

## Troubleshooting
#### Unable to log in Microsoft account. Launcher throw error "Signing in to Minecraft services failed (HTTP 403). This account is not allowed to complete this step. Check Xbox privacy settings and account restrictions. Or check the client id has authorized to use Minecraft API."

Now this launcher have registered to Minecraft API. If you use custom client ID. Please make sure
its valid and registered to API system (If not, see [this](https://forms.cloud.microsoft/Pages/ResponsePage.aspx?id=v4j5cvGGr0GRqy180BHbR-ajEQ1td1ROpz00KtS8Gd5UNVpPTkVLNFVROVQxNkdRMEtXVjNQQjdXVC4u))