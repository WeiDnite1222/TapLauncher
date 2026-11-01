from TapLauncher import PluginContext
from .log4j import Log4jPlugin

def entry(context: PluginContext) -> None:
    plugin = Log4jPlugin(context)
    context.on_cleanup(plugin.cleanup)
    context.override_api("launcher.game.launch.extra_arguments", plugin.extra_arguments)
    context.override_api("launcher.process_log.output", plugin.output)
    context.override_api("launcher.process_log.create_widget", plugin.create_widget)
    context.logger.info("Log4j hooks initialized")
