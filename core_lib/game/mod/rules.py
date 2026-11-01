from core_lib.game.mod.mod_core import PREFER_MOD_LIBRARY

MOD_LOADER_RULES = {
    "fabric": {
        "preferLibraryBy": PREFER_MOD_LIBRARY,
        "maven": {
            "group": "net.fabricmc",
            "name": "fabric-loader"
        }
    },
    "forge": {
        "preferLibraryBy": PREFER_MOD_LIBRARY,
        "maven": {
            "group": "net.minecraftforge",
            "name": "forge"
        }
    },
    "neoforge": {
        "preferLibraryBy": PREFER_MOD_LIBRARY,
        "maven": {
            "group": "net.neoforged",
            "name": "neoforge"
        }
    },
    "quilt": {
        "preferLibraryBy": PREFER_MOD_LIBRARY,
        "maven": {
            "group": "net.quiltmc",
            "name": "quilt-loader"
        }
    }
}

FORGE_LIKE_LOADERS = ["forge", "neoforge"]