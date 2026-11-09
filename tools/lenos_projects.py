"""Project path <-> patch directory mapping shared by the lenOS tools.

Everything under ``vendor/lenos/patches/<alias>/`` holds one project's patch
series. The alias is the project path with ``/`` replaced by ``_`` for most
projects; projects whose name contains a dash get an explicit alias so that
the directory name is a valid Python/Bash identifier-ish token.
"""
from __future__ import annotations

PROJECT_ALIASES = {
    "bionic": "bionic",
    "frameworks/base": "frameworks_base",
    "frameworks/native": "frameworks_native",
    "frameworks/opt/telephony": "frameworks_opt_telephony",
    "packages/apps/Settings": "packages_apps_Settings",
    "packages/apps/Updater": "packages_apps_Updater",
    "packages/apps/LineageParts": "packages_apps_LineageParts",
    "packages/apps/CellBroadcastReceiver": "packages_apps_CellBroadcastReceiver",
    "packages/apps/SetupWizard": "packages_apps_SetupWizard",
    "packages/apps/Seedvault": "packages_apps_Seedvault",
    "packages/modules/Connectivity": "packages_modules_Connectivity",
    "packages/modules/Permission": "packages_modules_Permission",
    "packages/modules/Wifi": "packages_modules_Wifi",
    "packages/modules/NetworkStack": "packages_modules_NetworkStack",
    "packages/providers/MediaProvider": "packages_providers_MediaProvider",
    "system/netd": "system_netd",
    "system/sepolicy": "system_sepolicy",
    "system/vold": "system_vold",
    "system/core": "system_core",
    "system/ca-certificates": "system_ca-certificates",
    "system/extras": "system_extras",
    "packages/services/Telephony": "packages_services_Telephony",
    "lineage-sdk": "lineage_sdk",
    "vendor/lineage": "vendor_lineage",
    "device/nothing/asteroids": "device_nothing_asteroids",
    "kernel/nothing/sm7635": "kernel_nothing_sm7635",
}


def alias_for(project: str) -> str:
    return PROJECT_ALIASES.get(project, project.replace("/", "_"))


def project_for(alias: str) -> str | None:
    for project, candidate in PROJECT_ALIASES.items():
        if candidate == alias:
            return project
    return None
