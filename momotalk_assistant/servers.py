from dataclasses import dataclass


@dataclass(frozen=True)
class Server:
    name: str
    profile: str
    tested: bool = True


SERVERS = {
    "com.YostarJP.BlueArchive": Server("碧蓝档案（日服）","jp"),
    "com.RoamingStar.BlueArchive": Server("蔚蓝档案（国服）","cn"),
    # Package name read from the user's installed application. Full gameplay
    # cannot be tested without an account; it shares the simplified-Chinese UI.
    "com.RoamingStar.BlueArchive.bilibili": Server("蔚蓝档案（Bilibili服）","cn",False),
    "com.nexon.bluearchive": Server("蔚蓝档案（国际服·繁中）","tw"),
}


def server_for(package: str) -> Server | None:
    return SERVERS.get(package)


def template_profile(package: str) -> str | None:
    server=server_for(package)
    return server.profile if server else None


def can_automate(package: str) -> bool:
    return package in SERVERS
