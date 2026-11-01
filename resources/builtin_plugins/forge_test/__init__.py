from TapLauncher import PluginContext, core

def entry(context: PluginContext) -> None:
    # init
    context.data_dir.mkdir(parents=True, exist_ok=True)
    logger = context.logger
    context.logger.info("Forge test initialized")

    # Start
    versions = core.fetch_forge_versions()
    logger.info(f"Found {len(versions)} versions")
