from TapLauncher import Plugin, PluginContext

class ExperimentalFarm(Plugin):
    pass

def entry(context: PluginContext) -> None:
    context.data_dir.mkdir(parents=True, exist_ok=True)
    context.logger.info("Experimental Farm initialized")
    list_apis = context.get_api("launcher.apis.list")
    context.logger.debug("Available launcher APIs: %s", list_apis())