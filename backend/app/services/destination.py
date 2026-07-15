from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError
from ..config import get_settings
from ..models import DestinationRule


@dataclass(frozen=True)
class ResolvedDestination:
    original_host: str
    connect_host: str
    addresses: List[str]


def normalize_hostname(host: str) -> str:
    value = host.strip().rstrip(".")
    if not value or any(ord(char) < 33 for char in value):
        raise AppError(400, "INVALID_DESTINATION", "目标地址格式无效")
    try:
        return value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise AppError(400, "INVALID_DESTINATION", "目标地址格式无效") from exc


def _is_always_blocked(address: ipaddress._BaseAddress) -> bool:
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def _domain_matches(host: str, suffix: str) -> bool:
    suffix = suffix.lower().strip(".")
    return host == suffix or host.endswith("." + suffix)


def _address_allowed(
    host: str, address: ipaddress._BaseAddress, port: int, rules: Iterable[DestinationRule]
) -> bool:
    for rule in rules:
        if not rule.enabled or not (rule.port_min <= port <= rule.port_max):
            continue
        if rule.kind == "cidr":
            try:
                if address in ipaddress.ip_network(rule.value, strict=False):
                    return True
            except ValueError:
                continue
        elif rule.kind == "domain" and _domain_matches(host, rule.value):
            return True
    return False


async def resolve_destination(
    db: AsyncSession, host: str, port: int
) -> ResolvedDestination:
    normalized = normalize_hostname(host)
    rules = (
        await db.execute(select(DestinationRule).where(DestinationRule.enabled.is_(True)))
    ).scalars().all()

    try:
        direct_ip = ipaddress.ip_address(normalized.strip("[]"))
        addresses = [direct_ip]
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            results = await loop.getaddrinfo(
                normalized, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
        except socket.gaierror as exc:
            raise AppError(400, "DNS_FAILED", "无法解析目标服务器地址") from exc
        unique = {item[4][0] for item in results}
        addresses = [ipaddress.ip_address(value) for value in sorted(unique)]

    if not addresses:
        raise AppError(400, "DNS_FAILED", "目标服务器没有可用地址")
    for address in addresses:
        if _is_always_blocked(address):
            raise AppError(403, "DESTINATION_BLOCKED", "目标地址属于禁止访问的系统网段")
        if get_settings().enforce_destination_rules and not _address_allowed(
            normalized, address, port, rules
        ):
            raise AppError(403, "DESTINATION_NOT_ALLOWED", "目标地址或端口未获管理员授权")

    ordered = sorted(addresses, key=lambda item: (item.version != 4, str(item)))
    return ResolvedDestination(
        original_host=normalized,
        connect_host=str(ordered[0]),
        addresses=[str(item) for item in ordered],
    )
