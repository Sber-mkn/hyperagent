"""Геолокация по IP — определяет страну, город и координаты по IP-адресу."""

import httpx
from typing import Optional
from agent.tools.registry import tool


def ip_geolocation(ip: str = None) -> dict:
    """Определить геолокацию по IP.

    По умолчанию определяется адрес самого агента (через публичный сервис).

    Returns:
        dict с полями: country, region, city, latitude, longitude, asn, query, status.
    """
    if ip is None:
        # Определяем текущий IP через публичный сервис
        try:
            resp = httpx.get("https://ipapi.co/json/", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return {
                "country": data.get("country_name", ""),
                "region": data.get("region"),
                "city": data.get("city", ""),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "asn": data.get("org", ""),
                "query": f"{data['ip']}",
                "status": 0,
            }
        except Exception:
            pass

    # Fallback через ip-api.com (бесплатный)
    try:
        resp = httpx.get(f"https://ipapi.co/{ip}/json/", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "country": data.get("country_name", ""),
            "region": data.get("region"),
            "city": data.get("city", ""),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "asn": data.get("org", ""),
            "query": ip,
            "status": 0,
        }
    except Exception:
        pass

    return {
        "country": "",
        "region": "",
        "city": "",
        "latitude": None,
        "longitude": None,
        "asn": "",
        "query": ip or "",
        "status": 6,
    }


@tool
def geolocation(ip: Optional[str] = None) -> dict:
    """Определить геолокацию по IP-адресу.

    Args:
        ip (Optional[str]): IP-адрес для проверки. Если не указан — определяется адрес самого агента.

    Returns:
        dict с полями country, region, city, latitude, longitude и т.д.

    Examples:
        >>> geolocation()
        {'country': 'United States', 'city': 'San Francisco', ...}

        >>> geolocation('8.8.8.8')
        {'country': 'United States', 'city': 'Mountain View', ...}
    """
    return ip_geolocation(ip)
